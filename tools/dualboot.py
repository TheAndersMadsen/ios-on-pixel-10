#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only dual-boot storage evidence. Never flashes, mounts, reboots or changes slots.

capture-gpt needs the native blazer_usb_readback=1 service and a known image
nonce. It captures GPT metadata only, NOT an Android or iOS data backup.
inspect-image and inspect-snapshot work offline and do not import USB libraries.
All captures contain device data and belong outside git (normally research/).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import time
import uuid
import zlib

BLOCK = 4096
HEADER = struct.Struct('<8sIIIIIiQQQQIIII')
GPT = struct.Struct('<8sIIIIQQQQ16sQIII')
MAGIC = b'HKRB0001'
INFO, SELECT, DATA = 0x64, 0x65, 0x66
UNAVAILABLE, IDLE, QUEUED, LOADING, COMPLETE, FAILED = range(6)
FIELDS = ('magic', 'abi', 'header', 'block_bytes', 'lun', 'state', 'result',
          'nonce', 'entry', 'generation', 'lba', 'total', 'offset', 'count', 'crc')


class Refused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular_open(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise Refused('expected a regular local file')
    return os.fdopen(fd, 'rb')


def small_file(path, limit):
    with regular_open(path) as f:
        require(os.fstat(f.fileno()).st_size <= limit, 'metadata file exceeds bound')
        data = f.read(limit + 1)
    require(len(data) <= limit, 'metadata file grew beyond bound')
    return data


def packet(data):
    require(len(data) >= HEADER.size, 'short readback header')
    h = dict(zip(FIELDS, HEADER.unpack_from(data)))
    require(h['magic'] == MAGIC and h['abi'] == 1 and h['header'] == HEADER.size,
            'unsupported readback protocol')
    require(h['block_bytes'] == BLOCK and 0 <= h['lun'] < 8 and
            0 <= h['state'] <= FAILED and h['nonce'] != 0, 'invalid readback identity/state')
    require(h['count'] == len(data) - HEADER.size, 'readback byte count mismatch')
    require(h['offset'] < BLOCK and h['count'] <= BLOCK - h['offset'], 'readback chunk range')
    if h['state'] == COMPLETE:
        require(h['result'] == 0 and h['total'] == BLOCK, 'inconsistent successful read')
    else:
        require(h['total'] == h['count'] == h['crc'] == 0, 'data exposed before exact completion')
    return h, bytes(data[HEADER.size:])


class UsbReader:
    """One boot and one bound LUN. No reconnect, SET_CONFIGURATION, reset or retry of SELECT."""
    def __init__(self, device, nonce, blocks, clock=time.monotonic, sleep=time.sleep):
        require(0 < nonce < 1 << 64 and 2 < blocks <= 1 << 32, 'nonce/capacity out of range')
        self.device, self.nonce, self.total_blocks = device, nonce, blocks
        self.clock, self.sleep, self.identity = clock, sleep, None
        self.last_receipts = []

    def info(self):
        h, payload = packet(bytes(self.transfer(0xc0, INFO, 0x5242, 1, HEADER.size)))
        require(not payload and h['offset'] == 0, 'INFO carried data')
        require(h['nonce'] == self.nonce, 'wrong image boot nonce')
        identity = (h['nonce'], h['entry'], h['lun'])
        # LUN is not bound until the UFS owner attaches. Bind host identity only afterwards.
        if h['state'] != UNAVAILABLE:
            if self.identity is None:
                self.identity = identity
            require(identity == self.identity, 'device rebooted or changed LUN')
        elif self.identity is not None:
            raise Refused('readback became unavailable during capture')
        return h

    def transfer(self, typ, req, value, index, length):
        try:
            return self.device.ctrl_transfer(typ, req, value, index, length, timeout=2000)
        except Refused:
            raise
        except Exception as exc:
            raise Refused('USB control transfer failed; capture is incomplete (no reconnect or SELECT retry)') from exc

    def wait_idle(self):
        end = self.clock() + 20
        while True:
            h = self.info()
            if h['state'] not in (UNAVAILABLE, QUEUED, LOADING):
                return h
            require(self.clock() < end, 'readback did not become ready')
            self.sleep(0.02)

    def read(self, lba, count=1):
        require(isinstance(lba, int) and isinstance(count, int) and lba >= 0 and count > 0 and
                count <= 256 and lba + count <= self.total_blocks, 'read outside supplied media capacity/batch bound')
        self.last_receipts = []
        return b''.join(self.read_block(n) for n in range(lba, lba + count))

    def read_block(self, lba):
        require(type(lba) is int and 0 <= lba < self.total_blocks, 'block outside supplied media capacity')
        before = self.wait_idle()
        require(before['state'] != FAILED, 'previous device read failed; stop capture')
        require(before['generation'] < (1 << 64) - 1, 'generation exhausted')
        generation = before['generation'] + 1
        self.transfer(0x40, SELECT, lba & 0xffff, lba >> 16, b'')
        end = self.clock() + 20
        while True:
            h = self.info()
            require((h['generation'], h['lba']) == (generation, lba), 'SELECT lost or another reader intervened')
            require(h['state'] != FAILED, f'exact device read failed at LBA {lba}')
            if h['state'] == COMPLETE:
                break
            require(h['state'] in (QUEUED, LOADING) and self.clock() < end, 'readback completion timeout')
            self.sleep(0.01)
        data = bytearray()
        binding = tuple(h[k] for k in ('nonce', 'entry', 'lun', 'generation', 'lba', 'crc'))
        while len(data) < BLOCK:
            p, part = packet(bytes(self.transfer(0xc0, DATA, len(data), 0, 384)))
            require(p['state'] == COMPLETE and p['offset'] == len(data) and part, 'invalid data chunk')
            require(tuple(p[k] for k in ('nonce', 'entry', 'lun', 'generation', 'lba', 'crc')) == binding,
                    'stale or interleaved block data')
            data += part
        require(len(data) == BLOCK and zlib.crc32(data) == h['crc'], 'block CRC mismatch')
        after = self.info()
        require(after['state'] == COMPLETE and
                tuple(after[k] for k in ('nonce', 'entry', 'lun', 'generation', 'lba', 'crc')) == binding,
                'block changed before capture finished')
        self.last_receipts.append({k: after[k] for k in ('nonce', 'entry', 'lun', 'generation', 'lba', 'crc')})
        return bytes(data)


class ImageReader:
    def __init__(self, path):
        self.file = regular_open(path)
        size = os.fstat(self.file.fileno()).st_size
        if size % BLOCK != 0 or size <= 2 * BLOCK:
            self.file.close()
            raise Refused('image size is not whole 4 KiB blocks')
        self.total_blocks = size // BLOCK

    def read(self, lba, count=1):
        require(lba >= 0 and count > 0 and lba + count <= self.total_blocks, 'image read out of range')
        data = os.pread(self.file.fileno(), count * BLOCK, lba * BLOCK)
        require(len(data) == count * BLOCK, 'short image read')
        return data

    def close(self):
        self.file.close()


def parse_header(data, at, blocks):
    require(len(data) == BLOCK, 'GPT header block is short')
    (signature, revision, size, crc, reserved, current, alternate, first, last,
     disk, array_lba, count, entry_size, array_crc) = GPT.unpack_from(data)
    require(signature == b'EFI PART' and revision == 0x10000, 'invalid GPT signature/revision')
    require(GPT.size <= size <= BLOCK and reserved == 0, 'invalid GPT header shape')
    check = bytearray(data[:size]); check[16:20] = b'\0' * 4
    require(zlib.crc32(check) == crc, 'GPT header CRC mismatch')
    require(not any(data[size:]), 'nonzero GPT reserved block padding')
    require(current == at and alternate == (blocks - 1 if at == 1 else 1), 'GPT reciprocal header geometry')
    # UEFI requires at least 16 KiB reserved for each entry array, even when
    # NumberOfPartitionEntries describes fewer bytes (as on this Pixel).
    require(6 <= first <= last <= blocks - 6 and disk != b'\0' * 16, 'invalid GPT usable interval/GUID')
    require(0 < count <= 4096 and 128 <= entry_size <= 4096 and
            entry_size % 128 == 0 and (entry_size // 128) & (entry_size // 128 - 1) == 0,
            'unsupported GPT entry shape')
    byte_count = count * entry_size
    require(byte_count <= 1024 * 1024, 'GPT entry array exceeds 1 MiB bound')
    array_blocks = (byte_count + BLOCK - 1) // BLOCK
    if at == 1:
        require(2 <= array_lba and array_lba + array_blocks <= first, 'primary GPT array overlaps usable blocks')
    else:
        require(last < array_lba and array_lba + array_blocks <= at, 'backup GPT array overlaps usable/header blocks')
    return dict(current=current, alternate=alternate, first=first, last=last,
                disk_guid=str(uuid.UUID(bytes_le=disk)), array_lba=array_lba,
                count=count, entry_size=entry_size, array_crc=array_crc,
                byte_count=byte_count, array_blocks=array_blocks)


def parse_entries(data, h):
    require(len(data) == h['array_blocks'] * BLOCK, 'short GPT array')
    array = data[:h['byte_count']]
    require(zlib.crc32(array) == h['array_crc'], 'GPT array CRC mismatch')
    parts, names, ids = [], set(), set()
    for i in range(h['count']):
        e = array[i * h['entry_size']:(i + 1) * h['entry_size']]
        if e[:16] == b'\0' * 16:
            require(not any(e), 'unused GPT entry has nonzero fields')
            continue
        first, last, attrs = struct.unpack_from('<QQQ', e, 32)
        require(h['first'] <= first <= last <= h['last'], 'partition outside usable GPT interval')
        ident = str(uuid.UUID(bytes_le=e[16:32]))
        require(e[16:32] != b'\0' * 16 and ident not in ids, 'zero or duplicate partition GUID')
        ids.add(ident)
        try:
            text = e[56:128].decode('utf-16-le')
        except UnicodeDecodeError as exc:
            raise Refused('invalid UTF-16 GPT name') from exc
        name, _, tail = text.partition('\0')
        require(not tail.strip('\0'), 'nonzero data after GPT name terminator')
        require(not name or name not in names, 'duplicate GPT partition name')
        names.add(name)
        parts.append(dict(index=i, name=name, first_lba=first, last_lba=last,
                          bytes=(last-first+1)*BLOCK, type_guid=str(uuid.UUID(bytes_le=e[:16])),
                          unique_guid=ident, attributes=attrs))
    ordered = sorted(parts, key=lambda p: p['first_lba'])
    for a, b in zip(ordered, ordered[1:]):
        require(a['last_lba'] < b['first_lba'], 'overlapping GPT partitions')
    return parts


def inspect_pmbr(mbr, blocks, reviewed_sha256=None):
    require(len(mbr) == BLOCK, 'short protective MBR block')
    require(mbr[510:512] == b'\x55\xaa', 'protective MBR signature missing')
    entries = [mbr[446+i*16:462+i*16] for i in range(4)]
    protective = [e for e in entries if e[4] == 0xee]
    require(len(protective) == 1 and all(e[4] in (0, 0xee) for e in entries), 'missing or hybrid protective MBR')
    require(all(not any(e) for e in entries if e[4] == 0), 'nonzero unused protective MBR record')
    start, sectors = struct.unpack_from('<II', protective[0], 8)
    expected = min(blocks-1, 0xffffffff)
    canonical = sectors == expected
    if reviewed_sha256 is not None:
        require(re.fullmatch('[0-9a-f]{64}', reviewed_sha256) is not None and sha(mbr) == reviewed_sha256,
                'protective MBR does not match the separately reviewed block hash')
    # Linux v6.12 block/partitions/efi.c:is_pmbr_valid explicitly recognizes
    # 0xffffffff regardless of disk size. Accept that observed vendor form only
    # with an operator-supplied, separately reviewed block hash. This neither
    # supplies media capacity nor relaxes any GPT copy/CRC/range requirement.
    saturated = not canonical and sectors == 0xffffffff and reviewed_sha256 is not None
    require(start == 1 and (canonical or saturated), 'protective MBR geometry mismatch')
    return dict(start_lba=start, size_in_lba=sectors, canonical_size_in_lba=expected,
                policy='uefi-size' if canonical else 'reviewed-linux-saturated',
                reviewed_sha256=reviewed_sha256)


def inspect_gpt(reader, reviewed_pmbr_sha256=None):
    mbr = reader.read(0)
    pmbr = inspect_pmbr(mbr, reader.total_blocks, reviewed_pmbr_sha256)
    raw_p, raw_b = reader.read(1), reader.read(reader.total_blocks-1)
    p = parse_header(raw_p, 1, reader.total_blocks)
    b = parse_header(raw_b, reader.total_blocks-1, reader.total_blocks)
    common = ('first', 'last', 'disk_guid', 'count', 'entry_size', 'array_crc', 'byte_count')
    require(all(p[k] == b[k] for k in common), 'GPT copies disagree')
    primary_array = reader.read(p['array_lba'], p['array_blocks'])
    backup_array = reader.read(b['array_lba'], b['array_blocks'])
    parts = parse_entries(primary_array, p)
    parse_entries(backup_array, b)
    require(primary_array[:p['byte_count']] == backup_array[:b['byte_count']], 'GPT entry copies differ')
    segments = [('protective-mbr.raw', 0, mbr), ('primary-header.raw', 1, raw_p),
                ('primary-entries.raw', p['array_lba'], primary_array),
                ('backup-entries.raw', b['array_lba'], backup_array),
                ('backup-header.raw', reader.total_blocks-1, raw_b)]
    return dict(block_bytes=BLOCK, total_blocks=reader.total_blocks,
                disk_guid=p['disk_guid'], partitions=parts,
                protective_mbr=pmbr,
                gpt_copies_match=True, storage_isolation_proven=False,
                android_integrity_proven=False, full_data_backup=False), segments


def fstab_owners(data):
    """Parse explicit /data device relationships; a missing relationship proves no ownership."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise Refused('fstab is not UTF-8') from exc
    owners = []
    for line in text.splitlines():
        fields = line.split('#', 1)[0].split()
        if len(fields) < 5 or fields[1] != '/data':
            continue
        devices = [dict(role='primary', name=fields[0].rsplit('/', 1)[-1])]
        for option in fields[4].split(','):
            if option.startswith('device='):
                role, sep, path = option[7:].partition(':')
                require(sep and path.startswith('/dev/block/'), 'unrecognized fstab auxiliary device')
                devices.append(dict(role=role, name=path.rsplit('/', 1)[-1]))
        owners.append(dict(mount='/data', filesystem=fields[2], devices=devices))
    require(owners, 'no /data relationship found; ownership remains unknown')
    return dict(sha256=sha(data), data_mounts=owners, live_alias_state='unknown')


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())


class RecordingReader:
    """Save each received block before parsing it, without any retry/extra read."""
    def __init__(self, reader, out):
        self.reader, self.out = reader, Path(out)
        self.total_blocks, self.observations = reader.total_blocks, []

    def read(self, lba, count=1):
        require(type(lba) is int and type(count) is int and lba >= 0 and 0 < count <= 256 and
                lba+count <= self.total_blocks, 'capture read range/batch bound')
        data = bytearray()
        for block in range(lba, lba+count):
            require(len(self.observations) < 1100, 'GPT evidence read budget exceeded')
            part = self.reader.read(block, 1)
            require(len(part) == BLOCK, 'short captured block')
            name = f'read-{len(self.observations):04d}-lba-{block:010d}.raw'
            write_new(self.out/name, part)
            observation = dict(file=name, lba=block, blocks=1, sha256=sha(part))
            if isinstance(self.reader, UsbReader):
                observation['wire_receipt'] = self.reader.last_receipts[-1]
            self.observations.append(observation)
            data += part
        return bytes(data)


def capture_gpt(reader, out, fstab=None, reviewed_pmbr_sha256=None):
    out = Path(out)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    recording = RecordingReader(reader, out)
    identity = lambda: dict(zip(('nonce', 'entry', 'lun'), reader.identity)) if isinstance(reader, UsbReader) and reader.identity else None
    try:
        report, segments = inspect_gpt(recording, reviewed_pmbr_sha256)
        # Re-read every metadata block: refuse a table changing during capture.
        for _, lba, data in segments:
            require(recording.read(lba, len(data)//BLOCK) == data, 'GPT changed during capture')
        if fstab is not None:
            report['android_fstab'] = fstab_owners(fstab)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        failure = dict(schema=1, ok=False, purpose='failed/incomplete GPT capture evidence only',
                       error=str(exc), observations=recording.observations, boot_identity=identity(),
                       block_bytes=BLOCK, total_blocks=reader.total_blocks,
                       gpt_copies_match=False, full_data_backup=False, storage_isolation_proven=False,
                       android_integrity_proven=False)
        write_new(out/'failure.json', (json.dumps(failure, indent=2)+'\n').encode())
        raise
    report['purpose'] = 'GPT metadata only; not a partition/data backup or migration approval'
    report['schema'] = 1
    report['segments'] = []
    report['observations'] = recording.observations
    if isinstance(reader, UsbReader):
        report['boot_identity'] = dict(zip(('nonce', 'entry', 'lun'), reader.identity))
    for name, lba, data in segments:
        write_new(out/name, data)
        report['segments'].append(dict(file=name, lba=lba, blocks=len(data)//BLOCK, sha256=sha(data)))
    write_new(out/'capture.json', (json.dumps(report, indent=2)+'\n').encode())
    return report


class SnapshotReader:
    def __init__(self, directory):
        directory = Path(directory)
        self.manifest = json.loads(small_file(directory/'capture.json', 2*1024*1024))
        require(self.manifest.get('schema') == 1 and self.manifest.get('block_bytes') == BLOCK,
                'unsupported snapshot schema')
        self.total_blocks = self.manifest['total_blocks']
        require(type(self.total_blocks) is int and 2 < self.total_blocks <= 1 << 32, 'snapshot capacity')
        self.segments = []
        segments = self.manifest['segments']
        require(len(segments) == 5, 'expected five GPT metadata segments')
        names = set()
        for s in segments:
            name, lba, count = s['file'], s['lba'], s['blocks']
            require(isinstance(name, str) and Path(name).name == name and name not in names and
                    name not in ('', '.', '..'), 'unsafe/duplicate snapshot filename')
            names.add(name)
            require(type(lba) is int and type(count) is int and lba >= 0 and count > 0 and
                    lba+count <= self.total_blocks, 'snapshot range')
            data = small_file(directory/name, 1024*1024)
            require(len(data) == count*BLOCK and sha(data) == s['sha256'], 'snapshot length/hash mismatch')
            self.segments.append((lba, lba+count, data))
        ordered = sorted(self.segments)
        require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), 'overlapping snapshot segments')
        observations = self.manifest.get('observations', [])
        require(isinstance(observations, list) and len(observations) <= 1100, 'snapshot observation bound')
        for observation in observations:
            name, lba = observation['file'], observation['lba']
            require(isinstance(name, str) and Path(name).name == name and name not in names and
                    name not in ('', '.', '..') and type(lba) is int and observation['blocks'] == 1,
                    'unsafe/duplicate observation file or range')
            names.add(name)
            data = small_file(directory/name, BLOCK)
            require(len(data) == BLOCK and sha(data) == observation['sha256'] and self.read(lba) == data,
                    'snapshot observation differs from validated metadata')

    def read(self, lba, count=1):
        for first, end, data in self.segments:
            if first <= lba and lba + count <= end:
                return data[(lba-first)*BLOCK:(lba+count-first)*BLOCK]
        raise Refused('missing snapshot blocks; never synthesize zeros')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    image = sub.add_parser('inspect-image'); image.add_argument('image')
    snap = sub.add_parser('inspect-snapshot'); snap.add_argument('directory')
    capture = sub.add_parser('capture-gpt')
    capture.add_argument('--nonce', type=lambda s: int(s, 0), required=True)
    capture.add_argument('--blocks', type=lambda s: int(s, 0), required=True,
                         help='independently observed READ CAPACITY block count, not a guessed disk size')
    capture.add_argument('--output', required=True)
    capture.add_argument('--fstab')
    for command in (image, snap, capture):
        command.add_argument('--reviewed-pmbr-sha256', help='explicitly accept reviewed saturated 0xffffffff PMBR only when this whole-block hash matches')
    capture.add_argument('--wait', type=float, default=60,
                         help='seconds to wait for the USB console to appear (0..300, default 60)')
    a = p.parse_args(argv)
    if a.command == 'inspect-image':
        reader = ImageReader(a.image)
        try:
            report, _ = inspect_gpt(reader, a.reviewed_pmbr_sha256)
        finally:
            reader.close()
    elif a.command == 'inspect-snapshot':
        reader = SnapshotReader(a.directory)
        report, _ = inspect_gpt(reader, a.reviewed_pmbr_sha256)
        # Recompute layout from raw bytes; never trust cached manifest partitions.
        report['stored_layout_matches'] = report['partitions'] == reader.manifest['partitions']
        require(report['stored_layout_matches'], 'stored layout differs from captured GPT bytes')
    else:
        import usb.core
        import usb.util
        require(0 <= a.wait <= 300, '--wait must be between 0 and 300 seconds')
        require(not Path(a.output).exists(), 'output directory already exists')
        end = time.monotonic() + a.wait
        while True:
            devices = list(usb.core.find(find_all=True, idVendor=0x1209, idProduct=0x0002))
            if devices or time.monotonic() >= end:
                break
            time.sleep(0.2)
        require(len(devices) == 1, 'need exactly one hackios XNU console device')
        dev = devices[0]
        try:
            require(usb.util.get_string(dev, dev.iProduct) == 'hackios XNU console', 'USB product mismatch')
            reader = UsbReader(dev, a.nonce, a.blocks)
            report = capture_gpt(reader, a.output, small_file(a.fstab, 1024*1024) if a.fstab else None,
                                 a.reviewed_pmbr_sha256)
        finally:
            usb.util.dispose_resources(dev)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'dualboot: refused: {exc}', file=sys.stderr)
        sys.exit(2)
