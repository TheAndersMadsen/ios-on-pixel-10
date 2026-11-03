/* Host test for keys_laguna.c against a mocked pinctrl@5280000 RXDATA bus.
 * Build: cc -DTGL_KEYS_POLL=1 keys_laguna.c keys_laguna_test.c (test_keys.py does this). */
#include <stdio.h>
#include <string.h>
#include "keys_laguna.h"

#if !TGL_KEYS_POLL
#error "build the test with -DTGL_KEYS_POLL=1"
#endif

static unsigned fails, checks;
#define CHECK(c, m) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d %s\n", __func__, __LINE__, m); } } while (0)

/* Mock MMIO: 57 cpm pads, each RXDATA word. Any other address is a test failure. */
static uint32_t rx[57];
static unsigned nreads[57], stray_reads, fail_pad = 99;
static uint32_t force_word[57];
static int force[57];

static int mock_rd32(uintptr_t pa, uint32_t *v)
{
	uint64_t off = (uint64_t)pa - KEYS_PAD_BASE;
	if ((uint64_t)pa < KEYS_PAD_BASE || off >= 57u * KEYS_PAD_STRIDE || (off & (KEYS_PAD_STRIDE - 1)) != KEYS_PAD_RXDATA) {
		stray_reads++;
		return 0;
	}
	unsigned pad = (unsigned)(off / KEYS_PAD_STRIDE);
	nreads[pad]++;
	if (pad == fail_pad) return 0;
	*v = force[pad] ? force_word[pad] : rx[pad];
	return 1;
}

/* Idle level = 1 (pulled up); pressed = 0. Upper bits as the probe might show them. */
static void level(unsigned pad, int pressed) { rx[pad] = 0x00000a00u | (pressed ? 0u : 1u); }
static void reset_bus(void)
{
	memset(nreads, 0, sizeof nreads);
	memset(force, 0, sizeof force);
	stray_reads = 0;
	fail_pad = 99;
	for (unsigned i = 0; i < 57; i++) level(i, 0);
}

/* Poll every 2 ms from t0 to t1 inclusive; return the last result. */
static unsigned run(struct keys_state *s, uint64_t *t, uint64_t ms)
{
	unsigned r = 0;
	for (uint64_t end = *t + ms; *t <= end; *t += 2) r = keys_poll(s, *t);
	*t -= 2;
	return r;
}

#define VOL (KEYS_VOL_UP | KEYS_VOL_DOWN)
#define ALL (VOL | KEYS_POWER)

static void test_addresses(void)
{
	CHECK(KEYS_PAD_PA(KEYS_PAD_POWER) == UINT64_C(0x052b0010), "power RXDATA PA");
	CHECK(KEYS_PAD_PA(KEYS_PAD_VOL_DOWN) == UINT64_C(0x052b3010), "vol-down RXDATA PA");
	CHECK(KEYS_PAD_PA(KEYS_PAD_VOL_UP) == UINT64_C(0x052b4010), "vol-up RXDATA PA");
	CHECK(KEYS_PAD_PA(56) < KEYS_PAD_BASE + 0x39000u, "last pad inside the FDT reg window");
}

static void test_press_release(void)
{
	struct keys_state s;
	uint64_t t = 1000;
	reset_bus();
	keys_init(&s, mock_rd32, VOL, t, 0);
	CHECK(run(&s, &t, 40) == 0, "idle reads nothing held");
	CHECK(s.live == VOL, "idle keys become live after a steady release");
	level(KEYS_PAD_VOL_DOWN, 1);
	CHECK(keys_poll(&s, t += 2) == 0, "no report before the debounce");
	CHECK(run(&s, &t, 10) == 0, "still nothing at 10 ms");
	CHECK(run(&s, &t, 14) == KEYS_VOL_DOWN, "volume down after 20 ms steady");
	level(KEYS_PAD_VOL_DOWN, 0);
	CHECK(run(&s, &t, 10) == KEYS_VOL_DOWN, "release not yet debounced");
	CHECK(run(&s, &t, 14) == 0, "released");
	level(KEYS_PAD_VOL_UP, 1);
	CHECK(run(&s, &t, 30) == KEYS_VOL_UP, "volume up");
	level(KEYS_PAD_VOL_DOWN, 1);
	CHECK(run(&s, &t, 30) == VOL, "a two-key chord is reported as both; the menu ignores it");
	CHECK(!(s.fault), "two volume keys low is not garbage");
	CHECK(nreads[KEYS_PAD_POWER] == 0, "power pad never read when not wanted");
	CHECK(stray_reads == 0, "no read outside the three RXDATA words");
	for (unsigned i = 0; i < 57; i++)
		if (i != KEYS_PAD_VOL_DOWN && i != KEYS_PAD_VOL_UP) CHECK(nreads[i] == 0, "only pads 51 and 52 read");
}

static void test_bounce(void)
{
	struct keys_state s;
	uint64_t t = 0;
	reset_bus();
	keys_init(&s, mock_rd32, VOL, t, 0);
	run(&s, &t, 40);
	/* Contact bounce: toggles every 6 ms for 120 ms never settles. */
	for (int k = 0; k < 20; k++) {
		level(KEYS_PAD_VOL_UP, k & 1);
		CHECK(run(&s, &t, 6) == 0, "bounce is not a press");
	}
	level(KEYS_PAD_VOL_UP, 0);
	CHECK(run(&s, &t, 30) == 0, "settled released");
	level(KEYS_PAD_VOL_UP, 1);
	CHECK(run(&s, &t, 14) == 0, "a 14 ms blip is not a press");
	level(KEYS_PAD_VOL_UP, 0);
	CHECK(run(&s, &t, 40) == 0, "back to idle");
}

static void test_held_at_start(void)
{
	struct keys_state s;
	uint64_t t = 0;
	reset_bus();
	level(KEYS_PAD_VOL_DOWN, 1);	/* user (or a stuck pad) holds vol-down before we look */
	keys_init(&s, mock_rd32, VOL, t, 0);
	CHECK(run(&s, &t, 200) == 0, "a key held from the start is no press");
	CHECK(!(s.live & KEYS_VOL_DOWN) && (s.live & KEYS_VOL_UP), "vol-down not live, vol-up live");
	level(KEYS_PAD_VOL_UP, 1);
	CHECK(run(&s, &t, 30) == KEYS_VOL_UP, "the other key still works");
	level(KEYS_PAD_VOL_UP, 0);
	level(KEYS_PAD_VOL_DOWN, 0);
	CHECK(run(&s, &t, 30) == 0, "both released");
	level(KEYS_PAD_VOL_DOWN, 1);
	CHECK(run(&s, &t, 30) == KEYS_VOL_DOWN, "after a release, vol-down is believed");
}

static void test_timeout(void)
{
	struct keys_state s;
	uint64_t t = 5000;
	reset_bus();
	keys_init(&s, mock_rd32, VOL, t, 3000);
	CHECK(!(run(&s, &t, 2990) & KEYS_TIMEOUT), "no timeout before 3 s");
	CHECK(run(&s, &t, 20) == KEYS_TIMEOUT, "3 s with no input: timeout (default Android)");

	keys_init(&s, mock_rd32, VOL, t, 3000);
	run(&s, &t, 1000);
	level(KEYS_PAD_VOL_DOWN, 1);
	CHECK(run(&s, &t, 4000) == KEYS_VOL_DOWN, "a held key never times out");
	level(KEYS_PAD_VOL_DOWN, 0);
	CHECK(!(run(&s, &t, 2900) & KEYS_TIMEOUT), "timeout restarts from the release");
	CHECK(run(&s, &t, 200) & KEYS_TIMEOUT, "then times out");

	keys_init(&s, mock_rd32, VOL, t, 0);
	CHECK(!(run(&s, &t, 100000) & KEYS_TIMEOUT), "timeout_ms 0 disables it");
}

static void test_garbage(void)
{
	struct keys_state s;
	uint64_t t = 0;
	reset_bus();
	keys_init(&s, mock_rd32, ALL, t, 3000);
	run(&s, &t, 40);
	CHECK(s.live == ALL, "all three live");
	/* All three low at once = unclocked block (blazer_keys.c rule): ignored. */
	level(KEYS_PAD_POWER, 1); level(KEYS_PAD_VOL_DOWN, 1); level(KEYS_PAD_VOL_UP, 1);
	unsigned r = 0;
	for (unsigned i = 0; i < KEYS_BAD_LIMIT - 1; i++) r |= keys_poll(&s, t += 2);
	CHECK(r == 0, "all-low samples report nothing");
	CHECK(!s.fault, "not yet a fault");
	level(KEYS_PAD_POWER, 0); level(KEYS_PAD_VOL_DOWN, 0);
	CHECK(run(&s, &t, 30) == KEYS_VOL_UP, "one clean key after garbage");
	level(KEYS_PAD_VOL_UP, 0);
	run(&s, &t, 30);

	force[KEYS_PAD_VOL_DOWN] = 1;
	force_word[KEYS_PAD_VOL_DOWN] = KEYS_UNREADABLE;
	for (unsigned i = 0; i < KEYS_BAD_LIMIT - 1; i++) keys_poll(&s, t += 2);
	CHECK(!s.fault, "63 unreadable samples: not yet");
	CHECK(keys_poll(&s, t += 2) & KEYS_FAULT, "64th latches the fault");
	unsigned before = nreads[KEYS_PAD_VOL_UP];
	force[KEYS_PAD_VOL_DOWN] = 0;
	CHECK((run(&s, &t, 100) & KEYS_HELD_MASK) == 0, "fault holds nothing");
	CHECK(nreads[KEYS_PAD_VOL_UP] == before, "no read after the fault");
	CHECK(run(&s, &t, 3000) & KEYS_TIMEOUT, "a fault still times out to the default");
}

static void test_read_fault(void)
{
	struct keys_state s;
	uint64_t t = 0;
	reset_bus();
	keys_init(&s, mock_rd32, VOL, t, 3000);
	run(&s, &t, 40);
	level(KEYS_PAD_VOL_UP, 1);
	run(&s, &t, 30);
	fail_pad = KEYS_PAD_VOL_DOWN;
	CHECK(keys_poll(&s, t += 2) == KEYS_FAULT, "a faulted read latches at once, nothing held");
	unsigned n = nreads[KEYS_PAD_VOL_DOWN] + nreads[KEYS_PAD_VOL_UP];
	run(&s, &t, 100);
	CHECK(nreads[KEYS_PAD_VOL_DOWN] + nreads[KEYS_PAD_VOL_UP] == n, "never read again");

	keys_init(&s, 0, VOL, t, 3000);
	CHECK(keys_poll(&s, t) & KEYS_FAULT, "no reader: fault, no crash");
	keys_init(&s, mock_rd32, 0, t, 3000);
	CHECK(keys_poll(&s, t) & KEYS_FAULT, "nothing wanted: fault");
}

static void test_raw(void)
{
	struct keys_state s;
	uint64_t t = 0;
	reset_bus();
	keys_init(&s, mock_rd32, ALL, t, 0);
	level(KEYS_PAD_VOL_UP, 1);
	keys_poll(&s, t);
	CHECK(keys_raw_levels(&s) == 3u, "raw levels: power 1, down 1, up 0");
	CHECK(s.raw[2] == 0x00000a00u, "raw word kept");
}

int main(void)
{
	test_addresses();
	test_press_release();
	test_bounce();
	test_held_at_start();
	test_timeout();
	test_garbage();
	test_read_fault();
	test_raw();
	printf("keys_laguna_test: %u checks, %u failures\n", checks, fails);
	return fails != 0;
}
