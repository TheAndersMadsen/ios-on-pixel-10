/* Host stand-ins for what blazer_gauge.c takes from XNU, plus a fake smartdv SPMI master with a gauge (SID 6) and a
 * max77779 charger (SID 3) behind it. blazer_gauge.c's spmi_rd/spmi_wr call host_spmi_rd/host_spmi_wr under BLAZER_GAUGE_HOST:
 * a REQ_COMMAND write with bit 0 is one transfer (recorded, answered from the register maps, DONE set); IRQ_STATUS is
 * write-1-to-clear. Test-only. */
#ifndef CHG_HOST_SHIM_H
#define CHG_HOST_SHIM_H
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;

#define os_atomic_load(p, o) __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define os_atomic_store(p, v, o) __atomic_store_n((p), (v), __ATOMIC_RELEASE)

struct fake_frame { unsigned op, sid, reg, bytes; };
extern uint32_t fake_spmi[0x300 / 4];
extern struct fake_frame fake_frames[4096];
extern unsigned fake_nframes;
extern uint16_t fake_gauge[256];
extern uint8_t fake_chg[256];
extern int fake_err_sid, fake_err_reg;     /* answer this frame with an error bit (bit 2) */
extern char fake_log[1 << 16];
extern size_t fake_log_len;
extern const char *fake_args[16];

int printf_shim(const char *fmt, ...);
#define printf printf_shim
#define IOLog printf_shim
void delay(unsigned us);
uint32_t host_spmi_rd(uint32_t off);
void host_spmi_wr(uint32_t off, uint32_t value);
void IOSleep(unsigned ms);
__attribute__((noreturn)) void panic(const char *fmt, ...);
vm_offset_t ml_io_map(vm_offset_t pa, vm_size_t size);
bool PE_parse_boot_argn(const char *name, void *out, int size);
#endif
