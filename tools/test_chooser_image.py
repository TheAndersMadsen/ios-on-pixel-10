#!/usr/bin/env python3
"""Host tests for tools/chooser_image.py switch gating (no device, no build, no stock image needed).

  python3 -I tools/test_chooser_image.py"""
import argparse, subprocess, sys, unittest, uuid
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; sys.path[:0] = [str(X)]
import chooser_image as C

# chooser-v1-r11 manifest.json (the PHYSICAL PASS display-handback chooser, attempts/chooser-v1-r11-t1).
R11_CFLAGS = ('-DTGL_CHOOSER=1 -DTGL_CHOOSER_MMU=1 -DTGL_CHOOSER_UI=1 -DTGL_CHOOSER_DISPLAY=1 -DTGL_DCS_MENU=1 '
              '-DTGL_FRAME_RUNG=3 -DTGL_DCS_QUIESCE=1')
R11_SRC = 'chooser.c lz4.c el2_mmu.c menu_ui.c tgl_dcs.c'


def sw(**k):
    d = dict(mmu=False, ui=False, display=False, quiesce=False, keys=False, keys_poll=False)
    d.update(k); return argparse.Namespace(**d)


R11 = dict(mmu=True, ui=True, display=True, quiesce=True)


class Gates(unittest.TestCase):
    def test_r11_unchanged(self):
        self.assertEqual(C.gates(sw(**R11)), (R11_CFLAGS, R11_SRC))

    def test_keys_poll_adds_only_the_keys_gates(self):
        f, s = C.gates(sw(**R11, keys=True, keys_poll=True))
        # --keys keeps its existing place before the quiesce gate; the poll gates go last.
        self.assertEqual(f, R11_CFLAGS.replace(' -DTGL_DCS_QUIESCE=1', ' -DTGL_CHOOSER_KEYS=1 -DTGL_DCS_QUIESCE=1') +
                         ' -DTGL_KEYS_POLL=1 -DTGL_CHOOSER_KEYS_POLL=1')
        self.assertEqual(sorted(f.split()), sorted(R11_CFLAGS.split() + ['-DTGL_CHOOSER_KEYS=1', '-DTGL_KEYS_POLL=1', '-DTGL_CHOOSER_KEYS_POLL=1']))
        self.assertEqual(s, R11_SRC + ' keys_laguna.c')

    def test_keys_without_poll_has_no_poll_gate(self):
        f, s = C.gates(sw(**R11, keys=True))
        self.assertNotIn('KEYS_POLL', f); self.assertNotIn('keys_laguna', s)

    def test_keys_poll_needs_keys(self):
        with self.assertRaises(SystemExit) as e: C.gates(sw(**R11, keys_poll=True))
        self.assertIn('--keys-poll', str(e.exception))

    def test_existing_refusals_kept(self):
        with self.assertRaises(SystemExit): C.gates(sw(display=True))
        with self.assertRaises(SystemExit): C.gates(sw(ui=True, quiesce=True))

    def test_symbols_checked_with_the_gate(self):
        for s in ('keys_init', 'keys_poll', 'chooser_keys_db'): self.assertIn(s, C.KEYS_POLL_SYMS)


class Cli(unittest.TestCase):
    def run_cli(self, *extra):
        name = 'test-chooser-' + uuid.uuid4().hex[:12]
        r = subprocess.run([sys.executable, '-I', str(X / 'chooser_image.py'), 'image', name, '--stock-kernel', '/nonexistent',
                            '--stock-kernel-sha', '0' * 64, '--mmu', '--ui', '--display', '--quiesce', *extra],
                           capture_output=True, text=True)
        self.assertFalse((C.IT.RUN / name).exists(), 'a refused build left an output directory')
        return r

    def test_cli_refuses_poll_without_keys_before_reading_input(self):
        r = self.run_cli('--keys-poll')
        self.assertNotEqual(r.returncode, 0); self.assertIn('--keys-poll debounces the --keys reads', r.stderr)

    def test_cli_accepts_the_switch(self):
        # Gates pass; the build then stops at the missing stock image (FileNotFoundError), not at argparse or gating.
        r = self.run_cli('--keys', '--keys-poll')
        self.assertNotIn('unrecognized arguments', r.stderr); self.assertNotIn('refused:', r.stderr)
        self.assertIn('/nonexistent', r.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
