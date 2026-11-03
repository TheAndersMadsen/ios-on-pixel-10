#!/usr/bin/env python3
"""Apply the r5-dsp kernel change to the release tree (run from research/ios26-release-r1/work/xnu). Idempotent check: refuses if applied."""
import sys
from pathlib import Path

def sub(path, old, new):
    p = Path(path); t = p.read_text()
    if t.count(old) != 1:
        sys.exit(f'{path}: anchor found {t.count(old)} times')
    p.write_text(t.replace(old, new))

H = 'iokit/Kernel/arm/sweet_surface_format.h'
sub(H, """#define SWEET_FMT_BGRA SWEET_FOURCC('B', 'G', 'R', 'A')
""", """#define SWEET_FMT_BGRA SWEET_FOURCC('B', 'G', 'R', 'A')
#define SWEET_FMT_RGHA SWEET_FOURCC('R', 'G', 'h', 'A')   /* 64-bit RGBA half float: iconservicesagent's icon surfaces on iOS 26 */
/*
 * hk_fmt=3, the default of this kernel (hk-dsp-icons; research/ios26-phaseb-r1/display/PLAN.md): refuse RGhA and keep every other format.
 * The CPU compositor never shows the icons drawn into these surfaces (owner: missing logos/icons; ios-tegu: they never reach backboardd).
 * A refused IOSurface makes the producer fall back to plain memory, which CoreAnimation ships to backboardd as image data. hk_fmt=0 restores the old answer.
 */
#define SWEET_FMT_DEFAULT_MODE 3u
""")
sub(H, """	if (mode == 2 && compressed) return SWEET_FMT_REFUSE;
""", """	if (mode == 2 && compressed) return SWEET_FMT_REFUSE;
	if (mode == 3 && format == SWEET_FMT_RGHA) return SWEET_FMT_REFUSE;
""")

C = 'iokit/Kernel/arm/SweetSurface.cpp'
sub(C, """	static uint32_t fmt_mode, fmt_read, fmt_logged;
	if (!fmt_read) {
		PE_parse_boot_argn("hk_fmt", &fmt_mode, sizeof(fmt_mode));
		fmt_read = 1;
	}""", """	static uint32_t fmt_mode = SWEET_FMT_DEFAULT_MODE, fmt_read, fmt_logged, fmt_refused;
	if (!fmt_read) {
		PE_parse_boot_argn("hk_fmt", &fmt_mode, sizeof(fmt_mode));
		fmt_read = 1;
		IOLog("SWEET SURF: hk_fmt %u%s\\n", fmt_mode, fmt_mode == 3 ? ": RGhA refused" : "");
	}""")
sub(C, """	if (fmt_action != SWEET_FMT_KEEP && fmt_logged < 16) {
		fmt_logged++;
		IOLog("SWEET SURF: format %x %ux%u %s\\n", s->pixelFormat, s->width, s->height, fmt_action == SWEET_FMT_PLAIN ? "served as BGRA" : "refused");
	}""", """	if (fmt_action == SWEET_FMT_REFUSE) fmt_refused++;
	if (fmt_action != SWEET_FMT_KEEP && (fmt_logged < 16 || (fmt_action == SWEET_FMT_REFUSE && (fmt_refused % 64) == 0))) {
		char who[32];
		proc_selfname(who, sizeof(who));
		fmt_logged++;
		IOLog("SWEET SURF: %s format %x %ux%u %s (refused %u)\\n", who, s->pixelFormat, s->width, s->height,
		    fmt_action == SWEET_FMT_PLAIN ? "served as BGRA" : "refused", fmt_refused);
	}""")
# Who imports which non-BGRA surface: answers whether icon surfaces ever reach backboardd.
sub(C, """	case kSweetSurfaceLookup: {
		SweetSurface *s = sweet_surface_copy((uint32_t)arg0);
		IOReturn ret = kIOReturnNotFound;
		if (s != NULL) {
			ret = sweet_surface_get(s) ? returnSurface(s, args) : kIOReturnNotFound;
""", """	case kSweetSurfaceLookup: {
		SweetSurface *s = sweet_surface_copy((uint32_t)arg0);
		IOReturn ret = kIOReturnNotFound;
		if (s != NULL) {
			ret = sweet_surface_get(s) ? returnSurface(s, args) : kIOReturnNotFound;
			sweet_surf_import_log(s, selector, ret);
""")
sub(C, """			ret = (s != NULL && sweet_surface_get(s)) ? returnSurface(s, args) : kIOReturnBadArgument;
		}
		OSSafeReleaseNULL(obj);""", """			ret = (s != NULL && sweet_surface_get(s)) ? returnSurface(s, args) : kIOReturnBadArgument;
			if (s != NULL) sweet_surf_import_log(s, selector, ret);
		}
		OSSafeReleaseNULL(obj);""")
sub(C, """/* Called only for owned aligned buffers, with CPU/GPU access externally fenced. */""",
"""/* hk-dsp-icons: the first 48 imports (lookup by id or port) of a surface that is not BGRA, by process. Always on, bounded. */
static uint32_t sweet_surf_imports_logged;
static void
sweet_surf_import_log(SweetSurface *s, uint32_t selector, IOReturn ret)
{
	if (s->pixelFormat == SWEET_FMT_BGRA || __atomic_fetch_add(&sweet_surf_imports_logged, 1, __ATOMIC_RELAXED) >= 48) return;
	char who[32];
	proc_selfname(who, sizeof(who));
	IOLog("SWEET SURF: %s imports id %u fmt %x %ux%u by sel %u -> 0x%x\\n", who, s->id, s->pixelFormat, s->width, s->height, selector, ret);
}

/* Called only for owned aligned buffers, with CPU/GPU access externally fenced. */""")
print('applied')
