# hk_ustack: user stacks of named processes from the kernel, no userland tool (2026-11-03, HOST build, not booted)

**Why:** perf/FIX.md section 4 leaves Settings' freeze open between (a) main thread blocked, (b) touches not delivered,
(c) commits not shown, because no userland stack is recorded. r10's answer is `hk_mainwatch.dylib`, which only works if the
dylib loads into Preferences. This sampler needs nothing in userland: the kernel reads the user registers each thread left
at its last kernel entry and walks its frame-pointer chain, every few seconds, for every thread of the named processes.

Evidence levels below: **source**, **host test** (m1box and Mac), **ARM64 object/kernel** (Mac build, symbols and
disassembly), **image check** (`image_tool.py check`). Nothing here was run in QEMU or on the phone.

## What prints

Boot-args (all BLAZER only, off by default):

| arg | meaning |
| --- | --- |
| `hk_ustack=NAME[,NAME...]` | up to 4 exact `p_comm` names (≤16 chars); a bad list is refused whole, with a line |
| `hk_ustack_s=N` | period 1..600 s, default **5** |
| `hk_ustack_n=N` | rounds per pid, default 240 (20 min at 5 s); a respawn (new pid) gets its own budget |
| `hk_ustack_max=N` | console line budget for the boot, default 12000; past it lines are counted (`dropped`), not printed |

Per round and matching task (formats are the kernel's printf strings, `xnu-src/osfmk/kern/hk_ustack.c`):

```
HK USTACK: every 5 s, 240 rounds per pid, 12000 lines; names Preferences,MobilePhone; live request on (usbcon 0x70)
HK USTACK: Preferences[312] r=7 t=145.210 threads=23 susp=0 slide=0x1a2b0000 main=0x100b54000 dsc=0x180000000 cpu+=12
HK USIMG: Preferences[312] n=412 dyld=0x...                     (once, again if dyld's count changes; ≤3 times per pid)
HK USIMG: Preferences[312] n=412 0x100b54000 /Applications/Preferences.app/Preferences   (non-cache images only)
HK USTACK: Preferences[312] r=7 tid=4567 i=0 st=W hint=0x2 pri=47 cpu+=0 sw+=0 off=9120 x16=-47 x0=0x... pc=0x... lr=0x... sp=0x... fp: 0x... 0x...
HK USTACK: Preferences[312] r=7 same: 4570 4571 4590          (threads whose st/hint/pc/lr/frames did not change)
```

- `slide` (shared region `sr_slide`), `main` (`mach_header_vm_address`), `dsc` (region base) are in the header; images
  outside the cache come from dyld's `all_image_infos` (read from the target's memory; if dyld leaves `infoArray` empty,
  nothing is listed and `main=` still covers the app binary).
- Per thread: `i=0` is the task's first thread (the main thread, **always printed**, never folded into `same:`); `st`
  R/W/U/S/T from `thread->state`; `hint` is `block_hint` (osfmk/kern/block_hint.h: 2 port receive, 0xa ulock, 0xf parked
  workqueue …); `cpu+`/`sw+` CPU ms and context switches since the last round (`recount_thread_time_mach`, `c_switch`);
  `off` ms since it last left a CPU; `x16` the syscall it trapped with (mach traps negative); `x0` its first argument;
  `name=` its pthread name if any; `pc lr sp` and `fp:` the return addresses (PAC stripped, `hk_hog_walk`, ≤32 frames).
- Read-only: `copyinmap` of the target, the route `hk_hog` (hk_top.c) already uses on the phone. No thread is stopped, so a
  running thread's (`st=R`) registers are from its last kernel entry (≤ a tick old) and its chain can be torn; the walk is
  bounded and stops on any non-ascending or unreadable frame.

There is no `kern.hakios.ksample` in the release tree, its branches or the repos (git grep over all branches, grep of the m1box and Mac
checkouts); the nearest existing code is `hk_hog` (hk_top.c: running threads of CPU hogs) and `hk_usertrace` (crashes, aborts),
whose walk (`hk_hog_walk.inc`) and register reads this reuses.

How it answers FIX.md's table: main thread `st=W`, same `pc/lr/fp` round after round, `cpu+=0 sw+=0`, growing `off` →
**blocked**, and the frames name the call (hint and x16 say on what). `sw+` growing with `hint=2`, `x16=-47`
(mach_msg2_trap) in the run loop's `mach_msg` → idle run loop, so touches are **not delivered** (or it handles them and
the commit is lost: `cpu+` per round tells those apart). `susp=` > 0 → **suspended** by RunningBoard.

Live request (attended, with `blazer_usbcon_input=1`): vendor IN request **0x70** (`hk_ustack_wire.h`, "HUS1", 56 bytes):
`value=pid, index=1..120` samples that pid now and then once per period, `index=0` cancels, `0/0` is a status query. It needs
no name in the boot-arg; the sampler thread starts when `blazer_usbcon_input=1` even without `hk_ustack=`. Client:
`ustack_ctl.py PID ROUNDS` (Mac, pyusb), which takes usbcon.py's USB owner lock and refuses while a usbcon reader runs.
0x64 was the first choice; it moved to 0x70 because another owner's uncommitted HLI1 work in `tools/usbcon.py` and the m1box
xnu copy takes 0x64..0x68 (KEY, SWIPE, SNAP). Adding `--ustack` to usbcon.py's control socket is left to that file's owner.

## Source and host tests

`ustack/xnu-src/` (files at their tree paths; `base/` = the e731e68 bytes they were edited from, checked by the build script):
- new `osfmk/kern/hk_ustack.c` (sampler), `hk_ustack_pure.inc` (name list, EP0 request rule, "same" hash, name cleaning; no
  XNU types), `hk_ustack_wire.h` (EP0 ABI); `osfmk/conf/files` +1 line; `hk_top.c` calls `hk_ustack_start()` first thing in
  `hk_top_start` (SweetHID start); `blazer_usbcon.c` defines `UC_USTACK` and `uc_ustack`; `blazer_usbcon_core.inc` dispatches
  0x70 only under `UC_USTACK` and `uc.input` (blazer_usbcon_input=1).
- `ustack/test/run.sh`: the real pure part, `hk_hog_walk.inc` and the real `uc_setup` from `blazer_usbcon_core.inc` against a
  fake register file/arena: **50 checks, 0 failed**; built without UC_USTACK (0x70 must stall): **36, 0 failed**; 6 mutants
  (drop the `uc.input` gate, round bound, name length, prefix match, hash field, pid-exists) all caught. PASS on m1box (gcc)
  and on the Mac (clang): `receipts/host-test-m1box.txt`.
- `test/test_ustack_sym.py`: real exported symbols from the 23G90 cache (`/data/hackios-qemu/dsc-r6`, uuid 0f1ee332…), lines in
  the kernel's formats with a made-up slide: **16 checks, 0 failed** (`receipts/sym-test.txt`). `test/test_ustack_ctl.py`
  (HUS1 layout parsed from the header, bounds): **14, 0 failed**.
- Out-of-tree ARM64 compile with the build's own command lines (BLAZER=1, `-w` removed, `-Werror` for implicit declarations,
  int/pointer conversions, format security): `tools/cc_mac.py`, `receipts/cc-mac.txt`: `T _hk_ustack_start`, `T _hk_ustack_control`,
  `t _hk_us_thread`, and `blazer_usbcon.o` references `_hk_ustack_control` (only sign-conversion warnings, as in hk_top.c).

## Kernel

XNU release tree (Mac `research/ios26-release-r1/work/xnu`), **new branch `hk-ustack-dbg4` = `hk-touch-direct` e731e68 + cac047f
(hk_ustack, request 0x64) + 2d640f1 (request moved to 0x70, nothing else)**. Built by `ustack/xnu-src/build_ustack.py` (as
dbg1-net's build_net.py): exclusive `/tmp/fleet/kernel-build-slot.lock`, waits for any make, refuses a dirty tree or changed
e731e68 base files, `mk.sh -j8`, refuses a kernel without the `HK USTACK: every %u s` string, then checks out p1 (b228c4f)
and rebuilds it (rc 0 both times; `receipts/build.txt`, `build-r2.txt`; the restored p1 obj kernel has no hk_ustack string).
After the second release another owner's build took the slot (tree on `hk-netstack-cfg1`, clean): theirs, not this one.

- `kernel.dbg4-ustack` **a5d16a269bc9cc063e21d0dfc146d84e9ba0288381d6f84a7b69f1870b332e18** (Mach-O arm64), `.unstripped`
  2e8a40bd55a1a94cd7aad63137e826edf1dd49763a6e84e23f710442be34e50a, in Mac `research/ios26-phaseb-r1/live/ustack/build/`.
  (The first build, request 0x64, was e678dd71…; superseded, not in any image.)
- `receipts/kernel-verify.txt` (unstripped, llvm-nm/objdump): `_hk_ustack_start`, `_hk_ustack_control`, `_hk_us_thread`
  present; `_hk_top_start`'s first call is `bl _hk_ustack_start`; inside `_usbcon_thread` (uc_setup inlined) `cmp w14, #0x70`
  precedes `bl _hk_ustack_control`. Strings `HK USTACK: every %u s`, `on (usbcon 0x70)` and `sweet_touch_indirect` (e731e68)
  are present; `blazer_persona_log`, `blazer_aks_usersession`, `blazer_aks_wrap` are absent.
- Note: r10-perf ran `kernel.rootview-bl-aks-us2` (hk-aks-usersession, off f24a98d, **no touch-direct**). e731e68 has
  touch-direct but **not** the AKS wrap/user-session commits (44689e0, eb2d19b, cc42295, incl. the varfs RENAME_SWAP fix),
  so this kernel differs from r10's in both. Branching from e731e68 was the instruction (as dbg1-net); whether personas
  still come up without cc42295 is open until a boot.

## Image `a7-ios-system-dbg4-ustack` (Mac `research/images/`, HOST build)

- Recipe: `ustack/mkimg_ustack.sh` = `perf/tools/run_mac.sh` step 3 (r9-apps-ufs's mkimg.sh ufs variant: `--phone-route ufsroot`,
  5 cores, bootcpu 0x200, canvas 1125x2511, deadline 300, overlay **perf-r1.ovl 95701ed9…** incl. hk_mainwatch) with the kernel
  swapped, **plus `hk_ustack=Preferences,MobilePhone`, minus `blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_persona_log=1`**:
  e731e68 has no reference to any of the three (0 strings, git grep), so they were no-ops; dbg1-net drops the same three.
  Period 5 s, the other ustack args at their defaults.
- **boot.img be862758eabdfb50b16494af06cf361180966d593523e758dae1a0034d266b70**, payload b4ab01a0…, margin 39,998,896 B.
  `image_tool.py check`: **`OK a7-ios-system-dbg4-ustack bootable be862758…`** (`receipts/image-check.txt`).
- **Cmdline 1015 → 985 bytes** (≤1023), 57 → 55 tokens; diff vs r10-perf: `-blazer_aks_usersession=1 -blazer_aks_wrap=1
  -blazer_persona_log=1 +hk_ustack=Preferences,MobilePhone` (`receipts/manifest-diff.txt`). Other manifest diffs follow from
  the kernel (mach, entry +0x2000, kernel_end +0x8000, plan, overlay placement) or are per-build (ADT seed, nonces, epoch).
- `tools/image_tool.py` (Mac copy) admits the new tokens: `ustack/tools/allow_ustack.py`, additive and idempotent, on top of
  dbg1-net's uncommitted usbnet lines: b4909202… → **ffbaf2d5…**; it also refuses `hk_ustack*` with a kernel lacking the
  sampler. Diff: `ustack/tools/image_tool-ustack.patch`. The m1box copy of image_tool.py (someone else's uncommitted edit)
  was not touched; the patch has to be applied there by the coordinator with the usbnet one.

## Symbolicate (m1box)

```
python3 -I research/ios26-phaseb-r1/live/ustack/tools/ustack_sym.py <attempt>/ramdump/kernel.log --proc Preferences
python3 -I research/ios26-phaseb-r1/live/ustack/tools/ustack_sym.py <attempt>/ramdump/kernel.log --proc Preferences --summary
```

Defaults: cache `/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e`, names from `research/ios26-release-r1/work/xnu`
(block_hint.h, syscalls.master, syscall_sw.c). Each address becomes `image symbol+off` via `dsc_sym.py` (nearest exported
symbol; a big `+off` means a local symbol, only the image is certain), or `image+off` from the USIMG list/`main=`;
`--root DIR` (an extracted root) names non-cache images from their own symbol tables. `--summary` gives the main thread per
round: state, wait, cpu+/sw+/off, syscall, top frame. It also reads `usbcon.py --output` logs.

## Attended use (owner; not run)

As perf/FIX.md's r10 test (same overlay, same steps), with the dbg4 image and its unstripped kernel:
`tools/bootios research/images/a7-ios-system-dbg4-ustack/boot.img a7-ios-system-dbg4-ustack --mach research/ios26-phaseb-r1/live/ustack/build/kernel.dbg4-ustack.unstripped --wait 480`.
Expect `HK USTACK: every 5 s …` at SweetHID start, then `HK USTACK: Preferences[N] r=1 …` within 5 s of Settings opening (and
`MobilePhone[N]` if Phone opens). The line budget at defaults is about 2–3 KB per process per round with folding; the 1 MiB
ring keeps the last several minutes. Stop rules and rollback are r10's (deadline/PSCI reset to fastboot, `return-check.sh`).
Deadline is r10's 300 s; HANDOFF item 1 notes Home took ~10 min on ios_system with 1800, so an attended run may want a
1800 s rebuild (one flag, `--phone-deadline 1800`).

## Files (none staged or committed; for the coordinator)

`research/ios26-phaseb-r1/live/USTACK.md`, `research/ios26-phaseb-r1/live/ustack/` (xnu-src/ with base/, mkimg_ustack.sh,
test/, tools/, receipts/). Out of git: Mac `ustack/build/` (kernels, objects) and `research/images/a7-ios-system-dbg4-ustack/`.
Shared file changed on the Mac only: `tools/image_tool.py` (patch above). Suggested NOTES line: "hk_ustack (kernel user-stack
sampler, boot-arg hk_ustack=, EP0 0x70): kernel a5d16a26, image a7-ios-system-dbg4-ustack be862758 (HOST build, check OK,
not booted); research/ios26-phaseb-r1/live/USTACK.md."
