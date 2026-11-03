/*
 * blazer_usbhost=1: the USB-C port as a USB host, once, late in a boot that has no live console. USBHOST.md
 * (research/ios26-phaseb-r1/usbhost/). Core: blazer_usbhost_core.inc (no XNU types, host-tested).
 *
 * Off without the arg: blazer_usbhost_start() reads a tunable and returns. No map, no MMIO, no thread, no line.
 *
 * With it:
 *  - refused unless blazer_usbcon is 0 or absent: one controller, one port, one owner. The console's boot-arg and this
 *    one are exclusive, and image_tool_usbhost refuses an image with both. The result goes to the msgbuf and comes back
 *    in the ramdump (the deadline panic ends the boot, ABL's ramdump/fastboot path re-initialises USB as a device);
 *  - refused unless this boot's shim stamps say its gadget came up and handed off (as blazer_usbcon): the proof that
 *    the controller is powered and clocked before the first DWC3 read;
 *  - a kernel thread sleeps blazer_usbhost_wait seconds (default 90): the owner unplugs the Mac and plugs the test
 *    device in that window. Then the core stops the shim's gadget, switches the DWC3 to host, starts the xHCI, powers the
 *    USB2 root ports only, waits up to blazer_usbhost_window seconds (default 150) for a connect and enumerates it;
 *  - DMA arena: 64 KiB at 0xbee00000, inside abl@be000000 (FDT-reserved for ABL, unused after the handoff; the same
 *    reservation blazer_usbcon and blazer_usbnet use), refused if it overlaps the shim's stamped console arena. Not the
 *    FDT's xhci_dma pools (0x09010000 AoC SRAM, 0x97000000): those are Android's/AoC's;
 *  - never sources VBUS, never writes the PHY, TCA, dp_top_csr, repeater, TCPC, charger, clocks, resets or the CPM.
 */
#if defined(BLAZER)
#include <kern/clock.h>
#include <kern/debug.h>
#include <kern/misc_protos.h>
#include <kern/sched.h>
#include <kern/startup.h>
#include <kern/thread.h>
#include <mach/mach_time.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
#include <stdbool.h>
#include <stdint.h>

TUNABLE(uint32_t, blazer_usbhost_mode, "blazer_usbhost", 0);
TUNABLE(uint32_t, blazer_usbhost_wait, "blazer_usbhost_wait", 90);
TUNABLE(uint32_t, blazer_usbhost_window, "blazer_usbhost_window", 150);

extern const volatile unsigned char *blazer_stamp_page(void);

#define UH_DWC3_PA              0x0c400000ULL   /* FDT dwc3@c400000, 0xd060; xHCI at 0x0..0x7fff */
#define UH_DWC3_MAP             0x10000u
#define UH_TCA_PA               0x0c430000ULL   /* FDT usb_phy dptx_tca_regs, 0x1000. Read only */
#define UH_DPTOP_PA             0x0c637000ULL   /* FDT usb_phy dp_top_csr, 0xa0. Read only */
#define UH_GLUE_PA              0x0c450000ULL   /* FDT usb3@c450000 usbcs_host_cfg_csr, 0x14. Read only */
#define UH_ABL_MIN              0xbe000000ULL   /* FDT abl@be000000, 16 MiB */
#define UH_ABL_MAX              0xbf000000ULL
#define UH_ARENA_PA             (UH_ABL_MAX - 0x200000ULL)      /* below blazer_usbnet's last MiB */
#define UH_CONSOLE_ARENA        0x200u          /* blazer_usbcon UC_ARENA_BYTES */

/* shim/tgl_stamp.h, read-only here; the same checks as blazer_usbcon's usbcon_admit. */
#define UH_STAMP_MAGIC          0x3254534d49485354ULL   /* "TSHIMST2" */
#define UH_STAMP_SLOTS          128u
#define UH_STAMP_R_HANDOFF      5u
#define UH_STAGE_DMA_ADMIT      0x0008u
#define UH_STAGE_EP0_READY      0x0010u
#define UH_STAMP_F_DONE         0x0002u

struct uh_stamp_header {
	uint64_t magic, nonce;
	uint32_t count, seq, last_stage, flags;
	uint64_t freq, t0, tlast;
	uint32_t dropped, reason;
};
struct uh_stamp_slot {
	uint32_t seq;
	uint16_t stage, flags;
	uint64_t t, arg;
};
_Static_assert(sizeof(struct uh_stamp_header) == 64, "TSHIMST2 header");
_Static_assert(sizeof(struct uh_stamp_slot) == 24, "TSHIMST2 slot");

struct uh_arena {
	uintptr_t va;
	uint64_t pa;
};
static struct uh_arena uh_mem;
static uintptr_t uh_regs, uh_tca, uh_dptop, uh_glue;

static inline void
uh_dsb(void)
{
	__asm__ volatile ("dsb sy" ::: "memory");
}

static inline uint32_t uh_rd(uint32_t off) { return *(volatile uint32_t *)(uh_regs + off); }
static inline void uh_wr(uint32_t off, uint32_t value) { *(volatile uint32_t *)(uh_regs + off) = value; uh_dsb(); }
static inline uint32_t uh_tca_rd(uint32_t off) { return *(volatile uint32_t *)(uh_tca + off); }
static inline uint32_t uh_dptop_rd(uint32_t off) { return *(volatile uint32_t *)(uh_dptop + off); }
static inline uint32_t uh_glue_rd(uint32_t off) { return *(volatile uint32_t *)(uh_glue + off); }
static inline uint64_t uh_ticks(void) { return mach_absolute_time(); }
static inline uint64_t uh_hz(void) { return __builtin_arm_rsr64("CNTFRQ_EL0"); }
static inline void uh_sleep_ms(unsigned ms) { delay_for_interval(ms, NSEC_PER_MSEC); }

#define UH_SAY(...) printf(__VA_ARGS__)

#include "blazer_usbhost_core.inc"

static void
usbhost_thread(__unused void *parameter, __unused wait_result_t result)
{
	unsigned wait_s = blazer_usbhost_wait, window_s = blazer_usbhost_window;

	for (unsigned s = 0; s < wait_s; s++) {
		if (s % 30 == 0) {
			printf("blazer-usbhost: host mode in %u s: unplug the Mac, plug the device\n", wait_s - s);
		}
		uh_sleep_ms(1000);
	}
	uh_regs = (uintptr_t)ml_io_map((vm_offset_t)UH_DWC3_PA, UH_DWC3_MAP);
	uh_tca = (uintptr_t)ml_io_map((vm_offset_t)UH_TCA_PA, 0x1000);
	uh_dptop = (uintptr_t)ml_io_map((vm_offset_t)UH_DPTOP_PA, 0x100);
	uh_glue = (uintptr_t)ml_io_map((vm_offset_t)UH_GLUE_PA, 0x100);
	/* Not DRAM to pmap: VM_WIMG_IO, Device-nGnRnE, so no cache maintenance between the core and the xHCI. */
	uh_mem.va = (uintptr_t)ml_io_map((vm_offset_t)uh_mem.pa, UH_ARENA_BYTES);
	if (uh_regs == 0 || uh_tca == 0 || uh_dptop == 0 || uh_glue == 0 || uh_mem.va == 0) {
		printf("blazer-usbhost: cannot map\n");
	} else {
		(void)uh_run(window_s);
	}
	(void)thread_terminate(current_thread());
	thread_block(THREAD_CONTINUE_NULL);
}

/* RAM only, and the boot-args. Says why not, and that's the end of it. */
static const char *
usbhost_admit(void)
{
	const volatile unsigned char *page = blazer_stamp_page();
	const volatile struct uh_stamp_header *h = (const volatile struct uh_stamp_header *)page;
	const volatile struct uh_stamp_slot *slot = (const volatile struct uh_stamp_slot *)(page + sizeof(*h));
	uint32_t console = 0, count;
	uint64_t dma = 0;
	bool ready = false;

	if (PE_parse_boot_argn("blazer_usbcon", &console, sizeof(console)) && console != 0) {
		return "blazer_usbcon owns the controller (host mode needs blazer_usbcon=0; results come back in the ramdump)";
	}
	if (blazer_usbhost_mode != 1) {
		return "unknown mode";
	}
	if (blazer_usbhost_window == 0 || blazer_usbhost_window > 1800 || blazer_usbhost_wait > 1800) {
		return "wait/window out of range (0..1800 s, window > 0)";
	}
	if (page == NULL || h->magic != UH_STAMP_MAGIC) {
		return "no shim stamps";
	}
	if (h->reason != UH_STAMP_R_HANDOFF) {
		return "stamps don't end in a handoff";
	}
	count = h->count;
	if (count > UH_STAMP_SLOTS) {
		return "bad stamp count";
	}
	for (uint32_t i = 0; i < count; i++) {
		uint32_t stage = slot[i].stage, flags = slot[i].flags;
		if (stage == UH_STAGE_DMA_ADMIT && flags == UH_STAMP_F_DONE) {
			dma = slot[i].arg;
			ready = false;
		} else if (stage == UH_STAGE_EP0_READY && flags == UH_STAMP_F_DONE) {
			ready = dma != 0;
		}
	}
	if (!ready) {
		return "shim's gadget didn't come up (controller power and clocks unproven)";
	}
	uh_mem.pa = UH_ARENA_PA;
	if (dma < uh_mem.pa + UH_ARENA_BYTES && uh_mem.pa < dma + UH_CONSOLE_ARENA) {
		return "arena overlaps the shim's console arena";
	}
	if (uh_mem.pa < UH_ABL_MIN || uh_mem.pa + UH_ARENA_BYTES > UH_ABL_MAX) {
		return "arena outside abl@be000000";
	}
	return NULL;
}

/* From kernel_bootstrap_thread, next to blazer_usbcon_start. */
void
blazer_usbhost_start(void)
{
	thread_t thread;
	const char *why;
	kern_return_t kr;

	if (blazer_usbhost_mode == 0) {
		return;
	}
	why = usbhost_admit();
	if (why != NULL) {
		printf("blazer-usbhost: refused: %s\n", why);
		return;
	}
	printf("blazer-usbhost: mode %u, wait %u s, window %u s, arena 0x%llx\n", blazer_usbhost_mode, blazer_usbhost_wait,
	    blazer_usbhost_window, (unsigned long long)uh_mem.pa);
	kr = kernel_thread_start_priority(usbhost_thread, NULL, MAXPRI_KERNEL, &thread);
	if (kr != KERN_SUCCESS) {
		printf("blazer-usbhost: no thread, %d\n", kr);
		return;
	}
	thread_set_thread_name(thread, "blazer_usbhost");
	thread_deallocate(thread);
}
#endif /* BLAZER */
