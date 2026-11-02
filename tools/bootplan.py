#!/usr/bin/env python3
"""The parent's boot list: what to boot next, the command for it, and what a finished attempt means.

  bootplan.py list                       the ordered boots, with state from the results log
  bootplan.py show BOOT [--kernel pN]    one boot: image and hash check, command, prerequisites, owner, readers
  bootplan.py next [--kernel pN]         the next boot by the plan and the results log
  bootplan.py verdict ATTEMPT [--as BOOT] [--owner-saw TEXT] [--no-log] [--kernel pN]
                                         verdict from the existing readers, what's next, one line in the log
  bootplan.py skip BOOT --why TEXT       parent's decision: pass over a boot, one line in the log
  bootplan.py signatures                 the panic and reset signature table

Host only. Reads captures, images and handoffs; runs only the fleet's read-only decoders on a capture. It never
runs fastboot, tools/bootios or anything that reaches the phone: it prints those commands for the parent.
Common: --log FILE (default research/ios26-runner-r1/results.jsonl), --release FILE (default handoffs/release.md).

verdict exits 0 for PASS and PARTIAL, 1 for FAIL, 2 for UNKNOWN or PENDING-OWNER, 3 for STOP.
"""
import argparse
import hashlib
import importlib.util
import json
import mmap
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "AGENTS.md").exists())
R = "research"
ATTEMPTS = f"{R}/laguna-usb-fix/attempts"
RELEASE = ROOT / R / "ios26-fleet/handoffs/release.md"
ARTIFACTS = ROOT / R / "ios26-release-r1/artifacts"
LOG = ROOT / R / "ios26-runner-r1/results.jsonl"  # a record of boots: stays out of git
FULLCHECK_CRC = "4f2b32c0"      # fastcore.md section 4, as 20261101-233933-fullcheck-r3b-after
CPU0_NS_PER_BYTE = 13.70        # fastcore.md section 4, ios26-speed-r1/FINDINGS.md
FULLCHECK_BYTES = 8.59e9
SOC_START_MIN = 80              # limits.md
RUN_NEEDS_REST, REST_S = 900, 900  # limits.md
VOTE_WRITE_EXPECTS = 20          # vote-write-r2, built after vote-read-r1 read domain 1 at 20
GRADE_EXIT = {"PASS": 0, "PARTIAL": 0, "FAIL": 1, "UNKNOWN": 2, "PENDING-OWNER": 2, "STOP": 3}
HOLD_NOTE = "The owner decides when boots run: check the newest word in NOTES.md and release.md first."


# ---------------------------------------------------------------- the plan
OWNER_ATTEND = "Don't touch the keys unless asked: a long press ends the boot. Cable in, SOC 80% or more."
FASTCORE_READERS = [
    "tools/boot-summary.py {attempt}",
    "python3 -I research/ios26-wdog-r1/tools/classify_reset.py {attempt}",
    "python3 -I research/ios26-fastcore-r1/tools/decode_ctlr.py {attempt}/ramdump/kernel.log",
]
B_IMG = f"{R}/ios26-bootchain-r1/run"
UI_READERS = ["tools/boot-summary.py {attempt}", "python3 -I research/ios26-wdog-r1/tools/classify_reset.py {attempt} --expect-deadline {deadline}",
              "python3 -I research/ios26-mine-r1/tools/decode_cost.py {attempt}/ramdump/kernel.log",
              "python3 -I research/ios26-dramclk-r1/tools/read_clkmon.py {attempt}/ramdump/kernel.log research/ios26-dramclk-r1/run/boot/decoded.json"]
THERMAL_READERS = ["tools/boot-summary.py {attempt}", "python3 -I research/ios26-wdog-r1/tools/classify_reset.py {attempt}"]
THERMAL_BUILD = "python3 -I research/ios26-bootchain-r1/image_tool.py image {name} --kernel research/ios26-release-r1/artifacts/kernel.ios26-p11 --kernel-sha {sha} --phone-root --phone-route md0-mountroot --qemu-run <run>{extra} --phone-args \"{args}\""
P11 = f"{R}/ios26-release-r1/artifacts/kernel.ios26-p11.unstripped"
P11_SHA = "666f744edc2936a4056ad9e1abd321b09e125aa0415190e91e66b5d5f4af5f22"
# Order: STATUS.md top, 01:35. Limits: handoffs/limits.md.
PLAN = [
    {"id": "p11-check-cpu0-r1", "kind": "fullcheck", "match": r"^p\d+-check-cpu0|^cpu0-check", "what": "No-arg code on cpu0, whole-image CRC. The control for fastcore-check-r1. Panel off",
     "image": f"{R}/ios26-bootchain-r1/run/p11-check-cpu0-r1/boot.img", "sha": "7c2537868366b1290a68113f9c59cac4d14bff806847103f9054e4ac6a5e28c9", "mach": f"{R}/ios26-release-r1/artifacts/kernel.ios26-p11.unstripped", "wait": 1500,
     "needs": [], "manual": [], "owner": "Attended. Hold power if no park at 20 min. " + OWNER_ATTEND, "readers": FASTCORE_READERS[:2],
     "passes": "CRC " + FULLCHECK_CRC + ", EXECOK6, initproc panic"},
    {"id": "fastcore-check-r1", "kind": "fastcore", "match": r"^fastcore-check", "what": "XNU on cpu2, whole-image CRC. Tests payload v2 and the boot core. About 3 min, panel off",
     "image": f"{R}/ios26-bootchain-r1/run/fastcore-check-r1/boot.img", "sha": "0773f28e0843a384679ffdfb69f0f94dd5f8728bd2446915f66019ecc54b4415",
     "mach": f"{R}/ios26-release-r1/artifacts/kernel.ios26-p11.unstripped", "wait": 1500, "needs": ["p11-check-cpu0-r1"], "manual": [],
     "owner": "Attended. Panel stays off, no brightness limit. Hold power if no park at 20 min. " + OWNER_ATTEND,
     "readers": FASTCORE_READERS, "passes": "fastcore.md's pass list: stamps, boot core 0x200, CRC " + FULLCHECK_CRC + ", EXECOK6, initproc panic, reset to fastboot"},
    {"id": "vote-read-r1", "kind": "vote-read", "match": r"^vote-read", "what": "First read of the CPU vote registers. Shim only, no write, about 2 min",
     "image": f"{R}/ios26-dramclk-r1/vote-read-r1/run/boot/boot.img",
     "sha": "b8ad0f0729eba8a703b32200991c89854b99444a1627367c2da46a5c33d72eee", "mach": None, "wait": 180,
     "needs": [], "manual": ["Parent: decision 1 in VOTE-PROPOSAL.md"],
     "owner": "Present, panel dark is fine. No reset by 90 s: long press (the 30 s guard's bite is unproved). " + OWNER_ATTEND,
     "readers": ["python3 -I research/ios26-dramclk-r1/vote/decode_vote.py {attempt}/ramdump/kernel.log research/ios26-dramclk-r1/vote-read-r1/run/boot/ufs-ids.json"],
     "passes": "READ_CLEAN, and d1 reads what vote-write-r2 expects, 20, or it refuses itself"},
    {"id": "phone-next", "kind": "ui", "match": r"^phone-next", "what": "p11 UI boot, cpu2, release.md's rows as built. Limits P1. On failure, steps come off in its fixed order",
     "image": f"{B_IMG}/phone-next-r1/boot.img", "sha": "96c9d2bb1790f59ec99a81d3f7e9865524fb7c8fbdf8521e0842d948f9157e99", "mach": P11, "wait": 1200, "ui_tag": "p11",
     "needs": ["fastcore-check-r1"], "manual": ["limits.md P1: P0 clean, brightness known"],
     "owner": "P1: 900 s deadline, hard stop at 20 min (long press), feel the back at 5, 10, 15 min. Film from the send; note the time home appears: no log gives it. limits.md's stop list. " + OWNER_ATTEND,
     "readers": UI_READERS, "passes": "Owner's sighting, SpringBoard and backboardd execs at 1 each, swaps counting, own deadline"},
    {"id": "t1-thermal-r1", "kind": "thermal", "match": r"^t1-", "what": "T1: first GET_TEMP, on cpu0. blazer_thermal=1",
     "image": f"{B_IMG}/t1-thermal-r1/boot.img", "sha": None, "mach": P11, "wait": 2100,
     "build": THERMAL_BUILD.format(name="t1-thermal-r1", sha=P11_SHA, extra="", args="blazer_thermal=1"), "needs": [], "manual": ["Parent sets --qemu-run <run>"],
     "owner": "P0: 1800 s deadline, hard stop at 35 min. limits.md's stop list. " + OWNER_ATTEND, "readers": THERMAL_READERS, "passes": "blazer-thermal lines with a temperature, own deadline. cpmlock.md"},
    {"id": "usbcon-r1", "kind": "xnu", "match": r"^usbcon", "what": "Live USB console, first DWC3 read from XNU. Needs the host reader running first",
     "image": f"{B_IMG}/usbcon-r1/boot.img", "sha": "e6f7d565b0c3c974916ad396a5ddbc75bbc12a1d9529df68a9a4c58a0b7f8722", "mach": f"{R}/ios26-usbcon-r1/artifacts/kernel.ios26-p4-usbcon.unstripped", "wait": 2100,
     "needs": [], "manual": ["First, in a second terminal: usbcon.py --output, as usbcon.md's test section"],
     "owner": "P0: hard stop at 35 min. A wrong guess resets at about 20 s. " + OWNER_ATTEND,
     "readers": ["python3 -I research/ios26-usbcon-r1/tools/usbcon.py --verify research/laguna-usb-fix/attempts/usbcon-r1.log --dump {attempt}/ramdump/kernel.log"], "passes": "usbcon.md: --verify ok, mismatched 0, lost_bytes 0, restarts 0. PARTIAL here until read"},
    {"id": "batt-probe-r4", "kind": "battery", "match": r"^batt-probe", "what": "Fuel gauge read against ABL's own line. Before blazer_battery on a UI boot",
     "image": f"{R}/ios26-battery-r1/run/batt-probe-r4/boot.img",
     "sha": "a623addfeae265995714b012f2375a356b6399760500d26a0af5525924dc6da1",
     "mach": f"{R}/ios26-battery-r1/artifacts/kernel.p4-battery-r4.unstripped", "wait": 300, "needs": [], "manual": [],
     "owner": OWNER_ATTEND, "readers": ["python3 -I research/ios26-battery-r1/tools/compare_abl.py {attempt}"],
     "passes": "compare_abl.py exit 0"},
    {"id": "wifi-stage2-r1", "kind": "wifi", "match": r"^wifi-stage2", "what": "Wi-Fi stage 2: DAR, OTP, firmware load. Not built: see wifi.md",
     "image": f"{B_IMG}/wifi-stage2-r1/boot.img", "sha": None, "mach": None, "wait": 480, "needs": [], "manual": ["wifi.md names its image and kernel; set them here"],
     "owner": OWNER_ATTEND, "readers": ["tools/boot-summary.py {attempt}"], "passes": "blazer-wifi: GO"},
    {"id": "t1f-thermal-r1", "kind": "thermal", "match": r"^t1f-", "what": "T1f: T1's line on cpu2, shows the MID zone reads. Also P1b",
     "image": f"{B_IMG}/t1f-thermal-r1/boot.img", "sha": None, "mach": P11, "wait": 2100,
     "build": THERMAL_BUILD.format(name="t1f-thermal-r1", sha=P11_SHA, extra=" --bootcpu 0x200", args="blazer_thermal=1"), "needs": ["t1-thermal-r1"],
     "manual": ["P1 clean. limits.md's P1b asks 1800 s, but --bootcpu sets blazer_deadline=900: confirm which the image has"],
     "owner": "P1b: hard stop at 35 min, feel the back at 15 and 30 min. " + OWNER_ATTEND, "readers": THERMAL_READERS, "passes": "blazer-thermal lines, MID parse noted. No vote on a MID parse of 1 or 3"},
    {"id": "t2-thermal-r1", "kind": "thermal-panic", "match": r"^t2-", "what": "T2: guard's route test, panics on purpose at 30 C, on cpu0",
     "image": f"{B_IMG}/t2-thermal-r1/boot.img", "sha": None, "mach": P11, "wait": 480,
     "build": THERMAL_BUILD.format(name="t2-thermal-r1", sha=P11_SHA, extra="", args="blazer_thermal=2 blazer_thermal_panic_c=30"), "needs": ["t1-thermal-r1"], "manual": ["Parent sets --qemu-run <run>"],
     "owner": OWNER_ATTEND, "readers": THERMAL_READERS, "passes": "A panic from the guard, reset to fastboot"},
    {"id": "phone-full", "kind": "ui", "match": r"^phone-full-p", "what": "p12, five A725s, release.md's On rows. On failure, steps come off in its fixed order",
     "image": None, "sha": None, "mach": "release", "wait": None, "ui_tag": None, "needs": ["t1f-thermal-r1", "t2-thermal-r1"], "manual": ["release.md's \"Before it can be built\" table", "Parent sets --qemu-run <run>", "limits.md's prerequisites for this profile; brightness known"],
     "owner": "With the fast core on: attended 15 min, capped brightness, hard stop at 20 min (long press); feel the back at 5, 10, 15 min. Without it: attended 30 min, hard stop 35 min. "
              "Film from the send; note the time home appears: no log gives it. limits.md's stop list. " + OWNER_ATTEND,
     "readers": ["tools/boot-summary.py {attempt}", "python3 -I research/ios26-wdog-r1/tools/classify_reset.py {attempt} --expect-deadline {deadline}",
                 "python3 -I research/ios26-mine-r1/tools/decode_cost.py {attempt}/ramdump/kernel.log",
                 "python3 -I research/ios26-dramclk-r1/tools/read_clkmon.py {attempt}/ramdump/kernel.log research/ios26-dramclk-r1/run/boot/decoded.json"],
     "passes": "Owner's sighting, SpringBoard and backboardd execs at 1 each, swaps counting, own deadline"},
    {"id": "vote-write-r2", "kind": "vote-write", "match": r"^vote-write", "what": "Writes to cpu2's vote only, levels 20, 18, 16, 13, 20. Shim only. State change",
     "image": f"{R}/ios26-dramclk-r1/vote-write-r2/run/boot/boot.img",
     "sha": "e4d2108cbe44d5c10d96564bf25ec3b972dc3b9684639abcd088dcebdcedb66c", "mach": None, "wait": 180,
     "needs": ["vote-read-r1", "t1f-thermal-r1", "t2-thermal-r1"],
     "manual": ["Parent: decision 2 in VOTE-PROPOSAL.md", "Owner has heard the rail risk (decode_vote.py's condition)",
                "fastcore.md: only if fastcore-check-r1's CRC speed shows the CPU is the limit. `skip` it otherwise"],
     "owner": "Present. No reset by 90 s: long press, no retry. " + OWNER_ATTEND,
     "readers": ["python3 -I research/ios26-dramclk-r1/vote/decode_vote.py {attempt}/ramdump/kernel.log research/ios26-dramclk-r1/vote-write-r2/run/boot/ufs-ids.json"],
     "passes": "LADDER_DONE: 532.8, 532.8, 729, 1075, 1536, 533, each within 2%"},
]
LATER = "Later boots, each its own: release.md's Off rows (thermal, usbcon, sensors, haptics, counters). Not planned here. smp-check-r1 (ios26-smp-r1/EXPERIMENT.md) isn't built; read as a generic XNU boot if run."
# Recorded attempts and other names: which reading applies.
KINDS = [(boot["match"], boot["kind"]) for boot in PLAN] + [
    (r"^phone-(root|touch|full)", "ui"), (r"^soak-", "soak"), (r"^clk-probe", "clk"), (r"^speed-probe", "speed"),
    (r"^keys-probe", "keys"), (r"^wifi-stage", "wifi"), (r"^fullcheck-", "fullcheck"),
]
THERMAL = {"thermal", "thermal-panic"}
SHIM_ONLY = {"vote-read", "vote-write", "clk", "speed", "keys"}


# ---------------------------------------------------------------- signature table
SIGNATURES = [
    {"id": "RAS", "looks": "CDD reason `0xc00e`, DER 20, `ECC RAS error`, `GNOC error` or `TGTERR` in ABL's log", "means": "Bad access to an unvoted or dead peripheral. Not a timer",
     "do": "STOP, no retry. SEM names the target. Vote boots: stop vote work only"},
    {"id": "WDT_BITE", "looks": "RST_STAT 2, `apc wdt expiry`, DER 2, `0xcbca` or `0xcbea` as the CDD reason", "means": "AP watchdog: the shim's stop failed or something re-armed it", "do": "STOP. Fix in the shim"},
    {"id": "THERMAL", "looks": "`CPM thermal trip breadcrumb` not 0", "means": "First CPM trip on this phone", "do": "STOP all testing (power.md)"},
    {"id": "POWER_LOSS", "looks": "ABL's log has no crash trace", "means": "Power loss, or the log isn't of this run. Compare SYSEVENTs, VCELL", "do": "STOP until read"},
    {"id": "NOT_CAPTURED", "looks": "No `ramdump/kernel.log`", "means": "Runner ended without a capture: phone never parked, or a hard hang", "do": "Owner holds power to fastboot, capture before any other boot, read again"},
    {"id": "HUNG", "looks": "Owner's press (DER 7, `0xccca`) or PMIC cold reset (`0xcccb`), or no park recorded, and no panic in this boot's mirror", "means": "Hard hang or scheduler stuck, unless the owner pressed for another reason. `0xcccb`: RAM may have decayed",
     "do": "SMP step if on (a hang after cpu=1 starts), then the fast core. Otherwise steps by order"},
    {"id": "NO_XNU_ENTRY", "looks": "`XNU not entered`, on a boot that should enter", "means": "`bad payl...`: payload version: shim and mkpayload differ, v1 against v2. `fc-*`: named fast-core refusal. TIMEOUT: shim stages. HANDOFF, no entry record: start_first_cpu or MMU",
     "do": "Payload or TIMEOUT: bootchain, no step. `fc-*` or HANDOFF with the fast core on: its step. Nonce reused: rebuild under a new name"},
    {"id": "LOG_UNBOUND", "looks": "`log not bound`: no entry record with the shim's nonce", "means": "Nonce or capture problem. Nothing in the log can be used", "do": "Don't reuse conclusions. New image on rerun"},
    {"id": "READ_FAILED", "looks": "Panic `blazer-root: READ failed`", "means": "UFS under load. Before p8: PT's crash, fixed by 0714. From p8 with `blazer_ufs_multi`: that row's match",
     "do": "Before p8: use a kernel with 0714. Otherwise `blazer_ufs_multi`, then the hold and spin rows. Rerun once if none is on: same LBA twice, stop"},
    {"id": "SGI_ASSERT", "looks": "Panic `cpu_common.c:NNN Assertion failed ... cpu_flags`, `blazer-gic:`", "means": "Stale firmware SGI, early. Fixed by 0532 from p3: `soak-p2-r1`. With 0532 it's new",
     "do": "Before p3: use a kernel with 0532. Otherwise the SMP step if on, then the fast core, then blazer"},
    {"id": "SMP_CORE", "looks": "Panic `cpu=N NOT alive`, a spinlock or ticket-lock timeout, or `blazer_smp_test`'s named failure", "means": "SMP: the first new thing on this line", "do": "SMP step: `--cpus 1`, without its args. `NOT alive` with no `rc`: stop, read `ios26-smp-r1/EXPERIMENT.md`"},
    {"id": "SCHED_PRIM", "looks": "Panic in `sched_prim.c`", "means": "`blazer_fast_first`'s match", "do": "Take `blazer_fast_first=1` off alone, then SMP"},
    {"id": "BOOT_CORE", "looks": "`cpu=0 startup timeout`, or any failure before `SWEET CPU: boot core`, with the fast core on", "means": "XNU's start on an A725, self-SGI on frame 2", "do": "Fast core's step. Then `--wait 2100`"},
    {"id": "DEADLINE", "looks": "Panic `blazer-root: deadline N s`", "means": "The kernel's own session limit, not a crash. Good with swaps and the owner's sighting", "do": "Record. With no swaps: stuck userland, read the log's tail"},
    {"id": "INITPROC", "looks": "Panic `initproc failed`", "means": "Expected on a fullcheck line. On a UI boot: launchd, or a feature path", "do": "UI: `usertrap` lines; `exception 2` means instruction"},
    {"id": "VARFS_OVERLAY", "looks": "Panic `varfs-overlay:`", "means": "The overlay names itself", "do": "The overlay's step"},
    {"id": "BOOTCPU_MISMATCH", "looks": "Panic `SWEET CPU: blazer_bootcpu`", "means": "Token, ADT and core disagree: a build error", "do": "Bootchain. No row"},
    {"id": "UFS_THREAD", "looks": "Panic in a UFS thread, or under `lck_mtx_unlock`", "means": "Hold and spin rows match", "do": "`blazer_ufs_hold`, then `blazer_ufs_spin_us`"},
    {"id": "FB_COPY", "looks": "Fault in `sweet_fb_copy64` or the row copy", "means": "`hk_fb_fast`'s match", "do": "`hk_fb_fast`'s step"},
    {"id": "PANIC_NAMED", "looks": "Any other panic with text", "means": "No clear cause", "do": "Steps in release.md's fixed order, one a boot"},
    {"id": "RESET_NO_NAME", "looks": "Software reset, no panic text bound to this boot", "means": "A crash with no name, or a trap to EL2 or EL3 (inferred). `0xbab9` alone doesn't prove a panic", "do": "SMP first. Once SMP is off, `validation_disables`, out of order, so the asserts name it"},
    {"id": "PROBE_DONE", "looks": "A shim-only image's end, with its decoder's verdict", "means": "`XNU not entered` is normal here", "do": "Decoder's verdict decides"},
]
SIG_BY_ID = {sig["id"]: sig for sig in SIGNATURES}
PANIC_PATTERNS = [
    ("READ_FAILED", r"blazer-root: READ failed"),
    ("DEADLINE", r"blazer-root: deadline \d+ s"),
    ("VARFS_OVERLAY", r"varfs-overlay:"),
    ("BOOTCPU_MISMATCH", r"SWEET CPU: blazer_bootcpu"),
    ("SGI_ASSERT", r"cpu_common\.c:\d+ Assertion failed.*cpu_flags|blazer-gic:"),
    ("BOOT_CORE", r"cpu=0 startup timeout"),
    ("SMP_CORE", r"cpu=\d+ NOT alive|cpu=[1-9]\d* startup timeout|spinlock|ticket|hw_lck|blazer[-_]smp[-_]test"),
    ("SCHED_PRIM", r"sched_prim\.c"),
    ("INITPROC", r"initproc failed"),
    ("FB_COPY", r"sweet_fb_copy64|sweet_fb_device_copy_row"),
    ("UFS_THREAD", r"lck_mtx_unlock"),
]
# The UFS rows' match is where the panic happened, so the caller's name. "ufs" in a message can mean something else:
# `cannot mount ufsroot0` is the partition, not a UFS thread.
SYMBOL_PATTERNS = [("FB_COPY", r"sweet_fb_copy64|sweet_fb_device_copy_row"), ("UFS_THREAD", r"ufs|n892_ro|lck_mtx_unlock")]
# Lines that don't end a boot, but name a row (release.md's last column).
SOFT_LINES = [(r"^HK CLK: stopped.*$", "hk_clk=30"), (r"^tensor-dpu: .*(?:latched|refused).*$", "hk_fb_scale=1")]


# ---------------------------------------------------------------- loading the readers
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_text(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def run_reader(*argv):
    """A fleet decoder, read only, on a capture. Returns (rc, stdout)."""
    done = subprocess.run([sys.executable, "-I", *map(str, argv)], cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=300)
    return done.returncode, done.stdout + done.stderr


# ---------------------------------------------------------------- release.md
def parse_release(path=RELEASE):
    """The fixed take-off order and the next-try commands, from release.md itself. Refuses rather than guesses.
    Rows that share an Order number are one step. Columns are found by their header: other agents edit this table."""
    text = Path(path).read_text()
    rows, keep = [], []
    columns = None
    for line in text.splitlines():
        if line.startswith("| Order | Feature | Exact arg"):
            columns = [cell.strip() for cell in line.strip("|").split("|")]
            continue
        if columns and not line.startswith("|"):
            break
        if not columns:
            continue
        cells = [cell.strip() for cell in re.sub(r"\\\|", "/", line).strip("|").split("|")]
        if len(cells) != len(columns):
            continue
        cell = dict(zip(columns, cells))
        token = re.search(r"`([a-z_]+=[^`\s]+)`", cell["Exact arg"])
        if cell["Order"].isdigit():
            if not token:
                raise ValueError(f"release.md: step {cell['Order']} has no exact arg")
            rows.append({"row": int(cell["Order"]), "feature": cell["Feature"], "token": token.group(1), "when": cell["Take it off first if"]})
        elif cell["Order"] == "Keep" and token:
            keep.append(token.group(1))
    steps = [row["row"] for row in rows]
    if not rows or steps != sorted(steps) or sorted(set(steps)) != list(range(1, steps[-1] + 1)):
        raise ValueError(f"release.md: order column isn't 1..n: {steps}")
    image = re.search(r"^python3 -I research/ios26-bootchain-r1/image_tool\.py image .*$", text, re.M)
    boot = re.search(r"^tools/bootios research/ios26-bootchain-r1/run/.*$", text, re.M)
    if not image or not boot:
        raise ValueError("release.md: next-try commands not found")
    hashes = {}
    for match in re.finditer(r"^\| \*{0,2}(p\d+)\*{0,2} \|.*?`([0-9a-f]{64})` \| `([0-9a-f]{64})`", text, re.M):
        hashes[match.group(1)] = (match.group(2), match.group(3))
    return {"rows": rows, "keep": keep, "image_cmd": image.group(0), "boot_cmd": boot.group(0), "hashes": hashes,
            "tag": re.search(r"kernel\.ios26-(p\d+)", image.group(0)).group(1), "name": re.search(r"image_tool\.py image (\S+?)-r\d+ ", image.group(0)).group(1)}


def kernel_facts(tag, release):
    """Hash of a linked kernel, checked against release.md when that lists it. A mismatch is an error."""
    path = ARTIFACTS / f"kernel.ios26-{tag}"
    if not path.is_file():
        return {"tag": tag, "sha": f"<{tag}>", "note": f"{path.name} isn't linked yet"}
    sha = sha256(path)
    listed = release["hashes"].get(tag)
    if listed and listed[0] != sha:
        raise ValueError(f"{path.name} is {sha}, release.md says {listed[0]}: a pN is never rebuilt, stop")
    return {"tag": tag, "sha": sha, "note": "matches release.md" if listed else "not in release.md's table yet: hash read from the file, confirm with release"}


def compose_ui(release, name, tag, kernel_sha, off=(), line=None):
    """release.md's two commands, with these tokens off, and what the image tool needs changed with each.
    `line`: a retry of an older image keeps to that image's own args, since release's command may be for a newer kernel."""
    image_cmd, boot_cmd = release["image_cmd"], release["boot_cmd"]
    args = re.search(r'--phone-args "([^"]*)"', image_cmd).group(1).split()
    args = [arg for arg in args if arg not in off and (line is None or arg in line.split())]
    if line is not None and not re.search(r"\bcpus=[2-9]", line):
        image_cmd = re.sub(r" --cpus \S+", "", image_cmd)
    if "cpus=5" in off:
        image_cmd = re.sub(r"--cpus \S+", "--cpus 1", image_cmd)
    if "blazer_bootcpu=0x200" in off:
        image_cmd = re.sub(r" --bootcpu \S+", "", image_cmd)
        image_cmd = re.sub(r" --cpus \S+", "", image_cmd)
        boot_cmd = re.sub(r"--wait \d+", "--wait 2100", boot_cmd)
    if "hk_fb_scale=1" in off:
        image_cmd = re.sub(r" --canvas \S+", "", image_cmd)
    if "hk_overlay=3" in off:
        image_cmd = re.sub(r" --var-overlay \S+ --var-overlay-sha \S+", "", image_cmd)
    image_cmd = re.sub(r'--phone-args "[^"]*"', '--phone-args "' + " ".join(args) + '"', image_cmd)
    image_cmd = re.sub(r"--kernel-sha \S+", f"--kernel-sha {kernel_sha}", image_cmd)
    for_kernel = lambda cmd: re.sub(r"kernel\.ios26-p\d+", f"kernel.ios26-{tag}", cmd)
    swap = lambda cmd: re.sub(re.escape(release["name"]) + r"-r\d+", name, cmd)
    return swap(for_kernel(image_cmd)), swap(for_kernel(boot_cmd))


def tokens_on_line(release, line):
    tokens = set((line or "").split())
    return [row["token"] for row in release["rows"] if row["token"] in tokens]


def rows_on_line(release, line):
    """Steps with any token on the line."""
    return sorted({row["row"] for row in release["rows"] if row["token"] in set((line or "").split())})


# Which token a signature names, from release.md's last column, most specific first. "step" takes its whole step.
TAKE_OFF = {"READ_FAILED": ["blazer_ufs_multi=1", "blazer_ufs_hold=1", "blazer_ufs_spin_us=300"], "UFS_THREAD": ["blazer_ufs_hold=1", "blazer_ufs_spin_us=300"],
            "SMP_CORE": ["cpus=5"], "SCHED_PRIM": ["blazer_fast_first=1", "cpus=5"], "HUNG": ["cpus=5", "blazer_bootcpu=0x200"], "BOOT_CORE": ["blazer_bootcpu=0x200"],
            "NO_XNU_ENTRY": ["blazer_bootcpu=0x200"], "SGI_ASSERT": ["cpus=5", "blazer_bootcpu=0x200"], "VARFS_OVERLAY": ["hk_overlay=3"], "FB_COPY": ["hk_fb_fast=1"],
            "RESET_NO_NAME": ["cpus=5", "validation_disables=0x39d64"]}
ALONE = {"blazer_fast_first=1"}   # release.md: it can come off alone


def take_off(release, tokens_on, sig, before_boot_core=False):
    """Tokens to take off next. Returns (step, tokens, text). A failure matching a row's last column goes to it; a crash
    with no name to SMP, then row `validation_disables`; otherwise the first step still on, in release.md's order."""
    if not tokens_on:
        return None, [], "No take-off row left on this line. release.md: only Keep rows failing means the no-arg code: a kernel without 0720, 0721, 0723, one relink"
    by_token = {row["token"]: row for row in release["rows"]}
    wanted = ["blazer_bootcpu=0x200"] if before_boot_core else TAKE_OFF.get(sig, [])
    pick = next((token for token in wanted if token in tokens_on), None)
    why = "this failure matches it"
    if pick is None:
        pick = next(row["token"] for row in release["rows"] if row["token"] in tokens_on)
        why = "first step still on, by release.md's order"
    step = by_token[pick]["row"]
    tokens = [pick] if pick in ALONE else [row["token"] for row in release["rows"] if row["row"] == step and row["token"] in tokens_on]
    return step, tokens, f"step {step} ({by_token[pick]['feature']}: {' '.join(tokens)}): {why}"


# ---------------------------------------------------------------- reading a capture
def base_name(attempt):
    return re.sub(r"^\d{8}-\d{6}-", "", Path(attempt).name)


def kind_of(name):
    return next((kind for pattern, kind in KINDS if re.search(pattern, name)), "xnu")


def kernel_number(mach):
    """N of kernel.ios26-pN in a kernel's name, or None. p2-soak and p4-wifi1 count as p2, p4."""
    match = re.search(r"kernel\.ios26-p(\d+)", mach or "")
    return int(match.group(1)) if match else None


def bound_log(summary_module, attempt, summary):
    """This boot's message log, only if the summary bound it. kernel.log's raw bytes hold earlier boots' text after
    the ring boundary: wifi-stage1-r1's holds a READ failed from another boot, so nothing here reads them raw."""
    x = summary.get("xnu12377") or {}
    if not x.get("bound"):
        return ""
    reader = load("read_ramdump", ROOT / "tools/read-ramdump.py")
    dump = (Path(attempt) / "ramdump/kernel.log").read_bytes()
    doc, mirror = reader._parse_msgbuf_mirror(dump[reader.PMSG_OFF:reader.PMSG_OFF + reader.PMSG_SIZE], tail_count=1 << 21)
    console = summary_module.console_text(dump)
    log, _ = summary_module.whole_log(mirror or "", console, doc.get("stream_total"), doc.get("size"))
    return log.replace("\r\n", "\n")


def parse_classify(out):
    pick = lambda pattern: (re.search(pattern, out) or [None, None])[1]
    number = lambda text: float(text) if text not in (None, "None") else None
    return {"class": pick(r"^class\s+([A-Z-]+):"), "xnu_s": number(pick(r"XNU (\S+) s;")), "rtc_gap": number(pick(r"rtc_gap (\S+) s")),
            "soc": number(pick(r"SOC (\d+) VCELL")), "vcell": number(pick(r"VCELL (\d+) INOW")), "temp": number(pick(r"SOC temp (-?\d+) C")), "iavg": number(pick(r"IAVG (-?\d+)")), "cdd": pick(r"CDD (0x\w+)"), "text": out}


def gather(attempt, kind):
    """Facts for decide(), from the existing readers."""
    attempt = Path(attempt)
    facts = {"attempt": attempt.name, "name": base_name(attempt), "kind": kind, "captured": (attempt / "ramdump/kernel.log").is_file(),
             "parked": "park_wall:" in read_text(attempt / "park-timeline.txt")}
    meta = read_text(attempt / "meta.txt")
    facts["mach"] = (re.search(r"^mach: (.*)$", meta, re.M) or [None, None])[1]
    facts["image"] = (re.search(r"^image: (.*)$", meta, re.M) or [None, None])[1]
    facts["image_sha"] = (re.search(r"^image_sha256: (\w+)", meta, re.M) or [None, None])[1]
    facts["kernel_num"] = kernel_number(facts["mach"])
    if not facts["captured"]:
        return facts
    summary_module = load("boot_summary", ROOT / "tools/boot-summary.py")
    summary = summary_module.summarize(attempt)
    facts["summary"] = summary
    facts["summary_text"] = summary_module.render(summary)
    facts["log"] = bound_log(summary_module, attempt, summary)
    facts["stamps"] = read_text(attempt / "stamps-decode.txt")
    _, out = run_reader(ROOT / R / "ios26-wdog-r1/tools/classify_reset.py", attempt)
    facts["reset"] = parse_classify(out)
    abl = read_text(attempt / "ramdump/abl.log.txt")
    facts["ras_lines"] = len(re.findall(r"ECC RAS|TGTERR|GNOC error", abl))
    facts["thermal"] = (re.search(r"CPM thermal trip breadcrumb: (0x\w+)", abl) or [None, None])[1]
    manifest = summary_module.beside_image(facts["image"], "manifest.json") if summary.get("image_same") and facts["image"] else {}
    facts["line"] = manifest.get("cmdline")
    deadline = re.search(r"\bblazer_deadline=(\d+)", facts["line"] or "")
    facts["deadline"] = int(deadline.group(1)) if deadline else None
    facts["probe"] = read_probe(kind, attempt, facts)
    message = ((summary.get("xnu12377") or {}).get("panic") or {}).get("message") or ""
    said = re.search(r"blazer-root: deadline (\d+) s", message)
    if said:
        facts["deadline_check"] = run_reader(ROOT / R / "ios26-wdog-r1/tools/classify_reset.py", attempt, "--expect-deadline", said.group(1))
    return facts


def ids_beside(facts):
    if not facts.get("image"):
        return None
    path = Path(facts["image"]).parent / "ufs-ids.json"
    return path if path.is_file() else None


def read_probe(kind, attempt, facts):
    """The boot's own decoder, by kind. {verdict, next, rc, text}, or None when the kind has none."""
    log = Path(attempt) / "ramdump/kernel.log"
    decoders = {"clk": f"{R}/ios26-dramclk-r1/tools/decode_clk.py", "keys": f"{R}/ios26-stability-r1/keys-probe-r1/tools/decode_probe.py",
                "vote-read": f"{R}/ios26-dramclk-r1/vote/decode_vote.py", "vote-write": f"{R}/ios26-dramclk-r1/vote/decode_vote.py"}
    if kind in decoders:
        ids = ids_beside(facts)
        if not ids or not facts["summary"].get("image_same"):
            return {"verdict": None, "rc": None, "text": "image rebuilt or its ids are gone: the decoder can't bind this record"}
        rc, out = run_reader(ROOT / decoders[kind], log, ids, "--json")
        try:
            doc = json.loads(out)
        except ValueError:
            return {"verdict": None, "rc": rc, "text": out.strip().splitlines()[-1] if out.strip() else "no output"}
        return {"verdict": doc.get("verdict"), "next": doc.get("next"), "rc": rc, "doc": doc, "text": ""}
    if kind == "speed":
        rc, out = run_reader(ROOT / R / "ios26-fastcore-r1/probe-r3/decode_speed.py", log)
        return {"verdict": (re.search(r"^verdict (\S+)", out, re.M) or [None, None])[1], "rc": rc, "text": out,
                "a725_unfixed": bool(re.search(r"A725 .*NOT FIXED", out))}
    if kind == "battery":
        rc, out = run_reader(ROOT / R / "ios26-battery-r1/tools/compare_abl.py", attempt)
        return {"verdict": "PASS" if rc == 0 else "FAIL", "rc": rc, "text": out}
    return None


# ---------------------------------------------------------------- deciding
def hardware_stop(facts, prior_soc):
    """Stop rules from ABL's log. They outrank anything the kernel said."""
    reset = facts["reset"]
    cls = reset.get("class")
    vote = facts["kind"].startswith("vote")
    if cls == "RAS" or facts.get("ras_lines"):
        return "RAS", "vote" if vote else "all", f"class {cls}, {facts.get('ras_lines', 0)} RAS lines"
    if cls == "WDT-BITE":
        return "WDT_BITE", "all", "AP watchdog bit"
    if cls == "THERMAL" or facts.get("thermal") not in (None, "0x0"):
        return "THERMAL", "all", f"breadcrumb {facts.get('thermal')}"
    if cls == "NO-CRASH-TRACE":
        return "POWER_LOSS", "all", "no crash trace in ABL's log"
    if (reset.get("temp") or 0) >= 48:
        return "THERMAL", "all", f"ABL SOC Temp {reset['temp']:.0f} C, 48 or more: stop for the day (limits.md)"
    return None


def power_cautions(facts, prior_soc):
    """limits.md's common stop list, the parts ABL's log can show."""
    reset, out = facts["reset"], []
    if reset.get("soc") is not None and prior_soc is not None and reset["soc"] < prior_soc:
        out.append(f"SOC fell, {prior_soc:.0f} to {reset['soc']:.0f}: no higher profile, check the charger (limits.md)")
    if reset.get("vcell") is not None and reset["vcell"] <= 4300:
        out.append(f"VCELL {reset['vcell']:.0f} mV, at or under 4300: no higher profile, check the charger (limits.md)")
    if reset.get("soc") is not None and reset["soc"] < SOC_START_MIN:
        out.append(f"SOC {reset['soc']:.0f} is under {SOC_START_MIN}: charge before the next boot (limits.md)")
    if out and reset.get("iavg") is not None:
        out.append(f"IAVG {reset['iavg']:.0f} supports the above only; it decides nothing (limits.md)")
    temp = reset.get("temp")
    if temp is not None and temp >= 45:
        out.append(f"ABL SOC Temp {temp:.0f} C: same profile next, not higher (limits.md)")
    if (reset.get("xnu_s") or 0) >= RUN_NEEDS_REST:
        out.append(f"XNU ran {reset['xnu_s']:.0f} s: wait 15 min before the next boot, heat carries over (limits.md)")
    return out


def panic_signature(message, symbol):
    for sig, pattern in PANIC_PATTERNS:
        if re.search(pattern, message or ""):
            return sig
    for sig, pattern in SYMBOL_PATTERNS:
        if re.search(pattern, symbol or ""):
            return sig
    return "PANIC_NAMED"


def not_entered_detail(facts):
    text = facts["summary"].get("not_entered") or ""
    if text.startswith("bad payl") or "payload" in text.split(":")[0]:
        return "payload", f"Shim refused the payload (`{text}`): version mismatch is the first suspect, v1 against a v2 shim. Bootchain"
    if text.startswith("fc-"):
        return "fastcore", f"Named fast-core refusal `{text}`, still on cpu0"
    if text.startswith("unproven: nonce reused"):
        return "nonce", "Nonce reused: rebuild under a new name, then rerun"
    if "shim handed off" in text:
        return "handoff", "HANDOFF with no kernel lines: start_first_cpu or MMU"
    return "shim", f"`{text}`: shim's stages or capture. Bootchain"


def grade_probe(facts):
    """Shim-only images: the decoder decides. `XNU not entered` is normal there."""
    kind, probe = facts["kind"], facts["probe"] or {}
    verdict = probe.get("verdict")
    if verdict is None:
        return "UNKNOWN", f"Decoder gave no verdict: {probe.get('text', '')[:160]}"
    hint = probe.get("next") or ""
    if kind == "vote-read" and "vote-write-r1" in hint:      # the decoder's text predates vote-write-r2
        hint = ""
    tail = f"Decoder: {verdict}." + (f" {hint}" if hint else "")
    if kind == "speed":
        if probe.get("a725_unfixed"):
            return "STOP", tail + " 3114823 NOT FIXED: no kernel boot on an A725; goes to the owner through the parent"
        return ("PASS", tail) if verdict == "ALL_DONE" else ("PARTIAL", tail) if verdict.startswith("OFF_TIMEOUT") else ("FAIL", tail)
    if kind == "clk":
        return ("PASS", tail) if verdict == "LEVELS_AND_TABLE" else ("FAIL", tail)
    if kind == "keys":
        if verdict == "READS_SAFE_KEYS_NOT_ALL_SEEN":
            return "PARTIAL", tail + f" Reads safe; pressed: {', '.join(probe['doc'].get('pressed', []))}"
        return ("PASS", tail) if probe.get("doc", {}).get("final") == "OK" else ("FAIL", tail)
    if kind == "vote-read":
        if verdict == "READ_CLEAN":
            return "PASS", tail
    elif verdict == "LADDER_DONE":
        return "PASS", tail
    stops = ("NO_END", "RULE_BROKEN", "GUARD_FAULT", "STOP_FAULT", "STOP_SERROR", "STOP_T_SERROR", "OVERSPEED")
    return ("STOP" if verdict.startswith(stops) else "FAIL"), tail


def check_fastcore(facts):
    """fastcore.md section 4's pass list, in its order. Returns (checks, seconds of speedup text)."""
    log, stamps = facts.get("log", ""), facts.get("stamps", "")
    fullcheck = re.search(r"blazer-ufs-fullcheck: done, spans \d+ blocks \d+ whole crc ([0-9a-f]+)", log)
    panic = ((facts["summary"].get("xnu12377") or {}).get("panic") or {}).get("message", "")
    checks = [("el-drop DONE, handed off", bool(re.search(r"el-drop\s+DONE", stamps)) and "handed-off-to-xnu" in stamps)]
    if facts["kind"] == "fastcore":
        checks += [("stage-0x00e6 ENTER, core 0x200", "stage-0x00e6" in stamps),
                   ("boot core 0x200, A725", "SWEET CPU: boot core mpidr=0x200 midr=0x410fd871" in log),
                   ("1/1 CPUs, SGI1 verified", "SWEET CPU: 1/1 CPUs initialized, SGI1 verified" in log),
                   ("blazer-smp, blazer-ctlr, blazer-clock lines", all(key in log for key in ("blazer-smp:", "blazer-ctlr:", "blazer-clock:")))]
    checks += [(f"fullcheck whole crc {FULLCHECK_CRC}", bool(fullcheck) and fullcheck.group(1) == FULLCHECK_CRC),
               ("EXECOK6", "EXECOK6:" in log), ("initproc panic", "initproc failed" in panic),
               ("reset to fastboot, not a press", facts["reset"].get("class") == "PSCI-SW")]
    return checks, fullcheck


def speedup_text(facts):
    stages = (facts["summary"].get("xnu12377") or {}).get("stages") or []
    if not stages or not stages[-1]["busy_ms"]:
        return None
    last = stages[-1]
    ns = (last["ms"] - last["busy_ms"]) * 1e6 / FULLCHECK_BYTES
    ratio = CPU0_NS_PER_BYTE / ns if ns > 0 else 0
    return (f"CRC speed: {ns:.2f} ns a byte, {ratio:.2f}x cpu0's {CPU0_NS_PER_BYTE}. Near 3.45x: core-limited, a vote would pay. "
            "Well under: memory-limited, dramclk's floor first")


def decide(facts, release, prior_soc=None, owner_saw=None):
    """One verdict. Pure over facts, so synthetic captures can test each branch."""
    out = {"attempt": facts["attempt"], "name": facts["name"], "kind": facts["kind"], "row": None, "scope": None, "cautions": []}

    def done(grade, sig, why, do=None, row=None, scope=None):
        out.update(grade=grade, signature=sig, why=why, do=do if do is not None else (SIG_BY_ID[sig]["do"] if sig in SIG_BY_ID else ""), row=row, scope=scope)
        return out

    if not facts["captured"]:
        if facts.get("parked"):
            return done("UNKNOWN", "NOT_CAPTURED", "Parked but no dump: capture failed. Log RAM holds until the next boot")
        return done("UNKNOWN", "NOT_CAPTURED", "No capture and no park recorded",
                    f"If the runner is still waiting, the boot is running: do nothing, and don't press. Only once the runner has ended uncaptured: owner holds power to fastboot, then capture before any other boot: python3 tools/capture-fastboot.py {ATTEMPTS}/{facts['attempt']}/ramdump --fastboot fastboot --diagnostics")

    summary, reset = facts["summary"], facts["reset"]
    out["cautions"] = power_cautions(facts, prior_soc)
    if not summary.get("image_same"):
        out["cautions"].append("Image rebuilt or gone since this boot: nonce, ids and the boot line aren't used")
    if reset.get("rtc_gap") is not None and not 12 <= reset["rtc_gap"] <= 16:
        out["cautions"].append(f"rtc_gap {reset['rtc_gap']} s is outside 12-16: ABL's two logs may not be of this run")
    stop = hardware_stop(facts, prior_soc)
    if stop:
        return done("STOP", stop[0], stop[2], scope=stop[1])

    if facts["kind"] in SHIM_ONLY or facts["kind"] == "battery" and facts.get("probe") and not summary.get("xnu12377"):
        grade, why = grade_probe(facts)
        d1 = ((facts.get("probe") or {}).get("doc") or {}).get("first_reads", {}).get("d1")
        if facts["kind"] == "vote-read" and grade == "PASS" and d1 != VOTE_WRITE_EXPECTS:
            out["holds"] = {"vote-write-r2": f"vote-read saw domain 1 at {d1}, not {VOTE_WRITE_EXPECTS}: this image refuses itself. Rebuild it with {d1}, new nonce, and update its hash in PLAN"}
        scope = None if grade != "STOP" else "vote" if facts["kind"].startswith("vote") else "all"
        return done(grade, "PROBE_DONE", why, do="" if grade in ("PASS", "PARTIAL") else "Read the record; no retry yet", scope=scope)

    tokens_on = tokens_on_line(release, facts.get("line")) if facts["kind"] == "ui" else []
    rows_on = rows_on_line(release, facts.get("line")) if facts["kind"] == "ui" else []
    out["rows_on"], out["tokens_on"], out["take_off"] = rows_on, tokens_on, []
    knum = facts.get("kernel_num")

    def failing(sig, why, do=None):
        if facts["kind"] != "ui":
            return done("FAIL", sig, why, do)
        early = "blazer_bootcpu=0x200" in tokens_on and "SWEET CPU: boot core" not in (facts.get("log") or "")
        step, tokens, text = take_off(release, tokens_on, sig, early)
        out["take_off"] = tokens
        return done("FAIL", sig, why, do or (f"Take off {text}" if step else text), row=step)

    x = summary.get("xnu12377")
    if summary.get("not_entered"):
        kind_, why = not_entered_detail(facts)
        if kind_ in ("fastcore", "handoff") and ("blazer_bootcpu=0x200" in tokens_on or facts["kind"] == "fastcore"):
            return failing("NO_XNU_ENTRY", why) if facts["kind"] == "ui" else done("FAIL", "NO_XNU_ENTRY", why, "The fast core's trouble: fastcore.md's table")
        return done("FAIL", "NO_XNU_ENTRY", why, why.split(". ")[-1])
    panic = (x or {}).get("panic")
    cls = reset.get("class")
    if cls in ("LONG-PRESS", "PMIC-COLD") and not panic:
        why = f"{cls}, no panic in this boot's mirror. Furthest {(x or {}).get('furthest')}, after {reset.get('xnu_s')} s. A hang unless the owner pressed for another reason"
        return failing("HUNG", why)
    if x is None or not x.get("bound"):
        return done("UNKNOWN", "LOG_UNBOUND", (x or {}).get("why", "No 12377 log in this dump"))
    for pattern, token in SOFT_LINES:
        hit = re.search(pattern, facts.get("log") or "", re.M)
        if hit and token in tokens_on:
            out["cautions"].append(f"`{hit.group(0)[:90]}` matches `{token}`'s last column: take it off if the owner saw trouble")

    if facts["kind"] == "wifi":
        wifi = re.findall(r"^blazer-wifi: ((?:NO-)?GO\b.*)$", facts["log"], re.M)
        ended = re.search(r"^blazer-wifi: panic in (\d+) s", facts["log"], re.M)
        if not wifi:
            return done("FAIL", "RESET_NO_NAME", "No blazer-wifi verdict line: read its last `Next:` line, which names the step", "wifi.md's table")
        if wifi[-1].startswith("GO"):
            note = f"; it announced `panic in {ended.group(1)} s` to end the boot, XNU ran {reset.get('xnu_s')} s" if ended else ""
            return done("PASS", "PROBE_DONE", f"blazer-wifi: {wifi[-1]}{note}. Its panic text isn't in the mirror (observed)", "")
        return done("FAIL", "PROBE_DONE", f"blazer-wifi: {wifi[-1]}", "wifi.md's table")

    if facts["kind"] in THERMAL:
        lines = re.findall(r"^blazer-thermal: poll \d+ max \d+ C.*$", facts["log"], re.M)
        blind = bool(panic) and "blazer-thermal: blind" in (panic.get("message") or "")
        guard = bool(panic) and bool(re.search(r"blazer-thermal: .* at \d+ C, limit \d+ C", panic.get("message") or ""))
        if facts["kind"] == "thermal-panic":
            return done("PASS", "PROBE_DONE", "Guard's panic: " + panic["message"][:110], "") if guard else done("FAIL", "PANIC_NAMED", "No panic from the guard: " + ((panic or {}).get("message") or "none")[:110], "Read cpmlock.md")
        if not lines:
            return done("FAIL", "PANIC_NAMED" if panic else "RESET_NO_NAME", "No `poll N max` line: GET_TEMP gave no temperature" + (" (guard's own `blind` panic)" if blind else ""), "Read cpmlock.md; last line of the log")
        if panic and not re.search(r"blazer-root: deadline", panic.get("message") or ""):
            return done("FAIL", "PANIC_NAMED", panic["message"][:110], "Read cpmlock.md")
        return done("PASS", "DEADLINE" if panic else "RESET_NO_NAME", f"{len(lines)} blazer-thermal lines. Last: {lines[-1][:90]}", "")

    if facts["kind"] in ("fastcore", "fullcheck"):
        checks, fullcheck = check_fastcore(facts)
        out["checks"] = checks
        speed = speedup_text(facts)
        if speed:
            out["cautions"].append(speed)
        if fullcheck and fullcheck.group(1) != FULLCHECK_CRC:
            return done("STOP", "PANIC_NAMED", f"CRC {fullcheck.group(1)}, not {FULLCHECK_CRC}: the data path is wrong on this core", "Stop fast-core work (fastcore.md)", scope="fastcore")
        tail = facts["log"].rstrip().splitlines()[-1] if facts["log"].strip() else ""
        if not panic and "blazer-clock: cpu 0 reading AMU" in tail:
            return done("FAIL", "RESET_NO_NAME", "Last line is the AMU read: it trapped", "Take blazer_smp_report=1 off the line, no new kernel (fastcore.md section 3)")
        bad = [name for name, good in checks if not good]
        if not bad:
            return done("PASS", "INITPROC", "Every pass line holds", "")
        sig = panic_signature(panic.get("message"), panic.get("symbol")) if panic else "RESET_NO_NAME"
        return done("FAIL", sig, "Not seen: " + "; ".join(bad) + (f". Panic: {panic['message'][:110]}" if panic else ""))

    if not panic:
        if cls == "PSCI-SW":
            return failing("RESET_NO_NAME", f"Software reset, no panic text. Furthest {x.get('furthest')}, after {reset.get('xnu_s')} s")
        return done("UNKNOWN", "RESET_NO_NAME", f"Reset class {cls}, no panic text")

    message = panic.get("message") or ""
    sig = panic_signature(message, panic.get("symbol"))
    where = f"{message[:120]}, after {reset.get('xnu_s')} s, furthest {x.get('furthest')}"
    if sig == "SGI_ASSERT" and knum is not None and knum < 3:
        return done("FAIL", sig, where + ". Kernel predates 0532", "Known: fixed by 0532. Use a kernel from p3 on; don't boot this one again")
    if sig == "READ_FAILED" and knum is not None and knum < 8:
        return done("FAIL", sig, where + ". Kernel predates 0714", "Known: fixed by 0714 (never run). Use a kernel from p8 on")
    if sig == "READ_FAILED" and facts["kind"] == "ui" and not set(TAKE_OFF["READ_FAILED"]) & set(tokens_on):
        return done("FAIL", sig, where, "No UFS row on: rerun once. Same LBA twice: stop. Different: driver or load, blazer (first-ios-boot.md)")
    if sig == "BOOTCPU_MISMATCH":
        return done("FAIL", sig, where)
    if sig == "DEADLINE":
        user = x.get("userland") or {}
        expected = f"deadline {facts['deadline']} s" in message if facts.get("deadline") else True
        rc, check = facts.get("deadline_check") or (0, "")
        if rc:
            out["cautions"].append("classify_reset's deadline checks differ: " + (check.strip().splitlines() or [""])[-1])
        if not expected:
            out["cautions"].append(f"Line asked for {facts['deadline']} s, panic says otherwise")
        if facts["kind"] != "ui":
            return done("PARTIAL", sig, "Own deadline ended it: " + where, "")
        respawned = max(user.get("springboard_execs", 0), user.get("backboardd_execs", 0)) > 1
        if not user.get("swaps_at_least") or not user.get("springboard_execs") or not user.get("backboardd_execs"):
            return failing(sig, f"Deadline, no UI signs: swaps {user.get('swaps_at_least')}, SpringBoard {user.get('springboard_execs')}, backboardd {user.get('backboardd_execs')}", "Stuck userland: read the log's tail; last daemon")
        if respawned:
            return failing("PANIC_NAMED", f"Crash loop: SpringBoard {user['springboard_execs']}, backboardd {user['backboardd_execs']} execs", "Their usertrap and jetsam lines, then rows by order")
        if owner_saw:
            return done("PASS", sig, f"Own deadline, swaps at least {user['swaps_at_least']}, SpringBoard 1, backboardd 1. Owner: {owner_saw}", "Good: record, next boot")
        return done("PENDING-OWNER", sig, f"Own deadline, swaps at least {user['swaps_at_least']}, SpringBoard 1, backboardd 1. Success also needs the owner's sighting", "Rerun with --owner-saw TEXT once the owner has reported")
    if sig == "SMP_CORE" and re.search(r"NOT alive", message) and "rc=" not in message:
        return done("STOP", sig, where, "`NOT alive` with no `rc`: no retry until `ios26-smp-r1/EXPERIMENT.md` is read", scope="boot")
    if sig == "SGI_ASSERT" and facts["kind"] != "ui":
        return done("FAIL", sig, where, "New with 0532 in: stop, blazer")
    return failing(sig, where)


# ---------------------------------------------------------------- results log
def read_log(path):
    entries = []
    for line in read_text(path).splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def append_log(path, entry):
    """One JSON line. Rereading an attempt with the same result adds nothing."""
    same = lambda old: all(old.get(key) == entry.get(key) for key in ("attempt", "grade", "signature", "row", "action", "boot"))
    if any(same(old) for old in read_log(path)):
        return False
    with open(path, "a") as sink:
        sink.write(json.dumps(entry, sort_keys=True) + "\n")
    return True


def boot_for(name):
    return next((boot for boot in PLAN if re.search(boot["match"], name)), None)


def last_of(entries, boot_id):
    return next((entry for entry in reversed(entries) if entry.get("boot") == boot_id), None)


def boot_state(entries, boot):
    entry = last_of(entries, boot["id"])
    if not entry:
        return "not run"
    return "skipped" if entry.get("action") == "skip" else entry["grade"]


def ui_state(entries, boot_id="phone-full"):
    """Number of the next UI image, and the last UI run."""
    runs = [entry for entry in entries if entry.get("boot") == boot_id and entry.get("action") != "skip"]
    numbers = [int(m.group(1)) for entry in runs if (m := re.search(r"-r(\d+)$", entry.get("name", "")))]
    return max(numbers, default=0) + 1, runs[-1] if runs else None


def tokens_off_next(release, entries, boot_id="phone-full"):
    """Tokens off for the next UI image: from the last run's own line, then what it said to take off. SMP and the fast core stay off if fastcore-check failed."""
    every = {row["token"] for row in release["rows"]}
    _, last = ui_state(entries, boot_id)
    off = set()
    if last and last.get("tokens_on") is not None:
        off = every - set(last["tokens_on"])
        off |= set(last.get("take_off") or [])
    fast = last_of(entries, "fastcore-check-r1")
    if fast and fast.get("grade") in ("FAIL", "STOP") and fast.get("action") != "skip":
        off |= {row["token"] for row in release["rows"] if row["token"] in ("cpus=5", "blazer_smp_test=1", "blazer_fast_first=1", "blazer_bootcpu=0x200")}
    if "cpus=5" in off:
        off |= {"blazer_smp_test=1", "blazer_fast_first=1"} & every
    return off


def _plan_next(entries, release):
    """Returns ({boot, why}, notes). boot is None when nothing can run."""
    notes = []
    for entry in reversed(entries):
        if entry.get("action") == "skip":
            break             # the parent has read everything before its last decision
        if entry.get("scope") == "all":
            return {"boot": None, "why": f"STOP: {entry['signature']} in {entry['attempt']}: {entry['why']}. No boot until the parent has read it; `skip` a boot to record that and go on"}, notes
    stopped = {entry.get("scope") for entry in entries if entry.get("grade") == "STOP" and entry.get("action") != "skip"}
    held = {}
    for entry in entries:
        held.update(entry.get("holds") or {})
    for boot in PLAN:
        state = boot_state(entries, boot)
        if state in ("PASS", "skipped"):
            continue
        if boot["id"].startswith("vote") and "vote" in stopped:
            continue
        if boot["id"] in held:
            notes.append(f"{boot['id']} held: {held[boot['id']]}")
            continue
        unmet = [need for need in boot["needs"] if boot_state(entries, boot_for(need)) not in ("PASS", "skipped")]
        if unmet:
            continue
        if boot["kind"] == "ui":
            _, last = ui_state(entries, boot["id"])
            if last and last.get("grade") in ("UNKNOWN", "STOP", "PENDING-OWNER"):
                return {"boot": None, "why": f"Last UI boot `{last['name']}` is {last['grade']}: {last.get('why')}. {last.get('do', '')}"}, notes
            if last and last["grade"] == "FAIL" and not last.get("row"):
                return {"boot": None, "why": f"UI boot `{last['name']}` failed with no row to take off: {last.get('do')}"}, notes
            if last and last["grade"] == "FAIL":
                return {"boot": boot, "why": f"{last['name']} failed: {last.get('do')}"}, notes
            return {"boot": boot, "why": "Next by the plan"}, notes
        if state == "not run":
            return {"boot": boot, "why": "Next by the plan"}, notes
        last = last_of(entries, boot["id"])
        if boot.get("kind") == "fastcore" and state in ("FAIL", "STOP"):
            continue          # the UI line then goes without the fast core and SMP
        if boot["id"] == "p11-check-cpu0-r1" and state in ("FAIL", "STOP"):
            return {"boot": None, "why": f"p11-check-cpu0-r1 failed: the no-arg code. A kernel without 0720, 0721, 0723 takes one relink (release.md). {last.get('why')}"}, notes
        if state in ("FAIL", "UNKNOWN", "PENDING-OWNER"):
            return {"boot": None, "why": f"{boot['id']} is {state}: {last.get('why')}. {last.get('do', '')} Parent decides: rerun it, or `skip` it"}, notes
    return {"boot": None, "why": "Plan finished. " + LATER}, notes


def plan_next(entries, release):
    """First boot to run, or why none, naming any boot a result has held."""
    pick, notes = _plan_next(entries, release)
    return dict(pick, why=" ".join(notes + [pick["why"]]))


# ---------------------------------------------------------------- printing
def check_image(path, want_sha, mach, attempts_dir=None):
    """Lines on the image and kernel. Doesn't touch the phone. Second value False if the boot must not go."""
    lines, good = [], True
    image = ROOT / path
    if not image.is_file():
        return [f"image   NOT BUILT: {path}"], False
    have = sha256(image)
    if want_sha and have != want_sha:
        lines.append(f"hash    WRONG: {have}, plan says {want_sha}. Don't boot it")
        good = False
    else:
        lines.append(f"hash    {'OK' if want_sha else 'not pinned, read'}: {have}")
    if mach:
        kernel = ROOT / mach
        uuid = _macho_uuid(kernel)
        if uuid is None:
            lines.append(f"kernel  no LC_UUID readable in {mach}")
            good = False
        else:
            with open(image, "rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
                found = data.find(uuid) >= 0
            lines.append(f"kernel  {'UUID found in the image' if found else 'NOT the kernel in this image'}: {mach}")
            good = good and found
    used = _attempts_with_image(have, attempts_dir)
    if used:
        lines.append(f"used    already booted: {', '.join(used)}. Its nonce repeats and the reader refuses that trail: rebuild under a new name, unless first-ios-boot.md says rerun the same image")
    return lines, good


def _macho_uuid(path):
    try:
        with open(path, "rb") as source:
            head = source.read(0x10000)
    except OSError:
        return None
    if len(head) < 32 or struct.unpack_from("<I", head)[0] != 0xfeedfacf:
        return None
    off = 32
    for _ in range(struct.unpack_from("<I", head, 16)[0]):
        if off + 8 > len(head):
            return None
        cmd, size = struct.unpack_from("<II", head, off)
        if cmd == 0x1b:
            return head[off + 8:off + 24]
        if size < 8:
            return None
        off += size
    return None


def _attempts_with_image(sha, attempts_dir=None):
    folder = Path(attempts_dir) if attempts_dir else ROOT / ATTEMPTS
    return sorted(p.parent.name for p in folder.glob("*/meta.txt") if f"image_sha256: {sha}" in read_text(p))


def resolve(boot, tag, release, entries):
    """Concrete commands for a boot on kernel `tag`."""
    facts = {"bootios": None, "build": None, "image": boot.get("image"), "mach": boot.get("mach"), "notes": []}
    if boot["kind"] == "ui":
        number, last = ui_state(entries, boot["id"])
        if boot.get("ui_tag") and number == 1:      # built already: its own image, not release's newer line
            facts["name"] = boot["id"] + "-r1"
            facts["bootios"] = f"tools/bootios {boot['image']} {facts['name']} --mach {boot['mach']} --wait {boot['wait']}"
            return facts
        tag = tag or boot.get("ui_tag") or release["tag"]
        kernel = kernel_facts(tag, release)
        facts["mach"] = f"{R}/ios26-release-r1/artifacts/kernel.ios26-{tag}.unstripped"
        facts["notes"].append(f"Kernel {tag}: {kernel['sha']} ({kernel['note']})")
        name = f"{boot['id'] if boot.get('ui_tag') else release['name']}-r{number}"
        off = tokens_off_next(release, entries, boot["id"])
        facts["build"], facts["bootios"] = compose_ui(release, name, tag, kernel["sha"], off, (last or {}).get("line") if boot.get("ui_tag") else None)
        facts["image"] = f"{R}/ios26-bootchain-r1/run/{name}/boot.img"
        facts["notes"].append(f"Off: {' '.join(sorted(off)) or 'nothing'}")
        facts["name"] = name
        return facts
    facts["name"] = boot["id"]
    wait = f" --wait {boot['wait']}"
    mach = f" --mach {facts['mach']}" if facts["mach"] else ""
    facts["bootios"] = f"tools/bootios {facts['image']} {boot['id']}{mach}{wait}"
    if not facts["mach"]:
        facts["notes"].append("No kernel in this image, so no --mach. bootios warns about that; it's expected")
    return facts


def print_boot(boot, tag, release, entries, attempts_dir=None):
    plan = resolve(boot, tag, release, entries)
    print(f"{plan['name']}  [{boot_state(entries, boot)}]  {boot['what']}")
    print(HOLD_NOTE)
    built = bool(plan["image"]) and (ROOT / plan["image"]).is_file()
    lines, good = check_image(plan["image"], boot.get("sha"), plan["mach"], attempts_dir) if built else ([f"image   not built yet: {plan['image']}"], None)
    for note in plan["notes"]:
        print(f"note    {note}")
    for line in lines:
        print(line)
    needs = [f"{need}: {boot_state(entries, boot_for(need))}" for need in boot["needs"]] + [f"by hand: {item}" for item in boot["manual"]]
    print("needs   " + ("\n        ".join(needs) if needs else "nothing recorded"))
    print(f"owner   {boot['owner']}")
    if plan["build"]:
        print(f"build   {plan['build']}" + ("" if not built else "\n        (already built: don't rebuild, a change gets a new name)"))
    print(f"boot    {plan['bootios']}" + ("" if good is not False else "\n        BLOCKED by the checks above"))
    deadline = re.search(r"--wait 2100", plan["bootios"])
    reader_args = {"attempt": f"{ATTEMPTS}/<attempt>", "deadline": 1800 if deadline else 900}
    for line in boot["readers"]:
        print(f"read    {line.format(**reader_args)}")
    print(f"then    python3 -I research/ios26-runner-r1/bootplan.py verdict {ATTEMPTS}/<attempt>")
    print(f"passes  {boot['passes']}")


def print_verdict(result, facts):
    print(f"VERDICT {result['grade']}  {result['signature']}  {facts['attempt']}")
    print(f"why     {result['why']}")
    if result.get("do"):
        print(f"do      {result['do']}")
    for name, good in result.get("checks", []):
        print(f"  {'PASS' if good else 'FAIL'}  {name}")
    for line in result.get("cautions", []):
        print(f"note    {line}")
    if result.get("rows_on") is not None and facts.get("kind") == "ui":
        print(f"rows on {result['rows_on'] or 'none of the take-off rows'}")
    if facts.get("summary_text"):
        print("--- boot-summary")
        print(facts["summary_text"])
    if facts.get("reset", {}).get("text"):
        print("--- classify_reset")
        print("\n".join(line[:150] for line in facts["reset"]["text"].splitlines()))
    print("---")


def rest_left(entries, now=None):
    """Seconds of limits.md's rest still owed: 15 min after a run of 15 min or more."""
    now = time.time() if now is None else now
    for entry in reversed(entries):
        if entry.get("xnu_s") is None:
            continue
        if entry["xnu_s"] < RUN_NEEDS_REST or not entry.get("ended"):
            return 0
        try:
            ended = time.mktime(time.strptime(entry["ended"][:19], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            return 0
        return max(0, int(ended + REST_S - now))
    return 0


def print_next(entries, release, tag, attempts_dir=None):
    pick = plan_next(entries, release)
    rest = rest_left(entries)
    if rest:
        print(f"REST    {rest // 60 + 1} min more before any boot: the last run was 15 min or more (limits.md)")
    print(f"NEXT    {pick['why']}")
    if pick["boot"]:
        print_boot(pick["boot"], tag, release, entries, attempts_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", default=str(LOG))
    parser.add_argument("--release", default=str(RELEASE))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("signatures")
    for name in ("show", "next", "verdict"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--kernel", help="pN for the UI boot, default the one in release.md's command")
        if name == "show":
            cmd.add_argument("boot")
        if name == "verdict":
            cmd.add_argument("attempt")
            cmd.add_argument("--as", dest="as_boot", help="read it as this plan boot")
            cmd.add_argument("--owner-saw", help="what the owner reported on the panel")
            cmd.add_argument("--no-log", action="store_true")
    skip = sub.add_parser("skip")
    skip.add_argument("boot")
    skip.add_argument("--why", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "signatures":
        print("| Signature | Looks like | Means | Do |\n|---|---|---|---|")
        for sig in SIGNATURES:
            print(f"| {sig['id']} | {sig['looks']} | {sig['means']} | {sig['do']} |")
        return 0
    release = parse_release(args.release)
    entries = read_log(args.log)
    tag = getattr(args, "kernel", None)
    if args.cmd == "list":
        for index, boot in enumerate(PLAN, 1):
            built = "image set" if boot["image"] and (ROOT / boot["image"]).is_file() else "not built"
            print(f"{index}. {boot['id']:<19} {boot_state(entries, boot):<14} {built:<10} {boot['what']}")
        print(LATER)
        print("Take-off order, release.md: " + ", ".join(f"{row['row']} {row['token']}" for row in release["rows"]))
        return 0
    if args.cmd == "show":
        boot = next((item for item in PLAN if item["id"] == args.boot), None) or boot_for(args.boot)
        if not boot:
            print(f"bootplan: no boot {args.boot}; `list` names them", file=sys.stderr)
            return 2
        print_boot(boot, tag, release, entries)
        return 0
    if args.cmd == "next":
        print_next(entries, release, tag)
        return 0
    if args.cmd == "skip":
        boot = next((item for item in PLAN if item["id"] == args.boot), None)
        if not boot:
            print(f"bootplan: no boot {args.boot}", file=sys.stderr)
            return 2
        append_log(args.log, {"time": time.strftime("%Y-%m-%d %H:%M:%S %z"), "attempt": None, "boot": boot["id"], "name": boot["id"], "grade": "SKIP",
                              "signature": None, "action": "skip", "row": None, "why": args.why})
        print_next(read_log(args.log), release, tag)
        return 0

    attempt = Path(args.attempt)
    if not attempt.is_absolute():
        attempt = Path.cwd() / attempt
    if not attempt.is_dir():
        print(f"bootplan: no attempt folder {args.attempt}", file=sys.stderr)
        return 2
    name = base_name(attempt)
    plan_boot = next((item for item in PLAN if item["id"] == args.as_boot), None) if args.as_boot else boot_for(name)
    if args.as_boot and not plan_boot:
        print(f"bootplan: no boot {args.as_boot}", file=sys.stderr)
        return 2
    kind = plan_boot["kind"] if plan_boot else kind_of(name)
    facts = gather(attempt, kind)
    prior = [entry["soc"] for entry in entries if entry.get("soc") is not None and entry.get("attempt") != attempt.name]
    result = decide(facts, release, prior[-1] if prior else None, args.owner_saw)
    print_verdict(result, facts)
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S %z"), "attempt": attempt.name, "name": name, "boot": plan_boot["id"] if plan_boot else None,
             "kind": kind, "grade": result["grade"], "signature": result["signature"], "row": result.get("row"), "scope": result.get("scope"),
             "rows_on": result.get("rows_on"), "tokens_on": result.get("tokens_on"), "take_off": result.get("take_off"), "holds": result.get("holds"), "why": result["why"], "do": result.get("do"), "image_sha": facts.get("image_sha"), "line": facts.get("line"), "ended": (re.search(r"^park_wall: (.*)$", read_text(attempt / "park-timeline.txt"), re.M) or [None, None])[1],
             "soc": facts.get("reset", {}).get("soc"), "iavg": facts.get("reset", {}).get("iavg"), "xnu_s": facts.get("reset", {}).get("xnu_s"), "owner": args.owner_saw}
    if not args.no_log:
        print(f"log     {'wrote a line to' if append_log(args.log, entry) else 'same result already in'} {args.log}")
    entries = read_log(args.log) if not args.no_log else entries + [entry]
    print_next(entries, release, tag)
    return GRADE_EXIT[result["grade"]]


if __name__ == "__main__":
    sys.exit(main())
