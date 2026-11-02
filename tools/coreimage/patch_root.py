#!/usr/bin/env python3
"""Clone a local 23G90 HFS root and apply only CoreImage's isWidget=true experiment.

Requires the existing local HFS reader; no Apple bytes or third-party reader are
distributed here. The input is always opened read-only. Outputs must be new.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

CACHE_DIR = '/System/Library/Caches/com.apple.dyld/'
CACHE_NAME = 'dyld_shared_cache_arm64e.09'
CACHE_UUID = bytes.fromhex('0f1ee33235db30f38f5fbd4b954138d5')
IMAGE_UUID = bytes.fromhex('6f5abd160e3c3fc3bcc7ccefeafbca00')
IMAGE_VA = 0x19df07000
FUNCTION_VA = 0x19e041778
EXPECTED = bytes.fromhex('688127f0085944f91f0500b181000054')
REPLACEMENT = struct.pack('<II', 0x52800020, 0xd65f03c0)  # mov w0,#1; ret


class Raw:
    def __init__(self, path):
        self.f = open(path, 'rb')

    def read(self, offset, size):
        self.f.seek(offset)
        data = self.f.read(size)
        if len(data) != size:
            raise ValueError('short image read')
        return data


def sha256(path, restore=()):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        offset = 0
        while chunk := f.read(8 << 20):
            end = offset + len(chunk)
            for change in restore:
                start = change['image_offset']
                before = bytes.fromhex(change['before'])
                lo, hi = max(start, offset), min(start + len(before), end)
                if lo < hi:
                    chunk = chunk[:lo-offset] + before[lo-start:hi-start] + chunk[hi-offset:]
            h.update(chunk)
            offset = end
    return h.hexdigest()


def read_at(file, offset, size):
    if offset < 0 or size < 0 or offset + size > file.size:
        raise ValueError('cache read exceeds file')
    file.seek(offset)
    data = file.read(size)
    if len(data) != size:
        raise ValueError('short cache read')
    return data


def translated(file, va, size):
    offset, count = struct.unpack('<II', read_at(file, 0x10, 8))
    if count > 128:
        raise ValueError('unexpected mapping count')
    matches = []
    for i in range(count):
        addr, length, pos, _, prot = struct.unpack('<QQQII', read_at(file, offset + 32*i, 32))
        if addr <= va and va + size <= addr + length:
            matches.append((pos + va - addr, prot))
    if len(matches) != 1:
        raise ValueError('address has no unique cache mapping')
    return matches[0]


def image_uuid(file):
    pos, _ = translated(file, IMAGE_VA, 32)
    header = read_at(file, pos, 32)
    magic, _, _, _, count, command_bytes = struct.unpack_from('<6I', header)
    if magic != 0xfeedfacf or count > 128 or command_bytes > 65536:
        raise ValueError('unexpected CoreImage Mach-O header')
    end = pos + 32 + command_bytes
    p = pos + 32
    for _ in range(count):
        command, size = struct.unpack('<II', read_at(file, p, 8))
        if size < 8 or p + size > end:
            raise ValueError('invalid CoreImage load command')
        if command == 0x1b and size == 24:
            return read_at(file, p + 8, 16)
        p += size
    raise ValueError('missing CoreImage UUID')


def physical_changes(file, offset, before, after, kind):
    if len(before) != len(after) or not before:
        raise ValueError('patch changes file size')
    changes = []
    pos = offset
    for logical, physical_block, count in file.ext:
        length = count * file.vol.bsize
        if logical <= pos < logical + length:
            n = min(len(before), logical + length - pos)
            changes.append({'kind': kind, 'cache_offset': pos,
                'image_offset': physical_block * file.vol.bsize + pos - logical,
                'before': before[:n].hex(), 'after': after[:n].hex()})
            pos += n
            before, after = before[n:], after[n:]
            if not before:
                return changes
    raise ValueError('patch not covered by HFS extents')


def plan(volume):
    main = volume.open(CACHE_DIR + 'dyld_shared_cache_arm64e')
    if read_at(main, 0x58, 16) != CACHE_UUID:
        raise ValueError('unknown shared-cache UUID')
    file = volume.open(CACHE_DIR + CACHE_NAME)
    if image_uuid(file) != IMAGE_UUID:
        raise ValueError('unknown CoreImage UUID')
    offset, prot = translated(file, FUNCTION_VA, len(EXPECTED))
    if prot != 5 or read_at(file, offset, len(EXPECTED)) != EXPECTED:
        raise ValueError('isWidget entry differs or is already patched')
    changes = physical_changes(file, offset, EXPECTED[:8], REPLACEMENT, 'isWidget')
    sig_offset, sig_size = struct.unpack('<QQ', read_at(file, 0x28, 16))
    magic, length, count = struct.unpack('>III', read_at(file, sig_offset, 12))
    if magic != 0xfade0cc0 or length > sig_size or count > 128:
        raise ValueError('invalid signature superblob')
    directories = []
    for i in range(count):
        slot, rel = struct.unpack('>II', read_at(file, sig_offset + 12 + 8*i, 8))
        cd = sig_offset + rel
        if cd + 8 > sig_offset + length:
            raise ValueError('signature entry exceeds superblob')
        if struct.unpack('>I', read_at(file, cd, 4))[0] != 0xfade0c02:
            continue
        if cd + 44 > sig_offset + length:
            raise ValueError('short CodeDirectory')
        header = read_at(file, cd, 44)
        _, cd_size, _, _, hash_offset, _, _, pages, limit = struct.unpack_from('>9I', header)
        hash_size, hash_type, _, shift = struct.unpack_from('4B', header, 36)
        names = {1:'sha1', 2:'sha256', 3:'sha256', 4:'sha384'}
        if hash_type not in names or shift not in (12, 14) or hash_size > hashlib.new(names[hash_type]).digest_size:
            raise ValueError('unsupported signature hash or page size')
        page_size = 1 << shift
        if (cd + cd_size > sig_offset + length or limit > sig_offset or
                pages != (limit + page_size - 1) // page_size or
                hash_offset < 44 or hash_offset + pages * hash_size > cd_size):
            raise ValueError('invalid CodeDirectory bounds')
        first, last = offset // page_size, (offset + len(REPLACEMENT) - 1) // page_size
        for page in range(first, last + 1):
            if page >= pages:
                raise ValueError('function is outside signed pages')
            start = page * page_size
            data = bytearray(read_at(file, start, min(page_size, limit-start)))
            digest = lambda b: hashlib.new(names[hash_type], b).digest()[:hash_size]
            hash_pos = cd + hash_offset + page * hash_size
            old = read_at(file, hash_pos, hash_size)
            if old != digest(data):
                raise ValueError('existing function page signature is invalid')
            lo, hi = max(start, offset), min(start + len(data), offset + len(REPLACEMENT))
            data[lo-start:hi-start] = REPLACEMENT[lo-offset:hi-offset]
            changes += physical_changes(file, hash_pos, old, digest(data), 'page_hash')
        directories.append({'slot':slot, 'hash':names[hash_type], 'page_size':page_size, 'code_pages':pages})
    if not directories:
        raise ValueError('no CodeDirectory')
    changes.sort(key=lambda c:c['image_offset'])
    for a, b in zip(changes, changes[1:]):
        if a['image_offset'] + len(bytes.fromhex(a['before'])) > b['image_offset']:
            raise ValueError('overlapping changes')
    return {'cache_file':CACHE_NAME, 'function_va':hex(FUNCTION_VA), 'cache_offset':hex(offset),
        'cache_uuid':CACHE_UUID.hex(), 'image_uuid':IMAGE_UUID.hex(),
        'signature_directories':directories, 'changes':changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--hfs-reader', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists() or args.report.is_symlink():
        raise SystemExit('report exists; no overwrite')
    source = args.source.resolve(strict=True)
    actual = sha256(source)
    if actual != args.source_sha256:
        raise SystemExit('source SHA256 differs; no output created')
    spec = importlib.util.spec_from_file_location('coreimage_hfs_reader', args.hfs_reader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = Raw(source)
    try:
        report = plan(module.Vol(raw))
    finally:
        raw.f.close()
    report.update(source=str(source), source_sha256=actual, applied=False)
    if args.output:
        if args.output.exists() or args.output.is_symlink():
            raise SystemExit('output exists; no overwrite')
        # Publish the clone with an exclusive hard-link operation. cp's normal
        # destination handling must never replace an existing caller artifact.
        with tempfile.TemporaryDirectory(prefix='.coreimage-clone-', dir=args.output.parent) as directory:
            temporary = Path(directory)/'root.img'
            subprocess.run(['cp', '-c', str(source), str(temporary)], check=True)
            os.link(temporary, args.output)
        os.chmod(args.output, 0o600)
        if os.path.samefile(source, args.output):
            raise SystemExit('output aliases source')
        with args.output.open('r+b') as f:
            for change in report['changes']:
                f.seek(change['image_offset'])
                before, after = bytes.fromhex(change['before']), bytes.fromhex(change['after'])
                if f.read(len(before)) != before:
                    raise SystemExit('clone differs before patch')
                f.seek(change['image_offset'])
                if f.write(after) != len(after):
                    raise SystemExit('short patch write')
            f.flush(); os.fsync(f.fileno())
        if sha256(args.output, report['changes']) != actual:
            raise SystemExit('output differs beyond planned function/signature edits')
        if sha256(source) != actual:
            raise SystemExit('source changed during operation')
        os.chmod(args.output, 0o444)
        report.update(output=str(args.output.resolve()), output_sha256=sha256(args.output),
            applied=True, only_planned_changes=True, source_unchanged=True)
    with args.report.open('x') as f:
        json.dump(report, f, indent=2); f.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
