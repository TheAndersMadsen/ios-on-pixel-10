# int3: one image that is both fully debug-instrumented and carries today's crash fixes (2026-11-03, HOST+ARM64+QEMU, not booted by this agent)

Labels: **SRC**, **HOST** (built/verified on m1box or the Mac), **ARM64** (symbols/disasm of the linked phone kernel),
**QEMU** (m1box TCG, read-only phone root r3), **PHYSICAL** (an earlier phone log, re-read), **INFERENCE**. This agent did
not touch the phone. Derived kernels/objects/overlays/images are not for git.

## Result

| Artifact | sha256 / id |
| --- | --- |
| XNU branch **`hk-int3`** (Mac nested repo) | **`3dc7fec3663746ed0390f360c3fa63031b970861`** = `hk-dbg12` 25d3978 (int2-ui dffc02d + DBG1 usbnet f6c0c6c + obs1 25d3978) + ABOUT `48b613b` cherry-picked (clean) |
| `kernel.int3` / `.unstripped` | `648b9f62c2a6b6b2086add8178fc1f8a7943347604a1bc9e1f2f81e9e1049641` / `8b520f8b6e91ec392c975277af060164946cc73975959ab79bd8a184732f796a` (`build/`, not for git) |
| overlay **`int3-r1.ovl`** (676,376 B, 65 records, 4 covers) | `898740adf222a87498e7331860f47ed9b020ac84d8ff496c4d99e04c616db2f3` (hkov_check hash `f2cd4bb0169afa58`; `overlays/`, not for git) |
| **`a7-ios-system-int3`** boot.img | **`eff0ed9ffac0e57512746409d0327711f9b91ac6fa0b25da395ed0504c89e0f5`** (payload `a4e4f8ba…`, margin 39,894,432 B; `research/images/`, not for git) |
| boot-arg line | **1000 bytes, 56 tokens** (≤ 1023). Only change vs int1 (1018 B): `−hk_ustack=Preferences,MobilePhone +hk_dbg=0x1e1e1f`. obs1 and ABOUT add **0** boot-arg bytes. |

`check`: `OK a7-ios-system-int3 bootable eff0ed9f…` with `image_tool_int2.py` **and** the shared `tools/image_tool.py` (Mac).
Manifest differs from int1 only in kernel (`mach` = int3), overlay (676376 B, int3-r1) and what follows (sizes, offsets,
payload, AVB, per-build ids). `receipts/manifest-diff.txt`.

## 1. What int3 is (the merge)

int3 is exactly the three already-built pieces in one image — nothing from jb1:

- **int2-ui** (hk-int2-ui dffc02d, UIDRIVE.md): live scripted input, live screenshots, `hk_screen`, stack sampler,
  crash info. Carried by `hk_dbg=0x1e1e1f` = input(0) + snap(1) + usertrace(2) + ustack Preferences,MobilePhone(3) +
  crashinfo(4) + hk_screen=30 + hk_top=30.
- **obs1** (hk-obs1 2841211, OBS.md): the daemon-log mirror (`HKL <prog>[pid]` for 11 daemons) + `HKOBS` driver-status
  lines + the kernel DYLD_INSERT_LIBRARIES merge. Overlay-only; **+0 boot-arg bytes**.
- **ABOUT** (hk-int2-about 48b613b, FIX.md): the overlay covers ml-en / ax-punct / ax-vopron **and** the narrow BlastDoor
  sandbox self-check kernel change. Overlay-only covers + a 2-file kernel commit; **+0 boot-arg bytes**.
- **DBG1 net log** (hk-usbnet-dbg1 f6c0c6c): already inside hk-dbg12; one console line per ARP/ICMP frame.

### Reconciliation with jb1 (research/ios26-jailbreak-r1, DESIGN.md) — jb1 NOT included

jb1 (`hk-jailbreak-r1` 5082189) is `hk-int2-about` 48b613b **plus** one consolidation commit that (a) *generalizes* the
sandbox self-check from ABOUT's narrow `blastdoor`-prefix exception to any declared embedded profile, (b) corrects op `0x43`
to one-byte booleans, and (c) adds `hk_inject_probe.dylib` injected into tccd + containermanagerd. None of (a)-(c) is
**strictly needed** for today's three crash fixes: ABOUT's narrow self-check already keeps `MessagesBlastDoorService`
(profile `blastdoor-messages`) alive, and op 0x43 is not implicated in any observed crash. Per the task's guardrail
("prefer hk-int2-about's narrow sandbox self-check; only pull a jb1 change if strictly needed; never re-introduce a blanket
allow-everything"), int3 uses **ABOUT's narrow change only** and omits the jb1 generalization, the op-0x43 change and the
probe dylib. (Neither ABOUT nor jb1 is the pre-ABOUT blanket "allow everything"; that bug — op 2 returning success without
writing a result — is fixed in both.)

## 2. Kernel (HOST build on the Mac, ARM64 verify on m1box)

- Branch made in a throwaway Mac worktree (`/tmp/hk-int3-wt`, removed; shared tree stayed on p1): `git switch -c hk-int3`
  off `hk-dbg12` 25d3978, `git cherry-pick 48b613b` — **clean, no conflict**. 48b613b touches only `bsd/kern/sweet_amfi.c`
  (+38) and new `bsd/kern/sweet_sandbox_check.h` (+52); no hk-dbg12 commit touches either file; both share merge-base
  hk-int1 484717f. Result `hk-int3` 3dc7fec.
- `tools/build_int3.py` (= about/build_int2_about.py, names changed): exclusive `/tmp/fleet/kernel-build-slot.lock`, p1
  clean check, `mk.sh -j8` **rc 0 (58 s)**, then **p1 b228c4f restored and rebuilt, rc 0**; the restored p1 kernel has no
  `HK USTACK` string. The tree is p1, clean. `receipts/` (build log on the Mac).
- **ARM64 verify** (`receipts/kernel-verify.txt`, llvm-nm/objdump on m1box): Mach-O arm64, **0 undefined symbols**. Present:
  int2-ui `_hk_dbg _hk_dbg_bits _hk_dbg_log _hk_ustack_start _hk_top_start _user_exception_trace`, `SweetHIDButtons`
  liveSubmit/liveStart/key (live HID), strings `HK DBG: hk_dbg=`, `HK USTACK: every`, `HK SCREEN` (5), `HK LIVE tap gen=`;
  obs1 `_hk_obs_start/_exec/_exit/_console/_tick/_final/_panic _blazer_usbcon_obs`, strings `HKOBS %u %s t=%llu %s: %s`
  and `rules' libraries in one DYLD_INSERT_LIBRARIES`; ABOUT `_sweet_sandbox_syscall` (op-2 path `cmp w19,#0x2` → `_copyin`
  → `_IOCurrentTaskGetEntitlement` → entitlement byte compare) and `_sweet_sandbox_self_logged`, string
  `self-check: sandboxed`; DBG1 `_blazer_usbnet_mode`. (The literal `blastdoor` is absent because the commit byte-compares
  immediates after `IOCurrentTaskGetEntitlement` rather than embedding a string — matches FIX.md §4.)

## 3. Overlay (HOST, m1box)

`tools/int3_overlay.py` applies obs1's two record edits to ABOUT's overlay:
`int2-about-r1.ovl` (edbd799a; int1-r1's 52 records + the three group-19 covers) → record **[39]** hk_env becomes the
11-daemon `hk_logmirror` rule and record **[50]** becomes `/private/var/hk/hk_logmirror.dylib` (0efadc03, 51,040 B). Every
other record — including the 13 ABOUT cover records [52..64] — is byte-identical (asserted). Result: **65 records, 4 covers**
(int1 `coreui-colour` + ABOUT `ml-en` / `ax-punct` / `ax-vopron`). hk-int1's own `hkov_check`/`hkov_cover_check`
(`research/ios26-phaseb-r1/about/tools/check_overlay.c`, release-pinned `varfs_overlay.h`): **ok, 65 entries, 676376 bytes,
hash f2cd4bb0169afa58, mask 0xa0080081 ⊆ groups, covers 4** (`receipts/overlay-check.txt`, `receipts/overlay.json`).

## 4. Image (HOST, Mac)

`tools/mkimg_int3.sh` = int2-ui's `live/uidrive/tools/mkimg_int2.sh` with the int3 kernel, the int3 overlay and `image_tool_int2.py`
(the hk_dbg allow-list). Boot line **byte-identical to int2-ui's** (1000 B). `check` OK with both the pinned tool and the shared
`tools/image_tool.py`. The shared `tools/image_tool.py` was **not** edited. `receipts/image-build.txt`, `image-check.txt`,
`manifest-diff.txt`, `inputs-verify.txt`, `image_tool.sha256`, `SHA256SUMS`.

## 5. QEMU proof (m1box TCG, read-only phone root r3)

**qf-int3-r2, VERDICT: PASS (0 findings)** (`receipts/qf-int3-r2.txt`, `qf-int3-r2.json`; 600 s TCG, root r3 read-only,
run dir `/data/hackios-qemu/research/ios26-apps-r1/runs/qf-int3-r2`). The image's real boot line was booted faithfully with
`--keep hk_dbg=0x1e1e1f` (the pre-flight otherwise drops `hk_dbg` as an unknown-to-the-rig token; an initial run without
`--keep` failed only that one phone-only probe, so it was superseded).

- Home-equivalent at host 296 s (PosterBoard + iconservicesagent spawned; backboardd/SpringBoard each exec once, never
  respawned or crashed). **panics: 0.** TCG draws no Home frame (phone-only).
- `overlay-65` PASS: `varfs-overlay: … 65 entries, 676376 bytes, hash f2cd4bb0169afa58`. `about-covers` PASS:
  `hkcover: 4 of 4 covers from the overlay`.
- `obs-dyld-merge` PASS (`hk_env: SpringBoard: 2 rules' libraries in one DYLD_INSERT_LIBRARIES`); `obs-hkobs` PASS
  (`HKOBS … tick`); `obs-mirror` PASS (`HKL SpringBoard[…] -- mirror on: …`, budget drops 0).
- `no-blastdoor-sandbox-crash` PASS and `no-ax-crash` PASS — zero-event in TCG (BlastDoor/AccessibilityUIServer did not
  launch in this run; see the scope note). `no-lsd-abort`, `no-NSURL-nil`, `no-panic`, `netstack-published` PASS.
- `hk_dbg-parsed` is PHONE_ONLY (the `HK DBG:` line is `blazer_usbcon_start`-gated; no DWC3 USB console in TCG).
- Respawns: only `fairplayd.H2` and `com.apple.datamigrator` (expected QEMU-without-hardware relaunching, `respawn_allow`);
  no int3-relevant daemon respawned. The systemic prune-crash apps (§6) did **not** prewarm in this TCG run, so they are
  neither proven nor disproven here — they are PHYSICAL-only (as on the int2 phone boot).

**Scope note (important):** QEMU uses the same read-only phone root r3, so int3's overlay presents only its 4 covers. The
systemic pruned-resource prewarm crashes below are a **root (r5)** problem that int3 does not address; wherever TCG prewarms
those apps they abort in QEMU as on the phone. The int3 proof asserts int3's own provable positives (boot to Home-equivalent,
0 panics, overlay applied, 4 covers mounted, obs mirror running, no BlastDoor sandbox crash) and records the prune crashes as
root-r5 evidence rather than forbidding them (`qemu_int3.expect.yaml`).

## 6. Systemic pruned-resource crashes — root r5, NOT int3 scope (PHYSICAL, from the a7-ios-system-int2 live boot)

Live console `research/laguna-usb-fix/attempts/live-20261103-230031-a7-int2/console.txt`. SpringBoard prewarms stock apps and
these SIGABRT/SIGTRAP at boot (`CRASH … code 0x6`/`0x5`): **MobileSMS, Preferences, FaceTime, Health, Photos,
AppleVisionProApp, Freeform, Journal, VoiceMemos, Magnifier** (Phone draws white). Shared cause: the r3/r4 prune stripped
`Assets.car`, `*.mom/*.momd` and plist resources from the staged apps and their linked frameworks.

- **ABOUT's About fix is mis-targeted (confirmed):** in stock `MusicLibrary.framework`, `MLSortMapTables.plist` (1218 B) and
  `SortingDetails.plist` (93 B) live at the **framework root**, only `MLSections.plist` (286 B) is in `en.lproj/`. ABOUT's
  `ml-en` cover mounts all three into `en.lproj`, so the framework root still lacks `MLSortMapTables.plist` →
  `pathForResource:` does not resolve it → About still aborts (PHYSICAL: int2 About SIGABRT at +67 s). int3 carries ABOUT's
  cover unchanged; About will still abort until root r5. A directory ramfs cover over the framework root would shadow its
  binary / `Support/medialibraryd` / `_CodeSignature`, so this is **not overlay-fixable** (FIX.md's own caveat).
- **Why this is not int3's artifact:** 10+ apps × their linked frameworks far exceed the 8-cover overlay limit, and the fix
  is restoring files on the read-only root, i.e. a new **root image**. Deploying it is a destructive `ios_system` flash that
  needs separate concrete owner approval (COORDINATION.md) and belongs to the apps/root lane.
- **int3 is the instrument for root r5:** unlike int2 (which dropped `hk_usertrace`), int3 re-enables `usertrace`+`crashinfo`
  (hk_dbg bits 2,4) and the obs1 `HKL` mirror, so a single int3 boot yields the per-app `usercrash:`/`userabort:` stacks and
  os_log for exactly these apps — the authoritative list of which resource each app loads, which root r5 needs.
- **Recommended root r5 (apps/root lane, separate task + flash approval):** re-stage the stock apps restoring the pruned
  resource *classes* (`Assets.car`, `*.mom`/`*.momd`, `MLSortMapTables.plist`/`SortingDetails.plist` at their real paths, and
  the `*.lproj`/plist each app loads) for the full prewarmed-app set and their linked frameworks, keeping only the
  Mach-O/codesign stage steps. Acceptance: every prewarmed app opens without SIGABRT. List driven by an int3 boot's crash
  stacks. See `research/ios26-apps-r1/root-r4/PLAN.md` §next.

## Files

- `INT3.md` (this file); `tools/build_int3.py`, `tools/int3_overlay.py`, `tools/mkimg_int3.sh`; `qemu_int3.expect.yaml`.
- `receipts/`: `kernel-verify.txt`, `overlay.json`, `overlay-check.txt`, `inputs-verify.txt`, `image-build.txt`,
  `image-check.txt`, `manifest-diff.txt`, `image_tool.sha256`, `SHA256SUMS`, `qf-int3-r1.txt`, `qf-int3-r1.json`.
- Derived, not for git: `build/` (kernel.int3{,.unstripped}, `obj/`), `overlays/int3-r1.ovl`, `research/images/a7-ios-system-int3/`.
