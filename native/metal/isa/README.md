<!-- SPDX-License-Identifier: MIT -->
# Portable ISA and streams source import

This is the frozen original ISA-r2/r3/r4 and streams/r2/r3 C implementation,
relocated into `native/metal/{isa,streams}`. The C files, public headers and
existing C tests are byte-identical to their recorded origins. No parser,
frontend, firmware broker, provider or complete-stage validator is added.
ISA-r5 is a later explicit delta, never a mutable build dependency.

The library produces and analyzes native scalar instruction bodies, and
constructs/decodes PDS/CDM resources. Successful ISA bodies still carry nonzero
proof obligations. `hmsr_validate_frozen` still requires authentic independent
stage and ordering callbacks; absent callbacks return DEPENDENCY. The queue
bridge still returns UNAVAILABLE without its real emitter. No provider is
registered, no HAS_CODE permission is granted, and no execution is claimed.

The single CMake entry point here builds both libraries. It consumes the
existing AIR-r4 frontend, not a copy of AIR-r4's assembly or Rust parser. Its
test-only Metal core/adapter are read directly from the frozen AIR-r4 sources.
The two libraries replace these portable units in any later reviewed AIR-r4
integration; do not link another copy of those units alongside them.

## External dependency boundary

`EXTERNAL-DEPENDENCIES.json` records every required external file by exact
repository origin, SHA256, size and role. CMake checks all of them at configure
time and notices changes during a build. It does not download or regenerate
anything. Set `HACKIOS_ROOT` to the absolute repository containing those frozen
inputs. Output directories can be anywhere outside the imported source tree.

HMGU v1 and HMUSC1 remain the original shared headers at
`research/ios26-metaldrv-r1/abi/hmgpu_uc.h` and
`research/ios26-gpucc-r1/include/hmusc.h`. The canonical profile and queue
agreement are checked as well. No wire header or firmware constant set is
copied into this import. A future stable shared-header location requires a
separate explicit parent-reviewed origin/path delta, preserving these bytes.

Only build-directory symlinks expose AIR-r4's exact `hm_air.h`, `hmn.h` and
`hmn_streams.h`; the remaining include paths point at the canonical owners.
This prevents accidental fallback to AIR-r4's older sparse ISA/streams copies.
Generated objects, dylibs, executables, bitcode and these symlinks are never
source-import payload.

AIR-r4 retains the selected **LGPL-3.0-or-later** metal2vulkan-air boundary,
upstream commit `219f01365dc4c8eb346816c405b5b17403793764`. It remains an
external replaceable `HMAIRFrontend.dylib`. Exact source, license texts and
relinking materials stay with that assembly; this MIT import does not relicense
or redistribute it. See `LICENSE-MANIFEST.json` and `PROVENANCE.md`.

## Build and focused source tests

Run from the repository root after applying the reviewed patch:

```sh
cmake -S native/metal/isa -B research/metal-source-import-host -G Ninja \
  -DHACKIOS_ROOT="$PWD" -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DBLAZER=ON -DHMGPU_NATIVE_STREAMS=ON \
  -DHMGPU_NATIVE_SHARED_INIT=ON -DBLAZER_HMG_QUEUE=ON \
  -DHM_PORTABLE_TESTS=ON -DHM_PORTABLE_SANITIZERS=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build research/metal-source-import-host --parallel 1 --verbose
ctest --test-dir research/metal-source-import-host --parallel 1 --verbose
```

All four original gates default OFF. Focused tests require them explicitly ON.
ISA C is unguarded userspace code. The shared-init/bridge/queue C translation
units are guarded; a successful empty-TU compile is not enabled evidence.
Assertions stay active in the tests even in Release/RelWithDebInfo builds.
ASan/UBSan instrument the imported C libraries and tests, not the existing Rust
frontend. Leak checking is disabled explicitly. Each host test executes with
`PATH=/nonexistent`.

The twelve unchanged C test bodies cover memory lowering, ALU/control and SSA
allocation, actual AIR parsing/composition, raw byte and body analysis, common
initialization/resource closure, bridge refusals and modeled BO lifetimes.
The test-only LLVM assembler prepares original MIT textual source fixtures
inside the build directory. The `air_single_add` fixture is the original
AIR-r2 `add.ll` with only its entry name changed; it replaces the historical
owned metallib input for source-only testing. This run exercises raw bitcode
input, not metallib container decoding. No Apple SDK source/compiler product,
stock shader, cache, proprietary helper or device data is imported.

For ARM64 iOS compilation and strict linking, use a separate build directory:

```sh
cmake -S native/metal/isa -B research/metal-source-import-ios -G Ninja \
  -DHACKIOS_ROOT="$PWD" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_OSX_SYSROOT=iphoneos -DCMAKE_OSX_DEPLOYMENT_TARGET=26.0 \
  -DCMAKE_C_COMPILER=/usr/bin/clang \
  -DCMAKE_C_COMPILER_TARGET=arm64-apple-ios26.0 \
  -DBLAZER=ON -DHMGPU_NATIVE_STREAMS=ON \
  -DHMGPU_NATIVE_SHARED_INIT=ON -DBLAZER_HMG_QUEUE=ON \
  -DHM_PORTABLE_TESTS=ON -DHM_PORTABLE_SANITIZERS=OFF \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build research/metal-source-import-ios --parallel 1 --verbose
```

This emits actual ARM64 objects, both strict-linked libraries and source-test
consumer executables. Do not run cross-compiled tests with CTest. Verify named
text symbols and gated-off controls before claiming enabled compilation. The
link uses `-undefined error`; legitimate dylib imports remain bound to the
actual frontend and system libraries. It is not a zero-import library.

## Acceptance boundaries

These are host source/build results. HEALTH5 remains FAIL, and the existing
CPU/Trusty/RAM-layout HOLD remains in force. UM26.1@7036548 reference output
does not establish ABI compatibility with kernel donor26.1@6967606. The five
source-bound compiler caches are parent-owned reference evidence; no cache or
heuristic scanner is imported or treated as a trusted code validator. UC-r3
and frozen AIR-r4 remain the single kernel/provider and userspace compositions.

The parent reviews/applies/commits the additive source patch, records the
repository licensing entry and any future exact dependency-path change, and
adopts ISA-r5 only through its separately supplied delta. No build, boot or
physical slot follows from this import. Rollback removes only the reviewed
new files, using the exact reverse patch after checking it.
