#!/usr/bin/env python3
"""Grow an unjournaled HFS+/HFSX image in place to NEW_BLOCKS allocation blocks (no hdiutil on Linux).

  hfs_grow.py IMAGE NEW_BLOCKS

Only what a grow needs, nothing moves: the file is extended (sparse zeros); the allocation file (bitmap) keeps its
first extent where it is and gains a second extent at the first new block, sized to cover NEW_BLOCKS; the old last
block (the old alternate volume header's block) is freed; the new extent and the new last block are marked used;
totalBlocks, freeBlocks and the allocation fork are updated; the primary header is rewritten and the alternate header
is written at NEW_BLOCKS*bsize-1024; the stale old alternate header is zeroed. Refuses anything it does not expect."""
import os, struct, sys
img, N = sys.argv[1], int(sys.argv[2])
f = open(img, 'r+b')
f.seek(1024); vh = bytearray(f.read(512))
assert vh[:2] in (b'H+', b'HX'), vh[:2]
attr = struct.unpack_from('>I', vh, 4)[0]
assert not attr & (1 << 13), 'journaled'
assert attr & (1 << 8), 'volume not cleanly unmounted'
bs, T, free = struct.unpack_from('>III', vh, 40)
assert bs == 4096 and N > T, (bs, T, N)
assert os.path.getsize(img) == T * bs, 'image size != volume size'
lg, clump, ab = struct.unpack_from('>QII', vh, 112)
ext = [struct.unpack_from('>II', vh, 128 + 8 * i) for i in range(8)]
assert ext[0][1] == ab and all(e == (0, 0) for e in ext[1:]), ext
need = -(-(-(-N // 8)) // bs)                     # bitmap blocks for N bits
add = need - ab
assert add > 0 and lg == ab * bs
bm_old_start = ext[0][0]
# bitmap of the old volume
f.seek(bm_old_start * bs); bm = bytearray(f.read(ab * bs)) + bytearray(add * bs)
def get(n): return (bm[n >> 3] >> (7 - (n & 7))) & 1
def put(n, v):
    if v: bm[n >> 3] |= 0x80 >> (n & 7)
    else: bm[n >> 3] &= ~(0x80 >> (n & 7)) & 0xff
used_before = sum(bin(b).count('1') for b in bm[:(T + 7) // 8])
assert used_before == T - free, (used_before, T, free)
assert get(T - 1) == 1 and all(not get(n) for n in range(T, T + 8))
put(T - 1, 0)                                      # old alternate header block
for n in range(T, T + add): put(n, 1)              # new bitmap extent
put(N - 1, 1)                                      # new alternate header block
newfree = N - sum(bin(b).count('1') for b in bm[:(N + 7) // 8])
assert newfree == free + (N - T) - add, (newfree, free, N, T, add)
f.truncate(N * bs)
f.seek(T * bs - 1024); f.write(bytes(512))       # stale old alternate header
f.seek(bm_old_start * bs); f.write(bm[:ab * bs])
f.seek(T * bs); f.write(bm[ab * bs:])
struct.pack_into('>II', vh, 44, N, newfree)
struct.pack_into('>QII', vh, 112, need * bs, clump, need)
struct.pack_into('>II', vh, 128 + 8, T, add)
f.seek(1024); f.write(vh)
f.seek(N * bs - 1024); f.write(vh)
f.flush(); os.fsync(f.fileno())
print(f'grown {T} -> {N} blocks of {bs}; bitmap {ab} -> {need} blocks (+{add} at {T}); free {free} -> {newfree}')
