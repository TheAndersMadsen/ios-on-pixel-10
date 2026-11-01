#pragma once

#include "fdt.h"
#include "laguna_usb.h"

extern volatile uint64_t tgl_failure_record[8];

/* Implemented in shim.c so the EP0 ACK callback reaches the existing PSCI
 * reset path without duplicating its method selection. */
void tgl_usb_reset_now(void);

/* Full ABL/FDT/DMA/CPM admission happens before gadget writes. Returns the
 * laguna_usb_error value (0 on success) and leaves early text in the USB log. */
int tgl_usb_console_start(const struct tgl_fdt_memory *memory);
void tgl_usb_console_service(void);
void tgl_usb_console_wait(unsigned seconds);
