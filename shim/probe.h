#pragma once
#include <stdint.h>

/*
 * Fault-gated MMIO/memory probes (v2).
 *
 * Every probe arms the exception return path, performs ONE aligned access,
 * and reports whether it survived. A fault in a probe is recovered in
 * exc_handler (ESR.EC==0x25 data abort: ELR advanced past the access,
 * probe_hit set) instead of ending in the panic screen, so unknown device
 * state can be INTERROGATED — and the exact fault (ESR/FAR/PA) is carried
 * into the findings the console (or the panic screen) prints.
 *
 * MMU off: every access is Device memory, -mstrict-align keeps all probes
 * aligned. No pointer tables: literals and immediates only (ABS64 contract).
 */

/* Set by exc_handler when a probe faults. */
extern volatile int probe_hit;
/* Fault record of the LAST recovered probe fault. */
extern volatile uint64_t probe_esr, probe_far, probe_pa;
extern volatile unsigned probe_wr;

/* Single fault-gated accesses. Return 1 = survived (value stored), 0 = fault. */
int probe_read32(uintptr_t pa, uint32_t *out);
int probe_read64(uintptr_t pa, uint64_t *out);
int probe_write32(uintptr_t pa, uint32_t v);
/* Exception hook: returns 1 when the fault belonged to an armed probe and
 * ELR was advanced past it (caller just erets). */
int probe_recover(uint64_t esr, uint64_t far_el1);

/* --- DC9x00 display-controller readout (read-only).
 * Source pin: GrapheneOS kernel_pixel_6.6 fac4effc829311dabd53d2d0e8cc3090318e6453
 * private/google-modules/display/vsi-drm/verisilicon/9x00/vs_dc_reg_fe0.h via
 * research/reuse-audit-20261024/display/dc9x00_readout.h. MAIN layer fields
 * (not EX_*); a programmed address is a DMA/IOVA until mapping is proven. */
#define TGL_DPU_BASE		UINT64_C(0x0ee00000) /* live DT: /sswrp_dpu@ec00000/dc9x00@200000 */
#define TGL_DPU_CHIP_ID		0x20U
#define TGL_DPU_ADDR_LO		0x2cU
#define TGL_DPU_ADDR_HI		0x30U
#define TGL_DPU_STRIDE		0x44U
#define TGL_DPU_SIZE		0x5cU
#define TGL_DPU_CONFIG		0x88U /* main CONFIG; enable = bit0 */
#define TGL_DPU_OUT0_COORD	0xb6068U /* output0 CURRENT_COORD (live line) */

struct tgl_dpu_state {
	unsigned probed, id_ok, enabled;
	uint32_t chip_id, config, addr_lo, addr_hi, stride, size;
	uint32_t coord0_a, coord0_b; /* two samples of output0 CURRENT_COORD */
	uint64_t esr, far, candidate; /* candidate = live scanout PA, else 0 */
};

/* Fault-gated read-only scan; fills *st, never writes the DPU. */
void probe_dpu(struct tgl_dpu_state *st);
