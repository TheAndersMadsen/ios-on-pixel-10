# Android and iOS 26 on Pixel 10 Pro

The goal is an on-phone chooser, independent storage for each OS, persistent iOS
data, and a tested route back to Android. **This is not working dual boot yet.**

The current iOS root is in `userdata_exp.ai`. The saved stock Android fstab
includes that partition as an F2FS `/data` expansion alias. Its reservation state
is unknown, and its original contents were not backed up before earlier approved
iOS writes. A raw backup made now preserves the current bytes; it cannot recover
the original Android bytes. Keep Android boot held until storage ownership and
recovery are established.

## Implementation order

1. Capture both GPT copies and their complete entry arrays through the native
   read-only UFS path. Check CRCs, geometry, overlap, and agreement. Capture and
   verify the current iOS region and Android recovery dependencies before writes.
2. Establish Android's actual F2FS device/alias state. Design an isolated iOS
   allocation from the verified layout. Do not treat a missing alias file, an
   apparent GPT gap, or free filesystem bytes as permission to reuse blocks.
   No in-place shrink of encrypted/zoned F2FS is assumed supported. If a wipe or
   repartition is necessary, prepare its exact backup, migration and rollback
   sequence for the owner's separate approval.
3. Implement a chooser above the working Pixel shim/XNU handoff, with visible
   choices, physical input and a deterministic recovery choice. Initially use
   temporary boot images. Prove Android handoff with the complete stock boot
   chain; do not mark slots unbootable to escape the menu.
4. Test iOS → Android → iOS repeatedly, checking both roots and iOS data after
   each switch. Test a cold start, power interruption, recovery, Android update,
   and failure of either OS. Install a persistent chooser only after the
   temporary route and rollback are demonstrated and the owner approves the
   exact boot-image change.

Google's bootloader, firmware, slot metadata and existing backups remain intact
during development. A boot menu alone does not meet acceptance.

## HakiOS reference

[HakiOS UEFI, pinned at 687fa6c6](https://github.com/oosexgang/hakios-uefi/tree/687fa6c6a5a70f43184de92980e0a76eea5f2c4b)
uses Mu-Silicium and starts a loader from an in-memory payload. That separation
is useful here. Its Qualcomm platform, memory addresses and proprietary drivers
do not establish Tensor G5 support. A full Tensor EFI platform can be added
later; it is not a prerequisite for extending our existing working XNU loader.

[HakiOS's dual-boot documentation](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/docs/dual-boot.md)
describes carving a dedicated partition, erasing Android data, replacing a boot
slot and changing slot bootability. Those device-specific installation commands
must not be run on this Pixel.

## Current work

The prior `research/ios26-feature-dualboot-r1` contains a host-tested chooser
policy without a hardware adapter. It does not display a menu or launch Android.
The first implementation is a native USB/UFS readback service and host GPT
verifier, kept read-only on the phone. Kernel patches with existing unlicensed
context, device captures, GPT GUIDs and raw backup bytes stay under ignored
`research/ios26-dualboot-r2/`. Original readback code and host tooling can be
tracked separately.

`dualboot/readback.c` implements the block-cache state machine. The XNU adapter
queues reads on its own worker, validates the existing exact-read receipts and
serves cached RAM over USB. It is off unless `blazer_usb_readback=1`, supports
only the already attached physical LUN and constructs no write command. The
host binds every chunk to the image nonce, boot entry, LUN, generation, LBA and
CRC. It stops on a mismatch and never reconnects or repeats a selection.

`tools/dualboot.py` verifies both GPT headers and complete entry arrays, their
CRCs, reciprocal geometry, partition GUID/name uniqueness and non-overlap. A
capture is explicitly **GPT metadata only**, not a complete partition backup or
evidence that Android is intact. The EP0 transport is intended for small
discovery captures; high-throughput whole-partition backup is still needed.
Every received block is now saved before parsing. A refused capture leaves
`failure.json` and hashed observations, with no successful `capture.json`.

The first physical attempt, `20261102-105345-dualboot-gpt-readback-r1`, proved one
exact LU0/LBA0 read through the native service and returned normally at its
300-second deadline. The host rejected the MBR size before reading GPT headers.
The retained MBR has one protective entry at LBA1 with size `0xffffffff`, even
though this LUN is smaller. [UEFI defines the canonical size field](https://uefi.org/specs/UEFI/2.10_A/05_GUID_Partition_Table_Format.html#protective-mbr);
[Linux explicitly recognizes this saturated form](https://github.com/torvalds/linux/blob/v6.12/block/partitions/efi.c#L193).
The tool retains canonical-size checking by default. An operator can pass
`--reviewed-pmbr-sha256 HASH` to accept the saturated form only if the complete
MBR block matches the independently reviewed hash. All GPT copies, CRCs,
capacity, bounds and overlap checks remain mandatory. The actual device hash,
raw bytes and next capture profile stay in ignored research, not this document.

Reproduce host checks with `python3 -I dualboot/validate.py`. If the local XNU
tree is available, add `--base research/ios26-release-r1/work/xnu` to exercise the
actual adapter against the real exact-read ABI. `tools/stage_dualboot_readback.py`
produces a private source fixture and context-bearing patch without changing the
release tree; `dualboot/validate.py --objects` emits both real ARM64 objects and
checks their definitions with `BLAZER=1` explicitly present.

A full candidate kernel and temporary image have also been linked and built
locally. Exact hashes, source/object provenance, build checks and phone-test
results are in `research/ios26-dualboot-r2/HANDOFF.md`. The baseline relink
matches p29 byte-for-byte except its 16-byte `LC_UUID`; only the USB console and
UFS owner objects are replaced in the candidate. The release tree and artifacts
are unchanged. A successful host build does not establish device operation.

The later GPT attempt is **held for CPU and phone-owner context review**. The
existing image uses `cpus=1` without `bootcpu`; the subsequent cpu0 A520 audit
found a required workaround bit clear. The earlier LBA0 observation does not
resolve that prerequisite. Preserve the immutable image and arguments. An A725
context requires a separately identified, explicitly reviewed image, source,
nonce, readback transport and matching unstripped kernel. The corrected host
PMBR profile is frozen; this hold authorizes no retry or additional read scope.
See [the shared coordination policy](COORDINATION.md).

Complete GPT capture, Android integrity, independent iOS storage, chooser
input/output, Android handoff, persistence and installed cold boot remain
unverified. See the active entry in `NOTES.md` for exact validation and commits.

## Android recovery component inventory

`tools/android_bootset.py` inventories regular local boot-chain copies using the
unmodified pinned AOSP unpacker in `third_party/aosp_bootimg/`. It independently
bounds image sections and vendor fragments before extraction, then compares
extracted bytes and metadata with AOSP. It records kernel, generic ramdisk,
boot signature, vendor fragment types/board IDs, DTB and bootconfig extents and
hashes. Unsafe fragment names, overlaps, gaps, truncation and source changes
are refused. Outputs inside this checkout must be under ignored `research/`.

Example, using only already saved images:

```
python3 -I tools/android_bootset.py --slot a \
  --image boot=research/workspace/hardware/recovery-current-a/boot_a.img \
  --image init_boot=research/workspace/hardware/recovery-current-a/init_boot_a.img \
  --image vendor_boot=research/workspace/hardware/recovery-current-a/vendor_boot_a.img \
  --output research/android-bootset-a-NEW
```

The inspected saved slot-a set lacks `vendor_kernel_boot_a`, DTBO and AVB
metadata. Its vendor boot image has no DTB and carries two ramdisk variants;
the table alone does not establish which variants ABL selects. Older files
labelled slot b have different capture histories and are not a proven matching
recovery set. The inventory always distinguishes structural validation from
AVB-chain verification, independently trusted stock keys, current slot identity,
Android integrity and physical dispatch. None of those follows from a filename
or successful unpack. No boot/slot change is performed by this tool.

A separate saved-file check with pinned AOSP AVB tooling also found that
`recovery-current-a/init_boot_a.img` fails its embedded payload hash although its
metadata signature verifies. A second AOSP `verify_image` run on a read-only copy
confirms the digest mismatch. This is evidence about the saved file, not proof
of the phone's current Android state or the cause of the mismatch. Exclude it
from a verified recovery set. A saved vendor boot image uses algorithm `NONE`;
the upstream helper reports success for unsigned metadata too, so signature
presence and top-level key/chain trust must be checked separately.

Run owned synthetic and malformed-image tests with
`python3 -I tools/test_android_bootset.py`; the vendored tool makes these checks
independent of local research artifacts or network access.

## Storage and recovery prerequisites

The apps owner's 20 GiB root image exceeds the current 8 GiB alias. Host guest
success cannot establish deployable phone capacity. A new allocation needs a
verified GPT, Android alias ownership, room for persistent iOS data, complete
backups and a reviewed migration/rollback sequence. No alias-aware resize or
metadata-decryption path is qualified for this phone.

Back up current raw bytes and independently verify readable user-file recovery.
Android [metadata encryption protects its key with KeyMint and Verified Boot](https://source.android.com/docs/security/features/encryption/metadata);
raw ciphertext alone does not demonstrate recoverability after a reset or key
state change. The reported normal UFS LUNs also do not constitute an RPMB or
secure-key backup. Keep original backups intact and use an independent storage
destination; a host filesystem clone is not an independent copy.

After GPT acceptance, the smallest proposed AVB discovery starts with the first
block of the owner-selected slot's top-level `vbmeta`, if it is in the attached
LUN. Its bounded authenticated/auxiliary extents and descriptors determine the
next dependency request. [AVB describes chained keys and A/B naming](https://android.googlesource.com/platform/external/avb/+/761178607206f4cb2af79ed9eec52d8cbd814adb/README.md);
an embedded valid signature still needs an independently trusted root key.
Current host capture supports GPT only. Additional metadata reads need a
separate reviewed host consumer and exact LBA list; no live scope expansion is
implied. Full payload hashes, missing boot roles, slot/rollback state and Android
integrity remain separate acceptance requirements.
