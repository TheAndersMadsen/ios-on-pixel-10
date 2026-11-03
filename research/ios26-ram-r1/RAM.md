# RAM: full map, hw.memsize = 16 GiB (2026-11-03; HOST build and QEMU, not booted on the phone)

| | | |
| --- | --- | --- |
| XNU branch **`hk-ram-full`** | **`476c253eb1946d5d53c575af0f94791c88ddc2ad`** = hk-int1 484717f + 1 commit | Mac `research/ios26-release-r1/work/xnu`; `patches/0001-hk-ram-full-476c253.patch` (b887f8be…) |
| `kernel.ramfull` | `d92f5d737c248fc1f8660f2b18cd4f1620c3a17d4df4e73a4eb1ee507546cc87`, UUID 9753A547-9CB6-3743-88B3-9CAB82D7623A | `build/` (Mac and m1box, not in git) |
| `kernel.ramfull.unstripped` | `2258c949055e0ab367ff97dce12d2e09d27a1bb8452514bf9d29d022c8954fe7` | same |
| image `a7-ios-system-ramfull` | boot.img `2463b8de9e76bffac6524ab2e3d916ee9a16ae3c06bc9b7efe6dc417dc3d30e1`, payload ac7b8b7d…, margin 39,929,424 B | `research/images/` (Mac and m1box) |

## Root cause (source + physical log)

The shim hands XNU a 4 GiB window: `memSize = memSizeActual = 0x100000000` at 0x882000000. `blazer_mem=13` (patch 0760) raises
`memSize` to 0x33b000000 (12.92 GiB, stopping at `BLAZER_RAM_TOP` 0xbbd000000, below Android's first top reservation). It
leaves `memSizeActual` alone unless `blazer_mem_report=1`, which no recipe carries (int1 has 5 B of the 1023 B left). XNU 12377 backs
`hw.memsize` with `max_mem_actual = memSizeActual` (`bsd/kern/kern_mib.c:995`, `osfmk/arm64/arm_vm_init.c:1915`). The result is
the live int1 line `blazer-mem: window 0x882000000 + 0x33b000000, was + 0x100000000, hw.memsize 0x100000000`
(`research/laguna-usb-fix/attempts/live-20261103-213954-a7-int1-live/console.txt:12`). hw.memsize is below the managed size,
the opposite of iBoot's invariant (`memSizeActual >= memSize`). `ml_get_booter_memory_size` (`machine_routines_common.c:1254`)
therefore returns 4 GiB − 12.92 GiB, which wraps in uint64 (`booter_size`, VM_KERN_COUNT_BOOT_STOLEN, accounting only).

The window is capped by policy, not by the hardware. The 14 GiB high bank holds no fixed DT carve-out, and the denied
`blazer_mem_top` path (0781) is the only thing above 0xbbd000000.

## Fix (XNU 476c253)

- New `osfmk/arm/blazer_memplan.h`: pure, no XNU types. The RAM constants move there from `SWEET.h`, plus `BLAZER_RAM_INSTALLED`
  0x400000000 and `blazer_mem_plan()`.
- **`blazer_mem=5..13`: behaves exactly as before.** The host test compares it with the old function over every gib/fake/report/base/old combination.
- **`blazer_mem=14..16`, the full map:**
  - The window grows to `BLAZER_RAM_TOP_TAGS` 0xbe0f80000, the MTE tag base 0xbe0f83000 page-aligned down (constant already in SWEET.h since 0760).
  - `memSizeActual` = max(managed, installed 16 GiB), so `hw.memsize` reads 0x400000000 while `max_mem` stays what the VM manages.
- The `blazer_mem_top=1` denial and `blazer_low` (still denied on the phone) are unchanged. QEMU's `blazer_ufs_fake` top override is unchanged.
- New lines: `blazer-mem: full map, …` and, after arm_vm_init, `blazer-mem: vm max_mem 0x…, hw.memsize 0x…` (read back from
  the sysctl's own variables).
- **Boot-arg budget:** int1's line with `blazer_mem=13` → `blazer_mem=16`, **1018 B → 1018 B (+0 B; limit 1023, 5 B left)**, 56 tokens
  (`receipts/manifest-diff.txt`). The kernel is the only other manifest change.

## Reserved vs usable (FDT d7c27fdc…, ABL `DRAM size : 0x400000000`, Android iomem + dmesg; `test/reserved.h`)

| Range | Size | What | blazer_mem=16 |
| --- | --- | --- | --- |
| 0x80000000..0x100000000 (low bank) | 2048 MiB | All 43 fixed DT carve-outs (563 MiB in this bank: AoC 48M, sec_dram/trusty 142M, gsa-gme 62M, gpu_fw 33M, tpu/gxp/vpu fw, cp_rmem modem, famodel/farawimg faceauth 155M, bl31, ramoops, ABL, …), plus our shim, ABL ramdisk, panel/flip pool and USB/UFS arenas | **not managed** (blazer_low stays denied) |
| 0x880000000..0x882000000 | 32 MiB | 16 MiB iomem reserved (owner unknown) + loader alignment | not managed |
| 0x882000000..0xbbd000000 | 13,232 MiB | free | managed (as int1) |
| 0xbbd000000..0xbe0f80000 | 576 MiB | at Android's boot: Linux memblock (0xbbd1f8000..0xbd5600000), vstream 72M + start of vframe, both CMA "map reusable"; all placed by Android itself, no fixed reg | **newly managed** |
| 0xbe0f80000..0xc00000000 | 496 MiB | MTE tag base 0xbe0f83000 up ("MTE S: 1, NS: 0"); rest of vframe, pkvm_iommu_cma, faprev, faceauth_tpu/dsp (non-reusable) | not managed |

**Managed 0x35ef80000 = 13.48 GiB (84.3 % of 16 GiB, was 12.92 GiB); hw.memsize 16.00 GiB.** The host test
(`receipts/host-test.txt`, 25,044 checks, 0 failed, also under ASan/UBSan) asserts that every phone window, for each gib 0..70:
- stays inside the FDT banks, below the tag base and 16 KiB aligned;
- overlaps no fixed carve-out;
- for 5..13, overlaps no iomem reserved span;
- for 14..16, overlaps only Android's boot-time placements at the top, never the non-reusable faceauth pools.

**Basis for admitting 0xbbd000000..0xbe0f80000 (inference from physical Android logs):**
- Every allocation there is one Android's kernel makes at its own boot: memblock, plus CMA that the buddy allocator uses as ordinary movable pages.
- That makes it plain non-secure DRAM at reset, unlike the fixed no-map carve-outs.
- Not proven: that no secure-world protection survives into our boot path. `blazer_mem_test` on the phone is that proof (see below).

## Evidence

- **ARM64 object/kernel (Mac, `receipts/kernel-verify.txt`, build `receipts/build_ram1.out`):**
  - `mk.sh -j8` under `/tmp/fleet/kernel-build-slot.lock`. Tree p1 b228c4f clean → hk-ram-full rc 0 in 65 s → **p1 restored and rebuilt, rc 0** (obj kernel 89ddad4f…, has no full-map string).
  - Strings: `blazer-mem: full map …` (both variants) and `blazer-mem: vm max_mem …`.
  - `_arm_init` references `_max_mem`/`_max_mem_actual`. 0 undefined symbols in the unstripped kernel.
  - Disassembly of the inlined plan: `base>>25 ≥ 0x441` bottom check; `csel` of 0xbbd000000 / 0xbe0f80000 on `gib > 13`; fake override; `max(size, 0x400000000)` stored to memSizeActual.
- **QEMU preflight, standard** (`receipts/preflight-pf1.txt`, run `ramfull-pf1`, 600 s, window 13 GiB; `blazer_mem` dropped as phone-only): **PASS**, 0 findings, 0 panics, Home-equivalent at 343 s. Regression check only.
- **QEMU growth run** (`ramfull-grow1`, harness variant `tools/qemu-ufsroot-ram.py` = rig qemu-ufsroot.py bdc6f360 + `--loader-gib`,
  `receipts/qemu-ufsroot-ram.patch`):
  - The loader hands 10 GiB of a 15 GiB backed window, as the phone loader hands 4 GiB of its bank. Same translated line + `blazer_mem=15 blazer_mem_test=4096`.
  - `receipts/grow1-blazer-mem.txt`:
    ```
    blazer-mem: window 0xa00000000 + 0x3c0000000, was + 0x280000000, hw.memsize 0x400000000
    blazer-mem: full map (QEMU fake), installed 0x400000000, managed 0xa00000000..0xdc0000000
    blazer-mem: vm max_mem 0x3c0000000, hw.memsize 0x400000000
    blazer-mem: test start 0xc80000000..0xdc0000000 stride 4096
    blazer-mem: test written
    blazer-mem: test pass
    ```
  - It grows by 5 GiB, the VM manages 15 GiB, and hw.memsize reports the installed 16 GiB (> managed). The new 5 GiB passes the write/read test. 0 panics.
  - `qemu_preflight.py --analyze`: **PASS** standalone (`preflight-grow1-nobaseline.txt`). Against the pf1 baseline it says FAIL on 2 "missing daemon" diffs; both are artifacts:
    - `exec lsd` is in the log, glued to a backboardd IOKit line (`grow1-lsd-line.txt`, console line 657).
    - `aonsensed` starts on demand at guest t≈555 s in pf1, 30 lines before the end of the window. grow1 started about 6 s later on a busier rig and stopped at 600 host s.
  - QEMU's address map is not the phone's: this proves the grow/readback/test path and the reporting, not the phone's top range.
- **Probe:** `docs/probes.yaml` `ram-rest` needed a window "above 15 GiB", which the 14 GiB high bank can never hold.
  - It now requires the full-map window + readback + a 900 s deadline with no panic.
  - `tools/test_probe_eval.py` OK (19). The synthetic expected lines (`test/expected-phone.synthetic.log`) score ✅. int1's live log scores no verdict.

## Phone test (coordinator; bare `fastboot boot`, return check after)

1. Unattended 900 s boot of the image as built (int1 recipe, `blazer_deadline=900`):

       tools/bootios research/images/a7-ios-system-ramfull/boot.img a7-ios-system-ramfull --mach research/ios26-ram-r1/build/kernel.ramfull.unstripped --wait 1080

   Success in `ramdump/kernel.log` (`probe_eval.py --row ram-rest <attempt>` → works):

       blazer-mem: window 0x882000000 + 0x35ef80000, was + 0x100000000, hw.memsize 0x400000000
       blazer-mem: full map, installed 0x400000000, managed 0x882000000..0xbe0f80000, unmanaged: low bank 0x80000000..0x100000000, high 0x880000000..0x882000000 and 0xbe0f80000..0xc00000000
       blazer-mem: vm max_mem 0x35ef80000, hw.memsize 0x400000000
       blazer-root: deadline 900 s, stage …        (and no other panic; Home as int1; Android return check PASS)

2. Memory test of the new 576 MiB, if 1 passes. It needs a rebuild:
   - `blazer_mem_test=4096` costs 21 B and the line has 5 B left. Drop e.g. `hk_ustack=Preferences,MobilePhone` (34 B, a sampler), giving 1005 B.
   - The test covers everything above the loader's end, 0x982000000..0xbe0f80000 (it includes the new 576 MiB). Expect `blazer-mem: test start 0x982000000..0xbe0f80000 stride 4096`, `test written`, `test pass`.
   - `blazer_mem=16 blazer_mem_test=4096` replaces the 13 GiB test that p32 relied on.
3. **Failure signs and fallback.** If the panic or abort happens in arm_vm_init or the memory test, or later corruption appears, the top range is not ours.
   - Same kernel, `blazer_mem=13`: the host test shows it behaves exactly like int1.
   - A further middle step is not offered: the next boundary inside the range would be 0xbd5600000 (memblock end), an unproven split.

Not done here: the low bank (blazer_low physical admission; it needs a firmware-ownership decision and the faceauth famodel/farawimg
carve-outs excluded from table entry 0). hw.memsize = 16 GiB is new to iOS userland on this device (iPads ship 16 GiB; inference: no
consumer keyed on an iPhone-sized memsize is known here), and only the phone boot shows the effect.
