# HakiOS and community XNU ports: incremental reuse audit

2026-11-02. Research only; no compilation, guest run, phone command or deployment.
Inspected local release source at `237e3889640333558525c8082593e68cc5401405`;
the relevant inspected files had no local modifications. Physical results remain
the separately recorded phone attempts in `NOTES.md`.

The useful next contribution from this family is a small registry-discovery
delta. Most of the earlier generic dada kernel fixes are already in our release.
Replacing the port wholesale would repeat completed work and import unrelated
Qualcomm hardware assumptions.

## Verified source identities

These HEADs were verified with `git ls-remote`; source inspection used local
copies and selected files fetched directly at the immutable revisions.

| Project | Verified revision | Assessment |
|---|---|---|
| [HakiOS kernel](https://github.com/oosexgang/hakios-xnu-kernel/tree/96ffbc532e970f3540885755d457e401e04d4707) | `96ffbc532e970f3540885755d457e401e04d4707` | XNU 8796 common drivers; useful generic IOKit contracts |
| [dada](https://github.com/superboyyy/hakios-arm64e-dada/tree/f1ae906fcc43ba8f763663257724ba938fb820ab) | `f1ae906fcc43ba8f763663257724ba938fb820ab` | XNU 12377; many fixes already imported |
| [UniXNU](https://github.com/UniXNU/UniXNU/commit/04573c510c5fd4892ca6948739389141cc9e05f5) | `04573c510c5fd4892ca6948739389141cc9e05f5` | Current commit changes device documentation; parent is local `dec111b6` |
| [ios-husky](https://github.com/nhansp/ios-husky/tree/2914ca4ed679335e79ae719b3fea42b64616459d) | `2914ca4ed679335e79ae719b3fea42b64616459d` | Newer than local `67a313ce`; current delta not fully inspected |
| [Data A Live original](https://github.com/ShueiTsuki/data-a-live/tree/db88a20f85faadc489ddc48f4371500c9b7871b6) | `db88a20f85faadc489ddc48f4371500c9b7871b6` | Archived iOS 16/Snapdragon reference |
| [Data A Live successor](https://github.com/yechenan/data-a-live/tree/6547194c4883efad2f8a42ad46e95874dd5e7576) | `6547194c4883efad2f8a42ad46e95874dd5e7576` | HEAD verified; implementation delta not inspected |
| [PixOS kernel](https://github.com/PixOS-Project/pixelios-kernel/tree/04457e5ddae2164778bd5e75c352a34dac916de9) | `04457e5ddae2164778bd5e75c352a34dac916de9` | Networking discovery helper already represented locally |
| [dodge](https://github.com/kusesad-1122/hackios-dodge/tree/fcd96b6a2311732a942b5ec72d5b12a278e3e218) | `fcd96b6a2311732a942b5ec72d5b12a278e3e218` | dada-derived OnePlus platform work; author records no phone test |
| [Old HakiOS userland](https://github.com/oosexgang/hackios-xnu-userland/blob/2573c4a8d80ed143e534d16b5a386efa5b06ccbb/README.md) | `2573c4a8d80ed143e534d16b5a386efa5b06ccbb` | README redirects work into the common kernel repository |

## 1. HakiOS WLAN registry ancestry and address publication

**Priority P1, concrete source delta, medium confidence of benefit here.**
The relevant source is
[`HakiosWLANStart`, controller classes and `publish`](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/drivers/wifi/hakios.wlan.cpp).
It supplies the `IONetworkController`/`IOEthernetController` ancestry and publishes
the real address on the `wlan` node. Its comment attributes repeated address
lookup delays to missing discovery entries. That is upstream evidence on its
port, not a measured cause of our lag.

Our `iokit/Kernel/arm/BlazerWiFiServices.cpp` already publishes the interface,
but its controller directly subclasses `IOService`, attaches at the service
root, and lacks the node address property and primary-interface property.
These differences are observable in source; their effect on our build is untested.

**Integration seam:** extend `BlazerWiFiStart` after successful real ifnet attach,
using the actual radio address already supplied to it. Preserve the single
`IONetworkStack` implementation owned by `BlazerNetServices.cpp`. This change
does not implement association, DHCP, or the Apple80211 request protocol.

**Small first task:** capture the current matching contract, then add only the
missing ancestry, parent selection and properties. Validate allocation and
publication failure cleanup, actual interface name, and absence of duplicate
metaclasses. Emit enabled BLAZER ARM64 objects and inspect class/text symbols.
Then ask the integration owner for a controlled guest comparison of interface
discovery and LaunchServices wait counts, without transmitting from the phone.

**Labour saved:** reuses a specific Darwin discovery contract instead of
rediscovering it through failed registrations. Benefit depends on having the
real interface attached; adding invented addresses before radio discovery is
not a substitute. The Wi-Fi audit owner received this finding independently.

**Licence:** HakiOS explicitly assigns `drivers/` to APSL-2.0 in its
[directory licence declaration](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/LICENSE).
Our current Blazer file has an MIT header. Any copied implementation needs
recorded provenance and appropriate notices; the existing header is not a
reason to label copied upstream material MIT.

## 2. UniXNU's complete directory enumeration across union mounts

**Priority P2, conditional reusable code; not a current missing-icons fix.**
Inspect the XNU-12377
[`getattrlistbulk` patch](https://github.com/UniXNU/UniXNU/blob/04573c510c5fd4892ca6948739389141cc9e05f5/patches/xnu-12377/native-union-getattrlistbulk.patch)
and companion
[`lookup_traverse_union` directory check](https://github.com/UniXNU/UniXNU/blob/04573c510c5fd4892ca6948739389141cc9e05f5/patches/xnu-12377/native-union-lower-directory.patch).
The first adds traversal to lower directories after upper EOF, preserves snapshot
enumeration, and checks lower-directory access and references. The companion
rejects a non-directory lower result. Both are absent from the inspected release.

**Important local constraint:** our `hkcover_mount` in
`bsd/miscfs/ramfs/varfs_seed.c` mounts replacement ramfs with mount flags zero.
It does not request `MNT_UNION`. Applying these patches alone would therefore
leave our covers unchanged. A cover can intentionally hide original files;
enabling union semantics globally could undo that isolation.

**Integration seam:** only if a future explicit overlay mode needs inherited
files, implement that mode separately and adapt both VFS patches together.
Do not reinterpret existing audio/service-hiding covers as unions.

**Small proof:** use a synthetic guest directory tree with upper-only,
lower-only, duplicate, unreadable and symlink cases; compare `getdirentries`
and `getattrlistbulk`, rewind and repeated EOF behavior. Include snapshot refusal
and vnode lifetime checks. ARM64 objects must use `CONFIG_UNION_MOUNTS=1`.

**Labour saved:** avoids reimplementing subtle EOF and vnode-reference handling
when a real union-overlay requirement arises. No current performance claim.
UniXNU declares contributions BSD-2-Clause-Patent in
[CONTRIBUTING](https://github.com/UniXNU/UniXNU/blob/04573c510c5fd4892ca6948739389141cc9e05f5/CONTRIBUTING.md)
and its [licence](https://github.com/UniXNU/UniXNU/blob/04573c510c5fd4892ca6948739389141cc9e05f5/LICENSE);
Apple XNU context and the receiving XNU files also retain their existing notices.

## 3. UniXNU CoreAnimation work-interval compatibility

**Priority P3, diagnostic reference first; low present benefit confidence.**
The XNU-12377
[`kern_work_interval_create` soft-fail patch](https://github.com/UniXNU/UniXNU/blob/04573c510c5fd4892ca6948739389141cc9e05f5/patches/xnu-12377/native-work-interval-soft-fail.patch)
extends ignored-interval handling for non-app clients and duplicate CA_CLIENT
intervals. This is an actual small compatibility patch, not a GPU driver.

Our source retains the duplicate-interval `KERN_FAILURE` return. However, the
current release's recorded compiler command for `work_interval.c` already
defines `XNU_TARGET_OS_OSX`, so its non-app soft-fail branch is already active.
Recommending the whole patch as entirely new would double-count existing behavior.

**Integration seam:** inspect duplicate CA_CLIENT refusal counts in existing
diagnostics before proposing a narrowly guarded compatibility change. No examined
capture establishes that this is our early backboardd nil-path failure.
**Small proof:** host-test flag and ownership transitions for the duplicate case,
including malformed requests and teardown; later test only the affected process
in a guest. Success may mean an explicitly ignored scheduling hint, never GPU
execution or permission to accept arbitrary unsupported calls.

**Labour saved:** provides the exact source branch to investigate if UIKit's
failure names work intervals. Otherwise defer. Licence context is as in item 2.
Our CoreAudio-only handling of operations 6–8 already exists and is narrower
than UniXNU's generic instance shim; do not replace it blindly.

## Already imported: do not repeat these projects' work

The older `research/ios26-fleet/handoffs/dada-parts.md` describes these as
missing from an earlier base. Current source/series inspection finds:

| Earlier candidate | Current local evidence |
|---|---|
| Jetsam accounting from `sane_size` | `kern_memorystatus_internal.h:281`; series `1015-0507` |
| xpcproxy identity-version preservation | `kern_exec.c:8214`; series `1017-0509` |
| Missing-persona compatibility | `spawn_validate_persona` and `spawn_persona_adopt` in `kern_exec.c` |
| Registry property tracing | `IOUserClient.cpp:3777`; series `1018-0521` |
| Exec injection/environment plumbing | `kern_exec.c:6776`; series `1022-0525`, plus current `hk_env` |
| User fault tracing | series `1011-0503-user-fault-trace.patch.patch` |
| Accelerator discovery stand-in | `iokit/Kernel/arm/sweet_services.cpp`; series `1025-0512` |
| Socket delegation compatibility | `bsd/kern/kern_priv.c:92` |
| System sleep disabled during bring-up | `IOPMrootDomain.cpp:570`, guarded platform branch |
| IONetworkStack discovery | `BlazerNetServices.cpp`, explicitly credits PixOS patch `0099` |

Dada's
[provenance notice](https://github.com/superboyyy/hakios-arm64e-dada/blob/f1ae906fcc43ba8f763663257724ba938fb820ab/NOTICE.md)
explicitly assigns its XNU-12377 patch to APSL-2.0 and tools to MIT, with
separate notices for incorporated libraries. A missing root `LICENSE` filename
does not mean this pinned dada tree is wholly unlicensed. Earlier shorthand
claiming that should not block correctly attributed, file-level reuse.

## Other leads and boundaries

- UniXNU has a real
  [XNU-12377 iPadOS profile](https://github.com/UniXNU/UniXNU/blob/04573c510c5fd4892ca6948739389141cc9e05f5/profiles/os/ipados-26.5.2-23F84/profile.toml),
  useful as a public-source dependency/ABI checklist. Its iPad identity,
  prelinked-family addresses and proprietary input assumptions are not a
  substitute for our 23G90 iPhone ABI or Tensor drivers.
- The old HakiOS userland repository is a redirect, not an independent active
  codebase to re-audit. Inspect current `userland/src/` in the common tree.
- Husky's local snapshot contains substantial Mali/Exynos GPU code, but its
  current HEAD moved and a raw README lookup returned 404. No repository licence
  was found in the inspected snapshot. Treat it as an unqualified lead; do not
  copy it or claim its newer changes were reviewed here.
- Data A Live's local source licence separates APSL kernel additions, MIT tools
  and third-party components. Its original is archived and names a successor;
  successor HEAD was verified, but no source-qualified new candidate is claimed.
  Qualcomm clock/DSP/Adreno code cannot become Tensor G5 support by renaming it.
- Dodge's own [README](https://github.com/kusesad-1122/hackios-dodge/blob/fcd96b6a2311732a942b5ec72d5b12a278e3e218/README.md)
  identifies a dada-derived platform split and no phone run. It contributes a
  useful board-boundary example, not a verified alternative iOS26 base.
- No audited project supplies a drop-in Tensor G5 kernel/peripheral stack.
  Native DXT/Metal work remains with the GPU owners; this audit does not restart
  previously rejected tasks or redirect the production route through Mesa.

Selected immutable upstream files and hashes are retained only under ignored
`research/reuse-audit-20261102/hakios/`. This report contains original summaries
and links; no upstream code, device identifiers, dumps or proprietary assets.
