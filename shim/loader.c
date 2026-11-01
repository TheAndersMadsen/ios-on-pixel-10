/*
 * Milestone 4: act as iBoot for xnu.
 *
 * mkpayload.py already resolved the kernel's chained fixups and built the
 * ADT, so this only has to: find the payload in the ABL ramdisk, copy the
 * segments to phys_base + (vmaddr - virt_base), place the ADT and
 * boot_args behind the kernel, and jump to the entry point with the MMU
 * and caches off, x0 = boot_args (physical).
 */
#include <stdint.h>
#include "console.h"
#include "fdt.h"
#include "loader.h"
#include "payload.h"
#include "handoff.h"
#include "tgl_stamp.h"
#include "tgl_usb_console.h"
#include "laguna_usb.h"
#include "tgl_display.h"
#include "tgl_ufs.h"

#define BOOT_LINE_LENGTH	1024	/* xnu-12377 pexpert/arm64/boot.h; was 608 on 8796 */
#define PAGE_16K		0x4000UL

/* pexpert/pexpert/arm64/boot.h, Revision/Version 2 */
struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};

struct boot_args {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
	struct boot_video Video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char CommandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags, memSizeActual;
};

_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8, "payload header layout");
_Static_assert(__builtin_offsetof(struct boot_args, Video) == 40, "boot_args layout");
_Static_assert(__builtin_offsetof(struct boot_args, CommandLine) == 108, "boot_args layout");
_Static_assert(sizeof(struct boot_args) == 1152, "boot_args layout");
_Static_assert(__builtin_offsetof(struct boot_args, bootFlags) == 1136, "12377 boot_args layout");
_Static_assert(__builtin_offsetof(struct boot_args, memSizeActual) == 1144, "12377 boot_args layout");

/* MMU off: everything is Device memory, so copy in aligned 8-byte words. */
static void zero64(uintptr_t dst, uint64_t n)
{
	volatile uint64_t *d = (volatile uint64_t *)dst;
	for (uint64_t i = 0; i < n / 8; i++)
		d[i] = 0;
}

typedef void (*xnu_entry_t)(uint64_t boot_args_pa);

/* B1 entry contract (start.S): the tegu-proven EL2→EL1 drop + final jump.
 * Stamps EL_DROP ENTER before / DONE (new EL) + reason HANDOFF after the
 * eret, I-cache invalidate, then branches to entry with x0 = boot_args PA.
 * Never returns. */
extern void tegu_el_drop_and_jump(uint64_t entry_pa, uint64_t ba_pa)
    __attribute__((noreturn));

const char *loader_boot(uintptr_t dtb)
{
	/* The linked image includes BSS and both stack areas. Never let XNU's
	 * allocator overwrite the code/input executing this planning pass. */
	extern char _head[], _end[];
	static struct tgl_fdt_memory memory;
	/* Step breadcrumbs + refusal-text stamps: the fb console is dead
	 * (CDPHY off at handoff), so every refusal names itself in the stamp
	 * channel — 8 chars of the error text, little-endian in the arg —
	 * and every completed step leaves a DONE stamp with its step id. */
	#define LB_STEP(n) tgl_stamp(TGL_STAGE_PAYLOAD, TGL_STAMP_F_DONE, (n))
	#define LB_FAIL(err) do { \
		uint64_t lb_txt = 0; \
		if (err) for (int lb_i = 0; lb_i < 8 && (err)[lb_i]; ++lb_i) \
			lb_txt |= (uint64_t)(uint8_t)(err)[lb_i] << (8 * lb_i); \
		tgl_stamp(TGL_STAGE_PAYLOAD, TGL_STAMP_F_REFUSED, lb_txt); \
	} while (0)
	if (!dtb || (dtb & 7)) { LB_FAIL("unaligned/missing FDT"); return "unaligned/missing FDT"; }
	const char *error = tgl_fdt_memory((const void *)dtb, TGL_FDT_MAX_SIZE, &memory);
	if (error) { LB_FAIL(error); return error; }
	LB_STEP(1);
	struct tgl_range shim = { (uintptr_t)_head, (uintptr_t)_end - (uintptr_t)_head };
	struct tgl_range rd;
	error = tgl_handoff_inputs(&memory, dtb, shim, &rd);
	if (error) { LB_FAIL(error); return error; }
	LB_STEP(2);
	uint64_t rd_start = rd.base, rd_end = rd.base + rd.size;
	con_hex2("INITRD", "lo=", rd_start, "hi=", rd_end);

	struct tgl_payload_view view;
	{	/* B1 entry contract: embedded TEGUPLD1 payload first (tegu
		 * loader.c:93-104 delivery), ABL-initrd scan as fallback. The
		 * diagnostic build has no envelope (image_size == _end offset)
		 * so the embedded probe reads nothing and falls through. */
		uintptr_t esrc = 0;
		uint64_t ebytes = 0;
		const char *emb = tgl_payload_embedded(&esrc, &ebytes);
		if (emb == TGL_PAYLOAD_NO_EMBEDDED) {
			error = tgl_payload_find(rd_start, rd_end, &view);
			if (error) { LB_FAIL(error); return error; }
		} else {
			if ((esrc & 7)) { LB_FAIL("misaligned embedded payload"); return "misaligned embedded payload"; }
			LB_STEP(3);
			error = tgl_payload_validate(esrc, ebytes, rd_start,
			    rd.size, &view);
			if (error) { LB_FAIL(error); return error; }
			LB_STEP(4);
			/* tegu loader.c:29 equivalent: an embedded source lives
			 * with the shim far below the window, but the check must
			 * be explicit — a window in the shim's own bank would
			 * scribble over the image we are still executing. */
			struct tgl_range esr = { esrc, ebytes };
			struct tgl_range win = { view.payload->phys_base,
						 view.payload->mem_size };
			if (tgl_ranges_overlap(esr, win)) {
				LB_FAIL("embedded payload overlaps destination window");
				return "embedded payload overlaps destination window";
			}
			con_hex2("EMBED", "src=", esrc, "bytes=", ebytes);
		}
	}
	const struct payload *p = view.payload;
	/* v3.9 honest handoff (PLAN.md 4.3, P2 lane): before this cmdline
	 * can reach boot_args, gate it on the UFS ladder's LIVE attestation
	 * (shim_main 6.5 ran the ladder). Without U8 the rewrite drops every
	 * blazer_ufs* token and substitutes rd=ufsroot0 -> rd=md0 — the
	 * shrink-only in-place edit of the payload's 608-byte field. A
	 * malformed (unterminated) field refuses the whole boot. */
	if (tgl_ufs_cmdline_admit((char *)p->cmdline, tgl_ufs_result()) < 0) {
		LB_FAIL("malformed cmdline");
		return "malformed cmdline";
	}
	struct tgl_range window = { p->phys_base, p->mem_size };
	struct tgl_range console = { con_fb_pa, con_fb_pa ? FB_STRIDE * FB_H : 0 };
	/* Window vs FDT RAM + FDT reservations + resident inputs. The console
	 * range is checked separately: the live scanout can sit inside the
	 * kernel-managed window, and refusing there would again hide every
	 * later finding — v2 prints the overlap and continues. */
	struct tgl_range none = {0, 0};
	error = tgl_handoff_window(&memory, window, dtb, shim, rd,
	    console.size ? none : console);
	if (error) { LB_FAIL(error); return error; }
	LB_STEP(5);
	if (console.size && tgl_ranges_overlap(window, console))
		con_str("FBWIN", "console inside kernel window; reported, not fatal");
	/* B1 §3.5: the ramoops zone hosts TSHIMST2 (0x95430000) and the kexec
	 * marker page (0x95400000) — XNU's allocator must never claim it. */
	{
		struct tgl_range ramoops = { UINT64_C(0x95200000),
					     UINT64_C(0x400000) };
		if (tgl_ranges_overlap(window, ramoops)) {
			LB_FAIL("payload window overlaps ramoops zone");
			return "payload window overlaps ramoops zone";
		}
	}
	LB_STEP(6);
	/* RESERVED is a placement proof, not a producer wish. The framebuffer
	 * must be outside XNU's allocator and clear of every resident input;
	 * otherwise the sealed record deliberately loses that required flag. */
	if (console.size) {
		struct tgl_range tree = { dtb, memory.total_size };
		struct tgl_range ramoops = { UINT64_C(0x95200000), UINT64_C(0x400000) };
		int reserved = !tgl_ranges_overlap(window, console) &&
			!tgl_ranges_overlap(shim, console) &&
			!tgl_ranges_overlap(tree, console) &&
			!tgl_ranges_overlap(rd, console) &&
			!tgl_ranges_overlap(ramoops, console);
		tgl_display_set_reserved(reserved);
	}
	/* FDT reservations inside the window are REPORTED, not fatal: the
	 * kexec-proven device geometry (0x80000000 + 256M) itself overlaps
	 * pkvm_guest_firmware (0x8af00000) and the payload boots. The carveout
	 * inventory rides the console for the kernel lane to adopt. */
	{
		unsigned nconf = 0;
		uint64_t first = 0, first_size = 0;
		for (unsigned i = 0; i < memory.reserved_count; ++i)
			if (tgl_ranges_overlap(window, memory.reserved[i])) {
				if (!nconf) {
					first = memory.reserved[i].base;
					first_size = memory.reserved[i].size;
				}
				++nconf;
			}
		if (nconf) {
			con_str("RAMGATE", "FDT reservations in window; reported, not fatal");
			con_hex2("RAMGATE", "n=", nconf, "base=", (uint32_t)first);
			con_hex("RAMHI", first >> 32);
			con_hex("RAMSZ", first_size);
		}
	}
	/* ABL places the boot ramdisk inside the kernel-managed window on the
	 * device (capture: initrd 0x86000000, window 0x80000000+): that is the
	 * proven delivery geometry. The segment copy stays correct iff every
	 * destination is BELOW its source (ascending copy then reads each
	 * source byte before the frontier clobbers it) and the metadata
	 * placement never overlaps the source. Otherwise: refuse with numbers. */
	if (tgl_ranges_overlap(rd, window)) {
		if (view.source <= p->phys_base)
			return "ramdisk below kernel window; ascending copy unsafe";
		con_str("RDWIN", "ramdisk inside window; ascending copy safe");
	}
	struct tgl_range meta = { view.adt_pa, view.top - view.adt_pa };
	if (tgl_ranges_overlap(meta, rd))
		return "metadata placement overlaps ramdisk";
#ifdef TGL_QEMU_TEST
	if (!memory.compatible[0] || !tgl_qemu_profile(memory.compatible))
		return "QEMU test profile cannot authorize physical handoff";
#endif
	uint64_t el, sctlr;
	__asm__ volatile("mrs %0, CurrentEL; mrs %1, sctlr_el1" : "=r"(el), "=r"(sctlr));
	/* B1 entry contract: ABL releases us at EL2 (device-measured cpu-state
	 * 0x80d01998). The gate still refuses a non-firmware-style state — but
	 * EL2 is now SATISFIED by the tegu-proven EL2→EL1 drop performed at
	 * the final jump (tegu_el_drop_and_jump), never by weakening it. */
	if ((el != 4 && el != 8) || (sctlr & ((UINT64_C(1) << 25) | 5)))
		return "handoff requires little-endian, MMU and D-cache off (EL1/EL2)";
	con_hex2("PAYLOAD", "base=", view.source, "prefix=", view.source - rd_start);

	uint64_t pa_of_va_base = p->phys_base - p->virt_base;	/* pa = va + this */
	con_hex2("PHYS", "base=", p->phys_base, "size=", p->mem_size);
	con_hex("VIRT", p->virt_base);
	con_hex("ENTRY", p->entry_va);

	for (uint32_t i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		uintptr_t dst = s->vmaddr + pa_of_va_base;
		tgl_usb_console_service();
		tgl_segment_copy(dst, view.source + s->file_off, s->file_size, s->vmsize);
	}
	con_hex2("SEGS", "n=", p->nsegs, "end=", p->kernel_end + pa_of_va_base);

	/* ADT, then boot_args, behind the kernel; everything below topOfKernelData is ours. */
	uintptr_t adt_pa = view.adt_pa;
	tgl_segment_copy(adt_pa, view.source + p->adt_off, p->adt_size,
	    (p->adt_size + 7) & ~UINT64_C(7));
	uintptr_t ba_pa = view.ba_pa;
	uintptr_t top = view.top;

	zero64(ba_pa, PAGE_16K);
	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->Revision = 2;
	ba->Version = 2;
	ba->virtBase = p->virt_base;
	ba->physBase = p->phys_base;
	ba->memSize = p->mem_size;
	ba->topOfKernelData = top;
	if (con_fb_pa) {
		ba->Video.v_baseAddr = con_fb_pa;
		ba->Video.v_display = 1;
		ba->Video.v_rowBytes = FB_STRIDE;
		ba->Video.v_width = FB_W;
		ba->Video.v_height = FB_H;
		ba->Video.v_depth = 32;
	} /* Otherwise all Video fields remain zero: a headless contract. */
	ba->deviceTreeP = adt_pa - pa_of_va_base;	/* xnu reads it with the MMU on: a VA */
	ba->deviceTreeLength = (uint32_t)p->adt_size;
	for (int i = 0; i < TGL_BOOT_LINE_LENGTH; i++) /* payload field stays 608; rest stays zero */
		ba->CommandLine[i] = p->cmdline[i];
	ba->memSizeActual = p->mem_size;
	/* The second half of this 16 KiB metadata page is below topOfKernelData
	 * and outside boot_args proper. Publish the exact 128 bytes, never a
	 * pointer to the shim's reclaimable BSS. */
	uintptr_t display_record_pa = ba_pa + 0x1000;
	tgl_display_export(display_record_pa);
	int display_adt_rc = tgl_display_adt_publish(adt_pa, p->adt_size,
	    display_record_pa);
#ifdef TGL_QEMU_TEST
	if (display_adt_rc && display_adt_rc != TGL_DISPLAY_ADT_NOT_FOUND)
		return "display handoff ADT publish failed";
#else
	if (display_adt_rc) return "display handoff ADT publish failed";
#endif
	con_hex2("BOOTARG", "pa=", ba_pa, "top=", top);

	uintptr_t entry_pa = view.entry_pa;
	/* Admission just blocked for seconds with USB unserved, so the host's next read is often
	 * pending and the service call below starts it. Let that one finish; still refuse if not. */
	{
		extern int tgl_stamp_boot_us(uint64_t *);
		uint64_t usb_t0 = 0, usb_now = 0;
		uint32_t usb_spins = 0; /* dead-counter cap, as tgl_usb_console_wait */
		tgl_usb_console_service();
		if (!tgl_stamp_boot_us(&usb_t0))
			while (laguna_usb_transfer_active() && !tgl_stamp_boot_us(&usb_now) &&
			    usb_now - usb_t0 < UINT64_C(1000000) &&
			    ++usb_spins < UINT32_C(10000000))
				tgl_usb_console_service();
	}
	if (laguna_usb_transfer_active()) return "USB transfer active at XNU handoff";
	/* v3.6 global bring-up deadline: after the jump only the EP0 log's
	 * last bytes and the DRAM mirror can tell the story, so bail with a
	 * stamped reason while we still own the machine. */
	if (tgl_stamp_over_deadline(90)) {
		tgl_stamp_reason(TGL_STAMP_R_TIMEOUT);
		return "global bring-up deadline exceeded";
	}
	tgl_stamp(TGL_STAGE_PAYLOAD, TGL_STAMP_F_DONE, entry_pa);
	tgl_stamp(TGL_STAGE_HANDOFF, TGL_STAMP_F_ENTER, ba_pa);
	con_hex("JUMP", entry_pa);
	con_str("XNU", "jumping (EL1 drop, fbcon clears screen)");
	/* B1 entry contract: the tegu-proven EL2→EL1 drop runs HERE (after
	 * payload load, composing with the v3.5 warm-skip diagnostics that
	 * run at EL2). The asm continuation stamps EL_DROP DONE (new EL) and
	 * the final reason=HANDOFF, executes `dsb sy; ic iallu; dsb sy; isb`,
	 * and branches with x0 = boot_args PA — register-for-register the
	 * handoff that physically reached XNU PID1 on tegu. */
	tgl_stamp(TGL_STAGE_EL_DROP, TGL_STAMP_F_ENTER, el);
	tegu_el_drop_and_jump(entry_pa, ba_pa);
	return "unreachable";
}
