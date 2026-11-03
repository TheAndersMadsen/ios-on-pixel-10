# a7-ios-system-int1-persist: build receipt (2026-11-03, HOST; not booted)

Labels: SOURCE, HOST, PHYSICAL (an earlier boot of int1), INFERENCE. Nothing here touched the phone. The plan and the attended
sequence are in `PHYSICAL-PLAN.md` (r2).

| Artifact | sha256 |
| --- | --- |
| **boot.img** `research/images/a7-ios-system-int1-persist/` (Mac, copied to m1box) | **`84f993b65fb24f2c98af106f49b5265d57677a9fe54eed75ce42c7ce6fbf519a`** |
| payload-usb.bin (margin 39,929,424 B) | `958765289e138a3d08ea4ea84ee03ac7be3cc62e7687880fcee7a1930b188e84` |
| manifest.json | `db98427011dc332bec62e0acdb4e9877b8dafc2ca20374a5e9b073d59680aa33` |
| kernel.int1 (XNU hk-int1 484717f) | `0d0c99b2cd7b1c71509c9cf52af34ca29c1856001fd077df41b6386bf243e9bf` |
| overlay int1-r1.ovl | `c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e` |

## Kernel (receipts/int1-persist/xnu-ancestry.txt, kernel-strings.txt)

SOURCE (Mac release tree, which stayed p1 b228c4f, clean; no XNU build was run):
- dd000c8 is an ancestor of 7227fe7, and 7227fe7 is an ancestor of 484717f, with 15 commits between them.
- Of the 33 changed files, none is a persist, ufs, n882 or n913 file, and no diff line names persist, write_guard, ios_data or bp_part.
- `varfs_persist.inc`, `varfs_persist_core.h`, `hakios.blazer_persist_disk.inc` and `hakios.blazer_ufs.c` have the same blob ids at
  7227fe7 and 484717f.

HOST: kernel.int1 has `blazer-persist: ios_data at LBA`, `refused root "%s": userdata`, `blazer_persist_period` and
`n882_port_write_guard`, and no `blazer_ufs_fake_lun`.

## Gate (tools/image_tool.py; patch receipts/int1-persist/image_tool.gate.patch, tests test_image_tool.patch)

- `PERSIST_KERNEL_SHA` became `PERSIST_KERNELS`, which pins kernel.rootview ddf874fb… and kernel.int1 0d0c99b2…. The file's sha must
  equal the claimed pin.
- The record carries the image's own kernel sha and name. `check` requires `mach` to be pinned and to equal the record's sha.
- All other conditions are unchanged.
- Tests: `PersistIosData` has 11 tests: `test_pins`, `test_real_int1_kernel`, cross-pin manifests, and a pinned file named under the
  other pin. The whole file runs 95/95 OK, and `test_persist_check` 17/17 OK (`tests.txt`).
- The m1box `tools/image_tool.py` also holds other owners' uncommitted edits (LLVM env, pwr1 allow-list, `--drop-diag`). The gate
  patch touches only the persist block.
- Build tool: `tools/image_tool_int1_persist.py` = `research/ios26-phaseb-r1/int/tools/image_tool_int1.py` + the same patch
  (`tools/image_tool_int1_persist.patch`). The 11 persist tests also pass against it.

## Image (tools/mkimg_int1_persist.sh, Mac)

- int1's recipe and inputs. Line changes:
  - `+blazer_persist=1 +blazer_persist_period=15`;
  - `−blazer_usbcon=1 −blazer_usbcon_ch9=1`;
  - `hk_ustack=Preferences,MobilePhone → hk_ustack=Preferences`.
- 1018 → 1012 B, 56 tokens, common order unchanged.
- Why these drops: without them the line would be 1060 B. hk_ustack alone would give 1026 B, and the usbcon pair alone 1024 B (the
  limit is 1023).
- bootios still works without the console: run-attempt.sh's watch is the full `--wait`, park is detected over fastboot and the
  ramdump is pulled.
- `manifest_diff_int1_persist.py`: `MANIFEST-DIFF OK`.
  - mach, var_overlay, window_base, bootcpu, cpus, route, dropped_diag, entry, kernel_end, segs, margin and payload size all match.
  - adt_facts also match, except `seed_sha256`, which is random per build (it differs between pwr1 and int1 too).
  - The first run's check listed `adt` and failed only on that seed (`manifest-diff.first-run.txt`). The checker was fixed;
    nothing was rebuilt.
- `check`:
  - Mac (persist tool): `OK`.
  - m1box: shared tool `OK`, persist tool `OK`; a7-ios-system-int1 still `OK`.
  - The pre-change shared tool refuses it (`MISMATCH persist`), as designed (`image-check.m1box.txt`).

## Proposed NOTES line

**ios_data persist (2026-11-03, HOST):** `a7-ios-system-int1-persist` (84f993b6…) = int1 + `blazer_persist=1 blazer_persist_period=15`
(− usbcon console, hk_ustack Preferences only). The gate admits kernel.int1 (hk-int1 484717f; writer files byte-identical to
7227fe7). Not booted; attended sequence in `research/ios26-dualboot-r8/ios-data-persist/PHYSICAL-PLAN.md`.
