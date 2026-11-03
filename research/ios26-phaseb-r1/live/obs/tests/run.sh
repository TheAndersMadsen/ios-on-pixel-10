#!/bin/sh
# HOST: every hk-obs1 host test, then mutants that each test must catch. Linux (m1box) or macOS. Exit 1 on any failure.
# Run from the repository root:  sh research/ios26-phaseb-r1/live/obs/tests/run.sh
set -u
O=research/ios26-phaseb-r1/live/obs; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CC=${CC:-cc}; SAN="-fsanitize=address,undefined -fno-sanitize-recover=all"
F=0
step() { echo "== $1"; }
res() { if [ "$1" = 0 ]; then echo "PASS $2"; else echo "FAIL $2"; F=1; fi; }
step "kernel headers (hk_env_merge.h, hk_obs.h)"
$CC -std=c11 -Wall -Wextra -Werror $SAN -I $O/xnu-src/bsd/kern $O/tests/test_hk_obs.c -o $T/t && $T/t; res $? test_hk_obs
step "logmirror line format"
$CC -std=c11 -Wall -Wextra -Werror $SAN -I $O/src $O/tests/test_logmirror_fmt.c -o $T/f && $T/f; res $? test_logmirror_fmt
step "logmirror injected into a program"
sh $O/tests/run_logmirror.sh; res $? run_logmirror
step "env per program, from the obs1-r1 overlay's hk_env"
python3 -I - $O/overlays/obs1-r1.ovl > $T/rules <<'PY'
import importlib.util, sys
sys.dont_write_bytecode = True
s = importlib.util.spec_from_file_location('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
r = m.decode(open(sys.argv[1], 'rb').read()); sys.stdout.write(r[39][6].decode())
PY
$CC -std=c11 -Wall -Wextra -Werror $SAN -I $O/xnu-src/bsd/kern $O/tests/env_per_program.c -o $T/e && $T/e $T/rules Preferences SpringBoard configd backboardd > $T/env.txt
grep -q 'DYLD_INSERT_LIBRARIES=/private/var/hk/hkart.dylib:/private/var/hk/hk_mainwatch.dylib:/private/var/hk/hk_logmirror.dylib' $T/env.txt &&
grep -q 'DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib:/private/var/hk/hk_logmirror.dylib' $T/env.txt &&
grep -A4 '^backboardd:' $T/env.txt | grep -q 'mirrored no'; res $? env_per_program
step "tools/hklog.py"
python3 -I tools/test_hklog.py 2>&1 | tail -3; res $? test_hklog
step "mutants (each must FAIL test_hk_obs)"
mut() { # name file sed-expression
  mkdir -p $T/m/kern; cp $O/xnu-src/bsd/kern/*.h $T/m/kern/
  sed -i.bak "$3" $T/m/kern/$2 && ! cmp -s $T/m/kern/$2 $T/m/kern/$2.bak || { echo "MUTANT $1 did not apply"; F=1; return; }
  if $CC -std=c11 -w $SAN -I $T/m/kern $O/tests/test_hk_obs.c -o $T/mt 2>/dev/null && $T/mt > /dev/null 2>&1; then echo "MUTANT SURVIVED $1"; F=1; else echo "caught $1"; fi; }
mut first-rule-wins hk_env_merge.h 's/if (\*ndyld > 1) {/if (0) {/'
mut no-dedup hk_env_merge.h 's/if (plen == 0 || hk_env_has_path(.*)) {/if (plen == 0) {/'
mut dyld-twice hk_env_merge.h 's/if (dyld_done) {/if (0) {/'
mut cut-library hk_env_merge.h 's/lost++;/lost++; out[(*olen)++] = val[w]; out[*olen] = 0;/'
mut no-mirror-flag hk_env_merge.h 's/\*mirror = 1;/;/'
mut bucket-no-refill hk_obs.h 's/uint64_t add = (now_us - b->last_us) \* (uint64_t)b->rate \/ 1000000u;/uint64_t add = 0;/'
mut bucket-past-burst hk_obs.h 's/if (t >= b->burst) {/if (0) {/'
mut prefix-match hk_obs.h 's/return a\[blen\] == .\\0.;/return 1;/'
mut status-signal hk_obs.h 's/(xstat \& 0x7fu) != 0x7fu/1/'
mut line-overrun hk_obs.h 's/if (l->len + 1 >= l->cap) {/if (l->len >= l->cap) {/'
mut table-overflow hk_obs.h 's/t->n >= HK_OBS_SLOTS/t->n > HK_OBS_SLOTS/'
echo
[ $F = 0 ] && echo "ALL PASS" || echo "FAILURES"
exit $F
