# Native Metal upstream reuse

Checked 2026-11-02 against GitHub API commit identities and source files.
The local inventory contains eight repositories and 24 text source/license
snapshots, with commit, blob and SHA256 identities. Files live under ignored
`research/ios26-metal-native-20261102/upstream/`; no vendor binary is imported.

| Source and verified commit | Work we can reuse | Integration decision |
|---|---|---|
| [UniXNU/AdrenoMetal, 831a9dc](https://github.com/UniXNU/AdrenoMetal/tree/831a9dcbd6ac7de89a11bdaf031e07b9aadfa3c8) | MIT Metal frontend classes, selector coverage, resource lifetime and IOSurface bridge patterns | Metal owner assesses reuse with our HMGU backend. Existing implementation uses metal2vulkan/Turnip, so it cannot be dropped into the DXT driver unchanged. |
| [metal2vulkan AIR crate, 219f013](https://github.com/steelbrain/metal2vulkan/tree/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air) | Independent metallib/LLVM bitcode parser, typed IR, metadata, canonicalization and bounded-work machinery | AIR owner is implementing a native adapter. This crate has no Vulkan dependency; the inspected manifest lists sha2 and optional serde. License is GPL-2.0-or-later OR LGPL-3.0-or-later, inherited from the workspace; preserve notices and the chosen terms. Requires Rust 1.98. |
| [ios-tegu, 8e2d75b](https://github.com/dgigantino/ios-tegu/commit/8e2d75bb19068be7cd157da46c13b2a4cf9ac689) | New renderer memory-pressure, draw-loss and transfer-bound findings | Three commits ahead of the recorded d807098 pin; 17 changed files. No root LICENSE was available. Read for facts and compare behavior; do not copy unlicensed source into tracked code. Mali-specific GPU code is not DXT. **Compositor-branch follow-up (2026-11-04):** [tegu-compositor.md](reuse/2026-11-04/tegu-compositor.md) — the partial CA integration's seams (capability advertisement, CA's real first pipelines, MIG descriptor inputs, scatter allocation, readback acceptance) as facts for our rung-11+ design. |
| [Linux PowerVR CCB, 6628e7d](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination/pvr_ccb.c) | Imagination-authored ring reservation, return-slot waiting and firmware-message dispatch patterns | The inspected CCB/FWIF files are GPL-2.0-only OR MIT. Keep notices if adapting. This is Rogue-generation code; verify every DXT26.1 layout and opcode against the matching vendor headers. |
| [UniXNU/Adreno740, a9a2cbb](https://github.com/UniXNU/Adreno740/tree/a9a2cbb43b89d672e2921e19721a6438b738b17f) | MIT XNU GPU driver organization, task/resource ownership and submission patterns | Useful kernel integration reference. Its A740/SM8550 hardware programming cannot drive Tensor G5. |
| [ios-flame, 745c434](https://github.com/NWylynko/ios-flame/tree/745c4341af86089efb0df851fa8a27fb8face624) | Metal integration notes, device diagnostics and dependency/provenance inventory | Inspect file origins in CREDITS before reuse; its GPU is Adreno and its current Metal route includes Vulkan/Mesa. |
| [ios-sweet, 45263be](https://github.com/dipa-studio/ios-sweet/tree/45263bee51df4a0f55cdf9c649af886399488ddb) | MIT-origin IOSurface/framebuffer protocol and XNU userland integration work | Check per-file Apple/vendor origins and iOS version before adapting. No hardware register transplant. |
| [GrapheneOS kernel manifest, fae63ef](https://github.com/GrapheneOS/kernel_manifest-6.18/blob/fae63ef0c2a745e2d7b798f76e3269e9859e0366/default.xml) | Current source routing and build dependency references | A source-discovery reference, not a verified Pixel10 DXT firmware ABI. The assumed GitHub kernel_pixel_6.12 repository returned404; do not invent that URL or replace our matching vendor pin blindly. |

The highest-value immediate work is reusing the AIR parser and applicable Metal
frontend code while retaining our native PowerVR kernel/compiler/stream path.
No repository in this review establishes a drop-in native DXT Metal driver.
No source is merged merely because a repository is newer.

Read the parallel [PowerVR kernel audit](reuse/2026-11-02/powervr-kernel.md),
[compiler audit](reuse/2026-11-02/powervr-compiler.md) and
[Metal runtime audit](reuse/2026-11-02/metal-runtime.md) before another import.
They identify the already-local Pixel26.1 donor as the closest hardware source,
including exact `rgxmem.c` memory-context, `rgxfwutils.c` invalidation and
`rgxcompute.c` context/submission seams. The compiler audit pins independent
Volcanic packet-generator references; its Rogue/DXT mismatch findings prevent
an incompatible compiler transplant. Tegu is private: our authenticated GitHub
API check resolves its head above, while the earlier audit used public access
and received404. Keep its source private and distinguish access from licensing.

## Keep the fleet current

Run `python3 -I tools/native_gpu_upstream.py` when reviewing a milestone or
before adopting a dependency. It pins each selected branch's current commit,
records changed heads against the previous successful inventory and saves
immutable text snapshots. A failed refresh preserves the previous usable index.
It performs no merges, build changes, firmware downloads or device operations.

For each proposed adoption, the owner records repository/commit, exact files,
license, target architecture/ABI, changed behavior and tests. Parent reviews the
diff and reruns relevant checks before integration. Compare protocol layouts,
not just matching symbol names. Preserve known-good source pins for rollback.

Active ownership and terminal history are in local `fleet.json` and `FLEET.md`.
Completed validation, AIR and ISA first milestones have successor implementation
tasks; the target remains ten concurrent owners. Delegate completion events
drive replacement; do not poll running delegates.

The firmware milestone adds one versioned profile under
`firmware/profile/lga26.1-abi41-v1.json`, consolidating existing firmware,
queue and VM measurements with exact donor/configuration hashes. Firmware
builds check it before compiling; parent independently reproduced its checks
and vendor layout output. Queue's agreement header checks shared constants.
Runtime ABI compatibility and cross-adapter adoption remain unfinished.
Use these existing artifacts for composition rather than another constant set.
The post-milestone eight-repository refresh found no changed heads; all24 saved
source/licence files were rehashed successfully.

`tools/native_gpu_upstream.py` is original hackios code under its per-file MIT
notice. Third-party snapshots retain their own licenses and remain out of git.
