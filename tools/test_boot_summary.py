"""Host tests of panic_region.py and boot-summary.py. No device.

Synthetic cases always run. Cases on real attempts skip when captures are absent,
because device dumps stay out of git.
"""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
ATTEMPTS = TOOLS.parent / "research/laguna-usb-fix/attempts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


region = load("panic_region", TOOLS / "panic_region.py")
summary = load("boot_summary", TOOLS / "boot-summary.py")
ENTRY = 2919824518


def panic_text(boot=0x4c, usec=0x573a3, abs_time=0xb12a927b, uuid="430B9DC4-6692-31EF-959C-7D8EED44C8C1"):
    return (f"panic(cpu 0 caller 0xfffffff007b03918):  initproc failed\n"
            f"Kernel UUID: {uuid}\nmach_absolute_time: {abs_time:#x}\n"
            f"Epoch Time:        sec       usec\n  Boot    : {boot:#010x} {usec:#010x}\n")


def dump_with(text, off=0x100000, size=0x400000):
    body = text.encode()
    data = bytearray(size)
    data[off:off + 48] = struct.pack("<4sIIQ6I", b"KNUF", 1, 4, 0, 0xa1, len(body), 0, 0, 0, 0)
    data[off + 0xa1:off + 0xa1 + len(body)] = body
    return bytes(data)


class Region(unittest.TestCase):
    FRESH = {"fresh": True, "entry_cntvct": ENTRY}

    def test_current_when_bound(self):
        current, regions = region.select(dump_with(panic_text()), self.FRESH)
        self.assertEqual(len(regions), 1)
        self.assertEqual(current["message"], "initproc failed")
        self.assertEqual(current["caller"], 0xfffffff007b03918)
        self.assertEqual(current["kernel_uuid"], "430B9DC4-6692-31EF-959C-7D8EED44C8C1")

    def test_no_region_when_entry_not_fresh(self):
        current, regions = region.select(dump_with(panic_text()), {"fresh": False, "entry_cntvct": ENTRY})
        self.assertIsNone(current)
        self.assertEqual(len(regions), 1)

    def test_other_boots_are_not_current(self):
        for label, text in (("boot long before entry", panic_text(boot=0x30)),
                            ("boot long after entry", panic_text(boot=0x60)),
                            ("clock before entry", panic_text(abs_time=ENTRY - 1)),
                            ("no boot time", "panic(cpu 0 caller 0x1): x\nmach_absolute_time: 0xb12a927b\n"),
                            ("no clock", "panic(cpu 0 caller 0x1): x\n  Boot    : 0x4c 0x573a3\n")):
            with self.subTest(label):
                self.assertIsNone(region.select(dump_with(text), self.FRESH)[0])

    def test_incoherent_headers_ignored(self):
        self.assertEqual(region.find_regions(dump_with("not a panic")), [])
        self.assertEqual(region.find_regions(dump_with(panic_text(), off=0x100010)), [])
        cut = bytearray(dump_with(panic_text()))
        struct.pack_into("<I", cut, 0x100000 + 24, 0x7fffffff)
        self.assertEqual(region.find_regions(bytes(cut)), [])


class Text(unittest.TestCase):
    def test_stamp_boots(self):
        slots = [{"cntvct": 5}, {"cntvct": 9}, {"cntvct": 2}, {"cntvct": 3}]
        self.assertEqual(summary.stamp_boots(slots), [0, 2])
        self.assertEqual(summary.stamp_boots(slots[:2]), [0])
        self.assertEqual(summary.stamp_boots([]), [])

    def test_refusal_prefers_console_then_stamp(self):
        console = "BOOTARG x\nREFUSED USB transfer active at XNU handoff\n"
        stamps = "48 49 payload-admit REFUSED 0x6e61727420425355 26135.7\n"
        self.assertEqual(summary.refusal_text(console, stamps), "USB transfer active at XNU handoff")
        self.assertEqual(summary.refusal_text("", stamps), "USB tran...")
        self.assertIsNone(summary.refusal_text("", "REFUSED 0x0000000080000000 1.0\n"))
        self.assertEqual(summary.refusal_text("WHY usb console bring-up failed\n", ""), "usb console bring-up failed")

    def test_not_entered_covers_reused_handoff(self):
        reused = summary.not_entered_text({"reused": True, "reason": 5}, {}, "", "")
        self.assertIn("nonce reused", reused)
        plain = summary.not_entered_text({"reason": 5, "present": True}, {"status": "x"}, "", "")
        self.assertIn("no XNU entry record", plain)
        none = summary.not_entered_text({"reason": 0, "reason_name": "none"}, {}, "", "")
        self.assertIn("no refusal text", none)

    def test_root_io(self):
        io = summary.root_io("blazer-root: deadline 300 s, stage mounted, 10287 reads, 10302 blocks, busy 76359 ms")
        self.assertEqual((io["ms_per_block"], io["mib_per_s"]), (7.41, 0.53))
        self.assertIsNone(summary.root_io("initproc failed"))
        self.assertNotIn("ms_per_block", summary.root_io("1 reads, 0 blocks, busy 0 ms"))


class Links(unittest.TestCase):
    def test_macho_uuid(self):
        self.assertIsNone(summary.macho_uuid("/nonexistent"))
        self.assertIsNone(summary.macho_uuid(__file__))


@unittest.skipUnless(ATTEMPTS.is_dir(), "no captures")
class RealAttempts(unittest.TestCase):
    XNU = "20261101-192828-ufs-xnu-r1"
    DISPLAY = ("20261101-194928-display-dcs-r1", "20261101-195242-display-dcs-r2")
    HANDED_OFF = ("20261101-181009-ufs-link-r1", "20261101-181514-ufs-link-r2",
                  "20261101-181939-ufs-postlink-r1", "20261101-182305-ufs-postlink-r2",
                  "20261101-184019-high-window-r1", "20261101-184200-high-window-fill-r1",
                  "20261101-184625-ufs-read-r1", "20261101-185202-ufs-read-r2",
                  "20261101-192343-ufs-read-r3", "20261101-192655-ufs-shim-r1", XNU,
                  "20261101-200840-page16k-r1")

    def run_one(self, name):
        path = ATTEMPTS / name
        if not (path / "ramdump/kernel.log").is_file():
            self.skipTest(f"no capture {name}")
        return summary.summarize(path)

    def test_handed_off_boots_show_their_panic(self):
        for name in self.HANDED_OFF:
            with self.subTest(name):
                s = self.run_one(name)
                self.assertTrue(s["panic"]["current"])
                self.assertIn("initproc failed to start", s["panic"]["message"])
                self.assertEqual(s["milestone"]["last"], "USERLAND-EXEC")
                self.assertIsNone(s["not_entered"])
                self.assertFalse(s["milestone"]["launchd_main"])
                self.assertEqual(s["kernel"]["match"], False)

    def test_display_boots_show_residue_only(self):
        for name in self.DISPLAY:
            with self.subTest(name):
                s = self.run_one(name)
                self.assertFalse(s["panic"]["current"])
                self.assertEqual(s["panic"]["regions"], 1)
                self.assertIs(s["nonce"]["xnu_match"], False)
                self.assertIs(s["nonce"]["image_match"], True)
                self.assertEqual(s["ufs"]["ladder"], None)
                self.assertNotIn("panic     initproc", summary.render(s))
                self.assertIn("residue", summary.render(s))
                self.assertIn("XNU not entered:", summary.render(s))

    def test_refused_boots_name_the_refusal(self):
        for name in ("20261101-201242-ufs-root-r1", "20261101-201517-ufs-root-r1b"):
            with self.subTest(name):
                s = self.run_one(name)
                text = summary.render(s)
                self.assertIn("XNU not entered: USB transfer active at XNU handoff", text)
                self.assertNotIn("initproc", text)
                self.assertFalse(s["panic"]["current"])
                self.assertIs(s["image_same"], False)
                self.assertIsNone(s["nonce"]["image_match"])

    def test_reused_nonce_is_called_out(self):
        s = self.run_one("20261101-201517-ufs-root-r1b")
        self.assertEqual((s["shim"]["boots"], s["shim"]["boot_stamps"]), (2, 50))
        self.assertIn("NONCE REUSED", summary.render(s))
        self.assertEqual(self.run_one("20261101-201242-ufs-root-r1")["shim"]["boots"], 1)

    def test_long_userland_boot(self):
        s = self.run_one("20261101-201914-ufs-root-r2")
        self.assertIsNone(s["not_entered"])
        self.assertTrue(s["panic"]["current"])
        self.assertIn("blazer-root: deadline 300 s", s["panic"]["message"])
        self.assertTrue(s["milestone"]["launchd_main"])
        self.assertEqual(s["milestone"]["last"], "LAUNCHD-MAIN")
        self.assertIs(s["kernel"]["match"], True)
        self.assertGreater(s["panic"]["seconds_after_entry"], 300)
        self.assertEqual(s["root_io"]["ms_per_block"], 7.41)

    def test_xnu_boot_ufs(self):
        s = self.run_one(self.XNU)
        self.assertEqual(s["ufs"]["link"], {"current": True, "rc": 0, "up": 1})
        self.assertEqual((s["ufs"]["read"]["rc"], s["ufs"]["read"]["blocks"]), ("OK", 21))
        self.assertEqual(s["ufs"]["xnu"], {"reads": 15, "errors": 0, "done": True})
        self.assertEqual(s["kernel"]["match"], False)

    def test_every_panic_is_rejected_against_every_other_boot(self):
        """Replay each captured panic against each other boot's entry record."""
        entries = {}
        regions = {}
        reader = load("read_ramdump", TOOLS / "read-ramdump.py")
        for name in self.HANDED_OFF:
            path = ATTEMPTS / name / "ramdump/kernel.log"
            if not path.is_file():
                self.skipTest("captures absent")
            data = path.read_bytes()
            doc = reader.analyze(data, None, "x", path, summary.DUMP_BASE, reader.RAMOOPS_PA,
                                 1024, None, None, None, True, None)
            entries[name] = doc["freshness"]["handoff_entry"]
            regions[name] = region.find_regions(data)[0]
        for owner, record in regions.items():
            self.assertTrue(region.is_current(record, entries[owner]), owner)
            for other, entry in entries.items():
                if other != owner:
                    self.assertFalse(region.is_current(record, entry), f"{owner} against {other}")

    def test_cli_fits_one_screen(self):
        path = ATTEMPTS / self.XNU
        if not path.is_dir():
            self.skipTest("capture absent")
        result = subprocess.run([sys.executable, str(TOOLS / "boot-summary.py"), str(path)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertLessEqual(len(lines), 24)
        self.assertLessEqual(max(map(len, lines)), 100)

    def test_cli_missing_dump(self):
        result = subprocess.run([sys.executable, str(TOOLS / "boot-summary.py"), "/nonexistent"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
