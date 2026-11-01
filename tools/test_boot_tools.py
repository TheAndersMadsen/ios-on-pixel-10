"""Device-free tests of capture-fastboot.py, run-attempt.sh and bootios.

Every fastboot, adb and USB call goes to a fake; nothing here touches a phone.
run-attempt.sh writes beneath the repository it finds itself in, so it runs from
a copy in a temporary tree and cannot reach the real ATTEMPTS.md.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
RUNNER = ROOT / "research/laguna-usb-fix/run-attempt.sh"
FORBIDDEN = ("reboot", "flash", "erase", "format", "set_active", "--set-active", "flashing", "continue")

_spec = importlib.util.spec_from_file_location("decode_shim_stamps", TOOLS / "decode-shim-stamps.py")
dec = importlib.util.module_from_spec(_spec)
sys.modules["decode_shim_stamps"] = dec
_spec.loader.exec_module(dec)


def kernel_log():
    """A 4 MiB aperture holding one real TSHIMST2 record the decoder accepts."""
    blob = bytearray(0x400000)
    base = dec.SHIM_STAMP_PA - dec.DEFAULT_DUMP_BASE
    struct.pack_into("<8sQIIIIQQQII", blob, base, dec.MAGIC, 0xfeedface1234, 1, 1, 1, 0,
                     38400000, 1000, 2000, 0, 1)
    struct.pack_into("<IHHQQ", blob, base + dec.HDR_SIZE, 1, 0x0001, 0x0001, 1500, 0)
    return bytes(blob)


ABL_TEXT = (b"  RST_STAT: 0x3 - Fatal Error SW\n  Reboot reason: 0xbab9 - Early Kernel PANIC\n"
            b"  RST_STAT: 0x0 - Cold Reset\n  Reboot reason: 0xbab9 - Early Kernel PANIC\n")

# State lives in $FAKE_DIR. `boot` marks the phone gone until FAKE_PARK_AFTER
# seconds have passed; a negative value means it never comes back.
FAKE_FASTBOOT = r'''#!/usr/bin/env python3
import os, pathlib, struct, sys, time
state = pathlib.Path(os.environ["FAKE_DIR"])
args = sys.argv[1:]
with open(state / "fastboot.calls", "a") as calls:
    calls.write(" ".join(args) + "\n")
booted = state / "booted"
park_after = float(os.environ.get("FAKE_PARK_AFTER", "0"))
parked = not booted.exists() or (park_after >= 0 and time.time() - booted.stat().st_mtime >= park_after)
if args == ["--version"]:
    print("fastboot version fake")
elif args == ["devices"]:
    if parked:
        print("FAKESERIAL\tfastboot")
elif not parked:
    print("< waiting for any device >"); sys.exit(1)
elif args == ["boot", args[-1]]:
    booted.touch(); print("Finished. Total time: 0.1s")
elif args[:1] == ["getvar"]:
    values = {"product": "blazer", "is-userspace": "no"}
    print(f"{args[1]}: {values.get(args[1], 'fake')}\nFinished. Total time: 0.001s")
elif args == ["oem", "force-fastboot", "on"]:
    print("OKAY [  0.001s]\nFinished.")
elif args == ["oem", "force-fastboot"]:
    print("(bootloader) force-fastboot on\nOKAY [  0.001s]")
elif args == ["oem", "ramdump"]:
    print("(bootloader) ramdump mode\nOKAY")
elif args[:3] == ["oem", "ramdump", "stage_file"]:
    if os.environ.get("FAKE_STAGE_FAIL") == args[3]:
        print("FAILED (remote: 'no such region')"); sys.exit(1)
    (state / "staged").write_text(args[3]); print("OKAY")
elif args[0] == "get_staged":
    name = (state / "staged").read_text()
    pathlib.Path(args[1]).write_bytes((state / ("region-" + name)).read_bytes()); print("OKAY")
else:
    print("fake fastboot: unexpected", args); sys.exit(1)
'''

# Prints the marker the real logger prints, FAKE_CONSOLE_AFTER seconds after start.
FAKE_USB_LOG = r'''#!/usr/bin/env python3
import os, sys, time
delay = float(os.environ.get("FAKE_CONSOLE_AFTER", "-1"))
if delay >= 0:
    time.sleep(delay)
    print("Tegu USB diagnostic connected.", file=sys.stderr, flush=True)
    print("LAGUNA USB: fake log line", flush=True)
time.sleep(600)
'''

FAKE_READER = """#!/usr/bin/env python3
print("read-ramdump fake")
print("VERDICT: PANICKED | fake")
"""


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def fill_regions(state):
    state.mkdir(parents=True, exist_ok=True)
    abl = struct.pack("<QQ", len(ABL_TEXT), 0x80000 - 16) + ABL_TEXT
    regions = {"RAMDUMP_MSG.txt": b"m" * 0x400, "kernel.log": kernel_log(), "bootreason.log": b"b" * 0x200,
               "abl.log": abl.ljust(0x80000, b"\0"), "abl_last.log": abl.ljust(0x80000, b"\0")}
    for name, data in regions.items():
        (state / ("region-" + name)).write_bytes(data)


def calls(state):
    return (state / "fastboot.calls").read_text().splitlines()


class CaptureNamedOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "state"
        fill_regions(self.state)
        self.fake = self.dir / "fastboot"
        write_exec(self.fake, FAKE_FASTBOOT)

    def capture(self, *extra, env=None):
        merged = {k: v for k, v in os.environ.items() if k != "HACKIOS_DEVICE_LEASE_FD"}
        merged.update(FAKE_DIR=str(self.state), **(env or {}))
        return subprocess.run([sys.executable, str(TOOLS / "capture-fastboot.py"), str(self.dir / "out"),
                               "--fastboot", str(self.fake), *extra],
                              env=merged, capture_output=True, text=True, timeout=60)

    def test_runs_by_hand_without_any_lease(self):
        result = self.capture("--diagnostics", "--named-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.dir / "out"
        self.assertEqual(json.loads((out / "manifest.json").read_text())["status"], "success")
        self.assertEqual((out / "abl.log.txt").read_bytes(), ABL_TEXT)
        self.assertEqual((out / "kernel.log").stat().st_size, 0x400000)

    def test_only_named_stage_and_get_staged(self):
        self.capture("--diagnostics", "--named-only")
        expected = []
        for name in ("RAMDUMP_MSG.txt", "kernel.log", "bootreason.log", "abl.log", "abl_last.log"):
            expected += [f"oem ramdump stage_file {name}", f"get_staged {name}"]
        self.assertEqual(calls(self.state), expected)

    def test_stale_lease_variable_is_ignored(self):
        result = self.capture("--diagnostics", "--named-only", env={"HACKIOS_DEVICE_LEASE_FD": "987"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_still_requires_diagnostics(self):
        result = self.capture("--named-only")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --diagnostics", result.stderr)
        self.assertFalse((self.dir / "out").exists())

    def test_old_path_symlink_points_here(self):
        old = ROOT / "research/laguna-ramdump/tools/capture-fastboot.py"
        if not old.is_symlink():
            self.skipTest("research/ is local and absent or not moved in this checkout")
        self.assertEqual(old.resolve(), TOOLS / "capture-fastboot.py")


class UsbLogPaths(unittest.TestCase):
    def test_old_path_symlinks_point_here(self):
        for name in ("usb_log.py", "usb_keyboard.py"):
            old = ROOT / "research/tegu-ios/tools/tegu" / name
            if not old.is_symlink():
                self.skipTest("research/ is local and absent or not moved in this checkout")
            self.assertEqual(old.resolve(), TOOLS / name)

    def test_no_nested_checkout_root_remains(self):
        source = (TOOLS / "usb_log.py").read_text()
        self.assertEqual(source.count("resolve().parents[1]"), 2)
        self.assertNotIn("parents[2]", source)
        self.assertNotIn("parents[4]", source)


class RunAttempt(unittest.TestCase):
    """The tools/bootios mode: --wait-park-after-ep0, with fast watch timings."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve() / "repo"
        self.state = self.repo.parent / "state"
        fill_regions(self.state)
        usbfix = self.repo / "research/laguna-usb-fix"
        usbfix.mkdir(parents=True)
        shutil.copy(RUNNER, usbfix / "run-attempt.sh")
        shutil.copy(TOOLS / "capture-fastboot.py", self.tool("tools/capture-fastboot.py"))
        shutil.copy(TOOLS / "decode-shim-stamps.py", self.tool("research/laguna-usb-console/tools/decode-shim-stamps.py"))
        write_exec(self.repo / "tools/usb_log.py", FAKE_USB_LOG)
        write_exec(self.tool("research/laguna-ramdump/reader/read-ramdump.py"), FAKE_READER)
        write_exec(self.tool("research/native-20261024/reuse/felix-working-source/baremetal_loader/avbtool.py"), "")
        write_exec(self.tool("research/laguna-panic-capture/mach.laguna141-paniccap"), "")
        self.fastboot = self.repo.parent / "bin/fastboot"
        write_exec(self.fastboot, FAKE_FASTBOOT)
        self.adb = self.repo.parent / "bin/adb"
        write_exec(self.adb, "#!/bin/sh\nexit 0\n")
        self.image = self.repo.parent / "boot.img"
        self.image.write_bytes(b"fake image")

    def tool(self, relative):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def run_attempt(self, *options, env=None):
        merged = dict(os.environ, FAKE_DIR=str(self.state), FASTBOOT=str(self.fastboot), ADB=str(self.adb),
                      TEGU_PYTHON=sys.executable, PY3=sys.executable, **(env or {}))
        result = subprocess.run(
            [str(self.repo / "research/laguna-usb-fix/run-attempt.sh"), "--image", str(self.image),
             "--name", "fake", "--skip-avb", "--settle", "0", "--poll", "1", *options],
            env=merged, capture_output=True, text=True, timeout=120)
        attempts = list((self.repo / "research/laguna-usb-fix/attempts").glob("*-fake"))
        self.assertEqual(len(attempts), 1, result.stdout + result.stderr)
        return result, attempts[0]

    def assert_full_capture(self, attempt):
        for name in ("kernel.log", "abl.log", "abl.log.txt", "abl_last.log", "abl_last.log.txt", "bootreason.log"):
            self.assertTrue((attempt / "ramdump" / name).is_file(), name)
        decoded = (attempt / "stamps-decode.txt").read_text()
        self.assertIn("nonce=0x0000feedface1234", decoded)
        self.assertIn("last stage: entry", decoded)
        self.assertTrue((attempt / "reader.txt").is_file())
        timeline = (attempt / "park-timeline.txt").read_text()
        self.assertIn("capture_rc: 0", timeline)
        self.assertIn("abl_reboot_reason: 0xbab9", timeline)
        self.assertIn("class 0x3, warm-fatal-error-sw", timeline)

    def assert_contract(self):
        for call in calls(self.state):
            self.assertNotIn(call.split()[0], FORBIDDEN, call)
            self.assertNotEqual(call, "oem force-fastboot off")

    def verdict(self):
        return (self.repo / "research/laguna-usb-fix/ATTEMPTS.md").read_text().splitlines()[-1]

    def test_console_first_then_park_captures_everything(self):
        result, attempt = self.run_attempt("--watch", "30", "--wait-park-after-ep0", "20",
                                           env={"FAKE_CONSOLE_AFTER": "0", "FAKE_PARK_AFTER": "4"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_full_capture(attempt)
        self.assertIn("Tegu USB diagnostic connected.", (attempt / "live.log").read_text())
        timeline = (attempt / "park-timeline.txt").read_text()
        self.assertRegex(timeline, r"ep0_live_watch_s: \d+")
        self.assertRegex(timeline, r"ep0_to_park_s: [1-9]\d*")
        self.assertIn("outcome=park EP0=yes", result.stdout)
        fields = [field.strip() for field in self.verdict().split("|")]
        self.assertEqual(fields[3:6], ["yes", "entry [-]@seq1", "timeout"])
        self.assertNotIn("capture-failed", self.verdict())
        self.assert_contract()

    def test_park_without_console_captures_everything(self):
        result, attempt = self.run_attempt("--watch", "30", "--wait-park-after-ep0", "20",
                                           env={"FAKE_PARK_AFTER": "2"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_full_capture(attempt)
        self.assertIn("never (no EP0 console this boot)", (attempt / "park-timeline.txt").read_text())
        self.assertIn("outcome=park EP0=no", result.stdout)
        self.assert_contract()

    def test_console_late_in_watch_still_gets_its_park_window(self):
        # The console appears after the watch would have ended; the park comes later still.
        result, attempt = self.run_attempt("--watch", "3", "--wait-park-after-ep0", "20", "--ep0-grace", "0",
                                           env={"FAKE_CONSOLE_AFTER": "2", "FAKE_PARK_AFTER": "8"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("outcome=park EP0=yes", result.stdout)
        self.assert_full_capture(attempt)

    def test_window_expiry_without_park_records_console_only(self):
        result, attempt = self.run_attempt("--watch", "2", "--wait-park-after-ep0", "3", "--ep0-grace", "0",
                                           env={"FAKE_CONSOLE_AFTER": "0", "FAKE_PARK_AFTER": "-1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("outcome=ep0-live EP0=yes", result.stdout)
        self.assertFalse((attempt / "ramdump").exists())
        self.assertFalse(any("stage_file" in call for call in calls(self.state)))

    def test_capture_uses_the_configured_fastboot_and_reports_partial_failure(self):
        # A fake only reachable through $FASTBOOT proves the collector was told about it.
        result, attempt = self.run_attempt("--watch", "30", "--wait-park-after-ep0", "20",
                                           env={"FAKE_PARK_AFTER": "1", "FAKE_STAGE_FAIL": "abl.log"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((attempt / "ramdump/kernel.log").is_file())
        self.assertTrue((attempt / "stamps-decode.txt").is_file())
        self.assertIn("capture_rc: 2", (attempt / "park-timeline.txt").read_text())
        self.assertIn("capture incomplete (rc=2)", result.stderr)

    def test_no_coordinator_wording(self):
        self.assertNotIn("coordinator", RUNNER.read_text().lower())


class Bootios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve()
        (self.repo / "tools").mkdir()
        shutil.copy(TOOLS / "bootios", self.repo / "tools/bootios")
        self.image = self.repo / "boot.img"
        self.image.write_bytes(b"fake image")

    def run_with(self, runner_body):
        write_exec(self.repo / "research/laguna-usb-fix/run-attempt.sh", "#!/bin/sh\n" + runner_body)
        return subprocess.run([str(self.repo / "tools/bootios"), str(self.image), "fake"],
                              capture_output=True, text=True, timeout=20)

    def test_ends_with_attempt_directory_and_passes_park_wait(self):
        result = self.run_with('echo "args: $*"\necho "[run-attempt] attempt dir: /x/attempts/1-fake"\n'
                               'echo "[run-attempt] DONE"\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines()[-1], "attempt: /x/attempts/1-fake")
        self.assertIn("--wait-park-after-ep0 180", result.stdout)

    def test_runner_status_and_no_directory(self):
        result = self.run_with('echo "[run-attempt] ABORT: no phone" >&2\nexit 2\n')
        self.assertEqual(result.returncode, 2)
        self.assertIn("ABORT: no phone", result.stdout)
        self.assertTrue(result.stdout.splitlines()[-1].startswith("attempt: none"))


if __name__ == "__main__":
    unittest.main()
