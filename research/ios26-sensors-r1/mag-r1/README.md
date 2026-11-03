# mag-r1: compass (MMC5616WA) on the AoC i3c0 pads, patch 0930

Plan and boot steps: `../PLAN.md` sections 5-6. Host only: not linked, not QEMU-run, not booted.

- `patches/0930-blazer-sensor-compass.patch`: against release `b228c4f` (`receipts/apply-check.txt`).
- `src/blazer_mag_hw.{c,h}`: the new files (also inside the patch).
- `tests/host_mag.c`: register-level, the exact file. `tests/bench_mag.c`: bit-level, harness copied from `../tests/bench.c`.
- `tools/run_tests.py DIR`: DIR holds the patched `blazer_sensor_hw.*`, `blazer_mag_hw.*`, and the release tree's
  `blazer_hw_port.h`, `blazer_cpmq.{c,h}`. Builds the three tests with ASan/UBSan and runs 22 mutants.
- `tools/mac_objects.py RELEASE_WORK OUT PATCHED`: on the Mac, compiles the five changed files with the release build's
  own per-object commands into OUT (the release tree is only read). `receipts/mac-objects.txt` is its output.
- `obj/*.local.o`: m1box arm64e objects of the two hardware-free files (LLVM 22 host toolchain, freestanding, -mkernel).
