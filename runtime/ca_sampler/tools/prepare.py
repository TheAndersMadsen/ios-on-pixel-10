#!/usr/bin/env python3
"""Generate addresses/fingerprints, never Apple code, from the local reference."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from paths import DEFAULT_BINARY, DEFAULT_DISASSEMBLY, DEFAULT_OUTPUT, generated
FN = 0x184129A9C
SIZE = 0x100
TABLE = 0x1EE985C60 + 128  # format 1, sixteen sampler function pointers


def inspect(binary, disassembly):
    b = binary.read_bytes()
    if struct.unpack_from('<I', b)[0] != 0xFEEDFACF:
        raise ValueError('expected thin little-endian Mach-O 64')
    ncmds = struct.unpack_from('<I', b, 16)[0]
    segments = []
    uuid = None
    p = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', b, p)
        if cmd == 0x19:
            name, va, vsize, off, fsize = struct.unpack_from('<16sQQQQ', b, p + 8)
            segments.append((name.rstrip(b'\0').decode(), va, vsize, off, fsize))
        if cmd == 0x1B:
            uuid = b[p+8:p+24]
        p += size

    def read(va, length):
        for _, addr, _, off, size in segments:
            if addr <= va and va + length <= addr + size:
                return b[off+va-addr:off+va-addr+length]
        raise ValueError(f'unmapped reference {va:#x}')

    code = read(FN, SIZE)
    projective = read(0x184129684, 0x304)
    instructions = []
    for line in disassembly.read_text().splitlines():
        m = re.match(r'0x([a-f0-9]+):  ((?:[a-f0-9]{2} ){3}[a-f0-9]{2})\s+(.*)', line)
        if m and FN <= int(m[1], 16) < FN + SIZE:
            instructions.append((int(m[1], 16), bytes.fromhex(m[2]), m[3]))
    assert len(instructions) == SIZE // 4
    for i, (addr, value, op) in enumerate(instructions):
        assert addr == FN + 4*i and value == code[4*i:4*i+4]
        assert not re.match(r'(?:adr|bl\b|blr|ldr\s+\w+,\s+0x)', op), op
    assert instructions[-1][2] == 'ret'
    # Extracted shared-cache auth chained pointers encode cache-relative targets.
    words = struct.unpack('<16Q', read(TABLE, 128))
    assert all(v >> 48 == 0x8010 for v in words)
    functions = [0x180000000 + (v & 0xFFFFFFFF) for v in words]
    assert functions[10] == FN
    def fnv(code):
        h = 0xCBF29CE484222325
        for x in code:
            h = ((h ^ x) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        return hex(h)
    assert uuid is not None
    return dict(binary_sha256=hashlib.sha256(b).hexdigest(), uuid=uuid.hex(),
                function=hex(FN), size=SIZE, sha256=hashlib.sha256(code).hexdigest(),
                fnv=fnv(code), format_table=hex(TABLE), slot_index=10,
                slot=hex(TABLE+80), functions=[hex(x) for x in functions],
                projective_function='0x184129684', projective_size=0x304,
                projective_sha256=hashlib.sha256(projective).hexdigest(), projective_fnv=fnv(projective),
                oracle='unaltered self-contained ARM64 leaf, executed locally by host harness')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--binary', type=Path, default=DEFAULT_BINARY)
    ap.add_argument('--disassembly', type=Path, default=DEFAULT_DISASSEMBLY)
    ap.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    output = generated(args.output_dir)
    r = inspect(args.binary, args.disassembly)
    if (r['binary_sha256'] != '8836d8c530ff926cc2e2b44e74b444aba114774d1fe85818f18a9a7cb9f1defc' or
            r['uuid'] != '8f1e0b3fadd63710a790009333597ab4'):
        raise ValueError('local reference is not the tested 23G90 QuartzCore')
    (output/'receipts').mkdir(parents=True, exist_ok=True)
    (output/'build').mkdir(exist_ok=True)
    (output/'receipts/reference.json').write_text(json.dumps(r, indent=2)+'\n')
    header = '#ifndef HS_FINGERPRINT_H\n#define HS_FINGERPRINT_H\n#include <stdint.h>\n'
    header += '#define HS_NEW_UNSLID UINT64_C(0x184105eb4)\n'
    header += f'#define HS_FN_UNSLID UINT64_C({r["function"]})\n#define HS_FN_SIZE {r["size"]}\n'
    header += f'#define HS_FN_FNV UINT64_C({r["fnv"]})\n'
    header += f'#define HS_PROJECTIVE_FN_UNSLID UINT64_C({r["projective_function"]})\n'
    header += f'#define HS_PROJECTIVE_FN_SIZE {r["projective_size"]}\n#define HS_PROJECTIVE_FN_FNV UINT64_C({r["projective_fnv"]})\n'
    header += f'#define HS_FORMAT_TABLE_UNSLID UINT64_C({r["format_table"]})\n#define HS_SLOT_INDEX 10\n'
    header += 'static const uint8_t hs_qc_uuid[16] = {'+','.join(f'0x{x:02x}' for x in bytes.fromhex(r['uuid']))+'};\n'
    header += 'static const uintptr_t hs_expected_functions[16] = {'+','.join('UINT64_C('+x+')' for x in r['functions'])+'};\n#endif\n'
    (output/'build/fingerprint.h').write_text(header)
    print(json.dumps(r, indent=2))


if __name__ == '__main__':
    main()
