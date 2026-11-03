# hk_cycle: one command, one unattended test cycle, one report (2026-11-03)

Status: **HOST evidence only.** `tools/hk_cycle.py` and its tests ran on m1box against fake adb/fastboot/mac. The
analysis ran on real physical dumps (pwr1 `20261103-201639`, int1 `20261103-205514`). No phone was booted or touched
while writing this; the coordinator runs the first physical cycle.

## Usage

```sh
cd /srv/dev/repos/personal/hackios
export PATH=$HOME/.local/share/phone-bridge/bin:$PATH ANDROID_SERIAL=...   # ANDROID_SERIAL optional with one phone
# a background run must keep stdin open (the bridge's stdin watchdog), e.g.:
sleep 7200 | tools/hk_cycle.py --image research/images/a7-ios-system-int1 \
    --mach research/ios26-phaseb-r1/int/build/kernel.int1.unstripped \
    --expect research/ios26-phaseb-r1/live/expect/int1.yaml          # [--ui ui/x.ui | --ui settings] [--deadline-wait S]
# chooser images go the bare `fastboot boot` route by themselves (mode auto -> plain):
tools/hk_cycle.py --image research/images/chooser-ios-int1 --mach research/ios26-phaseb-r1/int/build/kernel.int1.unstripped
# analysis and report again, no device (e.g. with a newer expect file):
tools/hk_cycle.py --report-only research/hk-cycles/<ts>-<name> --expect research/ios26-phaseb-r1/live/expect/int1.yaml
python3 -I tools/test_hk_cycle.py            # host tests
```

The output goes to `research/hk-cycles/<ts>-<name>/` (or `--out`):

| file | content |
| --- | --- |
| `summary.json` | `hk_cycle.summary/1`: verdict, exit code, rows `{id: verdict}`, errors, android, return check, home, crash signatures, screenshots. HUB (`hk cycle`) reads it |
| `report.md` / `report.json` | the full report: expectations, screenshots inline, crash table, respawns, HKMAIN, ustack, timings, phone states, return check |
| `cycle.log` | every step and every command, with its bound and rc; `cmd/NNN-label.out` holds each command's output (serials redacted) |
| `live_boot.out`, `screens/`, `ui/`, `analysis/` (`live.txt`, `dump.txt`, `boot.txt`, `crashdoc/`, `ustack-summary.txt`), `return-check/` | |

The live run and the attempt stay where live_boot and run-attempt put them (`research/laguna-usb-fix/attempts/`). Plain
mode writes both into the cycle directory. The report links them.

**Stable CLI** (HUB wraps it): `--image --mach --ui --ui-cmd --expect --deadline-wait --name --out --mode --busy-wait
--overwrite-mac --no-sync-tools --no-console --no-shots --shot-every --shot-step --max-shots --skip-image-check
--no-return-check --cache --poll --timeouts --report-only --attended --force-ui --builtin-eval`. Flags are only ever added.

## Steps, and what each one guards against

1. **Preflight** (nothing is written to the phone before the image passes):
   - arguments, and paths inside the checkout (the Mac mirror sees only those);
   - `image_tool.py check`, or `chooser_ios_image.py check` for a chooser;
   - the `--mach` LC_UUID present in boot.img (bootios's rule);
   - the Mac reachable (`mac --cd … git rev-parse HEAD`); a HEAD that differs is only noted, because every `mac repo`
     call uses `--force` (the Mac checkout may lag);
   - image and kernel on the Mac by sha256. A missing file is synced. A **different** file is refused
     (`MAC_COPY_DIFFERS`: mac repo would otherwise boot the Mac's bytes), unless `--overwrite-mac`.
   - The phone's state, read from `fastboot devices`, then `adb devices`, then `mac usb` (1209:0001..3 = shim/XNU, so
     **ios**; 18d1 alone = booting):
     - Android → `adb reboot bootloader`, then wait for fastboot;
     - recovery → refused (the owner picks "Try again");
     - **iOS → refused (`PHONE_IN_IOS`)**, or `--busy-wait S` waits for that boot's park. It never cold-resets, which
       would wipe RAM;
     - finally `fastboot getvar product` must answer.
2. **Boot.**
   - **bootios** (A7 images): `tools/live_boot.sh IMG NAME --mach K --wait W --sync-tools`. That is run-attempt with its AVB
     gate, force-fastboot on, `fastboot boot`, the park watch and the immediate ramdump, plus the live usbcon console. W
     defaults to the image's `blazer_deadline` + 180 s (int1: 1080).
   - **plain** (chooser images, which fail run-attempt's AVB gate):
     1. `fastboot oem force-fastboot on`, read back.
     2. The usbcon reader (live_boot's exact command line). Its lines go through live_boot's own marker filter, read out of
        live_boot.sh, so `console.txt`, `markers.txt` and `live.env` look the same.
     3. Bare `fastboot boot`.
     4. A park watch. A park counts only after the phone has left fastboot.
     5. On park, `mac repo --force --back … -- python3 tools/capture-fastboot.py …/ramdump --diagnostics`, then read-ramdump.
     A chooser that goes on to Android is recorded as `plain_outcome: android`. A cold-safe chooser has no console.
   - **Only one usbcon reader owns USB.** hk_cycle starts no reader of its own in bootios mode. Live screenshots
     (`tools/screenshot.sh RUN`, every `--shot-every` s once DISPLAY/CONSOLE_CONNECTED is seen, only with
     `blazer_usbcon_snap=1`) and the UI runner talk to live_boot's reader through `LIVE_SOCK`.
   - Every child runs in its own session with **stdin an open pipe for its whole life** (the bridge's stdin watchdog).
     Children are stopped by their process group id: never `pkill -f`, nothing that could match hk_cycle's own shell.
3. **Park.** `tools/screenshot.sh --dump ATTEMPT` writes the hk_screen PNG, and `fb_png.py --json` gives its reason, seq
   and identity. A stale record (previous boot) is shown as such, not as this boot's screen. `park-timeline.txt` gives the
   reset class. **A cold reset (RST_STAT class 0) is flagged: RAM was wiped, so only the live console counts.**
4. **Return.** It always runs, after a refusal, an error, a crash in hk_cycle itself, and the first two Ctrl-Cs:
   1. An iOS boot still running is left to reach its kernel deadline (`park_wait`, 1500 s). Never a cold reset.
   2. Android with force-fastboot possibly on (a chooser that booted Android) → `adb reboot bootloader` to disarm it.
   3. In fastboot: `fastboot oem force-fastboot off` (read back), then `fastboot reboot`.
   4. Wait for `sys.boot_completed=1`. Recovery means `PHONE_IN_RECOVERY`, which is left to the owner.
   5. `research/ios26-dualboot-r8/return-check.sh OUT`, and its `return-check.json` verdict.
   A phone the cycle never changed (a preflight refusal) is left alone: no reboot and no return check.
5. **Analysis** (the same code as `--report-only`):
   - Text: the live console (stamps stripped), and the dump's **current boot only**. The dump text comes from
     `live_profile.decode_dump`, the XNU-MSGBUF v2 ring framed by its XNUENT1 epoch. Raw `strings` of a dump mixes
     older boots: the int1 dump's raw strings hold 9 AccessibilityUIS `userabort` lines from earlier boots, and its
     current boot has none.
   - Row verdicts, below. Crashes: **`tools/crashdoc.py ATTEMPT LIVE_RUN --out analysis/crashdoc`** (CRASHDOC: boots split
     by nonce/slide, symbolicated, hints). The report lists only the signatures of the attempt's own boot(s) and counts
     the residue. The built-in usertrap/userabort grep (dsc_sym.py's lookup in process) is used only if crashdoc fails.
   - Also: respawns (`exec NAME` / `Successfully spawned` count − 1, xpcproxy excluded); `CRASH` and `exited due to` lines;
     panics (deadline or real); HKMAIN, the last periodic line per pid and stall frames;
     `ustack_sym.py --summary --main-only` when `HK USTACK:` lines exist.
   - **Home** (`analysis.home`, marker `HOME` for the rows): `UI_READY`, **or** `exec SpringBoard` + SweetHIDTouch open +
     SweetHIDButtons open + frames. The int1 live run never fired UI_READY: live_boot's SPRINGBOARD marker looks for launchd's
     `Successfully spawned SpringBoard`, and that line is not in the console, while `exec SpringBoard` is. This is interim
     until UIDRIVE.md fixes `wait_home`; the rule lives in `home_rule()`.
6. **Report.** Verdicts, in priority order:
   - `REFUSED`: preflight, phone untouched;
   - `PHONE_NOT_IN_ANDROID`;
   - `FAIL`: a required row FAIL, or a return check that is not PASS;
   - `ERROR`: a named error state;
   - `INTERRUPTED`;
   - `PASS`: every required row PASS and the return check PASS;
   - `COMPLETE`: no expect file, return check PASS;
   - `INCOMPLETE`: e.g. rows NOT_EXERCISED.

   Exit codes:

   | code | meaning |
   | --- | --- |
   | 0 | PASS / COMPLETE |
   | 1 | FAIL / INCOMPLETE |
   | 2 | usage |
   | 3 | refused |
   | 4 | boot error |
   | 5 | not in Android |
   | 130 | interrupted (after the return) |

Error states: BAD_ARGS, IMAGE_CHECK_FAILED, KERNEL_MISMATCH, MAC_UNREACHABLE, MAC_COPY_DIFFERS, MAC_SYNC_FAILED,
PHONE_IN_IOS, PHONE_IN_RECOVERY, PHONE_UNKNOWN, PHONE_NOT_FASTBOOT, FASTBOOT_UNRESPONSIVE, SERIAL_AMBIGUOUS,
UI_WITHOUT_CONSOLE, UI_WITHOUT_INPUT, UI_RUNNER_MISSING, CONSOLE_REFUSED (live_boot exit 3: the boot was not started),
FORCE_FASTBOOT_FAILED, BOOT_FAILED, BOOT_TIMEOUT, NO_PARK, CAPTURE_FAILED, FORCE_FASTBOOT_ON, RETURN_FAILED, INTERRUPTED,
INTERNAL, ANALYSIS.

**Ctrl-C** (also SIGTERM/SIGHUP):
1. The first stops the UI and the screenshots. The boot runs on to its park, and its ramdump is pulled.
2. The second abandons the boot: live_boot gets TERM, stops its reader and gets 40 s before its group is killed. The return
   still runs and waits for the deadline park.
3. The third abandons the return, and the report says the phone is left as it is.

Bounds: `--timeouts k=v,…`. The defaults are in `TIMEOUTS`, and each command's bound is printed in cycle.log.

## Expect / probes schema

A YAML (or JSON) file with `probes:` (or `expect:`), one row each:

```yaml
- id: S                      # unique
  feature: Settings responsive
  need:   [regex, ...]       # every one must match a line (re.M)
  any:    [regex, ...]       # at least one
  forbid: [regex, ...]       # any match -> FAIL
  values: [{re: 'touch=(\d+)', agg: max|min|last|count, min: 1, max: 9}]
  marker: HOME               # a live_boot marker (or the derived HOME)
  ui: about                  # the UI runner's step of that name must be ok
  needs_input: true          # without a UI run / --attended, missing evidence = NOT_EXERCISED (not FAIL)
  required: true             # false: shown, not in the verdict
  source: boot|live|dump     # default boot = live console + dump
  note: text                 # also allowed: readme, scope (probes.yaml bookkeeping)
```

Verdicts are PASS, FAIL, NOT_EXERCISED and NO_DATA.

**One evaluator.** When `tools/probe_eval.py` (VERIFY) exists, hk_cycle calls it, and its rows are the verdicts:
`probe_eval.py --probes FILE --text live=analysis/live.txt --text dump=analysis/dump.txt --markers M1,M2 --ui-json
analysis/ui-steps.json --json analysis/probe_eval.json`, expecting `{"rows": [{"id", "verdict", "evidence": [...]}]}`.
**This calling contract is my proposal; VERIFY has not confirmed it** (the file did not exist when this was written). If
the call fails or the output does not parse, the built-in matcher is used. `report.md` and `summary.json` (`evaluator`)
always say which one ran; `--builtin-eval` forces the built-in one. When VERIFY's CLI is fixed, only `Cycle.probe_eval()`
changes. QFARM's qemu_preflight should read the same files through the same evaluator.

Shipped (`research/ios26-phaseb-r1/live/expect/`):
- **`int1.yaml`** (INT1.md section 6). Rows: boot.root, boot.home, **S** (Settings responsive: netstack published, configd
  opens IONetworkStack, Preferences exec'd, HKMAIN pings ≥ 5 and touch ≥ 1, no Preferences crash), S.iokit_busy (info),
  **Ph** (Phone opens: MobilePhone exec'd, ustack or TCC lines, no trap), **A** (About: UI step `about`; the console has no
  About-specific line), ustack (info), T, Bt, K, H, B, end.deadline (info).
- **`pwr1.yaml`**: the pwr1 PLAN rows: boot.home, T, Bt, K.volume, K.power, H, B (info: pwr1 has no brt1 DBV drop), S,
  end.deadline.

Every pattern was checked on real lines. HOST runs on the physical dumps (attended boots, so rows were counted as exercised):

| file on dump | PASS | FAIL | known history |
| --- | --- | --- | --- |
| int1.yaml on the int1 dump `20261103-205514` | boot.root, boot.home, Ph, T, Bt, H, ustack, S.iokit_busy, end.deadline | **S** (that boot logged `CRASH Preferences … code 0x6`, touch 0); A (no UI); K (no volume press logged); B (DBV min 3138) | |
| int1 rows on the pwr1 dump | | S (no netstack), **Ph** (`usertrap: MobilePhone[415] exception 6`) | matches pwr1: no netstack, Phone trapped |
| pwr1.yaml on the pwr1 dump | all required rows, including K.volume (0xea down) and K.power (0x30) | B (info) | |

## UI runner (UIDRV) integration

`--ui SCRIPT` runs, once the live run exists, `python3 -I tools/ui_run.py {run} {script} --json {json}`. `--ui-cmd`
replaces it, with the placeholders `{run}`, `{script}`, `{json}` (`<cycle>/ui/ui_run.json`) and `{out}`. The runner must
wait for Home itself, and its JSON's `steps: [{name, ok|verdict}]` feed rows with `ui:`. `--ui settings` runs the existing
`tools/ui_settings_test.py RUN` and reads its `ui_test.json`. A UI script needs `blazer_usbcon_input=1` in the image, or
the kernel refuses input. **int1 drops it**, so `--ui` is refused on int1 (`UI_WITHOUT_INPUT`, `--force-ui` for snapshots
only), and int1's input rows are attended-only (`--attended`). `tools/ui_run.py` and UIDRIVE.md did not exist when this
was written: the command line is the assumed contract, nothing more.

## Host tests (`python3 -I tools/test_hk_cycle.py`)

The fake `adb`/`fastboot`/`mac` share one phone state machine (android, fastboot, ios, recovery; force-fastboot; park
timer; Mac file hashes). Each records its calls and **whether its stdin was an open pipe**. A fake `live_boot.sh` writes
live.env, console and markers, then the attempt with a synthetic v2 ramdump at its park. There are also fake
`screenshot.sh`, `return-check.sh` and usbcon.

Cases:
- Full bootios cycle from Android: PASS. It checks the force-fastboot-off-then-reboot order, `--wait` = deadline + 180,
  the inline PNGs, respawns, no serial in any file, and no forbidden fastboot verb (flash, erase, format, set_active).
- iOS at start: refused, phone untouched.
- Kernel not in the image; image check failure; Mac down; different Mac copy refused, then `--overwrite-mac`.
- Console refused, then the return to Android.
- No park: `PHONE_NOT_IN_ANDROID`, iOS left running, no cold reset.
- Ctrl-C ×2 during the boot: exit 130, the phone back in Android with force-fastboot off.
- Plain chooser: force-fastboot before `boot`, capture on the Mac, return.
- Plain chooser → Android: disarm via the bootloader.
- `--report-only`.
- Units: every row kind; schema errors; the shipped files parse; the home rule without UI_READY; redaction; dump decode
  with `\r` lines and usertrap continuations.
- The int1 rows on the real int1 dump.

Result: see `receipts/harness-tests.txt`.

## Not done / open

- No physical cycle yet. The first one should be int1 with `--expect …/int1.yaml`, once the coordinator's slot opens.
- probe_eval (VERIFY), ui_run/UIDRIVE `wait_home` (UIDRV) and `tools/hk` (HUB) did not exist yet. Each integration point
  is one function (`probe_eval()`, `ui_command()`/`ui_steps()`, `home_rule()`, `write_summary()`), and the stand-ins are
  labelled in every report.
- The live screenshots and the UI runner share live_boot's reader socket. Concurrent requests are serialized by the
  reader (INFERENCE from UNATTENDED.md's control-socket design, not measured).
- Files for the coordinator (nothing staged): `tools/hk_cycle.py`, `tools/test_hk_cycle.py`,
  `research/ios26-phaseb-r1/live/HARNESS.md`, `research/ios26-phaseb-r1/live/expect/{int1,pwr1}.yaml`,
  `research/ios26-phaseb-r1/live/receipts/harness-tests.txt` (force-add under research/).
