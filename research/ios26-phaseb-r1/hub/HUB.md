# HUB: `tools/hk`, one debug platform for parallel agents (2026-11-03, HOST only)

Status: **HOST evidence only.** `tools/hk` and its tests ran on m1box against fakes and against existing dumps (read only).
Nothing touched the phone or the Mac: no `hk boot/cycle/back/ui/shell/push/restart` was run for real. Nothing is staged or committed.

| File | sha256 | What |
| --- | --- | --- |
| `tools/hk` | `b4aa5caa34b5d14e23ccc241d2105c3105d3a4e92fb9208df7fc7ff29b2de4da` | launcher (`python3 -I tools/hk.py`) |
| `tools/hk.py` | `49d36a61cc054b4366ba85c7147110a412b9bfb71bd5672cb03eb6c61dd2c978` | the CLI, stdlib only |
| `tools/test_hk.py` | `9acf4e8dd3072c2b6dfd1e1b6ab6eedf539b5c5ab65d5ae66dc5055b778c7430` | host tests, fakes + real probe_eval/crashdoc on a synthetic dump: **31 tests OK** (`receipts/test_hk-r2.txt`) |
| `docs/debug/MAP.md` | `722e1bd01045be1de40c7a8e88fb3cc7defee88f385d386939350eb4e3c880c8` | per-subsystem knowledge map (`SUBSYS:` blocks) |
| `docs/debug/AGENTS-PLAYBOOK.md` | `fefcf94bf13204263c69ddd9fbca87e91efb7706e7a913ee2bea0c03b3b1866d` | claims, lease, queue, recording, lessons |

Generated, not for git: `attempts/` in the main checkout (its own `.gitignore` is `*`): 267 older runner, live and cycle
runs imported by `hk ingest --all` into `attempts/index.jsonl`, and `attempts/installed.json` (boot_b = chooser-ios-int1,
readback aca7c0fc, copied from LEDGER 21:13; a record, not read from the phone). The lease lives in `/tmp/fleet/`.

## 1. Commands

Every command prints concise text, or one JSON document with `--json` (`{"schema": "hk.<cmd>/1", "ok": bool, …}`). Progress
goes to stderr. Exit codes: 0 ok, 1 verdict FAIL, 2 usage, 3 tool or input not present yet, 4 phone busy (lease held),
5 unsupported by the phone side, 6 phone in the wrong state, 130 interrupted. Errors are `hk.error/1` with `error`, `message`,
`code` and context (`tool`, `path`, `owner`, `lease`). `hk schema [NAME]` prints each schema; they are listed in `SCHEMAS` in hk.py.

| Command | Wraps | Lease | Notes |
| --- | --- | --- | --- |
| `hk state [--no-phone]` | phone-bridge `fastboot devices`, `adb devices`, `mac usb`; hk_shell `pwd` | no | android / recovery / fastboot / ios / shim / usb-google / off-or-unknown (hk_cycle's order), lease, recorded boot_b, live run, recent attempts, queue |
| `hk lock status\|acquire NAME\|check [NAME]\|renew\|release NAME\|break` | — | — | section 3 |
| `hk status [--attempt\|--path DIR]` | probe_eval (all rows) + crashdoc `--no-symbols` (cached `crashes.json` first) | no | newest run dir by default: image, end, reader, milestones (live markers + milestone probes), README-row verdicts, crash signatures; a missing tool goes into `errors[]` (exit 3), the rest is still summarised |
| `hk boot IMAGE` = `hk live IMAGE` | `tools/live_boot.sh` | yes | `--mach --wait --sync-tools --no-console --ui-test`; live run goes into `attempts/<id>/` |
| `hk cycle IMAGE [-- args]` | `tools/hk_cycle.py` (HARNESS) | yes | `--mach --ui --expect --deadline-wait`; `--out attempts/<id>/cycle`; reads `summary.json` or `report.json` |
| `hk back [--attempt]` | `fastboot oem force-fastboot off`, `fastboot reboot`, `return-check.sh` | yes | refuses in iOS (exit 6: never cold-reset a running boot) |
| `hk ui SCRIPT [--check]` | `tools/ui_run.py RUN SCRIPT` (UIDRV); `settings` = `ui_settings_test.py` | yes (not for `--check`) | reads `<run>/ui_run.json` |
| `hk shot [--dump]` | `tools/screenshot.sh` (DBG5) | no | live: the reader's snapshot; `--dump`: HKSCR1 from the ramdump; stale records refused |
| `hk logs [PROC] [--sub S] [--grep RE] [--live]` | `tools/hklog.py` (OBS), cached in `attempts/<id>/logs/` | no | PROC = OBS's `HKL <prog>[<pid>] <message>` lines (`hkl/<prog>.log`), else lines naming `PROC[pid]`; raw-strings fallback without hklog |
| `hk stacks PROC [--full] [--live]` | `ustack_sym.py --summary` (DBG4); live: `spindump {proc} 2 -stdout` over hk_shell | no | dump needs `hk_ustack=PROC` in the image |
| `hk crash` = `hk crashes` `[--attempt\|--since\|--all]` | `tools/crashdoc.py` (CRASHDOC) → `crashes/crashes.json` | no | signatures with counts, status and hint ids; several attempts at once with `--since` |
| `hk shell CMD…` | hk_shell over the ECM link (DBG1/DBG2), via a Python client on the Mac | no (logged) | `[exit N]` → `exit`; builtins give `exit: null` |
| `hk push LOCAL /private/var/…` | hk_shell `put` builtin (proposed, 4.2) | yes | refuses targets outside /private/var (the root is read only) |
| `hk restart DAEMON` | hk_shell `ps` + `kill` builtin (proposed), launchd respawns | yes | reports old and new pids |
| `hk probe [ROW…] [--attempt\|--path DIR\|--live] [--qemu]` | `tools/probe_eval.py INPUTS [--row R]… --json` (VERIFY, `docs/probes.yaml`) | no | all rows by default; inputs = cycle + runner + live dirs; result in `attempts/<id>/probes/<row\|all>.json` |
| `hk report [ATTEMPT]` | — | no | `REPORT.md` + JSON: image, end, markers, UI, return check, crashes, probes, screens, paths |
| `hk note ATTEMPT TEXT` | — | no | owner actions into the manifest |
| `hk images [--feature F]` | `research/images/*/manifest.json` | no | features, deadline, overlay, attempts that used each image |
| `hk find [--feature --since --until --image --name --verdict --crash --kind --limit]` | `attempts/index.jsonl` | no | `--since today\|yesterday\|Nh\|Nd\|ISO` |
| `hk ingest [PATH…] [--all]` | runner, live_boot, hk_cycle and QEMU run dirs | no | idempotent by source path; a live run joins its runner attempt |
| `hk queue add\|list\|show\|admit\|cancel\|run` | `hk cycle` / `hk boot` + `hk back` | runner takes it per item | section 3 |
| `hk qemu IMAGE_DIR [-- args]` | `tools/qemu_preflight.py IMAGE --json OUT` (QFARM) | no (QEMU slot lock) | kind `qemu` attempts |
| `hk installed IMAGE --readback SHA` | — | no | records what boot_b holds; hk never reads or writes boot_b |
| `hk tools` / `hk schema` | — | no | which wrapped tools are present; argv templates |

A tool that is not there yet gives `{"error": "tool not present", "reason": "tool_missing", "tool": …, "path": …, "owner": …}` and exit 3, before any lease
or attempt is taken. `HK_TOOL_<KEY>=path` points a key at another file; `HK_ARGV_<KEY>='["{tool}", …]'` changes the argv
of `probe`, `ui_run`, `crashdoc`, `qemu` while those interfaces settle.

## 2. Attempt layout and index

```
attempts/
  index.jsonl                 append-only, one hk.index/1 line per write; the last line per id wins
  installed.json              recorded boot_b content
  queue/{pending,running,done,cancelled}/<qid>.json
  shell.jsonl                 every hk shell command (who, when, exit)
  census/<ts>/                hk crash --since …
  <YYYYMMDD-HHMMSS>-<name>/
    manifest.json             hk.manifest/1 (below)
    runner -> research/laguna-usb-fix/attempts/<ts>-<name>   (run-attempt.sh's dir, copied back by the bridge)
    ramdump -> runner/ramdump        console.txt -> live/console.txt
    live-<ts>-<name>/  or live ->    live_boot run (markers.txt, live.env, usbcon/)
    cycle/                    hk_cycle --out (report.json/summary.json, report.md)
    screens/ probes/ crashes/ logs/ return/ ui/
    hk-boot.log | hk-cycle.log | hk-back.log | REPORT.md
```

`manifest.json`: `id, name, kind (phone|qemu), created, created_by, agent (HK_AGENT), command[], queue_id, lease_holder,
image {name, dir, sha256, kernel_sha256, kind, cmdline, cpus, deadline, overlay, overlay_sha256, features}, kernel {mach,
sha256}, cmdline, features[], git {m1box {rev, dirty_tracked}}, owner_actions[{t, by, text}], paths {runner, live, cycle,
ramdump, qemu}, result {rc, verdict, reader, markers[], end {kind deadline|panic, seconds, line}, park, ui, return_check,
crash_signatures[]}, updated`. `features` are the MAP `SUBSYS` ids, derived from the image name and boot-arg keys
(`FEATURE_NAME_RULES`, `FEATURE_TOKEN_RULES`). `end` is a quick look at the first panic line of the ramdump; crashdoc and
hklog split boots exactly.

Example: `hk find --feature wifi --since today` gives a7-wifi-join-r1, r2, r3 (deadline, reader PANICKED) from the imported runs.

## 3. Phone lease and queue

- Lease: `/tmp/fleet/hk-phone.lease.json` under flock `/tmp/fleet/hk-phone.lease.lock`; events in
  `/tmp/fleet/hk-phone.events.jsonl`. Fields: `holder, purpose, token, host, pid, pid_bound, acquired, expires, ttl, attempt`.
  States: free, held, expired (past `expires`), stale (pid-bound and its process is gone on this host). Expired and stale
  leases are reclaimed with an event. One lease covers the device **and** usbcon (the reader belongs to the boot that started it).
- A phone command (boot/live/cycle/back/ui/push/restart) **refuses** (exit 4, `lock_required`) unless the caller names
  itself: `--lock NAME` / `HK_LOCK=NAME` (held by NAME → inherited, left held; free → a pid-bound lease under NAME for the
  command, renewed every ttl/3, released after) or `HK_LOCK_TOKEN`. Every child gets the token, so `hk_cycle` or a UI script
  calling `hk …` does not deadlock. Someone else's lease → exit 4 `phone_busy` naming the holder. `hk lock check [NAME]`
  exits 0 only for the holder. An acquire over an expired/stale lease records `reclaimed_from {holder, state, note}` in the
  new lease and a `reclaimed-<state>` event with `by` and `note`, and says so on stderr.
- `hk queue run` holds per item under `--lock`/`HK_LOCK`/`--holder`, default `hk-queue-runner`.
- Queue: `hk queue add IMAGE [UI] [EXPECT]` is pending and NOT admitted; `hk queue admit QID` is the phone owner's or the
  coordinator's step (COORDINATION.md). `hk queue run [--once|--follow]` is the single runner: oldest admitted item first,
  the lease per item (released between items, so attended work can interleave), a busy phone puts the item back. No retries.

## 4. Interfaces for the other owners (adopt or tell me; hk adapts by template)

1. **HARNESS (`tools/hk_cycle.py`)**: hk calls `--image DIR --name N --out attempts/<id>/cycle [--mach --ui --expect
   --deadline-wait]` and reads `summary.json` (preferred) or `report.json`: `verdict`, `return_check_verdict` or
   `return.check.verdict`, `ui.verdict`, and the runner attempt dir as `attempt` or `attempt_dir`. Please print `live run DIR`
   and `attempt dir: DIR` (it does). **Mismatch found:** hk_cycle's default `--ui-cmd` passes `--json {json}`, which
   `tools/ui_run.py` does not accept (its argparse has run, script, `--home-timeout --stop-on-fail --no-snap --check
   --tesseract --python`; it writes `<run>/ui_run.json` itself). One of the two should change; hk uses `ui_run.py RUN SCRIPT`.
2. **DBG2 (`hk_shell`)**: hk speaks the existing protocol (banner, `ios:<cwd> # ` prompt, `[exit N]`, `help`). Push and
   restart need two builtins, since the root has no shell, cat, kill or launchctl:
   - `put PATH SIZE MODE SHA256\n` followed by exactly SIZE raw bytes; write to PATH.tmp, fsync, rename; reply
     `[put ok SIZE SHA256]` (the hash of what was written) or `[put err <errno text>]`. Only under /private/var.
   - `kill -SIG PID` (TERM, KILL, HUP); reply as any command, `[exit 0]` or an error line.
   - list both in the `help` line (`builtins: cd pwd setenv help exit put kill`); hk feature-detects them from `help`.
   Optional: `get PATH` (`[get SIZE SHA256]` + bytes) for pulling crash logs. `tools/test_hk.py ShellServer` is a reference model.
3. **DBG1 (net)**: hk reaches 192.168.77.2:2222 from the Mac (the ECM link is Mac↔phone) with a Python client sent through
   `mac --`; `HK_SHELL_ADDR` overrides the address, `HK_SHELL=tcp:HOST:PORT` a direct path (e.g. a forward). The Mac side's
   ECM alias step (NET.md step 4, sudo) is still manual; hk does not run sudo.
4. **VERIFY (`tools/probe_eval.py`)**: default argv `probe_eval.py INPUT --row ROW --json`, INPUT = the attempt's cycle dir,
   runner dir or kernel.log (or the live run dir with `--live`); stdout one JSON object with `verdict`. If the settled CLI
   differs, change `ARGV['probe']` (or set `HK_ARGV_PROBE`); an importable `evaluate()` can replace the subprocess later.
5. **CRASHDOC**: hk calls `crashdoc.py INPUT… --out DIR [--no-symbols]` and reads `signatures[]` (`sig, proc, kind,
   culprit.text, incidents, status, hints[].id`). Works with today's tool.
6. **QFARM**: `qemu_preflight.py IMAGE_DIR --json OUT [args]`; hk reads `verdict` and `run_dir`/`run` from OUT.
7. **OBS**: `hk logs PROC` uses hklog's `hkl/<prog>.log` (the `HKL <prog>[<pid>] ` prefix from OBS.md section 1) and its
   subsystem files; respawns come from `hk logs --sub proc`.
8. **UIDRV / DBG3**: `hk ui` needs a live run (`live.env` without `BOOT_RC`, console.txt written within 180 s); with an
   explicit `--run DIR` any run.
9. **CRASHDOC/VERIFY → MAP**: add `SIG:` lines (with the hint id in brackets) to the subsystem's MAP block when a hint lands.

## 5. Waiting on others (nothing here is phone evidence)

- **DBG1**: the ECM link has never run on the phone (NET.md). Until it does, `hk shell/push/restart/stacks --live` return
  `shell_down` (exit 6), and `hk state` reports `ios_shell: false`.
- **DBG2**: `put` and `kill` builtins (4.2) and a phone boot of live-r1.ovl. Until then `hk push`/`hk restart` exit 5
  (`unsupported`); `hk shell` already works with the existing protocol (host-tested against a model).
- **VERIFY**: present (e43b3d3); `hk probe` parses its `{attempts, rows[]}` output.
- **HARNESS/UIDRV**: the `--json` mismatch in 4.1.
- Coordination: carry `tools/hk*`, `tools/test_hk.py` and `docs/debug/` in a commit; nothing else in the repo changed
  (attempts/ is ignored). The m1box checkout is ahead of the worktree this task was started from (b11f5e7); these files
  were written in the main checkout, where the other agents' tools live.

## 6. Verification receipts

- `receipts/test_hk.txt`: `python3 -I tools/test_hk.py -v`, 22 tests OK: lease acquire/busy/inherit/release, expiry and
  stale pid reclaim, break rules; tool_missing JSON for probe/crashdoc/qemu/cycle/live_boot with no lease or attempt left
  behind; ingest of a runner + live dir into one attempt, find by feature and since; boot under the lease (the fake live_boot
  checks the token against the lease file) and the attempt layout; a boot refused while another holder has the phone;
  cycle report parsing; back from fastboot (only `oem force-fastboot off` and `reboot`) and its refusal in iOS; state per
  phone state; shell, push and restart against a model hk_shell with and without the builtins; queue admission, runner and
  busy phone; crash/probe/qemu wrappers; argv template override; MAP ids equal hk's feature ids; every `hk X` in the
  playbook exists.
- Real dumps, read only (temporary store first, then the main checkout's `attempts/`): `hk ingest --all` 267 attempts in
  2.7 s; `hk logs tccd`, `hk crash` (crashdoc, 2.2 s, int1: axui-punctuation-model, preferences-launch-watchdog, blazer-deadline
  hints), `hk stacks Preferences` (int1: main thread in mach_msg2_trap, PortReceive), and `hk shot --dump` correctly
  refusing int1's stale HKSCR1 record (exit 1, fb_png rc 4).
- `receipts/hk-tools.txt`: wrapped tool presence at the time of writing (probe_eval missing).

## 7. Finish pass (2026-11-03 late, HOST only)

- `hk status`, `hk probe` over all rows (probe_eval's real `rows[]` output; the old reader looked for a top-level `verdict`
  and got none), `--path RUN_DIR` on status/probe/crash/logs/stacks (imports the dir, idempotent), lock by name and
  `hk lock check`, device commands refuse without the lock, reclaim notes, error value `tool not present`.
- Bug fixed: `hk cycle IMAGE` / `hk qemu IMAGE` declared `extra` as `argparse.REMAINDER`, so every hk option after IMAGE
  (`--ui`, `--mach`, `--lock`, `--json`) went to the wrapped tool unparsed. Now only arguments after `--` pass through.
- Still open: the hk_cycle default `--ui-cmd` (4.1). `tools/hk_cycle.py` and `tools/live_boot.sh` run directly do not check
  the lease; `hk lock check` is the hook for them (`tools/hk lock check || exit 4`), for their owners to add.
- Receipts: `receipts/test_hk-r2.txt` (31 tests OK, including RealToolsTest: real probe_eval + crashdoc on a synthetic
  dump), `receipts/hk-lock-r2.txt` (`hk --help` and the lock against a temp lock dir; the real `/tmp/fleet` lease only read:
  free), `receipts/hk-dump-r2.txt` (`hk probe/crash/status/logs` over `research/laguna-usb-fix/attempts/20261103-205514-a7-ios-system-int1`,
  read only, temp store: 59 rows, works 12 / partial 10 / active 2; 12 crash signatures with hints; milestones home works,
  app-settings-about partial; and the `tool not present` JSON for probe and crashdoc).
