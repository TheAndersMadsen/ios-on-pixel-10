import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "research/laguna-usb-console/tools/build-next-boot.sh"


class NextBootGateTests(unittest.TestCase):
    def run_build(self, out, macho):
        env = os.environ.copy()
        env.update(R4_MACHO=str(macho), OUT=str(out))
        return subprocess.run([str(BUILD)], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=30)

    def test_missing_r4_input_fails_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            result = self.run_build(out, Path(directory) / "missing.macho")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required input", result.stderr)
            self.assertFalse((out / "laguna-usb-next-boot-avb.img").exists())

    def test_mirrorless_r4_fails_before_mkpayload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            macho = root / "old-0128.macho"
            macho.write_bytes(b"not a mirror producer")
            out = root / "out"
            result = self.run_build(out, macho)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lacks XNU-MSGBUF v1", result.stderr)
            self.assertFalse((out / "payload-usb.bin").exists())
            self.assertFalse((out / "laguna-usb-next-boot-avb.img").exists())

    def test_marker_does_not_make_invalid_macho_bootable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            macho = root / "marker-only.macho"
            macho.write_bytes(b"XNU-MSGBUF v1\0not a Mach-O")
            out = root / "out"
            result = self.run_build(out, macho)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((out / "laguna-usb-next-boot-avb.img").exists())


if __name__ == "__main__":
    unittest.main()
