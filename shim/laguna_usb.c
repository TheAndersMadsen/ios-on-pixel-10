/* Polled DWC3 EP0 diagnostic gadget for the laguna teguload shim.
 *
 * The wire protocol is the hardware-proven Tegu protocol: no bulk endpoints,
 * no iOS USB stack, VID:PID 1209:0001 and product "Tegu USB diagnostic".
 * The board/PHY handoff is deliberately separate: G5 clocks/resets belong to
 * CPM, and this file never turns those firmware IDs into guessed MMIO writes.
 *
 * Standalone use requires MMU/D-cache off and an admitted identity DMA map.
 * A later XNU adapter may supply distinct CPU/device DMA addresses. The log is
 * append-only (not a circular overwrite ring) because the unmodified host
 * reader tracks absolute 32-bit offsets and cannot resynchronize after wrap.
 */
#include "laguna_usb.h"
#include "tgl_stamp.h"

#ifndef LAGUNA_USB_WRITE32
#define LAGUNA_USB_WRITE32(base, off, value) \
    (*(volatile uint32_t *)((base) + (off)) = (value))
#endif
#ifndef LAGUNA_USB_READ32
#define LAGUNA_USB_READ32(base, off) (*(volatile uint32_t *)((base) + (off)))
#endif

#define GCTL            0xc110
#define GSNPSID         0xc120
#define GUSB2PHYCFG     0xc200
#define GEVNTADRLO      0xc400
#define GEVNTADRHI      0xc404
#define GEVNTSIZ        0xc408
#define GEVNTCOUNT      0xc40c
#define DCFG            0xc700
#define DCTL            0xc704
#define DEVTEN          0xc708
#define DSTS            0xc70c
#define DALEPENA        0xc720
#define DEPCMDPAR2(n)   (0xc800 + 0x10 * (n))
#define DEPCMDPAR1(n)   (0xc804 + 0x10 * (n))
#define DEPCMDPAR0(n)   (0xc808 + 0x10 * (n))
#define DEPCMD(n)       (0xc80c + 0x10 * (n))

#define DCTL_RUN_STOP   (1u << 31)
#define DCTL_CSFTRST    (1u << 30)
#define DSTS_DEVCTRLHLT (1u << 22)
#define GCTL_PRTCAPDIR  (3u << 12)
#define GCTL_PRTCAP_DEVICE (2u << 12)
#define GUSB2PHYCFG_SUSPHY (1u << 6)

#define DEPCMD_SETEPCONFIG      1
#define DEPCMD_SETTRANSFRESOURCE 2
#define DEPCMD_SETSTALL         4
#define DEPCMD_STARTTRANSFER    6
#define DEPCMD_DEPSTARTCFG      9
#define DEPCMD_CMDACT           (1u << 10)

#define TRB_HWO         (1u << 0)
#define TRB_LST         (1u << 1)
#define TRB_CHN         (1u << 2)
#define TRB_ISP_IMI     (1u << 10)
#define TRB_IOC         (1u << 11)
#define TRBCTL_SETUP    (2u << 4)
#define TRBCTL_STATUS2  (3u << 4)
#define TRBCTL_STATUS3  (4u << 4)
#define TRBCTL_DATA     (5u << 4)

#define UD_EVT          0x0000
#define UD_EVT_SIZE     0x0040 /* 16 events; bounded EP0 traffic is polled. */
#define UD_TRB_OUT      0x0040
#define UD_TRB_IN       0x0050
#define UD_TRB_IN_ZLP   0x0060 /* contiguous second IN TRB; within admitted arena */
#define UD_SETUP        0x0070
#define UD_DATA         0x0080
#define UD_DATA_MAX     512
#define UD_OUT_ARMED    64

#define USB2_CFG19      0x0
#define USB2_CFG21      0x8
#define USB2_CFG21_PHY_ENABLE (1u << 12)
#define USBDP_PHY_CFG1  0x28
#define USBDP_POWER_CFG1 0x48

#define TFB_HEADER_SIZE 32u
#define TFB_FORMAT_BGRA 0x42475241u
#define TFB_FLAG_TOP_DOWN 1u
#define TFB_FLAG_BGRA8 2u
#define TFB_FLAG_SCALED 4u
#define TFB_SCALED_BIT (1u << 31)
#define TFB_MAX_PAYLOAD (64u << 20)

static void barrier(void)
{
#ifdef __aarch64__
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}

static void delay_us(unsigned us)
{
#ifdef __aarch64__
    uint64_t freq, now, end;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
    if (!freq) freq = 38400000;
    __asm__ volatile("mrs %0, cntpct_el0" : "=r"(now));
    end = now + (freq * us + 999999) / 1000000;
    /* A dead arch timer must not become an infinite spin (18:37 hang
     * class): bound the iterations independently of the counter. */
    uint64_t guard = 512 + (uint64_t)us * 512;
    do {
        __asm__ volatile("isb\n\tmrs %0, cntpct_el0" : "=r"(now));
    } while (now < end && --guard);
#else
    (void)us;
#endif
}

static void copy_bytes(volatile void *destination, const volatile void *source, size_t length)
{
    volatile uint8_t *d = destination;
    const volatile uint8_t *s = source;
    while (length--) *d++ = *s++;
}

static void zero_bytes(volatile void *destination, size_t length)
{
    volatile uint8_t *d = destination;
    while (length--) *d++ = 0;
}

static uint16_t get16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (uint16_t)p[1] << 8);
}

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
        (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint64_t get64(const uint8_t *p)
{
    return (uint64_t)get32(p) | (uint64_t)get32(p + 4) << 32;
}

static void put16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

static void put32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
    p[2] = (uint8_t)(value >> 16);
    p[3] = (uint8_t)(value >> 24);
}

/* The host recognizes this exact capability string in its first 1024 bytes. */
static const char capability[] = "TEGU USB: log32 1048576\n";
static uint8_t log_buffer[LAGUNA_USB_LOG_CAPACITY];
static uint32_t log_used;
static uint32_t log_dropped;
static uint8_t input_queue[256];
static uint32_t input_read, input_write;

static void append_bytes(const void *bytes, size_t length)
{
    const uint8_t *p = bytes;
    while (length--) {
        if (log_used == sizeof(log_buffer)) {
            log_dropped++;
            continue;
        }
        log_buffer[log_used++] = *p++;
    }
}

static void ensure_capability(void)
{
    if (!log_used) append_bytes(capability, sizeof(capability) - 1);
}

void laguna_usb_write(const void *bytes, size_t length)
{
    if (!bytes && length) return;
    ensure_capability();
    append_bytes(bytes, length);
}

void laguna_usb_putc(uint8_t byte)
{
    laguna_usb_write(&byte, 1);
}

void laguna_usb_log(const char *line)
{
    if (!line) return;
    ensure_capability();
    while (*line) append_bytes(line++, 1);
    append_bytes("\n", 1);
}

void laguna_usb_log_hex(const char *label, uint64_t value)
{
    char line[80];
    static const char digits[] = "0123456789abcdef";
    size_t n = 0;
    if (!label) label = "";
    while (*label && n < 48) line[n++] = *label++;
    if (n < 64) line[n++] = ' ';
    for (int shift = 60; shift >= 0 && n < 65; shift -= 4)
        line[n++] = digits[(value >> shift) & 15];
    line[n] = 0;
    laguna_usb_log(line);
}

int laguna_usb_getc(void)
{
    if (input_read == input_write) return -1;
    return input_queue[(input_read++) & 255];
}

uint32_t laguna_usb_dropped_bytes(void)
{
    return log_dropped;
}

static void (*reboot_handler)(void *context);
static void *reboot_context;
static volatile uint64_t *stamp_sink;

void laguna_usb_set_reboot_handler(void (*handler)(void *context), void *context)
{
    reboot_handler = handler;
    reboot_context = context;
}

void laguna_usb_set_stamp_sink(volatile uint64_t slots[LAGUNA_USB_STAMP_SLOTS])
{
    stamp_sink = slots;
}

struct framebuffer_source {
    const volatile uint8_t *pixels;
    uint32_t width, height, row_bytes;
};
static struct framebuffer_source framebuffer;

void laguna_usb_set_framebuffer(const volatile uint8_t *pixels,
    uint32_t width, uint32_t height, uint32_t row_bytes)
{
    /* Publish the pointer last. A malformed geometry disables capture. */
    framebuffer.pixels = 0;
    barrier();
    framebuffer.width = width;
    framebuffer.height = height;
    framebuffer.row_bytes = row_bytes;
    barrier();
    framebuffer.pixels = pixels;
}

static uint32_t framebuffer_header(uint8_t header[TFB_HEADER_SIZE],
    uint32_t width, uint32_t height, uint32_t row_bytes, uint32_t flags)
{
    uint64_t payload = (uint64_t)row_bytes * height;
    if (!width || !height || width > 16384 || height > 16384 ||
        row_bytes < width * 4u || payload > TFB_MAX_PAYLOAD ||
        payload > UINT32_MAX - TFB_HEADER_SIZE) return 0;
    zero_bytes(header, TFB_HEADER_SIZE);
    header[0] = 'T'; header[1] = 'F'; header[2] = 'B'; header[3] = '1';
    put16(header + 4, TFB_HEADER_SIZE);
    put16(header + 6, 1);
    put32(header + 8, width);
    put32(header + 12, height);
    put32(header + 16, row_bytes);
    put32(header + 20, TFB_FORMAT_BGRA);
    put32(header + 24, (uint32_t)payload);
    put32(header + 28, flags);
    return TFB_HEADER_SIZE;
}

static uint32_t framebuffer_read(uint32_t offset, volatile uint8_t *out, uint32_t capacity)
{
    uint8_t header[TFB_HEADER_SIZE];
    const struct framebuffer_source *s = &framebuffer;
    uint32_t copied = 0;
    if (!s->pixels || !out || !capacity) return 0;

    if (offset & TFB_SCALED_BIT) {
        uint32_t scale = (offset >> 27) & 15u;
        uint32_t w, h, row;
        offset &= (1u << 27) - 1u;
        if (scale < 2 || s->width < scale || s->height < scale) return 0;
        w = s->width / scale;
        h = s->height / scale;
        row = w * 4u;
        if (!framebuffer_header(header, w, h, row,
            TFB_FLAG_TOP_DOWN | TFB_FLAG_BGRA8 | TFB_FLAG_SCALED)) return 0;
        uint32_t payload = row * h;
        if ((uint64_t)payload + TFB_HEADER_SIZE >= (1u << 27) ||
            offset >= payload + TFB_HEADER_SIZE) return 0;
        while (capacity && offset < TFB_HEADER_SIZE) {
            *out++ = header[offset++]; capacity--; copied++;
        }
        while (capacity && offset < payload + TFB_HEADER_SIZE) {
            uint32_t p = offset - TFB_HEADER_SIZE;
            uint32_t y = p / row, x = (p % row) / 4u, c = p % 4u;
            *out++ = s->pixels[(uint64_t)y * scale * s->row_bytes +
                (uint64_t)x * scale * 4u + c];
            offset++; capacity--; copied++;
        }
        return copied;
    }

    uint64_t payload64 = (uint64_t)s->row_bytes * s->height;
    if (!framebuffer_header(header, s->width, s->height, s->row_bytes,
        TFB_FLAG_TOP_DOWN | TFB_FLAG_BGRA8)) return 0;
    uint32_t payload = (uint32_t)payload64;
    if (offset >= payload + TFB_HEADER_SIZE) return 0;
    while (capacity && offset < TFB_HEADER_SIZE) {
        *out++ = header[offset++]; capacity--; copied++;
    }
    if (capacity) {
        uint32_t left = payload + TFB_HEADER_SIZE - offset;
        uint32_t count = capacity < left ? capacity : left;
        copy_bytes(out, s->pixels + offset - TFB_HEADER_SIZE, count);
        copied += count;
    }
    return copied;
}

enum ep0_state { EP0_SETUP, EP0_DATA, EP0_WAIT_STATUS2, EP0_WAIT_STATUS3, EP0_STATUS };
enum out_kind { OUT_NONE, OUT_INPUT, OUT_STAMP };

static struct {
    uintptr_t dwc, dma;
    uint64_t dma_pa;
    uintptr_t usb2_cfg, usbdp_top;
    uint32_t dma_bytes, data_capacity;
    int (*read32)(void *context, uintptr_t base, uint32_t offset, uint32_t *value);
    int (*write32)(void *context, uintptr_t base, uint32_t offset, uint32_t value);
    void *io_context;
    uint32_t evt_pos, events;
    enum ep0_state state;
    bool data_in, running, configured, io_error, stalled, mmio_failed;
    enum out_kind out_kind;
    uint32_t out_length, stamp_slot;
    bool reboot_pending, reboot_queued;
} ud;
static uint8_t dma_area[LAGUNA_USB_DMA_BYTES] __attribute__((aligned(4096)));

uintptr_t laguna_usb_builtin_dma(void)
{
    return (uintptr_t)dma_area;
}

static uint32_t mmio_rd(uintptr_t base, uint32_t off)
{
    uint32_t value = 0;
    if (ud.mmio_failed) return 0;
    if (ud.read32) {
        if (ud.read32(ud.io_context, base, off, &value)) {
            ud.mmio_failed = true;
            ud.io_error = true;
            return 0;
        }
        return value;
    }
    return LAGUNA_USB_READ32(base, off);
}

static void mmio_wr(uintptr_t base, uint32_t off, uint32_t value)
{
    if (ud.mmio_failed) return;
    if (ud.write32) {
        if (ud.write32(ud.io_context, base, off, value)) {
            ud.mmio_failed = true;
            ud.io_error = true;
        }
    } else {
        LAGUNA_USB_WRITE32(base, off, value);
    }
    barrier();
}

static inline void dwc_wr(uint32_t off, uint32_t value)
{
    mmio_wr(ud.dwc, off, value);
}

static inline uint32_t dwc_rd(uint32_t off)
{
    return mmio_rd(ud.dwc, off);
}

static inline uint32_t cfg_rd(uintptr_t base, uint32_t off)
{
    return mmio_rd(base, off);
}

static inline void cfg_wr(uintptr_t base, uint32_t off, uint32_t value)
{
    mmio_wr(base, off, value);
}

static void ud_sync(uint32_t off, uint32_t length)
{
    (void)off; (void)length;
    /* The standalone mapping is non-cacheable. An XNU adapter must either use
     * a non-cacheable CPU mapping too or replace this with cache maintenance. */
    barrier();
}

static int ud_epcmd(unsigned ep, uint32_t command, uint32_t p0, uint32_t p1, uint32_t p2)
{
    dwc_wr(DEPCMDPAR0(ep), p0);
    dwc_wr(DEPCMDPAR1(ep), p1);
    dwc_wr(DEPCMDPAR2(ep), p2);
    dwc_wr(DEPCMD(ep), command | DEPCMD_CMDACT);
    for (unsigned i = 0; i < 1000; i++) {
        uint32_t value = dwc_rd(DEPCMD(ep));
        if (!(value & DEPCMD_CMDACT)) {
            if ((value >> 12) & 0xf) {
                laguna_usb_log_hex("LAGUNA USB: endpoint command status", value);
                ud.io_error = true;
                return -1;
            }
            return 0;
        }
        delay_us(1);
    }
    laguna_usb_log("LAGUNA USB: endpoint command timeout");
    ud.io_error = true;
    return -1;
}

static int ud_start(unsigned ep, uint32_t buffer, uint32_t length, uint32_t control)
{
    uint32_t trb_offset = ep ? UD_TRB_IN : UD_TRB_OUT;
    volatile uint32_t *trb = (volatile uint32_t *)(ud.dma + trb_offset);
    uint64_t buffer_pa = ud.dma_pa + buffer;
    trb[0] = (uint32_t)buffer_pa;
    trb[1] = (uint32_t)(buffer_pa >> 32);
    trb[2] = length;
    trb[3] = control | TRB_HWO | TRB_LST | TRB_ISP_IMI | TRB_IOC;
    ud_sync(trb_offset, 16);
    if (length) ud_sync(buffer, length);
    uint64_t trb_pa = ud.dma_pa + trb_offset;
    return ud_epcmd(ep, DEPCMD_STARTTRANSFER,
        (uint32_t)(trb_pa >> 32), (uint32_t)trb_pa, 0);
}

/* A short control-IN reply whose length is a nonzero multiple of EP0's
 * 64-byte maxpacket needs a zero-length packet. In particular the inherited
 * 512-byte DMA arena leaves 384 data bytes, while usb_log requests 512.
 * Chain a terminal zero-byte DATA TRB, keeping all DMA inside that arena.
 * DWC3's chain bit advances to the physically contiguous next 16-byte TRB.
 */
static int ud_start_in(uint32_t length, uint32_t requested)
{
    if (!length || length >= requested || length % 64)
        return ud_start(1, UD_DATA, length, TRBCTL_DATA);

    volatile uint32_t *first = (volatile uint32_t *)(ud.dma + UD_TRB_IN);
    volatile uint32_t *last = (volatile uint32_t *)(ud.dma + UD_TRB_IN_ZLP);
    uint64_t buffer_pa = ud.dma_pa + UD_DATA;
    last[0] = (uint32_t)buffer_pa;
    last[1] = (uint32_t)(buffer_pa >> 32);
    last[2] = 0;
    last[3] = TRBCTL_DATA | TRB_HWO | TRB_LST | TRB_ISP_IMI | TRB_IOC;
    first[0] = (uint32_t)buffer_pa;
    first[1] = (uint32_t)(buffer_pa >> 32);
    first[2] = length;
    first[3] = TRBCTL_DATA | TRB_HWO | TRB_CHN | TRB_ISP_IMI;
    ud_sync(UD_DATA, length);
    ud_sync(UD_TRB_IN, 32);
    uint64_t trb_pa = ud.dma_pa + UD_TRB_IN;
    return ud_epcmd(1, DEPCMD_STARTTRANSFER,
        (uint32_t)(trb_pa >> 32), (uint32_t)trb_pa, 0);
}

static void ud_start_setup(void)
{
    ud.state = EP0_SETUP;
    (void)ud_start(0, UD_SETUP, 8, TRBCTL_SETUP);
}

static void ud_stall(void)
{
    ud.stalled = true;
    ud.out_kind = OUT_NONE;
    ud.out_length = 0;
    (void)ud_epcmd(0, DEPCMD_SETSTALL, 0, 0, 0);
    ud_start_setup();
}

static const uint8_t device_descriptor[18] = {
    18, 1, 0x00, 0x02, 0x00, 0x00, 0x00, 64,
    0x09, 0x12, 0x01, 0x00, 0x00, 0x01, 1, 2, 3, 1,
};
static const uint8_t config_descriptor[18] = {
    9, 2, 18, 0, 1, 1, 0, 0x80, 250,
    9, 4, 0, 0, 0, 0xff, 0x00, 0x00, 0,
};

static uint32_t string_descriptor(unsigned index, volatile uint8_t *out)
{
    if (index == 0) {
        out[0] = 4; out[1] = 3; out[2] = 0x09; out[3] = 0x04;
        return 4;
    }
    if (index > 3) return 0;
    const char *string = index == 1 ? "ios-laguna" :
        index == 2 ? "Tegu USB diagnostic" : "0001";
    uint32_t n = 2;
    while (*string && n < 126) {
        out[n++] = (uint8_t)*string++;
        out[n++] = 0;
    }
    out[0] = (uint8_t)n;
    out[1] = 3;
    return n;
}

static void ud_setup(void)
{
    const uint8_t *setup = (const uint8_t *)(ud.dma + UD_SETUP);
    volatile uint8_t *data = (volatile uint8_t *)(ud.dma + UD_DATA);
    uint8_t type = setup[0], request = setup[1];
    uint16_t value = get16(setup + 2), index = get16(setup + 4);
    uint16_t length = get16(setup + 6);
    uint32_t n = 0;
    bool ok = true;
    /* Per-request breadcrumb: the host-driven EP0 path is new on hardware —
     * name each served request so a wedge/death names the exact transfer. */
    tgl_stamp(TGL_STAGE_USB_WAIT, TGL_STAMP_F_ENTER,
        (uint32_t)type << 16 | (uint32_t)request << 8 | (length & 0xff));
    ud.stalled = false;
    ud.data_in = (type & 0x80) != 0;
    ud.out_kind = OUT_NONE;
    ud.out_length = 0;
    ud.reboot_pending = false;

    if (!(type == 0xc0 && (request == 0x5a || request == 0x5d)))
        laguna_usb_log_hex("LAGUNA USB: setup",
            (uint32_t)type << 24 | (uint32_t)request << 16 | value);

    if (type == 0xc0 && request == 0x5a) {
        uint32_t offset = value | (uint32_t)index << 16;
        ok = length != 0;
        while (ok && offset < log_used && n < ud.data_capacity && n < length)
            data[n++] = log_buffer[offset++];
    } else if (type == 0x40 && request == 0x5b) {
        ok = !value && !index && length && length <= 64 &&
            length <= sizeof(input_queue) - (input_write - input_read);
        if (ok) { ud.out_kind = OUT_INPUT; ud.out_length = length; }
    } else if (type == 0x40 && request == 0x5c) {
        ok = value == 0x5447 && index == 1 && !length &&
            reboot_handler && !ud.reboot_queued;
        ud.reboot_pending = ok;
    } else if (type == 0xc0 && request == 0x5d) {
        uint32_t offset = value | (uint32_t)index << 16;
        ok = length != 0;
        if (ok) n = framebuffer_read(offset, data,
            length < ud.data_capacity ? length : ud.data_capacity);
    } else if (type == 0x40 && request == 0x5e) {
        ok = index == LAGUNA_USB_STAMP_MAGIC && value < LAGUNA_USB_STAMP_SLOTS &&
            length == 8 && stamp_sink;
        if (ok) {
            ud.out_kind = OUT_STAMP;
            ud.out_length = length;
            ud.stamp_slot = value;
        }
    } else if ((type & 0x60) != 0) {
        ok = false; /* remaining requests must be standard */
    } else if (request == 6) { /* GET_DESCRIPTOR */
        ok = ud.data_in;
        switch (value >> 8) {
        case 1: copy_bytes(data, device_descriptor, sizeof(device_descriptor)); n = sizeof(device_descriptor); break;
        case 2: copy_bytes(data, config_descriptor, sizeof(config_descriptor)); n = sizeof(config_descriptor); break;
        case 3: n = string_descriptor(value & 0xff, data); ok = ok && n != 0; break;
        default: ok = false; break;
        }
    } else if (request == 5) { /* SET_ADDRESS */
        ok = !ud.data_in && !index && !length && value <= 127;
        if (ok) {
            uint32_t dcfg = dwc_rd(DCFG) & ~(0x7fu << 3);
            dwc_wr(DCFG, dcfg | ((uint32_t)value << 3));
            laguna_usb_log_hex("LAGUNA USB: address", value);
        }
    } else if (request == 9) { /* SET_CONFIGURATION */
        ok = !ud.data_in && !index && !length && value <= 1;
        if (ok) ud.configured = value != 0;
    } else if (request == 8) { /* GET_CONFIGURATION */
        ok = ud.data_in && length != 0;
        data[0] = ud.configured ? 1 : 0; n = 1;
    } else if (request == 0) { /* GET_STATUS */
        ok = ud.data_in && length != 0;
        data[0] = 0; data[1] = 0; n = 2;
    } else if (request == 11) { /* SET_INTERFACE (zero endpoints) */
        ok = !ud.data_in && !value && !index && !length;
    } else {
        ok = false;
    }

    tgl_stamp(TGL_STAGE_USB_WAIT, TGL_STAMP_F_DONE,
        ok ? (0x8000u | n) : 0x8001u);
    if (!ok) { ud_stall(); return; }
    if (!length) { ud.state = EP0_WAIT_STATUS2; return; }
    ud.state = EP0_DATA;
    if (ud.data_in) {
        if (n > length) n = length;
        (void)ud_start_in(n, length);
    } else {
        (void)ud_start(0, UD_DATA, UD_OUT_ARMED, TRBCTL_DATA);
    }
}

static void ud_out_complete(void)
{
    enum out_kind kind = ud.out_kind;
    uint32_t expected = ud.out_length;
    if (kind == OUT_NONE) return;
    ud.out_kind = OUT_NONE;
    ud.out_length = 0;
    ud_sync(UD_TRB_OUT, 16);
    ud_sync(UD_DATA, UD_OUT_ARMED);
    uint32_t residual = *(volatile uint32_t *)(ud.dma + UD_TRB_OUT + 8) & 0xffffff;
    if (residual > UD_OUT_ARMED || UD_OUT_ARMED - residual != expected) {
        ud_stall();
        return;
    }
    const volatile uint8_t *data = (const volatile uint8_t *)(ud.dma + UD_DATA);
    if (kind == OUT_INPUT) {
        if (expected > sizeof(input_queue) - (input_write - input_read)) {
            ud_stall();
            return;
        }
        for (uint32_t i = 0; i < expected; i++) input_queue[(input_write++) & 255] = data[i];
    } else if (kind == OUT_STAMP) {
        if (!stamp_sink || ud.stamp_slot >= LAGUNA_USB_STAMP_SLOTS) {
            ud_stall();
            return;
        }
        uint64_t value = get64((const uint8_t *)data);
        stamp_sink[ud.stamp_slot] = value;
        barrier(); /* stamp is committed before the status stage can ACK */
        laguna_usb_log_hex("LAGUNA USB: stamp committed", ud.stamp_slot);
    }
}

static void ud_event(uint32_t event)
{
    if (event & 1) {
        uint32_t type = (event >> 8) & 0xf;
        if (type == 1) { /* USB reset */
            ud.reboot_pending = false;
            ud.configured = false;
            dwc_wr(DCFG, dwc_rd(DCFG) & ~(0x7fu << 3));
            laguna_usb_log("LAGUNA USB: bus reset");
        } else if (type == 2) { /* connect done */
            uint32_t speed = dwc_rd(DSTS) & 7;
            (void)ud_epcmd(0, DEPCMD_SETEPCONFIG,
                (64u << 3) | (2u << 30), (1u << 8) | (1u << 10), 0);
            (void)ud_epcmd(1, DEPCMD_SETEPCONFIG,
                (64u << 3) | (2u << 30), (1u << 8) | (1u << 10) | (1u << 25), 0);
            laguna_usb_log_hex("LAGUNA USB: connected speed", speed);
        } else if (type == 0) {
            ud.reboot_pending = false;
            ud.configured = false;
            laguna_usb_log("LAGUNA USB: disconnect");
        }
        return;
    }

    unsigned ep = (event >> 1) & 0x1f;
    unsigned type = (event >> 6) & 0xf;
    unsigned status = (event >> 12) & 0xf;
    if (ep > 1) return;
    if (type == 1) { /* XferComplete */
        switch (ud.state) {
        case EP0_SETUP:
            ud_sync(UD_SETUP, 8);
            ud_setup();
            break;
        case EP0_DATA:
            if (!ud.data_in) ud_out_complete();
            if (!ud.stalled) ud.state = EP0_WAIT_STATUS3;
            break;
        case EP0_STATUS: {
            bool reboot = ud.reboot_pending;
            ud.reboot_pending = false;
            ud_start_setup(); /* ACK completed; arm the next SETUP first. */
            if (reboot) {
                ud.reboot_queued = true;
                laguna_usb_log("LAGUNA USB: reboot accepted after status ACK");
                if (reboot_handler) reboot_handler(reboot_context);
            }
            break;
        }
        default:
            break;
        }
        return;
    }
    if (type == 3 && status == 2) { /* XferNotReady: control status */
        if (ud.state == EP0_WAIT_STATUS2 || ud.state == EP0_WAIT_STATUS3) {
            uint32_t control = ud.state == EP0_WAIT_STATUS3 ? TRBCTL_STATUS3 : TRBCTL_STATUS2;
            ud.state = EP0_STATUS;
            (void)ud_start(ep, UD_DATA, 0, control);
        }
    }
}

static bool valid_dwc3_id(uint32_t id)
{
    /* DWC3.1 (Tegu/laguna family), DWC3 and DWC3.2 IDs are explicit; no other
     * value is treated as permission to write the controller. */
    return id == 0x33313130 || (id >> 16) == 0x5533 || (id >> 16) == 0x3332;
}

static int board_resume(const struct laguna_usb_board_ops *board)
{
    static const uint8_t clocks[] = {
        LAGUNA_USB_CLOCK_USBC_NON_STICKY, LAGUNA_USB_CLOCK_USBC_STICKY,
        LAGUNA_USB_CLOCK_U2PHY_APB, LAGUNA_USB_CLOCK_USB2_PHY_RESET,
    };
    static const uint8_t resets[] = {
        LAGUNA_USB_RESET_USBC_NON_STICKY, LAGUNA_USB_RESET_USBC_STICKY,
        LAGUNA_USB_RESET_USBC_DRD_BUS, LAGUNA_USB_RESET_U2PHY_APB,
        LAGUNA_USB_RESET_USB_TOP_CSR, LAGUNA_USB_RESET_USB2_PHY,
    };
    if (!board || !board->power_on || !board->clock_enable ||
        !board->reset_deassert || !board->repeater_peripheral)
        return LAGUNA_USB_ERR_PROVIDER;
    int result = board->power_on(board->context);
    if (result) return LAGUNA_USB_ERR_PROVIDER;
    tgl_stamp(TGL_STAGE_PHY_RESUME, TGL_STAMP_F_ENTER, 0);
    for (unsigned i = 0; i < sizeof(clocks); i++)
        if (board->clock_enable(board->context, clocks[i])) return LAGUNA_USB_ERR_PROVIDER;
    for (unsigned i = 0; i < sizeof(resets); i++)
        if (board->reset_deassert(board->context, resets[i])) return LAGUNA_USB_ERR_PROVIDER;
    if (board->repeater_peripheral(board->context)) return LAGUNA_USB_ERR_PROVIDER;
    tgl_stamp(TGL_STAGE_PHY_RESUME, TGL_STAMP_F_DONE, sizeof(clocks) << 8 | sizeof(resets));
    return LAGUNA_USB_OK;
}

/* v3.4 resume-done latch (CPM-FIRST-SPEC §6.2): the early CPM-first resume
 * has already sent clocks+resets when laguna_usb_start re-runs board_resume;
 * double-send is only safe if LPCM gates are idempotent (DEVICE-VALIDATE),
 * so the second send is suppressed once one full resume succeeded.
 * Reset only by reboot. */
static int usb_resume_latched;

int laguna_usb_board_resume(const struct laguna_usb_board_ops *board)
{
    int result = board_resume(board);
    if (result == LAGUNA_USB_OK) usb_resume_latched = 1;
    return result;
}

int laguna_usb_start(const struct laguna_usb_config *config)
{
    if (!config || !config->dwc3_base || !config->usb2_cfg_base ||
        !config->usbdp_top_base || !config->dma || !config->dma_pa ||
        (config->dma & 4095) || (config->dma_pa & 4095) ||
        config->dma_bytes < LAGUNA_USB_DMA_MIN_BYTES ||
        config->dma_bytes > LAGUNA_USB_DMA_BYTES)
        return LAGUNA_USB_ERR_ARGUMENT;
    if (!config->dma_path_admitted) return LAGUNA_USB_ERR_DMA;
    if (ud.running) return LAGUNA_USB_ERR_BUSY;

    zero_bytes(&ud, sizeof(ud));
    ud.dwc = config->dwc3_base;
    ud.dma = config->dma;
    ud.dma_pa = config->dma_pa;
    ud.dma_bytes = config->dma_bytes;
    ud.data_capacity = config->dma_bytes - UD_DATA;
    if (ud.data_capacity > UD_DATA_MAX) ud.data_capacity = UD_DATA_MAX;
    ud.usb2_cfg = config->usb2_cfg_base;
    ud.usbdp_top = config->usbdp_top_base;
    ud.read32 = config->read32;
    ud.write32 = config->write32;
    ud.io_context = config->io_context;

    uint32_t id = dwc_rd(GSNPSID);
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    laguna_usb_log_hex("LAGUNA USB: GSNPSID", id);
    if (!valid_dwc3_id(id)) return LAGUNA_USB_ERR_ID;
    uint32_t gctl = dwc_rd(GCTL);
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    laguna_usb_log_hex("LAGUNA USB: inherited GCTL", gctl);
    if ((gctl & GCTL_PRTCAPDIR) != GCTL_PRTCAP_DEVICE) return LAGUNA_USB_ERR_MODE;
    laguna_usb_log_hex("LAGUNA USB: inherited DCTL", dwc_rd(DCTL));
    laguna_usb_log_hex("LAGUNA USB: inherited DSTS", dwc_rd(DSTS));
    laguna_usb_log_hex("LAGUNA USB: inherited USB2PHYCFG", dwc_rd(GUSB2PHYCFG));
    laguna_usb_log_hex("LAGUNA USB: inherited GEVNTADRHI", dwc_rd(GEVNTADRHI));
    laguna_usb_log_hex("LAGUNA USB: inherited GEVNTADRLO", dwc_rd(GEVNTADRLO));

    uint32_t cfg21 = cfg_rd(ud.usb2_cfg, USB2_CFG21);
    laguna_usb_log_hex("LAGUNA USB: inherited USB2 CFG19", cfg_rd(ud.usb2_cfg, USB2_CFG19));
    laguna_usb_log_hex("LAGUNA USB: inherited USB2 CFG21", cfg21);
    laguna_usb_log_hex("LAGUNA USB: inherited USBDP PHY CFG1", cfg_rd(ud.usbdp_top, USBDP_PHY_CFG1));
    laguna_usb_log_hex("LAGUNA USB: inherited USBDP POWER CFG1", cfg_rd(ud.usbdp_top, USBDP_POWER_CFG1));
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;

    bool resume = config->resume_requested || !(cfg21 & USB2_CFG21_PHY_ENABLE);
    const struct laguna_usb_board_ops *board = config->board;
    if (board && board->reset_status) {
        static const uint8_t query[] = {
            LAGUNA_USB_RESET_USBC_NON_STICKY, LAGUNA_USB_RESET_USBC_STICKY,
            LAGUNA_USB_RESET_USBC_DRD_BUS, LAGUNA_USB_RESET_U2PHY_APB,
            LAGUNA_USB_RESET_USB_TOP_CSR, LAGUNA_USB_RESET_USB2_PHY,
        };
        for (unsigned i = 0; i < sizeof(query); i++) {
            int status = board->reset_status(board->context, query[i]);
            if (status < 0) return LAGUNA_USB_ERR_PROVIDER;
            if (status) resume = true;
        }
    }
    if (resume) {
        if (!board) return LAGUNA_USB_ERR_PROVIDER;
        /* CPM-FIRST-SPEC §6.2: honor the resume-done latch — the early
         * tgl_usb_console_start resume already sent clocks/resets; do not
         * re-send (gate idempotency is DEVICE-VALIDATE, not assumed). */
        int result = usb_resume_latched ? LAGUNA_USB_OK : board_resume(board);
        if (result) return result;
        cfg21 = cfg_rd(ud.usb2_cfg, USB2_CFG21);
        if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    }
    if (!(cfg21 & USB2_CFG21_PHY_ENABLE)) {
        if (!board) return LAGUNA_USB_ERR_PROVIDER;
        /* Warm resume only: do not rewrite CFG19 PLL feedback, ref-frequency
         * selection, NVMEM tuning, SRAM firmware, or Type-C orientation. */
        cfg_wr(ud.usb2_cfg, USB2_CFG21, cfg21 | USB2_CFG21_PHY_ENABLE);
        if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    }

    dwc_wr(DCTL, dwc_rd(DCTL) & ~DCTL_RUN_STOP);
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    bool halted = false;
    tgl_stamp(TGL_STAGE_DWC3_HALT, TGL_STAMP_F_ENTER, 0);
    for (unsigned i = 0; i < 10000; i++) {
        if (dwc_rd(DSTS) & DSTS_DEVCTRLHLT) { halted = true; break; }
        delay_us(10);
    }
    if (!halted) {
        tgl_stamp(TGL_STAGE_DWC3_HALT, TGL_STAMP_F_TIMEOUT, 0);
        return LAGUNA_USB_ERR_HALT_TIMEOUT;
    }
    tgl_stamp(TGL_STAGE_DWC3_HALT, TGL_STAMP_F_DONE, 0);
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    /* ABL is halted before its event allocation is cleared or reused. */
    zero_bytes((volatile void *)ud.dma, ud.dma_bytes);

    /* Only the USB2 interface is resumed. Do not touch USB3/DP PHY status. */
    dwc_wr(GUSB2PHYCFG, dwc_rd(GUSB2PHYCFG) & ~GUSB2PHYCFG_SUSPHY);
    dwc_wr(DCTL, DCTL_CSFTRST);
    tgl_stamp(TGL_STAGE_DWC3_RESET, TGL_STAMP_F_ENTER, 0);
    for (unsigned i = 0; i < 500 && (dwc_rd(DCTL) & DCTL_CSFTRST); i++) delay_us(1000);
    if (dwc_rd(DCTL) & DCTL_CSFTRST) {
        tgl_stamp(TGL_STAGE_DWC3_RESET, TGL_STAMP_F_TIMEOUT, 0);
        return LAGUNA_USB_ERR_RESET_TIMEOUT;
    }
    tgl_stamp(TGL_STAGE_DWC3_RESET, TGL_STAMP_F_DONE, 0);
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;

    dwc_wr(GCTL, (dwc_rd(GCTL) & ~GCTL_PRTCAPDIR) | GCTL_PRTCAP_DEVICE);
    dwc_wr(GEVNTADRLO, (uint32_t)(ud.dma_pa + UD_EVT));
    dwc_wr(GEVNTADRHI, (uint32_t)((ud.dma_pa + UD_EVT) >> 32));
    dwc_wr(GEVNTSIZ, (1u << 31) | UD_EVT_SIZE);
    dwc_wr(GEVNTCOUNT, dwc_rd(GEVNTCOUNT) & 0xfffc);
    dwc_wr(DCFG, dwc_rd(DCFG) & ~(7u | (0x7fu << 3)));
    dwc_wr(DEVTEN, 7); /* disconnect, reset, connect-done; IRQs stay polled */

    tgl_stamp(TGL_STAGE_EP0_CONFIG, TGL_STAMP_F_ENTER, 0);
    if (ud_epcmd(0, DEPCMD_DEPSTARTCFG, 0, 0, 0) ||
        ud_epcmd(0, DEPCMD_SETEPCONFIG, 64u << 3, (1u << 8) | (1u << 10), 0) ||
        ud_epcmd(0, DEPCMD_SETTRANSFRESOURCE, 1, 0, 0) ||
        ud_epcmd(1, DEPCMD_SETEPCONFIG, 64u << 3,
            (1u << 8) | (1u << 10) | (1u << 25), 0) ||
        ud_epcmd(1, DEPCMD_SETTRANSFRESOURCE, 1, 0, 0)) {
        tgl_stamp(TGL_STAGE_EP0_CONFIG, TGL_STAMP_F_FAULT, 0);
        return ud.mmio_failed ? LAGUNA_USB_ERR_MMIO : LAGUNA_USB_ERR_ENDPOINT;
    }
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    dwc_wr(DALEPENA, 3);
    ud_start_setup();
    if (ud.io_error) return ud.mmio_failed ? LAGUNA_USB_ERR_MMIO : LAGUNA_USB_ERR_ENDPOINT;
    dwc_wr(DCTL, dwc_rd(DCTL) | DCTL_RUN_STOP);
    if (ud.mmio_failed) return LAGUNA_USB_ERR_MMIO;
    ud.running = true;
    tgl_stamp(TGL_STAGE_EP0_READY, TGL_STAMP_F_DONE, dwc_rd(DSTS));
    laguna_usb_log_hex("LAGUNA USB: RUN DSTS", dwc_rd(DSTS));
    laguna_usb_log_hex("LAGUNA USB: DMA", ud.dma_pa);
    return LAGUNA_USB_OK;
}

void laguna_usb_poll(void)
{
    if (!ud.running || ud.io_error) return;
    uint32_t count = dwc_rd(GEVNTCOUNT) & 0xfffc;
    if (!count || count > UD_EVT_SIZE) return;
    ud_sync(UD_EVT, UD_EVT_SIZE);
    for (uint32_t done = 0; done < count; done += 4) {
        uint32_t event = *(volatile uint32_t *)(ud.dma + UD_EVT + ud.evt_pos);
        ud.evt_pos = (ud.evt_pos + 4) % UD_EVT_SIZE;
        ud.events++;
        ud_event(event);
        if (ud.io_error) break;
    }
    dwc_wr(GEVNTCOUNT, count);
}

bool laguna_usb_running(void)
{
    return ud.running && !ud.io_error;
}

bool laguna_usb_transfer_active(void)
{
    /* Only a data stage genuinely in flight blocks the handoff. A stale
     * wait-state — the host disconnected mid-status after its last log
     * read (usb_log reads 384 B chunks, then closes) — is not active: the
     * console has served its purpose and XNU re-initialises the
     * controller. v44 proof: state parked in WAIT_STATUS3 at handoff and
     * the old `!= EP0_SETUP` test refused every host-connected run. */
    return laguna_usb_running() && ud.state == EP0_DATA;
}
