#!/usr/bin/env python3
"""Pack an xnu kernel Mach-O + ADT into the payload the tegu shim boots.

  mkpayload.py KERNEL ADT OUT [--cmdline "..."] [--ramdisk IMAGE [--ramdisk1 IMAGE]]

The kernel is linked as a PIE with LC_DYLD_CHAINED_FIXUPS. Nobody else
(no kmutil, no iBoot) resolves those for us, and xnu only rebases static
kernelcaches itself, so the chains are walked here and every pointer is
rewritten to its unslid target. The shim then only copies flat segments.

Payload layout (little endian, all offsets from payload start):
  0x000  char  magic[8] = "TEGUXNU"
  0x008  u32   version = 1, nsegs
  0x010  u64   virt_base      kernel VA that maps to phys_base
  0x018  u64   entry_va       LC_UNIXTHREAD pc
  0x020  u64   adt_off, adt_size
  0x030  u64   kernel_end_va  end of the highest segment (page aligned)
  0x038  u64   phys_base      kernel-managed RAM (same values as the ADT's dram-base/size)
  0x040  u64   mem_size
  0x048  char  cmdline[608]
  0x2a8  seg[nsegs] { u64 vmaddr, vmsize, file_off(in payload), file_size }

--ramdisk appends IMAGE as one more segment right after the kernel and moves
kernel_end past it, so the shim needs no changes: the image lands below the
ADT and boot_args, inside topOfKernelData (never handed to the VM), and the
ADT gets /chosen/memory-map "RAMDisk" = <phys, size> for IOFindBSDRoot to
turn into md0 (boot with rd=md0).

--ramdisk1 requires --ramdisk and appends a second image with the same
placement rules. RAMDisk1 advertises it as md1 for stage0 to mount on
/redwood; it never replaces the recovery md0 or changes the command line.
"""
import argparse, os, struct, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

LC_SEGMENT_64, LC_UNIXTHREAD, LC_DYLD_CHAINED_FIXUPS = 0x19, 0x5, 0x80000034
PAGE = 0x4000
BOOT_LINE_LENGTH = 608
CMDLINE = 0x48
SEG_TABLE = CMDLINE + BOOT_LINE_LENGTH	# 0x2a8
MAX_SEGS = 64                 # shim/payload.h TGL_MAX_SEGS
UINT64_MAX = (1 << 64) - 1
HEADROOM_MIN = 0x4000000      # shim/payload.h metadata placement rule
# The laguna kernel lineage (mach.laguna, MACHINE_CONFIG=LAGUNA) is linked at
# the fixed non-KASLR base 0xfffffff004000000 — blazer/shim SHIM_KERNEL_VIRT_BASE,
# start.s maps phys_base there, and the QEMU smoke's VA->PA math uses it. tegu
# derived virt_base from the __TEXT 32MB block instead; that picks the wrong
# block for this kernel (__TEXT starts 48MB above the base, so tegu's rule
# would place the payload 32MB too low and xnu would fetch garbage).
KERNEL_VIRT_BASE = 0xfffffff004000000


def parse_macho(buf):
    magic, cputype, cpusub, ftype, ncmds, sizeofcmds, flags, _ = struct.unpack_from('<8I', buf, 0)
    assert magic == 0xfeedfacf, 'not a 64-bit Mach-O'
    segs, entry, fixups = [], None, None
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', buf, off)
        if cmd == LC_SEGMENT_64:
            name = buf[off + 8:off + 24].split(b'\0')[0].decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<4Q', buf, off + 24)
            segs.append(dict(name=name, vmaddr=vmaddr, vmsize=vmsize, fileoff=fileoff, filesize=filesize))
        elif cmd == LC_UNIXTHREAD:
            flavor, count = struct.unpack_from('<II', buf, off + 8)
            # arm_thread_state64: x0..x28, fp, lr, sp, pc, cpsr
            entry, = struct.unpack_from('<Q', buf, off + 16 + 32 * 8)
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            fixups = struct.unpack_from('<II', buf, off + 8)	# dataoff, datasize
        off += size
    return dict(cputype=cputype, cpusub=cpusub & 0xff, segs=segs, entry=entry, fixups=fixups)


def apply_chained_fixups(buf, m):
    """Rewrite every chained rebase in buf (the whole file) to its plain target VA."""
    if not m['fixups']:
        return 0
    data_off, _ = m['fixups']
    _, starts_off, _, _, imports_count, _, _ = struct.unpack_from('<7I', buf, data_off)
    assert imports_count == 0, 'kernel has binds; only rebases are supported'
    image_base = m['segs'][0]['vmaddr']		# __TEXT, holds the mach header
    seg_count, = struct.unpack_from('<I', buf, data_off + starts_off)
    nfix = 0
    for i in range(seg_count):
        seg_info, = struct.unpack_from('<I', buf, data_off + starts_off + 4 + 4 * i)
        if not seg_info:
            continue
        base = data_off + starts_off + seg_info
        size, page_size, fmt, seg_offset, max_valid, page_count = struct.unpack_from('<IHHQIH', buf, base)
        starts = struct.unpack_from('<%dH' % page_count, buf, base + 22)
        seg = m['segs'][i]
        for p, start in enumerate(starts):
            if start == 0xffff:
                continue
            assert not start & 0x8000, 'DYLD_CHAINED_PTR_START_MULTI not supported'
            loc = seg['fileoff'] + p * page_size + start
            while True:
                raw, = struct.unpack_from('<Q', buf, loc)
                target, nxt, stride = decode(raw, fmt, image_base)
                struct.pack_into('<Q', buf, loc, target)
                nfix += 1
                if not nxt:
                    break
                loc += nxt * stride
    return nfix


def decode(raw, fmt, image_base):
    """Return (unslid target VA, next, stride) for one chained pointer."""
    if fmt in (2, 6):		# DYLD_CHAINED_PTR_64 / _64_OFFSET
        assert not raw >> 63, 'bind in kernel'
        target = raw & ((1 << 36) - 1)
        high8 = (raw >> 36) & 0xff
        nxt = (raw >> 51) & 0xfff
        if fmt == 6:
            target += image_base
        return target | (high8 << 56), nxt, 4
    if fmt == 8:		# DYLD_CHAINED_PTR_64_KERNEL_CACHE
        target = raw & ((1 << 30) - 1)
        nxt = (raw >> 51) & 0xfff
        return image_base + target, nxt, 4
    if fmt in (1, 7, 9, 12):	# arm64e variants (stock VMAPPLE kernel only; PAC is not re-signed)
        auth = raw >> 63
        nxt = (raw >> 51) & 0x7ff
        stride = 4 if fmt in (7, 12) else 8
        if auth:
            target = raw & 0xffffffff
        else:
            target = raw & ((1 << 43) - 1)
            target |= ((raw >> 43) & 0xff) << 56
        if fmt in (7, 9, 12) or auth:
            target += image_base
        return target, nxt, stride
    raise ValueError(f'unsupported chained pointer format {fmt}')


def add_ramdisk_to_adt(adt_blob, phys, size, name='RAMDisk'):
    """Publish one RAMDisk property as two little-endian uintptr_t values."""
    if name not in ('RAMDisk', 'RAMDisk1'):
        raise ValueError('unsupported ramdisk property')
    root, _ = adt.parse(adt_blob)
    chosen = next(c for c in root.children if c.name == 'chosen')
    mmap = next(c for c in chosen.children if c.name == 'memory-map')
    if any(n == name for n, _, _ in mmap.props):
        raise ValueError(f'ADT already has a {name}')
    mmap.props.append((name, 0, struct.pack('<2Q', phys, size)))
    return adt.serialize(root)


def adt_dram(adt_blob):
    """Kernel-managed RAM <base, size> from the ADT's /chosen dram-base/dram-size."""
    root, _ = adt.parse(adt_blob)
    chosen = next(c for c in root.children if c.name == 'chosen')
    return (struct.unpack('<Q', chosen.prop('dram-base'))[0],
            struct.unpack('<Q', chosen.prop('dram-size'))[0])


def validate_layout(pieces, virt_base, phys_base, mem_size, kernel_end, adt_size):
    """Mirror the shim's segment/window/headroom guards before serializing."""
    if not 0 < len(pieces) <= MAX_SEGS:
        raise ValueError('payload segment count exceeds shim limit')
    if (not phys_base or phys_base & 0x1ffffff or not mem_size or
            mem_size & (PAGE - 1) or mem_size > 0x180000000 or
            phys_base + mem_size > UINT64_MAX or virt_base + mem_size > UINT64_MAX):
        raise ValueError('invalid/overflowing kernel window')
    for i, (va, size, data) in enumerate(pieces):
        if (va < virt_base or va & (PAGE - 1) or not size or size & 7 or
                size > mem_size or va - virt_base > mem_size - size or
                len(data) > size):
            raise ValueError('segment outside kernel window or unaligned')
        if any(va < prev + length and prev < va + size
               for prev, length, _ in pieces[:i]):
            raise ValueError('overlapping payload segments')
    if (kernel_end & (PAGE - 1) or
            not virt_base <= kernel_end <= virt_base + mem_size or
            any(va + size > kernel_end for va, size, _ in pieces)):
        raise ValueError('invalid kernel metadata placement')
    adt_pa = phys_base + kernel_end - virt_base
    top = ((adt_pa + adt_size + PAGE - 1) & ~(PAGE - 1)) + PAGE
    if top > UINT64_MAX or phys_base + mem_size - top < HEADROOM_MIN:
        raise ValueError('insufficient kernel headroom or metadata overflow')


def build(kernel_path, adt_path, cmdline, ramdisk_path=None, ramdisk1_path=None):
    if ramdisk1_path is not None and not ramdisk_path:
        raise ValueError('--ramdisk1 requires --ramdisk (md0)')
    buf = bytearray(Path(kernel_path).read_bytes())
    m = parse_macho(buf)
    nfix = apply_chained_fixups(buf, m)
    segs = [s for s in m['segs'] if s['vmsize']]
    text = m['segs'][0]
    assert text['name'] == '__TEXT' and text['fileoff'] == 0
    # virt_base: the kernel's fixed link base (see KERNEL_VIRT_BASE above).
    # It is 32MB-aligned like tegu's, so the same "block below the mach
    # header" start.s mapping contract holds: phys_base maps virt_base.
    virt_base = KERNEL_VIRT_BASE
    assert virt_base % 0x2000000 == 0
    assert all(s['vmaddr'] >= virt_base for s in segs), 'segment below the kernel virt base'
    if any(s['fileoff'] > len(buf) or s['filesize'] > len(buf) - s['fileoff'] for s in segs):
        raise ValueError('kernel segment outside source file')
    kernel_end = max(s['vmaddr'] + s['vmsize'] for s in segs)
    kernel_end = (kernel_end + PAGE - 1) & ~(PAGE - 1)

    adt_blob = Path(adt_path).read_bytes()
    # The ADT decides where the kernel's RAM is (mkadt.py --highmem).
    PHYS_BASE, MEM_SIZE = adt_dram(adt_blob)
    pieces = [(s['vmaddr'], s['vmsize'], buf[s['fileoff']:s['fileoff'] + s['filesize']]) for s in segs]
    ramdisk = None
    ramdisk1 = None
    for name, path in (('RAMDisk', ramdisk_path), ('RAMDisk1', ramdisk1_path)):
        if path is None:
            continue
        image = Path(path).read_bytes()
        if not image:
            raise ValueError(f'{name} image is empty')
        rd_size = (len(image) + PAGE - 1) & ~(PAGE - 1)
        rd_va = kernel_end
        kernel_end = rd_va + rd_size
        rd_pa = rd_va - virt_base + PHYS_BASE
        pieces.append((rd_va, rd_size, image))
        if kernel_end > UINT64_MAX or rd_pa > UINT64_MAX:
            raise ValueError(f'{name} placement overflow')
        adt_blob = add_ramdisk_to_adt(adt_blob, rd_pa, rd_size, name)
        if name == 'RAMDisk':
            ramdisk = (hex(rd_pa), hex(rd_size))
        else:
            ramdisk1 = (hex(rd_pa), hex(rd_size))

    validate_layout(pieces, virt_base, PHYS_BASE, MEM_SIZE, kernel_end, len(adt_blob))

    hdr_size = SEG_TABLE + 32 * len(pieces)
    out = bytearray(hdr_size)
    seg_table = []
    for vmaddr, vmsize, data in pieces:
        off = len(out)
        out += data
        out += b'\0' * (-len(out) & 0xf)
        seg_table.append((vmaddr, vmsize, off, len(data)))
    adt_off = len(out)
    out += adt_blob
    out += b'\0' * (-len(out) & 0xf)

    struct.pack_into('<8sII', out, 0, b'TEGUXNU', 1, len(pieces))
    struct.pack_into('<7Q', out, 0x10, virt_base, m['entry'], adt_off, len(adt_blob), kernel_end,
                     PHYS_BASE, MEM_SIZE)
    cl = cmdline.encode()[:BOOT_LINE_LENGTH - 1]
    out[CMDLINE:CMDLINE + len(cl)] = cl
    for i, t in enumerate(seg_table):
        struct.pack_into('<4Q', out, SEG_TABLE + 32 * i, *t)
    info = dict(cputype=hex(m['cputype']), cpusub=m['cpusub'], fixups=nfix, virt_base=hex(virt_base),
                entry=hex(m['entry']), kernel_end=hex(kernel_end), ramdisk=ramdisk, size=len(out),
                segs=[(s['name'], hex(s['vmaddr']), hex(s['vmsize'])) for s in segs])
    if ramdisk1 is not None:
        info['ramdisk1'] = ramdisk1
    return bytes(out), info


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('kernel'); ap.add_argument('adt'); ap.add_argument('out')
    ap.add_argument('--cmdline', default='debug=0xc serial=3 cpus=1 keepsyms=1')
    ap.add_argument('--ramdisk', help='root image for md0 (boot with rd=md0)')
    ap.add_argument('--ramdisk1', help='second image for md1 (requires --ramdisk)')
    a = ap.parse_args()
    try:
        blob, info = build(a.kernel, a.adt, a.cmdline, a.ramdisk, a.ramdisk1)
    except ValueError as exc:
        ap.error(str(exc))
    open(a.out, 'wb').write(blob)
    for k, v in info.items():
        if k != 'segs':
            print(f'{k}: {v}')
    for s in info['segs']:
        print('  ', *s)
