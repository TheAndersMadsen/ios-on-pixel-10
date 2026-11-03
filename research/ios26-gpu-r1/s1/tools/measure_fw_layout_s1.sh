#!/bin/bash
# SPDX-License-Identifier: MIT
# Build and run fw_layout_s1.c against the pinned vendor tree (default /data/hackios-gpu-ref/powervr on m1box, out of git) with
# m3/tools/measure_fw_layout_r3.sh's include set. Writes src/hmfw_s1_layout.h (guarded) and receipts/fw-layout-s1.{h,txt}.
set -euo pipefail
S1=$(cd "$(dirname "$0")/.." && pwd)
V=${1:-/data/hackios-gpu-ref/powervr}
INC=$(python3 -I -c "
from pathlib import Path; V=Path('$V'); s={V/'pixel/lga/production'}
for p in (V/'pvrsrvkm').rglob('*.h'):
    for q in p.parents:
        if q==V: break
        s.add(q)
print(' '.join('-I'+str(x) for x in sorted(s)))")
T=$(mktemp -d)
${CC:-cc} -std=gnu11 -O0 $INC "$S1/tools/fw_layout_s1.c" -o "$T/fw_layout_s1"
"$T/fw_layout_s1" > "$S1/receipts/fw-layout-s1.h"
echo "cc: $(${CC:-cc} --version | head -1); vendor: $V" > "$S1/receipts/fw-layout-s1.txt"
{ printf '/* SPDX-License-Identifier: MIT\n * Copyright (c) 2026 hackios contributors. Measured from the pinned lga production DDK headers (5940a317) by\n * research/ios26-gpu-r1/s1/tools/fw_layout_s1.c (receipts/fw-layout-s1.h). Numeric layout facts only. */\n#ifndef HMFW_S1_LAYOUT_H\n#define HMFW_S1_LAYOUT_H\n'
  cat "$S1/receipts/fw-layout-s1.h"; printf '#endif\n'; } > "$S1/src/hmfw_s1_layout.h"
rm -rf "$T"
