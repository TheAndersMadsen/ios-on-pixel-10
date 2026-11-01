"""Read XNU's embedded panic region ("KNUF") from a raw log-RAM dump. Host only.

The region survives warm resets, so a copy in a dump is residue until bound to
the boot that just ran. Binding needs a fresh shim handoff -> XNU entry record,
and the panic's Epoch "Boot" time, which runs on the cntvct clock, must fall just
after that entry. A long early boot can miss the window: that reports the region
as unbound, with the gap, and never as current.

eph_crc is reported and not used. On the phone no byte range reproduces it
(capture of 2026-11-01, every start in the header, every end up to 0x8000).
Layout: osfmk/kern/debug.h, struct embedded_panic_header.
"""
import re
import struct

MAGIC = b"KNUF"
HEADER = struct.Struct("<4sIIQ6I")
CNTFRQ = 38400000
BOOT_BIND_SECONDS = 3.0
_MAX_HITS = 64


def find_regions(data):
    """Every page-aligned region whose panic log offsets are coherent."""
    found = []
    pos = 0
    for _ in range(_MAX_HITS):
        off = data.find(MAGIC, pos)
        if off < 0:
            break
        pos = off + 1
        if off % 0x1000 or off + HEADER.size > len(data):
            continue
        _, crc, version, flags, log_off, log_len, *_rest = HEADER.unpack_from(data, off)
        if not (HEADER.size <= log_off < 0x1000 and 0 < log_len <= 0x100000):
            continue
        if off + log_off + log_len > len(data):
            continue
        text = bytes(data[off + log_off:off + log_off + log_len]).decode("utf-8", "replace")
        if not text.startswith("panic("):
            continue
        found.append(_describe(off, crc, version, flags, text))
    return found


def _describe(off, crc, version, flags, text):
    boot = re.search(r"Boot\s*:\s*(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)", text)
    abs_time = re.search(r"mach_absolute_time:\s*(0x[0-9a-fA-F]+)", text)
    uuid = re.search(r"Kernel UUID:\s*([0-9A-Fa-f-]{36})", text)
    head = re.match(r"panic\(cpu\s+\d+\s+caller\s+(0x[0-9a-fA-F]+)\)\s*:\s*(.*)", text)
    return {
        "offset": off, "crc": crc, "version": version, "flags": flags, "text": text,
        "caller": int(head.group(1), 16) if head else None,
        "message": head.group(2).strip() if head else None,
        "boot_seconds": int(boot.group(1), 16) + int(boot.group(2), 16) / 1e6 if boot else None,
        "mach_absolute_time": int(abs_time.group(1), 16) if abs_time else None,
        "kernel_uuid": uuid.group(1).upper() if uuid else None,
    }


def boot_gap_seconds(region, entry_check):
    """Panic Boot time minus XNU entry, or None if the panic cannot be compared."""
    entry = entry_check.get("entry_cntvct")
    if not entry or region.get("boot_seconds") is None:
        return None
    return region["boot_seconds"] - entry / CNTFRQ


def is_current(region, entry_check):
    """True only if this region was written by the boot in entry_check."""
    gap = boot_gap_seconds(region, entry_check)
    if not entry_check.get("fresh") or gap is None:
        return False
    if region.get("mach_absolute_time") is None:
        return False
    return (region["mach_absolute_time"] >= entry_check["entry_cntvct"] and
            0 <= gap <= BOOT_BIND_SECONDS)


def select(data, entry_check):
    """(current region or None, all regions)."""
    regions = find_regions(data)
    return next((r for r in regions if is_current(r, entry_check)), None), regions
