/*
 * Host test: the real bsd/dev/blazer_tcm.c report parser and scaling, then blazer_touch.c's panel-pixel step,
 * against every finger the r5-accel phone boot logged (research/laguna-usb-fix/attempts/
 * 20261103-162351-a7-ios-system-r5-accel/ramdump/kernel.log: "tcm: finger 0 down at X, Y" followed by
 * "SWEET HID: touch 0 down at PX,PY").
 *
 * The question it settles: "finger 0 down at 59395, 383" is not an out-of-range panel x. The tcm line prints the
 * value AFTER the scale to 0..65535 (blazer_tcm.c: x * 65535 / scale_x, scale_x = max_x = 12799), so 59395 is raw
 * x 11600 of 12799, and 65535 is the clamp for raw >= max (bottom row). For each logged pair the test finds the raw
 * panel coordinate that produces it, sends that raw value through the real parser as a TouchComm touch report,
 * and checks the parser's output and the panel pixel equal the logged ones.
 *
 * Build: run.sh (compiles blazer_tcm.c with -DBLAZER).
 */
#include <stdio.h>
#include <string.h>
#include "blazer_tcm.h"

#define MAX_X 12799     /* tcm: panel 12799 x 28559 (the phone's application info) */
#define MAX_Y 28559
#define PANEL_W 1280    /* blazer_touch.c */
#define PANEL_H 2856

static int failures, checks;
#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint32_t got_type, got_x, got_y, got_n;
void
hakios_tcm_input(uint32_t type, uint32_t finger, uint32_t x, uint32_t y)
{
	(void)finger;
	got_type = type;
	got_x = x;
	got_y = y;
	got_n++;
}

/* blazer_touch.c touch_hw_sink with touch_round off (the r5 command line has no touch_round) */
static int px_of(uint32_t v, int panel) { return (int)(((uint64_t)v * (uint64_t)(panel - 1)) / 65535); }

/* the first raw value whose scaled form equals v (blazer_tcm.c's formula), or -1 */
static int
raw_for(uint32_t v, uint32_t max)
{
	for (uint32_t r = 0; r <= max + 1; r++) {
		uint32_t s = r >= max ? 65535 : r * 65535 / max;
		if (s == v) {
			return (int)r;
		}
	}
	return -1;
}

/* NUM_ACTIVE(8) FOREACH_ACTIVE { INDEX(4) CLASS(4) X(16) Y(16) } END */
static const uint8_t config[] = {
	TCM_CFG_NUM_ACTIVE, 8, TCM_CFG_FOREACH_ACTIVE,
	TCM_CFG_OBJ_INDEX, 4, TCM_CFG_OBJ_CLASS, 4, TCM_CFG_OBJ_X, 16, TCM_CFG_OBJ_Y, 16,
	TCM_CFG_FOREACH_END, TCM_CFG_END,
};

static void
report(struct hakios_tcm_state *st, int active, uint8_t class, uint32_t x, uint32_t y)
{
	uint8_t r[6] = { (uint8_t)active, (uint8_t)(0 | class << 4), (uint8_t)x, (uint8_t)(x >> 8), (uint8_t)y, (uint8_t)(y >> 8) };

	CHECK(hakios_tcm_touch_report(st, r, sizeof(r)), "report parsed");
}

int
main(void)
{
	/* kernel.log lines 5764..6961 of the r5-accel ramdump, in order */
	static const struct { uint32_t x, y; int px, py; } logged[] = {
		{ 56113, 780, 1095, 33 }, { 33200, 65535, 647, 2855 }, { 10609, 8251, 207, 359 }, { 52386, 52705, 1022, 2296 },
		{ 32401, 54963, 632, 2394 }, { 35760, 46000, 697, 2003 }, { 48786, 11384, 952, 495 }, { 58161, 1732, 1135, 75 },
		{ 6784, 2937, 132, 127 }, { 1054, 40621, 20, 1769 }, { 30240, 37830, 590, 1648 }, { 45796, 41589, 893, 1811 },
		{ 59395, 383, 1159, 16 }, { 41136, 34540, 802, 1504 }, { 39523, 36747, 771, 1600 }, { 50691, 41259, 989, 1797 },
	};
	static struct hakios_tcm_state st;

	memset(&st, 0, sizeof(st));
	memcpy(st.config, config, sizeof(config));
	st.config_len = sizeof(config);
	st.max_x = MAX_X;
	st.max_y = MAX_Y;
	st.scale_x = MAX_X;
	st.scale_y = MAX_Y;
	st.max_objects = 10;

	for (unsigned i = 0; i < sizeof(logged) / sizeof(logged[0]); i++) {
		int rx = raw_for(logged[i].x, MAX_X), ry = raw_for(logged[i].y, MAX_Y);

		CHECK(rx >= 0 && rx <= MAX_X, "logged x %u has a raw panel x within 0..%u (%d)", logged[i].x, MAX_X, rx);
		CHECK(ry >= 0 && ry <= MAX_Y, "logged y %u has a raw panel y within 0..%u (%d)", logged[i].y, MAX_Y, ry);
		got_n = 0;
		report(&st, 1, TCM_OBJ_FINGER, (uint32_t)rx, (uint32_t)ry);
		CHECK(got_n == 1 && got_type == HAKIOS_TOUCH_DOWN, "down posted");
		CHECK(got_x == logged[i].x && got_y == logged[i].y, "parser %u,%u vs logged %u,%u", got_x, got_y, logged[i].x, logged[i].y);
		CHECK(px_of(got_x, PANEL_W) == logged[i].px && px_of(got_y, PANEL_H) == logged[i].py, "pixel %d,%d vs logged %d,%d",
		    px_of(got_x, PANEL_W), px_of(got_y, PANEL_H), logged[i].px, logged[i].py);
		got_n = 0;
		report(&st, 0, TCM_OBJ_LIFT, 0, 0);
		CHECK(got_n == 1 && got_type == HAKIOS_TOUCH_UP && got_x == logged[i].x && got_y == logged[i].y, "up at the last position");
	}
	/* the edges: raw max is the last pixel, nothing goes past the panel */
	got_n = 0;
	report(&st, 1, TCM_OBJ_FINGER, MAX_X, MAX_Y);
	CHECK(got_x == 65535 && got_y == 65535 && px_of(got_x, PANEL_W) == PANEL_W - 1 && px_of(got_y, PANEL_H) == PANEL_H - 1, "max -> last pixel");
	report(&st, 0, TCM_OBJ_LIFT, 0, 0);
	report(&st, 1, TCM_OBJ_FINGER, 0, 0);
	CHECK(got_x == 0 && got_y == 0, "origin");
	printf("tcm decode host test: %d checks, %d failed\n", checks, failures);
	return failures != 0;
}
