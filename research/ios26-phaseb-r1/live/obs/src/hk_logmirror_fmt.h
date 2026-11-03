/*
 * hk_logmirror: the pure parts (host-tested on Linux and macOS). MIT, original.
 *
 * In:  one line a daemon wrote to stderr. Under OS_ACTIVITY_DT_MODE=YES libsystem_trace writes each os_log line as
 *      "1969-12-31 16:02:03.933641-0800 tccd[33:730] [access] message" (receipt: app2 qemu-r26).
 * Out: "HKL tccd[33] [access] message\n": the tag, the program and its pid, the message. The date (the host stamps lines
 *      itself) and the "prog[pid:tid] " head are dropped, the line is cut at a bound and marked "~" when cut.
 */
#ifndef HK_LOGMIRROR_FMT_H
#define HK_LOGMIRROR_FMT_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define HKM_LINE_MAX    320u    /* one console line, the tag and the newline included */
#define HKM_RATE        8u      /* lines per second per program */
#define HKM_BURST       64u

static inline int
hkm_digit(char c)
{
	return c >= '0' && c <= '9';
}

/* Where the message starts: past "YYYY-MM-DD HH:MM:SS.ffffff+zzzz " and then past "prog[...] ". 0 if neither is there */
static inline size_t
hkm_message_at(const char *s, size_t n, const char *prog)
{
	size_t i = 0, k;

	if (n >= 20 && hkm_digit(s[0]) && hkm_digit(s[3]) && s[4] == '-' && s[7] == '-' && s[10] == ' ' && s[13] == ':' &&
	    s[16] == ':' && hkm_digit(s[17])) {
		for (i = 19; i < n && s[i] != ' '; i++) {
			;
		}
		if (i < n) {
			i++;
		}
	}
	k = strlen(prog);
	if (k != 0 && n - i > k + 2 && memcmp(s + i, prog, k) == 0 && s[i + k] == '[') {
		size_t j;

		for (j = i + k + 1; j < n && s[j] != ']'; j++) {
			if (!hkm_digit(s[j]) && s[j] != ':') {
				return i;
			}
		}
		if (j + 1 < n && s[j] == ']' && s[j + 1] == ' ') {
			return j + 2;
		}
	}
	return i;
}

/*
 * The console line for msg[0..n) (no newline in it). cut: more of this line was not kept. Returns its length (at most
 * HKM_LINE_MAX - 1, newline included; out holds HKM_LINE_MAX). Control bytes become '.'; bytes >= 0x80 stay (UTF-8).
 */
static inline size_t
hkm_format(char *out, const char *prog, int pid, const char *msg, size_t n, int cut)
{
	int h = snprintf(out, HKM_LINE_MAX, "HKL %.32s[%d] ", prog, pid);
	size_t at = h > 0 && (size_t)h < HKM_LINE_MAX ? (size_t)h : 0, room = HKM_LINE_MAX - 3 - at, i;

	while (n != 0 && (msg[n - 1] == '\r' || msg[n - 1] == ' ')) {
		n--;
	}
	if (n > room) {
		n = room;
		cut = 1;
	}
	for (i = 0; i < n; i++) {
		unsigned char c = (unsigned char)msg[i];

		out[at++] = (c < 32 && c != '\t') || c == 127 ? '.' : (char)c;
	}
	if (cut) {
		out[at++] = '~';
	}
	out[at++] = '\n';
	out[at] = 0;
	return at;
}

/* Lines per second with a burst; time in microseconds. Whole lines, no lost fractions */
struct hkm_bucket {
	uint64_t last_us;
	uint32_t tokens, rate, burst;
	int primed;
};

static inline int
hkm_take(struct hkm_bucket *b, uint64_t now_us)
{
	if (b->rate == 0) {
		return 1;
	}
	if (!b->primed) {
		b->primed = 1;
		b->tokens = b->burst;
		b->last_us = now_us;
	}
	if (now_us > b->last_us) {
		uint64_t add = (now_us - b->last_us) * b->rate / 1000000u;

		if (add != 0) {
			if ((uint64_t)b->tokens + add >= b->burst) {
				b->tokens = b->burst;
				b->last_us = now_us;
			} else {
				b->tokens += (uint32_t)add;
				b->last_us += add * 1000000u / b->rate;
			}
		}
	}
	if (b->tokens == 0) {
		return 0;
	}
	b->tokens--;
	return 1;
}

/* HK_LOGMIRROR: "1" (defaults), "R" or "R,B" (lines/s, burst; R 0 = no limit). 0: off. Bounds R <= 1000, B 1..10000 */
static inline int
hkm_parse(const char *v, uint32_t *rate, uint32_t *burst)
{
	unsigned long r = 0, b = 0;
	const char *p = v;

	if (v == NULL || *v == 0 || strcmp(v, "0") == 0) {
		return 0;
	}
	*rate = HKM_RATE;
	*burst = HKM_BURST;
	if (strcmp(v, "1") == 0) {
		return 1;
	}
	while (hkm_digit(*p) && r <= 1000) {
		r = r * 10 + (unsigned long)(*p++ - '0');
	}
	if (p == v || r > 1000) {
		return 1;       /* malformed: on, with the defaults */
	}
	if (*p == ',') {
		const char *q = ++p;

		while (hkm_digit(*p) && b <= 10000) {
			b = b * 10 + (unsigned long)(*p++ - '0');
		}
		if (p == q || b == 0 || b > 10000 || *p != 0) {
			return 1;
		}
		*burst = (uint32_t)b;
	} else if (*p != 0) {
		return 1;
	}
	*rate = (uint32_t)r;
	return 1;
}

#endif /* HK_LOGMIRROR_FMT_H */
