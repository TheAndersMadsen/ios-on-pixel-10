#!/usr/bin/env python3
"""The kernel's own loop, compiled on the host against a file, then fullcheck.py compares. Includes mutants of the loop."""
import os, shutil, subprocess, sys, tempfile, unittest, zlib
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; sys.path.insert(0, str(X))
import fullcheck as F
INC = (X/'fullcheck/hakios.blazer_fullcheck.inc').read_text()
BLOCKS = 16384 * 3 + 777   # 3 spans and a short one
MUTANTS = {
 'skips last chunk': ('lba < nblocks;', 'lba + 16 < nblocks;'),
 'offsets by one block': ('FC_READ(first_block + lba,', 'FC_READ(first_block + lba + 1,'),
 'reads partition-relative': ('FC_READ(first_block + lba,', 'FC_READ(lba,'),
 'ignores read errors': ('if (error != 0) {', 'if (0) {'),
 'hashes one block per chunk': ('i < count * UFS_FC_BLOCK', 'i < UFS_FC_BLOCK'),
 'whole crc misses a byte': ('whole = (whole >> 8) ^ ufs_fc_table[(whole ^ d[i]) & 0xff];', 'if (i) whole = (whole >> 8) ^ ufs_fc_table[(whole ^ d[i]) & 0xff];'),
 'span crc misses a byte': ('span = (span >> 8) ^ ufs_fc_table[(span ^ d[i]) & 0xff];', 'if (i) span = (span >> 8) ^ ufs_fc_table[(span ^ d[i]) & 0xff];'),
 'span not reset': ('span = 0xffffffffu;\n\t\t\tspan_blocks = 0;', 'span_blocks = 0;'),
 'last short span dropped': ('span_blocks == UFS_FC_SPAN_BLOCKS || lba == nblocks', 'span_blocks == UFS_FC_SPAN_BLOCKS'),
 'wrong polynomial': ('0xedb88320u', '0x04c11db7u'),
 'crc not inverted in span': ('span_blocks, ~span);', 'span_blocks, span);'),
 'crc not inverted in whole': ('~whole, (unsigned', 'whole, (unsigned'),
 'span too long': ('#define UFS_FC_SPAN_BLOCKS 16384u', '#define UFS_FC_SPAN_BLOCKS 32768u'),
 'done line absent': ('"blazer-ufs-fullcheck: done,', '"blazer-ufs-fullcheck: finished,'),
}
def build_mask(d, inc=INC):
    (d/'hakios.blazer_fullcheck.inc').write_text(inc); shutil.copy(X/'fullcheck/host_fake_mask.c', d/'host_fake_mask.c')
    exe = d/'fake_mask'
    subprocess.run(['/usr/bin/cc', '-w', '-O2', '-o', str(exe), str(d/'host_fake_mask.c')], check=True)
    return exe
MASK_MUTANTS = {
 'masked blocks are hashed': ('if (!fc_skip) {', 'if (1) {'),
 'masked blocks not counted': ('		lba += count;\n		span_blocks += count;', '		lba += count;\n		span_blocks += fc_skip ? 0 : count;'),
 'run ignored': ('count = FC_MASK_RUN(lba, count, &fc_skip);', '(void)FC_MASK_RUN(lba, count, &fc_skip);'),
 'no mask line': ('	FC_MASK_LINE();\n', ''),
}
def make_image(path):
    with open(path, 'wb') as f:
        for n in range(BLOCKS):
            # A long zero stretch stands in for a FILL region; the rest differs per block.
            f.write(bytes(4096) if 20000 <= n < 30000 else n.to_bytes(8, 'little') * 512)
def build(d, inc=INC):
    (d/'hakios.blazer_fullcheck.inc').write_text(inc); shutil.copy(X/'fullcheck/host_fake.c', d/'host_fake.c')
    exe = d/'fake'
    subprocess.run(['/usr/bin/cc', '-w', '-O2', '-o', str(exe), str(d/'host_fake.c')], check=True)
    return exe
class FullCheck(unittest.TestCase):
    @classmethod
    def setUpClass(c):
        c.d = Path(tempfile.mkdtemp()); c.img = c.d/'img'; make_image(c.img); c.want = F.compute(c.img); c.exe = build(c.d)
    @classmethod
    def tearDownClass(c): shutil.rmtree(c.d)
    def run_on(self, img, *extra, exe=None):
        return subprocess.run([str(exe or self.exe), str(img), *extra], capture_output=True, text=True)
    def flipped(self, block, byte=100, bit=1):
        d = bytearray(self.img.read_bytes()); d[block * 4096 + byte] ^= bit; p = self.d/f'flip{block}'; p.write_bytes(d); return p
    def test_equal_passes(self):
        r = F.compare(self.run_on(self.img).stdout, self.want); self.assertTrue(r['ok'], r); self.assertEqual(r['spans'], 4)
    def test_crlf_as_on_the_phone(self):
        # 20261101-230701-fullcheck-r3-before: the mirror has \\r\\n after printf's \\n. The first tool said 0 spans.
        t = self.run_on(self.img).stdout.replace('\n', '\r\n'); r = F.compare(t, self.want); self.assertTrue(r['ok'], r); self.assertEqual(r['spans'], 4)
    def test_python_table_agrees_with_c(self):
        self.assertIn(f"whole crc {self.want['whole']:08x}", self.run_on(self.img).stdout)
    def test_bit_in_last_block(self):
        r = F.compare(self.run_on(self.flipped(BLOCKS - 1)).stdout, self.want)
        self.assertFalse(r['ok']); self.assertEqual(r['differ'], [3]); self.assertTrue(any('whole crc' in p for p in r['problems']))
    def test_bit_in_fill_region(self):
        r = F.compare(self.run_on(self.flipped(25000)).stdout, self.want)
        self.assertFalse(r['ok']); self.assertEqual(r['differ'], [1]); self.assertIn('blocks 16384..32767', r['problems'][0])
    def test_read_error_stops_and_names_lba(self):
        p = self.run_on(self.img, '40000'); self.assertEqual(p.returncode, 1)
        r = F.compare(p.stdout, self.want); self.assertFalse(r['ok']); self.assertIn('read error at partition block 40000', r['problems'][0])
        self.assertNotIn('done,', p.stdout); self.assertNotIn('span 3', p.stdout)
    def test_partial_log_fails(self):
        lines = self.run_on(self.img).stdout.splitlines()
        for drop in (lines[-1], lines[2]):
            self.assertFalse(F.compare('\n'.join(l for l in lines if l != drop) + '\n', self.want)['ok'])
        self.assertFalse(F.compare('', self.want)['ok'])
    def test_other_image_fails(self):
        o = F.compute(self.flipped(0)); self.assertFalse(F.compare(self.run_on(self.img).stdout, o)['ok'])
    def test_only_reads(self):
        for word in ('write', 'WRITE', 'bwrite', 'erase', 'unmap'): self.assertNotIn(word, INC)
    def test_mutants(self):
        for name, (a, b) in MUTANTS.items():
            with self.subTest(name):
                self.assertIn(a, INC); d = Path(tempfile.mkdtemp())
                try:
                    p = self.run_on(self.img, exe=build(d, INC.replace(a, b)))
                    caught = not F.compare(p.stdout, self.want)['ok']
                    if name == 'ignores read errors':
                        p = self.run_on(self.img, '40000', exe=build(d, INC.replace(a, b)))
                        caught = 'stopping' not in p.stdout and not F.compare(p.stdout, self.want)['ok']
                    self.assertTrue(caught, name)
                finally: shutil.rmtree(d)
class Masked(unittest.TestCase):
    """blazer_ufs_fullcheck=2: table blocks neither read nor hashed; every other block still compared."""
    EXT = [[16000, 400], [32760, 16], [40000, 3], [49500, 100]]   # across a span's end, across another, a short one, in the short last span
    @classmethod
    def setUpClass(c):
        c.d = Path(tempfile.mkdtemp()); c.img = c.d/'img'; make_image(c.img); c.exe = build_mask(c.d)
        c.mask = dict(extents=c.EXT, blocks=sum(n for _, n in c.EXT), table_crc=0xdf77bc20); c.want = F.compute(c.img, mask=c.mask); c.plain = F.compute(c.img)
    @classmethod
    def tearDownClass(c): shutil.rmtree(c.d)
    def run_on(self, img, err=-1, exe=None):
        return subprocess.run([str(exe or self.exe), str(img), str(err)] + [f'{a}:{n}' for a, n in self.EXT], capture_output=True, text=True)
    def flipped(self, block):
        d = bytearray(self.img.read_bytes()); d[block * 4096 + 100] ^= 1; p = self.d/f'flip{block}'; p.write_bytes(d); return p
    def test_equal_passes(self):
        p = self.run_on(self.img); r = F.compare(p.stdout, self.want); self.assertTrue(r['ok'], r); self.assertEqual(r['spans'], 4)
    def test_crlf(self):
        r = F.compare(self.run_on(self.img).stdout.replace('\n', '\r\n'), self.want); self.assertTrue(r['ok'], r)
    def test_table_block_changed_passes(self):
        for b in (16000, 16399, 32775, 40001, 49599):
            r = F.compare(self.run_on(self.flipped(b)).stdout, self.want); self.assertTrue(r['ok'], (b, r))
    def test_any_other_block_changed_fails(self):
        for b, span in ((15999, 0), (16400, 1), (32759, 1), (32776, 2), (39999, 2), (40003, 2), (49499, 3), (49600, 3)):
            r = F.compare(self.run_on(self.flipped(b)).stdout, self.want); self.assertFalse(r['ok'], b); self.assertEqual(r['differ'], [span], b)
    def test_table_blocks_not_read(self):
        p = self.run_on(self.img, 16010); self.assertTrue(F.compare(p.stdout, self.want)['ok'])  # the fake exits 4 on any read of one, and an error there never fires
    def test_read_error_elsewhere(self):
        p = self.run_on(self.img, 17000); self.assertEqual(p.returncode, 1); self.assertFalse(F.compare(p.stdout, self.want)['ok'])
    def test_mask_must_match_both_ways(self):
        masked = self.run_on(self.img).stdout; plain = subprocess.run([str(build(self.d)), str(self.img)], capture_output=True, text=True).stdout
        self.assertFalse(F.compare(masked, self.plain)['ok']); self.assertFalse(F.compare(plain, self.want)['ok'])
        self.assertFalse(F.compare(masked.replace('table crc df77bc20', 'table crc 00000000'), self.want)['ok'])
        self.assertFalse(F.compare(masked.replace('masked 519 blocks', 'masked 518 blocks'), self.want)['ok'])
    def test_mask_absent_from_log_fails(self):
        lines = [l for l in self.run_on(self.img).stdout.splitlines() if 'masked' not in l]; self.assertFalse(F.compare('\n'.join(lines) + '\n', self.want)['ok'])
    def test_overlay_is_the_image_with_that_block(self):
        pat = F.pattern(32000, 0); d = bytearray(self.img.read_bytes()); d[32000 * 4096:32001 * 4096] = pat; p = self.d/'over'; p.write_bytes(d)
        fake = build(self.d); log = subprocess.run([str(fake), str(p)], capture_output=True, text=True).stdout
        want = F.compute(self.img, overlay={32000: pat}); self.assertEqual(want, dict(F.compute(p), overlay=[32000]))
        self.assertTrue(F.compare(log, want)['ok']); r = F.compare(log, self.plain); self.assertFalse(r['ok']); self.assertEqual(r['differ'], [1])
        pat2 = F.pattern(32000, 1); self.assertNotEqual(pat, pat2); self.assertFalse(F.compare(log, F.compute(self.img, overlay={32000: pat2}))['ok'])
    def test_pattern_matches_the_kernel(self):
        self.assertEqual(zlib.crc32(F.pattern(1440939, 0)), 0x37239e23); self.assertEqual(zlib.crc32(F.pattern(1440939, 1)), 0x016bf938)
    def test_mutants(self):
        for name, (a, b) in MASK_MUTANTS.items():
            with self.subTest(name):
                self.assertIn(a, INC); d = Path(tempfile.mkdtemp())
                try:
                    p = self.run_on(self.img, exe=build_mask(d, INC.replace(a, b)))
                    self.assertTrue(p.returncode != 0 or not F.compare(p.stdout, self.want)['ok'], name)
                finally: shutil.rmtree(d)
if __name__ == '__main__': unittest.main()
