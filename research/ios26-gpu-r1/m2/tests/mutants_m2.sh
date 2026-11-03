#!/bin/bash
# SPDX-License-Identifier: MIT
# Each mutant of src/blazer_gpu_tipc.c must make tests/test_m2.c fail. Run from research/ios26-gpu-r1/m2. Output dir: $1 (scratch).
set -u
OUT=${1:?scratch dir}; mkdir -p "$OUT"
build() { cc -std=gnu11 -w -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=undefined -Itests/inc -I"$1" tests/test_m2.c -o "$OUT/t" 2>"$OUT/cc.err"; }
mutate() {
  local name=$1 from=$2 to=$3 d="$OUT/m"; rm -rf "$d"; mkdir -p "$d"; cp src/hmfw_m2_layout.h "$d/"
  python3 -I -c 'import sys; s=open(sys.argv[1]).read(); assert s.count(sys.argv[2])>=1, sys.argv[2]; open(sys.argv[3],"w").write(s.replace(sys.argv[2],sys.argv[3+1],1))' src/blazer_gpu_tipc.c "$from" "$d/blazer_gpu_tipc.c" "$to" || { echo "BAD MUTANT $name"; return; }
  sed -i 's|#include "../src/blazer_gpu_tipc.c"|#include "blazer_gpu_tipc.c"|' tests/test_m2.c
  if build "$d" && "$OUT/t" >/dev/null 2>&1; then echo "SURVIVED $name"; else echo "caught $name"; fi
  sed -i 's|#include "blazer_gpu_tipc.c"|#include "../src/blazer_gpu_tipc.c"|' tests/test_m2.c
}
mutate health-waits-rtn 'gta_kccb(rgx, 0, (uint32_t)GF_CMD_HEALTH, false' 'gta_kccb(rgx, 0, (uint32_t)GF_CMD_HEALTH, true'
mutate pass-on-consume 'if (e == GTA_K_EXECUTED) {' 'if (e == GTA_K_EXECUTED || e == GTA_K_NOT_EXECUTED) {'
mutate second-after-unread 'if (h != GTA_K_UNREAD && h != GTA_K_BAD) {
		/* Never' 'if (1) {
		/* Never'
mutate no-log-type 'gs_w32(gsh.tbuf + HMFV2_TB_LOG_TYPE, GTA_LOG_M2);' ';'
mutate no-tb-size 'gs_w32(gsh.tbuf + HMFV2_TB_SIZE_DW, GTA_TB_DW);' ';'
mutate tb-cached-va 'gsh.tbdata = gs_ptr(gsh.tbuf + HMFV2_TB_BUFFER0, GTA_TB_DW * 4u);' 'gsh.tbdata = gs_ptr(gsh.tbuf + HMFV2_TB_BUFFER0, GTA_TB_DW * 4u); gs_w32(gsh.tbuf + HMFV2_TB_BUFFER0, GTA_VA_CACHED | gsh.tbdata);'
mutate log-on-rung5 'if (m2) {
		/* RGXSetupFwSysData' 'if (1) {
		/* RGXSetupFwSysData'
mutate wrong-stateflags 'GTA_CMD_STATEFLAGS ((uint32_t)HMFV2_CMD_STATEFLAGS)' 'GTA_CMD_STATEFLAGS ((uint32_t)HMFV2_CMD_STATEFLAGS + 1u)'
mutate no-fresh-check 'if (gs_r32(gsh.kctl + GF_CCB_W) != slot || gs_r32(gsh.kctl + GF_CCB_R) != slot) {' 'if (0) {'
mutate line-offset 'gs_r32(base + 2u * (uint32_t)HMFV2_ASSERT_BYTES)' 'gs_r32(base + 2u * (uint32_t)HMFV2_ASSERT_BYTES + 4u)'
mutate exec-wait-short 'end = t_read + (wait_rtn ? GTA_EXEC_MS : GTA_QUIET_MS);' 'end = t_read + GTA_QUIET_MS;'
mutate no-diag 'gta_diag_snapshot(when);' ';'
