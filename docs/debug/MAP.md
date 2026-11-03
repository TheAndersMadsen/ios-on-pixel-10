# Debug map (LLM-oriented)

One block per subsystem. Every field starts a line, so `grep -A12 '^SUBSYS: wifi' docs/debug/MAP.md` gives one subsystem,
and `grep '^SIG:' docs/debug/MAP.md` lists every known failure signature. The `SUBSYS` ids are the `hk find --feature` ids
(tools/test_hk.py checks this). Paths: `xnu/…` = the release XNU tree (m1box mirror `research/ios26-release-r1/work/xnu`, Mac
nested repo of the same path; branches named in the linked docs); `shim/…` = this repo. Facts come from NOTES.md, the Phase B
LEDGER and the linked receipts. `OPEN` lines are open questions, not findings.

Field keys: `SRC` source, `ARGS` boot-args, `TAGS` console prefixes (also hklog's split rules in `tools/hklog.py SUBSYSTEMS`),
`SIG` known failure signature → cause (crashdoc hint id in brackets, from `tools/crashdoc.py HINTS`), `TOOLS`, `DOCS`, `OPEN`.

Cross-cutting: current state is `NOTES.md`; per-run one-liners are `research/ios26-phaseb-r1/LEDGER.md`; the attempt store
is `attempts/` (`hk find`). Evidence classes: SOURCE, HOST, QEMU, PHYSICAL. Never transfer acceptance between them.

## shim
SUBSYS: shim
SRC: shim/shim.c shim/start.S shim/loader.c shim/stamp.c shim/laguna_usb*.c shim/tgl_*.c (UFS, DCS display, CPM, fast start)
ARGS: build-time gates, not boot-args: TGL_UFS_*, TGL_ALL_DCS, TGL_DCS_HANDOFF, TGL_DCS_BRIGHT, TGL_FASTCORE, TGL_USB_DISABLE (manifest `cflags`)
TAGS: TEGU USB, TGL USB (usb.log); TSHIMST1/TSHIMST2 stamps at PA 0x95430000 (not console text)
SIG: `FAIL no TSHIMST1/TSHIMST2 magic` in stamps-decode.txt → shim never started its channel, or the dump predates v3.2
SIG: installed menu, iOS pick, red "Preparing for ram dump", last stamp #30 usb-warm ENTER → USB not started on a cold power-on (fixed by `--cold-safe`, chooser-ios-r3)
TOOLS: `hk report` (stamps via the runner's stamps-decode.txt); `python3 -I tools/decode-shim-stamps.py <attempt>/ramdump/kernel.log --json`
DOCS: docs/BUILD.md, research/ios26-dualboot-r8/chooser-ios/COLD-r3.md
OPEN: none recorded here

## chooser
SUBSYS: chooser
SRC: shim/chooser.c shim/chooser_ios.c shim/keys_laguna.c shim/menu_ui.c shim/tgl_dcs_menu.c; tools/chooser_ios_image.py
ARGS: image flags --keys --default-ios --cold-safe (chooser_ios_image.py); not XNU boot-args
TAGS: shim stamps only; the Android branch is checked by the return check
SIG: CPM Assert `lpb.c:676 sswrp_id < LPB_NUM_SSWRPS` on LPCM FE0 off → wrong LPCM off frame field order (fixed r11: vendor send_lpcm_mail order)
SIG: volume keys ignored, ring never moves → keys sampled only between redraws (fixed r13: sampled per drawn row)
TOOLS: `hk images --feature chooser`; `hk cycle research/images/chooser-…` (hk_cycle plain mode); `hk back`
DOCS: research/ios26-dualboot-r8/chooser-ios/DESIGN.md, research/ios26-dualboot-r8/keys/DIAG-r13.md, research/ios26-dualboot-r8/display-handback/SUSPEND-ORDER.md
OPEN: boot_b holds chooser-ios-int1 (readback aca7c0fc, LEDGER 21:13); iOS from power-on with int1 not yet owner-confirmed

## dualboot
SUBSYS: dualboot
SRC: research/ios26-dualboot-r8/return-check.sh, canaries.sh; tools/gpt_plan.py tools/persist_check.py
ARGS: none
TAGS: return-check.json `verdict`
SIG: return check `FAIL: <keys>` → the named hard check (serial, slot_b, su, sentinel, pkg3, data size, nVHE, screencap)
TOOLS: `hk back` (force-fastboot off, fastboot reboot, return check into attempts/<id>/return/)
DOCS: docs/DUALBOOT.md, GOAL.md, research/ios26-dualboot-r8/NEEDS-OWNER.md, research/android-backup-20261103/RESTORE.md
OPEN: none recorded here

## xnu
SUBSYS: xnu
SRC: xnu/bsd/dev/hakios.blazer_ufs.c (root, deadline), xnu/bsd/kern/kern_exec.c (hk_env/hk_deny exec rules, xnu/bsd/kern/hk_exec_rules.h), xnu/bsd/miscfs/ramfs/varfs_overlay.h (/private/var overlay)
ARGS: blazer_deadline=N (boot ends with a deadline panic → park → ramdump), rd=ufsroot0 (normal boot) vs rd=md0 (restore-like), varfs=1, hk_overlay=MASK, hk_env, hk_deny, msgbuf=1048576, debug=0x8
TAGS: `blazer-root: watch t N ms`, `panic(cpu N caller …): blazer-root: deadline N s, stage …`, `Darwin Kernel Version`, `exec <name>`, `com.apple.xpc.launchd|`
SIG: `blazer-root: deadline N s` panic → planned end of every boot, not a fault [blazer-deadline]
SIG: QEMU KVM: last line "EARLY 8: leaving bootstrap console mapping", data abort 0x96000006 → KVM does not boot XNU; use TCG
TOOLS: `hk logs --sub launchd|proc|panic`; `hk crash`; reader verdict in `hk find` (`reader` column)
DOCS: research/ios26-phaseb-r1/A7.md, research/ios26-phaseb-r1/RUN.md
OPEN: Home needs about 10 min with some kernels (deadline 1800); r3/int1 reached it within 300/900 s

## storage
SUBSYS: storage
SRC: xnu/bsd/dev/hakios.blazer_ufs*.c/.inc, hakios.blazer_persist_disk.inc, hakios.blazer_persist_table.inc
ARGS: blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=ios_system blazer_ufs_lun=0; blazer_persist=1 (refused by image_tool until the physical persist test); blazer_ufs_fake/_size (QEMU only)
TAGS: `blazer-root:`, `blazer_ufs` lines in other.log
SIG: none recorded beyond the deadline line
TOOLS: `python3 -I tools/persist_check.py snapshot|compare` (Android side, read only)
DOCS: docs/DUALBOOT.md, research/ios26-dualboot-r8/ios-data-persist/PHYSICAL-PLAN.md, NEGATIVE-r1.md
OPEN: physical ios_data persist test not run (needs a visible A7 Home first)

## usb
SUBSYS: usb
SRC: xnu/osfmk/arm64/blazer_usbcon.c, blazer_usbcon_core.inc, blazer_usbcon_input.inc; tools/usbcon.py (host reader)
ARGS: blazer_usbcon=1|2 blazer_usbcon_ch9=1 blazer_usbcon_input=1 (live TAP/HOME/KEY/SWIPE) blazer_usbcon_snap=1 (live snapshot)
TAGS: `blazer-usbcon` (refusals: `blazer-usbcon: refused:`), `HK LIVE` (input receipts)
SIG: live input refused → image has `hk_ui=` or `sweethidtest` (they disable live input)
TOOLS: `hk boot` (live_boot.sh starts the single usbcon reader first); `hk shot`; `hk ui`
DOCS: research/ios26-phaseb-r1/live/UNATTENDED.md
OPEN: EP0 requests 0x71+ unassigned (0x60..0x6b HLI1+snapshot, 0x70 hk_ustack)

## net
SUBSYS: net
SRC: xnu/bsd/dev/blazer_usbnet.c, blazer_usbnet_queue.h (UNQ_PHONE_IP/UNQ_MAC_IP), blazer_usbnet_log.h (dbg1-net branch); tools/usbnet_mac.py (Mac plan)
ARGS: blazer_usbnet=1 blazer_usbnet_direct=1 (plus blazer_usbcon); IONetworkStack registration for configd is the int1 configd fix
TAGS: `blazer-usbnet:` (mode, configured, alt 1, link up, en2 … err 0, rx/tx arp/icmp), `IONetworkStack`, `InterfaceNamer`
SIG: `blazer-usbnet: stopped, DMA ownership not reusable` → bus error, terminal by design (no retry)
SIG: `configured`, never `alt 1` → Mac did not bind AppleUserECM or the accessory was not allowed
TOOLS: `hk logs --sub net`; `hk state` (ios_shell)
DOCS: research/ios26-phaseb-r1/live/NET.md (diagnosis table, pass criteria)
OPEN: never booted: ECM binding, bulk DMA and console coexistence unproven on the phone (DBG1)

## shell
SUBSYS: shell
SRC: research/ios26-phaseb-r1/live/src/hk_shell.c (dylib injected into powerd by hk_env), live/tools/live_overlay.py, overlay live-r1.ovl
ARGS: none new (overlay + hk_overlay mask); needs the net subsystem for (A); config /private/var/hk/hk_shell.conf
TAGS: `HKSHELL:` (up, net listening/bind failed), `HKSHELL top:` (console fallback table every 30 s)
SIG: `HKSHELL net: bind … failed (1 Operation not permitted)` → powerd's sandbox blocks the listener; retarget the host daemon
TOOLS: `hk shell CMD`, `hk push`, `hk restart`, `hk stacks PROC --live` (spindump)
DOCS: research/ios26-phaseb-r1/live/SHELL.md, research/ios26-phaseb-r1/hub/HUB.md (put/kill builtins proposal)
OPEN: not booted; the root has no /bin/sh, kill or launchctl, so push/restart need hk_shell builtins (DBG2)

## display
SUBSYS: display
SRC: xnu/iokit/Kernel/arm/SweetFramebuffer.cpp, sweet_scanout.cpp, blazer_display120.c, SweetSurface.cpp; shim/tgl_display*.c, tgl_dcs.c
ARGS: hk_fb_* (hk_fb_scale, hk_fb_refresh, …), sweetfb_hz, hk_panel_hz, hk_bright=N (needs the calibration patch), canvas 1125x2511 (image_tool --canvas)
TAGS: `SWEET FB`, `SWEET BL`, `SWEET SURF`, `tensor-dpu`, `hk_fb`, `HK FB`; HK TOP `frames+N`
SIG: backboardd usertrap at unslid 0x1e2746924 (CoreBrightness NULL marketing table) → hk_bright=140 without backlight-calibration-parameters [corebrightness-calibration]
TOOLS: `hk logs --sub display`; `hk shot` / `hk shot --dump`
DOCS: research/ios26-phaseb-r1/corebrightness/FINDINGS.md, research/ios26-phaseb-r1/brightness/FIX.md, research/ios26-phaseb-r1/display/
OPEN: completed-frame rate never measured; presentation counts are not FPS

## compositor
SUBSYS: compositor
SRC: userland (backboardd, BaseBoard, containermanagerd); overlay fixes hk_container_ready, hk_flatmat.dylib (SpringBoard)
ARGS: hk_env rules in the overlay (HK_CONTAINER_READY=retry)
TAGS: `HKL backboardd[`, `HKL containermanagerd[`, `IOK backboardd`
SIG: backboardd SIGABRT, `-[NSURL initFileURLWithPath:]` nil → BSSystemSharedDirectoryForIdentifier got NULL from container_system_path_for_identifier [backboardd-nsurl-container]
SIG: Control Center tiles black → CABackdropLayer materials with no own fill; hk_flatmat flattens them
TOOLS: `hk logs backboardd`; `hk crash`; `hk stacks backboardd` (needs hk_ustack=backboardd)
DOCS: research/ios26-apps-r1/receipts/l1-r16/LANE1.md, research/ios26-phaseb-r1/cc/FIX.md
OPEN: QEMU never reproduces the NSURL abort (0 respawns in 15 min): phone-side timing

## gpu
SUBSYS: gpu
SRC: xnu/bsd/dev/blazer_gpu.c, blazer_gpu_fw.c, blazer_gpu_fwif.h, blazer_gpu_tipc.c
ARGS: blazer_gpu=N (3 = read-only survey; gpu2 rung 6 = health check)
TAGS: `blazer-gpu` (other.log; HKOBS when built in)
SIG: none recorded (gpu2: fw_faults 0, assert empty)
TOOLS: `hk logs --grep blazer-gpu`
DOCS: docs/NATIVE-METAL.md, research/ios26-metal-native-20261102/
OPEN: first real command stream (M3); native Metal drawing not done

## input
SUBSYS: input
SRC: xnu/bsd/dev/blazer_touch*.c, hakios.blazer_keys.c, blazer_haptic*.c, xnu/iokit/Kernel/arm/hid/SweetHID.cpp; live input xnu/osfmk/arm64/blazer_usbcon_input.inc
ARGS: blazer_touch*, touch_* (touch_flip, touch_palm, …), blazer_usbcon_input=1
TAGS: `blazer-touch`, `blazer-keys`, `blazer-haptic`, `blazer-power-key`, `SWEET HID`, `SWEET TOUCH`, `HK LIVE`
SIG: taps open Home icons but no in-app controls or edge gestures → touches indirect (IsDisplayIntegrated unset; fixed e731e68 hk-touch-direct)
TOOLS: `hk ui SCRIPT` (tools/ui_run.py, canvas pixels), `hk logs --sub input`
DOCS: research/ios26-phaseb-r1/touch/FIX.md, research/ios26-phaseb-r1/live/UNATTENDED.md, research/ios26-phaseb-r1/live/uidrive/
OPEN: clean scripted TAP acceptance on the phone (no retry) not yet recorded

## power
SUBSYS: power
SRC: xnu/bsd/dev/blazer_power.c, blazer_charge_policy.c, hakios.blazer_rtc.c, hakios.blazer_thermal.c, xnu/iokit/Kernel/arm/SweetBattery.cpp, blazer_gauge.c
ARGS: blazer_power, blazer_power_period, blazer_battery_*, sweetbattery
TAGS: `blazer-battery`, `blazer-rtc`, `blazer-thermal`, `HKBATT`
SIG: none recorded (pwr1: battery %, clock, lock button, haptics PASS by owner)
TOOLS: `hk logs --sub power`
DOCS: research/ios26-phaseb-r1/pwr/
OPEN: none recorded here

## cpu
SUBSYS: cpu
SRC: xnu/iokit/Kernel/arm/SweetCPU.cpp; shim/tgl_cpu_audit.c, tgl_fastcore.c; tools/cpu_audit.py, cpu_dvfs_check.py
ARGS: cpus=5, bootcpu (image_tool --bootcpu 0x200)
TAGS: `blazer-gov`, `blazer-clock`, `blazer-cpu`, `SWEET CPU`
SIG: none recorded
TOOLS: `hk logs --sub power`
DOCS: docs/CPU.md, research/ios26-cpu-complete-r3/
OPEN: higher clocks and the A520 cores not accepted

## perf
SUBSYS: perf
SRC: xnu/osfmk/kern/hk_top.c (HK TOP, hk_hog); overlay hk_mainwatch.dylib (HKMAIN)
ARGS: hk_top=N, hk_hog, hk_pmu, hk_vmstat
TAGS: `HK TOP: t=N frames+N cpu_ms=N: proc[pid]=ms …`, `HKMAIN` (main-thread stalls)
SIG: Spotlight ~31 s and launchd ~28 s CPU per 30 s → Spotlight/launchd spinning (r8-settings)
TOOLS: `hk logs --grep '^HK TOP'`; `hk stacks PROC`
DOCS: research/ios26-phaseb-r1/perf/FIX.md, research/ios26-phaseb-r1/accel-wait/FINDINGS.md
OPEN: none recorded here

## settings
SUBSYS: settings
SRC: userland (Preferences, configd); kernel IONetworkStack registration (int1)
ARGS: overlay hk_deny / hk_env rows
TAGS: `HKL configd[`, `HKMAIN`, `CRASH Preferences`
SIG: Preferences main thread blocked in SCNetworkInterfaceCopyAll → SCDynamicStoreNotifyWait (configd never answers) [configd-ionetworkstack]
SIG: Preferences killed `0x8badf00d` → launch watchdog while blocked on configd [preferences-launch-watchdog]
SIG: Preferences usertrap in sandbox_extension_consume → our Sandbox stand-in returns ENOENT for op 5, so tokens are NULL [preferences-sandbox-token]
SIG: Settings > About: Preferences SIGABRT right after tccd answers kTCCServiceMediaLibrary with generic_extension="invalid" [about-preferences-medialibrary]
TOOLS: `hk stacks Preferences` (hk_ustack=Preferences); `hk logs Preferences`; `hk crash`
DOCS: research/ios26-phaseb-r1/configd/FIX.md, research/ios26-phaseb-r1/settings/FIX.md
OPEN: none recorded here

## apps
SUBSYS: apps
SRC: userland (lsd, usermanagerd, containermanagerd, MobilePhone); tools/ios_app_inventory.py, ios_app_register.m
ARGS: rd=ufsroot0 (normal boot; usermanagerd --init runs), blazer_aks_usersession/blazer_aks_wrap (hk-aks-usersession branch only)
TAGS: `HKL lsd[`, `HKL usermanagerd[`, `usertrap:`, `userabort:`, `CRASH <proc> reason ns N code 0xN`
SIG: lsd `INVALID_PERSONA` → `Could not get user container URL! Must abort.` → no personas for the user (AKS user-session keybag; owner decision)
SIG: MobilePhone exc 6 at MobilePhone+0x1e2bc0 → +[CNContactStore contactStore] nil (tccd does not report AddressBook authorized), force-unwrap [mobilephone-contacts-tcc]
SIG: AccessibilityUIServer abort, CoreData 0x185bff6c0 → root build pruned AXSSPunctuationModel.momd [axui-punctuation-model]
SIG: MessagesBlastDoorService SIGTRAP (`CRASH MessagesBlastDoo … code 0x5`) → Swift fatalError after sandbox_check; the SWEET sandbox stub returns 0 for every op [blastdoor-sandbox-check]
TOOLS: `hk crash`, `hk logs lsd`, `hk stacks MobilePhone`
DOCS: docs/IOS-APPS-IDENTITY.md, research/ios26-apps-r1/receipts/h3-static-r12/VERDICT.md, research/ios26-apps-r1/crashes-r9/FINDINGS.md
OPEN: stock-app registration and foreground launches; lane stopped behind MKBUserSessionLoadKeybagForUser

## security
SUBSYS: security
SRC: xnu/iokit/Kernel/arm/SweetAMFIService.cpp, SweetKeyStore.cpp, SweetEntitlements.cpp, blazer_aks_trace.inc
ARGS: blazer_aks_log; blazer_aks_wrap/blazer_aks_usersession (branch hk-aks-usersession only; e731e68-based kernels ignore them)
TAGS: `SWEET AKS`, `SWEET AMFI`, `SWEET Sandbox`, `SWEET KEYSTORE`, `FIPSPOST`
SIG: none recorded (b1-aks: software wrap/unwrap PASS)
TOOLS: `hk logs --sub security`
DOCS: docs/IOS-APPS-IDENTITY.md
OPEN: SEP and Apple identity out of scope (closed lanes: jailbreak, injection frameworks, kernel debugger stubs)

## wifi
SUBSYS: wifi
SRC: xnu/bsd/dev/blazer_wifi*.c, blazer_bcm4390*.c, blazer_pcie1.c, blazer_apple80211.c, xnu/iokit/Kernel/arm/BlazerWiFiServices.cpp
ARGS: blazer_wifi=1, blazer_wifi_join, blazer_wifi_ios, blazer_wifi_hold, blazer_wifi_end, …
TAGS: `blazer-wifi`, `blazer-pcie`, `blazer-apple80211`, `IO80211`, `HKOBS … wifi:` (phase, at, stop, join, sup status/reason), `HKL wifid[`
SIG: join `status 4 reason 14`, firmware never answers M1 → open (a7-wifi-join-r2)
SIG: Settings waits on `wifi.manager` ×8 → missing Wi-Fi services block Settings (r7-touch)
TOOLS: `hk logs --sub wifi`; `hk logs wifid`; `hk find --feature wifi`
DOCS: docs/CONNECTIVITY.md, research/ios26-connectivity-r1/wifi/, research/ios26-phaseb-r1/live/OBS.md (HKOBS wifi fields)
OPEN: why the firmware never answers M1

## bt
SUBSYS: bt
SRC: xnu/bsd/dev/blazer_btuart*.c, blazer_bt_bridge.c, blazer_bt_gate.c
ARGS: blazer_bt, blazer_bt_end, blazer_bt_tx
TAGS: `blazer-bt`, `blazer-btuart`, `btsk:`, `HKL bluetoothd[`
SIG: none recorded
TOOLS: `hk logs --sub bt`
DOCS: docs/CONNECTIVITY.md
OPEN: bluetoothd is denied (hk_deny) in perf-r1-based overlays; enabling it is B2/B3

## audio
SUBSYS: audio
SRC: xnu/bsd/dev/blazer_audio.c, blazer_aoc.c
ARGS: blazer_audio, blazer_audio_pcm, blazer_audio_rt
TAGS: `HKL audiomxd[`
SIG: none recorded
TOOLS: `hk logs audiomxd`
DOCS: docs/CONNECTIVITY.md
OPEN: no audio service

## sensors
SUBSYS: sensors
SRC: xnu/bsd/dev/blazer_sensors.c, blazer_sensor_hw.c
ARGS: blazer_sensors, blazer_sensors_keep, blazer_sensors_mag, blazer_sensors_flip
TAGS: `HKL locationd[` (location.log)
SIG: none recorded
TOOLS: `hk logs --sub location`
DOCS: research/ios26-phaseb-r1/ (sens2 image)
OPEN: none recorded here

## screen
SUBSYS: screen
SRC: xnu osfmk/arm64/hk_screen.c, hk_screen_pure.inc (branch hk-screen-dbg5); tools/fb_png.py, tools/screenshot.sh
ARGS: hk_screen=N (HKSCR1 record at PA 0x95550000, every N s, deadline, panic), hk_screen_box=0, blazer_usbcon_snap=1 (live)
TAGS: `HK SCREEN:`
SIG: fb_png `record is not from this boot (stale …)` → the image lacks hk_screen, or the record is residue (exit 4)
TOOLS: `hk shot` (live), `hk shot --dump`
DOCS: research/ios26-phaseb-r1/live/SCREEN.md
OPEN: R/B order on the glass unverified

## ustack
SUBSYS: ustack
SRC: xnu osfmk/kern/hk_ustack.c, hk_ustack_pure.inc, hk_ustack_wire.h (branch hk-ustack-dbg4; also in int1); live/ustack/tools/ustack_sym.py
ARGS: hk_ustack=NAME[,NAME…] (≤4), hk_ustack_s, hk_ustack_n, hk_ustack_max; EP0 0x70 live request
TAGS: `HK USTACK:`, `HK USIMG:`
SIG: main thread `st=W hint=PortReceive x16=-47` every round, cpu+ small → idle run loop (not blocked)
TOOLS: `hk stacks PROC [--full]`
DOCS: research/ios26-phaseb-r1/live/USTACK.md
OPEN: none recorded here

## obs
SUBSYS: obs
SRC: hk_logmirror.dylib (live/obs/src), xnu hk-obs1 (HKOBS status lines, HKL console budget); tools/hklog.py
ARGS: none (overlay mirror rule); obs1 image = int1 cmdline
TAGS: `HKL <prog>[<pid>] <message>`, `HKL <prog>[<pid>] -- N lines dropped`, `HKOBS <n> <id> t=<s> <sub>: …` (wifi, bt, fw, usb, proc)
SIG: `HKL … -- N lines dropped (HK_LOGMIRROR budget)` → mirror budget hit, lines lost (counted)
TOOLS: `hk logs PROC` (hkl/<prog>.log), `hk logs --sub proc` (respawns = execs − 1)
DOCS: research/ios26-phaseb-r1/live/OBS.md
OPEN: obs1 not booted on the phone

## integration
SUBSYS: integration
SRC: research/ios26-phaseb-r1/int/ (hk-int1 484717f + overlay int1-r1)
ARGS: int1 cmdline (1018 B)
TAGS: all of the above
SIG: see display, settings, apps
TOOLS: `hk find --feature integration`
DOCS: research/ios26-phaseb-r1/int/INT1.md
OPEN: none recorded here

## qemu
SUBSYS: qemu
SRC: research/ios26-apps-r1/tools/qemu-ufsroot.py (rig /data/hackios-qemu), tools/qemu_preflight.py
ARGS: translated from the phone image (qemu_preflight: HARNESS_OWNED, QEMU_PROVEN, PHONE_ONLY)
TAGS: same console as the phone
SIG: KVM data abort at "leaving bootstrap console mapping" → use TCG (CALIBRATION.md)
TOOLS: `hk qemu IMAGE_DIR`; slot lock /tmp/fleet/qemu-guest-slot.lock (not the phone lease)
DOCS: research/ios26-apps-r1/receipts/m1box-rig/CALIBRATION.md
OPEN: QEMU results are QEMU results; no Tensor hardware
