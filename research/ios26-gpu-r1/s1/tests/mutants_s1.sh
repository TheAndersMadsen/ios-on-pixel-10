#!/bin/bash
# SPDX-License-Identifier: MIT
# Each mutant of src/blazer_gpu_tipc.c must make tests/test_s1.c (or the order check) fail. Run from research/ios26-gpu-r1/s1. $1: scratch dir.
# $2 (optional): gpu2 reader.txt for the replay fixture.
set -u
OUT=${1:?scratch dir}; mkdir -p "$OUT"; R=${2:-}
build() { cc -std=gnu11 -w -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=undefined -Itests/inc -I"$1" -DS1_SRC="\"$1/blazer_gpu_tipc.c\"" tests/test_s1.c -o "$OUT/t" 2>"$OUT/cc.err"; }
mutate() {
  local name=$1 from=$2 to=$3 d="$OUT/m"; rm -rf "$d"; mkdir -p "$d"; cp src/hmfw_m2_layout.h src/hmfw_s1_layout.h "$d/"
  python3 -I -c '
import sys; s=open(sys.argv[1]).read(); a=sys.argv[3:]
for f,t in zip(a[0::2],a[1::2]):
    assert s.count(f)>=1, f; s=s.replace(f,t,1)
open(sys.argv[2],"w").write(s)' src/blazer_gpu_tipc.c "$d/blazer_gpu_tipc.c" "$from" "$to" "${@:4}" || { echo "BAD MUTANT $name"; return; }
  sed 's|#include "../src/blazer_gpu_tipc.c"|#include S1_SRC|' tests/test_s1.c > "$OUT/test_s1.c"
  if cc -std=gnu11 -w -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=undefined -Itests/inc -I"$d" -DS1_SRC="\"$d/blazer_gpu_tipc.c\"" "$OUT/test_s1.c" -o "$OUT/t" 2>"$OUT/cc.err" \
     && S1_GPU2_READER="$R" "$OUT/t" >/dev/null 2>&1 && python3 -I tests/order_check.py "$d/blazer_gpu_tipc.c" >/dev/null 2>&1; then echo "SURVIVED $name"; else echo "caught $name"; fi
}
cp tests/inc/* "$OUT/" 2>/dev/null; mkdir -p "$OUT/inc"; cp tests/inc/* "$OUT/inc/"
mutate no-coremem-write 'gs_w64(si + GTA_S1_SI_COREMEM, GTA_S1_COREMEM_VA);' ';'
mutate fwva-not-devva '#define GTA_S1_COREMEM_VA  (GTA_S1_RAW_BASE + GTA_OFF_CDATA)' '#define GTA_S1_COREMEM_VA  ((uint64_t)GTA_FWVA_HEAP + GTA_OFF_CDATA)'
mutate pa-not-devva '#define GTA_S1_COREMEM_VA  (GTA_S1_RAW_BASE + GTA_OFF_CDATA)' '#define GTA_S1_COREMEM_VA  (GTA_CARVEOUT_PA + GTA_OFF_CDATA)'
mutate lo-only 'gs_w64(si + GTA_S1_SI_COREMEM, GTA_S1_COREMEM_VA);' 'gs_w32(si + GTA_S1_SI_COREMEM, (uint32_t)GTA_S1_COREMEM_VA);'
mutate wrong-offset '#define GTA_S1_SI_COREMEM  ((uint32_t)HMFS1_SI_COREMEM_DATA_STORE)' '#define GTA_S1_SI_COREMEM  ((uint32_t)HMFS1_SI_COREMEM_DATA_STORE + 8u)'
mutate coremem-on-rung8 'gta_s1_coremem = on == 7;' 'gta_s1_coremem = on >= 7;'
mutate store-after-barrier '	if (gta_s1_coremem) {
		/* RGXSetupFwSysData' '	if (0) {
		/* RGXSetupFwSysData'
mutate readback-ignored '	if (((uint64_t)hi << 32 | lo) != want) {' '	if (0) {'
mutate readback-after-power '	if (rung >= 7 && gta_s1_coremem_check(rung)) {
		return GTA_STOPPED;
	}
	if (gta_power_on(&rgx) != 0) {
		aoc_stop("GPU did not power on");
		return GTA_STOPPED;
	}' '	if (gta_power_on(&rgx) != 0) {
		aoc_stop("GPU did not power on");
		return GTA_STOPPED;
	}
	if (rung >= 7 && gta_s1_coremem_check(rung)) {
		return GTA_STOPPED;
	}'
mutate no-boot-gate 'if (s1 && !gta_s1_gate("boot")) {' 'if (0) {'
mutate final-ignored '		if (clean) {
			AOC_LOG("M3 S1 PASS' '		if (1) {
			AOC_LOG("M3 S1 PASS'
mutate mmu-not-counted 'case (uint32_t)HMFS1_SF_MMU_FAULT_EVENT: case (uint32_t)HMFS1_SF_CORE_MMU_FAULT: case (uint32_t)HMFS1_SF_CORE_MMU_FAULT_S7:
			c->mmu++;' 'case (uint32_t)HMFS1_SF_MMU_FAULT_EVENT: case (uint32_t)HMFS1_SF_CORE_MMU_FAULT_S7:
			c->mmu++;'
mutate lockup-not-gated 'c.mmu == 0 && c.lockup == 0 &&' 'c.mmu == 0 &&'
mutate poll-not-gated 'c.poll == 0 && c.reset == 0' 'c.reset == 0'
mutate resync-on-bad-id "		if ((id & (uint32_t)HMFS1_SF_IDMASK) != (uint32_t)HMFS1_SF_IDMARKER || i + 3u + n > p) {
			c->words = i;
			return false;
		}" "		if ((id & (uint32_t)HMFS1_SF_IDMASK) != (uint32_t)HMFS1_SF_IDMARKER) { i++; continue; }
		if (i + 3u + n > p) {
			c->words = i;
			return false;
		}"
mutate truncation-accepted '|| i + 3u + n > p) {' ') {'
mutate wrap-accepted 'gs_r32(tb + HMFV2_TB_BUFFER0) != (GTA_VA_UNCACHED | gsh.tbdata) || gs_r32(tb + HMFV2_TB_WRAP0) != 0) {' 'gs_r32(tb + HMFV2_TB_BUFFER0) != (GTA_VA_UNCACHED | gsh.tbdata)) {' \
  'c->valid = gs_r32(tb + HMFV2_TB_WRAP0) == 0 && ' 'c->valid = '
mutate reset-not-counted '		case (uint32_t)HMFS1_SF_START_HW_RESET:
			c->reset++;' '		case (uint32_t)HMFS1_SF_START_HW_RESET:'
mutate lockup-dm-not-counted 'case (uint32_t)HMFS1_SF_HIT_LOCKUP: case (uint32_t)HMFS1_SF_HIT_LOCKUP_DM:' 'case (uint32_t)HMFS1_SF_HIT_LOCKUP:'
mutate empty-accepted '	if (p == 0 || p > GTA_TB_DW) {' '	if (p > GTA_TB_DW) {'
mutate no-settle '			return false;   /* still logging' '			break;   /* still logging'
mutate invalid-not-fail 'return c.valid && c.mmu == 0' 'return c.mmu == 0'
mutate assert-ignored '&& assert_empty && hwr_ok' '&& hwr_ok'
mutate fwfault-ignored 'dumps == 0 && faults == 0 &&' 'dumps == 0 &&'
mutate hwr-ignored '&& assert_empty && hwr_ok &&' '&& assert_empty &&'
mutate dump-ignored 'dumps == 0 && faults == 0' 'faults == 0'
mutate pf-ignored '|| type == (uint32_t)HMFS1_FWCCB_FW_PF) {' ') {'
mutate s1-off-rung7 'rc = gta_m2(rgx, rung >= 7);' 'rc = gta_m2(rgx, rung >= 8);'
mutate trace-off-rung7 'if (gta_shared_init(rung >= 6)) {' 'if (gta_shared_init(rung == 6)) {'
mutate rung7-refused 'on < 1 || on > 8) {' 'on < 1 || on > 6) {'
