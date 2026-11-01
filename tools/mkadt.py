#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that the LAGUNA xnu needs to boot.

Only what the early boot path actually reads (see research/laguna-adt-requirements.md and
research/laguna-usb-fix/ADT-NODES.md for the per-node consumer evidence); every MMIO
address comes from the laguna live FDT. The node vocabulary follows the
laguna kernel patches (research/laguna-xnu-patches): root compatible google,lga-blazer
(0016 LagunaPlatformExpert IONameMatch), per-CPU compatible google,lga-cpu (0018),
console node name laguna-fbcon (0003 fbcon_probe). Usage:
  mkadt.py OUT.adt [--dump] [--qemu] [--bank1] [--phys-base=0x...] [--mem-size=0x...]
"""
import hashlib, os, struct, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# Kernel-managed RAM: the low DRAM bank (live FDT /memory@80000000 + 7 upper
# banks). On the device the first *declared-clean* window may be bank 1 (the
# low bank holds bl31_dram 0xffe00000 / sec_dram 0xf7000000 firmware carve-outs);
# probe-write before use (laguna-adt-requirements.md section 3).
PHYS_BASE = 0x80000000   # laguna: DRAM base (DTB /memory@80000000)
MEM_SIZE = 0x80000000   # laguna: 2G window (fills 0x80000000..0x100000000)
# --bank1 (device only, like tegu's --highmem): the first upper DDR bank from the
# live FDT (<0x8_80000000 2G>); every known firmware carve-out is in the low bank.
BANK1_PHYS_BASE = 0x880000000
BANK1_MEM_SIZE = 0x80000000
# /arm-io children are relative to this; it must not be 0 (serial_init bails).
# tegu pattern kept: soc base = the GICD address itself (both modes below).
SOC_BASE = 0x05880000   # laguna GICD; /arm-io children are relative to this

GICD, GICD_SIZE = 0x05880000, 0x10000   # laguna live FDT: /interrupt-controller@5880000
GICR, GICR_SIZE = 0x05900000, 0x200000  # laguna live FDT (confirmed; 8 x 0x40000 PE frames)
# FB address is RUNTIME on laguna (ABL scanout; no splash node in any static or
# live tree). Placeholder 0xf0000000 — the same PA the kernel's laguna-fbcon
# node, the QEMU smoke and the shim console use; NEEDS-DEVICE-PROBE (DC9x00
# layer regs 0x0ee00000+0x18060/64) replaces it on the first hardware session.
FB, FB_SIZE = 0xf0000000, 0x2000000
LAGUNA_ECID = 0x4c47413100000001  # 'LGA1' + 1, synthetic (tegu pattern: 'TEGU'+1)
FB_W, FB_H, FB_STRIDE = 1280, 2856, 1280 * 4   # laguna panel 6.3" 1280x2856, stride 5120
# DC9x00 display-controller windows (live /proc/iomem "ee00000.dc9x00
# dpu-fe-be"; dsi2host@3d8000). /device-tree/laguna-dpu carries them as an
# ABSOLUTE 4 x u64 reg — the exact shape laguna_dc9x00_adt_gate()
# (osfmk/arm64/laguna_dc9x00.c, DC9x00 series patch 0001) requires: node
# present AND reg equal to the kernel's built-in windows, else every DC
# MMIO access is refused (probe skipped, splash repoint refused). Device
# mode only; the QEMU ADT stays node-less so the gate keeps taking its
# refusal there (virt leaves those windows unassigned; a read would
# external-abort).
DPU_FE_BE, DPU_FE_BE_SIZE = 0x0ee00000, 0x120000
DPU_DSI2H0, DPU_DSI2H0_SIZE = 0x0efd8000, 0x800
# Console UART: DW-APB uart@db62000, stock status=disabled, no XNU driver. Not
# emitted as an ADT console node (drop-tegu-uart0 rule, requirements doc stage 3);
# kept as the documented bring-up MMIO for the future DW-APB driver.
UART0, UART0_SIZE = 0x0db62000, 0x1000
# Hardware watchdogs (live FDT): quiesce is a shim action, not an ADT property.
WDT_CL0, WDT_CL1 = 0x200c4000, 0x200c5000
TIMEBASE = 38400000   # laguna CNTFRQ_EL0, confirmed 38.4 MHz (runtime-read; ADT carries it)
VTIMER_INTID = 27   # laguna live FDT /timer: PPI 11 virt -> INTID 27 (ADT-overridable, 0017)
# /arm-io/timer (pe_identify_machine.c SecureDTFindEntry("device_type","timer") ->
# gTimerBase = ml_io_map(soc_phys + reg[0], reg[1]); required for
# pe_arm_map_interrupt_controller to return 1). laguna: the APT always-on timer
# apt@24074000 (0x10000) from the live FDT. arm64 maps it and never touches it
# (pe_arm_init_timer uses empty tbd funcs), so the address must only be real
# device space, not RAM.
TIMER, TIMER_SIZE = 0x24074000, 0x10000
# /arm-io/cpu-debug-interface (pe_identify_machine.c
# SecureDTFindEntry("device_type","cpu-debug-interface") -> pe_arm_init_debug ->
# ml_init_arm_debug_interface(args, ml_io_map(gSocPhys + reg[0], reg[1])): stores
# cpu_data_t.cpu_debug_interface_map + do_debugid() (an ID_AA64DFR0_EL1 register
# read). Deliberately NO panic-trace-mode property: the TUNABLE_DT default keeps
# panic_trace disabled, so pe_init_debug_command never runs and no MMIO is ever
# written through this mapping. laguna: CoreSight ETF etf@23802000 (0x1000).
DBG_IFACE, DBG_IFACE_SIZE = 0x23802000, 0x1000
# /pram + /chosen embedded-panic-log-size (pe_init.c check_for_panic_log ->
# gPanicBase = ml_io_map_wcomb(reg[0], embedded-panic-log-size); the BCM2837
# board header documents this as THE panic-log source). The region must be RAM
# that is outside the kernel window (no vm_page aliasing) and survives kexec:
# the upper half of the lga.dtsi ramoops console zone. The persistent_ram zone
# header + shim console records (live at 0x95200000, < 1 MiB used) stay intact;
# the region ends exactly at the pmsg zone start, so the 0x95400100 handoff
# records and the 0x95430000 compact mirror are never touched.
PRAM, PRAM_SIZE = 0x95300000, 0x100000
PANIC_LOG_SIZE = 0x80000   # 512 KiB (Apple's documented example in pe_init.c)
# The whole ramoops zone (console 0x95200000+0x200000, pmsg 0x95400000+0x200000).
# XNU takes its RAM from boot args, so the ADT cannot carve this out — the
# generator refuses a kernel window that overlaps it instead (device mode only;
# QEMU guest RAM legitimately spans the address).
RAMOOPS_LO, RAMOOPS_HI = 0x95200000, 0x95600000
# QEMU virt (-M virt,gic-version=3 -cpu cortex-a76): the GIC/virt-timer/UART map
# our kernel lineage already boots under (blazer/shim runtime.c QEMU contract).
QEMU_GICD, QEMU_GICR, QEMU_GICR_SIZE, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 0xf60000, 62500000
QEMU_UART0 = 0x09000000   # virt PL011: gives the QEMU runs a real serial console
QEMU_VTIMER_INTID = 27
# virt has no SoC timer / CoreSight; both ADT nodes are map-only on arm64 (no
# MMIO access with panic_trace disabled), so stable unassigned windows inside
# the virtio block are safe and keep the "failed to find" lines off QEMU logs.
QEMU_TIMER, QEMU_TIMER_SIZE = 0x0a000000, 0x1000
QEMU_DBG_IFACE, QEMU_DBG_IFACE_SIZE = 0x0a001000, 0x1000

BOOT_MANIFEST_HASH = hashlib.sha384(b'laguna boot manifest').digest()

# The iOS userland is the iPhone X (iPhone10,3 / D22AP) IPSW. MobileGestalt
# derives product type, device class, home-button-less UI, artwork etc. from
# the root identity and /product of the real D22AP device tree. That tree is
# an Apple artifact (kept out of git): extract it from the IPSW with
#   tools/remotezip.py URL DeviceTree.d22ap.im4p DIR
#   ipsw img4 im4p extract DIR/Firmware/all_flash/DeviceTree.d22ap.im4p -o d22ap.adt
D22AP_ADT = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                         '../research/ipsw-x/d22ap.adt')


def d22ap_product(path=D22AP_ADT):
    """/product properties of the real D22AP tree, without the syscfg
    placeholders iBoot would fill in (flag bit set) and the node bookkeeping."""
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')

u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def empty_nvram_proxy():
    """/chosen properties for a fresh, RAM-only CHRP NVRAM bank with no
    controller — the v55 wall fix (evidence: attempts/20261027-114400-v54
    reader-full.txt "IONVRAMCHRPHandler creation failed" -> MACH Reboot).

    Consumer chain (xnu-8796.121.2 iokit/Kernel/IONVRAM.cpp + IONVRAMCHRPHandler.cpp):
    with /options present (v54), IODTNVRAM::start -> initImageFormat reads
    /chosen nvram-bank-size + nvram-proxy-data, then IONVRAMCHRPHandler::init ->
    IODTNVRAMFormatHandler::getNVRAMProperties (IONVRAM.cpp:1140) requires, in
    order, nvram-bank-size / nvram-bank-count / nvram-current-bank (uint32
    OSData each) — their absence panicked at IONVRAM.cpp:1151.

    nvram-proxy-data is NOT optional: without it unserializeImage never runs,
    _nvramImage stays NULL while the constructor presets _commonPartitionSize
    to 0x800, and initImageFormat's _format->unserializeVariables() would walk
    NULL+uninitialized offsets. With the image present, unserializeImage's
    adler check (IONVRAMCHRPHandler.cpp:432) PANICS on a mismatch, so the
    checksums below must stay exact.

    Bank layout (UniXNU-sheng/pandora empty_nvram_proxy precedent): 8 KiB with
    nvram/common/free CHRP partitions, each 16-byte header {u8 sig 0x70,
    u8 cksum, u16 length/16, char name[12]} with cksum folded like
    chrp_checksum (sum of sig + every header byte except cksum itself), and the
    bank's adler32 from byte 20 stored at byte 16 (apple_nvram_header.adler).
    """
    def header(name, size):
        raw = bytearray(struct.pack('<BBH12s', 0x70, 0, size // 16, name))
        checksum = sum(raw)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        raw[1] = checksum
        return raw

    image = bytearray(8192)
    image[:16] = header(b'nvram', 32)
    image[32:48] = header(b'common', 16 + 2048)
    free_at = 32 + 16 + 2048
    image[free_at:free_at + 16] = header(b'free', len(image) - free_at)
    struct.pack_into('<I', image, 16, zlib.adler32(bytes(image[20:])))
    return [('nvram-bank-size', u32(len(image))),
            ('nvram-bank-count', u32(1)),
            ('nvram-current-bank', u32(0)),
            ('nvram-proxy-data', bytes(image))]


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def build(seed=None, qemu=False, bank1=False, mem_size=None, phys_base=None):
    """qemu=True: same tree, but with QEMU virt's GIC/UART addresses and CNTFRQ
    (tests/smoke-qemu-laguna.sh). bank1=True: kernel RAM in the first upper bank
    (device only; QEMU virt has no RAM there). mem_size overrides the kernel
    RAM window size (v2 device default: 256M, the kexec-proven geometry that
    avoids sec_dram 0xf7000000 / bl31_dram 0xffe00000)."""
    phys_base_d, size = (BANK1_PHYS_BASE, BANK1_MEM_SIZE) if bank1 else (PHYS_BASE, MEM_SIZE)
    phys_base = phys_base_d if phys_base is None else phys_base
    mem_size = size if mem_size is None else mem_size
    # Fail-closed ramoops exclusion (device mode): the kernel RAM window comes
    # from boot args, so the ADT cannot express the reservation — refuse a
    # geometry that would let XNU allocate over the pstore evidence zones
    # (probe.h PSTORE_CONSOLE/PSTORE_PMSG, mainline lga.dtsi ramoops@95200000,
    # stamps at 0x95430000). The kexec-proven 256M window ends at 0x90000000.
    if not qemu and phys_base < RAMOOPS_HI and phys_base + mem_size > RAMOOPS_LO:
        raise SystemExit(
            f'kernel window {phys_base:#x}..{phys_base + mem_size:#x} overlaps the '
            f'laguna ramoops/pstore reservation {RAMOOPS_LO:#x}..{RAMOOPS_HI:#x}; '
            f'XNU would allocate over the evidence zones. Pass a window that ends '
            f'at or below {RAMOOPS_LO:#x}, e.g. --mem-size=0x10000000 (the '
            f'kexec-proven 256M) or --bank1.')
    gicd, gicr, gicr_size, timebase = \
        (QEMU_GICD, QEMU_GICR, QEMU_GICR_SIZE, QEMU_TIMEBASE) if qemu \
        else (GICD, GICR, GICR_SIZE, TIMEBASE)
    timer, timer_size = (QEMU_TIMER, QEMU_TIMER_SIZE) if qemu else (TIMER, TIMER_SIZE)
    dbg_iface, dbg_iface_size = \
        (QEMU_DBG_IFACE, QEMU_DBG_IFACE_SIZE) if qemu else (DBG_IFACE, DBG_IFACE_SIZE)
    # /arm-io children are relative to the soc base = GICD address in both
    # modes (laguna 0x05880000, QEMU virt 0x08000000). A zero ranges parent
    # silently zeroes gPESoCBasePhys (24 MHz timebase, no GIC map).
    soc_base = gicd
    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('firmware-version', cstr('laguna-shim')),
        ('system-firmware-version', cstr('laguna-shim')),
        # Physical boots patch this zero placeholder in place after the shim
        # seals its 128-byte record. A zero pair is present-but-invalid and
        # therefore headless; QEMU omits it to preserve the ramfb control.
        *([('laguna-display-handoff', u64(0, 0))] if not qemu else []),
        # PSCI conduit for psci_smp.c (live FDT /psci: method "smc"; QEMU
        # virt advertises hvc — the kernel's default is smc without this).
        ('psci-method', cstr('hvc' if qemu else 'smc')),
        # iBoot's SHA-384 of the boot manifest; /sbin/mount -P 1 exits unless
        # it exists (bind mounts /private/preboot/<hex>/usr/standalone/firmware,
        # tolerating a missing directory). Fixed stand-in value.
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        # libimg4 (cryptexd) aborts "failed to get crypto algorithm" without
        # it; real A11+ device trees say sha2-384.
        ('crypto-hash-method', cstr('sha2-384')),
        # MobileGestalt's screen class: display-scale (u32, default 0) comes
        # from /chosen, the pixel size from IOMobileFramebuffer. Scale 0 makes
        # SpringBoard's FBSDisplayMode "infxinf@0x" invalid. 1280x2856 @3x =
        # ~427x952 points (iPhone X class).
        ('display-scale', u32(3)),
        # XNU derives IOPlatformUUID (gethostuuid) from these on arm; without
        # them CFPreferences cannot use kCFPreferencesCurrentHost (no ByHost
        # files), so e.g. DataMigration never records LastSystemVersion and
        # migrates on every boot. Synthetic ECID (not the phone's); chip-id
        # of the A11 that the iPhone X userland expects.
        ('unique-chip-id', struct.pack('<Q', LAGUNA_ECID)),
        ('chip-id', u32(0x8015)),
        # check_for_panic_log (pe_init.c) pairs this with /pram to size the
        # kernel panic log: gPanicSize = value, debug_buf_size = value -
        # header (osfmk/kern/debug.c debug_log_init). Device mode only; QEMU
        # keeps the benign "gPanicBase is still not initialized" warning.
        *([('embedded-panic-log-size', u32(PANIC_LOG_SIZE))] if not qemu else []),
        # Security status as on a dev-fused, undemoted board (tuple 0,0,1,1):
        # MobileGestalt reads these from /chosen, and mobileactivationd's
        # DeviceType then takes its native "Hactivation" branch (state
        # Activated without an activation record; no SEP, no baseband here).
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
        # IONVRAMCHRPHandler needs the 4 NVRAM properties above on /chosen
        # (v55 wall fix; empty_nvram_proxy documents the exact read order and
        # the adler panic if the bank image checksums drift).
        *empty_nvram_proxy(),
    ], [node('memory-map', [ph()]),
        # Local boot policy, read only if CONFIG_CSR is ever enabled: kern_csr.c
        # csr_bootstrap (STARTUP TUNABLES RANK_FIRST) takes csr_config from
        # /chosen/asmb lp-sip0 (u64) and CSR_ALLOW_UNAUTHENTICATED_ROOT from
        # lp-sip1. In the current DEVELOPMENT_ARM64_* builds kern_csr.c is
        # "optional config_csr" (bsd/conf/files:428) and NOT compiled — no csr
        # symbol exists in mach.blazer (nm-verified 2026-10-27, Q2) — so this
        # node is inert today; unknown /chosen children are ignored by XNU.
        # Kept because the day CONFIG_CSR comes on, lp-sip0 0x6f is exactly
        # `csrutil disable` (untrusted kexts | unrestricted FS | task_for-pid |
        # kernel debugger | dtrace | nvram) and lp-sip1 keeps an unsealed root
        # mountable; with CSR off, the shared-cache gate instead runs the
        # vm_unix.c:2539 "#else /* CONFIG_CSR */" mount-identity check, which
        # the root-v7 RAMDisk satisfies (QEMU proof: N1 cache probe, 0 refusals).
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    # LAGUNA SMP: all eight cores in physical-core order (0-1 Cortex-A520,
    # 2-6 Cortex-A725, 7 Cortex-X4; MPIDR Aff1 0x000-0x700), one homogeneous
    # cluster. The kernel defaults to one and uses cpus=N to select an initial
    # prefix (N <= 8). QEMU retains its original single-CPU tree: its MPIDRs
    # differ from laguna. Boot core assumed cpu0 (verify on first hardware boot).
    cpu_nodes = []
    for core in range(1 if qemu else 8):
        cpu_nodes.append(node(f'cpu{core}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', cstr('google,lga-cpu') + cstr('ARM,v8')),
            ('reg', u32(core << 8)),  # actual MPIDR Aff1:Aff0, NOT logical ID
            ('cpu-id', u32(core)),   # descriptive: XNU assigns IDs by DT order
            ('cluster-id', u32(0)),  # descriptive; see ml_parse_cpu_topology
            ('cluster-type', u32(0)),  # homogeneous CLUSTER_TYPE_SMP, not AMP
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(core)),
            ('l2-cache-id', u32(core)),  # per-core L2 in the live FDT
            ('l3-cache-id', u32(0)),     # shared L3
            ('state', cstr('running' if core == 0 else 'stopped')),
            ('timebase-frequency', u32(timebase)),
            # Clocks are synthetic placeholders (verify): the live FDT cpu
            # nodes carry 0x3b9ac9ff, which the requirements doc says not to
            # copy. Only timebase-frequency matters for early boot.
            ('clock-frequency', u32(3150000000 if core == 7 else
                                    2400000000 if core >= 2 else 1804800000)),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(1866000000)),
            ('peripheral-frequency', u32(timebase)),
            ('fixed-frequency', u32(timebase)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        # Must be the C-string "master": pe_arm_map_interrupt_controller does
        # SecureDTFindEntry("interrupt-controller", "master") with a strcmp on
        # the raw value (pexpert/gen/device_tree.c find_entry). An empty value
        # (the tegu shape) never matches -> gPicBase stays 0 ->
        # "failed to find the interrupt-controller" and pe_arm_init_timer is
        # never reached. reg[0..1] map GICD relative to gSocPhys; map-only.
        ('interrupt-controller', cstr('master')),
        ('virtual-timer-intid', u32(QEMU_VTIMER_INTID if qemu else VTIMER_INTID)),
        ('reg', u64(gicd - soc_base, GICD_SIZE, gicr - soc_base, gicr_size)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('laguna-io')),
        ('compatible', cstr('laguna-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, soc_base, 0x100000000 - soc_base)),
    ], [gic,
        # pe_arm_map_interrupt_controller requires device_type "timer" with a
        # reg (gTimerBase = ml_io_map(soc_phys + reg[0], reg[1]); map-only on
        # arm64) or it returns 0 even with the GIC mapped ("failed to find the
        # timer."). laguna: APT apt@24074000 from the live FDT.
        node('timer', [
            ph(),
            ('device_type', cstr('timer')),
            ('reg', u64(timer - soc_base, timer_size)),
        ]),
        # pe_arm_init_debug looks up device_type "cpu-debug-interface" and
        # hands reg[0..1] to ml_init_arm_debug_interface (stores
        # cpu_debug_interface_map, do_debugid reads ID_AA64DFR0_EL1 — no MMIO).
        # No panic-trace-mode property on purpose: panic_trace stays disabled
        # and the debug command buffers stay empty (no writes through this map).
        node('cpu-debug-interface', [
            ph(),
            ('device_type', cstr('cpu-debug-interface')),
            ('reg', u64(dbg_iface - soc_base, dbg_iface_size)),
        ]),
        # No hardware: watchdogd checks IODeviceTree:/arm-io/wdt for no-pmu and
        # otherwise crashes trying to set the PMU boot stage (customer builds
        # ignore the -wdt_no_pmu boot-arg). The hardware WDTs themselves
        # (0x200c4000/0x200c5000) are a shim quiesce action on the device.
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        # QEMU-only serial console (virt PL011): stock pe_serial drives it via
        # boot-console, giving the emulated boots a real serial log. laguna has
        # no PL011 (DW-APB uart@db62000 is disabled and driverless), so the
        # device tree omits this node and the console is the framebuffer.
        *([node('uart0', [
            ph(),
            ('device_type', cstr('uart')),
            ('compatible', cstr('arm,pl011')),
            ('reg', u64(QEMU_UART0 - soc_base, UART0_SIZE)),
            ('boot-console', u32(1)),
        ])] if qemu else []),
        # Main display: IOMobileFramebuffer.framework counts /arm-io children
        # with this device_type and reads the canvas size from the node
        # (the presented iPhone X size, see TeguFramebuffer.cpp);
        # the kernel's AppleCLCD matches the compatible string. The QEMU ADT
        # deliberately has NO laguna-dpu node: virt leaves the DC9x00 MMIO
        # windows unassigned, so the display probe must take its ADT gate.
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('laguna,display')),
            ('canvas-width', u32(1125)),
            ('canvas-height', u32(2436)),
        ])])

    fbcon = node('laguna-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
    ])

    # pmap_compute_max_asids requires the node even when no overrides are set.
    # An absent pmap-max-asids property selects XNU's own MAX_ASIDS default.
    # No effaceable storage: keybagd then reads /private/var/keybags/systembag.kb
    # as a plain plist instead of decrypting it with the effaceable key.
    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    # MobileGestalt HomeButtonType = IODeviceTree:/buttons home-button-type
    # (D22AP: 2, no Home button; absent = 0 = Home-button device).
    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    product = [node('product', [ph()] + product_props)] if product_props else []

    # Kernel panic log region (device only): check_for_panic_log does
    # SecureDTLookupEntry(0, "pram") + reg[0] -> gPanicBase =
    # ml_io_map_wcomb(PRAM, embedded-panic-log-size). 0x95300000 sits in the
    # upper half of the ramoops console zone: outside every kernel window the
    # generator accepts (the overlap guard above), after the shim console
    # records, and exactly 0x200000 below the pmsg zone — the loader handoff
    # records at 0x95400100 and the compact mirror at 0x95430000 stay intact.
    pram = [node('pram', [
        ph(),
        ('reg', u64(PRAM, PRAM_SIZE)),
    ])] if not qemu else []

    # Identity of the iPhone X whose userland runs here: compatible[0] is
    # hw.model/hw.target (D22AP), model is hw.machine/hw.product
    # (iPhone10,3). 'google,lga-blazer' stays for LagunaPlatformExpert
    # matching (0016 IONameMatch; its absence panics IOPanicPlatform).
    # /options is REQUIRED by IOPlatformExpert.cpp:1695 (G1's finding: its
    # absence makes createNVRAM() early-return -> gIOOptionsEntry NULL ->
    # assert fires in processTopLevel = the v51/v53 "MACH Reboot" kill).
    options = node('options', [])

    # DC9x00 display-controller node (device only): opens the kernel's
    # laguna_dc9x00_adt_gate() for the read-only probe (io.display.probe)
    # and the splash repoint (io.display.splash=2). Absolute reg — no
    # ranges parent involved. NOTE: this adds a node (and shifts the
    # phandle sequence) to the DEVICE ADT by design; the QEMU ADT stays
    # byte-identical to previous generations.
    laguna_dpu = [node('laguna-dpu', [
        ph(),
        ('reg', u64(DPU_FE_BE, DPU_FE_BE_SIZE, DPU_DSI2H0, DPU_DSI2H0_SIZE)),
    ])] if not qemu else []
    return node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') +
                       cstr('google,lga-blazer') + cstr('google,lga') + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon] + laguna_dpu + [buttons] + product + pram + [options])


def _phys_base_arg(argv):
    for a in argv:
        if a.startswith('--phys-base='):
            v = int(a.split('=', 1)[1], 0)
            if v & 0xFFFF or v < 0x80000000:
                raise SystemExit(f'invalid --phys-base {v:#x}')
            return v
    return None


def _mem_size_arg(argv):
    for a in argv:
        if a.startswith('--mem-size='):
            v = int(a.split('=', 1)[1], 0)
            if v % 0x4000 or v > 0x180000000:
                raise SystemExit(f'invalid --mem-size {v:#x}: 16K-aligned, <= 6G')
            return v
    return None


if __name__ == '__main__':
    root = build(qemu='--qemu' in sys.argv, bank1='--bank1' in sys.argv,
        mem_size=_mem_size_arg(sys.argv), phys_base=_phys_base_arg(sys.argv))
    blob = adt.serialize(root)
    open(sys.argv[1], 'wb').write(blob)
    if '--dump' in sys.argv:
        adt.dump(adt.parse(blob)[0])
    print(f'{sys.argv[1]}: {len(blob)} bytes', file=sys.stderr)
