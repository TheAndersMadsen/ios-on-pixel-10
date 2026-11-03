#!/bin/sh
# Mac, repo root. HOST/ARM64: what the hk-nfc1 kernel holds. Writes receipts/kernel-verify.txt
set -u
O=research/ios26-nfc-r1; K=$O/build/kernel.nfc1.unstripped; R=$O/receipts/kernel-verify.txt; X=research/ios26-release-r1/work/xnu
NM="xcrun llvm-nm"; OD="xcrun llvm-objdump"
{
echo "kernel $(shasum -a 256 $K | cut -c1-64)  $K"
echo "branch hk-nfc1 $(git -C $X rev-parse hk-nfc1) parent $(git -C $X rev-parse hk-nfc1~1)"
echo "undefined symbols: $($NM -u $K | wc -l | tr -d ' ')"
echo "-- symbols"
for s in _blazer_nfc_init _nf_init _nf_run _nf_stop_name _blazer_cli10_enter _blazer_cli10_exit _blazer_haptic_init _blazer_haptic_play_rom; do
  printf '%-26s %s\n' $s "$($NM $K | awk -v s=$s '$3==s{print $1, $2}')"; done
echo "-- strings"
for t in 'blazer-nfc: stage %u, starts in %u s' 'blazer-nfc: ends: %s, stage %u' 'chip st21nfc fw 0x%08x hw 0x%02x' 'address 0x%02x %s, power-up reset ntf %s' 'nci init ok: nci 0x%02x' 'tag: %s, protocol 0x%x, id %s' 'discovery: %s after %u rf notifications' 'blazer-cli10' 'blazer-haptic: tap feedback on'; do
  printf '%-48s %s\n' "$t" "$(strings -a $K | grep -cF "$t")"; done
echo "-- callers (bl or a tail-call b)"
call() { n=$($OD -d --no-show-raw-insn --disassemble-symbols=$1 $K 2>/dev/null | grep -cE "\sbl?\s.*<$2>"); printf '%-28s -> %-22s %s\n' $1 $2 $n; }
call _bsd_init _blazer_nfc_init
call _bsd_init _blazer_haptic_init
call _blazer_haptic_play_rom _blazer_cli10_exit
echo "-- haptic_thread / nfc_thread are static: their lock calls, by disassembly of every function calling the lock"
$OD -d --no-show-raw-insn $K 2>/dev/null | awk '/^[0-9a-f]+ <.*>:$/{f=$2} /\sbl\s.*<_blazer_cli10_(enter|exit)>/{print f, $NF}' | sort | uniq -c
echo "-- lck_mtx_try_lock in blazer_haptic_play_rom: $($OD -d --no-show-raw-insn --disassemble-symbols=_blazer_haptic_play_rom $K 2>/dev/null | grep -c 'lck_mtx_try_lock')"
echo "-- build warnings in changed files"
grep -E 'warning:' research/ios26-release-r1/logs/nfc1-build.log | grep -E 'blazer_nfc|blazer_haptic|bsd_init' | sort -u | head -20
echo "(end of warnings)"
} > $R 2>&1
cat $R
