#!/bin/sh
# Mac only. Deployable hk_accel_once.dylib, same steps as boot_services/tools/validate.py (hk_container_ready):
# xcrun clang -arch arm64e (iphoneos SDK, min 26.0) -dynamiclib, renegade pacstrip.py --sign, codesign --verify --strict.
# Writes only build-mac/. Not wired into any image.
set -eu
cd "$(dirname "$0")"
REPO=$(cd ../../../.. && pwd)
SRC=../src
OUT=out
mkdir -p "$OUT" receipts
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
IOS="xcrun clang -arch arm64e -isysroot $SDK -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror -I$SRC"
$IOS -c $SRC/hk_accel_once.c -o $OUT/hk_accel_once.arm64e.o
$IOS -dynamiclib $SRC/hk_accel_once.c -install_name /private/var/hk/hk_accel_once.dylib -o $OUT/hk_accel_once.raw.dylib
python3 -I "$REPO/research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py" --sign -o $OUT/hk_accel_once.dylib $OUT/hk_accel_once.raw.dylib > receipts/pacstrip.txt 2>&1
codesign --verify --strict $OUT/hk_accel_once.dylib > receipts/codesign-verify.txt 2>&1
codesign -d --verbose=4 $OUT/hk_accel_once.dylib > receipts/codesign-details.txt 2>&1
python3 -I "$REPO/research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py" --scan $OUT/hk_accel_once.dylib > receipts/pac-scan.txt 2>&1
file $OUT/hk_accel_once.arm64e.o $OUT/hk_accel_once.raw.dylib $OUT/hk_accel_once.dylib > receipts/file.txt
xcrun otool -hv $OUT/hk_accel_once.dylib > receipts/header.txt
xcrun otool -L $OUT/hk_accel_once.dylib > receipts/otool-L.txt
xcrun otool -l $OUT/hk_accel_once.dylib > receipts/load-commands.txt
xcrun vtool -show-build $OUT/hk_accel_once.dylib > receipts/build-version.txt
xcrun nm -m $OUT/hk_accel_once.dylib > receipts/nm-m.txt
xcrun nm -gU $OUT/hk_accel_once.dylib > receipts/nm-exported.txt
xcrun nm -u $OUT/hk_accel_once.dylib > receipts/nm-undefined.txt
xcrun otool -tvV $OUT/hk_accel_once.dylib > receipts/disassembly.txt
xcrun clang --version > receipts/clang-version.txt
echo "$SDK" > receipts/sdk.txt
shasum -a 256 $SRC/hk_accel_once.c $SRC/hka_decide.h $OUT/* > receipts/SHA256SUMS
cat receipts/SHA256SUMS
