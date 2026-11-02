# Licensing

**This repository is private, and no licence is granted.** Nobody may copy, use or redistribute its contents on the strength of this document. Parts of it carry their own licences, listed below, and those apply to those parts only. There's no `LICENSE` file on purpose: one licence can't truthfully cover this tree, and parts of it have no licence that anyone here could pass on.

This is a working inventory written from the files' own headers and the project's records, not legal advice and not a line-by-line audit.

## What each path is

Sources: file headers, `research/legacy-root-20261101/PROJECT-COMPOSITION.md` and `research/ios26-merge-r1/` (both local only).

| Path | Origin | Licence as far as known |
|---|---|---|
| `xnu/ios16-base/patches/` | Snapshot of the iOS 16 port on Apple's `xnu-8796.121.2`: Apple's code in context and in new files, HakiOS upstream porting changes, tegu-derived work, local changes | **Mixed and partly unknown.** Apple's parts are under Apple's licences (APSL), and their notices must stay. The tegu-derived parts have **no licence**. The patches aren't split by origin |
| `shim/tgl_ufs_link.c`, `.h` | Linux UFS code, with Samsung, Linux Foundation and Google copyright lines | GPL-2.0-only, by header |
| `shim/frame_tables.h`, `shim/dcs_tables.h` | Generated from vendor sources at GrapheneOS `8880355265bb` and `panel-gs-bmea.c` | **Undecided.** Generated from GPL sources, so treat as GPL-derived until decided |
| `shim/google-wdt-inspect.h`, `shim/probe.h` | Register facts taken from Google's Pixel kernel source | Facts, with the source named. Needs review |
| `shim/font.h` | Generated from a `cp850-8x16` PSF console font | **Unknown.** The font's source and licence aren't recorded |
| 11 files in `shim/` marked `SPDX-License-Identifier: MIT` (`tgl_all`, `tgl_dcs`, `tgl_scanout_takeover.h`, `tgl_ufs_handoff`, `tgl_ufs_host`, `tgl_ufs_route`) | Local work, by header | MIT by header. Some name non-local sources, so check each claim. No copyright holder is stated |
| Other files in `shim/`, including `start.S`, `loader.c`, `payload.h`, `laguna_usb.c` | Local work and porting code. `start.S` copies tegu's EL2 to EL1 sequence register for register. `payload.h` and `laguna_usb.c` follow tegu's formats | **No licence stated; tegu-derived in part** |
| `tools/mkbootimg.py` | Android Open Source Project | Apache-2.0, by header |
| `third_party/aosp_bootimg/` | Unmodified AOSP `unpack_bootimg.py`, pinned at `d2bb0af5ba6d3198a3e99529c97eda1be0b5a093`; provenance in its README | Apache-2.0. Original notice retained and complete `LICENSE` included. Separately licensed `bootimg.h` was read for format facts and is not copied |
| `tools/android_bootset.py`, `tools/test_android_bootset.py` | Original bounded component-inventory wrapper and owned synthetic tests around the pinned AOSP tool | MIT, by file headers. Extracted Android components and private inventories stay in ignored `research/` |
| `dualboot/`, `tools/dualboot.py`, `tools/stage_dualboot_readback.py`, `tools/test_dualboot.py` | Original project readback protocol, XNU adapter, host GPT verifier and tests. GPT field facts follow the UEFI specification; no UEFI or Android implementation copied | MIT, by file headers. Kernel patches containing existing third-party context remain under ignored `research/` |
| `tools/image_tool.py` | Local work. Its `USER` boot arguments were copied from tegu's build script | No licence stated. Owner decision pending |
| `tools/native_gpu_upstream.py` | Original GitHub source inventory and immutable snapshot tool; no upstream implementation copied | MIT, by file header. Downloaded source/license snapshots stay under ignored `research/` with their own terms |
| `runtime/ca_sampler/` | Original guarded CPU sampler, runtime hook and source/test/build helpers; ABI facts from the local 23G90 reference, no Apple implementation or artwork included | MIT under the scoped `runtime/ca_sampler/LICENSE`. Generated fingerprints, Apple reference inputs, binaries and overlays stay in ignored `research/` |
| `runtime/exit_trace/` | Original bounded process-exit observer, host mocks and staging/check helper; uses XNU's existing unwinder through its declared API | MIT under the scoped `runtime/exit_trace/LICENSE`. XNU-context patches, disassembly, Apple binaries, captures and compiler outputs stay in ignored `research/` |
| `tools/mkadt.py` and other files in `tools/` | Local work and porting code. Some come from upstream porting code; provenance is recorded per file only in part | No licence stated |
| `*.md`, `docs/`, `.github/` | Local work. The design of some documents follows `ios-tegu`'s structure, with this project's content | No licence stated |

## Kept out of git

| What | Why |
|---|---|
| iOS userland, root images, Device Trees, kernelcaches, shared caches | Apple's proprietary software |
| The iOS 26 kernel series, combined patches, Renegade and root scripts carrying tegu's patches | Tegu's context lines, with no licence, on Apple's XNU |
| Firmware for Wi-Fi, GPU, always-on chip, audio and others | Vendors' proprietary files |
| Partition backups, dumps, device trees, captures | Device data, with identifiers possible |
| Keys, including test keys | Not to be shared |

## Before any public release

Going public is the owner's decision. Each of these must be settled first:

1. **Tegu.** `ios-tegu` has no licence, so by default nothing derived from it may be redistributed. Ask its author for a licence or permission, or remove and rewrite everything derived from it: `xnu/ios16-base/patches/`, `shim/start.S`'s entry sequence, the payload format, the USB protocol, the `USER` boot arguments. Do the same check for HakiOS, dada and felix code, whose terms aren't recorded here.
2. **History.** Removing a file isn't enough: git history keeps it. The patches are in every commit since they were added, so a public tree should start from a clean or rewritten history, confirmed by the owner.
3. **GPL.** `tgl_ufs_link.c` is GPL-2.0-only and is linked into the same shim binary as MIT and unlicensed code, and the generated tables are probably derived from GPL sources. A distributed shim binary or source tree must meet the GPL, which affects the whole shim's licence. Decide `frame_tables.h` and `dcs_tables.h`.
4. **Apple.** Keep APSL notices on Apple's code and meet the APSL's terms. Audit the APFS and other material in the patches. Confirm no Apple binary, tool output, Device Tree data or iOS screenshot is tracked, and that facts from Apple's binaries in the notes are stated in our own words.
5. **Vendor data.** Review the panel values, DCS sequences and register tables in `shim/`, and values taken from firmware or stock files.
6. **Device identity.** A full read of tracked notes and history for serials, IMEIs, MACs, board identifiers, account names and local paths. `check_tracked.py` covers only a few patterns. A regex search found nothing, and that isn't an audit.
7. **Names and trademarks.** Check the project's name and descriptions against Apple's and Google's trademark rules, and keep the README's statement of non-affiliation.
8. **Legal advice.** Porting Apple's userland to other hardware raises questions beyond copyright notices, such as iOS's own licence terms. Take advice before publishing.
9. **Then choose a licence** per path, add `LICENSE` and SPDX headers, and record copyright holders. Update this file.

## Adding code

Record the origin and licence here in the same commit, and keep the original notices. Don't add code with no licence: reading it for facts and writing fresh is the rule, and what's copied says so.
