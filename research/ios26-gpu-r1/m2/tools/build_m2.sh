#!/bin/bash
# SPDX-License-Identifier: MIT
# Mac only. Build kernel.gpu-m2-r1 = d30f785 (hk-gpu-survey-r1) + rung 6 (bsd/dev/blazer_gpu_tipc.c, blazer_gpu.c, hmfw_m2_layout.h) on a new branch
# hk-gpu-m2-r1 of the release tree, under the fleet's kernel build slot; then put the tree back on p1 (b228c4f) and rebuild it there, as build_r1.sh did.
# Usage (Mac checkout root): tools/with_slot.py-held: python3 research/ios26-gpu-r1/tools/with_slot.py research/ios26-gpu-r1/m2/tools/build_m2.sh
set -euo pipefail
ROOT=$(pwd)
SRC=$ROOT/research/ios26-gpu-r1/m2/src
X=$ROOT/research/ios26-release-r1/work/xnu
OBJ=$ROOT/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER
OUT=$ROOT/research/ios26-gpu-r1/artifacts
LOG=$ROOT/research/ios26-gpu-r1/m2/receipts
BR=hk-gpu-m2-r1
mkdir -p "$OUT" "$LOG"
cd "$X"
[ -z "$(git status --porcelain)" ] || { echo "STOP: release tree not clean"; git status --short; exit 1; }
[ "$(git branch --show-current)" = p1 ] || { echo "STOP: release tree not on p1"; exit 1; }
[ "$(git rev-parse --short=7 HEAD)" = b228c4f ] || { echo "STOP: p1 is not b228c4f"; exit 1; }
[ ! -d /tmp/fleet/kernel-link.lock ] || { echo "STOP: a link holds /tmp/fleet/kernel-link.lock"; exit 1; }
[ "${HK_SLOT_HELD:-}" = 1 ] || { echo "STOP: run me through tools/with_slot.py"; exit 1; }
git switch -c "$BR" d30f785
cp "$SRC/blazer_gpu_tipc.c" "$SRC/blazer_gpu.c" "$SRC/hmfw_m2_layout.h" bsd/dev/
git add bsd/dev/blazer_gpu_tipc.c bsd/dev/blazer_gpu.c bsd/dev/hmfw_m2_layout.h
git -c user.name="Anders Madsen" -c user.email=madsenanders97@gmail.com commit -q -m "blazer gpu tipc: rung 6 (M2) firmware view from shared memory, stock-order HEALTH_CHECK then STATEFLAGS_CTRL execution check

blazer_gpu_tipc=6: rung 4 with the firmware trace log on (TRACEBUF log type, one 12000-word buffer), then the firmware's
view of our OS before any kick (OS runtime flags, CR poll, fault and assert buffers, FWCCB, read-only), HEALTH_CHECK as
RGXFWHealthCheckCmd sends it (consumption only), STATEFLAGS_CTRL with no flag change whose return slot stock waits on,
the view again, the raw firmware log, and blazer_gpu=3's 18 REE registers (blazer_gpu_survey_live). Rungs 1-5 unchanged.
Offsets: hmfw_m2_layout.h (fw_layout_r2.c). Host test research/ios26-gpu-r1/m2/tests (75 checks, 12/12 mutants).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git log --oneline -1 | tee "$LOG/xnu-commit.txt"
( /usr/bin/time -p "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 ) > "$LOG/build-m2.log" 2>&1 || { echo "STOP: build failed, see $LOG/build-m2.log"; tail -30 "$LOG/build-m2.log"; git switch p1; "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 > "$LOG/restore-p1.log" 2>&1; git branch --show-current; exit 1; }
cp "$OBJ/kernel.development.blazer" "$OUT/kernel.gpu-m2-r1"
cp "$OBJ/kernel.development.blazer.unstripped" "$OUT/kernel.gpu-m2-r1.unstripped"
cp "$OBJ/bsd/DEVELOPMENT/blazer_gpu_tipc.o" "$OUT/blazer_gpu_tipc.m2.o"
cp "$OBJ/bsd/DEVELOPMENT/blazer_gpu.o" "$OUT/blazer_gpu.m2.o"
grep -E "blazer_gpu|LD |KC |error" "$LOG/build-m2.log" | head -20 > "$LOG/build-m2.summary.txt" || true
git switch p1
( /usr/bin/time -p "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 ) > "$LOG/restore-p1.log" 2>&1 || { echo "WARN: restore build failed, see $LOG/restore-p1.log"; exit 1; }
git status --short | head
git branch --show-current
git log --oneline -1
( cd "$OUT" && shasum -a 256 kernel.gpu-m2-r1 kernel.gpu-m2-r1.unstripped blazer_gpu_tipc.m2.o blazer_gpu.m2.o ) | tee "$LOG/SHA256SUMS.kernel"
shasum -a 256 "$OBJ/kernel.development.blazer" "$OBJ/kernel.development.blazer.unstripped" | sed "s|$ROOT/||" > "$LOG/restore-p1.sha256"
echo DONE
