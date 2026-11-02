# Bootloader, chooser and Android handoff reuse audit

2026-11-02. Research only; no build, device command, image deployment or storage
change was performed. This audit does not establish working dual boot.

The useful shortcut is to keep the working Pixel shim and reuse mature image
and metadata libraries around it. No inspected project supplies a demonstrated
Tensor G5 UEFI platform or an Android return path suitable for this phone.

## Existing local work and evidence

- `docs/DUALBOOT.md` already defines the storage, recovery and boot acceptance.
- `research/ios26-feature-dualboot-r1/src/chooser_policy.c` implements bounded
  choice policy only. `hk_chooser_plan()` refuses Android and disk choices;
  there is no visible menu, Android dispatcher or verified-payload implementation.
- That feature's `tools/inspect_local.py` hashes regular files and identifies
  boot/vendor-boot headers. It explicitly does **not** validate their structure.
- The ongoing parent implementation has `dualboot/readback.c`,
  `dualboot/xnu_usb_readback.inc` and `tools/dualboot.py`. The latter validates
  captured GPT metadata. Do not write another transport or GPT parser.
- `shim/fdt.c` already parses memory, reservations and allocation pools and
  checks the whole XNU memory window. Keep its stricter admission policy.
- Local evidence says `userdata_exp.ai` belongs to Android's F2FS expansion
  scheme. Its reservation state and original contents are unknown. A valid
  iOS image or GPT capture cannot establish Android filesystem integrity.

## 1. AOSP boot-image tools: direct host reuse, high priority

Verified AOSP `system/tools/mkbootimg` commit:
`d2bb0af5ba6d3198a3e99529c97eda1be0b5a093`, obtained from Gitiles commit JSON.

[unpack_bootimg.py](https://android.googlesource.com/platform/system/tools/mkbootimg/+/d2bb0af5ba6d3198a3e99529c97eda1be0b5a093/unpack_bootimg.py)
provides `unpack_boot_image()`, `unpack_vendor_boot_image()` and
`VendorBootImageInfoFormatter`. It handles v4 signatures, vendor ramdisk table
entries, fragment types/board IDs, DTB placement and bootconfig. Apache-2.0.
[bootimg.h](https://android.googlesource.com/platform/system/tools/mkbootimg/+/d2bb0af5ba6d3198a3e99529c97eda1be0b5a093/include/bootimg/bootimg.h)
has the canonical packed layouts under its own BSD-3-Clause-style notice.
Preserve notices per file; do not label the whole package with one licence.

**Local overlap:** `tools/mkbootimg.py` is already an Apache-2.0 AOSP packer.
The earlier dualboot inspector only records version/kernel or ramdisk size;
it does not enumerate the Android boot-chain components. Reuse the missing
unpacking and layout knowledge, rather than replacing the working packer.

**Integration seam:** an offline Android-image manifest tool alongside the
existing readback/GPT tooling. Use AOSP extraction on regular local copies and
report each component's offset, length, hash, fragment metadata and provenance.
Have the wrapper independently bound every extent and reject truncation.
The stock chain may include separate `boot`, `init_boot`, `vendor_boot`,
DTBO and vbmeta dependencies; inventory the actual saved/captured set first.

**Smallest proof:** synthetic v4 boot plus vendor-boot containing two differently
typed fragments and bootconfig. Match AOSP offsets and re-extracted bytes;
reject overlapping, truncated and out-of-file table/fragment extents. Local
outputs belong under ignored `research/`, because bootconfig can hold identity.

**Savings/confidence:** high confidence for eliminating handwritten version and
fragment-layout work; no Android dispatch or preservation claim follows.

## 2. libavb metadata routines: direct reuse, high priority after readback

Verified AOSP AVB commit `761178607206f4cb2af79ed9eec52d8cbd814adb`.
The inspected C files carry MIT-style permission notices:

- [avb_footer.c](https://android.googlesource.com/platform/external/avb/+/761178607206f4cb2af79ed9eec52d8cbd814adb/libavb/avb_footer.c):
  `avb_footer_validate_and_byteswap()` validates magic/version and converts
  fields. It **does not** itself prove the footer's extents fit the input file.
- [avb_vbmeta_image.c](https://android.googlesource.com/platform/external/avb/+/761178607206f4cb2af79ed9eec52d8cbd814adb/libavb/avb_vbmeta_image.c):
  `avb_vbmeta_image_verify()` checks a supplied vbmeta image.
- [avb_descriptor.c](https://android.googlesource.com/platform/external/avb/+/761178607206f4cb2af79ed9eec52d8cbd814adb/libavb/avb_descriptor.c):
  `avb_descriptor_foreach()` uses overflow-aware descriptor bounds and expects
  cryptographically verified input.

**Local overlap:** none of those APIs appears in the inspected dualboot
inspector, readback tool or boot planner. Existing image checks prove our
staged iOS bytes, not the completeness of an Android recovery set.

**Integration seam:** a buffer-only offline dependency inventory. Associate
hash/chain descriptors with captured partition copies and report missing or
mismatching inputs. Use the library's verification result separately from
whether its signing key matches an independently established trusted key.
Good signatures with an arbitrary key do not establish stock authenticity.

**Smallest proof:** owned test-key fixtures with valid and altered vbmeta,
truncated descriptor areas, oversized footer offsets and one missing chained
image. Report each independently; reject a dependency set with missing bytes.
This needs a small host sysdeps/crypto build, not a Tensor hardware driver.
Do not wire slot, rollback-index or persistent-write callbacks for this tool.

**Savings/confidence:** high for avoiding bespoke endian/descriptor/crypto
parsers. It cannot validate Android's encrypted F2FS contents or recover an
earlier overwritten alias. The task remains blocked on complete real capture
before claiming a usable backup or recovery path.

## 3. libfdt and libufdt: host oracles, medium priority

Verified U-Boot tag `v2026.10` resolves to commit
`5508406582f6f7120dce0c4b3059819a41788db2` by `git ls-remote`.
[libfdt/fdt_check.c](https://github.com/u-boot/u-boot/blob/5508406582f6f7120dce0c4b3059819a41788db2/scripts/dtc/libfdt/fdt_check.c)
exposes `fdt_check_full(blob, size)` with dual GPL-2.0-or-later OR BSD-2-Clause
licensing. The BSD option is available for this inspected file; check its
supporting files before vendoring the complete library.

**Integration seam:** use libfdt as an independent host structural checker and
reservation/property reader for synthetic FDTs consumed by `shim/fdt.c`.
Do not equate structural acceptance with our memory-placement acceptance:
the latter deliberately rejects ambiguous pools and unsupported translation.

Verified AOSP libufdt commit `9b70f594cf149c7c73989c78f03d210f8aa1c1f6`.
[include/ufdt_overlay.h](https://android.googlesource.com/platform/system/libufdt/+/9b70f594cf149c7c73989c78f03d210f8aa1c1f6/include/ufdt_overlay.h)
declares `ufdt_apply_overlay()` and `ufdt_apply_multioverlay()`; the header is
Apache-2.0, while inspected
[ufdt_overlay.c](https://android.googlesource.com/platform/system/libufdt/+/9b70f594cf149c7c73989c78f03d210f8aa1c1f6/ufdt_overlay.c)
retains a BSD-2-Clause notice. It requires libfdt and allocator sysdeps.
The multi-overlay API is explicitly unstable and may mutate supplied buffers.

**Smallest proof:** offline copies of synthetic base tree plus two overlays;
compare applied properties/reservations and refused malformed fixups. Use only
if actual Android handoff requires DTBO composition. Do not add allocation and
overlay mutation to the proven shim merely because a library exists.

**Savings/confidence:** high confidence in mature format tooling, medium
immediate value because the existing live-FDT path already works.

## 4. HakiOS/Mu-Silicium: architecture reference, not a Pixel shortcut

Public HakiOS UEFI HEAD is still `687fa6c6a5a70f43184de92980e0a76eea5f2c4b`
(`git ls-remote`, checked in this audit). Its `BASE` is Mu-Silicium
`e51cd877e31c8fbb322032dc4cb6715e83d25ad3`.
[XnuLoader.c](https://github.com/oosexgang/hakios-uefi/blob/687fa6c6a5a70f43184de92980e0a76eea5f2c4b/files/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/XnuLoader.c)
is BSD-2-Clause-Patent. `StartPayloadLoader()` uses EFI `LoadImage`/`StartImage`
on an in-memory `loader.efi`; fallback `FlushLog()` writes a raw partition,
and `XnuLoaderMain()` eventually cold-resets. These are important behavior
differences from a read-only chooser above the Pixel shim.

**Reuse:** separate container identification, verified payload admission and
dispatcher callbacks. This is already the direction in `docs/DUALBOOT.md`.
Do not transplant the fixed payload address, EFI services assumptions, raw
logdump fallback or parser without strengthening entry bounds.

The [pinned HakiOS U-Boot guide](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/docs/u-boot.md)
describes a boot-v1 Qualcomm image, proprietary-interface-compatible USB shim
and specific memory carve-outs. Earlier local audit could not retrieve the
referenced `uefi/u-boot/BASE`/custom command source from the published trees.
Treat that extension as an unresolved source dependency, not reusable code.
Its POCO/QEMU results do not establish a Pixel implementation.

## 5. General bootloaders and chooser code: low immediate return

- U-Boot's [image-android.c](https://github.com/u-boot/u-boot/blob/5508406582f6f7120dce0c4b3059819a41788db2/boot/image-android.c)
  has actual v3/v4 parsing, vendor ramdisk and bootconfig assembly. GPL-2.0+;
  it relies on U-Boot mapping, allocation and board infrastructure. Useful as
  a future Android assembly reference, not a drop-in freestanding dispatcher.
- Its [common/menu.c](https://github.com/u-boot/u-boot/blob/5508406582f6f7120dce0c4b3059819a41788db2/common/menu.c)
  and [cmd/bootmenu.c](https://github.com/u-boot/u-boot/blob/5508406582f6f7120dce0c4b3059819a41788db2/cmd/bootmenu.c)
  are GPL-2.0+ and need CLI, ANSI console, allocation and event adapters.
  Importing that infrastructure for three choices is unlikely to save work.
- lk2nd HEAD `fd380ac637d1af38598e3f3c5321d4c962b96315` is Qualcomm-specific.
  Its [licence inventory](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/LICENSE)
  and [project licence](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/lk2nd/LICENSE)
  are mixed MIT/BSD/GPL, not one blanket licence. No Tensor platform identified.
- m1n1 HEAD `34c1a1e28b80ac5affaf4715fdb35c691a48532a` targets Apple Silicon.
  Its [README](https://github.com/AsahiLinux/m1n1/blob/34c1a1e28b80ac5affaf4715fdb35c691a48532a/README.md)
  says MIT applies through 1.9.9, GPLv2-or-later from 2.0.0; current
  [src/main.c](https://github.com/AsahiLinux/m1n1/blob/34c1a1e28b80ac5affaf4715fdb35c691a48532a/src/main.c)
  carries GPL-2.0-or-later and initializes Apple-specific AIC/PMGR/MCC paths.
  Neither its boot ABI nor those drivers supplies Tensor support.

## First integration-sized task

Extend the existing offline inspector with a **complete v4 image component
manifest**, using the pinned AOSP layouts/unpacker as an independent oracle.
Keep output separate from device identity and never execute reconstructed
shell arguments. Cover multi-fragment vendor ramdisk, bootconfig, init-boot
identification, extent arithmetic, malformed tables and unchanged-input hashes.
Pass its component inventory to the existing dualboot parent for the readback
capture plan. Then add libavb metadata verification after capture is complete.

This removes two substantial categories of handwritten parser work without
creating a second bootloader port or implying that a menu solves storage.
The Android dispatcher, isolated iOS storage and physical repeatability remain
separate unimplemented acceptance items.

Evidence method: targeted public raw/Gitiles source reads, exact ref queries,
and local file/symbol inspection. GitHub API requests hit HTTP403 rate limits;
no API HEAD values were invented. No compile or runtime result is claimed.
