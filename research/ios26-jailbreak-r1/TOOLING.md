# jb tooling: writable packages, APT, and an hk_env tweak loader

Date: 2026-11-04. Scope: design only for the owner's own XNU/iOS 26 build on their own Pixel 10 Pro. No XNU
changes, builds, Git index operations, or phone access were performed for this document. **SOURCE** means the named
project source, **HOST/QEMU** means an existing named receipt, **UPSTREAM** means the linked public project, and
**INFERENCE/DESIGN** means a proposal still requiring implementation and validation. No physical tooling result is
claimed.

## 0. Decisions and reachability

| Question | Decision |
| --- | --- |
| Install prefix | Use the rootless-compatible **`/var/jb` spelling, backed by `/private/var/jb`**. It is writable in RAM varfs now; HKVAROV can seed it, but runtime changes are lost on reboot. |
| Persistent home | Put package payloads and all APT/dpkg state under that same prefix on `ios_data`. The current preferences snapshot cannot hold a real bootstrap. A small snapshot-v2 proof is possible after new persistence work; a real filesystem is the right full-bootstrapping target. |
| Bootstrap | Rebuild a minimal [Procursus](https://github.com/ProcursusTeam/Procursus) `iphoneos-arm64e-rootless` bootstrap for the iOS 26 SDK, then add the remaining packages. Do not assume prebuilt arm64e packages are PAC-compatible with the Pixel. |
| Package manager | Prove **APT/dpkg CLI plus a local signed repository first**. Use **Zebra 2** as the later user-facing UI reference. Sileo is the fallback; Installer's public legacy source is not a modern candidate. |
| Tweak loading | Keep one base loader in `/private/var/hk`, insert it with the existing **kernel `hk_env`** rule, and let it discover/dlopen package tweaks in `/var/jb/usr/lib/TweakInject`. Reuse ElleKit's injector/filter model and hooking APIs, not its launchd/task_for_pid loader. |
| Now, with jb1 plus new userland work | Ephemeral bootstrap, local APT/dpkg operations, one test package, and a constructor-only tweak in an already named daemon are plausible without another kernel feature. None is implemented or proven by this document. |
| Needs new work | Reboot persistence, a full bootstrap, arbitrary-new-target injection beyond the static `hk_env` budget, and real hooking if its executable-memory path hits policy. GUI package management additionally waits on app registration and any platform entitlement actually exercised. Stock ElleKit/Sileo task-port flows should be avoided, not enabled globally. |

The existing jb1 evidence is **QEMU, not PHYSICAL**: two signed dylibs loaded into `tccd` and `containermanagerd`,
with no daemon regression. Before any phone acceptance below, the coordinator must complete jb1's own temporary-boot
checklist in [DESIGN.md](DESIGN.md), including visible Settings interaction and the Android return check.

## 1. What the current build already provides

### 1.1 Read-only root, RAM `/var`, and HKVAROV

**SOURCE:** `ios_system` is mounted read-only. `/private/var` is RAM varfs, seeded from `var.skel` and then from the
selected groups of an `HKVAROV1` blob carried in the boot image. An overlay entry can create a directory, file, or
symlink, remove an entry, or append an `hk_env`/`hk_deny` rule. Files created or changed in varfs during the boot are
writable, but the overlay is a **boot-time seed, not a persistent backing store**.

Relevant limits in `varfs_overlay.h` are 48 MiB total overlay data and 4096 entries, with selected group bits and
last-selected-entry-wins behavior. Covers can expose overlay files over a read-only root directory, but do not make the
root writable. Therefore:

- `/private/var/jb` is a valid **ephemeral** install tree now.
- Rebooting the same image can recreate a fixed demo, which is not package persistence.
- A full Procursus installation must not be squeezed into the 48 MiB boot overlay. Only a minimal proof belongs there.
- Base policy and the tweak loader should remain in `/private/var/hk`, separate from package-managed content.

### 1.2 The existing `ios_data` store is narrow

**SOURCE/HOST/QEMU:** the current store saves only:

- `/private/var/preferences`;
- `/private/var/mobile/Library/Preferences`;
- `/private/var/root/Library/Preferences`;
- `/private/var/.blazer-persist-boots`.

It records directories, regular files, and symlinks with mode/uid/gid/mtime. It does not preserve hard links, xattrs,
or BSD flags. A file is capped at 4 MiB, paths at 1024 bytes, depth at 12, and entries at 65,536. Each of two slots has
2049 4096-byte blocks including its header, so the payload capacity is **8,388,608 bytes (8 MiB)**. Saves are periodic
whole-whitelist snapshots, with alternating slots, generation numbers, CRCs, read-back, and unchanged-write suppression.
Restore order is seed -> overlay -> saved copy, so a saved file overrules a newer overlay file on a whitelisted path.

The partition is 8 GiB, but the admitted table uses only `ios_data` blocks 2..4099. The physical checker currently
requires blocks 4100 onward to remain unchanged. The QEMU negative test passed with 12 saves and no writes outside the
approved table; **the physical persistence test has not run**, and `image_tool.py` still gates the feature to a pinned
kernel/profile. See [NEGATIVE-r1.md](../ios26-dualboot-r8/ios-data-persist/NEGATIVE-r1.md) and
[PHYSICAL-PLAN.md](../ios26-dualboot-r8/ios-data-persist/PHYSICAL-PLAN.md).

Consequences for packages:

1. Adding `/private/var/jb` to the current whitelist is **not sufficient**. APT/dpkg binaries exceed the per-file and
   per-slot limits, and dpkg expects useful rename/fsync/lock/crash semantics rather than a best-effort periodic copy.
2. Merely enlarging the slots would also enlarge the current whole-snapshot kernel allocations and I/O on every save.
3. Package state and payloads must share one committed generation. Restoring a new dpkg `status` with old binaries, or
   vice versa, is a broken package transaction.
4. If `/var/jb` becomes persistent, base-system updates should not be delivered by overlay files on the same paths;
   the saved copy would win. Package-managed files should be updated by APT. The base loader stays outside this tree.

### 1.3 The reusable injection mechanism

**SOURCE/QEMU:** `hk_env` is applied by XNU during exec, ahead of the job environment. Target names are executable
basenames, not launchd labels. Injected values precede job values, and `getenv` takes the first match. Consequently,
a second `DYLD_INSERT_LIBRARIES` rule does not merge with the first. The existing value must be edited to retain every
current library and append the loader with `:`.

The active grammar allows `:` inside values. Aggregate rules have a 1024-byte buffer including NUL; each `KEY=VALUE`
has a 384-byte limit. jb1 reports 974 bytes used, leaving 50 bytes. Appending one short loader path to an existing
insertion value is feasible after measuring the exact delta; adding arbitrary new target rules is not a scalable model.
The 48 MiB overlay and exec argument/environment limits also remain applicable.

The established owner-code recipe is an arm64e, iOS 26, ad-hoc-signed Mach-O processed by `pacstrip.py --sign`, then
strict codesign verification and a PAC scan. `sweetarm64e=1` grants the arm64e dyld path/insertion policy. Signature and
page validation stay enabled. A successfully inserted constructor banner, not the `hk_env:` kernel line alone, is the
load receipt. See [DESIGN.md](DESIGN.md) and [app2/FIX.md](../ios26-apps-r1/app2/FIX.md).

## 2. Writable package layout and persistence contract

### 2.1 One prefix for payloads and state

Use `/var/jb` for rootless package compatibility. It must resolve to `/private/var/jb` through the system's existing
`/var` alias; the bootstrap must test that resolution rather than creating a symlink on the read-only root. All writes
stay beneath this prefix:

| Path | Purpose |
| --- | --- |
| `/var/jb/usr/{bin,sbin,lib,libexec}` | APT/dpkg, their libraries, shells/tools, root helper |
| `/var/jb/Applications` | Zebra or Sileo and other owner apps, before LaunchServices registration |
| `/var/jb/Library/dpkg` | dpkg `status`, `available`, `info`, alternatives and diversions |
| `/var/jb/etc/apt` | sources, APT configuration, owner keyring/trust configuration |
| `/var/jb/var/{lib,cache,log}` | APT lists, archives, logs and other variable package state |
| `/var/jb/usr/lib/TweakInject` | One `.dylib` plus its filter `.plist` per tweak |
| `/var/jb/Library/LaunchDaemons` | Package job definitions consumed by the prefix-aware job manager, not a directory stock launchd magically scans |
| `/var/jb/var/lib/hk/safe-mode` | Optional loader kill switch; checked before any tweak is dlopened |

The first local repository can instead be read-only seed data under `/private/var/hk/repo`, so downloaded archives and
repository metadata do not become part of the persistence acceptance requirement.

### 2.2 Persistence choices

| Model | Useful for | Verdict |
| --- | --- | --- |
| RAM varfs + HKVAROV seed | QEMU and first ephemeral CLI/package/tweak tests | **Available design path now.** Runtime writes work; reboot persistence does not. |
| Snapshot format v2 on `ios_data` | One small package and one small tweak across reboot | **Near-term proof only.** Requires a new bounded layout, larger/chunked files, transaction consistency, checker updates, QEMU negative tests, then physical admission. |
| Real writable filesystem on `ios_data`, mounted at `/private/var/jb` | Full Procursus, many packages, normal dpkg locking/rename/fsync/hard-link behavior | **Recommended final model.** New VFS/mount/format/recovery work; must not overwrite or silently reinterpret the existing preferences store. |

The persistence lane owns the disk format and write guard. The tooling lane should request this contract rather than
unilaterally widening the current whitelist:

1. A versioned, explicitly bounded package area on `ios_data`; preferences and package generations must be distinguishable.
2. Atomic package transactions, or a journal that can finish/roll back an interrupted dpkg transaction before launchd uses it.
3. An explicit flush/fence after dpkg and tweak installation. A periodic snapshot alone is not an install-success signal.
4. Restore before package jobs and target apps start, with a safe-mode/no-restore boot escape and no execute-before-restore window.
5. Whole-device negative checks updated to permit only the new package extents. GPT, Android partitions, `ios_system`, and
   all unallocated/other `ios_data` blocks remain unchanged.
6. QEMU torn-write, stale-generation, oversized-file, path-traversal, symlink, deletion, and rollback tests before the first
   physical write. Physical persistence remains gated until the existing baseline test and the package-specific test pass.

## 3. Package manager survey and selection

### 3.1 Candidates

| Candidate | What upstream provides | Dependencies and adaptation | Fit here |
| --- | --- | --- | --- |
| [Sileo](https://github.com/Sileo/Sileo) | Modern Swift APT frontend. Its [Makefile](https://github.com/Sileo/Sileo/blob/main/Makefile) has rootless `/var/jb` staging and declares APT, dpkg, coreutils, Swift and zstd dependencies. | A root XPC daemon spawns APT and validates clients by signing certificates ([RootHelper](https://github.com/Sileo/Sileo/blob/main/SileoRootDaemon/RootHelper.swift), [CodesignCheck](https://github.com/Sileo/Sileo/blob/main/SileoRootDaemon/CodesignCheck.swift)). Its [entitlements](https://github.com/Sileo/Sileo/blob/main/Sileo/Entitlements.entitlements) include `platform-application`, task-port, no-container/no-sandbox and many other private keys. Ad-hoc certificates and the current app/container stack need audit; do not import the whole entitlement set. | Good maintained rootless reference, but more privileged-service and identity adaptation than needed for the first UI. |
| [Zebra 2](https://github.com/zbrateam/Zebra) | Actively developed rootless APT UI. [Plains](https://github.com/zbrateam/Plains) wraps libapt; Zebra's Makefile uses the rootless scheme. | Needs Procursus libapt/dpkg, Swift/Obj-C frameworks and app registration. [Supersling](https://github.com/zbrateam/Zebra/tree/main/Supersling) is a comparatively small setuid root helper, while the app and helper entitlement files center on platform/container/storage keys rather than launchd-wide task-port injection. Zebra 2 is alpha, so it is not the first acceptance test. | **Best UI fit** after CLI works. Replace or narrowly confine the root helper if setuid execution is not reliable on varfs. |
| [Installer 3](https://github.com/AppTapp/Installer-3) / [Installer 4](https://github.com/AppTapp/Installer-4) | Public AppTapp package-manager source and XML repository tooling. | These target iPhone OS 1/2 and the AppTapp framework, not a modern APT/dpkg rootless bootstrap. No public modern Installer 5 source was located in the AppTapp organization during this survey; only its issue tracker and legacy source were used as evidence. | Reject for this build: legacy format/APIs and no suitable modern open implementation to port. |

**Selection:** use Zebra 2 as the user-facing target, not as the bootstrap proof. First run the exact same APT/dpkg
backend as root from a controlled job. This isolates package/prefix/signing failures from UIKit, LaunchServices, XPC and
entitlement failures. Sileo is the fallback if Plains/libapt proves harder to port than Sileo's root-daemon model.

### 3.2 Bootstrap and repository requirements

**UPSTREAM:** [Procursus](https://github.com/ProcursusTeam/Procursus) deliberately excludes a hooking platform and
supports both `iphoneos-arm64-rootless` and `iphoneos-arm64e-rootless`, with `MEMO_PREFIX=/var/jb`, prefixed `/etc` and
`/var`, and dpkg state under `/var/jb/Library/dpkg`. Its current Makefile has release mappings through iOS 18, so an
iOS 26 SDK/CoreFoundation profile must be established rather than guessed.

Build in two steps:

1. **Minimal CLI strap:** dpkg, APT/libapt, their compression/crypto/network libraries, a shell, core utilities, tar,
   and enough certificate/keyring support for the chosen repository. Drop documentation, locales and development files.
2. **Full strap and UI:** remaining Procursus runtime packages, Zebra/Plains, and a narrowly privileged root helper.

Every Mach-O payload needs the jb1 signature/PAC audit. Procursus's ad-hoc `ldid` signature and upstream arm64e build
are useful inputs, but are not evidence that their instructions run on this CPU. Rebuild or process and scan every
binary and dylib; reject unsupported PAC instead of treating a package install as a runtime test.

Use an owner APT repository with `.deb` files, `Packages` and cryptographic hashes, `Release`/`InRelease`, and an owner
public key in the bootstrap keyring. **APT repository signing authenticates the repository; Mach-O ad-hoc signing makes
an owner binary loadable. Neither is an Apple trust-cache entry.** Begin with a `file:` repository seeded under
`/private/var/hk/repo`; add HTTPS only after native networking is accepted.

For privileged operations:

- CLI stage: run dpkg/APT as uid 0 from one controlled launchd job, with all paths confined to `/var/jb` and only owner
  packages enabled.
- UI stage: evaluate Zebra's Supersling behind that same backend contract. If setuid varfs execution or caller identity
  validation is unreliable, use a small root job/helper with an authenticated, command-specific interface instead.
- Package job plists under `/var/jb` need a prefix-aware manager to bootstrap them through launchd's supported runtime
  interface. Do not require writes to `/System/Library/LaunchDaemons` and do not run every package script from the UI app.

## 4. Tweak loader design

### 4.1 Map ElleKit's model onto `hk_env`

**UPSTREAM:** ElleKit's [injector](https://github.com/tealbathingsuit/ellekit/blob/main/injector/injector.c) scans
`TweakInject`, reads each tweak's plist, evaluates `Filter` entries for bundles, classes, executables and CoreFoundation
versions, checks safe-mode state, and `dlopen`s matching dylibs. Its launchd implementation separately propagates
`DYLD_INSERT_LIBRARIES`, prepending to an existing value and issuing an extension. Its standalone loader obtains
launchd's task port and remotely creates a thread. Only the first part is needed here.

Proposed flow:

1. The base image carries a signed `/private/var/hk/hk_tweak_loader.dylib` and the ElleKit-compatible hooking library.
   The loader is base policy, not a package that can accidentally remove its own injection path.
2. For each selected target, edit its **existing** `hk_env` insertion value to preserve current diagnostics and append the
   base loader. Measure the 50-byte remaining rule budget. Do not add a second insertion variable.
3. At exec, dyld loads existing instrumentation and then the loader. The loader checks the safe-mode marker and its own
   gate, evaluates each tweak plist against the current executable/bundle, and dlopens matches from
   `/var/jb/usr/lib/TweakInject` in deterministic order.
4. A tweak links the Substrate or libhooker API supplied by ElleKit. The loader records selected path, `dlopen` result and
   `dlerror` to a bounded receipt. A failed tweak must not be hidden by allow-failed-insertion for the base loader.
5. Installing another tweak changes only the package directory; it does not rebuild the boot overlay. Selecting another
   executable class of targets still requires a measured static `hk_env` change or later kernel rule work.

This gives per-process selection without a launchd hook, KDP, a live root shell, remote threads, or `task_for_pid`.
`hk_env` has no wildcard/default target, so “inject into every app” is not a current capability. Expanding rule storage
or adding an explicit default rule is new kernel work; a compact static target set is sufficient for the first test.

### 4.2 Hooking-library choice

| Library | Provides | Assessment |
| --- | --- | --- |
| [ElleKit](https://github.com/tealbathingsuit/ellekit) | Injector/filter model, direct C and Objective-C hooking, assembler/trampolines, and Substrate/libhooker-compatible APIs. | **Best fit** because both discovery and hooking are available and `hk_env` replaces only its privileged launch chain. Upstream lists arm64e testing through iOS 17, not iOS 26; constructor loading and each hooking mechanism need separate validation here. |
| [libhooker](https://github.com/coolstar/libhooker) | Hooking implementation, libblackjack, and Substrate/Substitute compatibility shims. | Reasonable alternate hook API, but the repository does not supply the complete per-process discovery/launch policy wanted here. ElleKit already exposes its API. |
| [Substitute](https://github.com/comex/substitute) | Runtime function/Objective-C modification and import interposition. | Upstream explicitly says **unmaintained**. It is not the new iOS 26 arm64e baseline and does not solve injection/discovery by itself. |

A constructor-only tweak is the first acceptance target. Real hooks are a later gate: ElleKit patches code pages and
creates executable trampolines, and far hooks use an exception-port mechanism. Those operations are not proven by jb1's
constructor receipt. Test near hooks, far hooks and Objective-C hooks separately, identify any exact code-signing,
VM-protection or exception-port denial, and add only a scoped policy if required. Do not respond with global unsigned/JIT
execution or global task-port access.

## 5. Entitlement and sandbox gap map

| Area | Covered by current SWEET/jb1 | Still needed / deliberately avoided |
| --- | --- | --- |
| Owner Mach-O loading | Validated ad-hoc-signed owner code can execute/load; the QEMU probe proves two arm64e dylib injections. | Truly unsigned executables are not covered. All package payloads need the PAC/signature recipe. Prebuilt packages need validation. |
| Apple trust cache | No Apple/Image4 trust cache is required for the existing SWEET signature decision. | `/var/jb` files are not automatically `CS_PLATFORM_BINARY`; rootfs files are. Do not insert every cdhash into a global trust cache. Add a narrow owner-prefix platform classification only if a required private entitlement actually needs it. |
| `platform-application` | XML entitlements are parsed and attached to validated signatures. | Zebra, Sileo and their helpers declare this key, but entitlement presence is not platform classification. First remove unnecessary privilege from CLI design; for the GUI/helper, trace the failing query and use a scoped prefix/identity decision if needed. |
| Sandbox operations/extensions | Real op-2 checks return allowed; profile self-status is coherent; op 5 returns the consumable no-op token; op 4/container behavior remains. | This is not a real Seatbelt profile/extension system. `no-sandbox`, `no-container`, storage and launchd entitlements can affect other userland decisions and must be tested individually rather than assumed covered by op 2. |
| Root package operations | Root jobs can write RAM varfs, and sandbox operation checks are permissive. | dpkg maintainer scripts require uid 0 and correct path confinement. Supersling's setuid path is unproven; a narrow root job avoids extra task-port entitlements. |
| `task_for_pid` / task ports | Not needed by `hk_env`, which acts during exec. | Stock ElleKit's loader needs launchd's task port; Sileo declares task-port keys. Root's POSIX check alone does not erase the MAC get-task/debug checks. Avoid these flows. If ever required, grant only a named helper/target through the owning MAC policy, never globally. |
| App installation/registration | Existing Settings/Phone work shows the stock path can register some root apps; XML entitlement lookup exists. | Zebra/Sileo under `/var/jb/Applications` still need LaunchServices registration, useful icons and a stable visible Home. Audit `canmaplsdatabase`, storage, system-application and container keys only against observed failures. Current phone app breadth is independently incomplete. |
| Tweak `dlopen` | A signed dylib inherits the established insertion path into a chosen stock process. | Arbitrary package dylibs, dependencies and library-validation queries are not all proven. Sign every dependency and keep the base loader insertion fatal/diagnosable. |
| Runtime hooking | No new task port is needed merely to constructor-load code into the current process. | Executable trampolines, code-page writes and exception ports may need separate scoped policy. jb1 does not establish JIT/RWX or far-hook support. |
| Repository access | Local `file:` repositories need no network entitlement or native service. | Remote HTTPS repositories wait for native networking and CA/keyring validation. |
| Rule/boot capacity | One existing insertion value can be edited with no new boot argument. | The 50-byte `hk_env` remainder and full boot line prevent broad static targeting. This is a real tooling limit, not an entitlement problem. |

## 6. Staged implementation and acceptance

“Current jb1 path” below means no additional kernel feature is expected, but new userland/image implementation and
QEMU evidence are still required. It does not mean the stage is already complete.

| Stage | Work and acceptance signal | Reachability |
| --- | --- | --- |
| **0. Admit jb1 physically** | Run the existing temporary jb1 image, obtain both injection receipts, no BlastDoor/Settings regression, then Android return PASS. | **Outstanding coordinator phone gate.** QEMU already passed; no new tooling should claim physical success first. |
| **1. Ephemeral prefix + bootstrap** | Seed `/private/var/jb` and minimal signed CLI tools. In QEMU, shell starts, `/var/jb` resolves to the writable prefix, APT/dpkg version queries succeed, a state file can be created/renamed/read, and `ios_system` hash is unchanged. | **Current jb1 path + userland build.** Full Procursus does not fit the overlay; keep this minimal. |
| **2. Package manager backend runs** | Add a local signed `file:` repository. `apt update` verifies `InRelease`, parses `Packages`, and produces a correct dependency plan with every config/cache/state path under `/var/jb`. | **Current jb1 path + APT port.** No network, platform entitlement, or task port required. |
| **3. Install one test package** | Install an owner `hk-hello` package containing a signed executable and marker. Acceptance: dpkg exit 0, `dpkg-query` reports the exact version, executable prints one expected line, payload hash matches the package manifest, and removal leaves no stale status entry. | **Current jb1 path, ephemeral.** GUI is not needed for this gate. |
| **4a. Load one constructor tweak** | Install a signed tweak plus filter plist, append the base loader to one existing daemon's insertion value, and reboot QEMU. Acceptance: one loader selection receipt and one tweak constructor banner for the selected daemon, zero for the control daemon, no target crash/respawn increase, and safe mode produces zero tweak banners. | **Current jb1 path + loader/tweak build.** Measure rule bytes; no task_for_pid. |
| **4b. Load/hook in one app** | After visible app admission, target Preferences or SpringBoard. First prove constructor-only loading, then one small C or Objective-C hook whose replacement calls the original once and emits one expected receipt. Safe mode restores original behavior. | **Constructor load is near-term jb1 work; real hooking needs separate validation and possibly scoped kernel policy.** Physical app stability is also a prerequisite. |
| **5. Run the user-facing manager** | Build Zebra/Plains, register the app, open it from Home, refresh the local repo, and install/remove `hk-hello` through the UI while the root helper emits the same backend receipts as stage 3. | **Needs GUI/app and entitlement work; not a current proof.** Sileo is the fallback. |
| **6. Persist one package + tweak across reboot** | In boot 1, install a different package version/tweak, explicitly flush, and reboot **without rebuilding the image**. In boot 2: dpkg reports the new version, payload hashes match, the tweak constructor loads once, preferences still restore, and safe rollback works. The updated whole-device checker passes with changes only in the newly approved `ios_data` package extents; Android return check passes. | **Needs new persistence kernel/format work and physical admission.** A seeded overlay recreating the same demo does not satisfy this stage. |
| **7. Full user-facing bootstrap** | Full Procursus survives upgrades and interrupted transactions; Zebra installs a second package with dependencies; remote repo works after network acceptance; repeated reboot and rollback tests pass. | **Recommended on a real `ios_data` filesystem; needs the persistence, GUI and networking lanes.** |

## 7. Recommended implementation order

1. Build the ephemeral `/var/jb` CLI strap and local repository; prove stages 1-3 in QEMU.
2. Add the base loader and a constructor-only tweak to the already injected daemon set; prove stage 4a and safe mode.
3. In parallel, have the persistence lane design format v2 or the real package filesystem. Do not block ephemeral CLI work,
   but do not call any of it persistent.
4. Complete physical jb1/app admission, then the one-app constructor test and individual hook tests.
5. Bring up Zebra only after backend and app-registration failures can be distinguished. Use scoped entitlements based on
   receipts, not the union of Sileo/Zebra/ElleKit entitlement files.
6. Accept reboot persistence only with a changed package set surviving an unchanged boot image and with the storage/Android
   safety receipts. Then expand to the full Procursus/Zebra system.

## 8. Primary references

Project evidence:

- [jb1 design, sandbox gate map, injection recipe and QEMU receipts](DESIGN.md).
- [app2 hk_env example and overlay transformation](../ios26-apps-r1/app2/FIX.md).
- [`ios_data` QEMU negative test](../ios26-dualboot-r8/ios-data-persist/NEGATIVE-r1.md).
- [`ios_data` physical admission plan and current scope](../ios26-dualboot-r8/ios-data-persist/PHYSICAL-PLAN.md).
- Nested XNU `508218953db46f984859f7e57ad08048fc5faed0`: `varfs_overlay.h`, `varfs_persist_core.h`,
  `varfs_persist.inc`, `hakios.blazer_persist_{table,disk}.inc`, `hk_exec_rules.h`, `kern_exec.c`, and `sweet_amfi.c`.

Upstream design references (links only; no code copied):

- [Procursus bootstrap](https://github.com/ProcursusTeam/Procursus) and its [Makefile target/prefix definitions](https://github.com/ProcursusTeam/Procursus/blob/main/Makefile).
- [Sileo](https://github.com/Sileo/Sileo), [Zebra](https://github.com/zbrateam/Zebra), [Plains](https://github.com/zbrateam/Plains),
  [Installer 3](https://github.com/AppTapp/Installer-3), and [Installer 4](https://github.com/AppTapp/Installer-4).
- [ElleKit README](https://github.com/tealbathingsuit/ellekit/blob/main/README.md),
  [injector](https://github.com/tealbathingsuit/ellekit/blob/main/injector/injector.c), and
  [launchd environment merge](https://github.com/tealbathingsuit/ellekit/blob/main/launchd/Implementations.swift).
- [libhooker](https://github.com/coolstar/libhooker) and [Substitute](https://github.com/comex/substitute).
