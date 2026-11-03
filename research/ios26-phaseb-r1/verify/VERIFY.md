# VERIFY: evidence probes for every README row (2026-11-03, m1box, host only)

All results here are **host evaluations of existing captures**. No phone was touched and nothing
was booted. The evidence comes from PHYSICAL boot dumps and one live console, as labelled.

## What exists now

| Path | What |
| --- | --- |
| `docs/probes.yaml` | One probe per status.json row (55), plus 4 milestones (Home, Settings > About, AccessibilityUIServer, MessagesBlastDoorService). Each probe has: `phone_only`, `needs` (boot-args, markers, image), log checks per level (✅ `works` / 🟡 `partial` / 🔧 `built` / ⏳ `active`), `fails` (❌ evidence, reported as blockers, never used to demote), `confirm` (owner/screenshot fallback), optional `screenshot`, `owner` question, `next` (cheapest test). |
| `tools/probe_eval.py` | Evaluator. CLI: `<attempts>...`, `--propose-status [--apply]`, `--queue`, `--json`, `--qemu`, `--row`, `--text-dir`. Import: `evaluate(paths, rows=None, *, qemu=False, ...) -> list[dict]` for `tools/hk_cycle.py` / `tools/qemu_preflight.py`. Stdlib only. A YAML-subset loader is used when PyYAML is absent, and the test checks that both loaders give the same result. |
| `docs/owner_confirmations.txt` | Owner confirmations, seeded from the main LEDGER (pwr1 20:32, int1 21:13). A confirmation only finishes a level whose log checks already pass in that attempt. |
| `tools/test_probe_eval.py` | 19 host tests (synthetic mirror dumps, live console, confirmations, ordering, freshness, PNG luma, propose/apply, queue, line numbers). One real-capture case skips without research/. Added to `.github/scripts/ci-tests.sh`. |

Evaluator rules:
- XNU mirror text is decoded from `ramdump/kernel.log`, using the same v2/v1 geometry checks as `tools/read-ramdump.py`. It counts only when the attempt's `reader.txt` says `current-fresh=yes`. dbg5-screen (no reader verdict) and int1-dbg (no mirror) are listed but ignored. `reader.txt` repeats the mirror tail, so it is searched only by checks that name `src: [reader]`, which avoids counting lines twice.
- Line numbers split on `\n` only. `str.splitlines` also splits on the `\x1c`/U+2028 noise in these logs and moved cites by up to 3.5k lines. That is fixed and has a test.
- Best verdict across attempts; the latest attempt wins a tie. Blockers come from the best attempt and the latest exercised attempt.
- `--propose-status` only ever promotes. A status that the attempts do not show is reported as `unsupported-here` and never demoted.

## Verification

- `python3 -I tools/test_probe_eval.py`: 19 tests, OK.
- `docs/probes.yaml`: subset loader == `yaml.safe_load` (PyYAML 6.0.3). Every status.json row has exactly one probe, and every regex compiles.
- `.github/scripts/check_tracked.py`: clean.
- Runs (all under `research/ios26-phaseb-r1/verify/`; research/ is gitignored, so add with `-f`):
  - `probe-eval-report.txt` / `.json`: 27 attempts (`20261103-*`, `live-20261103-*`) against the **main checkout's** `docs/status.json` (ios26 a98be1e+, md5 081fcfc6…). This worktree's status.json predates the pwr1/gpu2/int1 owner promotions.
  - `probe-eval-vs-b11f5e7-logs-only.txt`: the same attempts against the pre-owner-report status (b11f5e7), with no confirmations. This shows what the logs alone would have proposed.
  - `msgbuf/*.msgbuf.txt`: decoded mirror text that the cites point at. These are device logs, so do not commit them.
- The live console `live-20261103-213954-a7-int1-live/console.txt` was still growing during the work (7.8k → 8.6k lines). Cites refer to the file as read at the final run.

## Result against the current status.json (main)

26 rows agree, 1 promotion, 1 log-short-of-confirmed, 4 unsupported here, 5 not exercised, 11 with no log probe, 6 out.

Logs alone, against b11f5e7 with no confirmations, would have proposed: Volume keys partial→works and Power key active→works (pwr1), GPU firmware partial→works (gpu2 rung 6), Isolated partitions →works, and 60 Hz built→partial. Brightness, chooser, haptics, battery and RTC reach "works pending confirmation". This matches the owner reports the coordinator committed later (a98be1e), except for brightness (see below).

### Disagreements

1. **Brightness (status ✅ on owner word, pwr1). The pwr1 log does not show the slider path.** In pwr1, every backboardd request is `(queue only)` and 0 are `queued for DCS`. DBV moves only 4336–4635 (span 299, the startup ramp). The DCS path first appears in int1: 46 `queued for DCS`, DBV 3138–4632 in the dump. The int1 live console has 47 DCS-queued requests, DBV 3187–4635 (~62–140 nits, `rc 0`, but `(no panel readback)`). So the owner's observation and the log evidence are from different boots. Either pwr1's visible change came through another path, or the observation needs repeating on int1. Next step: one attended slider move on int1, or log the panel's DBV readback.
2. **60 Hz (status 🔧 "cadence unmeasured"): it is measured.** `SWEET FB: rate swaps` gives at most 39.4 swaps/s (live int1) and 43.1/s (dumps), at `refresh asked 60, running 60`, with frames completing. Proposed: built→partial, note "completed frames measured at up to 39.4 swaps/s". This is the only promotion.
3. **120 Hz (status 🟡 "120 Hz mode observed"):** none of the 27 attempts runs at 120. All are `running 60`, so the claim rests on older boots.
4. **Home: UI_READY / SPRINGBOARD never fires in int1 live (UIDRV confirmed).** `live_boot.sh` waits for `Successfully spawned (SpringBoard)[`, which int1 never prints (0 lines). The `home` milestone uses fallback signals instead: `exec SpringBoard` (console:666), touch and button clients (857/860), frames (`rate swaps 16.0/s`, 3188), and the SpringBoard status-bar `HKBATT: event=battery_view_installed pid=28` (821), plus `battery_view_set` updates. It reaches ✅ for int1 live with no SpringBoard crash.
5. **Settings > About (ABOUT): the log contradicts "tccd rejects kServiceMediaLibrary".** Both Preferences SIGABRTs (console:3794, 6161, `CRASH Preferences reason ns 2 code 0x6`) come about 7 ms after tccd **grants** `kTCCServiceMediaLibrary` (console:3781, 6148: `Granting … via com.apple.private.tcc.allow`, `authValue=2`). The reply carries `generic_extension="invalid"` (3786, 6153). The failing piece is more likely the sandbox extension than the TCC decision. The probe records the sequence request → result → `generic_extension="invalid"` → SIGABRT as a known ❌.
6. **AccessibilityUIServer and MessagesBlastDoorService (ABOUT): the logs show only the crash signature.** AccessibilityUIServer has 10× `CRASH AccessibilityUIS … code 0x6`, and `AXSSPunctuationModel` appears nowhere in the log. BlastDoor has `EXC_GUARD AST` and then `CRASH MessagesBlastDoo … code 0x5` (SIGTRAP), 8×, and `Sandbox.swift` does not appear. Both are known ❌ blockers in the probes, with ABOUT's root causes noted as static attributions.
7. **Battery ✅:** the log has `battery_view_set … percent=95` from the gauge (SOC 95), but HKBATT itself says `ui_scope=unproved`. ✅ rests on the owner confirmation. An unattended `hk_screen` screenshot would replace it.
8. **Rows that cannot move from logs as built today:** Scripted taps (no kernel marker for remote TAP/HOME), Link to the Mac (no mux/lockdown markers), A520 (host audit only), Idle sleep (code reading only). The Live console "879,706 bytes matched" claim is not re-derivable here; the probe only proves the connection and live lines. Chooser ✅ rests on the owner (a cold power-on leaves no dump of the menu).

## Prioritised test queue (from `--queue`; unattended first, then points per phone-minute)

1. Scripted taps and keys 🟡→✅: int1 live, `usbcon --tap/--home` loop with `hk_screen=30` before/after (needs a kernel "remote event accepted" marker first).
2. Wi-Fi 🟡→✅: boot **a7-wifi-join-r4** (built 214641ba, not booted). The blocker today is `4-way handshake failed: status 4, reason 14` in all 3 join runs.
3. 60 Hz 🔧→🟡 (already proposed) and toward ✅: int1 300 s with a scripted swipe loop. Pass when `rate swaps ≥ 55/s`.
4. Writing (persistent /var) 🟡→✅: **a7-ios-system-int1-persist** (built 84f993b6) booted twice. The second boot must log the restore. Not exercised today (no `blazer-persist:` line in any attempt).
5. Sensors ⏳→: **a7-ios-system-sens2** (built 85664fb3). Not exercised today.
6. Audio: QEMU first (no phone time).
7. Builds needed before an unattended boot: 120 Hz profile; storage MB/s line; GPU M3 command stream (Metal); Bluetooth B2/B3 HCI; A520 cpus=6; higher governor cap; charger read-only log; idle-rate VRR; AOC; USB ECM; >13 GiB map; PCIe0 modem; native mux.
8. Attended or human-only, regression only: chooser cold boot, volume/power keys, haptic buzz, brightness (item 1 of the disagreements is the one worth a repeat).
9. Free instrumentation wins (they turn owner-only rows into log rows): DBV panel readback per send (Brightness), `hk_screen` status-bar crop vs HKBATT/RTC (Battery, Date and time), WFI residency in the gov tick (Idle sleep), remote-event accept line (Scripted input).

## Handoff for the coordinator (paths, tested hashes, message)

```
docs/probes.yaml                 4a144667633cd59cc1de86c818e641d25365e90158eb3b02ea1cfe04ee3ed0ee
docs/owner_confirmations.txt     84f39b9ee9ab622b11c80a20525543b1080592a0eb3787ba9cade2e342a994b5
tools/probe_eval.py              7b34bfcff30a31e4098c773c559101616faee9c2348e09611eac9d5cd04fee84
tools/test_probe_eval.py         9018beb21581e70c8b811460fbc2813f4b421103d21db6aad48bec9fab003f49
.github/scripts/ci-tests.sh      eafcbe37618175de72c4894ba6e1a21c3024b17cc34a1a396a65f05a07482424  (adds test_probe_eval)
research/ios26-phaseb-r1/verify/VERIFY.md            (git add -f; research/ is ignored)
research/ios26-phaseb-r1/verify/probe-eval-report.txt (optional, git add -f; contains log excerpts only)
```

These files are in the worktree `/srv/dev/.t3/worktrees/hackios/t3-06b9b643` (based on b11f5e7). None of them exist on ios26, so they do not conflict.

Commit message: `Probes: docs/probes.yaml (55 README rows + 4 milestones, phone_only) and tools/probe_eval.py (verdicts with file:line evidence, --propose-status/--apply, --queue, --json, evaluate()); 27 attempts of 11-03: 1 promotion (60 Hz built→partial), brightness ✅ not shown by pwr1's log`

NOTES section (proposed, to replace nothing):
- **Probes (host, 2026-11-03):** `python3 -I tools/probe_eval.py --propose-status <attempts>` gives per-row verdicts from boot logs (`docs/probes.yaml`). Today: 26/38 probed rows agree. 60 Hz is measured (≤ 43 swaps/s, propose 🟡). Brightness ✅ rests on an owner report whose boot (pwr1) never queued a DCS send. Receipts: `research/ios26-phaseb-r1/verify/VERIFY.md`.
