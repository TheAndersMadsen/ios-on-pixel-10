#!/bin/sh
# Mutation check for test_usbhost.c: each mutant must make the test fail. Run from this directory.
set -u
mkdir -p build/mut
SRC=../xnu-src/blazer_usbhost_core.inc
killed=0; total=0
mut() {
	total=$((total + 1))
	python3 -I - "$SRC" build/mut/blazer_usbhost_core.inc "$2" "$3" <<'PY'
import sys
s = open(sys.argv[1]).read(); a, b = sys.argv[3], sys.argv[4]
assert s.count(a) >= 1, a
open(sys.argv[2], 'w').write(s.replace(a, b, 1))
PY
	cp test_usbhost.c build/mut/
	if cc -std=c11 -w -fsanitize=address,undefined -Ibuild/mut build/mut/test_usbhost.c -o build/mut/t 2>/dev/null && ./build/mut/t >/dev/null 2>&1; then
		echo "SURVIVED $1"
	else
		echo "killed   $1"; killed=$((killed + 1))
	fi
}
mut event-cycle-no-toggle 'uh.evt_cycle ^= 1u;' ';'
mut cmd-cycle-no-toggle 'uh.cmd_cycle ^= 1u;' ';'
mut neutral-keeps-ped '((v) & (PORTSC_PP |' '((v) & (PORTSC_PED | PORTSC_PP |'
mut status-stage-in 'TRB_TYPE(TRB_STATUS) | TRB_IOC' 'TRB_TYPE(TRB_STATUS) | TRB_IOC | TRB_DIR_IN'
mut no-evaluate-context 'if (mps == 64) {' 'if (mps != 0) {'
mut power-usb3-too 'for (uint32_t i = 0; i < uh.u2_count; i++) {
			uint32_t port = uh.u2_first + i, v' 'for (uint32_t i = 0; i < uh.ports; i++) {
			uint32_t port = 1 + i, v'
mut reset-despite-no-halt 'if (!halted) {' 'if (0) {'
mut no-id-check 'if (id != UH_EXPECT_ID ||' 'if ('
mut no-scratchpad-array '*uh_m32(UA_DCBAA) = (uint32_t)uh_pa(UA_SCRATCH_ARRAY);' ';'
mut softreset-left-set 'uh_wr(UH_GCTL, uh_rd(UH_GCTL) & ~UH_GCTL_CORESOFTRESET);' ';'
mut no-event-buffer-retire 'uh_wr(UH_GEVNTADRLO, 0);' ';'
mut wrong-root-port '*uh_m32(ic + cs + 4) = port << 16;' '*uh_m32(ic + cs + 4) = (port + 1) << 16;'
echo "mutants: $killed/$total killed"
[ "$killed" -eq "$total" ]
