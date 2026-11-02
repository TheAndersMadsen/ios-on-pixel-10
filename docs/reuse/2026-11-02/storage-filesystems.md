# Storage and filesystem reuse audit

2026-11-02. Research only: source and handoff inspection, public source verification;
no compilation, test execution, USB access, boot, mount, capture or storage write.
The integration proposals below have not been implemented by this audit.

## Best return

Use existing filesystem and partition tools as independent **offline oracles**.
Do not replace the working single-slot UFS reader to chase the current UI lag.
The largest storage-related labour saving is avoiding another hand-written F2FS
metadata walker, followed by independently checking our new GPT verifier.

| Priority | Candidate | Reuse class | Confidence / limit |
|---|---|---|---|
| P1 | util-linux libfdisk GPT parser and tests | Host library/tool and independent oracle | High; supports explicit read-only opens, needs matching 4 KiB sectors |
| P1 dependency discovery | AOSP f2fs-tools alias-aware metadata checks | Separate host tool; format reference | High source evidence; usable Android metadata/decryption not established |
| P2 | Correct Google 6.12 UFS source and generated definitions | Register/protocol reference; source audit tooling | High for the source family; not exact shipped-build identity |
| P3 | Apple LZFSE/LZVN decoders | Direct BSD-licensed code, conditional future use | High code availability; no current HFS-root speed benefit established |

## Existing work to reuse first

The current release source already includes `hakios.blazer_ufs_adapt.inc` and its
`blazer_ufs_interval` gate. These correspond to corrected 0990 and interval 0992;
the old handoffs that describe them as awaiting integration are stale for source
presence. This audit did not establish which gates ran in any physical capture.
Do not assign another implementation of adaptive waiting or shorter poll steps.

`bsd/sys/hakios.blazer_ufs.h` already exposes `n882_blazer_read10_exact()` for
whole-LUN reads with driver locking, and `n882_blazer_now_us()` for its deadline
domain. Build the readback transport on that contract, not another SCSI engine.
The current [`tools/dualboot.py`](../../../tools/dualboot.py) already parses both
GPT headers/arrays, checks their CRCs and agreement, rejects overlaps and hybrid
MBRs, and reports `storage_isolation_proven=False`. Its `fstab_owners()` correctly
leaves live alias state unknown. This is active concurrent work, read only here.

`handoffs/persist.md` records real save/restore evidence through S5, separately
from host modelling. The later persistence handoff has a stable-snapshot patch,
strict cache exclusions, and an unresolved icon-cache path inventory. Replacing
this with another archive saver would discard substantial existing validation.
Whole `/var` persistence is not equivalent to the present bounded whitelist.

## 1. libfdisk: independently check GPT without writing another parser

Verified upstream HEAD by `git ls-remote`:
`becdb8ba9f6ce3b0fa2a8ec0d0fb4bb45f5a860f`.

- [`libfdisk/src/gpt.c`](https://github.com/util-linux/util-linux/blob/becdb8ba9f6ce3b0fa2a8ec0d0fb4bb45f5a860f/libfdisk/src/gpt.c):
  `gpt_read_header`, `gpt_check_header_crc`, `gpt_check_entryarr_crc`,
  `gpt_check_lba_sanity`, `gpt_probe_label`, `gpt_verify_disklabel`.
- [`libfdisk/src/context.c`](https://github.com/util-linux/util-linux/blob/becdb8ba9f6ce3b0fa2a8ec0d0fb4bb45f5a860f/libfdisk/src/context.c):
  `fdisk_assign_device(..., readonly=1)` selects `O_RDONLY`;
  `fdisk_assign_device_by_fd` accepts an already-open descriptor.
- [`libfdisk.h.in`](https://github.com/util-linux/util-linux/blob/becdb8ba9f6ce3b0fa2a8ec0d0fb4bb45f5a860f/libfdisk/src/libfdisk.h.in):
  `fdisk_save_user_sector_size` configures the sector interpretation.
- [`libfdisk/COPYING`](https://github.com/util-linux/util-linux/blob/becdb8ba9f6ce3b0fa2a8ec0d0fb4bb45f5a860f/libfdisk/COPYING)
  is LGPL-2.1-or-later; the
  [`fdisk GPT test`](https://github.com/util-linux/util-linux/blob/becdb8ba9f6ce3b0fa2a8ec0d0fb4bb45f5a860f/tests/ts/fdisk/gpt)
  is GPL-2.0-or-later. Keep these separate from a permissive test wrapper.

**Seam:** a small host executable opens a regular synthetic image read-only,
selects 4096-byte sectors before assigning the image, and emits partition ranges,
header diagnostics and verification status. Compare these with `inspect_gpt()`.
The parent verifier has a stricter policy than general recovery tools: libfdisk
can recover a usable label from one damaged GPT copy. Such a discrepancy should
be reported as deliberate strict rejection, not silently changed into success.

**Smallest proof:** reuse synthetic fixtures in `tools/test_dualboot.py`; compare
clean 4 KiB geometry, bad header/array CRC, inconsistent copies, out-of-range
entries, overlap, hybrid MBR and truncation. Hash the fixture before and after.
Use no host block-device path and call no write-label API. Linux host/container
support is a dependency; macOS portability of this particular build was not tested.

**Labour saved:** obtains a maintained second implementation, endian/CRC checks
and a mature fixture source without maintaining a second local GPT parser.

## 2. f2fs-tools: reuse alias-aware checks, subject to metadata access

Verified AOSP `main` commit through Gitiles JSON:
`d34dcc887617535a0001ea389a2bb8058f41ea05` (tree
`748db6474b76d45162de010962a01db391daaf44`). Pin it; do not assume an old
distribution's `fsck.f2fs` understands device aliasing.

- [`include/f2fs_fs.h`](https://android.googlesource.com/platform/external/f2fs-tools/+/d34dcc887617535a0001ea389a2bb8058f41ea05/include/f2fs_fs.h):
  `F2FS_DEVICE_ALIAS_FL`, `IS_DEVICE_ALIASING`, device and inode layouts.
  Header states GPL/LGPL version 2 dual licensing and identifies LGPL-2.1
  byteswap material; it also contains explicitly GPL-derived sections.
- [`fsck/fsck.c`](https://android.googlesource.com/platform/external/f2fs-tools/+/d34dcc887617535a0001ea389a2bb8058f41ea05/fsck/fsck.c):
  alias inodes use `i_ext` to walk their reserved extent; alias data skips
  ordinary SSA ownership validation while retaining validity/bitmap checks.
  This file is GPL-2.0-only.
- [`fsck/dump.c`](https://android.googlesource.com/platform/external/f2fs-tools/+/d34dcc887617535a0001ea389a2bb8058f41ea05/fsck/dump.c):
  `dump_node` and inode/block inspection supply an existing metadata explorer;
  its file notice is GPL-2.0-only.
- [`fsck/main.c`](https://android.googlesource.com/platform/external/f2fs-tools/+/d34dcc887617535a0001ea389a2bb8058f41ea05/fsck/main.c)
  rejects resize of an image with the device-alias feature. Do not base a
  dual-boot migration plan on generic F2FS shrink instructions.

The original AOSP
[`exp_alias` implementation commit](https://android.googlesource.com/platform/system/core/+/77ee43a9fe56db6042d9f91d75cab703f04180e7)
explains the reserved placeholder relationship. It confirms that a partition
appearing separately in GPT need not be independently available to another OS.
Our saved fstab alone cannot establish whether the placeholder remains reserved.

**Seam:** keep f2fs-tools as a separate GPL host utility in ignored research,
then normalize its evidence into an original JSON report. Do not copy its walker
into XNU or into a supposedly permissive Python parser. Follow the local
licensing policy for GPL material; tool execution and copied implementation are
different decisions.

**Smallest proof:** first inspect a synthetic multi-device image with a device
alias, then inspect changed copies with reserved and released aliases. The
verification pass opens copies read-only and retains before/after hashes; never
feed it the phone or an only backup. Formatting fixture files is a separate host
test task, not a command performed in this audit.

**Dependencies:** readable complete F2FS metadata, all constituent device geometry,
the actual feature set, and any required owner-controlled metadata-decryption
path. A raw encrypted Android `/data` image may not be parseable by this tool.
Obtaining a plaintext view is not established here. Do not interpret failure to
find an inode, missing alias pathname or tool failure as unused space.

**Labour saved:** avoids implementing NAT/SIT/checkpoint/extent traversal from
scratch. It does not recover Android bytes overwritten by earlier iOS staging.

## 3. Google UFS: keep the correct reference, not a new driver port

Verified local repository HEAD and public GitLab commit API:
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`, committed 2026-10-24.
The captured kernel family is 6.12.81; that is not proof of identical source build.
The normal GitLab HTML tree returned HTTP 403; its public API source endpoint
worked. Local files are in `research/ios26-webscout-r1/dl-gos-6.12/repo/`.

- [`lga/ufs-regs-gen.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/drivers/ufs/lga/ufs-regs-gen.h):
  GPL-2.0-only generated offsets, masks and shifts; distinct from the older
  incorrect `*_OFFSET` table already warned about in `NOTES.md`.
- [`ufs-google.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/drivers/ufs/ufs-google.c):
  GPL-2.0-only; callbacks for HCE, link startup, suspend/resume and MCQ are references
  for future lifecycle work. They depend on Linux UFS/SCSI/PM infrastructure.
- [`lga/ufs-platform.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/drivers/ufs/lga/ufs-platform.c):
  GPL-2.0-or-later; LGA platform setup, PHY readiness and CPM dependencies.
  Do not copy embedded firmware/table contents into tracked audit artifacts.

**Seam:** add an original host source-audit tool that records pin/file hashes and
checks named offset/mask/shift invariants before any future register-table change.
Keep generated vendor derivatives and machine output ignored under research.
It should reject a 6.6 table accidentally substituted for the approved 6.12 input.

**Smallest proof:** validate that each one-bit field satisfies `mask == 1 << shift`
and that current named offsets match the approved local source. Mutate a field
shift and require rejection. This catches transcription/version drift; it proves
no hardware behavior. Google's internal `go/ufs-autogen` generator is not public.

**Limits:** the current driver deliberately refuses MCQ and uses a bounded legacy
slot. Porting Linux MCQ, clocks or recovery is substantial new hardware work and
would weaken existing proofs if treated as a drop-in. Existing measurements put
storage well below CPU rendering as the current UI bottleneck.

## 4. LZFSE/LZVN: a real decoder instead of handwritten codec work

Verified upstream HEAD `e634ca58b4821d9f3d560cdc6df5dec02ffc93fd`.
[`LICENSE`](https://github.com/lzfse/lzfse/blob/e634ca58b4821d9f3d560cdc6df5dec02ffc93fd/LICENSE),
[`src/lzfse_decode.c`](https://github.com/lzfse/lzfse/blob/e634ca58b4821d9f3d560cdc6df5dec02ffc93fd/src/lzfse_decode.c)
and [`src/lzvn_decode_base.c`](https://github.com/lzfse/lzfse/blob/e634ca58b4821d9f3d560cdc6df5dec02ffc93fd/src/lzvn_decode_base.c)
carry BSD-3-Clause terms. Direct reuse with notices is possible.

The old APFS reader handoff reports missing LZVN/LZFSE decmpfs support. Its current
local `cfile_header()` still rejects unrecognized types, while the active p29
release has no `bsd/miscfs/apfs` directory. Therefore this is conditional future
APFS/tooling reuse, not a present HFS-root boot or UI optimization.

Use `lzvn_decode` for an appropriate raw LZVN block; the outer decmpfs/resource
fork framing still needs an adapter. `lzfse_decode_buffer` returns destination
capacity on `DST_FULL`, so a return equal to expected length alone does not prove
complete successful decoding. Validate actual decoder status/end conditions or
use a bounded extra-output-byte strategy with guarded buffers.

**Smallest proof:** host-only synthetic compressed attributes/resource blocks,
truncation at every offset, malformed lengths, canaries and exact expected bytes;
compare with the platform Compression implementation where formats agree.
Only implement this if a chosen image actually contains those codec types.

## Other leads and exclusions

Existing HakiOS `var_store.c` was already considered by the persistence owner;
its commit protocol ideas are not an unclaimed shortcut. Incremental raw backups
can reuse chunk hashing and host deduplication later, but an absent chunk is not
a zero chunk: capture completeness must remain explicit. A GPT-only capture is
not an Android/iOS data backup. Neither a clean iOS-root checksum nor alias-aware
format parsing establishes Android integrity or permits allocation/migration.

Next task: implement the libfdisk synthetic-fixture comparison first; separately
resolve whether F2FS metadata is even available for offline alias inspection.
