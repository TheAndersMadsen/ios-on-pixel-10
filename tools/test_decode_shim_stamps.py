#!/usr/bin/env python3
"""Host tests for tools/decode-shim-stamps.py (S1 lane).

Builds synthetic 4 MiB kernel.log fixtures — a v2 TSHIMST2 trail (64-slot
ring, 24-byte slots with per-stamp timestamps) and a v1 TSHIMST1 trail shaped
like the real 2026-10-27 v2b device dump — runs the CLI against them, and
checks the human/JSON renders plus the failure paths.
"""
import importlib.util  # noqa: E402
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "decode_shim_stamps", TOOLS / "decode-shim-stamps.py")
dec = importlib.util.module_from_spec(_spec)
sys.modules["decode_shim_stamps"] = dec
_spec.loader.exec_module(dec)

PA = dec.SHIM_STAMP_PA
BASE = dec.DEFAULT_DUMP_BASE
FREQ = 38400000


def build_blob(stamps, nonce=0xfeedface1234, reason=1, count=None, abi=2):
    blob = bytearray(4 * 1024 * 1024)
    base = PA - BASE
    t0 = 2_000_000
    tlast = t0 + FREQ // 2  # 500 ms of bring-up
    magic = dec.MAGIC if abi == 2 else dec.MAGIC_V1
    struct.pack_into("<8sQIIIIQQQII", blob, base, magic, nonce,
                     count if count is not None else len(stamps),
                     len(stamps), stamps[-1][1] if stamps else 0,
                     stamps[-1][2] if stamps else 0, FREQ, t0, tlast,
                     0, reason)
    for i, (seq, stage, flags, arg) in enumerate(stamps):
        if abi == 2:
            t = t0 + FREQ * (i + 1) // (len(stamps) + 1)
            struct.pack_into("<IHHQQ", blob,
                             base + dec.HDR_SIZE + i * dec.SLOT_SIZE_V2,
                             seq, stage, flags, t, arg)
        else:
            struct.pack_into("<IHHQ", blob,
                             base + dec.HDR_SIZE + i * dec.SLOT_SIZE_V1,
                             seq, stage, flags, arg)
    return bytes(blob)


STAMPS = [
    (1, 0x0001, 0x0001, 0),           # entry
    (2, 0x0004, 0x0002, 0x8a000000),  # fdt parse done (device dtb)
    (3, 0x0003, 0x0002, 0x3),         # wdt survey: both identified
    (4, 0x001d, 0x0002, 0xf0000000),  # console paint done
    (5, 0x001e, 0x0001, 0),           # cpm-first ENTER
    (6, 0x001f, 0x0002, 0x00040004),  # cpm-geo: 4/4 words
    (7, 0x0009, 0x0002, 0),           # cpm ack done
    (8, 0x0021, 0x0002, 0x0700),      # clk 0x07 resp 0
    (9, 0x0022, 0x0002, 0x0d00),      # rst 0x0d resp 0
    (10, 0x0016, 0x0002, 0x33313130),  # GSNPSID value evidence
    (11, 0x0017, 0x0002, 0x1020),      # GCTL value evidence
    (12, 0x0018, 0x0002, 0x0),         # EVT_HI hang-check ok
    (13, 0x0009, 0x0001, 3000),        # cpm-ack-wait ENTER (hang candidate)
]

# The v3.4 cpm-fail scenario: MBA mailbox dead cold — geometry refuses.
CPM_FAIL_STAMPS = [
    (1, 0x0001, 0x0001, 0),
    (2, 0x001e, 0x0001, 0),           # cpm-first ENTER
    (3, 0x001f, 0x0001, 0),           # cpm-geo ENTER
    (4, 0x001f, 0x0008, 0),           # cpm-geo FAULT arg=0 (read faulted)
    (5, 0x001e, 0x0008, 0xffffffff),  # terminal FAULT, code -1
]

# The v3.5 warm path: usb-warm YES -> skip CPM -> preflight value evidence.
WARM_STAMPS = [
    (1, 0x0001, 0x0001, 0),
    (2, 0x0023, 0x0002, 0x33313130),  # usb-warm YES arg=gsnpsid
    (3, 0x0024, 0x0002, 0x0),         # DCTL fingerprint: RUN_STOP cleared
    (4, 0x0007, 0x0002, 0x33313130),  # preflight GSNPSID ok
    (5, 0x0017, 0x0002, 0x1020),      # GCTL device-mode evidence
    (6, 0x0018, 0x0002, 0x0),         # EVT_HI hang-check ok
    (7, 0x001e, 0x0002, 0x1f),        # cpm-first DONE bitmap (rdback ok)
    (8, 0x0008, 0x0002, 0xbe123000),  # dma-admit done
]

# The v3.5 cold fallback: warm NO -> MBA liveness -> one clock through the port.
COLD_STAMPS = [
    (1, 0x0001, 0x0001, 0),
    (2, 0x0023, 0x0010, 0x0),          # usb-warm NO: gsnpsid said no
    (3, 0x0023, 0x0002, 0xc2117002),   # usb-warm cfg-csr canary diagnostic
    (4, 0x0015, 0x0002, 0x0),          # usb-pwr wrapper canary diagnostic
    (5, 0x001e, 0x0001, 0),            # cpm-first ENTER
    (6, 0x001f, 0x0002, 0x60007),      # cpm-geo DONE: 6 channels, live=7
    (7, 0x002a, 0x0002, 0x4d4241),     # cpm-geo2 DONE: LPCM magic
    (8, 0x0025, 0x0002, 0x7004d4241),  # mba-live DONE: bitmap 7 + mbox0 word
    (9, 0x000c, 0x0001, 0),            # phy-resume ENTER
    (10, 0x0015, 0x0002, 0x100),       # usb-pwr status D0
    (11, 0x0026, 0x0001, 0x10007),     # mba-send ENTER: seq 1, clock cmd
    (12, 0x0026, 0x0001, 0x010f0),     # pre-doorbell marker (seq<<8|0xf0)
    (13, 0x002b, 0x0002, 0x08000000),  # LPCM req0 echo: header
    (14, 0x002c, 0x0002, 0x04010700),  # LPCM req1 echo: cmd dword
    (15, 0x0029, 0x0002, 0x1),         # mba-resp0: completion word bit0 set
    (16, 0x002d, 0x0002, 0x00840000),  # LPCM reply0: type tag
    (17, 0x002e, 0x0002, 0xfffffff8),  # LPCM reply1: NACK status (v37 device)
    (18, 0x0021, 0x0010, 0x7f8),       # clk 0x07 REFUSED, reply 0xf8
    (19, 0x0007, 0x0002, 0x33313130),  # preflight GSNPSID ok
]

# The v3.7 jump: payload loaded -> EL2->EL1 drop -> final jumping reason.
JUMP_STAMPS = [
    (1, 0x0012, 0x0001, 0x8a000000),   # payload-admit ENTER
    (2, 0x0012, 0x0002, 0x883a75238),  # payload DONE arg=entry_pa
    (3, 0x0013, 0x0001, 0x884448000),  # handoff ENTER arg=ba_pa
    (4, 0x0028, 0x0001, 0x8),          # el-drop ENTER arg=entry EL (EL2)
    (5, 0x0028, 0x0002, 0x40000000),   # el-drop DONE arg=new EL << 28 (EL1)
    (6, 0x0013, 0x0002, 0x884448000),  # handoff DONE: the final jumping stamp
]

# The v36 wedge trail: a send write wedged the bus, the WDT reset the phone —
# reason must decode as in-progress (+ last_stage names the wedge point),
# never none.
WEDGE_STAMPS = [
    (1, 0x0001, 0x0001, 0),
    (2, 0x0023, 0x0010, 0x0),
    (3, 0x001e, 0x0001, 0),
    (4, 0x0026, 0x0001, 0x0007),     # mba-send ENTER
    (5, 0x0026, 0x0001, 0x00070ff),  # pre-doorbell marker (id<<8|0xff)
]

# TGL_FAST_START=1 (shim/tgl_fast_start.h): profile, 500 ms window, FDT reuse,
# cached copy on/off, drain-only window before admission.
FAST = 0x46415354 << 32
FAST_STAMPS = [
    (1, 0x00f1, 0x0002, (1 << 56) | 0xf),          # profile: all four parts
    (2, 0x0011, 0x0001, FAST | (500 << 16) | 1000),  # usb-enum-wait ENTER
    (3, 0x0011, 0x0002, FAST | 500),                # DONE after 500 ms, idle
    (4, 0x0011, 0x0001, FAST | 1000),               # drain-only ENTER
    (5, 0x0011, 0x0002, FAST | (1 << 31) | 37),     # waited 37 ms for a data stage
    (6, 0x00f1, 0x0002, 2 << 56),                   # fdt reused
    (7, 0x00f1, 0x0002, (3 << 56) | (55 << 16)),    # cache on: 55 wb blocks
    (8, 0x00f1, 0x0002, (4 << 56) | 84250),         # cache off: 84.25 ms
]
FAST_REFUSED = [
    (1, 0x00f1, 0x0010, (2 << 56) | 4),             # fdt size changed -> parse
    (2, 0x00f1, 0x0010, (3 << 56) | 3),             # cache refused: avoid range
]
# The flag-off windows as in A7 r1: 8 s, then 1 s.
SLOW_STAMPS = [
    (1, 0x0011, 0x0001, 8), (2, 0x0011, 0x0002, 1), (3, 0x0011, 0x0001, 1), (4, 0x0011, 0x0002, 1),
]

# Shaped like the real v2b dump: saturated v1 ring, refusals dropped.
V1_STAMPS = [
    (1, 0x0001, 0x0001, 0),
    (2, 0x0002, 0x0002, 0x80d01998),
    (3, 0x0003, 0x0001, 0),
    (4, 0x0003, 0x0002, 0x3),
    (5, 0x0004, 0x0001, 0x8a000000),
    (6, 0x0005, 0x0001, 0),
    (7, 0x0006, 0x0002, 0x2),
    (8, 0x0007, 0x0001, 0),
]


class DecoderTests(unittest.TestCase):
    def test_cli_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "kernel.log"
            dump.write_bytes(build_blob(STAMPS))
            out = subprocess.run(
                [sys.executable, str(TOOLS / "decode-shim-stamps.py"), str(dump)],
                capture_output=True, text=True, check=True)
            self.assertIn("TSHIMST2 shim stamp history", out.stdout)
            self.assertIn("file offset 0x230000", out.stdout)
            self.assertIn("nonce=0x0000feedface1234", out.stdout)
            self.assertIn("count=13/128", out.stdout)
            self.assertIn("reason=timeout", out.stdout)
            self.assertIn("usb-gsnpsid", out.stdout)
            self.assertIn("0x33313130", out.stdout)
            self.assertIn("HANG EVIDENCE", out.stdout)
            self.assertIn("500.0", out.stdout)  # last slot's own timestamp

    def test_cli_json(self):
        blob = build_blob(STAMPS, reason=5)
        decoded = dec.decode(blob)
        self.assertEqual(decoded["abi"], 2)
        self.assertEqual(decoded["reason"], "handed-off-to-xnu")
        self.assertEqual(decoded["slots"][9]["stage"], "usb-gsnpsid")
        self.assertEqual(decoded["slots"][0]["flags"], "ENTER")
        self.assertEqual(decoded["slots"][0]["arg"], "0x0")
        self.assertEqual(decoded["slots"][5]["stage"], "cpm-geo")
        self.assertEqual(decoded["slots"][5]["arg"], "0x40004")
        self.assertEqual(decoded["slots"][7]["stage"], "cpm-clk")
        self.assertEqual(decoded["slots"][7]["arg"], "0x700")
        # Per-slot timestamps: monotonic, ~every 50 ms in this fixture.
        ms = [s["ms_since_entry"] for s in decoded["slots"]]
        self.assertTrue(all(m is not None for m in ms))
        self.assertEqual(ms, sorted(ms))
        json.dumps(decoded)  # must be JSON-serializable

    def test_cpm_fail_trail(self):
        blob = build_blob(CPM_FAIL_STAMPS, reason=6, count=4)
        decoded = dec.decode(blob)
        self.assertEqual(decoded["reason"], "cpm-never-came-up")
        self.assertEqual(decoded["slots"][2]["stage"], "cpm-geo")
        self.assertEqual(decoded["slots"][2]["flags"], "ENTER")
        self.assertEqual(decoded["slots"][3]["flags"], "FAULT")
        # Torn count: the terminal FAULT stamp was attempted but the count
        # word died with the fault — the four visible slots still tell it.
        self.assertEqual(len(decoded["slots"]), 4)
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "kernel.log"
            dump.write_bytes(build_blob(CPM_FAIL_STAMPS, reason=6))
            out = subprocess.run(
                [sys.executable, str(TOOLS / "decode-shim-stamps.py"), str(dump)],
                capture_output=True, text=True, check=True)
            self.assertIn("cpm-geo", out.stdout)
            self.assertIn("cpm-never-came-up", out.stdout)

    def test_warm_path_trail(self):
        blob = build_blob(WARM_STAMPS, reason=5)
        decoded = dec.decode(blob)
        self.assertEqual(decoded["slots"][1]["stage"], "usb-warm")
        self.assertEqual(decoded["slots"][1]["arg"], "0x33313130")
        self.assertEqual(decoded["slots"][2]["stage"], "usb-dctl")
        self.assertEqual(decoded["slots"][6]["stage"], "cpm-first")
        self.assertEqual(decoded["slots"][6]["arg"], "0x1f")
        self.assertEqual(decoded["slots"][7]["stage"], "dma-admit")
        # No mailbox stamps on the warm path: the CPM phase was skipped.
        for s in decoded["slots"]:
            self.assertNotIn(s["stage"], ("mba-live", "mba-send", "mba-ack"))

    def test_warm_verdict_ignores_canaries(self):
        # v3.8 regression: the v37 run had a perfect GSNPSID (0x33313130)
        # but canary0 == 0, and the old gate refused a warm controller.
        # The verdict must depend on the ID family alone; canaries ride as
        # separate diagnostics (USB_PWR value + packed cfg-csr record).
        stamps = [
            (1, 0x0001, 0x0001, 0),
            (2, 0x0015, 0x0002, 0x0),           # canary0 reads 0 (legal!)
            (3, 0x0023, 0x0002, 0xc2117002),    # cfg-csr canary diagnostic
            (4, 0x0023, 0x0002, 0x33313130),    # usb-warm YES arg=gsnpsid
            (5, 0x0007, 0x0002, 0x33313130),    # preflight GSNPSID ok
        ]
        decoded = dec.decode(build_blob(stamps, reason=5))
        self.assertEqual(decoded["slots"][3]["stage"], "usb-warm")
        self.assertEqual(decoded["slots"][3]["flags"], "DONE")  # YES despite canary0 == 0
        self.assertEqual(decoded["slots"][3]["arg"], "0x33313130")
        self.assertEqual(decoded["slots"][2]["stage"], "usb-warm")
        self.assertEqual(decoded["slots"][2]["arg"], "0xc2117002")  # cfg-csr diagnostic

    def test_cold_fallback_trail(self):
        blob = build_blob(COLD_STAMPS, reason=1)
        decoded = dec.decode(blob)
        self.assertEqual(decoded["slots"][1]["flags"], "REFUSED")
        self.assertEqual(decoded["slots"][2]["arg"], "0xc2117002")  # cfg-csr canary
        self.assertEqual(decoded["slots"][6]["stage"], "cpm-geo2")
        self.assertEqual(decoded["slots"][6]["arg"], "0x4d4241")
        self.assertEqual(decoded["slots"][7]["stage"], "mba-live")
        self.assertEqual(decoded["slots"][10]["stage"], "mba-send")
        self.assertEqual(decoded["slots"][12]["stage"], "lpcm-req0")
        self.assertEqual(decoded["slots"][12]["arg"], "0x8000000")
        self.assertEqual(decoded["slots"][13]["stage"], "lpcm-req1")
        self.assertEqual(decoded["slots"][14]["stage"], "mba-resp0")
        self.assertEqual(decoded["slots"][15]["stage"], "lpcm-reply0")
        self.assertEqual(decoded["slots"][16]["stage"], "lpcm-reply1")
        self.assertEqual(decoded["slots"][16]["arg"], "0xfffffff8")  # NACK status
        self.assertEqual(decoded["slots"][17]["stage"], "cpm-clk")
        self.assertEqual(decoded["slots"][17]["flags"], "REFUSED")
        self.assertEqual(decoded["slots"][17]["arg"], "0x7f8")  # id 0x07, 0xf8

    def test_jump_trail_el_drop(self):
        blob = build_blob(JUMP_STAMPS, reason=5)
        decoded = dec.decode(blob)
        self.assertEqual(decoded["slots"][3]["stage"], "el-drop")
        self.assertEqual(decoded["slots"][3]["flags"], "ENTER")
        self.assertEqual(decoded["slots"][3]["arg"], "0x8")  # entered at EL2
        self.assertEqual(decoded["slots"][4]["stage"], "el-drop")
        self.assertEqual(decoded["slots"][4]["arg"], "0x40000000")  # EL1 << 28
        self.assertEqual(decoded["slots"][5]["stage"], "pre-xnu-handoff")
        self.assertEqual(decoded["slots"][5]["flags"], "DONE")  # final stamp
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "kernel.log"
            dump.write_bytes(blob)
            out = subprocess.run(
                [sys.executable, str(TOOLS / "decode-shim-stamps.py"), str(dump)],
                capture_output=True, text=True, check=True)
        self.assertIn("el-drop", out.stdout)
        self.assertIn("handed-off-to-xnu", out.stdout)

    def test_wedge_trail_decodes_in_progress(self):
        # reason=none is impossible by construction: the channel arms
        # IN-PROGRESS at entry, so a WDT reset mid-send decodes as
        # in-progress + last_stage (the v35 dump's failure mode).
        blob = build_blob(WEDGE_STAMPS, reason=7)
        decoded = dec.decode(blob)
        self.assertEqual(decoded["reason"], "in-progress")
        self.assertEqual(decoded["slots"][-1]["stage"], "mba-send")
        self.assertEqual(decoded["slots"][-1]["arg"], "0x70ff")
        out = subprocess.run(
            [sys.executable, str(TOOLS / "decode-shim-stamps.py"), "--selftest"],
            capture_output=True, text=True, check=True)
        self.assertIn("PASS decode-shim-stamps selftest", out.stdout)

    def test_v1_backward_compat_real_dump_shape(self):
        blob = build_blob(V1_STAMPS, nonce=0x6dbf3154abd454ef, reason=3,
                          count=8, abi=1)
        decoded = dec.decode(blob)
        self.assertEqual(decoded["abi"], 1)
        self.assertEqual(decoded["reason"], "usb-fatal")
        self.assertEqual(decoded["dropped"], 0)
        self.assertEqual(decoded["slots"][-1]["stage"], "usb-preflight")
        self.assertIsNone(decoded["slots"][-1]["ms_since_entry"])
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "kernel.log"
            dump.write_bytes(blob)
            out = subprocess.run(
                [sys.executable, str(TOOLS / "decode-shim-stamps.py"), str(dump)],
                capture_output=True, text=True, check=True)
            self.assertIn("TSHIMST1 shim stamp history", out.stdout)
            self.assertIn("count=8/8", out.stdout)

    def test_no_trail_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "kernel.log"
            dump.write_bytes(bytes(4 * 1024 * 1024))
            out = subprocess.run(
                [sys.executable, str(TOOLS / "decode-shim-stamps.py"), str(dump)],
                capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("no TSHIMST1/TSHIMST2", out.stderr)

    def test_torn_count_underreads_but_stays_valid(self):
        blob = build_blob(STAMPS, count=8)
        decoded = dec.decode(blob)
        self.assertEqual(len(decoded["slots"]), 8)
        self.assertEqual(decoded["slots"][-1]["seq"], 8)

    def test_reused_nonce_restarts_times_per_boot(self):
        slots = [{"t": 1000, "i": 0}, {"t": 2000, "i": 1}, {"t": 100, "i": 2}, {"t": 400, "i": 3}]
        self.assertEqual(dec.assign_boots(slots), 2)
        self.assertEqual([s["boot"] for s in slots], [1, 1, 2, 2])
        header = {"freq": 1000, "t0": 1000}
        self.assertEqual(dec.delta_ms(header, slots[3]), 300 * 1000.0 / 1000)
        self.assertEqual(dec.delta_ms(header, slots[1]), 1000.0)

    def test_single_boot_keeps_header_origin(self):
        slots = [{"t": 1000}, {"t": 2000}]
        self.assertEqual(dec.assign_boots(slots), 1)
        self.assertEqual(dec.delta_ms({"freq": 1000, "t0": 500}, slots[0]), 500.0)

    def test_fast_start_trail(self):
        decoded = dec.decode(build_blob(FAST_STAMPS, reason=5))
        notes = [x["note"] for x in decoded["slots"]]
        self.assertEqual(decoded["slots"][0]["stage"], "fast-start")
        self.assertEqual(notes[0], "profile: 0xf")
        self.assertEqual(notes[1], "fast window 500 ms + drain 1000 ms")
        self.assertEqual(notes[2], "fast: 500 ms")
        self.assertEqual(notes[4], "fast: 37 ms drained")
        self.assertEqual(notes[5], "fdt-reuse: reused")
        self.assertEqual(notes[6], "cache-on: 55 wb blocks, 0 left device")
        self.assertEqual(notes[7], "cache-off: cached window 84.2 ms")
        self.assertIn("(fast window 500 ms", dec.render(decoded))
        refused = dec.decode(build_blob(FAST_REFUSED, reason=5))
        self.assertEqual([x["note"] for x in refused["slots"]],
                         ["fdt-reuse: size changed, parsed",
                          "cache-on refused: resident input in a cached block, uncached copy"])

    def test_flag_off_windows_keep_their_reading(self):
        decoded = dec.decode(build_blob(SLOW_STAMPS, reason=5))
        self.assertEqual([x["note"] for x in decoded["slots"]], ["8 s window", "", "1 s window", ""])
        self.assertEqual([x["arg"] for x in decoded["slots"]], ["0x8", "0x1", "0x1", "0x1"])

    def test_fast_constants_match_the_shim_header(self):
        h = (TOOLS.parent / "shim" / "tgl_fast_start.h").read_text()
        self.assertIn("#define TGL_STAGE_FAST\t\t0x00f1u", h)
        self.assertIn("UINT64_C(0x4641535400000000)", h)
        self.assertEqual(dec.FAST_USB_TAG, 0x4641535400000000)
        for line, val in (("TGL_FAST_USB_DRAINED\t(UINT64_C(1) << 31)", 1), ("TGL_FAST_USB_STILL\t(UINT64_C(1) << 30)", 1)):
            self.assertIn(line, h)
        self.assertIn("TGL_FAST_S_PROFILE = 1", h)
        self.assertIn("TGL_FAST_S_CACHE_OFF = 4", h)
        self.assertIn("TGL_FAST_C_AVOID = 3", h)
        self.assertIn("TGL_FAST_C_OFF = 6", h)
        self.assertEqual(dec.FAST_CACHE[6], "off at build time")
        self.assertIn("TGL_FAST_FDT_SIZE = 4", h)

    def test_selftest_cli_matches_module(self):
        out = subprocess.run(
            [sys.executable, str(TOOLS / "decode-shim-stamps.py"), "--selftest"],
            capture_output=True, text=True, check=True)
        self.assertIn("PASS decode-shim-stamps selftest", out.stdout)


if __name__ == "__main__":
    unittest.main()
