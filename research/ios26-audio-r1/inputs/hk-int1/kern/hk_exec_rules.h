/*
 * hk_deny and hk_env: the rule text and its parser. No kernel types: the host test includes this.
 *
 *   deny list   NAME[,NAME...]
 *   env rules   PROG[+PROG...]:KEY=VAL[;KEY=VAL...][,PROG...:KEY=VAL...]
 *
 * NAME and PROG are the last component of the path being executed. A rule's text may hold ':' in a value
 * (DYLD_INSERT_LIBRARIES=/a.dylib:/b.dylib), but not ',' or ';', which end the variable. '~' in a value stands
 * for a space, as boot-args end at spaces.
 */
#ifndef HK_EXEC_RULES_H
#define HK_EXEC_RULES_H

#define HK_RULES_MAX    1024            /* each text, with its NUL. More than the whole command line */
#define HK_VAR_MAX      384             /* one KEY=VAL, with its NUL */

/* 1 if the list holds exactly this name. */
static inline int
hk_list_has(const char *list, const char *name, unsigned long namelen)
{
	const char *p = list;

	if (namelen == 0) {
		return 0;
	}
	while (*p != '\0') {
		const char *w = p;
		unsigned long i;

		while (*p != '\0' && *p != ',') {
			p++;
		}
		if ((unsigned long)(p - w) == namelen) {
			for (i = 0; i < namelen && w[i] == name[i]; i++) {
				;
			}
			if (i == namelen) {
				return 1;
			}
		}
		if (*p == ',') {
			p++;
		}
	}
	return 0;
}

/*
 * hk_adaptive: a job launchd starts as standard or with no type becomes adaptive, the type 23G90 itself gives biomed
 * and modelcatalogd: background unless a client's XPC boost is in flight, and its threads can be turnstile-boosted out
 * of it. So a client waiting on it doesn't stay behind it. Interactive, background, app and driver types are left alone.
 */
static inline int
hk_apptype_for_listed(int apptype, int mask, int standard, int adaptive)
{
	int type = apptype & mask;

	if (type != 0 && type != standard) {
		return apptype;
	}
	return (apptype & ~mask) | adaptive;
}

/* Well formed? Returns NULL, or says what is wrong. */
static inline const char *
hk_deny_check(const char *list)
{
	const char *p = list;

	if (*p == '\0') {
		return (const char *)0;
	}
	while (1) {
		const char *w = p;

		while (*p != '\0' && *p != ',') {
			if (*p == '/' || *p == ' ' || *p == ':' || *p == ';' || *p == '=') {
				return "name holds / space : ; or =";
			}
			p++;
		}
		if (p == w) {
			return "empty name";
		}
		if (p - w > 255) {
			return "name over 255 bytes";
		}
		if (*p == '\0') {
			return (const char *)0;
		}
		p++;
	}
}

static inline const char *
hk_env_check(const char *rules)
{
	const char *p = rules;

	if (*p == '\0') {
		return (const char *)0;
	}
	while (1) {
		const char *w = p;

		/* the programs */
		while (*p != '\0' && *p != ':' && *p != ',') {
			if (*p == '/' || *p == ' ' || *p == ';' || *p == '=') {
				return "program holds / space ; or =";
			}
			if (*p == '+') {
				if (p == w) {
					return "empty program";
				}
				w = p + 1;
			}
			p++;
		}
		if (*p != ':') {
			return "rule has no ':'";
		}
		if (p == w) {
			return "empty program";
		}
		p++;
		/* its variables */
		while (1) {
			const char *v = p;
			const char *eq = (const char *)0;

			while (*p != '\0' && *p != ';' && *p != ',') {
				if (*p == ' ') {
					return "space in a variable: write ~";
				}
				if (*p == '=' && eq == (const char *)0) {
					eq = p;
				}
				p++;
			}
			if (eq == (const char *)0) {
				return "variable has no '='";
			}
			if (eq == v) {
				return "variable has no name";
			}
			if (p - v >= HK_VAR_MAX) {
				return "variable too long";
			}
			if (*p != ';') {
				break;
			}
			p++;
		}
		if (*p == '\0') {
			return (const char *)0;
		}
		p++;
	}
}

/* Does this rule, at p and with its programs ending at colon, name this program? */
static inline int
hk_env_rule_names(const char *p, const char *colon, const char *name, unsigned long namelen)
{
	while (p < colon) {
		const char *w = p;
		unsigned long i;

		while (p < colon && *p != '+') {
			p++;
		}
		if ((unsigned long)(p - w) == namelen) {
			for (i = 0; i < namelen && w[i] == name[i]; i++) {
				;
			}
			if (i == namelen) {
				return 1;
			}
		}
		if (p < colon) {
			p++;
		}
	}
	return 0;
}

/*
 * Walk the variables for this program. Start with *cursor = the rules, *in_rule = 0. Each call gives the next KEY=VAL
 * in var[0..len), and 1; at the end 0. The rules must have passed hk_env_check.
 */
static inline int
hk_env_next(const char **cursor, int *in_rule, const char *name, unsigned long namelen, const char **var, unsigned long *len)
{
	const char *p = *cursor;

	while (1) {
		if (!*in_rule) {
			const char *colon;

			if (*p == '\0') {
				*cursor = p;
				return 0;
			}
			colon = p;
			while (*colon != ':') {
				colon++;
			}
			if (hk_env_rule_names(p, colon, name, namelen)) {
				*in_rule = 1;
				p = colon + 1;
			} else {
				/* this rule ends at the first ',' after its programs */
				p = colon + 1;
				while (*p != '\0' && *p != ',') {
					p++;
				}
				if (*p == ',') {
					p++;
				}
				continue;
			}
		}
		*var = p;
		while (*p != '\0' && *p != ';' && *p != ',') {
			p++;
		}
		*len = (unsigned long)(p - *var);
		if (*p == ';') {
			p++;
		} else {
			if (*p == ',') {
				p++;
			}
			*in_rule = 0;
		}
		*cursor = p;
		return 1;
	}
}

/*
 * Add text to a rule string, with a ',' if it isn't the first. 0, or -1 if it doesn't fit: the string is unchanged.
 */
static inline int
hk_rules_append(char *rules, unsigned long size, const char *text, unsigned long len)
{
	unsigned long have = 0, i;

	while (have < size && rules[have] != '\0') {
		have++;
	}
	if (len == 0) {
		return 0;
	}
	if (have + (have != 0 ? 1 : 0) + len + 1 > size) {
		return -1;
	}
	if (have != 0) {
		rules[have++] = ',';
	}
	for (i = 0; i < len; i++) {
		rules[have + i] = text[i];
	}
	rules[have + len] = '\0';
	return 0;
}

#endif /* HK_EXEC_RULES_H */
