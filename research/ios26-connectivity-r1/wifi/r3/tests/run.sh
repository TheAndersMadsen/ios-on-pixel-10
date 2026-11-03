#!/bin/sh
# HOST ONLY (m1box). W1 r3: the two-method join. Builds and runs join2_oracle (real r3 join.c + real r3 gate in scan.c), its mutants,
# r2's kernel-reader oracle and composer tests against the r3 sources (b4_net_parse is unchanged), and emits ARM64 objects of both r3
# files with their expected symbols. With K=<unstripped kernel> it also checks that kernel for r3's symbols and strings.
# Writes only ./build and ../receipts. No phone, QEMU, image or secret.
set -eu
cd "$(dirname "$0")"
R3=$(cd .. && pwd)
W=$(cd ../.. && pwd)
REPO=$(cd ../../../../.. && pwd)
X=$REPO/research/ios26-release-r1/work/xnu
L=${LLVM:-$HOME/.local/share/hackios-host/llvm/bin}
R=$R3/receipts
mkdir -p build "$R" build/inc/miscfs/ramfs
ln -sf "$X/bsd/miscfs/ramfs/varfs_overlay.h" "$X/bsd/miscfs/ramfs/varfs_tsv.h" build/inc/miscfs/ramfs/
INC="-iquote $R3/src -iquote $X/bsd/dev"
SAN="-std=c11 -O1 -g -DBLAZER -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -Wno-missing-field-initializers"

# 1. The two methods, the part between them, the gate
"$L/clang" $SAN $INC join2_oracle.c "$R3/src/blazer_bcm4390_scan.c" -o build/join2_oracle
{ ./build/join2_oracle && python3 -I mutate_join2.py; } > "$R/join2-oracle.txt" 2>&1 || { cat "$R/join2-oracle.txt"; exit 1; }
cat "$R/join2-oracle.txt"

# 2. r2's reader oracle and composer tests, on the r3 sources (the overlay record and its reader don't change)
"$L/clang" $SAN -Ibuild/inc $INC "$W/tests/kernel_oracle.c" "$R3/src/blazer_bcm4390_join.c" -o "$W/tests/build/kernel_oracle.r3"
cp "$W/tests/build/kernel_oracle" build/kernel_oracle.r2-saved 2>/dev/null || true
cp "$W/tests/build/kernel_oracle.r3" "$W/tests/build/kernel_oracle"
python3 -I "$W/tests/test_compose_wifi_join.py" 2>&1 | tail -3 | tee "$R/compose-tests.txt"
[ -f build/kernel_oracle.r2-saved ] && cp build/kernel_oracle.r2-saved "$W/tests/build/kernel_oracle"

# 3. ARM64 objects, gates enabled (-DBLAZER), and their symbols
AF="-target arm64e-apple-macos13.0 -DBLAZER -ffreestanding -fno-builtin -fno-stack-protector -O2 -std=c11 -c $INC"
"$L/clang" $AF "$R3/src/blazer_bcm4390_join.c" -o build/blazer_bcm4390_join.arm64e.o
"$L/clang" $AF -Wno-missing-field-initializers "$R3/src/blazer_bcm4390_scan.c" -o build/blazer_bcm4390_scan.arm64e.o
{
  for o in join scan; do
    echo "== blazer_bcm4390_$o.arm64e.o"
    "$L/llvm-objdump" --macho --private-header build/blazer_bcm4390_$o.arm64e.o | sed -n 3,4p
  done
  for s in _b4_net_parse _b4_join_run _b4_join_heard _b4_join_event _b4_net_rx _b4_on_flow_created _b4_join_pre_up _b4_join_pre_clm; do
    "$L/llvm-nm" -g build/blazer_bcm4390_join.arm64e.o | grep -q " T $s\$" && echo "join defines $s" || { echo "MISSING $s"; exit 1; }
  done
  for s in _b4_ioctl_allowed _b4_gate_level _b4_scan; do
    "$L/llvm-nm" -g build/blazer_bcm4390_scan.arm64e.o | grep -q " T $s\$" && echo "scan defines $s" || { echo "MISSING $s"; exit 1; }
  done
  for t in 'join: method 1: Android' 'join: keyed by method %u' 'join: method 1 over: disassociate' 'wsec_info' 'join_pref' 'sup_wpa to 1 before the interface is up'; do
    LC_ALL=C grep -qaF "$t" build/blazer_bcm4390_join.arm64e.o && echo "join string: $t" || { echo "join MISSING string: $t"; exit 1; }
  done
  for t in wsec_info join_pref chanspec; do
    LC_ALL=C grep -qaF "$t" build/blazer_bcm4390_scan.arm64e.o && echo "scan (gate) string: $t" || { echo "scan MISSING string: $t"; exit 1; }
  done
  if [ -n "${K:-}" ]; then
    echo "== kernel $(sha256sum "$K" | cut -d' ' -f1)"
    for s in _b4_net_parse _b4_join_run _b4_ioctl_allowed _blazer_wifi_net_secret _b4_img_fw; do
      "$L/llvm-nm" "$K" | grep -q " $s\$" && echo "kernel has $s" || { echo "kernel MISSING $s"; exit 1; }
    done
    for t in 'join: method 1: Android' 'join: keyed by method %u' 'join: method 2: r2' 'join: method 1 over: disassociate' 'sup_wpa to 1 before the interface is up' 'join: passphrase given to the firmware by wsec_info' 'the image holds a network' blazer_wifi_join; do
      LC_ALL=C grep -qaF "$t" "$K" && echo "kernel string: $t" || { echo "kernel MISSING string: $t"; exit 1; }
    done
  fi
} 2>&1 | tee "$R/objects.txt"
sha256sum build/join2_oracle build/blazer_bcm4390_join.arm64e.o build/blazer_bcm4390_scan.arm64e.o join2_oracle.c mutate_join2.py run.sh \
  "$R3/src/blazer_bcm4390_join.c" "$R3/src/blazer_bcm4390_scan.c" "$R3/src/blazer_pcie1.h" | tee "$R/SHA256SUMS"
