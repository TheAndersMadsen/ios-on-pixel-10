#!/bin/sh
# Mac, repo root. HOST: what the hk-obs1 kernel holds. Writes receipts/kernel-verify.txt
set -u
O=research/ios26-phaseb-r1/live/obs; K=$O/build/kernel.obs1.unstripped; R=$O/receipts/kernel-verify.txt
NM="xcrun llvm-nm"; OD="xcrun llvm-objdump"
{
echo "kernel $(shasum -a 256 $K | cut -c1-64)  $K"
echo "branch hk-obs1 $(git -C research/ios26-release-r1/work/xnu rev-parse hk-obs1) parent $(git -C research/ios26-release-r1/work/xnu rev-parse hk-obs1~1)"
echo "undefined symbols: $($NM -u $K | wc -l | tr -d ' ')"
echo "-- symbols"
for s in _hk_obs_start _hk_obs_exec _hk_obs_exit _hk_obs_console _hk_obs_tick _hk_obs_final _hk_obs_panic _blazer_wifi_obs _blazer_wifi_obs_fw _blazer_bt_obs _blazer_bt_bridge_obs _blazer_usbcon_obs; do
  printf '%-26s %s\n' $s "$($NM $K | awk -v s=$s '$3==s{print $1, $2}')"; done
echo "-- strings"
for t in 'HKOBS %u %s t=%llu %s: %s' 'HKOBS %u %s t=%llu proc:%s%s' "rules' libraries in one DYLD_INSERT_LIBRARIES" 'budget %u B/s burst %u' 'off (no blazer_wifi=1)' 'off (no blazer_bt=)' 'off (no blazer_usbcon=)' 'bridge %s%s, level %d' 'hk_conlim' 'hk_conburst' 'console %s%s%s, stream %llu B'; do
  printf '%-48s %s\n' "$t" "$(strings -a $K | grep -cF "$t")"; done
echo "-- callers (bl or a tail-call b to the hook, in the function that should call it)"
call() { # function hook
  n=$($OD -d --no-show-raw-insn --disassemble-symbols=$1 $K 2>/dev/null | grep -cE "\sbl?\s.*<$2>")
  printf '%-28s -> %-22s %s\n' $1 $2 $n; }
call _cnwrite _hk_obs_console
call _proc_exit _hk_obs_exit
call _hk_exec_env_add _hk_obs_exec
call _panic_trap_to_debugger _hk_obs_panic
call _ufs_root_watch _hk_obs_tick
call _ufs_root_watch _hk_obs_final
call _hk_obs_report _blazer_wifi_obs
call _hk_obs_report _blazer_bt_obs
call _hk_obs_report _blazer_usbcon_obs
call _blazer_bt_obs _blazer_bt_bridge_obs
call _hakios_blazer_watch_start _hk_obs_start
echo "-- hk_exec_env_add present as a function (noinline): $($NM $K | grep -c ' _hk_exec_env_add$')"
echo "-- build warnings in changed files"
grep -E 'warning:' research/ios26-release-r1/logs/obs1-build.log | grep -E 'hk_obs|hk_env_merge|kern_exec|kern_exit|/cons\.c|debug\.c|blazer_wifi\.c|blazer_bcm4390|bt_bridge|btuart\.c|blazer_usbcon\.c|blazer_ufs\.c' | sort -u | head -20
echo "(end of warnings)"
} > $R 2>&1
cat $R
