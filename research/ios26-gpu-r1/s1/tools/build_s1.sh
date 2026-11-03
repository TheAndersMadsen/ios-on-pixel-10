#!/bin/bash
# SPDX-License-Identifier: MIT
# Mac only. Build kernel.gpu-m3-s1 = 58f0893 (hk-gpu-m2-r1, rung 6) + rung 7/8 S1 (bsd/dev/blazer_gpu_tipc.c, new bsd/dev/hmfw_s1_layout.h) on a new
# branch hk-gpu-m3-s1 of the release tree, under the fleet's kernel build slot; then put the tree back on p1 (b228c4f) and rebuild it there, as
# m2/tools/build_m2.sh did. blazer_gpu.c, hmfw_m2_layout.h, firmware bytes and MMU code are 58f0893's, unchanged.
# Usage (Mac checkout root): python3 research/ios26-gpu-r1/tools/with_slot.py research/ios26-gpu-r1/s1/tools/build_s1.sh
set -euo pipefail
ROOT=$(pwd)
SRC=$ROOT/research/ios26-gpu-r1/s1/src
X=$ROOT/research/ios26-release-r1/work/xnu
OBJ=$ROOT/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER
OUT=$ROOT/research/ios26-gpu-r1/artifacts
LOG=$ROOT/research/ios26-gpu-r1/s1/receipts
BR=hk-gpu-m3-s1
mkdir -p "$OUT" "$LOG"
cd "$X"
[ -z "$(git status --porcelain)" ] || { echo "STOP: release tree not clean"; git status --short; exit 1; }
[ "$(git branch --show-current)" = p1 ] || { echo "STOP: release tree not on p1"; exit 1; }
[ "$(git rev-parse --short=7 HEAD)" = b228c4f ] || { echo "STOP: p1 is not b228c4f"; exit 1; }
[ "$(git rev-parse --short=7 hk-gpu-m2-r1)" = 58f0893 ] || { echo "STOP: hk-gpu-m2-r1 is not 58f0893"; exit 1; }
! git rev-parse -q --verify "$BR" >/dev/null || { echo "STOP: $BR exists"; exit 1; }
[ ! -d /tmp/fleet/kernel-link.lock ] || { echo "STOP: a link holds /tmp/fleet/kernel-link.lock"; exit 1; }
[ "${HK_SLOT_HELD:-}" = 1 ] || { echo "STOP: run me through tools/with_slot.py"; exit 1; }
shasum -a 256 "$OBJ/kernel.development.blazer" "$OBJ/kernel.development.blazer.unstripped" | sed "s|$ROOT/||" > "$LOG/p1-before.sha256"
git show hk-gpu-m2-r1:bsd/dev/blazer_gpu_tipc.c | shasum -a 256 | sed 's|-|58f0893:bsd/dev/blazer_gpu_tipc.c|' > "$LOG/base.sha256"
git switch -c "$BR" hk-gpu-m2-r1
cp "$SRC/blazer_gpu_tipc.c" "$SRC/hmfw_s1_layout.h" bsd/dev/
cmp "$SRC/hmfw_m2_layout.h" bsd/dev/hmfw_m2_layout.h
git add bsd/dev/blazer_gpu_tipc.c bsd/dev/hmfw_s1_layout.h
git -c user.name="Anders Madsen" -c user.email=madsenanders97@gmail.com commit -q -m "blazer gpu tipc: rung 7 (M3 S1) sysinit coremem data store at +0x150 = 0xE1C013C000, strict trace gate; rung 8 control

blazer_gpu_tipc=7: rung 6 plus the one sysinit field stock fills (RGXSetupFwSysData, sCorememDataStoreDeprecated = raw device VA of the
coremem data section, 0xE1C0000000 + 0x13C000), written after the sysinit zero and before the publication barrier, read back before
power-on and SMC START (mismatch: STOP). The firmware trace is parsed strictly before HEALTH_CHECK and after STATEFLAGS_CTRL; any MMU
fault, lockup, failed HW poll, HW reset, assert, fw fault, bad HWR flag or FWCCB fault command stops the boot, before any command if
seen at boot. PASS: M3 S1 PASS, rung 7 S1 PASS panic. No client context, CCB or KICK. =8: =7 with the field left 0 (control).
Offsets: hmfw_s1_layout.h (research/ios26-gpu-r1/s1/tools/fw_layout_s1.c). Host test research/ios26-gpu-r1/s1/tests (612 checks, 30/30 mutants).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git log --oneline -1 | tee "$LOG/xnu-commit.txt"
git diff --stat hk-gpu-m2-r1 HEAD | tee -a "$LOG/xnu-commit.txt"
( /usr/bin/time -p "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 ) > "$LOG/build-s1.log" 2>&1 || { echo "STOP: build failed, see $LOG/build-s1.log"; tail -30 "$LOG/build-s1.log"; git switch p1; "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 > "$LOG/restore-p1.log" 2>&1; git branch --show-current; exit 1; }
cp "$OBJ/kernel.development.blazer" "$OUT/kernel.gpu-m3-s1"
cp "$OBJ/kernel.development.blazer.unstripped" "$OUT/kernel.gpu-m3-s1.unstripped"
cp "$OBJ/bsd/DEVELOPMENT/blazer_gpu_tipc.o" "$OUT/blazer_gpu_tipc.s1.o"
cp "$OBJ/bsd/DEVELOPMENT/blazer_gpu.o" "$OUT/blazer_gpu.s1.o"
grep -E "blazer_gpu|LD |KC |error|warning: .*blazer" "$LOG/build-s1.log" | head -20 > "$LOG/build-s1.summary.txt" || true
git switch p1
( /usr/bin/time -p "$ROOT/research/ios26-release-r1/tools/mk.sh" -j8 ) > "$LOG/restore-p1.log" 2>&1 || { echo "WARN: restore build failed, see $LOG/restore-p1.log"; exit 1; }
git status --short | head
git branch --show-current
git log --oneline -1
( cd "$OUT" && shasum -a 256 kernel.gpu-m3-s1 kernel.gpu-m3-s1.unstripped blazer_gpu_tipc.s1.o blazer_gpu.s1.o ) | tee "$LOG/SHA256SUMS.kernel"
shasum -a 256 "$OBJ/kernel.development.blazer" "$OBJ/kernel.development.blazer.unstripped" | sed "s|$ROOT/||" > "$LOG/restore-p1.sha256"
echo DONE
