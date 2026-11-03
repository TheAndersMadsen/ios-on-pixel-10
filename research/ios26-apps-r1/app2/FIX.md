# app2: sandbox token, tccd visibility, and why Home shows only Settings and Phone (2026-11-03, m1box + Mac, no phone)

Evidence labels: **STATIC** (disassembly), **SRC**, **HOST** (host test/build on the Mac or m1box), **QEMU** (m1box TCG),
**PHYS** (earlier phone logs, none new). Nothing here touched the phone.

## 0. Result

| Item | Status |
| --- | --- |
| 1. Kernel: sandbox op 5 writes `"invalid"` into argument word 4, returns 0 | Done. XNU branch `hk-sandbox-token` 237a8b5 (parent cc42295). Host test PASS, 4/4 mutations killed. Kernel `kernel.rootview-bl-app2` b875e3e3…. QEMU r26: r23 counters unchanged, 0 traps (4). |
| 2. Overlay: `/private/var/mobile/Library/TCC` and the tccd log mirror | Done (overlay `app2-r1` 0eb06481…). The mirror is a dylib, because the phone root is read only (2.2). **No TCC.db seed**, because tccd's own code shows a DB row would not change the answer (2.3). QEMU r26: tccd log mirrored, TCC.db created in the new dir, AddressBook granted to entitled daemons (4). |
| 3. Why only Settings and Phone are on Home | **The phone root has no other visible stock app bundles.** It is not an lsd registration or icon-state fault. It cannot be fixed in the overlay (3). |
| Image `a7-ios-system-app2` | boot.img **b06e271fa74cae684e43efecf7d3861f770d27acbe5d039fef7b38619212a3d9**, `check` OK, cmdline identical to r10-perf. Built, not booted. |

## 1. Kernel: extension issue answers libsandbox's no-op token

STATIC (dsc-r6, libsystem_sandbox):
- `sandbox_extension_issue_file_to_process` (0x2a4413e30) and the other issue wrappers go through one helper, 0x2a4413ea4.
- The helper does `buf = malloc(0x3ff0)`.
  - If flag bit 0 is set, it does `strlcpy(buf, "invalid", 0x3ff0)` and returns buf, with no syscall.
  - Otherwise it builds 7 u64 words on the stack, `{x0, w1, x2, flags, buf, (s64)x4, w5}`, and calls `__sandbox_ms("Sandbox", 5, &words)`.
  - On a nonzero result it frees buf and returns NULL.
- So word 4 is the output buffer, and the buffer size (0x3ff0) is not passed. This confirms crashes-r9/FINDINGS §2.

SRC change (`research/ios26-apps-r1/app2/xnu-src/`, applied by `build_app2.py`):
- New `bsd/kern/sweet_sandbox_issue.h`: pure C, included by the host test. `ssi_issue_target()` picks word 4 and refuses 0.
  `ssi_token` is `"invalid"`, 8 bytes with its NUL.
- `sweet_amfi.c` `sweet_sandbox_syscall`, case 5:
  1. `copyin` the 56 bytes.
  2. A NULL buffer returns EINVAL.
  3. Otherwise `copyout(ssi_token, word4, 8)` and return 0.
- Case 6 (consume) stays ENOENT. libsandbox's consume returns 0 for `"invalid"` without a syscall.
- The first-use log `SWEET Sandbox: <proc> op 5` is unchanged. Always on, with no boot-arg. Nothing is enforced, so nothing is extended.

HOST:
- `tests/run.sh`: a model of libsandbox issue/consume over a fake kernel, run with ASan/UBSan.
  - Checks that the token lands in word 4 whatever the other words hold, that nothing is written past the NUL, and that consume takes it with no syscall.
  - Checks that a NULL buffer gives NULL as before, that flag bit 0 never reaches the kernel, and that a real token still goes to op 6.
  - Result: **PASS**. Mutations killed: word 4→5, the NULL check, the token text, and an extra NUL. `receipts/tests.txt`, and Mac `build/tests-mac.txt`.
- Build `xnu-src/build_app2.py`:
  - Takes the `/tmp/fleet/kernel-build-slot.lock` and refuses a dirty tree.
  - Verifies `hk-aks-usersession` = cc422959….
  - Creates the new branch, commits, and builds with `mk.sh -j8`. It then restores `p1` (b228c4f) and rebuilds it (rc 0).
  - Log `build/build_app2.out`. Mac logs `research/ios26-release-r1/logs/app2-build.log` and `app2-restore-p1-build.log`.
  - Note: after my restore, another owner's build took the lock and the tree is now on `hk-bright-brt1`. That is theirs.
- Artifacts:
  - `build/kernel.rootview-bl-app2` **b875e3e30d643b5b82965e6a6470dd9a4017a6e57a33e73a859b6e594dcb0d13**.
  - Unstripped 9ab8057737e4bf03adfc636ca5cc2b0eae126314d130755f1dfa8319c0b78570.
- Contents of the unstripped kernel: `_sweet_sandbox_syscall`, `_ramfs_renamex` (the varfs fix), the AKS user-session and `hk_persona` strings.
- Disassembly of the arm64 `sweet_amfi.o` (`build/sweet_amfi.o.otool.txt`), op 5 path:
  `copyin(x2, sp+0x20, 0x38)` → `ldr x1, [sp+0x40]` (word 4) → `cbz` → EINVAL / `copyout(token, x1, 8)`.

## 2. tccd: directory, log mirror, no seed

### 2.1 Directory
- The root's `private/var.skel.tsv` (phone-r3) has `/private/var/mobile/Library` (711 501:501, line 197) and no `Library/TCC` row
  (`receipts/root-phone-r3.txt`).
- tccd (b6e6238c…, job `UserName mobile`) opens `%s/TCC.db` under `Library/TCC`.
- The overlay adds `d 0755 501:501 /private/var/mobile/Library/TCC` in group 0. This is equivalent to the asked `var.skel` line; the skeleton itself is on the read-only root.

### 2.2 Log mirror (the root cannot be edited)
- `edit_logmirror_lsd_umd.py` edits the job plist (`StandardErrorPath=/dev/console`). The phone boots `ios_system`, which is
  read only and changes only by an owner-approved flash. So the mirror goes through the overlay.
- `src/hk_stderr_console.c` is a dylib. Its constructor, gated by `HK_STDERR_CONSOLE=1`, opens `/dev/console`, `dup2`s it onto fd 2 and prints one
  line `HKSTDERR: <prog>[pid] stderr -> /dev/console`.
- New hk_env rule: `tccd:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_stderr_console.dylib;HK_STDERR_CONSOLE=1;OS_ACTIVITY_DT_MODE=YES`.
  - DT mode needs the AMFI dyld policy bit, which arm64e processes get (sweetarm64e=1).
- HOST: `tools/build_stderr_console.sh` with the console path pointed at a temp file. `receipts/stderr_console/host-test.txt`:
  - gate off or 0: stderr untouched, nothing written to the console;
  - gate 1: the banner plus the program's stderr arrive on the console;
  - result **PASS**.
- Device dylib: arm64e, iOS 26.0, `pacstrip --sign` ("no PAC code"), `codesign --verify --strict` OK,
  **a630a41b80d15a2726105217d1c81d66d9348ccc0198bc7ec5b93f34e62d5837** (50,192 B).
- Expected lines on the phone, all from tccd's strings: `AUTHREQ_CTX`, `AUTHREQ_RESULT: … authValue=…`,
  `Granting … via entitlement 'com.apple.private.tcc.allow'`, `Failed to open database`, `Couldn't create the database for this path`,
  `Failed to create a SecTaskCreateWithAuditToken() for PID`, `Open accessory database failed as it's before device first unlock`.

### 2.3 Why there is no TCC.db seed (STATIC, tccd strings)
- The schema is in the binary: admin `version` 32, with tables `access`, `policies`, `active_policy`, `access_overrides`, `expired` and `integrity_flag`.
  A seed could be built from it exactly.
- But MobilePhone holds `com.apple.private.tcc.allow` = […, AddressBook, …] (crashes-r9 §1).
  - tccd answers such services with `Granting %@ access to %@ via entitlement 'com.apple.private.tcc.allow'`.
  - It also says `Default Allow for: Client %@ to %@ will not be stored in database`.
- So the entitlement path neither reads nor writes `access`. An allow row would not change MobilePhone's result. It would only add a variable and an
  unverified `csreq`/`auth_reason` choice.
- The mirror decides the next step:
  - "Granting … via entitlement" appears and Phone still traps: the fault is after tccd (Contacts' client side).
  - A DB/open error appears: the TCC directory or the database is the cause.
  - `SecTaskCreateWithAuditToken` fails, or the entitlement is not seen: the kernel csops_audittoken path.

### 2.4 Overlay `app2-r1` (`tools/app2_overlay.py`, base perf-r1 95701ed9…)
- Output **0eb06481d31376b95684dbc6bc53a005adff7ae3e03e967a983f46e41605755e**: 661,592 B, 51 records.
- `receipts/decode-diff.txt`: 48 records byte-identical. [39] hk_env gains the tccd rule, appended last (710 → 821 B, 822 with NUL; max 1024).
  Appended: [49] the TCC dir and [50] the dylib (group 29, 0755 root).
- Release consumers (`tools/app2_consumer.c`, ASan/UBSan, pinned headers == `hk-sandbox-token`'s; `receipts/release-headers.txt`):
  - Every new record is written under 0xA0080081.
  - hk_deny is unchanged.
  - Only tccd's exec environment changes.
  - `receipts/consumer.txt`: **PASS, 292 checks**.
- QEMU variant `qemu-app2-r1` f5603849… = hgltrack-rebuilt 61c38161… plus the same three changes (`--qemu`, `receipts/transform-qemu.json`, `decode-diff-qemu.txt`).

## 3. Why Home shows only Settings and Phone

STATIC/HOST, read-only look at `research/ios26-root-r1/build-r3/ios26-phone-r3.img`, the image flashed to ios_system
(`receipts/root-phone-r3.txt`; it was already attached on the Mac by another session, verified with `hdiutil info`, and left attached):
- `/Applications` holds 206 bundles (+ a non-bundle).
  - Per `ios26-apps-r1/census.tsv`, its only Home-visible stock apps are **Preferences and MobilePhone**.
  - The other "visible" ones are stickers, internal or extension hosts, or need hardware or capabilities.
- Calculator, MobileSafari, MobileSMS, MobileTimer, MobileNotes, Camera, Photos, MobileMail and the rest (49) exist only as
  `/System/Library/AppPlaceholders/*.app`.
  - These hold PlugIns and lproj only; **0 of 49 have an Info.plist**. They are App Store re-download placeholders, never Home icons.
- `/private/var/staged_system_apps` is absent on the root and in `var.skel`.
  - That is where the IPSW keeps the 49 real bundles: 1,112.7 MiB per `receipts/candidate-inventory.json`, source `staged_system_apps`.
- QEMU's "Scanned 253 apps in /Applications" (r23) used `apps-logmirror-r14`. That root derives from `apps-full-r6`, where those 49 bundles were
  copied into `/Applications` (206 + 49 = 255, less ones without an Info.plist). The phone root never received them.

So:
- On the phone, lsd and SpringBoard show exactly what the root offers. The persona/varfs fix (cc42295) was the registration blocker.
- With it, Settings and Phone register and appear (PHYS r9-apps-ufs). SpringBoard's icon state is not empty; it lists the two apps that exist.

Not fixable in the overlay. The overlay format caps at 48 MiB, the image margin is ~40 MB, and the bundles are 1.1 GiB.

**Fix (owner decision, a flash of ios_system):** a phone root r4 = phone-r3 with the 49 staged bundles copied into `/Applications`,
as `apps-full-r6` did.
- ios_system is 24 GiB and phone-r3 uses 8 GiB, of which ~4.18 GB is free (inventory: "staged_content_exceeds_free_space": false).
- Afterwards: sparse image, readback hash, and the A7-READY flash procedure.
- Not built here: it needs the IPSW OS mount (`ios26-gps-r1/work/mnt-os`) on the Mac, disk is tight, and a flash needs the owner.
- Until then **Calculator cannot appear on Home**, whatever the kernel or overlay does.

## 4. QEMU (m1box TCG, one slot)

Run `app2-r26`:
- Setup is r23's: root apps-logmirror-r14 f67e3bc9…, the same argument tail, persona log, 600 s.
- Changes: kernel b875e3e3… and overlay qemu-app2-r1 f5603849….
- Intent `receipts/qemu-r26-intent.json`, launcher `tools/runq_app2.sh`, run dir
  `/data/hackios-qemu/research/ios26-apps-r1/runs/app2-r26`, result `receipts/qemu-r26.txt`.

QEMU results:

| | r23 control | **r26** |
| --- | --- | --- |
| exit / root unchanged | 0 / yes | 0 / yes (600 s) |
| uid-501 personas, INVALID_PERSONA, lsd aborts, "no personas" | 3, 0, 0, 0 | **3, 0, 0, 0** |
| `Scanned N apps in /Applications` | 253 | 253 |
| usertrap / userabort / panic | 0 / 0 / 0 | 0 / 0 / 0 |
| `SWEET Sandbox: containermanager op 5` | 1 | 1 |
| tccd os_log on the console | none | `HKSTDERR: tccd[33] stderr -> /dev/console`, then the full `[access]` log |

What tccd says (r26):
- `TCCDMainDatabase created for path: /private/var/mobile/Library/TCC/TCC.db`, `_sqlite3_integrity_check … returned (0)`,
  `using database version: 32`. The DB opens in the new directory, and no DB error appears.
- 21 `AUTHREQ_RESULT`:
  - 20 with `authValue=2, authReason=11` (granted via `com.apple.private.tcc.allow`), 12 of them for **kTCCServiceAddressBook**
    (contactsd, sharingd, rapportd, donotdisturbd, TelephonyUtilities, contacts.donation).
  - 1 denial: deviceaccessd / BluetoothAlways, `Unable to construct an identity` (Code=2; unrelated, recorded).
- So in QEMU, tccd identifies clients by audit token, reads their entitlements and grants AddressBook. MobilePhone does not run in
  QEMU (no Home in TCG), so its own request is the attended boot's question.
- 9× `Failed to issue generic sandbox extension for class: …`. STATIC (tccd b6e6238c, 0x100026458-0x100026578) shows this line is not a token failure:
  - On the non-"both" path the issued token goes into the reply's `extension` key, and the `generic_extension` slot is set to 0 on purpose.
  - That zero slot is what prints this line.
  - A NULL token would take 0x1000264e0 → 0x1000267c8 → 0x10006bad4, which logs `Failed to issue sandbox extension for class`. That line appears **0** times.
  - Inference: op 5 now hands tccd's clients a token. The old kernel's tccd was not mirrored, so there is no before/after comparison.
- Not shown in QEMU: Preferences' SafariCore path, because Settings is not launched in TCG.

Receipt: `receipts/qemu-r26.txt`. Run dir is 5.1 MB, with no backing files left. Kernel and overlay copies are in
`/data/hackios-qemu/research/ios26-apps-r1/app2/`.

## 5. Image `a7-ios-system-app2` (Mac `research/images/`, copied back; HOST build, not booted)

- Recipe: a7-ios-system-r10-perf's exactly (`ios26-phaseb-r1/perf/tools/run_mac.sh`, itself r9-apps-ufs's): `--phone-route ufsroot`,
  5 cores, bootcpu 0x200, canvas 1125x2511, deadline 300, the same phone-args.
- Only `--kernel/--kernel-sha` (b875e3e3…) and `--var-overlay/--var-overlay-sha` (0eb06481…) differ. Script `tools/run_mac.sh`.
- **boot.img b06e271fa74cae684e43efecf7d3861f770d27acbe5d039fef7b38619212a3d9**: payload 347808da…, margin 39,948,864 B, avb verify OK.
  `image_tool.py check`: `OK a7-ios-system-app2 bootable` (`receipts/image-check.txt`).
- **Cmdline diff vs r10-perf: none.** 1015 → 1015 B, 57 tokens, same order.
- Manifest diff (`receipts/manifest-diff.txt`):
  - mach (the kernel);
  - var_overlay (path, sha, 611,168 → 661,592 B, placed 0x98000 → 0xa4000), and what follows from it: kernel_end +0xc000,
    the plan addresses, payload, image and AVB size;
  - per-build values (ADT seed, nonces, epoch). Entry is unchanged.
- `tools.image_tool.py` is **b4909202…** on the Mac now (r10 used 45eadfe3…). Another owner changed the Mac's working copy in between.
  The check passes and the cmdline is identical, but it is a different tool hash.

## 6. Attended test (owner; bare `fastboot boot`, then the return check; nothing is written)

```sh
tools/bootios research/images/a7-ios-system-app2/boot.img a7-ios-system-app2 --mach research/ios26-apps-r1/app2/build/kernel.rootview-bl-app2.unstripped --wait 480
# then: force-fastboot off, reboot, return-check.sh attempts/a7-ios-system-app2-after-boot
```

1. Wait for Home, as with r10-perf.
   - Expected icons: **Settings and Phone only** (section 3). Say if anything else appears.
2. **Phone:** tap it once and wait ~10 s. Say whether a window appears or it bounces back to Home.
   - Expected: it may still trap. This boot is meant to make tccd's reason visible.
3. **Calculator:** not on Home with this root (section 3). Nothing to open. Searching is disabled (Spotlight denied in r10).
4. **Settings:** tap it, wait ~5 s, scroll, tap General, then back, then Accessibility. Then use it ~30 s, as in r10-perf's test.
   - New here: any screen that sets up Safari/AuthenticationServices data (the earlier SIGSEGV) should no longer fault.
5. Go Home, wait ~20 s for the ramdump.

Read-out (ramdump `kernel.log`):
- `SWEET Sandbox: containermanager op 5` once. **No** `usertrap: Preferences … EXC_BAD_ACCESS addr 0x0` with `x1 -> "invalid"`.
- `HKSTDERR: tccd[N] stderr -> /dev/console`, then tccd lines around the Phone tap:
  `AUTHREQ_CTX … service=kTCCServiceAddressBook`, `Granting … via entitlement`, `AUTHREQ_RESULT … authValue=`, or one of the errors in 2.2.
  Apply the 2.3 decision.
  - Look for a request whose `identifier=com.apple.mobilephone`.
  - `Failed to issue generic sandbox extension` is expected noise (section 4). `Failed to issue sandbox extension for class` is not.
  - If MobilePhone makes **no** request before it traps, the nil comes from Contacts' client side, before tccd: `isAccessRestrictedForEntityType:` (ManagedConfiguration).
- `MobilePhone[N] exception 6` at `main+0x1e2bc0` still means the CNContactStore nil (crashes-r9 §1).
- HKMAIN lines as in r10-perf (Settings watchdog is a separate open item).

Stop: any panic other than the 300 s deadline, Home lost, or a crash loop of backboardd, SpringBoard or tccd.
Rollback: r10-perf's or r7-touch's image (nothing persists).

## 7. Open

- Stock apps beyond Settings/Phone need the phone root r4 (owner flash, section 3).
- MobilePhone's Contacts grant: decided by the tccd mirror on the attended boot.
- Preferences' 0x8badf00d launch watchdog: unchanged (r10-perf's HKMAIN measures it).
