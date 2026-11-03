#!/bin/sh
# Host tests for the touch fix. XNU = a checkout of the release tree at the branch under test (hk-touch-direct);
# default: the m1box mirror. Builds with the host clang; no kernel, no device.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
XNU=${1:-$here/../../../ios26-release-r1/work/xnu}
out=${TMPDIR:-/tmp}/hk-touch-test.$$
mkdir -p "$out"
trap 'rm -rf "$out"' EXIT
CC=${CC:-clang}
CXX=${CXX:-clang++}
"$CXX" -std=c++17 -Wall -Wextra -Werror -I"$here/shim" -I"$XNU/iokit/Kernel/arm/hid" \
	"$here/test_touch_shape.cpp" -o "$out/shape"
"$CC" -std=c11 -Wall -Wextra -DBLAZER -I"$XNU/bsd/dev" \
	"$here/test_tcm_decode.c" "$XNU/bsd/dev/blazer_tcm.c" -o "$out/tcm"
"$out/shape"
"$out/tcm"
