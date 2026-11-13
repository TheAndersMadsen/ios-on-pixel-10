"""Host tests of hk_score.py and docs/scoreboard.yaml. No device.

Synthetic boots always run. The real-boot cases skip when the 2026-11-04 captures are absent (device dumps stay
out of git): every rung's `sample` boot must match that rung, and no `unverified` rung may match a real boot.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
ATTEMPTS = ROOT / "research/laguna-usb-fix/attempts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hs = load("hk_score", TOOLS / "hk_score.py")
pe = hs.pe
BOARD = hs.load_board()


def mirror_dump(text):
    """4 MiB ramoops image whose pmsg zone holds a valid XNU-MSGBUF v2 mirror of text (as test_probe_eval)."""
    data = bytearray(0x400000)
    raw = text.encode()
    size = 0x10000
    assert len(raw) < size
    hdr = struct.pack("<16sIIQQIIQII", b"XNU-MSGBUF v2".ljust(16, b"\0"), 7, 0, 0xFFFFFE0000001000,
                      0xFFFFFE0000002000, size, len(raw), len(raw), 0, len(raw))
    data[pe.PMSG_OFF + pe.MIRROR_HDR2_OFF:pe.PMSG_OFF + pe.MIRROR_HDR2_OFF + len(hdr)] = hdr
    ring = pe.PMSG_OFF + pe.MIRROR_RING_OFF
    data[ring:ring + len(raw)] = raw
    return bytes(data)


def live_dir(parent, name, lines, markers=(), attempt=None):
    d = Path(parent) / name
    d.mkdir()
    stamp = "03:07:%02d.%03d"
    body = "".join(f"{stamp % (i % 60, i % 1000)} [{i:8.2f}] {l}\n" for i, l in enumerate(lines))
    (d / "console.txt").write_text(body)
    mk = list(markers)
    if attempt:
        mk.insert(0, f"LIVEBOOT 03:06:20.472 +7.5 ATTEMPT_DIR /Users/x/attempts/{attempt}")
    (d / "markers.txt").write_text("".join(m + "\n" for m in mk))
    return d


def attempt_dir(parent, name, msgbuf_text, fresh=True):
    d = Path(parent) / name
    (d / "ramdump").mkdir(parents=True)
    (d / "ramdump" / "kernel.log").write_bytes(mirror_dump(msgbuf_text))
    (d / "reader.txt").write_text(
        f"XNU-MSGBUF mirror: fmt=v2 valid=yes current-fresh={'yes' if fresh else 'no'}\n"
        "  shim: TSHIMST2 nonce=0x1 reason=5 handoff=yes cntfrq=38400000\n")
    return d


def sub(score, sid):
    return next(s for s in score["subsystems"] if s["id"] == sid)


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = hs.main(argv)
    return rc, out.getvalue()


WIFI_LINES = [
    "blazer-wifi: link: UP, attempt 1, 1164 us after LTSSM on: gen 1, x1",
    "blazer-wifi: fw: boot doorbell, mailbox 0x1, 909 ms after release. Android: 912 ms",
    "blazer-wifi: scan: ended, status 0, 6560 ms: 19 results, 18 networks: 10 on 2.4 GHz",
    "blazer-wifi: join: association: status 0, reason 0",
    "blazer-wifi: join: joined in 350 ms",
    "blazer-wifi: net: frames can pass",
    "blazer-wifi: net: address 192.168.1.227, mask 255.255.255.0, gateway 192.168.1.1, lease 86400 s",
]


class BoardTests(unittest.TestCase):
    def test_every_rung_has_sample_xor_unverified(self):
        for s in BOARD["subsystems"]:
            for r in s["rungs"]:
                self.assertTrue(bool(r.get("sample")) != bool(r.get("unverified")), f"{s['id']}.{r['id']}")
                self.assertTrue(r.get("next"), f"{s['id']}.{r['id']} has no next hint")

    def test_bad_board_is_refused(self):
        bad = {"subsystems": [{"id": "x", "rungs": [{"id": "a", "label": "a", "next": "n", "all": [{"re": "("}],
                                                     "sample": "b"}]}]}
        with self.assertRaises(ValueError):
            hs.validate_board(bad)
        both = {"subsystems": [{"id": "x", "rungs": [{"id": "a", "label": "a", "next": "n", "all": [{"re": "a"}]}]}]}
        with self.assertRaises(ValueError):
            hs.validate_board(both)

    def test_required_subsystems(self):
        ids = {s["id"] for s in BOARD["subsystems"]}
        for want in ("boot", "display", "input", "storage", "cpu", "battery", "gpu", "wifi", "bluetooth",
                     "cellular", "sensors", "audio", "nfc", "cameras", "apps", "stability"):
            self.assertIn(want, ids)


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def score(self, path):
        return hs.score_boot(hs.boot_from_path(path), BOARD)

    def test_wifi_ladder_and_next(self):
        d = live_dir(self.dir, "live-20261104-030612-a7-w", WIFI_LINES)
        w = sub(self.score(d), "wifi")
        self.assertEqual(w["level"], 7)
        self.assertEqual(w["best_id"], "dhcp")
        self.assertEqual(w["first_missing"], "traffic")
        self.assertIn("rx/tx", w["next"])
        self.assertTrue(w["best_time"].startswith("k="), w["best_time"])
        self.assertIn("192.168.1.227", w["best_evidence"])

    def test_higher_rung_implies_lower(self):
        d = live_dir(self.dir, "live-20261104-030612-a7-w", [WIFI_LINES[-1]])
        w = sub(self.score(d), "wifi")
        self.assertEqual(w["level"], 7)
        self.assertEqual([r["state"] for r in w["rungs"][:7]], ["implied"] * 6 + ["reached"])

    def test_independent_rung_implies_nothing(self):
        d = live_dir(self.dir, "live-20261104-030612-a7-b", ["exec bluetoothd"])
        b = sub(self.score(d), "bluetooth")
        self.assertEqual(b["best_id"], "bluetoothd")
        self.assertEqual(b["level"], 0)
        self.assertEqual(b["first_missing"], "enabled")

    def test_app_walk_counts_different_apps(self):
        respawns = live_dir(self.dir, "live-20261104-040000-a7-r", ["exec Photos"] * 6 + ["exec Maps", "exec Music", "exec MobileCal"])
        self.assertNotIn("app-walk", [r["id"] for r in sub(self.score(respawns), "apps")["rungs"] if r["state"] == "reached"])
        names = ["MobileNotes", "MobileTimer", "MobileCal", "Photos", "Maps", "MobileSafari", "Health", "Music"]
        walk = live_dir(self.dir, "live-20261104-050000-a7-k", [f"exec {n}" for n in names])
        self.assertIn("app-walk", [r["id"] for r in sub(self.score(walk), "apps")["rungs"] if r["state"] == "reached"])

    def test_gated_negative_rungs_need_the_rung_below(self):
        d = live_dir(self.dir, "live-20261104-030612-a7-e", ["nothing to see"])
        st = sub(self.score(d), "stability")
        self.assertEqual(st["level"], 0)
        self.assertFalse(any(r["state"] == "reached" for r in st["rungs"]))

    def test_metrics_respawn_and_panic(self):
        lines = ["HKOBS 88 tick t=888 proc: SpringBoard 1/0 - l7655 d61 bluetoothd 25/24 e1 l3838 d0 lsd 1/0 -",
                 "CRASH Preferences reason ns 2 code 0x6: (none)"]
        d = live_dir(self.dir, "live-20261104-030612-a7-m", lines)
        sc = self.score(d)
        self.assertEqual(sc["metrics"]["respawn_max"], 25)
        self.assertEqual(sc["metric_detail"]["respawns"], {"bluetoothd": 25})
        self.assertEqual(sc["metrics"]["crashes"], 1)
        st = sub(sc, "stability")
        self.assertEqual(st["first_missing"], "ran-900")              # HKOBS t=888
        self.assertEqual(sub(sc, "apps")["rungs"][0]["state"], "reached")   # lsd from the HKOBS proc line

    def test_ramdump_stamps_and_pairing(self):
        text = "HKOBS 1 tick t=60 usb: running\nblazer-sensors: compass 0: 1 -2 3 nT\n" \
               "blazer-sensors: compass 1: 1 -2 3 nT\nblazer-root: deadline 900 s, stage pid1_exec\n"
        attempt_dir(self.dir, "20261104-095002-a7-x", text)
        live = live_dir(self.dir, "live-20261104-094950-a7-x", ["blazer-sensors: aoc domain 2 (2 on)"])
        att, lv = hs.pair(self.dir / "20261104-095002-a7-x")
        self.assertEqual(lv, live)                                   # name + time heuristic
        sc = self.score(self.dir / "20261104-095002-a7-x")
        self.assertEqual(sc["boot"], "20261104-095002-a7-x")
        se = sub(sc, "sensors")
        self.assertEqual(se["best_id"], "compass")
        self.assertEqual(se["best_time"], "t>=60s")
        self.assertEqual(se["rungs"][0]["state"], "reached")           # from the paired live console
        self.assertEqual(sc["metrics"]["uptime_s"], 900)
        self.assertEqual(sub(sc, "cpu")["rungs"][5]["state"], "reached")

    def test_pairing_by_marker(self):
        attempt_dir(self.dir, "20261104-030620-a7-w", "x\n")
        live = live_dir(self.dir, "live-20261104-030612-a7-w", [], attempt="20261104-030620-a7-w")
        self.assertEqual(hs.pair(live), (self.dir / "20261104-030620-a7-w", live))
        self.assertEqual(hs.pair(self.dir / "20261104-030620-a7-w")[1], live)

    def test_stale_mirror_is_ignored(self):
        attempt_dir(self.dir, "20261104-095002-a7-s", "blazer-wifi: net: address 10.0.0.2\n", fresh=False)
        w = sub(self.score(self.dir / "20261104-095002-a7-s"), "wifi")
        self.assertFalse(w["exercised"])

    def test_diff_baseline_exit_codes(self):
        old = live_dir(self.dir, "live-20261104-010000-a7-o", WIFI_LINES)
        new = live_dir(self.dir, "live-20261104-020000-a7-n", WIFI_LINES[:3])
        rc, out = run_main([str(new), "--baseline", str(old)])
        self.assertEqual(rc, 1)
        self.assertIn("REGRESSION", out)
        rc, out = run_main([str(old), "--diff", str(new)])
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"wifi .* progress")
        js = self.dir / "base.json"
        rc, out = run_main([str(new), "--json"])
        js.write_text(out)
        rc, _ = run_main([str(old), "--baseline", str(js)])
        self.assertEqual(rc, 0)

    def test_lost_subsystem_only_fails_strict(self):
        old = live_dir(self.dir, "live-20261104-010000-a7-o", ["blazer-sensors: compass 0: 1 2 3 nT"] * 2)
        new = live_dir(self.dir, "live-20261104-020000-a7-n", ["nothing"])
        self.assertEqual(run_main([str(new), "--baseline", str(old)])[0], 0)
        self.assertEqual(run_main([str(new), "--baseline", str(old), "--strict"])[0], 1)

    def test_md_json_and_table_render(self):
        d = live_dir(self.dir, "live-20261104-030612-a7-w", WIFI_LINES,
                     markers=["UIRUN 03:07:31.508 +78.5 HOME console conditions met (touch, buttons, SpringBoard, frames)"])
        rc, md = run_main([str(d), "--md"])
        self.assertEqual(rc, 0)
        wifi_rungs = len(next(s for s in BOARD["subsystems"] if s["id"] == "wifi")["rungs"])
        self.assertIn(f"| Wi-Fi (BCM4390) | 7/{wifi_rungs} |", md)
        self.assertIn("## Boot timeline", md)
        rc, js = run_main([str(d), "--json"])
        doc = json.loads(js)
        self.assertEqual(sub(doc, "boot")["best_id"], "home")
        self.assertEqual(sub(doc, "boot")["rungs"][6]["time"], "03:07:31 +78s")
        rc, table = run_main([str(d)])
        self.assertIn("wifi", table)
        self.assertEqual(run_main([str(self.dir / "missing")])[0], 2)

    def test_best_aggregates_across_boots(self):
        a = live_dir(self.dir, "live-20261104-010000-a7-a", WIFI_LINES[:2])
        b = live_dir(self.dir, "live-20261104-020000-a7-b", ["exec bluetoothd"])
        scores = [hs.score_boot(hs.Boot(None, a), BOARD), hs.score_boot(hs.Boot(None, b), BOARD)]
        subs = hs.aggregate(scores, BOARD)
        w = next(s for s in subs if s["id"] == "wifi")
        self.assertEqual(w["level"], 2)
        self.assertEqual(w["rungs"][1]["boot"], "live-20261104-010000-a7-a")
        acts = hs.top_actions(subs)
        self.assertTrue(acts and acts[0]["unblocks"] >= acts[-1]["unblocks"])
        md = hs.render_best_md(subs, acts, "2 boots", scores)
        self.assertIn("## Level per boot", md)


@unittest.skipUnless((ATTEMPTS / "20261104-095002-a7-int5-r3").is_dir(), "real 2026-11-04 attempts absent")
class RealBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.boots = {}
        for att, live in hs.list_boots(ATTEMPTS, "20261102"):
            b = hs.Boot(att, live)
            for part in [att, live]:
                if part is not None:
                    cls.boots[part.name] = b

    def test_samples_match_their_rung(self):
        for s in BOARD["subsystems"]:
            for r in s["rungs"]:
                if r.get("sample"):
                    b = self.boots.get(r["sample"])
                    self.assertIsNotNone(b, f"{s['id']}.{r['id']}: sample {r['sample']} not found")
                    self.assertTrue(hs.eval_spec(r, b)[0], f"{s['id']}.{r['id']} does not match {r['sample']}")

    def test_unverified_rungs_match_no_real_boot(self):
        seen = {id(b): b for b in self.boots.values()}
        for s in BOARD["subsystems"]:
            for r in s["rungs"]:
                if r.get("unverified"):
                    for b in seen.values():
                        self.assertFalse(hs.eval_spec(r, b)[0], f"{s['id']}.{r['id']} matches {b.name}: add a sample")

    def test_int5_r3_and_wifi_w2(self):
        sc = hs.score_boot(self.boots["20261104-095002-a7-int5-r3"], BOARD)
        self.assertGreaterEqual(sub(sc, "boot")["level"], 7)
        self.assertEqual(sub(sc, "stability")["first_missing"], "no-respawn-loop")    # bluetoothd 26 execs
        w = sub(hs.score_boot(self.boots["live-20261104-030612-a7-wifi-w2-r1"], BOARD), "wifi")
        self.assertEqual(w["best_id"], "traffic")


if __name__ == "__main__":
    unittest.main()
