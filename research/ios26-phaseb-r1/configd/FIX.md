# Settings frozen: configd's InterfaceNamer waits 300 s for an IONetworkStack (2026-11-03, HOST + QEMU fix, not booted)

**Physical input:** `a7-ios-system-r10-perf`, attempt `research/laguna-usb-fix/attempts/20261103-194531-a7-ios-system-r10-perf`
(ramdump `kernel.log`). **That file holds three boots:** r10 is lines 1..4147 (Darwin banner at 21, last `HK TOP t=388` at 4145).
4148.. is the older `a7-ios-system-r6-gpu` boot (device clock 18:39 = host 19:38), then Android, then a second copy of r10 from
19833. Bounded extract: `receipts/r10-evidence.txt`.

## 1. Why configd "doesn't answer" (PHYSICAL log + HOST disassembly)

- **configd is fine.** In r10 it ran once (`exec configd`, line 685, before kernel t=118), set up lo0 and its routes, was never
  respawned and used 761 ms of CPU in total. It is not denied, not crashing and not itself blocked.
- **Settings waits for one dynamic-store key.** HKMAIN's frames (dsc-r6, slide 0x1c5a8000): Preferences+0xcdab0 →
  `__SCNetworkInterfaceCopyAllWithPreferences`+0x170 → libdispatch (a once) → SystemConfiguration+0x4a87c → `_SCDynamicStoreNotifyWait`+0x98
  → mach_msg. +0x4a87c is `__waitForInterfaces`: it logs "Waiting for IOKit to quiesce (or timeout)", watches
  `Plugin:InterfaceNamer` and returns only when that value contains `*QUIET*`, `*COMPLETE*` or `*TIMEOUT*` (CFStrings at
  0x1f1abd460/480/4a0). The mach_msg is the store's notification wait, so no reply was missing. The key was never written.
- **configd's InterfaceNamer writes it only with an IONetworkStack** (23G90 configd, `/usr/libexec/configd` from the root,
  `receipts/configd-interfacenamer.txt`):
  - `setup_IOKit` arms one CFRunLoop timer at start + **WaitStackTimeout = 300.0 s**. The bundle's Info.plist has no override, so
    that is the `__data` default; WaitQuietTimeout is 240.0 s. It then matches `IONetworkStack` (IOServiceFirstMatch).
  - `quietCallback` adds `*QUIET*` when the root's busy state is 0, then returns unless it holds a stack connection
    (`IOServiceOpen(stack, task, 0, &S_connect)` in `stackCallback`). Only after that does it publish (`*COMPLETE*`).
  - The timer's callback adds `*TIMEOUT*`, so without a stack the key appears at configd start + 300 s at the earliest.
- **Our kernel publishes IONetworkStack only with `blazer_usbnet=2` or `blazer_wifi_net=2`** (`BlazerNetServices.cpp`, whose own
  comment says "without it waits out a 300 s timer"). r10 had neither. Kernel log: no `IONetworkStack published`.
  The phone boot ends at `blazer_deadline=300`, and Preferences started at kernel t≈190 s. So the wait can end only
  around configd start + 300 s, at the very end of the boot or after it. HKMAIN shows wait growing 3 s → 198 s with
  touch=0 until its 60-line cap.
- Ruled out: a missing kext or interface namer (InterfaceNamer is built into configd and ran), an unwritable preference plist
  (nothing is written before the stack), and `blazer_usbnet=2` as the fix (it reshapes the USB gadget around the console).

## 2. Fix: `blazer_netstack=1` (kernel, XNU branch `hk-netstack-cfg1` 093ca86 on `hk-aks-usersession` cc42295)

- `bsd/dev/blazer_usbnet.c`: `blazer_netstack=1` calls `blazer_net_publish_services()` alone: the existing stand-in, no ifnet,
  no USB, before any of usbnet's own checks. It prints `blazer-netstack: published alone`.
- `iokit/Kernel/arm/BlazerNetServices.cpp`: `IONetworkStackUserClient::initWithTask` logs
  `blazer-netstack: IONetworkStack opened by NAME[pid] type T, IOKit root busy B`. If B > 0, one thread logs up to 8 busy leaf
  services and `IOKit quiet N ms after the open` (or still busy after 300 s). That is the phone-side answer to the
  240 s quiet timer.
- `bsd/kern/kern_exec.c`: hk_deny prints the first 64 refusals, then every power of two, now with the count:
  `hk_deny: NAME refused, EBADARCH (refusal N)` (section 3).
- Build (Mac, `xnu-src/build_cfg1.py`, `build/build_cfg1.out`): exclusive `/tmp/fleet/kernel-build-slot.lock`, tree was `p1`
  b228c4f and clean, new branch, `mk.sh -j8` rc 0. The tree was restored to **p1 b228c4f** and rebuilt (rc 0; obj kernel f98a6e11…).
  - `kernel.rootview-bl-aks-us2-ns1` **f75a20c47dc978b8958bb359adf21ba143453fa567328af2ab4597a0f5ca5967**, unstripped
    4bccaad3b875673ffd1d4159d1bdb98c13c371be5c245fac52699099754bbeae (both on the Mac and here in `build/`, not in git).
  - `receipts/kernel-verify.txt`: `IONetworkStackUserClient::initWithTask`, `blazer_net_busy_leaves`, `blazer_net_quiet_watch`
    are defined; the strings are present; `blazer_usbnet.o` references `blazer_net_publish_services` and `PE_parse_boot_argn`.
- Risk: `IOServiceOpen` succeeds without IONetworkStackUserClient implementing naming (externalMethod Unsupported). That is fine
  with no interfaces. With Wi-Fi en0, InterfaceNamer would try `IOConnectSetCFProperties` (`docs/reuse/2026-11-02/darwin-services.md` §2).

## 3. Spotlight: the deny did apply in r10. The 30 s per 30 s Spotlight[142] is r6-gpu's (PHYSICAL log)

- In r10's own section: `varfs-overlay: c hk_deny bluetoothd,Spotlight`, 63 `hk_deny: Spotlight refused, EBADARCH` lines and
  **0** `Spotlight[N]` in any HK TOP line.
- `Spotlight[142]` ("Successfully spawned Spotlight[142]" 18:40:08, HK TOP `Spotlight[142]=4084…6006`) is in the leftover
  r6-gpu section. It is in r6-gpu's own ramdump, and r6-gpu's overlay denies only `bluetoothd`.
- What r10 does show: 61 refusals in t=118..148 s (about 2/s, SpringBoard relaunching it), then the kernel's 64-line print
  cap. After that SpringBoard ~2.0–2.7 s, runningboardd ~1.9–2.5 s and launchd ~1.0 s per 30 s while idle, against r9's ~0.3 / ~0 / ~0.1.
  A relaunch loop that continues unprinted is the likely reason (inference). It costs about 6 s per 30 s, not a core.
- **Change:** none to the deny row. The counted print lets the next boot measure the loop rate directly. If it stays about
  2/s, the next step is stopping SpringBoard's relaunch (or leaving Spotlight loaded and suppressing the dictation-button
  path, perf/FIX.md §2), not the deny.

## 4. QEMU A/B (m1box, TCG, 1 CPU; intent `receipts/qemu-ab-intent.md`)

The same ns1 kernel, root `apps-logmirror-r14.img` and QEMU-only overlay `overlays/qemu-cfg1-scwait.ovl` (7acd3d4a…) in both runs:
perf-r1 plus `hk_scwait.dylib` (`src/hk_scwait.c`) in powerd (receipts `qemu-overlay-*`: 48 records identical, [39] powerd's
rule and the appended dylib). The probe makes Settings' own call, `SCNetworkInterfaceCopyAll`, on a thread and prints the InterfaceNamer keys.
Host run on macOS: `receipts/scwait/` PASS (keys `*STACK*,*QUIET*,*QUIET&NAMED*`, returns at once; gate off silent).
One variable: `blazer_netstack=1`.

Result (`receipts/qemu-ab-result.txt`, runs `/data/hackios-qemu/research/ios26-apps-r1/runs/cfg1-qemu-{a,b}`):

| | A (no arg) | B (`blazer_netstack=1`) |
| --- | --- | --- |
| stack | no `blazer-netstack` lines | `published alone`; `IONetworkStack opened by configd[32] type 0, IOKit root busy 0` (between kernel t=181 and 211) |
| `Plugin:InterfaceNamer` | `none` from probe t=21.8 until **t=449.5: `*QUIET*,*TIMEOUT*,*TIMEOUT&NAMED*`** (kernel ≈505 s, ~300 s after setup) | `none` until **t=143.2: `*STACK*,*QUIET*,*QUIET&NAMED*,*COMPLETE*`** |
| SCNetworkInterfaceCopyAll | still blocked at the capture (kernel t≈511) | **returned after 154.4 s**, 0 interfaces |

**So configd hangs the same way in QEMU,** until its 300 s stack timer. IOKit was quiet in QEMU both times (A also has `*QUIET*`; it was
held back only by the missing stack connection). With the stack, InterfaceNamer answers as soon as it is set up. Under TCG with one
saturated CPU, configd only reached that at kernel t≈185 s; on the phone configd starts before t=118 with five cores. QEMU's IOKit
busy state says nothing about the phone's. The `opened by … busy` line on the phone does.

## 5. Image `a7-ios-system-cfg1` (Mac `research/images/`, HOST build)

- Recipe: r10-perf's (`perf/tools/run_mac.sh` step 3) via `tools/run_cfg1_mac.sh`. Changes: the kernel (ns1 above), and one
  phone-arg. **Overlay unchanged:** perf-r1.ovl 95701ed9 (`receipts/decode-diff.txt`: 49 identical, 0 differing). The
  HKMAIN watch in Preferences and `hk_deny bluetoothd,Spotlight` stay.
- Image tool: `tools/image_tool_cfg1.py` = r10's exact 45eadfe3 (`tools/image_tool.r10.py`, from the Mac's
  `live/net/tools/image_tool.before.py`) plus 3 lines: repo-relative paths, `blazer_netstack=1` allowlisted, and the
  manifest records the image tool that actually ran (c1f2de1b…). The Mac's shared `tools/image_tool.py` holds another owner's
  uncommitted usbnet edits and was not touched.
- **boot.img 9e48a97048f933fa0f907cc48b7fbcc0c33a7f29fbef7f9ee2ba810d63905373**, payload a6a0a4f0…, margin 39,999,040 B.
  `check`: `OK a7-ios-system-cfg1 bootable`.
- **Cmdline diff vs r10-perf** (`receipts/cmdline-diff.txt`): 1015 → 1012 bytes, 57 tokens. Token 55 `blazer_persona_log=1` →
  `blazer_netstack=1`; every other token is identical and in the same order. Both would make 1033 bytes, over the shim's 1023, and
  persona_log only prints persona alloc/free lines for the stopped apps lane. Entry, segments, plan, overlay placement, shim and cflags
  are unchanged. (`receipts/manifest-diff.txt`'s "token order CHANGED" line is a bug in that check: it expects every old token in the new line.)

## Attended test (owner, bare `fastboot boot`, then the return check)

`tools/bootios research/images/a7-ios-system-cfg1/boot.img a7-ios-system-cfg1 --mach research/ios26-phaseb-r1/configd/build/kernel.rootview-bl-aks-us2-ns1.unstripped --wait 480`

1. Wait for Home. Do not pull down on Home first.
2. Tap **Settings**, wait ~5 s, then scroll the list down and up, tap **General**, then back, then **Accessibility** > **Motion**.
   Note the time of the first gesture and what responds.
3. Keep using Settings ~30 s even if frozen, then go Home.
4. Owner: say what responded in 2.

Stop: a panic other than the 300 s deadline, Home lost, a backboardd SIGSEGV loop or a SpringBoard crash loop. Rollback: deadline/PSCI
reset to fastboot, then `return-check.sh`. Nothing is written (root read-only, `/private/var` in RAM).

## Read-out (ramdump; read only lines up to the first older boot's banner)

| Line | Meaning |
| --- | --- |
| `blazer-netstack: published alone`, then `IONetworkStack opened by configd[N] … busy 0` | InterfaceNamer posts *QUIET*/*COMPLETE* at once: the wait is gone |
| `… busy B>0`, `busy leaf …`, `IOKit quiet N ms after the open` | Settings' wait lasts until then (≤240 s); the leaves name what to fix next |
| no `opened by configd` | configd never matched or opened the stack: check `IOServiceOpen` (entitlement/IOUserClient path) |
| HKMAIN: `pings` +~10 per beat, `wait` small, `ev touch` grows | **Settings interactive** (the goal) |
| HKMAIN: stalls again with **different** frames | the next blocking call: symbolize with dsc_sym.py as before |
| HKMAIN: `pings` normal, `ev touch=0` while tapping | touches not delivered (perf/FIX.md §4 table) |
| `hk_deny: Spotlight refused … (refusal N)` at 128, 256, … | relaunch rate: N over time; 0 `Spotlight[N]` in HK TOP expected |
