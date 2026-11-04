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

## usbhost
SUBSYS: usbhost
SRC: xnu/osfmk/arm64/blazer_usbhost.c, blazer_usbhost_core.inc (branch hk-usbhost1 = hk-obs1 + research/ios26-phaseb-r1/usbhost/patches/0001); host model usbhost/tests/test_usbhost.c
ARGS: blazer_usbhost=1 (refused with any blazer_usbcon*/blazer_usbnet*: one controller, one owner), blazer_usbhost_wait=S (90), blazer_usbhost_window=S (150); image a7-ios-system-usbhost1
TAGS: `blazer-usbhost:` (survey, gadget halted, host mode, xhci, root ports, running, port N connect/reset, slot, ENUM, PASS, stop), `blazer-dp:` (planned, DP alt mode)
SIG: `blazer-usbhost: stop: no device` → no USB2 connect in the window: the phone does not source VBUS, so the device needs a powered hub
SIG: `blazer-usbhost: gadget no halt after 100 ms` → the shim's gadget kept running; nothing was reset (by design, the result is that line)
SIG: `blazer-usbhost: refused: blazer_usbcon owns the controller` → image has both; host mode needs a console-free image (ramdump path)
TOOLS: `hk logs --sub usbhost` (ramdump); `python3 -I tools/probe_eval.py --row usb-host --row usb-host-enumerate --row dp-video-out <attempt>`; host test `usbhost/tests/run.sh`
DOCS: research/ios26-phaseb-r1/usbhost/USBHOST.md (hardware map, role-switch safety, attended test, DP alt-mode stages D0-D5)
OPEN: never booted (HOST + ARM64 object only); VBUS sourcing (TCPC + charger OTG over SPMI) and PD/DP alt mode are owner decisions

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

## charger
SUBSYS: charger
SRC: xnu/iokit/Kernel/arm/blazer_gauge.c (SPMI spmi@53f1000, EXT_REG_READ frames only), blazer_charger.h (pure decode) on branch hk-chg1; blazer_charge_policy.c (pure planner, not built)
ARGS: blazer_battery_chg=1 (status → iOS external/charging), blazer_battery_chg=2 (report only: one line per gauge sample, iOS state unchanged; needs hk-chg1); both need blazer_battery=1
TAGS: `blazer-battery: charger N in=usb|wireless|both|none chg=cc|cv|topoff|done|off… mode= cp= wdt= cc= cv= icl= wicl= ichgin= iwcin= vwcin=` (hklog power split)
SIG: `blazer-battery: charger report N unread` → one charger frame came back with SPMI error bits; the gauge sample still stands
SIG: `leaving the controller alone from here on` → a frame timed out or CONTROL/REQ_COMMAND moved: gauge and charger both stop for the boot
TOOLS: `hk logs --sub power --grep 'charger '`; `python3 -I tools/probe_eval.py --row charging --row wireless-charging <attempt>`
DOCS: research/ios26-phaseb-r1/chg/PLAN.md (tests), REGISTERS.md (map, vendor links), CONTROL.md (write design, owner approval)
OPEN: never booted; charger IC max77779chrg SPMI SID 3; wireless RX CPS4041 is behind the max77779 I2C master (SID 2, 0x30), detected only via WCIN; any write (CHGCC limit) needs owner approval

## cpu
SUBSYS: cpu
SRC: xnu/iokit/Kernel/arm/SweetCPU.cpp (PSCI CPU_ON per ADT cpu node, `startAll`), xnu/pexpert/pexpert/arm64/SWEET.h (SWEET_SMP_MAX_CPUS 8); shim/tgl_fastcore.c (cpu0 hands XNU to 0x200, stays parked), shim/tgl_cpu_audit.c (cpu0 reads; mode 2 Errata ABI queries); tools/image_tool.py `cpu_order` (core 7 refused), tools/cpu_audit.py, tools/cpu_dvfs_check.py
ARGS: cpus=N (the ADT holds N nodes: N is the count), blazer_bootcpu=0x200, blazer_smp_report=1, blazer_smp_test=1, blazer_cpu0_audit=1|2 (shim, needs --cpu-audit), image_tool --cpus/--cpu-order/--bootcpu
TAGS: `SWEET CPU: requested=N selected=N`, `SWEET CPU: cpu=N mpidr=0xM came alive; SGI1 OK`, `SWEET CPU: N/N CPUs initialized`, `blazer-gov`, `blazer-clock`, `blazer-cpu`; stamps `cpu0-actlr`, `cpu0-em-version`, `cpu0-em-features`, `cpu0-em-erratum` (stamps-decode.txt)
SIG: `SWEET CPU: 5/5 CPUs initialized` → the built topology (five A725 nodes 0x200-0x600), not a startup failure; A520 0x0/0x100 and X4 0x700 are left out of the ADT on purpose (research/ios26-cpu-smp-r1/SMP.md)
SIG: `SWEET CPU: cpu=N NOT alive: PSCI CPU_ON rc=-4` → ALREADY_ON: that core is cpu0 (0x0), parked in the shim under blazer_bootcpu
SIG: `SWEET CPU: cpu=N mpidr=0xM NOT alive after 5s` → CPU_ON accepted but the core never reached initCPU (entry/MMU/GIC); stop, no retry
SIG: stamps-decode `cpu0-em-version DONE 0xffffffffffffffff (EM not-supported)` → firmware has no Errata Management ABI; the A520 answers must come from elsewhere
TOOLS: `hk logs --sub power`; `python3 -I tools/probe_eval.py --row a520-cores --row x4-core <attempt>`; `python3 -I tools/cpu_audit.py <attempt>/ramdump/kernel.log <image>/manifest.json` (mode 1 or 2)
DOCS: docs/CPU.md, research/ios26-cpu-smp-r1/SMP.md, research/ios26-cpu-complete-r3/
OPEN: firmware's own answer for A520 erratum 3685825 (CPUACTLR[9] clear on cpu0; a7-cpu0-em-r1 built, not booted); X4 errata (3076789, 2957258, 4118414) cannot be queried from cpu0; cpu0 release from the shim park; higher clocks

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

## modem
SUBSYS: modem
SRC: xnu/bsd/dev/blazer_modem.c (glue), blazer_modem_core.c/.h (hardware-free ladder; hk-modem1 = hk-int3 + research/ios26-modem-r1/src; hk-modem2 f9f81c5 = hk-int4 + research/ios26-modem-r1/modem2/src); host tests research/ios26-modem-r1/{tests,modem2/tests}/run.sh
ARGS: hk_dbg bits 24..27 = stage (1 read, 2 ctrl, 3 phy, 4 link, 5 bar [modem2]), bit 28 hold; or blazer_modem=N, blazer_modem_hold=1, blazer_modem_force=1. Off by default
TAGS: `blazer-modem:` (read:, pad, ctrl:, phy:, rc:, cp:, link:, id:, survey:, bar:, tidy:, verdict: rung N, verdict:, stopped:); planned `cell:`, `blazer-gnss:`/`gnss:`; `HKL CommCenter[` (net.log), `HKL locationd[` (location.log)
SIG: `blazer-modem: verdict: STOP stage N, at X: <reason>` → the named rung failed; everything driven was tidied (tidy: errors 0x0)
SIG: `blazer-modem: verdict: rung N (name) STOP: <reason>` (modem2) → that rung; later rungs print SKIP. Rungs 1..4 PASS PHYSICAL in a7-sweep1 (2026-11-04)
SIG: panic right after `bar: command … Next: read 16 words of BAR0` → BAR0 read not decoded, DWC SError (modem2 rung 5)
SIG: `read: CP as found: NOT off` → stage 4 refuses to power the CP (`CP not off as found`); rerun stage 1 and compare pad TX values
SIG: `link: attempt 4 failed … LTSSM 0x…` with `cp: powered` → CP ROM did not train: check CP2AP pads after power, PHY table, phy_fw clock
TOOLS: `hk logs --grep blazer-modem`; `python3 -I tools/probe_eval.py --row Cellular <attempt>`; `hk find --feature modem`
DOCS: research/ios26-modem-r1/MODEM.md (S5400 map, CommCenter/ARI gap, rungs 5..11 and GNSS G1..G2), PHONE-TEST.md, modem2/MODEM2.md (sweep1 decode, rung 5), COMMCENTER.md (why CommCenter is absent: `_LimitLoadToDeviceTree baseband`), docs/CONNECTIVITY.md
OPEN: no physical run yet (rung 0 659b370 and stages 1..4 never booted). CP firmware (rung 6+) needs an owner decision; CommCenter on iPhone12,3 speaks ARI, the S5400 SIPC

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

## nfc
SUBSYS: nfc
SRC: xnu/bsd/dev/blazer_nfc_hw.c (pure, host-tested), blazer_nfc.c, blazer_cli10_bus.h + the cli10 lock in blazer_haptic.c (branch hk-nfc1); research/ios26-nfc-r1/tests/
ARGS: blazer_nfc=1..4 (1 pads read-only, 2 power + identify, 3 NCI init, 4 RF discovery), blazer_nfc_wait=1..60 (stage 4 listen s), blazer_nfc_delay=30..600 (default 60), blazer_nfc_keep=1
TAGS: `blazer-nfc:` (pad …, chip st21nfc fw/hw/loader/nci, address 0x08 acked/never acked, rsp <CMD> status, nci init ok, tag: <tech> … id, discovery: …, ends: <stop>)
SIG: `blazer-nfc: address 0x08 never acked` → ST21NFC not powered (enable pad hsion 1 polarity/mux) or needs the 19.2 MHz clock (OPEN)
SIG: `blazer-nfc: chip in loader mode` → controller firmware not in router mode; no NCI is sent
SIG: `blazer-nfc: core generic error ntf` during stage 4 → RF needs ST config/clock (OPEN)
SIG: haptic `tap N rc 16` while blazer-nfc runs → EBUSY by design (the cli10 bus lock), the tap is skipped
TOOLS: `hk logs --grep blazer-nfc`; `python3 -I tools/probe_eval.py --row nfc <attempt>`; host `sh research/ios26-nfc-r1/tests/run.sh`
DOCS: research/ios26-nfc-r1/DESIGN.md (pins, ST HAL facts, phone test and expected lines)
OPEN: never booted on the phone (a7-ios-system-nfc1 built); RF clock pads not driven; no iOS nfcd service or mirror rule yet

## camera
SUBSYS: camera
SRC: xnu/bsd/dev/blazer_torch.c, blazer_torch_hw.c (LM3644 flash on CLI7 i2c@3a301000 0x63; p1 = stages 1-2, branch hk-cam1 2e8d777 = stages 3-4); research/ios26-camera-r1/tests/test_blazer_torch.c (host model)
ARGS: blazer_torch=1 look, 2 id (needs CLI7 already I2C), 3 select I2C + id, 4 + torch LED1 then LED2 at 12 mA (hk-cam1 only); blazer_torch_ms=500..5000 (default 2000), blazer_torch_delay=30..600 (default 45)
TAGS: `blazer-torch:` (cli was, cli select, pads were, chip answered, ledN on/off, stop, ends, summary); planned `blazer-cam:` (PMIC/sensor ID); `HKL cameracaptured[` once mirrored
SIG: `cli was 2,1,1` then `stop cli, detail 0x2` → loader left CLI7 in UART; p1 stages 1-2 never reach the controller (torch-1-r1). Use hk-cam1 blazer_torch=3|4
SIG: `stop lines-low` after `pads muxed to cli7` → SCL/SDA low: bus pull-up rail off (INFERENCE: CAMIO ldo_22s); F2 rail check
SIG: `stop flags, detail 0x<f1><f2>` → LM3644 fault flag in torch (Flags1 0x7e / Flags2 0x1b bits); LED already in standby, EN dropped
TOOLS: `hk find --feature camera`; `hk logs --grep blazer-torch`; `python3 -I tools/probe_eval.py --row 'Cameras, flash' <attempt>`
DOCS: research/ios26-camera-r1/CAMERA.md (camera path map, stage plan), research/ios26-camera-r1/PHONE-TEST.md (cam1 boot)
OPEN: cam1 (blazer_torch=4) not booted; sensors need PMIC GPIO/rail frames (da9188 GPIO 2,5,8,9,15 + SLG51002 LDOs) and MCLK; ISP/CSI capture needs vendor register tables

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
