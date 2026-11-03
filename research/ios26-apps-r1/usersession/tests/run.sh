#!/bin/sh
# Host test of the user-session core (ASan/UBSan) plus four mutations that must each fail it.
set -e
H=$(cd "$(dirname "$0")/.." && pwd); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -g -I"$H/xnu-src" "$H/tests/test_aks_usersession.c" -o "$T/t" && "$T/t"
for m in 's/if (bag_in\[i\] != want\[i\]) {/if (0) {/' 's/c->scalar_in\[0\] != AUS_USER_HANDLE/0/' \
         's/if (c->struct_out_cap < AUS_BAG_LEN) {/if (0) {/' 's/return sel == 2 || sel == 3/return sel == 10 || sel == 2 || sel == 3/'; do
  mkdir -p "$T/m/tests"; sed "$m" "$H/xnu-src/blazer_aks_usersession.inc" > "$T/m/blazer_aks_usersession.inc"; cp "$H/tests/test_aks_usersession.c" "$T/m/tests/"
  cc -std=c11 -w -fsanitize=address,undefined -I"$T/m" "$T/m/tests/test_aks_usersession.c" -o "$T/m/t"
  if "$T/m/t" >/dev/null 2>&1; then echo "MUTATION SURVIVED: $m"; exit 1; else echo "killed: $m"; fi
done
echo PASS
