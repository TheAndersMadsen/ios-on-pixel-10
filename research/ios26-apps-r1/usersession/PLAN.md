# Apps: AKS user session vs. the real blocker (2026-11-03, m1box + Mac, no phone)

Evidence labels: **STATIC** (disassembly), **SRC**, **HOST** (host test or build), **QEMU** (m1box TCG),
**PHYS** (an earlier phone log). Inferences are marked.

## 0. Result in one paragraph

The VERDICT (`receipts/h3-static-r12/VERDICT.md`) inferred that per-user personas wait on
`MKBUserSessionLoadKeybagForUser` and our AKS stub. That inference was **wrong** for this device.
- On a non-split device, usermanagerd's foreground-user loader skips the keybag load (STATIC).
- `--init` already allocates the user's kernel personas without any AKS user-session call (QEMU, new persona log).
- The software user-session selectors (built, gated, host-tested) are **never called** in QEMU. QEMU result unchanged: r22 = r21.

What actually loses the personas is varfs. Foundation's atomic writes replace an existing file with
`renamex_np(RENAME_SWAP)`, and ramfs/varfs (`/private/var`) had no `vnop_renamex`. So every save of usermanagerd's
manifests over an existing copy failed with ENOTSUP, and the daemon came up with "no personas found for user".
With RENAME_SWAP in ramfs (one kernel change, always on):

| QEMU, same root/route/overlay, 600 s | r21 control | r22 +AKS user session | **r23 +varfs RENAME_SWAP** |
| --- | --- | --- | --- |
| kernel personas allocated for uid 501 (`hk_persona`) | 3 | 3 | 3 |
| lsd `INVALID_PERSONA` | 40 | 40 | **0** |
| `userabort: lsd` (lsd processes) | 20 (20) | 20 | **0 (1)** |
| usermanagerd `no personas found for user` | 3 | 3 | **0** |
| user-session AKS selectors called (2/3/6/65/96/97/98/117) | 0 | 0 | 0 |
| `/Applications/*.app` bundles lsd reached / MIBundle extension checks | 0 / 0 | 0 / 0 | **37 / 641** |

1800 s runs (r24 swap only, r25 swap + `blazer_aks_wrap=1 blazer_aks_usersession=1`): see section 4.
QEMU results are QEMU results. TCG reaches no Home frame in either control or fix (both `fb-final.png` show the Apple logo).

## 1. Evidence (STATIC, dsc-r6 and `research/ios26-root-r1/apple/dis/usermanagerd.otool`)

- `MKBUserSessionLoadKeybagForUser` (MobileKeyBag 0x1cb458174), in-process path (w5=1, usermanagerd's call at
  0x100046a88):
  1. `aks_get_system(uid)` (sel 14); 0 means done.
  2. Only on 0xe00002f0: read the session dict, `aks_load_bag` (sel 6: struct in = bag, scalar out = handle),
     `aks_set_system` (sel 5), then `aks_get_system` again.
  The base stub already answers sel 14 with success, so this call could never fail on our kernel.
- Selector map (immediates before the IOConnectCallMethod helper):
  - `aks_unload_bag` 4, `aks_load_bag` 6, `aks_save_bag` 3 (scalar handle → struct ≤0x8000), `aks_lock_bag` 13, `aks_get_system` 14
  - `aks_get_bag_uuid` 23, `aks_unload_session_bags` 55
  - `aks_set_keybag_for_volume_with_cookie_persona` 65, `aks_copy_volume_cookie_persona` 68
  - `aks_keybag_persona_create` 96 (3 scalars + DER struct, no outputs), `aks_keybag_persona_list` 97 (scalar → struct ≤0x2000),
    `aks_keybag_persona_delete` 98, `aks_keybag_persona_create_with_flags` 117
  - `AKSIdentityGetPrimary` 125, `aks_se_support_in_rm_is_set` 107
- `MKBUserSessionCreateKeybagForUser` / `CreatePersonaKeyForUser` are ObjC/XPC (to keybagd), not direct AKS calls.
- usermanagerd's foreground loader 0x1000442e4 (called unconditionally at the end of `--init`, 0x1000411a8):
  - At 0x1000450f8 it asks `splitUserVolumeEnabled` (selref 0x1000e4e08). When false, which is any non-shared-iPad
    device, it branches to 0x10004729c. That jumps over "loading keybag for session" and `MKBUserSessionLoadKeybagForUser`,
    straight to the exclaves check and the persona setup 0x100094d70 ("No personas for user %@ found, creating new set
    of default personas", "setup kernel personas").
  - The keybag load and its "Failed to load keybag for session" return-0 path apply only to split-volume (multi-user) mode.
- The persona manifest is saved with Foundation's atomic write ("Failed to save persona manifest: Failed to write data
  to disk atomically", 0x100093ea8).
  - Our XNU already carries `0052-sweet-hfs-rename-swap.patch` (kpi_vfs.c): "Foundation's atomic writes use RENAME_SWAP
    (usermanagerd: Failed to atomically swap writing file: Operation not supported)". It only falls back to
    `VNOP_EXCHANGE`, which HFS has and ramfs does not.
  - `/private/var` is varfs (ramfs) since `varfs=1`. dirs_cleaner already showed `RENAME_SWAP failed with errno=45` there.

## 2. Evidence (QEMU)

- Boot-task visibility: `--init` logs to `/var/logs/usermanagerd_init.log`, and its os_log never composes in a boot task.
  Three attempts were void, recorded so nobody repeats them:
  - r18: `hk_env=usermanagerd:OS_ACTIVITY_DT_MODE=YES`;
  - r19: varfs symlinks of both log files to `/dev/console`;
  - r20: plus `OS_ACTIVITY_MODE=debug`.
  None of them printed any line between `STARTING EARLYBOOT SETUP` and `DONE EARLYBOOT SETUP`. The kernel persona log
  replaced them.
- r21 (control, new kernel, `blazer_persona_log=1`): during `--init`, usermanagerd allocates
  - 99 (type 4) and 199 (type 6) for the system session;
  - **1000 (type 5), 100 (type 4) and 200 (type 6) for uid 501**.
  All return 0. The daemon is later asked for persona `FEEDEEEE-…-5555000001F5`, which is id 200, and answers
  "no personas found for user". So the kernel has the persona and the manifest the daemon loads does not. lsd then aborts
  with INVALID_PERSONA, as in r14/r15b.
- r22 = r21 + `blazer_aks_wrap=1 blazer_aks_usersession=1`: `SWEET AKS: user session on` once and identical
  counters. No process calls any user-session selector.
- r23 = r21 with RENAME_SWAP in ramfs: the table above.

## 3. The change (XNU branch `hk-aks-usersession`, Mac `research/ios26-release-r1/work/xnu`, base hk-aks-wrap 44689e0)

1. **eb2d19b** SweetKeyStore user-session selectors, gated twice (`-DBLAZER_AKS_USERSESSION=1` and boot-arg
   `blazer_aks_usersession=1`; requires BLAZER_AKS_WRAP).
   - Selectors: create_bag 2 (handle 1), save_bag 3 (16-byte record "HKUSBAG1"+handle, handle 1 only), load_bag 6
     (accepts only that record), persona create 96/117, list 97 (empty DER SEQUENCE), delete 98,
     set_keybag_for_volume_with_cookie_persona 65.
   - Refusals are logged (`SWEET AKS: user session sel N refused`).
   - Also `blazer_persona_log=1`: one console line per persona alloc/dealloc (bsd/kern/sys_persona.c).
   - Core `xnu-src/blazer_aks_usersession.inc`, host test `tests/run.sh` (ASan/UBSan, 4 mutations killed;
     `receipts/tests.txt`).
   - Inert in QEMU (section 2). It is kept because it is gated and logged, and because the attended boot can show
     whether the phone ever asks for these selectors.
2. **cc42295** ramfs `vnop_renamex`:
   - RENAME_SWAP of two non-directories (swap the two dirents' nodes under the mount lock, update both vnodes' identity).
   - RENAME_EXCL (EEXIST if the target exists, else rename).
   - Directory swaps and other flags stay ENOTSUP.
   - Always on (no boot-arg): it fixes a filesystem bug. No host test (ramfs has no host harness). Evidence is QEMU r23-r25.
- Patches: `patches/0001-…`, `patches/0002-…`. Build scripts `xnu-src/build_us.py`, `build_us2.py` (fcntl lock
  /tmp/fleet/kernel-build-slot.lock, refuse a dirty tree, restore `p1` b228c4f and rebuild it). Logs `build_us*.out`.
- Kernel `kernel.rootview-bl-aks-us2` (both commits) **d7f47431164650c96cbab32dde384a288c321f67adcaf69f37eccc3116133186**,
  unstripped 95469a16f2d670285e844ab09e9602e4b7cda32e3eeccd6480055ee88c95a751; `_ramfs_renamex` defined.
  First build (eb2d19b only) `kernel.rootview-bl-aks-us` 0745526e…, unstripped 43dcbef0….

**Trade-off (security):**
- This is a software keystore with no SEP. The wrap secret is per boot. The user-session "bag" holds no key at all,
  because `/private/var` has no data protection here.
- Nothing is hardware protected. Anyone with code execution on the device, or with a dump of RAM, has everything.
  If a later stage persists the secret on ios_data, anyone who can read ios_data can read the keychain.
- No Apple identity, attestation, escrow or SEP selectors are answered (AKSIdentity*, 107 and 125 stay unsupported).

## 4. QEMU measurements (m1box TCG, root apps-logmirror-r14 f67e3bc9…, overlay hgltrack-rebuilt 61c38161…, rd=ufsroot0)

Commands: `tools/runq.sh NAME KERNEL ROOT SECONDS "EXTRA"` (r14's argument tail), counters `tools/measure.sh`.
Run directories `/data/hackios-qemu/research/ios26-apps-r1/runs/usersession-*`. Receipts `receipts/qemu.json`.

| run | kernel / extra args | uid-501 personas | INVALID_PERSONA | lsd aborts (processes) | "no personas" | user-session sel calls | MI gather of the LS database | test registrar (`com.apple.calculator`) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r21 600 s | us 0745526e, persona log | 3 | 40 | 20 (20) | 3 | 0 | never reached | `all_applications` entered, lsd dies under it |
| r22 600 s | r21 + wrap + usersession | 3 | 40 | 20 (20) | 3 | 0 | never reached | same |
| r23 600 s | **us2 d7f47431**, persona log | 3 | **0** | **0 (1)** | **0** | 0 | **done**: scanned 253 apps in /Applications | `all_applications` entered, not returned |
| r24 ~1500 s* | r23 | 3 | 0 | 0 (1) | 0 | 0 | done (guest 16:17:30) | not returned by guest 16:22:51 |
| r25 ~1500 s* | r23 + wrap + usersession | 3 | 0 | 0 (1) | 0 | 0 (`user session on` 1) | done | not returned by guest 16:22:20 |

\* r24/r25 were launched for 1800 s; their launcher hit the agent's 30-minute background limit and took the guests
with it (no `exit.json`; backing files removed by hand). Consoles up to that point are complete.

Reading:
- The varfs fix removes the persona failure completely (40 → 0, 20 → 0 lsd aborts).
- lsd survives and MobileInstallation rebuilds the LaunchServices database:
  - `Scanned 253 apps in /Applications`, `Scanned 34 items in frameworks dir`, `Scanned 258 items in ExtensionKit`;
  - `MILaunchServicesDatabaseGatherer … Updated app extension data containers with parent bundle IDs`.
- r22 vs r21 and r25 vs r24 are identical: the AKS user-session selectors have no measurable effect.
- Not shown in QEMU:
  - The test registrar's `all_applications` enumeration does not return within ~23 guest minutes. lsd is quiet after
    the gather.
  - SpringBoard Home with icons: TCG shows only the Apple logo by 600 s in every run, control included.

So "registered apps" in QEMU is: the system LS database was built from 253 apps by lsd itself. A registration readback
(`registration_readback` → `all_applications` return) is still missing. Next QEMU step: one run longer than 30 min,
launched detached (`setsid`), to see whether the enumeration returns and what lsd waits on.

Void diagnostics, kept for the record: r18 (hk_env DT mode, kernel.rootview), r19 (root apps-umdlog-r19 40089577…, log
symlinks), r20 (r19 + OS_ACTIVITY_MODE=debug). The edit is `tools/edit_umdlog_console.py`.

## 5. Phone images (Mac `research/images/`, HOST build, not booted)

`mkimg.sh`:
- Recipe: r7-touch's (A7-READY step 6, accel-skip overlay f5d4c367…, 5 cores, bootcpu 0x200, deadline 300,
  canvas 1125x2511) with kernel d7f47431….
- image_tool needed `image_tool-usersession.patch`, applied on the Mac's working copy: allow
  `blazer_aks_usersession=1`, `blazer_persona_log=1`; b56ae2bd… → 45eadfe3….

| image | boot.img sha256 | cmdline vs r7-touch |
| --- | --- | --- |
| `a7-ios-system-r9-apps` (as asked) | d1be9fd23330844a8782f94d1026987a8b5abb63a3592bd2262e7c3d79049e19 | 1013 → 1012 B; −`hk_present_trace=1` −`blazer_battery_receipt=1` +`blazer_aks_wrap=1` +`blazer_aks_usersession=1`; order otherwise identical |
| `a7-ios-system-r9-apps-ufs` (variant) | 06514cdd044f8d5404c770dbc6045e8275e2b28bebb2ad04dcdf615e81611dc5 | 1015 B; as r9-apps, plus `rd=md0 blazer_ufs_mountroot=1` → `rd=ufsroot0`, +`blazer_persona_log=1` |

Both `image_tool.py check` OK, avb verify OK. Dropping `blazer_battery_receipt=1` (a diagnostic) was needed as well,
because only removing `hk_present_trace=1` left 1037 bytes.

**Why the variant exists (PHYS + QEMU):**
- On the phone the md0-mountroot route is launchd's "ramdisk" boot. Both A7 r3 and B1 logs show
  `Skipping boot-task` ×100, no `IN UMD_INIT`, and 686-710 `Unable to find persona with type 6`.
- So **r9-apps cannot create the user personas on the phone, whatever the kernel does**. It still tests that the new
  kernel boots like r7, and B1's wrap.
- Only `rd=ufsroot0` runs the boot tasks (QEMU r13-r25). That route has never been booted on the phone (none of 272
  local attempts). image_tool has it (`PHONE_ROUTES['ufsroot']`), without `rootfstype=hfs`, which QEMU always passed.
  This is the main risk of the variant.

## 6. Attended boot (owner; bare `fastboot boot`, then the return check; nothing is written: root read only, /private/var in RAM)

Order:
1. **r9-apps** (one boot; the kernel changes only).
2. If that is as r7, **r9-apps-ufs**.

```sh
tools/bootios research/images/a7-ios-system-r9-apps/boot.img a7-ios-system-r9-apps --mach research/ios26-apps-r1/usersession/build/kernel.rootview-bl-aks-us2.unstripped --wait 480
tools/bootios research/images/a7-ios-system-r9-apps-ufs/boot.img a7-ios-system-r9-apps-ufs --mach research/ios26-apps-r1/usersession/build/kernel.rootview-bl-aks-us2.unstripped --wait 480
# after each: force-fastboot off, reboot, return-check.sh attempts/<name>-after-boot
```

r9-apps pass:
- `SWEET AKS: wrap/unwrap on` and `SWEET AKS: user session on` once each.
- securityd sel 10 → 0x0 as in B1. No `refused`.
- Home, touch and Settings as r7. Return check PASS.
- Expected unchanged: Settings is the only icon, ~700 type-6 errors, `Skipping boot-task`.

r9-apps-ufs pass:
- Root mounts (`rooting on ufsroot0` or `BSD root: ufsroot0`), then `IN UMD_INIT` / `DONE UMD_INIT`.
- `hk_persona: usermanagerd alloc … uid 501 … -> 0` three times. `Unable to find persona with type` 0.
- **Home shows the stock app icons.** Opening one app (e.g. Calculator) shows its window.
- Return check PASS.
- Record: any `SWEET AKS: <proc> sel 2/3/6/65/96/97/98/117` line (it would mean the phone does use the user-session
  path), and any `user session … refused`.

Stop and keep the capture:
- no root mount on ufsroot0;
- any panic other than the 300 s deadline;
- a crash loop of usermanagerd, lsd, SpringBoard or backboardd;
- Home lost.

Rollback: r7-touch's image (nothing persists).

## 7. Not done / open

- No registration verdict on the phone. In QEMU, registration of a container app is shown only as far as section 4 says.
- RENAME_SWAP of directories (dirs_cleaner's swaps) is still ENOTSUP.
- The ufsroot route on the phone is untested.
- NOTES.md "Apps" line to replace (coordinator): see the suggested text in the final message of this run.
