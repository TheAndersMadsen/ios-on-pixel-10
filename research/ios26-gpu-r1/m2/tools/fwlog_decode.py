#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Decode blazer_gpu_tipc=6's firmware log ("HK GPUTA: M2 TB xxxx: 8 words" lines) against the pinned DDK's rgx_fwif_sf.h.
Usage: python3 -I fwlog_decode.py <kernel.log> <path to pvrsrvkm/include/rgx_fwif_sf.h>
Entry layout as RGXDumpFirmwareTrace reads it (rgxdebug_common.c): id, timestamp high, timestamp low, RGXFW_SF_PARAMNUM(id) params.
Reads the vendor header at run time; nothing of it is copied here. Prints one line per entry; unknown words are skipped as the host does."""
import re, sys

def load_sf(path):
    text = open(path, encoding='latin-1').read()
    groups = re.search(r'#define RGXFW_LOG_SFGROUPLIST(.*?)\n\n', text, re.S).group(1)
    gid = {m.group(1): i for i, m in enumerate(re.finditer(r'X\((RGXFW_GROUP_\w+),\s*(\w+)\)', groups))}
    names = {i: m.group(2) for i, m in enumerate(re.finditer(r'X\((RGXFW_GROUP_\w+),\s*(\w+)\)', groups))}
    sfs = {}
    for m in re.finditer(r'X\(\s*(\d+),\s*(RGXFW_GROUP_\w+),\s*(\w+),\s*"((?:[^"\\]|\\.)*)",\s*(\d+)\)', text):
        a, g, name, fmt, e = int(m.group(1)), gid[m.group(2)], m.group(3), m.group(4), int(m.group(5))
        sid = (a | ((g & 0x10) << 7) | ((g & 0xF) << 12) | (e << 16)) | 0x70000000
        sfs[sid] = (name, fmt, e, names[g])
    return sfs

def pyfmt(fmt, args):
    out, i = [], 0
    def conv(m):
        nonlocal i
        spec = m.group(0)
        if spec == '%%':
            return '%'
        v = args[i] if i < len(args) else 0
        i += 1
        flags, width, typ = m.group(1) or '', m.group(2) or '', m.group(4)
        if typ in 'di':
            v = v - (1 << 32) if v & 0x80000000 else v
            typ = 'd'
        if typ == 'u':
            typ = 'd'
        if typ == 's':
            return '<str>'
        return ('%' + flags + width + typ) % v
    return re.sub(r'%([-0#+ ]*)(\d*)(\.\d+)?(?:ll|l|h)?([diuxXcs%])', conv, fmt.replace('\\n', ' '))

def main():
    log, sfh = sys.argv[1], sys.argv[2]
    sfs = load_sf(sfh)
    words, seen = [], None
    for line in open(log, encoding='latin-1', errors='replace'):
        m = re.search(r'M2 TB ([0-9a-f]{4}): ((?:[0-9a-f]{8} ?){8})', line)
        if m:
            words.extend(int(w, 16) for w in m.group(2).split())
        if 'M2 fwlog: ptr' in line:
            seen = line.strip()
    print('#', seen or 'no fwlog header', f'({len(words)} words)')
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        if w not in sfs:
            i += 1
            continue
        name, fmt, e, grp = sfs[w]
        if i + 3 + e > n:
            print(f'{i:5d}: {grp} {name} (truncated)')
            break
        ts = (words[i + 1] << 32 | words[i + 2]) & 0xFFFFFFFFFFFF
        args = words[i + 3:i + 3 + e]
        print(f'{i:5d}: {ts:#014x} {grp:7s} {pyfmt(fmt, args)}   [{name}]')
        i += 3 + e

if __name__ == '__main__':
    main()
