#pragma once
#include <stdint.h>

#define FB_BASE 0xf0000000UL /* QEMU test scratch only; never a native fallback. */
#define FB_W		1280
#define FB_H		2856
#define FB_STRIDE	(FB_W * 4)	/* a8r8g8b8; panel mode 1280x2856@60, stride 5120 */

#define RED	0xffff0000U
#define BLUE	0xff0000a0U
#define WHITE	0xffffffffU
#define YELLOW	0xffffff00U
#define GREEN	0xff00ff00U

extern volatile uint32_t *con_fb;
extern uintptr_t con_fb_pa;	/* physical address of the console fb */
/* Paint-loop tick hook (see console.c): lets the owner keep the armed
 * firmware watchdog alive during multi-second Device-memory clears. */
extern void (*con_tick)(void);

/* NULL disables output; a nonzero PA requires a validated ownership contract. */
void con_init(uintptr_t fb_pa);

void con_clear(uint32_t bg);
void con_skip(void);
void con_str(const char *label, const char *s);
void con_hex(const char *label, uint64_t v);
/* label, then "a=xxxxxxxx b=xxxxxxxx" style pairs of 32-bit values */
void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb);
