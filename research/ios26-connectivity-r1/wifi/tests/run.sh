#!/bin/sh
# HOST ONLY (m1box). Builds the kernel-source oracle, runs the composer's tests, emits ARM64 objects of the unchanged
# release sources the join boot depends on, and checks the A7-r3 kernel (ddf874fb) for the symbols and boot-arg strings.
# Writes only ./build and ../receipts. No phone, QEMU or image action.
set -eu
cd "$(dirname "$0")"
W=$(cd .. && pwd)
REPO=$(cd ../../../.. && pwd)
X=$REPO/research/ios26-release-r1/work/xnu
L=${LLVM:-$HOME/.local/share/hackios-host/llvm/bin}
K=$REPO/research/ios26-dualboot-r8/rootview/kernel.rootview.unstripped
R=$W/receipts
mkdir -p build "$R"
mkdir -p build/inc/miscfs/ramfs
ln -sf "$X/bsd/miscfs/ramfs/varfs_overlay.h" "$X/bsd/miscfs/ramfs/varfs_tsv.h" build/inc/miscfs/ramfs/
# Only the two overlay headers: -I$X/bsd would shadow the host libc's sys/ headers
# r2 (branch hk-wifi-pass): the join and its header from ../r2/src, everything else from the release tree
INC="-Ibuild/inc -iquote $W/r2/src -iquote $X/bsd/dev"

# 1. Oracle: real varfs_overlay.h + real blazer_bcm4390_join.c, host executable, ASan/UBSan
"$L/clang" -std=c11 -O1 -g -DBLAZER -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra $INC \
  kernel_oracle.c "$W/r2/src/blazer_bcm4390_join.c" -o build/kernel_oracle
# 1b. Key oracle: the real configure()/set_key() against a recording ioctl, and its mutants
"$L/clang" -std=c11 -O1 -g -DBLAZER -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Wextra $INC key_oracle.c -o build/key_oracle
./build/key_oracle > "$R/key-oracle.txt" 2>&1 || { cat "$R/key-oracle.txt"; exit 1; }
python3 -I mutate_key.py >> "$R/key-oracle.txt" 2>&1 || { cat "$R/key-oracle.txt"; exit 1; }
cat "$R/key-oracle.txt"

# 2. Composer tests (they call build/kernel_oracle)
python3 -I test_compose_wifi_join.py 2>&1 | tee "$R/tests.txt"

# 2b. image_tool-w1.patch on a scratch copy of HEAD tools/: its own suite, then the W1 token tests
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
for e in "$REPO"/*; do [ "$(basename "$e")" = tools ] || ln -s "$e" "$T/$(basename "$e")"; done
(cd "$REPO" && git --no-optional-locks archive HEAD tools) | tar -x -C "$T"
(cd "$T" && patch -s -p1 < "$W/image_tool-w1.patch")
(cd "$T/tools" && python3 test_image_tool.py 2>&1 | tail -2) | tee "$R/image_tool-suite.txt"
python3 -I test_image_tool_w1.py "$T/tools" 2>&1 | tee "$R/image_tool-w1.txt"

# 3. ARM64 objects of the sources the join boot runs (unchanged here: a compile and symbol check, not a new implementation)
AF="-target arm64e-apple-macos13.0 -DBLAZER -ffreestanding -fno-builtin -fno-stack-protector -O2 -std=c11 -c $INC"
"$L/clang" $AF "$W/r2/src/blazer_bcm4390_join.c" -o build/blazer_bcm4390_join.arm64e.o
{
  echo "== blazer_bcm4390_join.arm64e.o"
  "$L/llvm-objdump" --macho --private-header build/blazer_bcm4390_join.arm64e.o | sed -n 1,4p
  for s in _b4_net_parse _b4_join_run _b4_join_heard _b4_join_event _b4_net_rx _b4_on_flow_created _b4_join_pre_up _b4_join_pre_clm; do
    "$L/llvm-nm" -g build/blazer_bcm4390_join.arm64e.o | grep -q " T $s\$" && echo "defines $s" || { echo "MISSING $s"; exit 1; }
  done
  echo "== A7-r3 kernel $(sha256sum "$K" | cut -c1-16) (unstripped; stripped kernel.rootview is ddf874fb, A7-r3's mach)"
  for s in _b4_net_parse _b4_join_run _blazer_wifi_net_secret _blazer_wifi_net_ready _blazer_wifi_net_addr _b4_img_fw _b4_img_clm _b4_img_txcap _b4_img_nv_7311; do
    "$L/llvm-nm" "$K" | grep -q " $s\$" && echo "kernel has $s" || { echo "kernel MISSING $s"; exit 1; }
  done
  for t in blazer_wifi_join blazer_wifi_stage blazer_wifi_net blazer_wifi_run 'join: dry run done' 'en0 address err' 'the image holds a network' HKVarOverlay; do
    LC_ALL=C grep -qaF "$t" "$K" && echo "kernel string: $t" || { echo "kernel MISSING string: $t"; exit 1; }
  done
} 2>&1 | tee "$R/objects.txt"
sha256sum build/kernel_oracle build/key_oracle build/blazer_bcm4390_join.arm64e.o ../tools/compose_wifi_join.py kernel_oracle.c key_oracle.c mutate_key.py test_compose_wifi_join.py test_image_tool_w1.py ../image_tool-w1.patch run.sh \
  "$REPO/research/ios26-wifi-r1/tools/mkwifisecret.py" "$W/r2/src/blazer_bcm4390_join.c" "$W/r2/src/blazer_pcie1.h" "$X/bsd/miscfs/ramfs/varfs_overlay.h" "$X/bsd/dev/blazer_wifi_net.c" | tee "$R/SHA256SUMS"
