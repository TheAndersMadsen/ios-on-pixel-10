#!/usr/bin/env python3
"""Read-only comparison of Inferno's CoreImage targets against a local root cache.

Use a symbol dump from the matching stock cache and the existing local
pacstrip_cache.py reader. Private symbols need not exist in the pruned root.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys

TARGETS = (
    '_CI_ENABLE_METAL_GPU', '_CI_ENABLE_METAL_BLIT', '_CI_ENABLE_MPS',
    '_CI_ENABLE_METAL_CONVERT', '_CI_ENABLE_METAL_CAPTURE', '_CI_ENABLE_METAL_LABEL',
    '_CI_ENABLE_METAL_IMAGEBLOCKS', '_CI_HARVEST_SPECIALIZED_MTL_FUNCTIONS',
    '_CI_USE_MTL_DAG_FOR_CIKL_SRC', '_wrapGLIsUsable', '_wrapGLIsAccelerated', '_isWidget',
)


def read(cache, va, length):
    mapping = cache.translate(va, length)
    if mapping is None:
        raise ValueError('address not mapped')
    file, offset, _ = mapping
    return bytes(cache.bufs[file][offset:offset+length])


def image(cache):
    matches = [(a, p) for a, p in cache.images() if p.endswith('/CoreImage.framework/CoreImage')]
    if len(matches) != 1:
        raise ValueError('CoreImage image is not unique')
    va, path = matches[0]
    count, size = struct.unpack_from('<II', read(cache, va, 32), 16)
    pos, end = va + 32, va + 32 + size
    for _ in range(count):
        cmd, length = struct.unpack('<II', read(cache, pos, 8))
        if length < 8 or pos + length > end:
            raise ValueError('invalid load command')
        if cmd == 0x1b and length == 24:
            return {'address':hex(va), 'path':path, 'uuid':read(cache, pos+8, 16).hex(),
                'cache_uuid':bytes(cache.bufs[cache.main][0x58:0x68]).hex()}
        pos += length
    raise ValueError('missing UUID')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader', required=True, type=Path)
    parser.add_argument('--symbols', required=True, type=Path)
    parser.add_argument('--stock', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.reader.resolve().parent))
    spec = importlib.util.spec_from_file_location('coreimage_cache_reader', args.reader)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    stock, root = module.Cache(str(args.stock)), module.Cache(str(args.root))
    try:
        images = {'stock':image(stock), 'root':image(root)}
        if images['stock'] != images['root']:
            raise ValueError('stock/root image or cache identity differs')
        addresses, text = {}, set()
        for line in args.symbols.read_text().splitlines():
            fields = line.split('\t')
            match = re.match(r'0x([0-9a-f]+):', line)
            if not match:
                continue
            addr = int(match[1], 16)
            if len(fields) >= 3 and '__TEXT.__text' in fields[1]:
                text.add(addr)
                if fields[2] in TARGETS:
                    addresses[fields[2]] = addr
            if len(fields) < 3:
                for target in TARGETS:
                    if re.search(r'\)\s+' + re.escape(target) + r'$', line):
                        addresses.setdefault(target, addr)
        starts = sorted(text | set(addresses.values()))
        rows = []
        for target in TARGETS:
            if target not in addresses:
                rows.append({'symbol':target, 'missing':True}); continue
            start = addresses[target]
            end = next((a for a in starts if a > start), start + 8)
            if read(stock, start, 8) in (bytes.fromhex('20008052c0035fd6'), bytes.fromhex('00008052c0035fd6')):
                end = start + 8
            a, b = read(stock, start, end-start), read(root, start, end-start)
            file, offset, prot = root.translate(start, end-start)
            normalized = b''.join(struct.pack('<I', module.pacstrip.rewrite_word(w)[0]
                if module.pacstrip.rewrite_word(w)[0] is not None else w)
                for (w,) in struct.iter_unpack('<I', a))
            requested = bytes.fromhex('20008052c0035fd6' if target == '_isWidget' else '00008052c0035fd6')
            rows.append({'symbol':target, 'address':hex(start), 'length':end-start,
                'file':file, 'offset':hex(offset), 'prot':prot, 'root_entry':b[:8].hex(),
                'stock_entry':a[:8].hex(), 'root_sha256':hashlib.sha256(b).hexdigest(),
                'stock_sha256':hashlib.sha256(a).hexdigest(), 'entry_equal':a[:8] == b[:8],
                'same_after_pacstrip':normalized == b, 'inferno_return_stub_present':b[:8] == requested})
        report = {'images':images, 'functions':rows, 'source_symbol_sha256':
            hashlib.sha256(args.symbols.read_bytes()).hexdigest()}
        with args.output.open('x') as f:
            json.dump(report, f, indent=2); f.write('\n')
        print('CoreImage UUID:', images['root']['uuid'])
        for row in rows:
            print(row['symbol'], 'MISSING' if row.get('missing') else
                f"{row['address']} size={row['length']} same_after_pacstrip={row['same_after_pacstrip']} inferno_stub={row['inferno_return_stub_present']}")
    finally:
        for cache in (stock, root):
            for buf in cache.bufs.values():
                buf.close()


if __name__ == '__main__':
    main()
