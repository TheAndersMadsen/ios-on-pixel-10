#!/bin/sh
# Host test of sweet_sandbox_issue.h (ASan/UBSan) plus mutations that must each fail it.
set -e
H=$(cd "$(dirname "$0")/.." && pwd); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -g -I"$H/xnu-src" "$H/tests/test_sandbox_issue.c" -o "$T/t" && "$T/t"
for m in 's/#define SSI_OUT_WORD    4/#define SSI_OUT_WORD    5/' 's/if (args\[SSI_OUT_WORD\] == 0) {/if (0) {/' \
         's/ssi_token\[\] = "invalid"/ssi_token[] = "invalix"/' 's/ssi_token\[\] = "invalid"/ssi_token[] = "invalid\\0\\1"/'; do
  mkdir -p "$T/m/tests"; sed "$m" "$H/xnu-src/sweet_sandbox_issue.h" > "$T/m/sweet_sandbox_issue.h"; cp "$H/tests/test_sandbox_issue.c" "$T/m/tests/"
  cmp -s "$T/m/sweet_sandbox_issue.h" "$H/xnu-src/sweet_sandbox_issue.h" && { echo "MUTATION DID NOT APPLY: $m"; exit 1; }
  cc -std=c11 -w -fsanitize=address,undefined -I"$T/m" "$T/m/tests/test_sandbox_issue.c" -o "$T/m/t"
  if "$T/m/t" >/dev/null 2>&1; then echo "MUTATION SURVIVED: $m"; exit 1; else echo "killed: $m"; fi
done
echo PASS
