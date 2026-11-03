#!/bin/bash
# SPDX-License-Identifier: MIT
# Mac only. Build kernel.gpu-survey-r1 = 7227fe7 (kernel.rootview's commit) + the new bsd/dev/blazer_gpu.c, on a new branch of the
# release tree, under the fleet's kernel build slot; then put the tree back on p1 (b228c4f) and rebuild it there, as RESULT-bl.md did.
# Usage (from the Mac checkout root): research/ios26-gpu-r1/tools/build_r1.sh <new blazer_gpu.c>
set -euo pipefail
NEW=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
ROOT=$(pwd)
X=$ROOT/research/ios26-release-r1/work/xnu
OBJ=$ROOT/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER
OUT=$ROOT/research/ios26-gpu-r1/artifacts
LOG=$ROOT/research/ios26-gpu-r1/receipts
BR=hk-gpu-survey-r1
mkdir -p "$OUT" "$LOG"
cd "$X"
[ -z "$(git status --porcelain)" ] || { echo "STOP: release tree not clean"; git status --short; exit 1; }
[ "$(git branch --show-current)" = p1 ] || { echo "STOP: release tree not on p1"; exit 1; }
[ "$(git rev-parse --short=7 HEAD)" = b228c4f ] || { echo "STOP: p1 is not b228c4f"; exit 1; }
[ ! -d /tmp/fleet/kernel-link.lock ] || { echo "STOP: a link holds /tmp/fleet/kernel-link.lock"; exit 1; }
[ "${HK_SLOT_HELD:-}" = 1 ] || { echo "STOP: run me through tools/with_slot.py"; exit 1; }
git switch -c "$BR" 7227fe7
cp "$NEW" bsd/dev/blazer_gpu.c
git add bsd/dev/blazer_gpu.c
git -c user.name="Anders Madsen" -c user.email=madsenanders97@gmail.com commit -q -m "blazer gpu: blazer_gpu=3 read-only register survey and timer tick check after stage 1's CORE_ID PASS

Reads only, after the existing power-up and CORE_ID check and before its power-down: the registers stock's REE debug dump
reads with plain OSReadHWReg (Clk, EVENT_STATUS, MMU fault/status, SLC), from a 64 KiB view of rgx, and RGX_CR_TIMER twice
1 ms apart. Modes 1 and 2 unchanged. Host test research/ios26-gpu-r1/tests (820 checks, 11/11 mutants).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git log --oneline -1 | tee "$LOG/xnu-commit.txt"
( /usr/bin/time -p "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 ) > "$LOG/build-r1.log" 2>&1 || { echo "STOP: build failed, see $LOG/build-r1.log"; tail -30 "$LOG/build-r1.log"; git switch p1; "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 > "$LOG/restore-p1.log" 2>&1; git branch --show-current; exit 1; }
cp "$OBJ/kernel.development.blazer" "$OUT/kernel.gpu-survey-r1"
cp "$OBJ/kernel.development.blazer.unstripped" "$OUT/kernel.gpu-survey-r1.unstripped"
cp "$OBJ/bsd/DEVELOPMENT/blazer_gpu.o" "$OUT/blazer_gpu.o"
grep -E "blazer_gpu|LD |KC |error" "$LOG/build-r1.log" | head -20 > "$LOG/build-r1.summary.txt" || true
# Restore: p1, rebuilt, so the next owner finds the tree and objects as they were (link not reproducible: UUID differs)
git switch p1
( /usr/bin/time -p "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 ) > "$LOG/restore-p1.log" 2>&1 || { echo "WARN: restore build failed, see $LOG/restore-p1.log"; exit 1; }
git status --short | head
git branch --show-current
git log --oneline -1
( cd "$OUT" && shasum -a 256 kernel.gpu-survey-r1 kernel.gpu-survey-r1.unstripped blazer_gpu.o ) | tee "$LOG/SHA256SUMS.kernel"
shasum -a 256 "$OBJ/kernel.development.blazer" "$OBJ/kernel.development.blazer.unstripped" | sed "s|$ROOT/||" > "$LOG/restore-p1.sha256"
echo DONE
