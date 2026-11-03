"""Host tests of probe_eval.py and docs/probes.yaml. No device.

Synthetic attempts always run. The real-attempt case skips when the 2026-11-03
captures are absent, because device dumps stay out of git.
"""
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
ATTEMPTS = ROOT / "research/laguna-usb-fix/attempts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pe = load("probe_eval", TOOLS / "probe_eval.py")


def mirror_dump(text, magic=b"XNU-MSGBUF v2"):
    """4 MiB ramoops image whose pmsg zone holds a valid XNU-MSGBUF v2 mirror of text."""
    data = bytearray(0x400000)
    raw = text.encode()
    size = 0x10000
    assert len(raw) < size
    hdr = struct.pack("<16sIIQQIIQII", magic.ljust(16, b"\0"), 7, 0, 0xFFFFFE0000001000,
                      0xFFFFFE0000002000, size, len(raw), len(raw), 0, len(raw))
    data[pe.PMSG_OFF + pe.MIRROR_HDR2_OFF:pe.PMSG_OFF + pe.MIRROR_HDR2_OFF + len(hdr)] = hdr
    ring = pe.PMSG_OFF + pe.MIRROR_RING_OFF
    data[ring:ring + len(raw)] = raw
    return bytes(data)


def png(width, height, value):
    rows = b"".join(b"\0" + bytes([value]) * (3 * width) for _ in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


PWR_LOG = """\
SWEET CPU: 5/5 CPUs initialized, SGI1 verified
com.apple.xpc.launchd|2026-11-03 19:55:53.174321 <Notice>: boot-args = debug=0x8 cpus=5 rd=ufsroot0 blazer_deadline=900
blazer-keys: legacy mode
blazer-keys: volume down pressed
SWEET PHYSICAL: epoch=3 key=2 usage=0xea down clients=1 callback
blazer-keys: volume up pressed
SWEET PHYSICAL: epoch=3 key=1 usage=0xe9 down clients=1 callback
blazer-power-key: pressed
SWEET PHYSICAL: epoch=3 key=0 usage=0x30 down clients=1 callback
SWEET FB: display off
blazer-power-key: pressed
SWEET FB: display on
blazer-battery: sample 1 SOC(95), VCELL(4385), INOW(-21), IAVG(-20), TEMP(3231), raw soc 5f24
HKBATT: event=powerd_percent_post pid=40 rc=0
HKBATT: event=battery_view_set pid=5 role=2 now_ns=1 view=0x1 ui_scope=unproved value=0.95 notify_rc=0 state=0x9005f percent=95
blazer-wifi: chip: ARM control 0x21: halted, as Android finds it
blazer-wifi: scan: ended, status 0, 6563 ms: 32 results, 26 networks: 13 on 2.4 GHz, 12 on 5 GHz
blazer-wifi: join: association: status 0, reason 0
blazer-wifi: join: the 4-way handshake failed: status 4, reason 14: the firmware never answered M1
panic(cpu 0 caller 0xfffffe00079fe060): blazer-root: deadline 900 s, stage pid1_exec, 52810 reads
"""


def make_attempt(base, name, text, fresh="yes", extra=None):
    d = Path(base) / name
    (d / "ramdump").mkdir(parents=True)
    (d / "ramdump" / "kernel.log").write_bytes(mirror_dump(text))
    if fresh is not None:
        (d / "reader.txt").write_text(f"XNU-MSGBUF mirror: fmt=v2 valid=yes current-fresh={fresh}\n")
    (d / "boot.log").write_text("Booting                                            OKAY [  0.006s]\n")
    for rel, body in (extra or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body) if isinstance(body, bytes) else p.write_text(body)
    return d


def by_id(rows):
    return {r["id"]: r for r in rows}


class YamlSubset(unittest.TestCase):
    def test_constructs(self):
        doc = pe.yaml_subset_load(
            "# head\na: 1\nb: 'it''s # not a comment'  # real comment\nc:\n  - x\n  - {re: 'p\\d+', min: 0, l: [a, 'b c']}\n"
            "  - id: q\n    n: null\n    t: true\nd: \"q\\\"x\"\n")
        self.assertEqual(doc, {"a": 1, "b": "it's # not a comment",
                               "c": ["x", {"re": "p\\d+", "min": 0, "l": ["a", "b c"]}, {"id": "q", "n": None, "t": True}],
                               "d": 'q"x'})

    def test_errors(self):
        with self.assertRaises(pe.YamlError):
            pe.yaml_subset_load("a: 'open\n")
        with self.assertRaises(pe.YamlError):
            pe.yaml_subset_load("a: 1\n   b: 2\n")

    def test_probes_file_matches_pyyaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        text = pe.PROBES.read_text()
        self.assertEqual(pe.yaml_subset_load(text), yaml.safe_load(text))


class ProbesFile(unittest.TestCase):
    def setUp(self):
        self.doc = pe.load_probes()

    def test_one_probe_per_readme_row(self):
        status = json.loads((ROOT / "docs/status.json").read_text())
        rows = [f[0] for b in status["blocks"] for f in b["features"]]
        probes = [p["row"] for p in self.doc["probes"] if not p.get("milestone")]
        self.assertEqual(sorted(rows), sorted(probes))
        self.assertEqual(len(probes), len(set(probes)))

    def test_every_probe_has_phone_only_owner_and_next(self):
        for p in self.doc["probes"]:
            self.assertIsInstance(p["phone_only"], bool, p["id"])
            self.assertTrue(p.get("owner"), p["id"])
            self.assertIn(p["next"]["kind"], pe.NEXT_KIND, p["id"])

    def test_validation_rejects_bad_probes(self):
        good = {"id": "x", "row": "X", "phone_only": True, "works": {"all": [{"re": "a"}]}}
        pe.validate_probes({"probes": [dict(good)]})
        for bad in ({**good, "phone_only": "yes"}, {**good, "works": {"all": [{"re": "("}]}},
                    {**good, "works": {"all": [{"re": "a", "group": "g", "ge": 1}]}},
                    {**good, "works": {"all": [{"re": "a"}], "confirm": "maybe"}}):
            with self.assertRaises(ValueError):
                pe.validate_probes({"probes": [bad]})
        with self.assertRaises(ValueError):
            pe.validate_probes({"probes": [dict(good), dict(good)]})


class Evaluate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.none = self.base / "no-confirmations.txt"
        self.none.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def run_eval(self, paths, **kw):
        kw.setdefault("confirm_files", [str(self.none)])
        return by_id(pe.evaluate([str(p) for p in paths], **kw))

    def test_mirror_decode(self):
        text, why = pe.decode_mirror(mirror_dump("hello\nworld\n"))
        self.assertEqual((text, why), ("hello\nworld\n", None))
        self.assertEqual(pe.decode_mirror(bytes(0x400000))[0], None)
        bad = bytearray(mirror_dump("abc\n"))
        struct.pack_into("<I", bad, pe.PMSG_OFF + pe.MIRROR_HDR2_OFF + 16, 0)  # seq 0
        self.assertEqual(pe.decode_mirror(bytes(bad)), (None, "XNU-MSGBUF v2 header invalid"))

    def test_keys_power_wifi_battery(self):
        a = make_attempt(self.base, "20261103-201639-a7-ios-system-pwr1", PWR_LOG)
        rows = self.run_eval([a])
        self.assertEqual(rows["volume-keys"]["verdict"], "works")
        self.assertEqual(rows["power-key"]["verdict"], "works")
        self.assertEqual(rows["a725-cores"]["verdict"], "works")
        wifi = rows["wifi"]
        self.assertEqual(wifi["verdict"], "partial")
        self.assertIn("26 networks", wifi["note"])
        self.assertEqual([f["label"] for f in wifi["fails"]], ["4-way handshake failed"])
        cite = wifi["evidence"][0]["cites"][0]
        self.assertRegex(cite, r"kernel\.log#msgbuf:17: blazer-wifi: scan: ended")
        # Battery view value set reaches works only with a confirmation.
        bat = rows["battery"]
        self.assertEqual((bat["verdict"], bat["pending_confirm"]), ("partial", "works"))
        (a / "confirm.txt").write_text(f"{a.name} battery works screenshot: 95% in the status bar\n")
        bat = self.run_eval([a])["battery"]
        self.assertEqual(bat["verdict"], "works")
        self.assertIn("95% set on the SpringBoard battery view", bat["note"])

    def test_cited_lines_match_grep(self):
        # \x1c and U+2028 in log noise must not shift line numbers (str.splitlines would).
        log = "noise \x1c here\nmore \u2028 noise\n" + PWR_LOG
        a = make_attempt(self.base, "lines", log, extra={"live.log": "x\x0by\nblazer-keys: volume up pressed\n"})
        cite = self.run_eval([a], rows=["wifi"])["wifi"]["evidence"][0]["cites"][0]
        self.assertRegex(cite, r"#msgbuf:19: blazer-wifi: scan: ended")
        rows = by_id(pe.evaluate([str(a / "live.log")], rows=["volume-keys"], confirm_files=[str(self.none)]))
        self.assertRegex(rows["volume-keys"]["evidence"][0]["cites"][0], r"live\.log:2: ")

    def test_power_key_needs_order(self):
        log = PWR_LOG.replace("SWEET FB: display off\n", "").replace("SWEET FB: display on\n", "SWEET FB: display on\nSWEET FB: display off\n")
        a = make_attempt(self.base, "x-order", log)
        self.assertEqual(self.run_eval([a], rows=["power-key"])["power-key"]["verdict"], "partial")

    def test_stale_or_unverified_mirror_is_ignored(self):
        stale = make_attempt(self.base, "a-stale", PWR_LOG, fresh="no")
        unver = make_attempt(self.base, "b-unverified", PWR_LOG, fresh=None)
        rows = self.run_eval([stale, unver], rows=["volume-keys"])
        self.assertEqual(rows["volume-keys"]["exercised_in"], [])
        rows = self.run_eval([unver], rows=["volume-keys"], trust_unverified=True)
        self.assertEqual(rows["volume-keys"]["verdict"], "works")

    def test_live_console_and_milestones(self):
        live = self.base / "live-20261103-213954-a7-int1-live"
        live.mkdir()
        lines = ["21:40:36.774 usbcon: connected: nonce 0x8bc64d7181cbb83c"]
        lines += [f"21:40:3{i % 10}.000 [    {i}.00] filler {i}" for i in range(1000)]
        lines += ["21:40:38.740 [    1.99] exec SpringBoard",
                  "21:40:40.678 [    3.93] HKBATT: event=battery_view_installed pid=28",
                  "21:40:41.388 [    4.64] SWEET HID: SweetHIDTouch open by IOHIDEventServiceUserClient -> 1",
                  "21:40:41.388 [    4.64] SWEET HID: SweetHIDButtons open by IOHIDEventServiceUserClient -> 1",
                  "21:41:09.163 [   32.41] SWEET FB: rate swaps 16.0/s kicks 16.0/s max_gap_us 3930230",
                  "21:41:04.563 [   27.81] ERROR: [MessagesBlastDoorService:156] EXC_GUARD AST: type=0x1",
                  "21:41:04.717 [   27.97] CRASH MessagesBlastDoo reason ns 2 code 0x5: (none)",
                  "21:41:09.768 [   32.99] CRASH AccessibilityUIS reason ns 2 code 0x6: (none)"]
        (live / "console.txt").write_text("\n".join(lines) + "\n")
        rows = self.run_eval([live])
        self.assertEqual(rows["live-console"]["verdict"], "works")
        home = rows["home"]
        self.assertTrue(home["milestone"])
        self.assertEqual(home["verdict"], "works")  # no SPRINGBOARD line: the battery-view fallback carries it
        labels = [e["label"] for e in home["evidence"]]
        self.assertIn("fallback: SpringBoard status-bar battery view installed", labels)
        self.assertIsNone(rows["app-blastdoor"]["verdict"])
        self.assertEqual(len(rows["app-blastdoor"]["fails"]), 2)
        self.assertTrue(rows["app-accessibility-ui"]["fails"])
        # A SpringBoard crash takes Home away.
        (live / "console.txt").write_text("\n".join(lines + ["21:42:00.000 [   80.00] CRASH SpringBoard reason ns 2 code 0x6"]) + "\n")
        self.assertEqual(self.run_eval([live], rows=["home"])["home"]["verdict"], "partial")

    def test_qemu_filter_and_row_selection(self):
        a = make_attempt(self.base, "q", PWR_LOG)
        rows = pe.evaluate([str(a)], qemu=True, confirm_files=[str(self.none)])
        self.assertTrue(rows)
        self.assertFalse(any(r["phone_only"] for r in rows))
        self.assertIn("home", {r["id"] for r in rows})
        rows = pe.evaluate([str(a)], rows=["wifi", "Volume keys"], confirm_files=[str(self.none)])
        self.assertEqual({r["id"] for r in rows}, {"wifi", "volume-keys"})
        with self.assertRaises(ValueError):
            pe.evaluate([str(a)], rows=["no-such-row"])
        json.dumps(rows)  # JSON-ready

    def test_screenshot_luma(self):
        a = make_attempt(self.base, "s", PWR_LOG, extra={"screen.png": png(4, 3, 200)})
        self.assertAlmostEqual(pe.png_mean_luma(a / "screen.png"), 200, delta=1)
        (self.base / "black.png").write_bytes(png(2, 2, 0))
        self.assertEqual(pe.png_mean_luma(self.base / "black.png"), 0)
        shot = self.run_eval([a], rows=["battery"])["battery"]["screens"][0]
        self.assertTrue(shot["nonblack"])
        self.assertFalse(shot["content_checked"])


class Status(unittest.TestCase):
    def status(self, **rows):
        feats = [[name, st, "note"] for name, st in rows.items()]
        return {"scores": {"works": 100, "partial": 60, "built": 35, "active": 20, "open": 0, "out": None},
                "blocks": [{"name": "B", "features": feats}]}

    def row(self, row, verdict, pending=None, ran=True, levels=True):
        return {"row": row, "id": row.lower(), "verdict": verdict, "pending_confirm": pending,
                "attempt": "a" if verdict else None, "note": f"{row} note", "exercised_in": ["a"] if ran else [],
                "has_levels": levels, "milestone": False, "next": {"kind": "unattended", "minutes": 10, "test": "t"}}

    def test_compare_kinds_never_demote(self):
        st = self.status(Up="partial", Same="works", Down="works", Conf="partial", Idle="active", Out="out")
        rows = [self.row("Up", "works"), self.row("Same", "works"), self.row("Down", "partial"),
                self.row("Conf", "partial", pending="works"), self.row("Idle", None, ran=False),
                self.row("Out", "partial")]
        kinds = {c["row"]: c["kind"] for c in pe.compare(rows, st)}
        self.assertEqual(kinds, {"Up": "promote", "Same": "agree", "Down": "unsupported-here",
                                 "Conf": "needs-confirmation", "Idle": "not-exercised", "Out": "out"})
        changed = pe.apply_status(st, pe.compare(rows, st))
        self.assertEqual([(o[1], n[1], n[2]) for o, n in changed], [("partial", "works", "Up note")])
        self.assertEqual(st["blocks"][0]["features"][2][1], "works")  # Down untouched

    def test_queue_order(self):
        st = self.status(A="partial", B="partial", C="works", D="open")
        rows = [self.row("A", "partial"), self.row("B", "partial"), self.row("C", "works"), self.row("D", None)]
        rows[0]["next"] = {"kind": "build", "minutes": 5, "test": "build"}
        rows[1]["next"] = {"kind": "unattended", "minutes": 30, "test": "boot"}
        rows[3]["next"] = {"kind": "none", "minutes": 0, "test": "-"}
        self.assertEqual([q["row"] for q in pe.queue(rows, st)], ["B", "A", "C", "D"])


class Cli(unittest.TestCase):
    def test_propose_does_not_write_unless_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = make_attempt(tmp, "20261103-pwr", PWR_LOG)
            status = Path(tmp) / "status.json"
            st = {"scores": {"works": 100, "partial": 60, "built": 35, "active": 20, "open": 0, "out": None},
                  "blocks": [{"name": "Input", "features": [["Volume keys", "partial", "old"], ["Power key", "active", "old"]]}]}
            status.write_text(json.dumps(st))
            before = status.read_text()
            cmd = [sys.executable, "-I", str(TOOLS / "probe_eval.py"), "--status", str(status),
                   "--confirm", str(Path(tmp) / "none.txt"), "--row", "volume-keys", "--row", "power-key"]
            out = subprocess.run(cmd + ["--propose-status", str(a)], capture_output=True, text=True, check=True).stdout
            self.assertIn("proposed: partial -> works", out)
            self.assertEqual(status.read_text(), before)
            js = json.loads(subprocess.run(cmd + ["--propose-status", "--json", str(a)],
                                           capture_output=True, text=True, check=True).stdout)
            self.assertEqual({c["row"]: c["kind"] for c in js["comparisons"]}, {"Volume keys": "promote", "Power key": "promote"})
            subprocess.run(cmd + ["--propose-status", "--apply", str(a)], capture_output=True, text=True, check=True)
            after = json.loads(status.read_text())
            self.assertEqual([f[1] for f in after["blocks"][0]["features"]], ["works", "works"])
            self.assertIn("usage 0xe9/0xea", after["blocks"][0]["features"][0][2])

    def test_missing_input_exit_2(self):
        r = subprocess.run([sys.executable, "-I", str(TOOLS / "probe_eval.py"), "/nonexistent/attempt"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class RealAttempts(unittest.TestCase):
    PWR1 = ATTEMPTS / "20261103-201639-a7-ios-system-pwr1"

    def test_pwr1(self):
        if not (self.PWR1 / "ramdump/kernel.log").is_file():
            self.skipTest("capture absent (device dumps stay out of git)")
        rows = by_id(pe.evaluate([str(self.PWR1)], rows=["volume-keys", "power-key", "wifi", "brightness"]))
        self.assertEqual(rows["volume-keys"]["verdict"], "works")
        self.assertEqual(rows["power-key"]["verdict"], "works")
        # pwr1's slider requests were all "(queue only)": the log alone does not reach works.
        self.assertEqual(rows["brightness"]["verdict"], "partial")


if __name__ == "__main__":
    out = io.StringIO()
    unittest.main(verbosity=1)
