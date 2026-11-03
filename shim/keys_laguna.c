/* Debounced volume/power key sampling for the chooser. Reads only; see keys_laguna.h for the wiring
 * citations and research/ios26-dualboot-r8/keys/KEYS.md for the evidence and the test. */
#include "keys_laguna.h"

#if TGL_KEYS_POLL

/* Index i: 0 power (pad 48), 1 volume down (pad 51), 2 volume up (pad 52). No pointer tables: the
 * shim image forbids ABS64 relocations (build.sh). */
static inline unsigned key_bit(unsigned i)
{
	return i == 0 ? KEYS_POWER : i == 1 ? KEYS_VOL_DOWN : KEYS_VOL_UP;
}

static inline unsigned key_pad(unsigned i)
{
	return i == 0 ? KEYS_PAD_POWER : i == 1 ? KEYS_PAD_VOL_DOWN : KEYS_PAD_VOL_UP;
}

static inline uint64_t since(uint64_t now, uint64_t then)
{
	return now > then ? now - then : 0;
}

void keys_init(struct keys_state *s, keys_rd32_fn rd, unsigned want, uint64_t now_ms, uint64_t timeout_ms)
{
	s->rd = rd;
	s->want = want & KEYS_HELD_MASK;
	s->stable = KEYS_UNKNOWN;	/* the first steady sample is accepted, whatever it is */
	s->live = 0;
	s->cand = KEYS_UNKNOWN;
	s->fault = rd == 0 || s->want == 0;
	s->bad = 0;
	s->reads = 0;
	s->samples = 0;
	for (unsigned i = 0; i < KEYS_N; i++) s->raw[i] = KEYS_UNREADABLE;
	s->cand_ms = now_ms;
	s->quiet_ms = now_ms;
	s->timeout_ms = timeout_ms;
}

static unsigned keys_report(const struct keys_state *s, uint64_t now_ms)
{
	unsigned held = s->stable & s->live & s->want;
	unsigned r = s->fault ? KEYS_FAULT : held;
	if (s->timeout_ms && (s->fault || !held) && since(now_ms, s->quiet_ms) >= s->timeout_ms) r |= KEYS_TIMEOUT;
	return r;
}

unsigned keys_poll(struct keys_state *s, uint64_t now_ms)
{
	if (s->fault) return keys_report(s, now_ms);
	unsigned pressed = 0, nread = 0, nlow = 0, garbage = 0;
	for (unsigned i = 0; i < KEYS_N; i++) {
		unsigned b = key_bit(i);
		uint32_t v = 0;
		if (!(s->want & b)) continue;
		if (!s->rd((uintptr_t)KEYS_PAD_PA(key_pad(i)), &v)) {
			/* A faulted read is never retried: the guard caught it once, do not ask again. */
			s->fault = 1;
			s->stable = 0;
			return keys_report(s, now_ms);
		}
		s->raw[i] = v;
		s->reads++;
		nread++;
		if (v == KEYS_UNREADABLE) garbage = 1;
		if (!(v & KEYS_LEVEL_BIT)) { pressed |= b; nlow++; }	/* FDT GPIO_ACTIVE_LOW */
	}
	/* An unclocked or unpowered block reads all ones or all zeros; all three keys at once look the same
	 * (blazer_keys.c rule). With two pads that is a plain chord, which the menu ignores anyway. */
	if (nread == KEYS_N && nlow == nread) garbage = 1;
	if (garbage) {
		s->cand_ms = now_ms;	/* garbage interrupts a debounce in progress */
		if (++s->bad >= KEYS_BAD_LIMIT) {
			s->fault = 1;
			s->stable = 0;
		}
		return keys_report(s, now_ms);
	}
	s->bad = 0;
	s->samples++;
	if (pressed != s->cand) {
		s->cand = pressed;
		s->cand_ms = now_ms;
	} else if (pressed != s->stable && since(now_ms, s->cand_ms) >= KEYS_DEBOUNCE_MS) {
		unsigned before = s->stable & s->live;
		s->stable = pressed;
		s->live |= ~pressed & s->want;	/* released and steady: believed from here on */
		if ((s->stable & s->live) != before) s->quiet_ms = now_ms;
	}
	return keys_report(s, now_ms);
}

unsigned keys_raw_levels(const struct keys_state *s)
{
	unsigned r = 0;
	for (unsigned i = 0; i < KEYS_N; i++) r |= (s->raw[i] & KEYS_LEVEL_BIT) << i;
	return r;
}

#endif
