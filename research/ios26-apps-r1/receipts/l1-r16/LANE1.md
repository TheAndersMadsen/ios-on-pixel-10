# Lane 1: backboardd NSURL-nil abort (2026-11-03). Root cause from disassembly; QEMU cannot reproduce it

## Root cause (static, from the dyld cache of the r6/r12 roots, uuid 0f1ee332…; tools/m1box/dsc_sym.py, dsc_dis.py)

Physical backtrace (phone captures, e.g. `research/ios26-opt-20261102/parent/sampler-fast-p29-r1.raw`, slide 0x170d0000):
`backboardd main -> libdispatch -> backboardd 0x100871594 -> BaseBoard 0x19075c488 -> BaseBoard 0x19075c434 ->
Foundation -[NSURL initFileURLWithPath:] -> objc_exception_throw -> abort` with
`*** -[NSURL initFileURLWithPath:]: nil string parameter`.

- **Frame:** BaseBoard function at 0x19075c400 calls `_BSSystemSharedResourcesDirectoryForCurrentProcess()` and passes the
  result straight to NSURL (`initFileURLWithPath:`) through the class ref at 0x1e5d163b0.
- **Nil argument:** `_BSSystemSharedResourcesDirectoryForCurrentProcess` is a `dispatch_once` around
  `_BSSystemSharedResourcesDirectoryForIdentifier(nil)` -> `_BSSystemSharedDirectoryForIdentifier(nil)`, which calls
  **`_container_system_path_for_identifier`** (libsystem_containermanager) with an error out-parameter. On NULL it logs
  (FAULT) either `Error getting shared system container - not entitled. The "com.apple.security.system-container"
  entitlement is required` (error 0x37) or `Error getting shared system container for bundleID: %{public}@: %llu`, and
  returns nil.
- **What fills it on a device:** containermanagerd, which serves the process's system container under
  `/private/var/containers/Data/System/<UUID>`.

## QEMU measurement: `runs/backboardd-15m-r16` (m1box TCG, 900 s; intent `intent-r16.json`)

Root = r14 (rd=ufsroot0, kernel.rootview, lsd + usermanagerd mirrors) + backboardd os_log mirror.
- backboardd started once and never respawned in 15 minutes: `exec backboardd` 1, `usercrash`/`userabort: backboardd` 0.
- `Error getting shared system container` 0; `initFileURLWithPath` 0.
- Deciding line: `backboardd[46] [Display] StartWindowServer: Initializing shader cache path:
  /private/var/containers/Data/System/5FB14F0C-…/Library/Caches`: the system container resolved.
- Every other QEMU console on the rig also has 0 backboardd aborts (r12d, r13, r14, r15b, cal-r12d-tcg, cal-r12d-tcg-b).

## Hypotheses (two, materially different, both rejected; lane stops under GOAL.md section 7)

1. **The abort is deterministic in this userland** (it would reproduce in QEMU with the same binaries): rejected; 0 aborts
   in 7 QEMU runs, including 15 minutes with backboardd mirrored.
2. **The nil comes from the entitlement branch (error 0x37)**: rejected; the same backboardd binary and entitlements
   resolve the system container in QEMU (shader cache path line), so the entitlement is present.

Remaining cause (inference): on the phone, containermanagerd does not answer backboardd's system-container lookup in
time early in boot (the abort is "intermittent early" in the physical records). No fix was applied: QEMU shows 0
respawns with and without any change, so it cannot measure one. Next measurement is physical: the A7 iOS boot from
`ios_system` with backboardd and containermanagerd mirrored, recording the BaseBoard error text and code.
