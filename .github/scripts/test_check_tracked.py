#!/usr/bin/env python3
"""Tests for check_tracked.py, on throwaway repositories."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

CHECK = pathlib.Path(__file__).with_name('check_tracked.py').resolve()
IMEI_SHAPED = '3' * 7 + '5' * 8  # built here so this file doesn't trip its own check


class CheckTracked(unittest.TestCase):
    def run_on(self, name, data=b'text\n', *args):
        with tempfile.TemporaryDirectory() as d:
            git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'core.hooksPath=/dev/null', '-C', d]
            subprocess.run([*git, 'init', '-q'], check=True)
            path = pathlib.Path(d, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            subprocess.run([*git, 'add', '-f', '--', name], check=True)
            if '--history' in args:
                subprocess.run([*git, 'commit', '-qm', 'add'], check=True)
                subprocess.run([*git, 'rm', '-qf', '--', name], check=True)
                subprocess.run([*git, 'commit', '-qm', 'remove', '--allow-empty'], check=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
            return subprocess.run([sys.executable, '-I', str(CHECK), *args], cwd=d, env=env, capture_output=True, text=True)

    def test_clean_text_passes(self):
        self.assertEqual(self.run_on('tools/read-ramdump.py').returncode, 0)

    def test_bad_names_fail(self):
        for name in ('boot.img', 'a/b.bin', 'x/ramdump/notes.txt', 'fw_bcmdhd.bin_4390_b1', 'research/a.md', 'kernel.log',
                     'cs40l26-calib.txt', 'DeviceTree.d421ap.txt', 'test-rsa4096.pem', 'dyld_shared_cache_arm64e'):
            with self.subTest(name):
                self.assertEqual(self.run_on(name).returncode, 1)

    def test_binary_fails(self):
        self.assertEqual(self.run_on('blob.dat', b'a\0b').returncode, 1)

    def test_imei_shape_fails_and_value_stays_out_of_the_log(self):
        result = self.run_on('n.md', f'IMEI {IMEI_SHAPED}\n'.encode())
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(IMEI_SHAPED, result.stdout)

    def test_serial_assignment_fails(self):
        self.assertEqual(self.run_on('n.md', b'androidboot.serial' + b'no=ABC12345\n').returncode, 1)

    def test_other_long_numbers_pass(self):
        for text in ('0x' + IMEI_SHAPED, IMEI_SHAPED + '1', 'a' + IMEI_SHAPED, '1.' + IMEI_SHAPED):
            with self.subTest(text):
                self.assertEqual(self.run_on('n.md', text.encode() + b'\n').returncode, 0)

    def test_history_finds_a_removed_file(self):
        self.assertEqual(self.run_on('boot.img', b'x\n', '--history').returncode, 1)


if __name__ == '__main__':
    unittest.main()
