#!/bin/sh
# Mac only (repo root). hk_scwait: host run on macOS (HK_SCWAIT_TEST, stderr), gate-off run, then the device dylib with
# perf/tools/build_mainwatch.sh's steps (arm64e, iphoneos SDK, min 26.0, pacstrip --sign, codesign --verify --strict).
# Writes only research/ios26-phaseb-r1/configd/{out,receipts/scwait}. HOST ONLY: boots nothing.
set -eu
C=research/ios26-phaseb-r1/configd; OUT=$C/out; R=$C/receipts/scwait
mkdir -p $OUT $R
FW="-framework CoreFoundation -framework SystemConfiguration"
xcrun clang -arch arm64 -O1 -g -Wall -Wextra -Werror -DHK_SCWAIT_TEST -dynamiclib $C/src/hk_scwait.c $FW -o $OUT/hk_scwait_test.dylib
xcrun clang -arch arm64 -O1 -Wall -Wextra -Werror $C/tests/host_scwait.c -o $OUT/host_scwait
$OUT/host_scwait $OUT/hk_scwait_test.dylib > $R/host-run.txt 2>&1; cat $R/host-run.txt
$OUT/host_scwait $OUT/hk_scwait_test.dylib off > $R/host-off.txt 2>&1; cat $R/host-off.txt
grep -q 'HKSC: SCNetworkInterfaceCopyAll returned' $R/host-run.txt && grep -q 'keys=' $R/host-run.txt && ! grep -q HKSC $R/host-off.txt && echo PASS | tee $R/host-check.txt
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
IOS="xcrun clang -arch arm64e -isysroot $SDK -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror"
$IOS -c $C/src/hk_scwait.c -o $OUT/hk_scwait.arm64e.o
$IOS -dynamiclib $C/src/hk_scwait.c $FW -install_name /private/var/hk/hk_scwait.dylib -o $OUT/hk_scwait.raw.dylib
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --sign -o $OUT/hk_scwait.dylib $OUT/hk_scwait.raw.dylib > $R/pacstrip.txt 2>&1
codesign --verify --strict $OUT/hk_scwait.dylib > $R/codesign-verify.txt 2>&1
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --scan $OUT/hk_scwait.dylib > $R/pac-scan.txt 2>&1
file $OUT/hk_scwait.arm64e.o $OUT/hk_scwait.dylib > $R/file.txt
xcrun otool -L $OUT/hk_scwait.dylib > $R/otool-L.txt
xcrun nm -u $OUT/hk_scwait.dylib > $R/nm-undefined.txt
cat $R/file.txt $R/otool-L.txt $R/codesign-verify.txt $R/pac-scan.txt
shasum -a 256 $C/src/hk_scwait.c $C/tests/host_scwait.c $OUT/hk_scwait.arm64e.o $OUT/hk_scwait.raw.dylib $OUT/hk_scwait.dylib | tee $R/SHA256SUMS
