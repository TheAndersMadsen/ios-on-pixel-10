#!/bin/sh
# Host test of the modem core (ASan + UBSan), from the repository root. The core includes blazer_hw_port.h from the XNU mirror.
set -eu
R=$(cd "$(dirname "$0")/../../.." && pwd)
M=$R/research/ios26-modem-r1
X=$R/research/ios26-release-r1/work/xnu/bsd/dev
O=${TMPDIR:-/tmp}/hk-modem-test
mkdir -p "$O"
cc -std=c11 -Wall -Wextra -Werror -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=all -DBLAZER \
  -I"$M/src/bsd/dev" -I"$X" "$M/src/bsd/dev/blazer_modem_core.c" "$M/tests/test_modem_core.c" -o "$O/test_modem_core"
"$O/test_modem_core"
