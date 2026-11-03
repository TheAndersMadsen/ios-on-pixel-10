#!/bin/sh
# launch.sh NAME ROOT : one detached guest on the r23/r26 route at r24's length (QEMU only)
cd /data/hackios-qemu/research/ios26-apps-r1
TAIL="launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 sweetarm64e=1 autounlock=0 blazer_panic=1 hk_usertrace=1 hk_fb_scanout=1 sweetfb_noconsole=1 sweetfb_hz=60 varfs=1 blazer_deadline=1800 interrupt-masked-debug-mode=0 sched_preemption_disable_debug_mode=0 wdt=-1 hk_top=30 hk_overlay=0xA0080081 hk_ui_trace=1 blazer_persona_log=1"
HACKIOS_QEMU_SLOTS=3 exec python3 tools/qemu-ufsroot.py "$1" --kernel app2/kernel.rootview-bl-app2 --root "$2" --window-gib 32 --var-overlay app2/qemu-app2-r1.ovl --runtime 1800 --idle 1800 --wait 1800 --args "$TAIL"
