/* hk_accel_once.dylib: skip QuartzCore's 30 s IOAcceleratorES wait in backboardd. MIT, hackios.
 *
 * Gates (both required): the process is backboardd, and HK_ACCEL_ONCE is "probe" (log the verdict only) or "skip"
 * (complete QuartzCore's dispatch_once predicate so its wait block never runs). Anything else: untouched, silent.
 * Before writing, it checks QuartzCore's LC_UUID, its header address against the slide, the global block literal's
 * invoke pointer, and FNV-1a fingerprints of the wait loop and of the device-creation function that owns the once.
 * The only write is dispatch_once_f() on that predicate, i.e. libdispatch's own completion of a once that has not
 * started. QuartzCore then goes straight to MTLCreateSystemDefaultDevice(), exactly as it does after the 30 s.
 *
 * Built without an SDK: the few libSystem prototypes are declared here.
 */
#include "hka_decide.h"

typedef unsigned long size_t;
typedef long dispatch_once_t;
extern void dispatch_once_f(dispatch_once_t *predicate, void *context, void (*function)(void *));
extern unsigned int _dyld_image_count(void);
extern const char *_dyld_get_image_name(unsigned int);
extern const void *_dyld_get_image_header(unsigned int);
extern long _dyld_get_image_vmaddr_slide(unsigned int);
extern const char *getprogname(void);
extern char *getenv(const char *);
extern int strcmp(const char *, const char *);
extern size_t strlen(const char *);
extern int memcmp(const void *, const void *, size_t);
extern int open(const char *, int, ...);
extern long write(int, const void *, size_t);
extern int close(int);
extern int snprintf(char *, size_t, const char *, ...);

#define O_WRONLY 0x1
#define O_NOCTTY 0x20000
#define O_NONBLOCK 0x4

struct hka_mh { uint32_t magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved; };
struct hka_lc { uint32_t cmd, cmdsize; };
#define HKA_MH_MAGIC_64 0xfeedfacfu
#define HKA_LC_UUID 0x1bu

static void say(const char *s)
{
	int fd = open("/dev/console", O_WRONLY | O_NOCTTY | O_NONBLOCK);
	if (fd < 0) return;
	(void)write(fd, s, strlen(s));
	close(fd);
}

static int uuid_ok(const struct hka_mh *h)
{
	if (!h || h->magic != HKA_MH_MAGIC_64 || h->ncmds > 4096 || h->sizeofcmds > (1u << 20)) return 0;
	const uint8_t *p = (const uint8_t *)(h + 1), *end = p + h->sizeofcmds;
	for (uint32_t i = 0; i < h->ncmds && (size_t)(end - p) >= sizeof(struct hka_lc); ++i) {
		const struct hka_lc *lc = (const struct hka_lc *)p;
		if (lc->cmdsize < sizeof *lc || lc->cmdsize > (size_t)(end - p)) return 0;
		if (lc->cmd == HKA_LC_UUID && lc->cmdsize >= 24) return memcmp(p + 8, hka_qc_uuid, 16) == 0;
		p += lc->cmdsize;
	}
	return 0;
}

static int ends_with(const char *s, const char *t)
{
	size_t a = strlen(s), b = strlen(t);
	return a >= b && strcmp(s + a - b, t) == 0;
}

static void hka_noop(void *ctx) { (void)ctx; }

__attribute__((constructor)) static void hka_start(void)
{
	const char *pn = getprogname();
	if (!pn || strcmp(pn, "backboardd")) return;
	const char *mode = getenv("HK_ACCEL_ONCE");
	if (!mode) return;
	int apply = !strcmp(mode, "skip");
	if (!apply && strcmp(mode, "probe")) { say("HKACCEL: invalid HK_ACCEL_ONCE, untouched\n"); return; }

	struct hka_view v = {0};
	unsigned int n = _dyld_image_count();
	for (unsigned int i = 0; i < n; ++i) {
		const char *name = _dyld_get_image_name(i);
		if (!name || !ends_with(name, "/QuartzCore.framework/QuartzCore")) continue;
		const struct hka_mh *h = (const struct hka_mh *)_dyld_get_image_header(i);
		v.have_image = 1;
		v.header = (uint64_t)(uintptr_t)h;
		v.slide = (uint64_t)_dyld_get_image_vmaddr_slide(i);
		v.uuid_ok = uuid_ok(h);
		break;
	}
	/* Only read the fixed addresses once identity and layout hold. */
	if (v.have_image && v.uuid_ok && v.header == HKA_QC_BASE + v.slide) {
		v.block_invoke_raw = *(const volatile uint64_t *)(uintptr_t)(HKA_BLOCK_INVOKE_P + v.slide);
		v.wait_fnv = hka_fnv((const void *)(uintptr_t)(HKA_WAIT_FN + v.slide), HKA_WAIT_LEN);
		v.create_fnv = hka_fnv((const void *)(uintptr_t)(HKA_CREATE_FN + v.slide), HKA_CREATE_LEN);
		v.pred = *(const volatile uint64_t *)(uintptr_t)(HKA_PRED + v.slide);
	}
	enum hka_verdict d = hka_decide(&v);
	char line[200];
	if (d == HKA_APPLY && apply) {
		dispatch_once_t *pred = (dispatch_once_t *)(uintptr_t)(HKA_PRED + v.slide);
		dispatch_once_f(pred, 0, hka_noop);
		uint64_t after = *(const volatile uint64_t *)pred;
		snprintf(line, sizeof line, "HKACCEL: IOAcceleratorES wait skipped, pred %#llx -> %#llx, slide %#llx\n",
		    (unsigned long long)v.pred, (unsigned long long)after, (unsigned long long)v.slide);
	} else {
		snprintf(line, sizeof line, "HKACCEL: mode=%s verdict=%s slide %#llx pred %#llx, untouched\n",
		    mode, hka_name(d), (unsigned long long)v.slide, (unsigned long long)v.pred);
	}
	say(line);
}
