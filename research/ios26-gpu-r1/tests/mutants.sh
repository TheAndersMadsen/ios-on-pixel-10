#!/bin/sh
# Host-only mutation check for tests/test_survey.c. Usage: tests/mutants.sh <build-dir>
set -u
B=$1; cd "$(dirname "$0")/.."
run() { name=$1; shift
  sed "$@" src/blazer_gpu.c > "$B/mutant.c"
  if cc -std=gnu11 -w -fsanitize=address,undefined -DBLAZER=1 -DBLAZER_GPU_HOSTTEST=1 -DBLAZER_GPU_HOSTTEST_BUS=1 -Itests -iquote src \
      "$B/mutant.c" tests/test_survey.c -o "$B/mutant" 2>/dev/null && "$B/mutant" >/dev/null 2>&1; then
    echo "SURVIVED $name"; survived=$((survived+1))
  else echo "caught $name"; fi
  total=$((total+1)); }
survived=0 total=0
run extra-offset      -e 's/{ 0xe240, 0, "SLC_FAULT_STOP_STATUS" },/&\n\t{ 0xe300, 0, "EXTRA" },/'
run rgx-write         -e 's/printf("blazer-gpu: survey done/gpu_w32(rgx + 0x130, 0); &/'
run survey-in-mode1   -e 's/gpu_mode == 3 \&\& first/gpu_mode >= 1 \&\& first/'
run no-id-guard       -e 's/gpu_mode == 3 \&\& first == CORE_ID_EXPECT \&\& second == first/gpu_mode == 3/'
run survey-after-off  -e 's/^\t\t\tgpu_survey();$//' -e 's/printf("blazer-gpu: core logic off, control 0x%x\\n", seen);/gpu_survey(); &/'
run timer-no-retry    -e 's/n < 3; n++/n < 1; n++/'
run timer-unbounded   -e 's/n < 3; n++/n < 9; n++/'
run stopped-as-runs   -e 's/t1 > t0 ? "CLOCK_RUNS"/t1 >= t0 ? "CLOCK_RUNS"/'
run no-delay          -e 's/delay(GPU_TIMER_GAP_US);//'
run wrong-width       -e 's/{ 0xe150, 1, "MMU_FAULT_STATUS1" }/{ 0xe150, 0, "MMU_FAULT_STATUS1" }/'
run unstable-continues -e '0,/printf("blazer-gpu: TIMER UNSTABLE high word\\n");/{n;s/return;//}'
echo "mutants: $((total-survived))/$total caught"
[ "$survived" -eq 0 ]
