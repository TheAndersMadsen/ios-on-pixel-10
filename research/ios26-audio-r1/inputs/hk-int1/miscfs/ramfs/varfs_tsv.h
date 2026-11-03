/*
 * Parser for /private/var.skel.tsv, the root agent's seed list. No kernel types: the host test includes it.
 *
 *   type TAB mode TAB uid TAB gid TAB path [TAB link] NEWLINE
 *
 * type is d, f or l. mode is octal, uid and gid decimal, path absolute under /private/var/. Only l has link.
 * Anything else is an error, not a skipped line: a half-seeded /var fails later, in ways that are hard to read.
 */
#ifndef VARFS_TSV_H
#define VARFS_TSV_H

#define VARFS_PREFIX            "/private/var/"
#define VARFS_PREFIX_LEN        13
#define VARFS_PATH_MAX          1024            /* MAXPATHLEN */

struct varfs_entry {
	char            type;
	unsigned int    mode;                   /* permission, setuid, setgid and sticky bits only */
	unsigned int    uid, gid;
	const char     *path;                   /* whole, /private/var/... */
	const char     *rel;                    /* the part after /private/var/ */
	const char     *link;                   /* l only */
};

/* Whole field, digits of the given base, value at most max. */
static inline int
varfs_tsv_num(const char *s, unsigned int base, unsigned long long max, unsigned int *out)
{
	unsigned long long v = 0;

	if (*s == '\0') {
		return -1;
	}
	for (; *s != '\0'; s++) {
		unsigned int d = (unsigned int)(*s - '0');

		if (*s < '0' || d >= base) {
			return -1;
		}
		v = v * base + d;
		if (v > max) {
			return -1;
		}
	}
	*out = (unsigned int)v;
	return 0;
}

/* Under /private/var/, with no empty, . or .. component: nothing can land outside the mount. */
static inline int
varfs_tsv_path_ok(const char *p, unsigned long len)
{
	const char *c;

	if (len >= VARFS_PATH_MAX || len <= VARFS_PREFIX_LEN) {
		return 0;
	}
	for (unsigned int i = 0; i < VARFS_PREFIX_LEN; i++) {
		if (p[i] != VARFS_PREFIX[i]) {
			return 0;
		}
	}
	c = p + VARFS_PREFIX_LEN;
	while (1) {
		const char *e = c;

		while (*e != '\0' && *e != '/') {
			e++;
		}
		if (e == c || (e - c == 1 && c[0] == '.') || (e - c == 2 && c[0] == '.' && c[1] == '.') || e - c > 255) {
			return 0;
		}
		if (*e == '\0') {
			return 1;
		}
		c = e + 1;
	}
}

/*
 * Parse one line at *cursor, ending at end. Fields are terminated in place, so the buffer must stay alive
 * as long as the entry. 1: an entry. 0: the end. -1: *why says what is wrong.
 */
static inline int
varfs_tsv_next(char **cursor, char *end, struct varfs_entry *e, const char **why)
{
	char *f[7];
	unsigned int n = 0;
	char *p = *cursor;

	if (p >= end) {
		return 0;
	}
	f[n++] = p;
	for (; p < end && *p != '\n'; p++) {
		if (*p == '\0') {
			*why = "NUL in line";
			return -1;
		}
		if (*p == '\t') {
			if (n == 6) {
				*why = "too many fields";
				return -1;
			}
			*p = '\0';
			f[n++] = p + 1;
		}
	}
	if (p >= end) {
		*why = "last line has no newline: truncated list";
		return -1;
	}
	*p = '\0';
	*cursor = p + 1;

	if (n != 5 && n != 6) {
		*why = "wrong number of fields";
		return -1;
	}
	if (f[0][0] == '\0' || f[0][1] != '\0' || (f[0][0] != 'd' && f[0][0] != 'f' && f[0][0] != 'l')) {
		*why = "unknown type";
		return -1;
	}
	e->type = f[0][0];
	if ((e->type == 'l') != (n == 6)) {
		*why = "only l has a link field, and it must";
		return -1;
	}
	if (varfs_tsv_num(f[1], 8, 07777777, &e->mode) != 0) {
		*why = "bad mode";
		return -1;
	}
	e->mode &= 07777;
	if (varfs_tsv_num(f[2], 10, 0xffffffffull, &e->uid) != 0 || varfs_tsv_num(f[3], 10, 0xffffffffull, &e->gid) != 0) {
		*why = "bad owner";
		return -1;
	}
	if (!varfs_tsv_path_ok(f[4], (unsigned long)(((n == 6) ? f[5] - 1 : p) - f[4]))) {
		*why = "bad path";
		return -1;
	}
	e->path = f[4];
	e->rel = f[4] + VARFS_PREFIX_LEN;
	e->link = n == 6 ? f[5] : (const char *)0;
	if (n == 6 && (f[5][0] == '\0' || p - f[5] >= VARFS_PATH_MAX)) {
		*why = "bad link";
		return -1;
	}
	return 1;
}

#endif /* VARFS_TSV_H */
