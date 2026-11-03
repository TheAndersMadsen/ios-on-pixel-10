#!/bin/sh
# HOST ONLY (m1box). W1 r5: the RX buffer supply. r4's suite on the r5 sources (join.c is r4's, unchanged), plus:
#   ring_oracle (real r5 ring.c), console_oracle (real r5 blazer_bcm4390.c), their mutants, ARM64e objects with -DBLAZER and symbols,
#   and the firmware facts the fix stands on, read from Android's .57.31 bin + map (FW=). With K=<unstripped kernel> it checks that kernel too.
# Writes only ./build and ../receipts. No phone, QEMU, image or secret.
set -eu
cd "$(dirname "$0")"
R5=$(cd .. && pwd)
W=$(cd ../.. && pwd)
X=${XNU:-/data/hackios-qemu/wifi-r4/xnu}
L=${LLVM:-$HOME/.local/share/hackios-host/llvm/bin}
FW=${FW:-/data/hackios-qemu/wifi-r4/fw-57.31}
R=$R5/receipts
mkdir -p build "$R" build/inc/miscfs/ramfs
ln -sf "$X/bsd/miscfs/ramfs/varfs_overlay.h" "$X/bsd/miscfs/ramfs/varfs_tsv.h" build/inc/miscfs/ramfs/
INC="-iquote $R5/src -iquote $X/bsd/dev"
SAN="-std=c11 -O1 -g -DBLAZER -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra -Wno-missing-field-initializers -Wno-format"
export ASAN_OPTIONS=detect_leaks=0

# 0. The sources are the branch's
for f in blazer_bcm4390_ring.c blazer_bcm4390.c blazer_bcm4390_scan.c blazer_pcie1.h blazer_wifi.c blazer_bcm4390_join.c; do
  cmp -s "$R5/src/$f" "$X/bsd/dev/$f" || { echo "src/$f differs from $X"; exit 1; }
done
grep -q '^#define WIFI_DMA_BYTES  0x280000u' "$R5/src/blazer_wifi.c" && grep -q '^#define B4_DMA_NEEDED   0x280000u' "$R5/src/blazer_bcm4390_ring.c" \
  || { echo "WIFI_DMA_BYTES != B4_DMA_NEEDED"; exit 1; }

# 1. r5's own
"$L/clang" $SAN $INC ring_oracle.c -o build/ring_oracle
"$L/clang" $SAN $INC console_oracle.c "$R5/src/blazer_bcm4390.c" -o build/console_oracle
{ ./build/ring_oracle && ./build/console_oracle && python3 -I mutate_r5.py; } > "$R/r5-oracles.txt" 2>&1 || { cat "$R/r5-oracles.txt"; exit 1; }
cat "$R/r5-oracles.txt"

# 2. r4's join oracle + r5's M1 checks (join2_oracle_r5.c) on r5's join.c and scan.c; r2's reader oracle and composer tests
R4T=$W/r4/tests
"$L/clang" $SAN $INC join2_oracle_r5.c "$R5/src/blazer_bcm4390_scan.c" -o build/join2_oracle
./build/join2_oracle > "$R/join2-oracle.txt" 2>&1 || { cat "$R/join2-oracle.txt"; exit 1; }
tail -2 "$R/join2-oracle.txt"
"$L/clang" $SAN -Ibuild/inc $INC "$W/tests/kernel_oracle.c" "$R5/src/blazer_bcm4390_join.c" "$R4T/kernel_oracle_r4_stubs.c" -o build/kernel_oracle.r5
cp "$W/tests/build/kernel_oracle" build/kernel_oracle.saved 2>/dev/null || true
cp build/kernel_oracle.r5 "$W/tests/build/kernel_oracle"
python3 -I "$W/tests/test_compose_wifi_join.py" 2>&1 | tail -3 | tee "$R/compose-tests.txt"
[ -f build/kernel_oracle.saved ] && cp build/kernel_oracle.saved "$W/tests/build/kernel_oracle"

# 3. ARM64e objects, gates enabled (-DBLAZER), and their symbols and strings
AF="-target arm64e-apple-macos13.0 -DBLAZER -ffreestanding -fno-builtin -fno-stack-protector -O2 -std=c11 -c $INC -Wno-missing-field-initializers"
for o in ring bcm4390 scan join; do
  f=blazer_bcm4390_$o.c; [ $o = bcm4390 ] && f=blazer_bcm4390.c
  "$L/clang" $AF "$R5/src/$f" -o build/$o.arm64e.o
done
{
  for o in ring bcm4390 scan join; do
    echo "== $o.arm64e.o"; "$L/llvm-objdump" --macho --private-header build/$o.arm64e.o | sed -n 3,4p
  done
  for s in _b4_rx_post_all _b4_rx_bufs_wanted _b4_rx_witness _b4_rings _b4_poll; do
    "$L/llvm-nm" -g build/ring.arm64e.o | grep -q " T $s\$" && echo "ring defines $s" || { echo "MISSING $s"; exit 1; }
  done
  for s in _b4_console _b4_console_note; do
    "$L/llvm-nm" -g build/bcm4390.arm64e.o | grep -q " T $s\$" && echo "bcm4390 defines $s" || { echo "MISSING $s"; exit 1; }
  done
  "$L/llvm-nm" build/bcm4390.arm64e.o | grep -q " U _b4_console_note\$" && echo "bcm4390 is not calling a stub" || true
  for t in 'Firmware drops for want of a host buffer (EL 30 b8c8): %u'; do
    LC_ALL=C grep -qaF "$t" build/ring.arm64e.o && echo "ring string: $t" || { echo "ring MISSING string: $t"; exit 1; }
  done
  for t in 'rx: the firmware dropped a packet for the host: no host RX buffer was queued (EL 30 b8c8)'; do
    LC_ALL=C grep -qaF "$t" build/bcm4390.arm64e.o && echo "bcm4390 string: $t" || { echo "bcm4390 MISSING string: $t"; exit 1; }
  done
  for t in 'rx: %u buffers posted. The firmware takes up to %u (max_host_rxbufs); r1-r4 posted 64' 'rx: posted %u, above the %u the MAC fill holds: %s'; do
    LC_ALL=C grep -qaF "$t" build/scan.arm64e.o && echo "scan string: $t" || { echo "scan MISSING string: $t"; exit 1; }
  done
  LC_ALL=C grep -qaF 'join: M1 received: %s (supplicant %s)' build/join.arm64e.o && echo "join string: join: M1 received: %s (supplicant %s)" || { echo "join MISSING M1 string"; exit 1; }
  # The constants, from the object: RX_BUFS (1024 = 0x400) bounds b4_rx_bufs_wanted
  "$L/llvm-objdump" -d --no-show-raw-insn build/ring.arm64e.o | awk '/<_b4_rx_bufs_wanted>:/,/ret/' | tee build/wanted.s | grep -qE '#0x400|#1024' \
    && echo "ring: _b4_rx_bufs_wanted compares with 0x400 (1024)" || { echo "ring: 1024 not found in _b4_rx_bufs_wanted"; cat build/wanted.s; exit 1; }
  if [ -n "${K:-}" ]; then
    echo "== kernel $(sha256sum "$K" | cut -d' ' -f1)"
    for s in _b4_rx_post_all _b4_rx_bufs_wanted _b4_rx_witness _b4_console_note _b4_join_run _b4_rx_counters _blazer_wifi_net_secret; do
      "$L/llvm-nm" "$K" | grep -q " $s\$" && echo "kernel has $s" || { echo "kernel MISSING $s"; exit 1; }
    done
    for t in 'Firmware drops for want of a host buffer (EL 30 b8c8)' 'no host RX buffer was queued (EL 30 b8c8)' 'r1-r4 posted 64' 'join: M1 received: %s (supplicant %s)' 'above the %u the MAC fill holds' 'waiting for M1' 'join: keyed by method %u' 'rx: witness %s' 'version 27.10.1121.57.31'; do
      LC_ALL=C grep -qaF "$t" "$K" && echo "kernel string: $t" || { echo "kernel MISSING string: $t"; exit 1; }
    done
  fi
} > "$R/objects.txt" 2>&1 || { cat "$R/objects.txt"; exit 1; }
cat "$R/objects.txt"

# 4. The firmware facts (Android's .57.31: db46afd6 bin, 12cf6569 map), static
python3 -I "$R5/tests/fw_facts.py" "$FW/fw_bcmdhd.bin_4390_b1" "$FW/fw_bcmdhd.map_4390_b1" > "$R/fw-facts.txt" 2>&1 || { cat "$R/fw-facts.txt"; exit 1; }
cat "$R/fw-facts.txt"

sha256sum build/ring_oracle build/console_oracle build/*.arm64e.o ring_oracle.c console_oracle.c join2_oracle_r5.c mutate_r5.py fw_facts.py run.sh \
  "$R5/src/"* | sed "s|$R5/||" | tee "$R/SHA256SUMS"
