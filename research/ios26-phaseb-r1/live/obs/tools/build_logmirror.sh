#!/bin/sh
# Mac only (repo root). hk_logmirror: host test on macOS (tests/run_logmirror.sh: real os_log under OS_ACTIVITY_DT_MODE,
# SIGPIPE safety, budget, flood), then the device dylib (arm64e, iphoneos SDK, min 26.0, renegade pacstrip.py --sign,
# codesign --verify --strict), as app2/tools/build_stderr_console.sh.
set -eu
O=research/ios26-phaseb-r1/live/obs; OUT=$O/build; R=$O/receipts/logmirror
mkdir -p $OUT $R
sh $O/tests/run_logmirror.sh > $R/host-test-macos.txt 2>&1 || { cat $R/host-test-macos.txt; exit 1; }
cat $R/host-test-macos.txt
xcrun clang -arch arm64 -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I $O/src $O/tests/test_logmirror_fmt.c -o /tmp/hkm_fmt_t
/tmp/hkm_fmt_t | tee $R/fmt-test-macos.txt
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
IOS="xcrun clang -arch arm64e -isysroot $SDK -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror"
$IOS -dynamiclib -I $O/src $O/src/hk_logmirror.c -install_name /private/var/hk/hk_logmirror.dylib -o $OUT/hk_logmirror.raw.dylib
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --sign -o $OUT/hk_logmirror.dylib $OUT/hk_logmirror.raw.dylib > $R/pacstrip.txt 2>&1
codesign --verify --strict $OUT/hk_logmirror.dylib > $R/codesign-verify.txt 2>&1 && echo "codesign verify OK" >> $R/codesign-verify.txt
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --scan $OUT/hk_logmirror.dylib > $R/pac-scan.txt 2>&1
file $OUT/hk_logmirror.dylib > $R/file.txt
xcrun otool -L $OUT/hk_logmirror.dylib > $R/otool-L.txt
xcrun vtool -show-build $OUT/hk_logmirror.dylib > $R/build-version.txt
xcrun nm -u $OUT/hk_logmirror.dylib > $R/nm-undefined.txt
cat $R/file.txt $R/otool-L.txt $R/nm-undefined.txt $R/codesign-verify.txt $R/pac-scan.txt $R/build-version.txt
shasum -a 256 $O/src/hk_logmirror.c $O/src/hk_logmirror_fmt.h $OUT/hk_logmirror.raw.dylib $OUT/hk_logmirror.dylib | tee $R/SHA256SUMS
