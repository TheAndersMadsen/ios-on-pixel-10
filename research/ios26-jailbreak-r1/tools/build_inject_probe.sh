#!/bin/sh
# Mac only, repo root. HOST ONLY: build/test the reusable injection probe; never boots or accesses a device.
set -eu
A=research/ios26-jailbreak-r1
OUT=$A/out
R=$A/receipts/inject_probe
mkdir -p "$OUT" "$R"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

# Host gate/load test with a temporary console. macOS's own sandbox results are not the guest assertions.
xcrun clang -arch arm64 -O1 -Wall -Wextra -Werror -DHK_CONSOLE_PATH="\"$T/console\"" \
  -dynamiclib "$A/src/hk_inject_probe.c" -o "$T/probe.dylib"
xcrun clang -arch arm64 -O1 -Wall -Wextra -Werror "$A/tests/probe_driver.c" -o "$T/driver"
: > "$T/console"
DYLD_INSERT_LIBRARIES="$T/probe.dylib" "$T/driver"
DYLD_INSERT_LIBRARIES="$T/probe.dylib" HK_INJECT_PROBE=0 "$T/driver"
OFF=$(wc -c < "$T/console" | tr -d ' ')
DYLD_INSERT_LIBRARIES="$T/probe.dylib" HK_INJECT_PROBE=1 "$T/driver"
{
  echo "gate off/0 console bytes: $OFF (want 0)"
  test "$OFF" = 0 && echo "PASS off"
  sed 's/^/  /' "$T/console"
  test "$(grep -c '^HKINJECT: driver\[[0-9][0-9]*\] loaded self=-\?[0-9][0-9]* operation=-\?[0-9][0-9]*$' "$T/console")" = 1 \
    && echo "PASS load and direct-console receipt"
} | tee "$R/host-test.txt"

# Device/Guest probe: arm64e, iOS 26, no PAC, ad-hoc signed like the established app2 dylib.
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun clang -arch arm64e -isysroot "$SDK" -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror \
  -dynamiclib "$A/src/hk_inject_probe.c" -install_name /private/var/hk/hk_inject_probe.dylib \
  -o "$OUT/hk_inject_probe.raw.dylib"
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --sign \
  -o "$OUT/hk_inject_probe.dylib" "$OUT/hk_inject_probe.raw.dylib" > "$R/pacstrip.txt" 2>&1
codesign --verify --strict "$OUT/hk_inject_probe.dylib" > "$R/codesign-verify.txt" 2>&1
echo "codesign verify OK" >> "$R/codesign-verify.txt"
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --scan "$OUT/hk_inject_probe.dylib" > "$R/pac-scan.txt" 2>&1
file "$OUT/hk_inject_probe.dylib" > "$R/file.txt"
xcrun otool -L "$OUT/hk_inject_probe.dylib" > "$R/otool-L.txt"
xcrun vtool -show-build "$OUT/hk_inject_probe.dylib" > "$R/build-version.txt"
xcrun nm -u "$OUT/hk_inject_probe.dylib" > "$R/nm-undefined.txt"
cat "$R/file.txt" "$R/otool-L.txt" "$R/nm-undefined.txt" "$R/codesign-verify.txt" "$R/pac-scan.txt"
shasum -a 256 "$A/src/hk_inject_probe.c" "$A/tests/probe_driver.c" \
  "$OUT/hk_inject_probe.raw.dylib" "$OUT/hk_inject_probe.dylib" | tee "$R/SHA256SUMS"
