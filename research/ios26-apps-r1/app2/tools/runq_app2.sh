#!/bin/sh
# runq_app2.sh NAME KERNEL OVERLAY RUNTIME : usersession/tools/runq.sh (r23's tail, root apps-logmirror-r14, persona log)
# with the overlay as an argument. One slot. QEMU only.
TAIL="launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 sweetarm64e=1 autounlock=0 blazer_panic=1 hk_usertrace=1 hk_fb_scanout=1 sweetfb_noconsole=1 sweetfb_hz=60 varfs=1 blazer_deadline=1800 interrupt-masked-debug-mode=0 sched_preemption_disable_debug_mode=0 wdt=-1 hk_top=30 hk_overlay=0xA0080081 hk_ui_trace=1 blazer_persona_log=1"
cd /data/hackios-qemu/research/ios26-apps-r1 && HACKIOS_QEMU_SLOTS=1 exec python3 tools/qemu-ufsroot.py "$1" --kernel "$2" --root artifacts/apps-logmirror-r14.img --window-gib 28 --var-overlay "$3" --runtime "$4" --idle "$4" --wait 1800 --args "$TAIL"
