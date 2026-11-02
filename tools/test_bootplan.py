#!/usr/bin/env python3
"""Tests for bootplan.py. Host only. Real captures from research/laguna-usb-fix/attempts, read only, plus synthetic facts
for branches no recorded boot took. Logs go to a temporary folder.
  python3 -I tools/test_bootplan.py
release.md is live and other agents edit it, so order and command tests use a frozen copy of its table."""
import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bootplan", HERE / "bootplan.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)
ATT = bp.ROOT / bp.ATTEMPTS
FIXTURE = HERE / "bootplan_release_fixture.md"
RELEASE = bp.parse_release(FIXTURE)
RECORDED = {  # attempt: (grade, signature)
    "20261101-234344-phone-root-r1": ("PENDING-OWNER", "DEADLINE"),
    "20261102-002034-phone-touch-r2": ("FAIL", "READ_FAILED"),
    "20261101-233231-soak-p2-r1": ("FAIL", "SGI_ASSERT"),
    "20261102-003649-clk-probe-r1": ("PASS", "PROBE_DONE"),
    "20261102-004155-speed-probe-r3": ("PASS", "PROBE_DONE"),
    "20261102-004645-keys-probe-r1": ("PARTIAL", "PROBE_DONE"),
    "20261102-005130-wifi-stage1-r1": ("PASS", "PROBE_DONE"),
}
CACHE = {}


def facts_of(attempt):
    if attempt not in CACHE:
        CACHE[attempt] = bp.gather(ATT / attempt, bp.kind_of(bp.base_name(attempt)))
    return CACHE[attempt]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = bp.main(["--release", str(FIXTURE), *argv])
    return rc, out.getvalue()


def synth(kind="ui", cls="PSCI-SW", panic=None, symbol=None, line=None, entered=True, not_entered=None, user=None, log="", mach="kernel.ios26-p11.unstripped", **extra):
    x = {"bound": True, "panic": {"message": panic, "symbol": symbol} if panic else None, "furthest": "display on", "userland": user or {}, "stages": []}
    facts = {"attempt": "20261102-100000-phone-full-p12-r1", "name": "phone-full-p12-r1", "kind": kind, "captured": True, "parked": True,
             "kernel_num": bp.kernel_number(mach), "line": line, "deadline": None, "log": log, "stamps": "", "ras_lines": 0, "thermal": "0x0", "probe": None,
             "reset": {"class": cls, "xnu_s": 100.0, "rtc_gap": 14.0, "soc": 89.0, "iavg": 40.0},
             "summary": {"image_same": True, "not_entered": not_entered, "xnu12377": x if entered else None}}
    facts.update(extra)
    return facts


ALL_ON = " ".join(row["token"] for row in RELEASE["rows"])
MULTI, HOLD, SPIN, BOOTCPU, CPUS, VALID = "blazer_ufs_multi=1", "blazer_ufs_hold=1", "blazer_ufs_spin_us=300", "blazer_bootcpu=0x200", "cpus=5", "validation_disables=0x39d64"
NO_SMP = " ".join(token for token in ALL_ON.split() if token not in (CPUS, "blazer_smp_test=1", "blazer_fast_first=1"))
BOOTED = "SWEET CPU: boot core mpidr=0x200\n"
UI = dict(swaps_at_least=20, springboard_execs=1, backboardd_execs=1)


class Recorded(unittest.TestCase):
    def test_each_recorded_attempt(self):
        for attempt, (grade, sig) in RECORDED.items():
            with self.subTest(attempt):
                result = bp.decide(facts_of(attempt), RELEASE)
                self.assertEqual((result["grade"], result["signature"]), (grade, sig), result["why"])

    def test_phone_root_passes_with_the_owner(self):
        facts = facts_of("20261101-234344-phone-root-r1")
        result = bp.decide(facts, RELEASE, owner_saw="home screen")
        self.assertEqual(result["grade"], "PASS")
        self.assertEqual(facts["deadline_check"][0], 0, "classify_reset's ten checks passed on this run")
        self.assertIn("swaps at least 15", result["why"])

    def test_old_kernels_are_known_fixes_not_rows(self):
        touch = bp.decide(facts_of("20261102-002034-phone-touch-r2"), RELEASE)
        self.assertIsNone(touch["row"])
        self.assertIn("0714", touch["do"])
        soak = bp.decide(facts_of("20261101-233231-soak-p2-r1"), RELEASE)
        self.assertIn("0532", soak["do"])

    def test_wifi_residue_is_not_this_boots_panic(self):
        """kernel.log's raw bytes hold another boot's READ failed. It must not be this boot's verdict."""
        raw = (ATT / "20261102-005130-wifi-stage1-r1/ramdump/kernel.log").read_bytes()
        self.assertIn(b"READ failed", raw)
        facts = facts_of("20261102-005130-wifi-stage1-r1")
        self.assertNotIn("READ failed", facts["log"])
        result = bp.decide(facts, RELEASE)
        self.assertIn("14e4:4438", result["why"])

    def test_probes_arent_called_no_entry(self):
        for attempt in ("20261102-003649-clk-probe-r1", "20261102-004155-speed-probe-r3", "20261102-004645-keys-probe-r1"):
            self.assertTrue(facts_of(attempt)["summary"]["not_entered"])
            self.assertNotEqual(bp.decide(facts_of(attempt), RELEASE)["signature"], "NO_XNU_ENTRY")

    def test_no_recorded_ui_attempt_shows_ras(self):
        for attempt in RECORDED:
            self.assertEqual(facts_of(attempt)["ras_lines"], 0)

    def test_real_ras_capture_stops(self):
        result = bp.decide(bp.gather(ATT / "20261101-213232-ssi-id-r1", "ui"), RELEASE)
        self.assertEqual((result["grade"], result["signature"], result["scope"]), ("STOP", "RAS", "all"))

    def test_real_ras_on_a_vote_boot_stops_vote_work_only(self):
        facts = bp.gather(ATT / "20261101-213232-ssi-id-r1", "vote-read")
        self.assertEqual(bp.decide(facts, RELEASE)["scope"], "vote")

    def test_real_long_press_is_a_hang_candidate(self):
        result = bp.decide(bp.gather(ATT / "20261101-203354-ufs-ui-r1", "soak"), RELEASE)
        self.assertEqual(result["signature"], "HUNG")

    def test_real_fullcheck_as_cpu0_check_passes_with_cpu0_speed(self):
        attempt = "20261101-233933-fullcheck-r3b-after"
        result = bp.decide(bp.gather(ATT / attempt, "fullcheck"), RELEASE)
        self.assertEqual(result["grade"], "PASS")
        speed = next(line for line in result["cautions"] if line.startswith("CRC speed"))
        self.assertAlmostEqual(float(re.search(r"([\d.]+) ns", speed).group(1)), 13.7, delta=0.1)

    def test_real_fullcheck_read_as_fastcore_fails_on_the_core_lines(self):
        """Ran on cpu0: the fast-core lines must be missing, the CRC still good."""
        result = bp.decide(bp.gather(ATT / "20261101-233933-fullcheck-r3b-after", "fastcore"), RELEASE)
        self.assertEqual(result["grade"], "FAIL")
        self.assertIn("boot core 0x200", result["why"])
        self.assertNotIn("crc", result["why"])


class NewCaptures(unittest.TestCase):
    def test_p11_cpu0_control_holds_older_panics_as_residue(self):
        """Log RAM holds READ failed and deadline panics of earlier boots. Only the reader's current-boot verdict counts."""
        attempt = "20261102-012714-p11-check-cpu0-r1"
        raw = (ATT / attempt / "ramdump/kernel.log").read_bytes()
        self.assertTrue(b"READ failed" in raw or b"blazer-root: deadline" in raw, "the residue this test is about")
        facts = bp.gather(ATT / attempt, "fullcheck")
        self.assertIn("initproc failed", facts["summary"]["xnu12377"]["panic"]["message"])
        self.assertNotIn("READ failed", facts["log"])
        self.assertNotIn("blazer-root: deadline", facts["log"])
        result = bp.decide(facts, RELEASE)
        self.assertEqual((result["grade"], result["signature"]), ("PASS", "INITPROC"))

    def test_p11_cpu0_control_on_a_real_capture(self):
        attempt = "20261102-012714-p11-check-cpu0-r1"
        self.assertEqual(bp.boot_for(bp.base_name(attempt))["id"], "p11-check-cpu0-r1")
        result = bp.decide(bp.gather(ATT / attempt, "fullcheck"), RELEASE)
        self.assertEqual(result["grade"], "PASS", result["why"])
        self.assertTrue(any(line.startswith("CRC speed") for line in result["cautions"]))


    def test_fast_core_on_a_real_capture(self):
        result = bp.decide(bp.gather(ATT / "20261102-013105-fastcore-check-r1", "fastcore"), RELEASE)
        self.assertEqual(result["grade"], "PASS", result["why"])
        self.assertEqual(len(result["checks"]), 9)
        speed = next(line for line in result["cautions"] if line.startswith("CRC speed"))
        self.assertIn("13.48 ns", speed)

    def test_vote_read_on_a_real_capture_clears_vote_write_r2(self):
        """d1 read 20. r1 expected 21 and is void; r2 expects 20, so nothing is held."""
        result = bp.decide(bp.gather(ATT / "20261102-013509-vote-read-r1", "vote-read"), RELEASE)
        self.assertEqual(result["grade"], "PASS", result["why"])
        self.assertFalse(result.get("holds"))
        self.assertNotIn("Rebuild", result["why"])

    def test_vote_read_with_another_value_holds_vote_write(self):
        probe = dict(verdict="READ_CLEAN", doc=dict(first_reads=dict(d1=21)))
        result = bp.decide(synth(kind="vote-read", entered=False, not_entered="shim ended", probe=probe), RELEASE)
        self.assertIn("vote-write-r2", result["holds"])
        ids = [boot["id"] for boot in bp.PLAN if boot["id"] not in ("vote-read-r1", "vote-write-r2")]
        entries = [dict(attempt=item, boot=item, name=item, grade="PASS", signature="S", why="w", do="") for item in ids]
        entries.append(dict(attempt="v", boot="vote-read-r1", name="vote-read-r1", grade="PASS", signature="S", why="w", do="", holds=result["holds"]))
        pick = bp.plan_next(entries, RELEASE)
        self.assertIsNone(pick["boot"])
        self.assertIn("vote-write-r2 held", pick["why"])


class Signatures(unittest.TestCase):
    def decide(self, **kw):
        kw.setdefault("log", BOOTED)
        return bp.decide(synth(**kw), RELEASE)

    def test_read_failed_goes_to_the_multi_row(self):
        result = self.decide(panic="blazer-root: READ failed, partition lba 1, status -9/-9", line=ALL_ON)
        self.assertEqual((result["signature"], result["take_off"]), ("READ_FAILED", [MULTI]))

    def test_read_failed_then_hold_when_multi_is_off(self):
        self.assertEqual(self.decide(panic="blazer-root: READ failed", line=ALL_ON.replace(MULTI, ""))["take_off"], [HOLD])

    def test_read_failed_no_ufs_row_is_a_rerun(self):
        result = self.decide(panic="blazer-root: READ failed", line="hk_top=30")
        self.assertIsNone(result["row"])
        self.assertIn("rerun once", result["do"])

    def test_sgi_assert_with_0532_goes_to_smp(self):
        result = self.decide(panic="cpu_common.c:634 Assertion failed: x cpu_flags y", line=ALL_ON)
        self.assertEqual((result["signature"], result["row"]), ("SGI_ASSERT", 1))
        self.assertEqual(set(result["take_off"]), {CPUS, "blazer_smp_test=1", "blazer_fast_first=1"})

    def test_startup_timeout_on_cpu0_is_the_fast_core(self):
        result = self.decide(panic="SWEET CPU: cpu=0 startup timeout", line=ALL_ON)
        self.assertEqual((result["signature"], result["take_off"]), ("BOOT_CORE", [BOOTCPU]))

    def test_any_failure_before_boot_core_line_is_the_fast_core(self):
        result = self.decide(panic="some assert", line=ALL_ON, log="early text\n")
        self.assertEqual(result["take_off"], [BOOTCPU])

    def test_second_core_is_smp(self):
        result = self.decide(panic="SWEET CPU: cpu=1 NOT alive: PSCI CPU_ON rc=-9", line=ALL_ON)
        self.assertEqual((result["signature"], result["row"]), ("SMP_CORE", 1))

    def test_not_alive_with_no_rc_stops(self):
        result = self.decide(panic="SWEET CPU: cpu=1 NOT alive", line=ALL_ON)
        self.assertEqual(result["grade"], "STOP")
        self.assertIn("EXPERIMENT", result["do"])

    def test_smp_self_test_names_smp(self):
        self.assertEqual(self.decide(panic="blazer-smp-test: 3 errors, see the lines before this", line=ALL_ON)["signature"], "SMP_CORE")

    def test_sched_prim_takes_fast_first_alone(self):
        result = self.decide(panic="sched_prim.c:123 assert", line=ALL_ON)
        self.assertEqual(result["take_off"], ["blazer_fast_first=1"])

    def test_deadline_no_ui_is_stuck_userland(self):
        result = self.decide(panic="blazer-root: deadline 900 s, stage pid1_exec", line=ALL_ON, user=dict(swaps_at_least=0, springboard_execs=1, backboardd_execs=1))
        self.assertEqual(result["grade"], "FAIL")
        self.assertIn("Stuck userland", result["do"])

    def test_deadline_respawn_is_a_crash_loop(self):
        result = self.decide(panic="blazer-root: deadline 900 s", line=ALL_ON, user=dict(swaps_at_least=5, springboard_execs=3, backboardd_execs=1))
        self.assertIn("Crash loop", result["why"])

    def test_deadline_is_good_with_ui(self):
        self.assertEqual(self.decide(panic="blazer-root: deadline 900 s", line=ALL_ON, user=UI)["grade"], "PENDING-OWNER")

    def test_no_name_crash_takes_smp_then_validation(self):
        first = self.decide(panic=None, line=ALL_ON)
        self.assertEqual((first["signature"], first["row"]), ("RESET_NO_NAME", 1))
        self.assertEqual(self.decide(panic=None, line=NO_SMP)["take_off"], [VALID])

    def test_named_unknown_panic_takes_first_step_still_on(self):
        first = self.decide(panic="some assert elsewhere", line=ALL_ON)
        self.assertEqual((first["signature"], first["row"]), ("PANIC_NAMED", 1))
        self.assertEqual(self.decide(panic="some assert", line=NO_SMP)["take_off"], [BOOTCPU])

    def test_ufs_in_a_message_isnt_a_ufs_thread(self):
        self.assertEqual(self.decide(panic="bsd_init: cannot mount ufsroot0, errno = 22", line=ALL_ON)["signature"], "PANIC_NAMED")

    def test_ufs_caller_is_the_hold_row(self):
        result = self.decide(panic="data abort", symbol="n892_ro_read_exact+0x6c", line=ALL_ON)
        self.assertEqual((result["signature"], result["take_off"]), ("UFS_THREAD", [HOLD]))

    def test_lock_panic_is_the_hold_row(self):
        self.assertEqual(self.decide(panic="panic under lck_mtx_unlock", line=ALL_ON)["take_off"], [HOLD])

    def test_fb_copy(self):
        self.assertEqual(self.decide(panic="fault", symbol="sweet_fb_copy64+0x20", line=ALL_ON)["take_off"], ["hk_fb_fast=1"])

    def test_overlay_names_itself(self):
        self.assertEqual(self.decide(panic="varfs-overlay: bad group", line=ALL_ON)["take_off"], ["hk_overlay=3"])

    def test_bootcpu_mismatch_has_no_row(self):
        result = self.decide(panic="SWEET CPU: blazer_bootcpu 0x200 not in ADT", line=ALL_ON)
        self.assertEqual((result["signature"], result["row"]), ("BOOTCPU_MISMATCH", None))

    def test_payload_version_goes_to_bootchain(self):
        result = self.decide(entered=False, not_entered="bad payl...", line=ALL_ON)
        self.assertEqual((result["signature"], result["row"]), ("NO_XNU_ENTRY", None))
        self.assertIn("version", result["why"])
        self.assertIn("Bootchain", result["do"])

    def test_payload_reader_text_from_the_shims_stamp(self):
        spec2 = importlib.util.spec_from_file_location("bs", bp.ROOT / "tools/boot-summary.py")
        summary = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(summary)
        arg = int.from_bytes(b"bad payl", "little")
        text = summary.refusal_text("", f"  1 2 payload REFUSED {arg:#018x} x")
        self.assertEqual(bp.not_entered_detail(synth(entered=False, not_entered=text))[0], "payload")

    def test_named_fast_core_refusal(self):
        result = self.decide(entered=False, not_entered="fc-cpuon...", line=ALL_ON, log="")
        self.assertEqual((result["signature"], result["take_off"]), ("NO_XNU_ENTRY", [BOOTCPU]))

    def test_handoff_no_kernel_lines(self):
        self.assertEqual(self.decide(entered=False, not_entered="shim handed off but no XNU entry record (x)", line=ALL_ON, log="")["take_off"], [BOOTCPU])

    def test_nonce_reuse_has_no_row(self):
        self.assertIsNone(self.decide(entered=False, not_entered="unproven: nonce reused, reader refuses the trail", line=ALL_ON)["row"])

    def test_hung_goes_to_smp_then_fast_core_then_order(self):
        first = self.decide(cls="LONG-PRESS", line=ALL_ON)
        self.assertEqual((first["signature"], first["row"]), ("HUNG", 1))
        self.assertEqual(self.decide(cls="LONG-PRESS", line=NO_SMP)["take_off"], [BOOTCPU])
        rest = NO_SMP.replace(BOOTCPU, "")
        self.assertEqual(self.decide(cls="PMIC-COLD", line=rest)["take_off"], ["hk_fb_scale=1"])

    def test_press_after_a_panic_is_the_panic(self):
        self.assertEqual(self.decide(cls="LONG-PRESS", panic="blazer-root: READ failed", line=ALL_ON)["signature"], "READ_FAILED")

    def test_not_captured_prints_capture_not_runs_it(self):
        facts = {"attempt": "a", "name": "a", "kind": "ui", "captured": False, "parked": False}
        result = bp.decide(facts, RELEASE)
        self.assertEqual(result["signature"], "NOT_CAPTURED")
        self.assertIn("capture-fastboot.py", result["do"])

    def test_unbound_log(self):
        facts = synth()
        facts["summary"]["xnu12377"] = {"bound": False, "why": "no XNU entry record"}
        self.assertEqual(bp.decide(facts, RELEASE)["signature"], "LOG_UNBOUND")

    def test_ras_beats_a_panic(self):
        self.assertEqual(self.decide(cls="RAS", panic="blazer-root: READ failed", line=ALL_ON)["signature"], "RAS")

    def test_new_ras_line_stops_even_as_psci(self):
        self.assertEqual(self.decide(ras_lines=1)["grade"], "STOP")

    def test_watchdog_and_thermal_stop(self):
        self.assertEqual(self.decide(cls="WDT-BITE")["signature"], "WDT_BITE")
        self.assertEqual(self.decide(thermal="0x4")["signature"], "THERMAL")
        self.assertEqual(self.decide(cls="NO-CRASH-TRACE")["signature"], "POWER_LOSS")

    def test_limits_stop_list(self):
        facts = synth(panic="x", line=ALL_ON)
        facts["reset"].update(iavg=-5.0, soc=70.0, vcell=4290.0, temp=46.0, xnu_s=1000.0)
        notes = " ".join(bp.decide(facts, RELEASE, prior_soc=89.0)["cautions"])
        for piece in ("SOC fell", "charge", "VCELL 4290", "SOC Temp 46", "wait 15 min", "IAVG -5 supports"):
            self.assertIn(piece, notes)
        alone = synth(panic="x", line=ALL_ON)
        alone["reset"]["iavg"] = -232.0
        self.assertFalse([line for line in bp.decide(alone, RELEASE)["cautions"] if "IAVG" in line], "IAVG alone decides nothing")
        hot = synth(panic="x", line=ALL_ON)
        hot["reset"]["temp"] = 48.0
        self.assertEqual(bp.decide(hot, RELEASE)["grade"], "STOP")

    def test_soft_lines_name_a_row(self):
        result = self.decide(panic="blazer-root: deadline 900 s", line=ALL_ON, user=UI, log=BOOTED + "HK CLK: stopped, queue\n")
        self.assertTrue(any("hk_clk=30" in line for line in result["cautions"]))

    def test_table_is_complete(self):
        ids = {sig["id"] for sig in bp.SIGNATURES}
        for name in ("RAS", "READ_FAILED", "SGI_ASSERT", "DEADLINE", "NO_XNU_ENTRY", "HUNG", "SMP_CORE", "BOOT_CORE"):
            self.assertIn(name, ids)
        for sig in list(bp.TAKE_OFF) + [name for name, _ in bp.PANIC_PATTERNS]:
            self.assertIn(sig, ids)
        rc, out = run("signatures")
        self.assertEqual(rc, 0)
        self.assertIn("bad payl", out)

    def test_take_off_tokens_are_in_the_table(self):
        tokens = {row["token"] for row in RELEASE["rows"]}
        for wanted in bp.TAKE_OFF.values():
            self.assertLessEqual(set(wanted), tokens)


class Binding(unittest.TestCase):
    def test_an_unbound_log_is_not_read(self):
        self.assertEqual(bp.bound_log(None, ATT / "20261102-005130-wifi-stage1-r1", {"xnu12377": {"bound": False}}), "")
        self.assertEqual(bp.bound_log(None, ATT / "20261102-005130-wifi-stage1-r1", {"xnu12377": None}), "")

    def test_a_wrong_crc_stops_fast_core_work(self):
        log = "SWEET CPU: boot core mpidr=0x200 midr=0x410fd871\nblazer-ufs-fullcheck: done, spans 128 blocks 2097152 whole crc deadbeef, 1 ms\n"
        result = bp.decide(synth(kind="fastcore", panic="initproc failed", log=log), RELEASE)
        self.assertEqual((result["grade"], result["scope"]), ("STOP", "fastcore"))
        self.assertIn("deadbeef", result["why"])


class ProbeGrades(unittest.TestCase):
    def grade(self, kind, verdict, **probe):
        facts = synth(kind=kind, entered=False, not_entered="shim ended", probe=dict(verdict=verdict, **probe))
        return bp.decide(facts, RELEASE)

    def test_vote_read(self):
        self.assertEqual(self.grade("vote-read", "READ_CLEAN")["grade"], "PASS")
        for bad, want in (("NO_END: reset", "STOP"), ("GUARD_FAULT", "STOP"), ("STOP_NOT_LEVEL", "FAIL")):
            self.assertEqual(self.grade("vote-read", bad)["grade"], want)
        self.assertEqual(self.grade("vote-read", "NO_END: x")["scope"], "vote")

    def test_vote_write(self):
        self.assertEqual(self.grade("vote-write", "LADDER_DONE")["grade"], "PASS")
        self.assertEqual(self.grade("vote-write", "VOTE_IGNORED")["grade"], "FAIL")
        self.assertEqual(self.grade("vote-write", "OVERSPEED")["grade"], "STOP")

    def test_speed_unfixed_erratum_stops(self):
        self.assertEqual(self.grade("speed", "ALL_DONE", a725_unfixed=True)["grade"], "STOP")

    def test_decoder_refusal_is_unknown(self):
        self.assertEqual(self.grade("clk", None, text="record of another build")["grade"], "UNKNOWN")

    def test_decoders_refuse_another_builds_record(self):
        """vote's decoder reads this capture's RAM with vote-read's ids: no vote record there, so no verdict."""
        facts = dict(facts_of("20261102-004155-speed-probe-r3"), image=str(bp.ROOT / next(b for b in bp.PLAN if b["id"] == "vote-read-r1")["image"]))
        probe = bp.read_probe("vote-read", ATT / "20261102-004155-speed-probe-r3", facts)
        self.assertIsNone(probe["verdict"])


class Release(unittest.TestCase):
    def test_order_from_the_table(self):
        steps = {row["token"]: row["row"] for row in RELEASE["rows"]}
        self.assertEqual((steps[CPUS], steps["blazer_smp_test=1"], steps["blazer_fast_first=1"], steps[BOOTCPU], steps[VALID]), (1, 1, 1, 2, 11))
        self.assertEqual(max(steps.values()), 12)
        self.assertIn("blazer_touch=1", RELEASE["keep"])
        self.assertEqual((RELEASE["tag"], RELEASE["name"]), ("p12", "phone-full-p12"))

    def test_a_cell_with_an_escaped_pipe_stays_one_cell(self):
        self.assertTrue(all(row["when"] for row in RELEASE["rows"]))

    def test_live_release_still_parses(self):
        live = bp.parse_release()
        self.assertEqual(live["rows"][0]["row"], 1)
        image, boot = bp.compose_ui(live, live["name"] + "-r1", live["tag"], f"<{live['tag']}>")
        self.assertEqual((image, boot), (live["image_cmd"], live["boot_cmd"]))

    def test_a_broken_table_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "r.md"
            path.write_text(FIXTURE.read_text().replace("| 3 | Picture", "| 9 | Picture"))
            with self.assertRaises(ValueError):
                bp.parse_release(path)
            path.write_text(FIXTURE.read_text().replace("tools/bootios research", "tools/other research"))
            with self.assertRaises(ValueError):
                bp.parse_release(path)

    def test_all_on_equals_release_commands(self):
        image, boot = bp.compose_ui(RELEASE, "phone-full-p12-r1", "p12", "<p12>")
        self.assertEqual((image, boot), (RELEASE["image_cmd"], RELEASE["boot_cmd"]))

    def test_smp_off_is_cpus_1_on_the_same_core(self):
        image, boot = bp.compose_ui(RELEASE, "phone-full-p12-r2", "p12", "abc", {CPUS, "blazer_smp_test=1", "blazer_fast_first=1"})
        self.assertIn("--bootcpu 0x200 --cpus 1", image)
        self.assertNotIn("blazer_smp_test", image)
        self.assertIn("blazer_smp_report=1", image)
        self.assertIn("--wait 1200", boot)
        self.assertIn("--kernel-sha abc", image)
        self.assertIn("run/phone-full-p12-r2/boot.img phone-full-p12-r2", boot)

    def test_fast_core_off_changes_wait_and_flags(self):
        image, boot = bp.compose_ui(RELEASE, "x-r3", "p13", "s", {CPUS, BOOTCPU})
        self.assertNotIn("--bootcpu", image)
        self.assertNotIn("--cpus", image)
        self.assertIn("--wait 2100", boot)
        self.assertIn("kernel.ios26-p13.unstripped", boot)

    def test_scale_and_overlay_take_their_tool_flags(self):
        image, _ = bp.compose_ui(RELEASE, "x-r2", "p12", "a", {"hk_fb_scale=1", "hk_overlay=3"})
        for gone in ("--canvas", "hk_fb_scale=1", "--var-overlay", "hk_overlay=3"):
            self.assertNotIn(gone, image)
        self.assertIn("--bootcpu 0x200", image)

    def test_each_plain_token_removes_only_itself(self):
        whole, _ = bp.compose_ui(RELEASE, "a-r1", "p12", "s")
        for token in (HOLD, SPIN, MULTI, "hk_fb_fast=1", "blazer_ssbs=3", "hk_clk=30", VALID):
            image, _ = bp.compose_ui(RELEASE, "a-r1", "p12", "s", {token})
            self.assertEqual(image, whole.replace(token + " ", "").replace(" " + token + '"', '"'))

    def test_steps_from_a_line(self):
        self.assertEqual(bp.rows_on_line(RELEASE, ALL_ON), list(range(1, 13)))
        self.assertEqual(bp.rows_on_line(RELEASE, "hk_top=30"), [])
        self.assertEqual(bp.tokens_on_line(RELEASE, None), [])

    def test_a_step_comes_off_whole(self):
        step, tokens, _ = bp.take_off(RELEASE, ALL_ON.split(), "SMP_CORE")
        self.assertEqual((step, set(tokens)), (1, {CPUS, "blazer_smp_test=1", "blazer_fast_first=1"}))

    def test_no_rows_left_means_relink(self):
        step, tokens, text = bp.take_off(RELEASE, [], "PANIC_NAMED")
        self.assertIsNone(step)
        self.assertIn("0720", text)

    def test_wrong_kernel_hash_refused(self):
        with self.assertRaises(ValueError):
            bp.kernel_facts("p11", dict(RELEASE, hashes={"p11": ("0" * 64, "0" * 64)}))

    def test_unlinked_kernel_is_a_placeholder(self):
        self.assertEqual(bp.kernel_facts("p99", RELEASE)["sha"], "<p99>")


class Plan(unittest.TestCase):
    ORDER = ["p11-check-cpu0-r1", "fastcore-check-r1", "vote-read-r1", "phone-next", "t1-thermal-r1", "usbcon-r1", "batt-probe-r4", "wifi-stage2-r1", "t1f-thermal-r1", "t2-thermal-r1", "phone-full", "vote-write-r2"]

    def entry(self, boot, grade, **kw):
        return dict(attempt=kw.pop("attempt", f"x-{boot}"), boot=boot, name=kw.pop("name", boot), grade=grade, signature="S", why="w", do="d", **kw)

    def passed(self, *ids):
        return [self.entry(item, "PASS") for item in ids]

    def next_id(self, *entries):
        return (bp.plan_next(list(entries), RELEASE)["boot"] or {}).get("id")

    def boot(self, boot_id):
        return next(item for item in bp.PLAN if item["id"] == boot_id)

    def test_order_is_status_md(self):
        self.assertEqual([boot["id"] for boot in bp.PLAN], self.ORDER)

    def test_walks_in_order_when_each_passes(self):
        for index, boot_id in enumerate(self.ORDER):
            self.assertEqual(self.next_id(*self.passed(*self.ORDER[:index])), boot_id)
        self.assertIn("finished", bp.plan_next(self.passed(*self.ORDER), RELEASE)["why"])

    def test_limits_per_boot(self):
        self.assertEqual(self.boot("phone-next")["wait"], 1200)
        self.assertEqual(self.boot("t1-thermal-r1")["wait"], 2100)
        self.assertEqual(self.boot("t2-thermal-r1")["wait"], 480)
        self.assertIn("20 min", self.boot("phone-next")["owner"])

    def test_cpu0_fail_means_relink(self):
        pick = bp.plan_next([self.entry("p11-check-cpu0-r1", "FAIL")], RELEASE)
        self.assertIsNone(pick["boot"])
        self.assertIn("relink", pick["why"])

    def test_no_vote_or_p12_without_t1f_and_t2(self):
        self.assertEqual(set(self.boot("vote-write-r2")["needs"]) & {"t1f-thermal-r1", "t2-thermal-r1"}, {"t1f-thermal-r1", "t2-thermal-r1"})
        self.assertIn("t2-thermal-r1", self.boot("phone-full")["needs"])
        before = self.ORDER[:self.ORDER.index("t1f-thermal-r1")]
        self.assertEqual(self.next_id(*self.passed(*before), self.entry("t1f-thermal-r1", "FAIL")), None)

    def test_vote_read_fail_doesnt_stop_the_ui(self):
        base = self.passed("p11-check-cpu0-r1", "fastcore-check-r1")
        self.assertEqual(self.next_id(*base, self.entry("vote-read-r1", "STOP", scope="vote")), "phone-next")

    def test_stop_for_all_holds_everything_until_the_parent_skips(self):
        stop = self.entry("p11-check-cpu0-r1", "STOP", scope="all")
        self.assertIsNone(self.next_id(stop))
        skip = self.entry("p11-check-cpu0-r1", "SKIP", action="skip", attempt=None)
        self.assertEqual(self.next_id(stop, skip), "fastcore-check-r1")

    def test_fast_core_unknown_holds(self):
        self.assertIsNone(self.next_id(*self.passed("p11-check-cpu0-r1"), self.entry("fastcore-check-r1", "UNKNOWN")))

    def test_p11_first_boot_uses_its_built_image(self):
        plan = bp.resolve(self.boot("phone-next"), None, RELEASE, [])
        self.assertIn("run/phone-next-r1/boot.img", plan["bootios"])
        self.assertIn("--wait 1200", plan["bootios"])
        self.assertIsNone(plan["build"])

    def test_p11_retry_keeps_to_its_own_line(self):
        line = "cpus=1 blazer_touch=1 hk_top=30 blazer_ufs_hold=1 blazer_ufs_spin_us=300 blazer_ufs_multi=1 hk_clk=30 blazer_bootcpu=0x200"
        tokens = bp.tokens_on_line(RELEASE, line)
        first = self.entry("phone-next", "FAIL", name="phone-next-r1", tokens_on=tokens, take_off=[MULTI], row=6, line=line)
        plan = bp.resolve(self.boot("phone-next"), None, RELEASE, [*self.passed("fastcore-check-r1"), first])
        self.assertEqual(plan["name"], "phone-next-r2")
        self.assertIn("kernel.ios26-p11", plan["build"])
        self.assertNotIn("--cpus", plan["build"])
        self.assertIn("--bootcpu 0x200", plan["build"])
        for gone in (MULTI, "hk_fb_te=1", "blazer_smp_test=1", "blazer_smp_report=1"):
            self.assertNotIn(gone, plan["build"])
        self.assertIn(HOLD, plan["build"])

    def test_ui_failure_walks_the_order_on_p12(self):
        tokens = ALL_ON.split()
        first = self.entry("phone-full", "FAIL", name="phone-full-p12-r1", tokens_on=tokens, take_off=[CPUS, "blazer_smp_test=1", "blazer_fast_first=1"], row=1)
        off = bp.tokens_off_next(RELEASE, [first])
        self.assertEqual(off, {CPUS, "blazer_smp_test=1", "blazer_fast_first=1"})
        on = [token for token in tokens if token not in off]
        second = self.entry("phone-full", "FAIL", name="phone-full-p12-r2", tokens_on=on, take_off=[VALID], row=11)
        plan = bp.resolve(self.boot("phone-full"), None, RELEASE, [first, second])
        self.assertEqual(plan["name"], "phone-full-p12-r3")
        self.assertIn("--cpus 1", plan["build"])
        self.assertNotIn("validation_disables", plan["build"])

    def test_ui_pending_waits_for_the_owner(self):
        base = self.passed("p11-check-cpu0-r1", "fastcore-check-r1", "vote-read-r1")
        self.assertIsNone(self.next_id(*base, self.entry("phone-next", "PENDING-OWNER", name="phone-next-r1")))

    def test_ui_fail_no_row_stops_the_walk(self):
        base = self.passed("p11-check-cpu0-r1", "fastcore-check-r1", "vote-read-r1")
        self.assertIsNone(self.next_id(*base, self.entry("phone-next", "FAIL", name="phone-next-r9", tokens_on=[])))

    def test_rest_after_a_long_run(self):
        ended = "2026-11-02 01:00:00 +0100"
        base = bp.time.mktime(bp.time.strptime(ended[:19], "%Y-%m-%d %H:%M:%S"))
        long_run = self.entry("phone-next", "PASS", xnu_s=900.0, ended=ended)
        self.assertEqual(bp.rest_left([long_run], base + 60), 840)
        self.assertEqual(bp.rest_left([long_run], base + 901), 0)
        self.assertEqual(bp.rest_left([self.entry("t2-thermal-r1", "PASS", xnu_s=120.0, ended=ended)], base), 0)

    def test_thermal_grades(self):
        ok = bp.decide(synth(kind="thermal", panic="blazer-root: deadline 1800 s", log="blazer-thermal: poll 3 max 41 C MID\n"), RELEASE)
        self.assertEqual(ok["grade"], "PASS")
        self.assertEqual(bp.decide(synth(kind="thermal", panic="blazer-root: deadline 1800 s"), RELEASE)["grade"], "FAIL")
        self.assertEqual(bp.decide(synth(kind="thermal-panic", panic="blazer-thermal: MID at 41 C, limit 30 C, poll 2"), RELEASE)["grade"], "PASS")
        self.assertEqual(bp.decide(synth(kind="thermal-panic", panic="blazer-thermal: blind, no temperature for 3 polls after 0 polls"), RELEASE)["grade"], "FAIL")
        self.assertEqual(bp.decide(synth(kind="thermal", panic=None, log="blazer-thermal: poll 3 got no temperature (1 in a row)\n"), RELEASE)["grade"], "FAIL")
        self.assertEqual(bp.decide(synth(kind="thermal-panic", panic="other"), RELEASE)["grade"], "FAIL")


VOTE = next(boot for boot in bp.PLAN if boot["id"] == "vote-read-r1")


class Images(unittest.TestCase):
    def test_built_images_match_their_pins(self):
        for boot in bp.PLAN:
            if boot["sha"]:
                with self.subTest(boot["id"]):
                    self.assertEqual(bp.sha256(bp.ROOT / boot["image"]), boot["sha"])

    def test_wrong_hash_blocks(self):
        lines, good = bp.check_image(VOTE["image"], "0" * 64, None)
        self.assertFalse(good)
        self.assertIn("WRONG", lines[0])

    def test_wrong_kernel_blocks(self):
        lines, good = bp.check_image(VOTE["image"], VOTE["sha"], "research/ios26-release-r1/artifacts/kernel.ios26-p4.unstripped")
        self.assertFalse(good)
        self.assertTrue(any("NOT the kernel" in line for line in lines))

    def test_right_kernel_passes(self):
        boot = next(b for b in bp.PLAN if b["id"] == "batt-probe-r4")
        lines, good = bp.check_image(boot["image"], boot["sha"], boot["mach"])
        self.assertTrue(good, lines)

    def test_used_image_warns(self):
        image = "research/ios26-bootchain-r1/run/phone-touch-r2/boot.img"
        lines, _ = bp.check_image(image, None, None)
        self.assertTrue(any("already booted" in line and "phone-touch-r2" in line for line in lines))

    def test_missing_image(self):
        self.assertFalse(bp.check_image("research/nope/boot.img", None, None)[1])

    def test_kernel_number(self):
        self.assertEqual(bp.kernel_number("x/kernel.ios26-p4-wifi1.unstripped"), 4)
        self.assertEqual(bp.kernel_number("x/kernel.ios26-p2-soak.unstripped"), 2)
        self.assertEqual(bp.kernel_number("x/kernel.blazer-r1"), None)
        self.assertEqual(bp.kernel_number(None), None)


class Commands(unittest.TestCase):
    def test_verdict_writes_one_line_and_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "r.jsonl"
            attempt = str(ATT / "20261102-002034-phone-touch-r2")
            rc, out = run("--log", str(log), "verdict", attempt)
            self.assertEqual(rc, 1)
            self.assertIn("VERDICT FAIL  READ_FAILED", out)
            self.assertIn("NEXT", out)
            lines = log.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual((entry["attempt"], entry["signature"], entry["soc"]), (Path(attempt).name, "READ_FAILED", 89.0))
            run("--log", str(log), "verdict", attempt)
            self.assertEqual(len(log.read_text().splitlines()), 1, "same result: no second line")

    def test_no_log_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "r.jsonl"
            run("--log", str(log), "verdict", str(ATT / "20261102-004155-speed-probe-r3"), "--no-log")
            self.assertFalse(log.exists())

    def test_soc_compares_with_the_log(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "r.jsonl"
            log.write_text(json.dumps(dict(attempt="old", boot=None, grade="PASS", soc=95.0, signature="S", row=None)) + "\n")
            _, out = run("--log", str(log), "verdict", str(ATT / "20261102-004155-speed-probe-r3"), "--no-log")
            self.assertIn("SOC fell, 95 to 89", out)

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            log = str(Path(folder) / "r.jsonl")
            self.assertEqual(run("--log", log, "verdict", str(ATT / "20261102-003649-clk-probe-r1"), "--no-log")[0], 0)
            self.assertEqual(run("--log", log, "verdict", str(ATT / "20261102-004645-keys-probe-r1"), "--no-log")[0], 0)
            self.assertEqual(run("--log", log, "verdict", str(ATT / "20261101-234344-phone-root-r1"), "--no-log")[0], 2)
            self.assertEqual(run("--log", log, "verdict", str(ATT / "20261101-213232-ssi-id-r1"), "--no-log", "--as", "phone-full")[0], 3)

    def test_missing_capture_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            attempt = Path(folder) / "20261102-100000-phone-full-p12-r1"
            attempt.mkdir()
            rc, out = run("--log", str(Path(folder) / "r"), "verdict", str(attempt), "--no-log")
            self.assertEqual(rc, 2)
            self.assertIn("NOT_CAPTURED", out)
            self.assertIn("capture-fastboot.py", out)

    def test_skip_is_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "r.jsonl"
            rc, out = run("--log", str(log), "skip", "p11-check-cpu0-r1", "--why", "parent")
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(log.read_text())["action"], "skip")
            self.assertIn("fastcore-check-r1", out.splitlines()[1])

    def test_show_each_boot_prints_a_command(self):
        with tempfile.TemporaryDirectory() as folder:
            for boot in bp.PLAN:
                rc, out = run("--log", str(Path(folder) / "r"), "show", boot["id"])
                self.assertEqual(rc, 0)
                self.assertRegex(out, r"(?m)^boot    tools/bootios ")
                self.assertRegex(out, r"(?m)^owner   ")
                self.assertRegex(out, r"(?m)^read    ")
                self.assertRegex(out, r"(?m)^hash|^image")
                self.assertIn("--wait", out)

    def test_vote_boots_have_no_mach(self):
        rc, out = run("--log", "/nonexistent/r", "show", "vote-read-r1")
        self.assertNotIn("--mach", next(line for line in out.splitlines() if line.startswith("boot ")))

    def test_never_runs_anything_but_decoders(self):
        """Every process this tool starts is python3 -I on a fleet reader. Nothing names fastboot, adb or bootios."""
        started = []
        real = subprocess.run

        def spy(cmd, *args, **kw):
            started.append(cmd)
            return real(cmd, *args, **kw)

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(bp.subprocess, "run", spy), mock.patch("os.system", side_effect=AssertionError("system")):
            log = str(Path(folder) / "r")
            for attempt in ("20261101-234344-phone-root-r1", "20261102-003649-clk-probe-r1"):
                run("--log", log, "verdict", str(ATT / attempt))
            for boot in bp.PLAN:
                run("--log", log, "show", boot["id"])
            run("--log", log, "next")
        self.assertTrue(started)
        for cmd in started:
            self.assertEqual(cmd[1], "-I")
            self.assertTrue(cmd[2].endswith(".py"), cmd)
            self.assertFalse(re.search(r"fastboot|adb|bootios|run-attempt", " ".join(cmd)), cmd)

    def test_source_starts_no_other_process(self):
        source = (HERE / "bootplan.py").read_text()
        self.assertEqual(source.count("subprocess.run("), 1)
        self.assertNotRegex(source, r"os\.system|os\.exec|Popen|check_output|check_call")


if __name__ == "__main__":
    unittest.main(verbosity=1)
