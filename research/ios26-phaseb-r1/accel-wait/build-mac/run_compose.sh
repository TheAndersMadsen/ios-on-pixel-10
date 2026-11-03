#!/bin/sh
# Mac only: compose both overlays, decode-diff each against the base, run the release-header consumer. HOST ONLY.
set -eu
cd "$(dirname "$0")"
REPO=$(cd ../../../.. && pwd)
CUO=$REPO/research/ios26-opt-20261102/combined_ui_overlay
BASE=$CUO/artifacts/artwork-container-battery-observe-r1.ovl
mkdir -p receipts out
python3 -I compose.py | tee receipts/compose.txt
# release headers: the pinned copies, and say whether the live release tree still matches them
for h in kern/hk_exec_rules.h miscfs/ramfs/varfs_overlay.h miscfs/ramfs/varfs_tsv.h; do
  cmp -s "$CUO/inputs/r1/bsd/$h" "$REPO/research/ios26-release-r1/work/xnu/bsd/$h" && echo "live == pinned $h" || echo "live DIFFERS from pinned $h"
done > receipts/release-headers.txt
xcrun clang -arch arm64 -DBLAZER=1 -DARM64_BOARD_CONFIG_SWEET=1 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-sanitize-recover=all -idirafter "$CUO/inputs/r1/bsd" accel_consumer.c -o out/accel_consumer
for pair in "artwork-container-battery-observe-accel-r1 probe" "artwork-container-battery-observe-accel-skip-r1 skip"; do
  set -- $pair
  python3 -I decode_diff.py "$BASE" overlays/$1.ovl out/hk_accel_once.dylib > receipts/$1.decode-diff.txt
  out/accel_consumer "$BASE" overlays/$1.ovl $2 > receipts/$1.consumer.txt
done
python3 -I decode_diff.py overlays/artwork-container-battery-observe-accel-r1.ovl overlays/artwork-container-battery-observe-accel-skip-r1.ovl > receipts/probe-vs-skip.decode-diff.txt
shasum -a 256 overlays/*.ovl overlays/*.json compose.py decode_diff.py accel_consumer.c run_compose.sh build.sh | tee receipts/SHA256SUMS.overlays
