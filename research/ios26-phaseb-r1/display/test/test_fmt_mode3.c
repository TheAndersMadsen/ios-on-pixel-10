/* Host check of sweet_surface_format_action after the hk-dsp-icons change: mode 3 refuses only RGhA; modes 0-2 unchanged. */
#include <stdio.h>
#include "sweet_surface_format.h"
static int fails;
#define EXPECT(f, m, want) do { int got = sweet_surface_format_action((f), (m)); if (got != (want)) { printf("FAIL fmt %08x mode %u got %d want %d\n", (f), (m), got, (want)); fails++; } } while (0)
int main(void) {
    uint32_t rgha = SWEET_FOURCC('R','G','h','A'), bgra = SWEET_FMT_BGRA, w30r = SWEET_FOURCC('w','3','0','r'), comp = SWEET_FOURCC('&','B','G','A'), la08 = 0x4c413038;
    EXPECT(rgha, 3, SWEET_FMT_REFUSE); EXPECT(bgra, 3, SWEET_FMT_KEEP); EXPECT(w30r, 3, SWEET_FMT_KEEP); EXPECT(comp, 3, SWEET_FMT_KEEP); EXPECT(la08, 3, SWEET_FMT_KEEP);
    for (unsigned m = 0; m <= 2; m++) EXPECT(rgha, m, SWEET_FMT_KEEP);
    EXPECT(bgra, 0, SWEET_FMT_KEEP); EXPECT(w30r, 1, SWEET_FMT_PLAIN); EXPECT(comp, 1, SWEET_FMT_PLAIN); EXPECT(w30r, 2, SWEET_FMT_PLAIN); EXPECT(comp, 2, SWEET_FMT_REFUSE);
    if (SWEET_FMT_DEFAULT_MODE != 3u) { puts("FAIL default"); fails++; }
    printf("%s (%d failures)\n", fails ? "FAIL" : "PASS", fails);
    return fails != 0;
}
