#!/bin/bash
# SPDX-License-Identifier: MIT
# All S1 host gates, from research/ios26-gpu-r1: S1 test (sanitizers, optional gpu2 replay), order check, S1 mutants, M2's test and mutants
# against the S1 source (rung 6 behaviour unchanged), M1 survey regression, decoder on the clean model's log. $1: scratch dir, $2: gpu2 reader.txt.
set -uo pipefail
T=${1:?scratch}; R=${2:-}; mkdir -p "$T"
echo "# $(date -Iseconds) $(hostname) $(cc --version | head -1)"
CF="-std=gnu11 -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=undefined"
echo "cc $CF -Wall -Wextra -Is1/tests/inc -Is1/src s1/tests/test_s1.c"
cc $CF -Wall -Wextra -Wno-unused-function -Wno-unused-parameter -Wno-sign-compare -Wno-unused-const-variable -Is1/tests/inc -Is1/src s1/tests/test_s1.c -o "$T/t_s1" 2>&1 | grep -v '^s1/tests/inc' | grep -E 'warning|error' || true
S1_GPU2_READER="$R" S1_LOGFILE="$T/clean.log" "$T/t_s1"; echo "rc=$?"
python3 -I s1/tests/order_check.py s1/src/blazer_gpu_tipc.c
echo "s1/tests/mutants_s1.sh"
( cd s1 && bash tests/mutants_s1.sh "$T/mut" "$R" )
echo "M2 test against the S1 source (rung 6 path: gta_m2(rgx, false)):"
mkdir -p "$T/m2s1"; sed -e 's|#include "../src/blazer_gpu_tipc.c"|#include "blazer_gpu_tipc.c"|' -e 's|gta_m2(0x1000)|gta_m2(0x1000, false)|g' m2/tests/test_m2.c > "$T/m2s1/test_m2.c"
cc $CF -w -Im2/tests -Im2/tests/inc -Is1/src "$T/m2s1/test_m2.c" -o "$T/t_m2s1" && "$T/t_m2s1"; echo "rc=$?"
echo "M2 test and mutants against m2/src (unchanged):"
cc $CF -w -Im2/tests/inc -Im2/src m2/tests/test_m2.c -o "$T/t_m2" && "$T/t_m2"; echo "rc=$?"
( cd m2 && cp -r . "$T/m2copy" && cd "$T/m2copy" && bash tests/mutants_m2.sh "$T/m2mut" ) | sort | uniq -c
echo "M1 regression: cc ... -Itests m2/src/blazer_gpu.c tests/test_survey.c"
cc -std=gnu11 -w -fsanitize=address,undefined -g -DBLAZER=1 -DBLAZER_GPU_HOSTTEST=1 -DBLAZER_GPU_HOSTTEST_BUS=1 -Itests m2/src/blazer_gpu.c tests/test_survey.c -o "$T/t_m1" && "$T/t_m1"; echo "rc=$?"
V=${SF_H:-/data/hackios-gpu-ref/powervr/pvrsrvkm/include/rgx_fwif_sf.h}
echo "fwlog_decode on the CLEAN model's log:"
python3 -I m2/tools/fwlog_decode.py "$T/clean.log" "$V"
echo "s1/tests/test_s1_accept.py (host acceptance tool, gpu2 phone log relabelled + synthetic clean and corruptions):"
[ -n "$R" ] && python3 -I s1/tests/test_s1_accept.py "$R" "$V"; echo "rc=$?"
