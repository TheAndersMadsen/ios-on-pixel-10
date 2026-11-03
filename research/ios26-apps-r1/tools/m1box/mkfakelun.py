#!/usr/bin/env python3
"""Build a QEMU fake whole-LUN medium (4096-byte logical blocks, like the phone's UFS LUN 0) for blazer_ufs_fake_lun=1.

    mkfakelun.py ROOT.img OUT.img [--data-blocks 16384]

Layout (LBA = 4096 bytes): 0 protective MBR, 1 primary GPT header, 2..5 entry array (128 x 128 B), then
  userdata  (Android data type)  LBA 6 .. 261          (only so ios_data can start above userdata's last LBA, as on the phone)
  ios_system (hackios type)      2 MiB aligned, exactly the root image's blocks; the root is copied in (sparse-aware)
  ios_data   (hackios type)      next 2 MiB boundary, --data-blocks blocks (>= 4101), zero-filled
and the backup entry array + header at the end. Header and array CRCs are valid in both copies. Writes OUT.img and
OUT.img.layout.json (every extent in LBAs and bytes). The fake medium has no other contents. Host only.
"""
import argparse, json, os, struct, sys, uuid, zlib
from pathlib import Path

B = 4096
HACKIOS = uuid.UUID('364eb72d-8d24-5ee6-9658-db13e5e7b10a')      # tools/gpt_plan.py IOS_TYPE
ANDROID_DATA = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4')  # Linux data; userdata's type is not checked
DISK = uuid.UUID('54494857-4345-4148-5045-4c204c554e31')


def entry(t, u, first, last, name):
    n = name.encode('utf-16-le').ljust(72, b'\0')
    return t.bytes_le + u.bytes_le + struct.pack('<QQQ', first, last, 0) + n


def header(my, alt, first_use, last_use, entries_lba, array_crc):
    h = bytearray(struct.pack('<8sIIIIQQQQ16sQIII', b'EFI PART', 0x00010000, 92, 0, 0, my, alt, first_use, last_use,
                              DISK.bytes_le, entries_lba, 128, 128, array_crc))
    struct.pack_into('<I', h, 16, zlib.crc32(bytes(h)) & 0xffffffff)
    return bytes(h).ljust(B, b'\0')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('root'); ap.add_argument('out'); ap.add_argument('--data-blocks', type=int, default=16384)
    a = ap.parse_args()
    root = Path(a.root); out = Path(a.out)
    assert not out.exists(), 'refusing to overwrite'
    rsize = root.stat().st_size; assert rsize % B == 0
    rblocks = rsize // B
    align = (2 << 20) // B
    ud = (6, 261)
    sys_first = align; sys_last = sys_first + rblocks - 1
    data_first = ((sys_last + 1 + align - 1) // align) * align; data_last = data_first + a.data_blocks - 1
    assert a.data_blocks >= 4101
    total = ((data_last + 1 + 5 + align - 1) // align) * align          # 2 MiB multiple for the harness
    last_use = total - 6
    ents = [entry(ANDROID_DATA, uuid.uuid5(DISK, 'userdata'), *ud, 'userdata'),
            entry(HACKIOS, uuid.uuid5(DISK, 'ios_system'), sys_first, sys_last, 'ios_system'),
            entry(HACKIOS, uuid.uuid5(DISK, 'ios_data'), data_first, data_last, 'ios_data')]
    arr = b''.join(ents).ljust(128 * 128, b'\0'); acrc = zlib.crc32(arr) & 0xffffffff
    mbr = bytearray(512); mbr[446:462] = struct.pack('<BBBBBBBBII', 0, 0, 2, 0, 0xee, 0xff, 0xff, 0xff, 1, min(total - 1, 0xffffffff)); mbr[510:512] = b'\x55\xaa'
    with out.open('wb') as f:
        f.truncate(total * B)
        f.seek(0); f.write(bytes(mbr).ljust(B, b'\0'))
        f.write(header(1, total - 1, 6, last_use, 2, acrc)); f.write(arr)
        f.seek((total - 5) * B); f.write(arr); f.write(header(total - 1, 1, 6, last_use, total - 5, acrc))
        with root.open('rb') as r:                                   # sparse-aware copy: skip zero chunks
            f.seek(sys_first * B); chunk = 8 << 20; done = 0
            while True:
                b = r.read(chunk)
                if not b: break
                if b.count(0) != len(b): f.seek(sys_first * B + done); f.write(b)
                done += len(b)
    lay = dict(block=B, total_blocks=total, userdata=ud, ios_system=[sys_first, sys_last], ios_data=[data_first, data_last],
               primary=[0, 5], backup=[total - 5, total - 1], root=str(root), root_bytes=rsize, out=str(out))
    Path(str(out) + '.layout.json').write_text(json.dumps(lay, indent=1) + '\n'); print(json.dumps(lay, indent=1))


if __name__ == '__main__':
    main()
