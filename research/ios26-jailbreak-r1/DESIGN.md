# jb1: stable owner-code loading, sandbox compatibility, and reusable dylib injection

Date: 2026-11-03. Scope: the owner's own XNU build and iOS userland on their own device. Software/host/QEMU only;
this work did not access the phone. **SOURCE**, **HOST**, **QEMU**, **PHYSICAL** (only a named earlier receipt), and
**INFERENCE** are kept distinct. Nothing here is a stock-iOS security boundary claim.

## 0. Bound result

| Item | Value |
| --- | --- |
| Nested XNU branch | `hk-jailbreak-r1` |
| Consolidation commit | `508218953db46f984859f7e57ad08048fc5faed0` |
| Required parent | `48b613bae1245516ef8197f9c0f4ddbc09963836` (`hk-int2-about`, itself one commit on `hk-int1` 484717f) |
| Kernel `kernel.jb1` | `12118733acf1d8d70090708068c0e5fdc8a67b0dac7e51447ec7cbb2e167a764` |
| Unstripped kernel | `dd420ea3d19e7e154bd07aa94d697dde33332cb82e345ff8e802f85673881352` |
| Probe dylib | `86f29d511b45a5da3f50460b788a77df70c1825fab6e922570b23463952446ec` (arm64e, no PAC, ad-hoc signed) |
| Overlay `jb1-r1.ovl` | `a37e4257c7cc6d8858c304c4ebd34b329746e6d9d28299300271a0e514144957` (66 records) |
| Image `a7-ios-system-jb1/boot.img` | `72ee1fe9ae124e52634de31f230357b4ee7b86b39da3104109bad3bfd9fb7b7e` |
| Boot line | **1018 bytes, 56 tokens, 0-byte delta from int1 and ABOUT; identical token order** |

Derived kernels, dylibs, overlays and boot images are not for git. Source, tools, patch and text receipts are under
`research/ios26-jailbreak-r1/`.

## 1. The gate map: what actually stops owner code

“Unsigned” in this project normally means **not signed by Apple / absent from Apple's trust cache**, not a Mach-O with no
CodeDirectory. The reliable recipe gives owner code an ad-hoc signature with `pacstrip.py --sign`. A completely unsigned
executable is a different case and is not silently conflated with ad-hoc signed code.

| Gate | Current SWEET/int1/ABOUT behavior | Stable jb1 policy |
| --- | --- | --- |
| XNU `cs_system_enforcement` / `cs_process_enforcement`, page/signature validation | XNU code-signing paths remain compiled and active. The int1/ABOUT boot line has no `cs_enforcement_disable` or `amfi_get_out_of_my_way`. SWEET's `mpo_vnode_check_signature` marks a signature that reached the hook `CS_SIGNED`; root-filesystem signatures also get `CS_PLATFORM_BINARY`. | Keep signature and page-hash validation. Ad-hoc sign owner Mach-O files; do not add a global enforcement-disable boot argument. This preserves useful load diagnostics and stock entitlement behavior. A truly signatureless executable needs a separately justified, narrow exec policy, not an accidental side effect of the sandbox fix. |
| Apple trust cache / platform classification | Image4/Apple AMFI trust caches are unavailable. SWEET replaces that decision with the built-in rootfs policy above; the TrustCache interface remains version 0. Owner files under `/private/var/hk` are not automatically platform binaries. | Do not mark every owner binary platform or every cdhash trusted. Injection into a chosen stock process uses that process's existing identity and entitlements. A standalone owner daemon that needs a platform-only entitlement needs a narrow path/identity decision and its own test; ordinary owner code needs no such entitlement. |
| Entitlement discovery and stock daemon entitlement checks | `sweet_amfi_attach_entitlements` parses the validated XML entitlement blob when the signature is added and attaches the whole object to the cs blob. `IOCurrentTaskGetEntitlement`, TCC and other queries use it. DER-only signatures currently get none. | Preserve the complete dictionary, not just the sandbox profile. Do not blanket-grant private entitlements. `containermanagerd`'s embedded profile and tccd's TCC grants are the regression checks. Owner code that deliberately declares a profile gets the corresponding self-status answer. |
| Userland `amfid` | No amfid takeover is used by the existing `hk_env` path. Stock jailbreaks need one because they start outside the kernel trust decision; this build already owns the kernel AMFI interface. | Do not import an exploit-era amfid patch. If a future retained userland flow actually consults amfid, trace that flow and implement a narrow compatible service decision. Kernel injection success is not evidence that every unrelated amfid client is relaxed. |
| dyld path variables / insertion policy | AMFI policy syscall `0x5a` returns `0x3ff` only when `sweetarm64e=1` and the current process is arm64e. This enables development/path variables used by dyld and `OS_ACTIVITY_DT_MODE`; arm64 processes retain the restricted answer. | Keep this independent gate explicit. Build inserted libraries and target processes for the established arm64e path. Missing insertion remains fatal and diagnosable; do not hide it with allow-failed-insertion. |
| launchd stripping `DYLD_*` | A launchd job plist cannot reliably propagate insertion variables. `hk_env` is applied by XNU during exec, before the job's own environment, so it is not subject to that stripping. | Reuse `hk_env`; do not add a launchd hook, SystemHook, RootHide or a second injector. Preserve existing insertion entries with `:` and never add a second `DYLD_INSERT_LIBRARIES` for one process. |
| PAC/arm64e execution on the host CPU | `sweetarm64e=1` accepts the userland and dyld policy, but injected arm64e code must contain no unsupported PAC instructions. | Use the established `pacstrip.py --sign`, then `codesign --verify --strict` and `pacstrip.py --scan`. Host signing is only build evidence; the guest constructor receipt proves loading. |
| Sandbox operation checks | The SWEET policy replaces Apple Sandbox; there is no real profile compiler/enforcer. Before ABOUT, op 2 returned syscall success without writing its result, making both real checks and the special self-status query look zero. | Real operation checks explicitly write **0 = allowed**. The special self-status query writes 1 only for a declared embedded profile, otherwise 0. This is a compatibility answer, not a claim that a real Seatbelt profile is enforced. |
| Sandbox extensions | Op 5 writes libsandbox's own no-op token `"invalid\0"` into argument word 4. Libsandbox consumes that token locally with success and no op-6 syscall. Unknown/real op-6 tokens return `ENOENT`. | Preserve this protocol. Do not manufacture real-looking tokens or return NULL where SafariCore/TCC expect a consumable token. Because operation checks are permissive, no additional privilege is being delegated by `"invalid"`. |
| Container queries | Op 4 returns the established container path answer. Op `0x43` reports no container expected. | Preserve op 4. jb1 corrects op `0x43` to write one-byte false booleans, not eight bytes through each `bool *`. |
| MAC privilege grants | SWEET grants `PRIV_WORK_INTERVAL` (needed by CoreAnimation) and denies/logs other privileges. | Keep narrow grants. If owner code hits another privilege, identify the exact privilege and caller before adding a scoped rule; a blanket `mac_priv_grant = 0` would hide bring-up faults. |
| MACF policy composition | XNU combines `MAC_CHECK` errors across policies. A second permissive policy cannot override a different registered policy that denies. SWEET works because its built-in AMFI/Sandbox policies replace the absent Apple policies. | Do not add another “allow” policy and expect it to cancel Apple AMFI/Sandbox. Relax the policy that owns the relevant decision. |
| Boot-arg capacity | int1/ABOUT use 1018 of the 1023 data bytes. | jb1 adds **zero** boot-arg bytes. No `hk_dbg` bit is consumed. Injection lives in the existing active overlay group. Aggregate `hk_env` is 974 bytes including NUL, leaving 50 bytes. |

## 2. Stable `sandbox_check` semantics

### 2.1 The ABI distinction

The 23G90 static analysis in ABOUT/FIX.md shows libsandbox's op-2 wrapper passing at least:

```
{ u64 *result, (s64)pid, operation, filter_type, ... }
```

It returns `-1` on syscall error and otherwise `result != 0`. Those last four words have two different meanings:

- `sandbox_check(pid, "mach-lookup", 0, ...)`: nonzero means denied. SWEET is permissive, so the answer is zero.
- `sandbox_check(getpid(), NULL, 0)`: stock Swift uses this as “am I sandboxed?”. A profiled service expects one.
  BlastDoor otherwise executes `fatalError("BlastDoor cannot run unsandboxed.")` and SIGTRAPs.

Returning a blanket zero is therefore wrong for self-status; returning a blanket one would deny every real operation and
falsely mark unprofiled owner code sandboxed.

### 2.2 jb1 rule

For every valid op-2 call, jb1 copies in the argument words, rejects a null result pointer with `EINVAL`, and writes an
explicit 64-bit zero or one. Only the exact self-query (`NULL` operation, type zero, signed pid equals caller pid) performs
an entitlement lookup. A nonempty `com.apple.private.sandbox.profile:embedded` string produces one. NULL/empty/no parsed
XML entitlement produces zero. Cross-pid status queries conservatively remain zero; no proc lookup/PID-reuse machinery is
added. `copyin`/`copyout` errors propagate instead of silently looking allowed.

This builds directly on ABOUT's result-pointer path and generalizes its `blastdoor` prefix exception to the declared
profile semantic. It does **not** widen real checks, op 5/op 6, dyld policy or code-signing flags.

Expected probe values:

| Main executable | Embedded profile | Self-status | Real `mach-lookup` check |
| --- | --- | --- | --- |
| `tccd` | absent (verified from its signed entitlements) | 0 | 0 |
| `containermanagerd` | `containermanagerd` (verified) | 1 | 0 |
| `MessagesBlastDoorService` | `blastdoor-messages` (ABOUT static evidence) | 1 | 0 |
| ordinary owner/ad-hoc code with no profile entitlement | absent | 0 | 0 |

Successful profiled self-checks log a bounded receipt such as
`SWEET Sandbox: containermanager[PID] self-check: sandboxed`. The global log counter is diagnostic only and never affects
the answer. Diagnostic counters can duplicate/lose a line under a race; the result path does not depend on them.

### 2.3 Extension and container behavior is deliberately unchanged

Op 5 still writes exactly eight bytes (`"invalid\0"`) to word 4 and returns an error for a null output pointer or copy
failure. Op 6 is unchanged. The only adjacent sandbox hardening is op `0x43`: its documented boolean outputs now use a
one-byte zero and a one-byte `copyout`, confirmed as `mov w2,#1` in the ARM64 object. Op 4's container semantics are out of
scope for this consolidation and are not changed.

## 3. Reusable recipe: inject my dylib into process X

### 3.1 Write and build the library

Use `src/hk_inject_probe.c` as the minimal pattern: a constructor gated by an owner variable, no interposition, no threads,
no persistent state, and a direct `/dev/console` receipt. Replace the probe checks with the owner's code as needed.

```sh
A=research/ios26-jailbreak-r1
sh "$A/tools/build_inject_probe.sh"    # Mac, repo root; host test + arm64e guest build/sign/verify
```

For another library, follow that script: iphoneos SDK, `-arch arm64e -miphoneos-version-min=26.0 -dynamiclib`, an install
name matching its overlay path, `pacstrip.py --sign`, strict codesign verification and PAC scan. Do not commit the derived
raw/signed dylibs.

### 3.2 Address the executable, not a launchd label

`X` is the executable basename from exec, e.g. `tccd` or `containermanagerd`, not `com.apple.tccd` and not a full path.
Add the signed file as `/private/var/hk/X.dylib` in an active overlay group (the established dylib group is 29, root-owned
mode 0755). Add or edit that same group's `hk_env` record:

```text
X:DYLD_INSERT_LIBRARIES=/private/var/hk/X.dylib;HK_X_GATE=1
```

Multiple target processes can share one library, one rule per process. A constructor should check its own gate so an
accidental environment match does nothing.

If X already has insertion libraries, **edit the existing variable** and preserve them:

```text
X:DYLD_INSERT_LIBRARIES=/private/var/hk/existing.dylib:/private/var/hk/X.dylib;EXISTING_GATE=1;HK_X_GATE=1
```

Do not append another `X:DYLD_INSERT_LIBRARIES=...` rule: injected variables precede the job environment and the first
value wins. `OS_ACTIVITY_DT_MODE=YES` is needed only for the os_log/stderr-mirror use case; a direct-console constructor
does not need it.

Grammar and bounds (from `hk_exec_rules.h`/exec source):

- `PROG[+PROG...]:KEY=VAL[;KEY=VAL...][,...]`; `:` is legal inside values and separates libraries.
- `,` ends a rule and `;` ends a variable; neither can be escaped inside a value. Literal spaces are forbidden; `~`
  becomes a space in a value.
- Aggregate boot-arg plus active overlay rules: 1023 data bytes plus NUL. Each `KEY=VAL`: 383 bytes plus NUL.
- Every injected string also consumes exec environment/pointer space. Avoid bulk injection.
- Kernel `hk_env:` diagnostics prove environment insertion only. A constructor banner proves dyld loaded the library.
  The kernel diagnostic is globally capped, so absence after its cap is not evidence of absence.

jb1's concrete rules are in `receipts/overlay.json`: tccd keeps `hk_stderr_console.dylib` and gains the probe;
containermanagerd gets only the probe. All 64 unrelated base records are byte-identical, and the kernel's own
`hkov_check`/`hkov_cover_check` accepts the result.

### 3.3 Validation and escape

1. Host-test the constructor with gate absent/0/1, as `build_inject_probe.sh` does.
2. Run the release-header overlay checker and decode-diff assertions.
3. Run `tools/qemu_preflight.py` with probes for exactly one constructor receipt, the chosen exec count, no target crash,
   unchanged critical daemons and no new respawns.
4. To disable injection, remove that overlay rule/file or set the gate to 0 and build a new image. Do not make a broken
   insertion nonfatal; that would turn a missing library into a silent bootstrap failure.

This is deliberately narrower than vphone/ElleKit's launchd-wide propagation. It needs no exploit primitive, launchd hook,
writable system volume, live root shell or KDP. Those are other agents' scopes, not dependencies of this recipe.

## 4. Implementation and HOST evidence

- `hk-jailbreak-r1` is exactly ABOUT `48b613b` plus consolidation `5082189`; only `bsd/kern/sweet_amfi.c` and
  `bsd/kern/sweet_sandbox_check.h` differ from ABOUT. `patches/0001-...patch` is the nested-Git commit.
- Full `mk.sh -j8` build passed under `/tmp/fleet/kernel-build-slot.lock`; p1 was restored and rebuilt successfully. The
  build script uses no reset/clean and refuses a dirty shared tree. Receipt: `receipts/build_jb1.out`.
- `sweet_amfi.o` is a Mach-O ARM64 object, SHA `76aca17c…e74408`, with `_sweet_sandbox_syscall`, entitlement/copyin/
  copyout references. The linked unstripped kernel has zero undefined symbols and retains int1 markers. ARM64 disassembly
  shows the op-2 explicit result path and one-byte op-`0x43` writes. Receipt: `receipts/kernel-verify.txt`.
- Pure-C host model: **15 checks, 0 failed**, ASan/UBSan. Six mutations (BlastDoor-only, null-profile-sandboxed, dropped
  self-pid, dropped NULL-operation, dropped filter-type, dropped result-pointer check) are all killed. Receipts:
  `receipts/test_sandbox_check.txt`, `receipts/mutation-tests.txt`.
- Probe: Mac host gate/load test PASS, arm64e iOS 26 dylib, no PAC code, strict codesign verification OK. Receipts:
  `receipts/inject_probe/`.
- Overlay: 66 records, 725856 bytes, mask `0xA0080081`, four ABOUT covers retained, 64 unrelated records byte-identical;
  `hkov_check` and cover check OK. Receipts: `receipts/overlay.json`, `receipts/overlay-check.txt`.
- Image checks pass with both the pinned int1 image tool and the shared tool. Manifest diff proves the line is identical
  to int1 and ABOUT. Receipts: `receipts/image-check.txt`, `receipts/manifest-diff.txt`, `receipts/SHA256SUMS.image`.

## 5. QEMU proof

Runs use the canonical phone root read-only as the fake UFS LUN, the exact phone kernel/overlay, and TCG. “Home
equivalent” is a daemon-stability proxy, not a phone UI result.

Control:

```sh
HACKIOS_QEMU_SLOTS=1 python3 -I tools/qemu_preflight.py \
  research/images/a7-ios-system-int2 \
  --kernel research/ios26-phaseb-r1/about/build/kernel.int2-about \
  --seconds 600 --name qf-jb1-base-r1 \
  --json research/ios26-jailbreak-r1/receipts/qf-jb1-base-r1.json
```

Candidate:

```sh
HACKIOS_QEMU_SLOTS=2 python3 -I tools/qemu_preflight.py \
  research/images/a7-ios-system-jb1 \
  --kernel research/ios26-jailbreak-r1/build/kernel.jb1 \
  --seconds 600 --name qf-jb1-full-r1 \
  --baseline /data/hackios-qemu/research/ios26-apps-r1/runs/qf-jb1-base-r1 \
  --expect tools/qemu_preflight.expect.yaml \
  --expect research/ios26-jailbreak-r1/tools/qemu_jb1.expect.yaml \
  --json research/ios26-jailbreak-r1/receipts/qf-jb1-full-r1.json
```

Transcripts are `receipts/qf-jb1-base-r1.txt` and **`receipts/qf-jb1-r1.txt`**. The completed run directories are
`/data/hackios-qemu/research/ios26-apps-r1/runs/qf-jb1-base-r1` and `.../qf-jb1-full-r1`.

**QEMU verdict: PASS.** The full candidate ran for 600.38 seconds, exited 0 and left the root unchanged. Home equivalent
was reached at host 88 seconds; overlay 19/19 applied, 0 rejected, 0 panics and 0 crash events. Both exact result lines
appeared once:

```
HKINJECT: containermanagerd[52] loaded self=1 operation=0
SWEET Sandbox: containermanager[52] self-check: sandboxed
HKINJECT: tccd[32] loaded self=0 operation=0
```

`tccd` and `containermanagerd` each exec'd once (the separate `containermanagerd_system` is not counted as a respawn).
The containermanager op-5 path and TCC entitlement grants remained. `receipts/raw-console-counts.txt` records the raw
line counts. `receipts/daemon-compare.txt` compares every daemon against ABOUT: **0 respawn increases and 0 crash-count
increases, with no exceptions**. The control passes the default pre-flight; evaluated with the new rows it fails exactly
the two injection probes and the new self-check probe (`receipts/qf-jb1-base-negative.txt`), so the positive result is
not vacuous.

The generic `--baseline` report (`receipts/qf-jb1-full-r1.txt`) additionally flags three on-demand daemons that happened
not to launch in this run: `com.apple.CallKit.CallDirectoryM`, `financed` and `nanoregistrylaunchd`. None is a required
milestone, and none is a respawn or crash. The canonical no-baseline analysis of the same completed console is
`receipts/qf-jb1-r1.txt` (PASS); the direct all-daemon comparison above is the requested new-respawn test. An interrupted
first candidate was also rescued to 593 seconds and passed the functional probes, but is not used as the completion proof
(`receipts/qf-jb1-r1-partial.txt`).

The analyzer itself needed a host-only compatibility fix: `probe_eval.evaluate()` now has a different public API, so
`tools/qemu_preflight.py` selects an evaluator by its four-argument in-memory signature and falls back to `hk_cycle`.
`tools/test_qemu_preflight.py` has a regression test; all 14 tests pass (`receipts/qemu-preflight-host-tests.txt`). No
guest was rerun for the control's initial analyzer exception; its completed console was reused.

TCG launched neither `MessagesBlastDoorService` nor `Preferences` (both raw exec counts zero). Their zero crash counts
satisfy the no-crash check but are **not** interactive launch proof. The physical checklist below remains necessary for
those two.

## 6. Coordinator's unattended temporary phone boot

This is a command for the coordinator, **not** a command run by this agent. It uses temporary `fastboot boot` through the
existing wrapper, writes no partition and needs no UI script:

```sh
cd /srv/dev/repos/personal/hackios
tools/bootios research/images/a7-ios-system-jb1/boot.img a7-ios-system-jb1 \
  --mach research/ios26-jailbreak-r1/build/kernel.jb1.unstripped --wait 1080
```

The 900-second in-guest deadline ends the temporary boot. Preserve the complete attempt and ramdump, then perform the
normal Android return check. Do not flash this image. On the phone, check for the two HKINJECT result lines, no
MessagesBlastDoorService SIGTRAP loop, and Settings > General > About without a Preferences crash. QEMU success does not
substitute for this physical admission and interaction test.

## 7. Public research sweep (links, no copied code)

### Primary XNU/dyld semantics

1. [Apple XNU 12377 `kern_cs.c`](https://github.com/apple-oss-distributions/xnu/blob/xnu-12377.121.6/bsd/kern/kern_cs.c):
   separates system/process enforcement and shows that `cs_enforcement_disable` is `!SECURE_KERNEL` and debugger-gated.
   It is not a universal AMFI, Sandbox or dyld-policy switch.
2. [Apple XNU 12377 `mac_internal.h`](https://github.com/apple-oss-distributions/xnu/blob/xnu-12377.121.6/security/mac_internal.h):
   `MAC_CHECK` combines policy errors; permissive callbacks in another policy do not override a denial.
3. [Apple dyld `DyldProcessConfig.cpp`](https://github.com/apple-oss-distributions/dyld/blob/main/dyld/DyldProcessConfig.cpp):
   AMFI path-variable policy gates parsing of `DYLD_INSERT_LIBRARIES`; it is separate from generic cs flags.
4. [Apple dyld `DyldRuntimeState.cpp`](https://github.com/apple-oss-distributions/dyld/blob/main/dyld/DyldRuntimeState.cpp):
   inserted libraries go through the normal loader, duplicates are suppressed, and failed insertion is separately gated.
   Main-branch dyld is architectural evidence, not assumed byte-identical to 23G90.

### Sandbox/extensions and jailbreak structure

5. [Mark Rowe, Sandboxing on macOS](https://bdash.net.nz/posts/sandboxing-on-macos/): separates userspace APIs/profile
   compilation from kernel MACF enforcement and explains that consuming profiles give extensions meaning. macOS-focused
   secondary analysis, used for architecture rather than iOS 26 ABI claims.
6. [Chromium `seatbelt_extension.cc`](https://github.com/chromium/chromium/blob/main/sandbox/mac/seatbelt_extension.cc):
   a production consumer showing issue/consume/release and opaque token lifecycle. Its private declarations/comments are
   not treated as current Apple implementation source.
7. [libSandy README](https://github.com/opa334/libSandy/blob/main/README.md) and
   [`libSandy.m`](https://github.com/opa334/libSandy/blob/main/libSandy.m): brokered per-process extensions and the modern
   caveat that a `sandbox_check` result need not equal actual Mach reachability. Supports keeping query compatibility
   separate from operation enforcement.
8. [ElleKit launchd implementations](https://github.com/evelyneee/ellekit/blob/main/launchd/Implementations.swift) and
   [injector](https://github.com/evelyneee/ellekit/blob/main/injector/injector.c): shows the conventional launchd-hosted
   per-spawn insertion/extension chain and explicit targeting/safe-mode decisions. Those dependencies are unnecessary
   when XNU already supplies `hk_env`.
9. [Dopamine 3.x systemwide domain](https://github.com/opa334/Dopamine/blob/3.x/BaseBin/launchdhook/src/jbserver/jbdomain_systemwide.c)
   and [launchd hook](https://github.com/opa334/Dopamine/blob/3.x/BaseBin/launchdhook/src/main.m): separates per-process
   extensions, trust/debug state and syscall filters. Relevant as a layer checklist, not as a source-controlled-XNU recipe.
10. [Chimera13 amfid takeover](https://github.com/coolstar/Chimera13/blob/master/Chimera13/post-exploit/utils/amfidtakeover.swift):
    historical evidence that userland amfid can be a separate decision point. iOS 13/exploit/task-port machinery is not an
    appropriate implementation model here.

Apple does not expose a current standalone `apple-oss-distributions/libsystem_sandbox` repository; third-party wrappers
were not represented as Apple's implementation. The op-2/op-5 ABI statements above instead come from the project's named
23G90 disassembly receipts.

### vphone-cli assessment

The requested vphone-cli review found no installed local binary/checkout. Public source was pinned at
[`fd1610d7928aacd6cbc060722bb27fd7d2c76315`](https://github.com/Lakr233/vphone-cli/tree/fd1610d7928aacd6cbc060722bb27fd7d2c76315).

- [Trust-cache patch research](https://github.com/Lakr233/vphone-cli/blob/main/Research/KernelCustomFirmwarePatches/patch_amfi_cdhash_in_trustcache.md)
  and [exec-kill path research](https://github.com/Lakr233/vphone-cli/blob/main/Research/KernelCustomFirmwarePatches/patch_amfi_execve_kill_path.md)
  independently reinforce that completely unsigned execution, ad-hoc cdhash trust and exec entitlement failures are
  different gates. They target PCC/VPHONE600 private firmware, not SWEET/Pixel source.
- [Sandbox hook patch research](https://github.com/Lakr233/vphone-cli/blob/main/Research/KernelCustomFirmwarePatches/patch_sandbox_hooks_extended.md)
  relaxes MACF hooks; it does not implement SWEET's op-2/op-5 userland ABI and would not fix BlastDoor's result word.
- [`InjectionEnvironment.h`](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/VPhoneGuestComponents/Shared/InjectionEnvironment.h)
  has useful prepend/preserve/dedup/target/safe-mode algorithms, but its launchd/SystemHook/RootHide chain is not needed.
- [`KernelPatchDyldPolicy.swift`](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/VPhoneExecutable/VPhoneCommand/FirmwarePatcher/Kernel/BasePatches/Security/KernelPatchDyldPolicy.swift)
  confirms dyld policy as a separate checklist item.
- [`host-setup.md`](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/Documents/Guides/host-setup.md)
  concerns macOS host virtualization entitlements/AMFI, not the Pixel guest.

**Decision:** use vphone as a gate checklist and for environment-handling ideas only. Do not transplant firmware offsets,
TXM/credential patches, bulk MAC-hook allows, guest daemons or host-AMFI instructions. Direct source-level SWEET decisions
are narrower and more reliable for this build. The local `tools/ios_app_register.m` already independently adopts the
useful LaunchServices read-back pattern; app registration cannot repair missing app content, sandbox ABI or code signing.

## 8. Limits and follow-ups

- This is not a real Seatbelt profile compiler/enforcer and does not provide security extensions. It supplies coherent
  compatibility answers for the permissive owner build.
- XML entitlements are supported; DER-only entitlements remain unimplemented and are not guessed.
- Cross-pid self-status queries remain zero. Add target audit-token/proc-lifetime handling only if a real caller needs it.
- A standalone owner executable with no signature, a platform-only private entitlement or a new MAC privilege is a
  separate tested policy decision, not silently covered by the dylib recipe.
- Preferences' earlier About abort involved pruned MusicLibrary resources, not Sandbox; ABOUT's three covers are retained.
  Phone's missing asset catalogs and AKS/SEP/user-session issues are independent and unchanged.
- No physical result is claimed. BlastDoor and Preferences require the coordinator's phone interaction even if TCG has
  zero events because it did not launch them.
