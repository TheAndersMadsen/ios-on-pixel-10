#!/bin/sh
# HOST ONLY: pure-C sandbox result model under ASan/UBSan; no device access.
set -eu
A=research/ios26-jailbreak-r1
mkdir -p "$A/build/host" "$A/receipts"
${CC:-cc} -std=c11 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-sanitize-recover=all \
  -I"$A/src" "$A/tools/test_sandbox_check.c" -o "$A/build/host/test_sandbox_check"
"$A/build/host/test_sandbox_check" | tee "$A/receipts/test_sandbox_check.txt"
