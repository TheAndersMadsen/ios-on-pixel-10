#!/bin/sh
# Mac only (repo root). hk_flatmat: host test (macOS arm64, -DHK_FLATMAT_TEST, fake MTMaterialLayer on the real
# CABackdropLayer/CAFilter), then the deployable dylib with perf/tools/build_mainwatch.sh's steps: xcrun clang -arch
# arm64e (iphoneos SDK, min 26.0) -dynamiclib, renegade pacstrip.py --sign, codesign --verify --strict, receipts.
# Writes only research/ios26-phaseb-r1/cc/{out,receipts}. HOST ONLY: boots nothing.
set -eu
P=research/ios26-phaseb-r1/cc; OUT=$P/out; R=$P/receipts/flatmat
mkdir -p $OUT $R
# 1. host test (CGColorCreateGenericGray stands in for UIColor; AppKit is not linked because it loads macOS's own
#    CoreMaterial, whose real MTMaterialLayer would replace the fake one)
xcrun clang -arch arm64 -O1 -g -Wall -Wextra -Werror -DHK_FLATMAT_TEST -dynamiclib $P/src/hk_flatmat.c -lobjc -framework CoreGraphics -o $OUT/hk_flatmat_test.dylib
xcrun clang -arch arm64 -O1 -g -Wall -Wextra -Werror -fobjc-arc -framework Foundation -framework QuartzCore -framework CoreGraphics $P/tests/test_flatmat.m -o $OUT/test_flatmat
$OUT/test_flatmat $OUT/hk_flatmat_test.dylib off > $R/host-off.txt 2>&1 || true
cat $R/host-off.txt
grep -q '^OFF imp-unchanged 1$' $R/host-off.txt && ! grep -q HKFLAT $R/host-off.txt && echo 'PASS gate off: silent, IMPs untouched' | tee -a $R/host-off.txt
$OUT/test_flatmat $OUT/hk_flatmat_test.dylib > $R/host-run.txt 2>&1 || true
cat $R/host-run.txt
grep -q '^RESULT PASS' $R/host-run.txt
# 2. device dylib
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
IOS="xcrun clang -arch arm64e -isysroot $SDK -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror"
$IOS -c $P/src/hk_flatmat.c -o $OUT/hk_flatmat.arm64e.o
$IOS -dynamiclib $P/src/hk_flatmat.c -install_name /private/var/hk/hk_flatmat.dylib -lobjc -o $OUT/hk_flatmat.raw.dylib
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --sign -o $OUT/hk_flatmat.dylib $OUT/hk_flatmat.raw.dylib > $R/pacstrip.txt 2>&1
codesign --verify --strict $OUT/hk_flatmat.dylib > $R/codesign-verify.txt 2>&1
codesign -d --verbose=4 $OUT/hk_flatmat.dylib > $R/codesign-details.txt 2>&1
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --scan $OUT/hk_flatmat.dylib > $R/pac-scan.txt 2>&1
file $OUT/hk_flatmat.arm64e.o $OUT/hk_flatmat.raw.dylib $OUT/hk_flatmat.dylib > $R/file.txt
xcrun otool -L $OUT/hk_flatmat.dylib > $R/otool-L.txt
xcrun vtool -show-build $OUT/hk_flatmat.dylib > $R/build-version.txt
xcrun nm -m $OUT/hk_flatmat.dylib > $R/nm-m.txt
xcrun nm -u $OUT/hk_flatmat.dylib > $R/nm-undefined.txt
xcrun otool -tvV $OUT/hk_flatmat.dylib > $R/disassembly.txt
xcrun clang --version > $R/clang-version.txt
echo "$SDK" > $R/sdk.txt
cat $R/file.txt $R/otool-L.txt $R/build-version.txt $R/codesign-verify.txt $R/pac-scan.txt $R/nm-undefined.txt
shasum -a 256 $P/src/hk_flatmat.c $P/tests/test_flatmat.m $OUT/hk_flatmat.arm64e.o $OUT/hk_flatmat.raw.dylib $OUT/hk_flatmat.dylib $OUT/hk_flatmat_test.dylib | tee $R/SHA256SUMS
