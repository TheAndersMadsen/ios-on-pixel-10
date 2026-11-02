#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline Android v4 boot-chain component inventory, checked against pinned AOSP.

Reads regular local copies only. Never reaches a device or executes unpacked
commands. Structural agreement is separate from AVB trust, slot provenance,
complete backups and Android integrity. Extracts stay outside tracked paths.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dualboot import Refused, regular_open, require, small_file, write_new

AOSP_REF = 'd2bb0af5ba6d3198a3e99529c97eda1be0b5a093'
AOSP_SHA = 'a9d260978a63bd06a24b6347e7dee8a28ff96639793caea15dff6aa491316308'
AOSP_URL = f'https://android.googlesource.com/platform/system/tools/mkbootimg/+/{AOSP_REF}/unpack_bootimg.py'
ROOT = Path(__file__).resolve().parents[1]
LIMIT = 256 * 1024 * 1024
ROLES = ('boot', 'init_boot', 'vendor_boot', 'vendor_kernel_boot', 'dtbo',
         'vbmeta', 'vbmeta_system', 'vbmeta_vendor')
VENDOR_ENTRY = struct.Struct('<III32s16I')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_exact(f, offset, size, total):
    require(type(offset) is int and type(size) is int and 0 <= offset <= total and
            0 <= size <= total-offset, 'component outside image')
    data = os.pread(f.fileno(), size, offset)
    require(len(data) == size, 'short component read')
    return data


def hash_extent(f, offset, size, total):
    require(0 <= offset <= total and 0 <= size <= total-offset, 'hash extent outside image')
    h = hashlib.sha256()
    while size:
        chunk = read_exact(f, offset, min(size, 1024*1024), total)
        h.update(chunk); offset += len(chunk); size -= len(chunk)
    return h.hexdigest()


def aligned(value, page):
    return (value+page-1)//page*page


def cstring(raw, filename=False):
    value = raw.split(b'\0', 1)[0]
    try:
        text = value.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise Refused('invalid UTF-8 header string') from exc
    # AOSP makes a by-name symlink from this field. Keep it one path component.
    if filename:
        require(re.fullmatch(r'[A-Za-z0-9_.-]*', text) is not None, 'unsafe vendor fragment name')
    return text


def inspect_image(f, role, total):
    require(role in ROLES and 0 < total <= LIMIT, 'unsupported role or image size')
    head = read_exact(f, 0, min(total, 4096), total)
    components, fragments = [], []

    def component(name, offset, size, oracle=None):
        require(offset <= total and size <= total-offset, f'{name} truncated/out of image')
        value = dict(name=name, offset=offset, size=size,
                     sha256=hash_extent(f, offset, size, total), oracle_file=oracle)
        components.append(value)
        return value

    if role in ('dtbo', 'vbmeta', 'vbmeta_system', 'vbmeta_vendor'):
        # These need their own mature validators; a hash is not an AVB/DTBO check.
        return dict(format='opaque-dependency', structural_validation=False,
                    components=[dict(name=role, offset=0, size=total,
                                     sha256=hash_extent(f, 0, total, total), oracle_file=None)],
                    avb_verification='not performed', aosp_checked=False)
    if role in ('boot', 'init_boot'):
        require(len(head) >= 1584 and head[:8] == b'ANDROID!', 'not an Android v4 boot/init_boot header')
        kernel, ramdisk, os_version, header_size = struct.unpack_from('<IIII', head, 8)
        version = struct.unpack_from('<I', head, 40)[0]
        require(version == 4 and header_size == 1584 and not any(head[24:40]), 'unsupported boot header/reserved fields')
        signature = struct.unpack_from('<I', head, 1580)[0]
        cmdline = cstring(head[44:1580])
        if role == 'init_boot':
            require(kernel == 0 and ramdisk > 0, 'init_boot must contain a generic ramdisk and no kernel')
        else:
            require(kernel > 0, 'boot image has no kernel')
        page = 4096
        component('kernel', page, kernel, 'kernel')
        ramdisk_at = page + aligned(kernel, page)
        component('ramdisk', ramdisk_at, ramdisk, 'ramdisk')
        if signature:
            component('boot_signature', ramdisk_at+aligned(ramdisk, page), signature, 'boot_signature')
        fmt = 'android-boot-v4'
        detail = dict(header_size=header_size, os_version_field=os_version,
                      command_line_bytes=len(cmdline.encode()), command_line_sha256=digest(head[44:1580]))
    else:
        require(len(head) >= 2128 and head[:8] == b'VNDRBOOT', 'not a vendor boot v4 header')
        version, page = struct.unpack_from('<II', head, 8)
        header_size, dtb_size = struct.unpack_from('<II', head, 2096)
        require(version == 4 and header_size == 2128 and 2048 <= page <= 65536 and page & (page-1) == 0,
                'unsupported vendor header/page size')
        ramdisk_size = struct.unpack_from('<I', head, 24)[0]
        table_size, count, entry_size, config_size = struct.unpack_from('<IIII', head, 2112)
        require(entry_size == VENDOR_ENTRY.size and 0 < count <= 4096 and table_size == count*entry_size,
                'invalid vendor fragment table shape')
        require(ramdisk_size > 0 and table_size <= 1024*1024, 'vendor ramdisk/table missing or oversized')
        cstring(head[28:2076]); cstring(head[2080:2096])
        ramdisk_at = aligned(header_size, page)
        dtb_at = ramdisk_at + aligned(ramdisk_size, page)
        table_at = dtb_at + aligned(dtb_size, page)
        config_at = table_at + aligned(table_size, page)
        component('vendor_ramdisk', ramdisk_at, ramdisk_size)
        if dtb_size:
            component('dtb', dtb_at, dtb_size, 'dtb')
        table = read_exact(f, table_at, table_size, total)
        component('vendor_ramdisk_table', table_at, table_size)
        component('bootconfig', config_at, config_size, 'bootconfig')
        names = set()
        for i in range(count):
            size, offset, typ, raw_name, *board = VENDOR_ENTRY.unpack_from(table, i*entry_size)
            name = cstring(raw_name, filename=True)
            require(name not in names and typ in (0, 1, 2, 3), 'duplicate fragment name or unsupported type')
            names.add(name)
            require(size > 0 and offset <= ramdisk_size and size <= ramdisk_size-offset, 'fragment outside vendor ramdisk')
            fragments.append(dict(index=i, size=size, relative_offset=offset, type=typ, name=name,
                                  board_id=board, offset=ramdisk_at+offset,
                                  sha256=hash_extent(f, ramdisk_at+offset, size, total),
                                  oracle_file=f'vendor_ramdisk{i:02}'))
        intervals = sorted((v['relative_offset'], v['relative_offset']+v['size']) for v in fragments)
        end = 0
        for first, last in intervals:
            require(first == end, 'overlap or unrepresented gap in vendor ramdisk fragments')
            end = last
        require(end == ramdisk_size, 'vendor fragments do not cover the complete ramdisk section')
        fmt = 'android-vendor-boot-v4'
        detail = dict(header_size=header_size, fragment_count=count,
                      command_line_sha256=digest(head[28:2076]), board_name_sha256=digest(head[2080:2096]))
    for a, b in zip(components, components[1:]):
        require(a['offset']+a['size'] <= b['offset'], 'overlapping image sections')
    return dict(format=fmt, header_version=4, page_size=page, **detail,
                components=components, fragments=fragments, structural_validation=True,
                aosp_checked=False, avb_verification='not performed')


def aosp_module(path):
    source = small_file(path, 128*1024)
    require(digest(source) == AOSP_SHA, 'unpacker does not match the pinned AOSP SHA256')
    require(sys.byteorder == 'little', 'pinned unpacker uses native endian structs; little-endian host required')
    module = types.ModuleType('pinned_aosp_unpack_bootimg')
    # Execute only the verified pinned source. No downloaded mkbootimg command
    # string, image cmdline or arbitrary module path is executed.
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def compare_aosp(module, f, parsed, out, total):
    out.mkdir(mode=0o700)
    f.seek(0)
    if parsed['format'] == 'android-boot-v4':
        info = module.unpack_boot_image(f, str(out))
    elif parsed['format'] == 'android-vendor-boot-v4':
        info = module.unpack_vendor_boot_image(f, str(out))
        for actual, expected in zip(info.vendor_ramdisk_table, parsed['fragments'], strict=True):
            filename, size, offset, typ, name, board_id = actual
            require((filename, size, offset, typ, name, list(board_id)) ==
                    (expected['oracle_file'], expected['size'], expected['relative_offset'],
                     expected['type'], expected['name'], expected['board_id']), 'AOSP fragment metadata differs')
    else:
        return
    require(info.header_version == 4 and info.page_size == parsed['page_size'], 'AOSP header interpretation differs')
    for part in parsed['components']+parsed.get('fragments', []):
        name = part.get('oracle_file')
        if name is None:
            continue
        with regular_open(out/name) as extracted:
            size = os.fstat(extracted.fileno()).st_size
            require(size == part['size'] and hash_extent(extracted, 0, size, size) == part['sha256'],
                    'AOSP extraction differs from bounded source extent')
    parsed['aosp_checked'] = True


def inventory(images, slot, unpacker, out):
    require(slot in ('a', 'b') and images and len(images) <= len(ROLES), 'slot/image set invalid')
    require(len({role for role, _ in images}) == len(images), 'duplicate boot-chain role')
    out = Path(out).resolve()
    require(not out.exists(), 'output already exists')
    require(not out.is_relative_to(ROOT) or out.is_relative_to(ROOT/'research'),
            'device artifacts inside the repo must be under ignored research/')
    module = aosp_module(unpacker)
    report = dict(schema=1, slot_claim=slot, slot_provenance='caller supplied; not established by header parsing',
                  aosp=dict(commit=AOSP_REF, sha256=AOSP_SHA, url=AOSP_URL), images=[],
                  avb_chain_verified=False, trusted_stock_key_verified=False,
                  current_device_contents_verified=False, android_integrity_proven=False,
                  complete_recovery_backup=False, ready_for_android_dispatch=False)
    out.mkdir(mode=0o700, parents=True)
    for role, path in images:
        require(role in ROLES, 'unknown boot-chain role')
        with regular_open(path) as f:
            before = os.fstat(f.fileno())
            total = before.st_size
            parsed = inspect_image(f, role, total)
            source_sha = hash_extent(f, 0, total, total)
            if parsed['format'] != 'opaque-dependency':
                compare_aosp(module, f, parsed, out/role, total)
            after = os.fstat(f.fileno())
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns) and
                    hash_extent(f, 0, total, total) == source_sha, 'input changed during inventory')
            parsed.update(role=role, path=str(Path(path).absolute()), bytes=total, sha256=source_sha)
            report['images'].append(parsed)
    supplied = {role for role, _ in images}
    # This Pixel family has a separate vendor_kernel_boot image in saved slot b.
    # Actual dependencies still need current GPT plus a verified AVB graph.
    report['missing_pixel_boot_roles'] = sorted(set(('boot', 'init_boot', 'vendor_boot', 'vendor_kernel_boot'))-supplied)
    report['missing_dtbo_avb_inventory'] = sorted(set(('dtbo', 'vbmeta', 'vbmeta_system', 'vbmeta_vendor'))-supplied)
    report['unresolved'] = ['current slot/partition capture provenance', 'complete current GPT and AVB dependency graph',
                            'AVB signature and independently trusted stock key', 'Android data and F2FS alias integrity',
                            'isolated iOS storage', 'physical Android return and recovery']
    write_new(out/'inventory.json', (json.dumps(report, indent=2)+'\n').encode())
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--slot', choices=('a', 'b'), required=True)
    p.add_argument('--image', action='append', required=True, help='ROLE=PATH, once per boot-chain role')
    p.add_argument('--aosp-unpacker', default=str(ROOT/'third_party/aosp_bootimg/unpack_bootimg.py'))
    p.add_argument('--output', required=True)
    a = p.parse_args(argv)
    images = []
    for arg in a.image:
        role, sep, path = arg.partition('=')
        require(sep and path, '--image needs ROLE=PATH')
        images.append((role, path))
    mask = os.umask(0o077)
    try:
        report = inventory(images, a.slot, a.aosp_unpacker, a.output)
    finally:
        os.umask(mask)
    print(json.dumps(dict(output=str(Path(a.output).absolute()),
                          images=len(report['images']), aosp_checked=sum(x['aosp_checked'] for x in report['images']),
                          missing_pixel_boot_roles=report['missing_pixel_boot_roles'],
                          missing_dtbo_avb_inventory=report['missing_dtbo_avb_inventory'],
                          ready_for_android_dispatch=False), indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Refused, OSError, ValueError, TypeError) as exc:
        sys.exit(f'android-bootset: refused: {exc}')
