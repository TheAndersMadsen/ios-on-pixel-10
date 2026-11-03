#!/bin/sh
# HOST: build and run the model test (ASan/UBSan), then mutants of blazer_nfc_hw.c that the test must catch.
#   sh research/ios26-nfc-r1/tests/run.sh [XNU_BSD_DEV_DIR]   (default: the m1box mirror of the release tree, for blazer_hw_port.h)
set -u
D=$(cd "$(dirname "$0")" && pwd); SRC=$D/../xnu-src/bsd/dev
PORT=${1:-$D/../../ios26-release-r1/work/xnu/bsd/dev}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CC=${CC:-cc}
build() { $CC -std=c11 -Wall -Wextra -Werror -Wno-unused-function -DBLAZER -fsanitize=address,undefined -g -I"$1" -I"$PORT" "$D/test_nfc_hw.c" -o "$2"; }
build "$SRC" "$T/t" || exit 1
"$T/t" | tail -1; "$T/t" >/dev/null || exit 1
caught=0; total=0
mutant() { # name, python replacement (old, new)
  total=$((total+1)); mkdir -p "$T/m$total"; cp "$SRC"/blazer_nfc_hw.h "$T/m$total/"
  python3 -I -c 'import sys; s=open(sys.argv[1]).read(); assert s.count(sys.argv[2])>=1, sys.argv[2]; open(sys.argv[3],"w").write(s.replace(sys.argv[2], sys.argv[4], 1))' \
    "$SRC/blazer_nfc_hw.c" "$2" "$T/m$total/blazer_nfc_hw.c" "$3" || { echo "mutant $1: pattern missing"; exit 1; }
  if build "$T/m$total" "$T/m$total/t" 2>/dev/null && ASAN_OPTIONS=detect_leaks=0 "$T/m$total/t" >/dev/null 2>&1; then echo "MUTANT SURVIVED: $1"; else caught=$((caught+1)); fi
}
mutant no-restore      'if (!n->en_driven || n->cfg.keep == 1) {' 'if (1) {'
mutant no-off-time     '#define EN_OFF_US       30000u' '#define EN_OFF_US       0u'
mutant no-bus-down     'n->stop = NF_OK;
	(void)wr(n, I2C + IC_ENABLE, 0);' 'n->stop = NF_OK; return;
	(void)wr(n, I2C + IC_ENABLE, 0);'
mutant no-bus-exit     'n->ops.bus_exit(n->ops.ctx);' ';'
mutant fw-offset       '(uint32_t)b[10] << 24' '(uint32_t)b[9] << 24'
mutant no-idle-shift   'skip = h[1] != NCI_IDLE ? 1 : h[2] != NCI_IDLE ? 2 : 3;' 'skip = 3;'
mutant read-no-stop    'CMD_READ | (pushed + 1 == count ? CMD_STOP : 0)' 'CMD_READ'
mutant write-allow-all 'if (write) {
		return false;' 'if (write) {
		return true;'
mutant stage-gate      'if (c >= C_COUNT || n->cfg.stage < cmds[c].stage) {' 'if (c >= C_COUNT) {'
mutant loader-ignored  'return halt(n, NF_STOP_LOADER, b[3]);' 'return 0;'
mutant rsp-any         'if (mt(n) == MT_RSP && gid(n) == (cmds[c].b[0] & 0x0fu) && oid(n) == (cmds[c].b[1] & 0x3fu)) {' 'if (mt(n) == MT_RSP) {'
mutant no-rf-off       'if (!n->rf_on || !n->bus_on) {' 'if (1) {'
mutant foreign-mux     'if (n->en_dmux != 0) {' 'if (0) {'
mutant no-abort-clear  'rd(n, I2C + IC_CLR_TX_ABRT, &junk) || rd(n, I2C + IC_CLR_STOP, &junk)) {
				return (int)n->stop;
			}
			return -1;' 'rd(n, I2C + IC_CLR_STOP, &junk)) {
				return (int)n->stop;
			}
			return -1;'
mutant nfca-uid-len    'n->uid_len = p[2];' 'n->uid_len = 4;'
echo "mutants: $caught/$total caught"
[ "$caught" = "$total" ]
