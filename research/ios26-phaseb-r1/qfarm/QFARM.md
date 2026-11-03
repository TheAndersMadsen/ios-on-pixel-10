# qfarm: QEMU pre-flight for phone images (2026-11-03, HOST tool + QEMU runs; nothing touched the phone)

Labels: **QEMU** = m1box rig, TCG, 1 CPU (`receipts/m1box-rig/CALIBRATION.md`: TCG matches the Mac's boot order, KVM does not
boot XNU). **HOST** = tool and host tests. QEMU results are QEMU results: they cannot show Tensor drivers, the panel or
phone timing. They do catch the regressions this tool exists for: a crash loop, a missing daemon, an overlay the kernel
rejects, a panic, all before a phone boot is spent.

## Tool

`tools/qemu_preflight.py IMAGE_DIR [--seconds N]` (sha `e1144dca…`). Default probes are in `tools/qemu_preflight.expect.yaml`
(`8e305260…`). Host tests are `tools/test_qemu_preflight.py` (`661918d7…`): 13 tests, OK. IMAGE_DIR is an `image_tool.py`
image (a7-ios-system-*) or a `chooser_ios_image.py` image. For a chooser image the tool follows `ios.dir` and checks that
the embedded iOS image hash and cmdline match that manifest.

Derivation (recorded in `RUN/preflight.json`):

| Part | Phone image | QEMU equivalent |
| --- | --- | --- |
| Kernel | manifest `mach` (payload's XNU build) | The file with that sha256, found under `research/` of the repo or the rig. **No QEMU rebuild:** the phone build boots on the rig's `mkadt --qemu` ADT (aud1-q-r1, cfg1-qemu-*, s2-sens2-* all ran phone kernels). If no file matches, the tool stops and names the hash. |
| Overlay | manifest `var_overlay` | The same file, sha256 checked (`--overlay` overrides it for negative tests and is recorded). |
| Root | ios_system partition (rd=ufsroot0, `blazer_ufs_root=ios_system`) | `ios26-phone-r3.img`, the bytes flashed to ios_system (A7.md), mapped read-only as the **UFS fake LUN** (`blazer_ufs_fake=PA blazer_ufs_fake_size=N`, from the harness). |
| Line | manifest `cmdline` | **harness**: debug/serial/cpus/rd/blazer_ufs*/msgbuf/launchd_disable_all_timeouts come from `qemu-ufsroot.py` (cpus 5 → 1). **keep**: keys proven in some rig run's `intent.json`. **keep-new**: software-only keys not yet on the rig (`atm_diagnostic_config`, `hk_ustack`). **drop**: phone hardware (touch, UFS host tuning, SSBS, DPU, battery, mem, thermal, gov, usbcon, RTC, backlight, keys, power key, haptics, bootcpu, GPU, Wi-Fi, BT, persist / GPT fake LUN) and any unknown key. Every dropped key is listed with its reason; `--keep KEY` forces one in. **add**: `runq.sh` TAIL observability (`sched_preemption_disable_debug_mode=0 wdt=-1 hk_usertrace=1 hk_top=30`). `blazer_deadline` keeps the phone value; `--deadline` changes it. |
| Run | `fastboot boot` | `research/ios26-apps-r1/tools/qemu-ufsroot.py` (rig harness): TCG, `--idle 0`, window max(12, root GiB + 5), shared slot lock, `--slots min(HACKIOS_QEMU_SLOTS, 3)`. |

Analysis of `console.log` (ramoops mirror) uses host seconds from `progress.txt`:

- **Milestones:** arm_init, root/pid1, overlay applied, launchd, usermanagerd, backboardd, SpringBoard, display on, PosterBoard,
  iconservicesagent.
- **Home equivalent (QEMU proxy):** the Home-time daemons (BUDGET.md §4) have spawned, backboardd and SpringBoard never
  respawned or crashed, and there is no panic. TCG draws no Home frame (apps PLAN r21-r25), so this proxy is not the phone's Home.
- **Per-daemon exec/respawn counts** (respawns = exec count - 1; xpcproxy exempt) and crash events (`usertrap:`, `userabort:`,
  `CRASH name reason`, launchd `exited due to`). The kernel truncates process names to 16 characters; these are mapped back
  to the exec names.
- **Overlay:** the kernel's mask line, its "N applied" count against the decoded overlay's in-mask records (hkcover group 19
  excluded), `varfs-overlay: bad overlay`, and a host decode of the overlay.
- **Panics:** the `blazer-root: deadline N s` panic is the recipe ending the boot, so it is reported as a note, not a fault.
- **Probes:** the expect rows are evaluated through the shared evaluator; see the next section.
- Exit codes: 0 PASS, 1 FAIL, 2 setup error. `--analyze RUN` re-analyses an existing run without starting QEMU.
  `--baseline RUN` lists lost milestones, missing daemons and respawn increases against an earlier run.

### Probe format (coordination)

The probe rows use the shared format: `id, feature, need/any/forbid, values{re,agg,min,max}, required, note, source`.
- **Evaluator:** `tools/probe_eval.py` (VERIFY) when it exists. It did not exist at the end of this work. Until then the
  tool uses `tools/hk_cycle.py`'s `evaluate()` (HARNESS; same rows; sha `1a398d11…` used here). The report names the
  evaluator and its hash.
- **Skipped rows:** rows with `phone_only: true` (or `ui` / `needs_input`) are listed as PHONE_ONLY and are not evaluated in QEMU.
- **Conditional rows:** a row with `if_arg: TOKEN` reports N/A unless the QEMU line holds TOKEN.
- **Respawn bounds:** top-level `respawn_max` (2) and `respawn_allow` (fairplayd.H2, which relaunches in QEMU without
  FairPlay; datamigrator).
- **Layering:** an image directory's own `expect.yaml` is loaded after the default file and replaces rows by id.
- **To do when VERIFY lands:** point `--expect` at `docs/probes.yaml`. If its top-level key is `probes:` instead of
  `expect:`, the loader already accepts it.

## int1 pre-flight (QEMU)

Command:
`python3 -I tools/qemu_preflight.py research/images/a7-ios-system-int1 --seconds 600 --name qf-int1-r1`.
Run dir: `/data/hackios-qemu/research/ios26-apps-r1/runs/qf-int1-r1`. Receipts: `receipts/qf-int1-r1.{txt,json,intent.json,
preflight.json,exit.json}`.

Inputs:
- kernel.int1 `0d0c99b2…` (Darwin 25.5.0 DEVELOPMENT_ARM64_BLAZER, Nov 1 23:52)
- overlay int1-r1 `c440b6ea…` (mask 0xa0080081)
- root ios26-phone-r3.img (read-only; `root_unchanged: true`)

Translation: 10 harness tokens, 15 QEMU-proven kept, 2 keep-new, 4 added, and the rest dropped as phone-only (listed in
the .txt). The QEMU line keeps `blazer_deadline=900 blazer_aks_wrap=1 blazer_netstack=1 hk_ustack=Preferences,MobilePhone
hk_overlay=0xA0080081`. The run ended on its 600 s runtime, before the 900 s deadline.

| Milestone | host s |
| --- | --- |
| arm_init / root + pid1 / overlay applied / launchd | 0 / 2 / 2 / 2 |
| usermanagerd | 11 |
| SpringBoard / backboardd | 26 / 46 |
| SWEET FB display on | 65 |
| iconservicesagent / PosterBoard | 94 / 236 |
| **Home equivalent** | **236** (UI stable) |

- **Respawns:** backboardd 1 exec, SpringBoard 1 exec, 0 crash events of any kind.
  - fairplayd.H2: 39 execs (allowed in QEMU).
  - com.apple.datamigrator: 6.
  - cfprefsd, corecaptured, keybagd, mount, usermanagerd: 2 each (normal: boot-task then daemon).
  - 123 distinct daemons exec'd. 0 usertrap, 0 userabort.
- **Panics:** 0.
- **Overlay:** mask 0xa0080081, 52 entries, **18 applied = 18 expected**, 0 rejected. hgltrack.dylib is applied
  (backboardd's `HGLTRACK:` line comes from it) but has no per-record listing line. aud1-q-r1 shows the same, so it is a
  note, not a fault.
- **Probes:**
  - 11 evaluated, all PASS: root-on-ufs, overlay-applied, launchd, usermanagerd, backboardd (once, no trap),
    SpringBoard (once, no trap), home-daemons, no-lsd-abort, no-NSURL-nil (optional), no-panic, netstack-published.
  - 5 PHONE_ONLY: frame-display, power-key, haptics, RTC, backlight.
- `hk_ustack` (keep-new) started cleanly: `HK USTACK: every 5 s … names Preferences,MobilePhone; live request off`.
- **VERDICT: PASS.** The chooser path gives the same verdict: `qemu_preflight.py research/images/chooser-ios-int1 --analyze …qf-int1-r1`
  resolves to the same kernel, overlay and line (`receipts/qf-chooser-ios-int1-analyze.txt`).

So int1's kernel and overlay show no regression in QEMU: no crash loop, no missing daemon, no overlay failure, no panic.
That says nothing about the phone-only rows (keys, haptics, backlight, panel) or phone timing. Those stay the INT1.md §6
attended checklist.

## Negative control: does it catch a regression? (QEMU)

`qf-int1-neg-bitflip-r1`: the same recipe with one bit flipped in the overlay (`int1-r1.ovl` byte 4096 XOR 0x01 →
`816ce735…`, `--overlay /tmp/qfarm-neg/int1-r1-bitflip.ovl`), 180 s.
- **Guest:** panicked at 2 s, `varfs-overlay: bad overlay at pa 0xc02e00000, 671744 bytes: hash differs @varfs_seed.c:739`.
  QEMU stopped (`guest stopped`).
- **Pre-flight report:** **FAIL, 20 findings**:
  - the panic;
  - overlay rejected, and the overlay does not decode on the host either;
  - 9 milestones not reached;
  - the failed probes (root-on-ufs, overlay-applied, launchd … home-daemons, no-panic).
- `netstack-published` still passed: the kernel prints it during IOKit bring-up, before root (console line 123), which is correct.
- Receipt: `receipts/qf-int1-neg-bitflip-r1.{txt,json,intent.json}`.

The first pass of this run crashed the analyzer: it raised on the host decode of the corrupt overlay. That is fixed (the
decode error is now a finding) and covered by a test. Both runs were re-analysed with the final tool (`--analyze`). The
QEMU line was the same in both versions of the tool.

## Rig use

- **Slots:** at most 2 of mine at a time. Overall the cap was 3: aud1-q-r1 and one other guest held 2 slots, so the
  negative run waited for a free slot.
- **Cleanup:** both runs ended normally. Their backing files are deleted, and `root_unchanged` is true for both.

## Files

- **For git:**
  - `tools/qemu_preflight.py`, `tools/qemu_preflight.expect.yaml`, `tools/test_qemu_preflight.py`;
  - this file and `receipts/` (`SHA256SUMS` holds the tool, probe and test hashes, the bit-flip overlay hash and both console hashes).
- **Not for git:** the rig run directories and `/tmp/qfarm-neg/` (recipe above).

## Commit request (coordination; nothing staged here)

Paths: `tools/qemu_preflight.py tools/qemu_preflight.expect.yaml tools/test_qemu_preflight.py research/ios26-phaseb-r1/qfarm/`.
Message: "qfarm: tools/qemu_preflight.py, a QEMU pre-flight for phone images (kernel by mach hash, fake-LUN root,
translated line, shared probe rows); int1 PASS (Home equivalent 236 s, 0 respawns of backboardd/SpringBoard, 0 panics,
overlay 18/18); bit-flipped overlay control FAIL".

Proposed NOTES line: **QEMU pre-flight (2026-11-03, QEMU):** `tools/qemu_preflight.py IMAGE_DIR` runs a phone image's
rig equivalent (same kernel, overlay, ios_system bytes as the fake LUN, phone-only args dropped) and reports milestones,
respawns, panics and the shared probes. int1: PASS. A bit-flipped overlay: FAIL. `research/ios26-phaseb-r1/qfarm/QFARM.md`.
