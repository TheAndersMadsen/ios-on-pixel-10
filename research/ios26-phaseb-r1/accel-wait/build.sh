#!/bin/sh
# Host build, no SDK. Output in ./build. Not wired into any image.
# hk_accel_once.o is a real arm64e (PAC00) object. lld 23 cannot link arm64e: the dylib it writes is cpusubtype
# ARM64_ALL and unsigned, so it is for symbol/load-command inspection only. Deployable: Mac xcrun clang -arch arm64e
# -dynamiclib + pacstrip --sign + codesign --verify, as runtime/ca_sampler/tools/build.py does.
set -eu
cd "$(dirname "$0")"
L=${LLVM:-$HOME/.local/share/hackios-host/llvm/bin}
mkdir -p build
CF="-target arm64e-apple-ios26.0 -std=c11 -O2 -Wall -Wextra -Werror -ffreestanding -fno-builtin -fno-stack-protector -Isrc"
"$L/clang" $CF -c src/hk_accel_once.c -o build/hk_accel_once.o
env LD_LIBRARY_PATH=$HOME/.local/share/hackios-host/lld/usr/lib "$HOME/.local/share/hackios-host/lld/usr/bin/lld" -flavor darwin -arch arm64e -platform_version ios 26.0 26.0 -dylib \
  -install_name /private/var/hk/hk_accel_once.dylib -o build/hk_accel_once.inspect-only.dylib build/hk_accel_once.o src/libSystem.tbd
"$L/llvm-nm" -m build/hk_accel_once.o > build/hk_accel_once.o.nm.txt
"$L/llvm-nm" -m build/hk_accel_once.inspect-only.dylib > build/hk_accel_once.inspect-only.dylib.nm.txt
"$L/llvm-objdump" --macho --private-headers build/hk_accel_once.inspect-only.dylib > build/hk_accel_once.inspect-only.dylib.headers.txt
"$L/llvm-objdump" --macho -d --no-show-raw-insn build/hk_accel_once.inspect-only.dylib > build/hk_accel_once.inspect-only.dylib.dis.txt
sha256sum build/hk_accel_once.o build/hk_accel_once.inspect-only.dylib
