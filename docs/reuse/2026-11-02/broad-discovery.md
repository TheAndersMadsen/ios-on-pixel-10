# Additional reusable tools and format code

Audit date: 2026-11-02. Source inspection only; no build, deployment, device
command, firmware download, implementation change or new performance result.
Current physical GPU health acceptance failed in attempt
`20261102-102719-native-metal-health-p29-r1`; these tools do not change that.

This audit concentrated on resources missing from the earlier `reuse.md` and
`perfreuse.md` handoffs. Existing native Metal, sampler, asset and storage
workers already own their implementations. The useful additions are independent
oracles and reusable host tooling, rather than another parallel driver stack.

| Candidate | Reuse class | Priority | Confidence and labour saved |
|---|---|---|---|
| Arm astcenc decompressor | Callable licensed codec; host oracle first | P1 if ASTC demand is observed | High source confidence; avoids writing and debugging a complex texture decoder |
| Coccinelle | Existing host matcher/transformation engine | P2 | High tool confidence; project rule coverage still needs a pilot; reduces repeated hand review of the same C patterns |
| FSFE REUSE | Existing host provenance checker | P2 for new imports | High source confidence; avoids bespoke SPDX parsing and repeated notice inventory |
| Kaitai schemas | Declarative parser/oracle | P2 for wire formats; P3 for existing GPT | High format-source confidence; current strict storage parser is already more suitable for acceptance |

## 1. Arm ASTC decoder: independent oracle before a runtime import

Verified the official repository's current HEAD as
`d0f91386350222fcbf6da533c0f7a3f9b5c6b783`, and stable tag `5.5.0` as
`27270637eb14e997baaa94a82a8839bae6f8f914`, using `git ls-remote`.
Pin the stable tag for an experiment, rather than silently following HEAD.

Actual source inspected:

- [Public codec API, astcenc.h](https://github.com/ARM-software/astc-encoder/blob/27270637eb14e997baaa94a82a8839bae6f8f914/Source/astcenc.h): `astcenc_config_init`,
  `astcenc_context_alloc`, `astcenc_decompress_image`, reset/free; explicit sized
  buffers and LDR, sRGB and HDR profiles.
- [Build definitions](https://github.com/ARM-software/astc-encoder/blob/27270637eb14e997baaa94a82a8839bae6f8f914/Source/cmake_core.cmake):
  `ASTCENC_DECOMPRESSOR` enables `ASTCENC_DECOMPRESS_ONLY`; scalar and NEON
  configurations exist; this is a C++14 library, not a single C decoder.
- [Decoder](https://github.com/ARM-software/astc-encoder/blob/27270637eb14e997baaa94a82a8839bae6f8f914/Source/astcenc_decompress_symbolic.cpp):
  `decompress_symbolic_block` handles actual ASTC blocks, including error blocks
  and constant-color modes.
- [Licence](https://github.com/ARM-software/astc-encoder/blob/27270637eb14e997baaa94a82a8839bae6f8f914/LICENSE.txt): Apache-2.0;
  inspected source/build files carry matching SPDX notices.

**Local overlap:** `research/ios26-gpushell-r1/bundle/HMetal.m` already has
`HakiosMetalTextureLayout`, ASTCTwiddler-facing tight block layout, and compressed
buffer upload handling. A layout/upload path alone does not establish a working
ASTC sampler. The Tegu audit found a smaller explicitly MIT-licensed ASTC LDR
decoder; use Arm's implementation as its independent oracle, not a duplicate
replacement project. Missing icons have not been traced to ASTC in this audit.

**First task:** add an offline differential fixture to the existing texture
worker: owned constant-color and nonconstant blocks, several block sizes,
partial edge dimensions, alpha and sRGB profile. Decode with Arm's library and
the proposed compact decoder, normalize RGBA/BGRA explicitly, and compare
pixels plus guard regions. Retain invalid-block cases as policy checks, with
profile-dependent error colours accounted for.

If runtime use becomes warranted, wrap the decompression-only API at the
existing texture upload boundary and cache decoded levels. Its memory input is
tightly packed; a Metal row pitch/mipmap/slice adapter is still required. The
caller owns threads, CPU ISA selection and synchronization. Do not enable
`ASTCENC_FLG_SELF_DECOMPRESS_ONLY` for arbitrary assets: that assumes the same
encoder configuration. No phone speed or missing-icon improvement is claimed.

## 2. Coccinelle: reuse a semantic matcher for repetitive porting checks

Verified current official HEAD
`11b93adb6516a358a6687051e5762136666626e0` with `git ls-remote`.
The [README](https://github.com/coccinelle/coccinelle/blob/11b93adb6516a358a6687051e5762136666626e0/readme.txt)
documents `spatch --sp-file`; the actual
[minimal rule](https://github.com/coccinelle/coccinelle/blob/11b93adb6516a358a6687051e5762136666626e0/demos/simple.cocci)
matches a call expression and changes its argument list. This is more precise
than replacing source strings. The
[official documentation](https://coccinelle.gitlabpages.inria.fr/website/)
describes C API evolution and bug matching; C++ support remains partial.

The tool's [licence text](https://github.com/coccinelle/coccinelle/blob/11b93adb6516a358a6687051e5762136666626e0/license.txt)
is GPLv2. Use it as an external host program; do not copy its implementation or
unreviewed Linux semantic rules into the kernel. Original project-specific
rules can operate on the existing locally licensed source.

**Local seam:** the native GPU VM/surface workers already distinguish failed
`complete()` from successful cleanup. For example,
`vm/src/hmg_vm_xnu.cpp:xb_release` preserves its descriptor after a failed
`complete(kIODirectionInOut)`. Similar rules recur across owned buffers,
imports, submissions and stop paths. Existing model tests remain essential;
a syntax matcher cannot prove DMA quiescence or alias/lifetime correctness.

**First task:** pilot report-only matching over a small set of C helpers,
flagging discarded return values from designated cleanup/retirement APIs and
old API call shapes. Seed one positive and one negative fixture for each rule,
including macro/preprocessor cases. Require full parse coverage or explicit
unsupported-file reporting; start with C before XNU C++/Objective-C. Do not
enable automatic rewrites initially. Add a reviewed rule only when it catches
a recurring real error. This can reduce repeated review and rebase labour;
it does not replace gate-on ARM64 object/symbol verification.

## 3. FSFE REUSE: source import receipts without a custom licence parser

Verified canonical Codeberg and its GitHub mirror both resolve HEAD to
`0113a6258fd09a06a33f3e17cbba88acfde173d7`.
The actual [lint implementation](https://github.com/fsfe/reuse-tool/blob/0113a6258fd09a06a33f3e17cbba88acfde173d7/src/reuse/lint.py)
provides `format_json` and reports missing notices, invalid SPDX expressions
and missing licence texts. It carries GPL-3.0-or-later; keep this an external
host tool. The [CLI documentation](https://github.com/fsfe/reuse-tool/blob/0113a6258fd09a06a33f3e17cbba88acfde173d7/README.md)
includes `lint-file` and `spdx`, so adoption need not impose a whole-repository
relicensing exercise. Its
[REUSE.toml](https://github.com/fsfe/reuse-tool/blob/0113a6258fd09a06a33f3e17cbba88acfde173d7/REUSE.toml)
is a CC0 example of per-path annotation and precedence.

**Local seam:** `.github/scripts/check_tracked.py` correctly blocks artifacts
and device identifiers; `docs/LICENSING.md` manually records mixed provenance.
Neither supplies structured per-import copyright/licence validation. Preserve
the existing artifact scanner; these are different checks.

**First task:** run a pinned REUSE version on a small staging directory holding
only a newly selected permissive upstream component and its preserved notices.
Store the source URL, commit, file hash, licence and reviewer decision beside
the import receipt. Export a local SPDX inventory; test that removing a notice
or licence text fails the pilot. Do not invent annotations to make old
unlicensed code pass. Lint validates recorded declarations, not authorship,
permission, compatibility or the correctness of a source's licence claim.

No tool installation or lint invocation was performed in this audit. This is
useful before promoting vendor MMU/panel/decoder code and prevents the same
manual notice inventory from being repeated by each future agent.

## 4. Kaitai: use schemas as independent readers, with strict limits

Verified `kaitai_struct_formats` HEAD
`7d175667527372eb0c521045c1dac212230d9779`.
The inspected [GPT schema](https://github.com/kaitai-io/kaitai_struct_formats/blob/7d175667527372eb0c521045c1dac212230d9779/filesystem/gpt_partition_table.ksy)
is CC0-1.0. It parses both headers and entry arrays, but hardcodes 512-byte
sectors and merely reads CRC fields; it does not validate their checksums.
It cannot replace `tools/dualboot.py`, whose current parser uses 4096-byte
blocks, CRC checks, reciprocal geometry, bounded arrays and overlap rejection.

The [Mach-O schema](https://github.com/kaitai-io/kaitai_struct_formats/blob/7d175667527372eb0c521045c1dac212230d9779/executable/mach_o.ksy)
is MIT and includes arm64/load-command descriptions. Its load-command enum
stops short of modern chained-fixup commands; this is not a complete iOS26
shared-cache loader or symbolicator. The Qualcomm bootloader schema in the
same repository explicitly targets older Snapdragon formats, not this Pixel.

The [Python runtime](https://github.com/kaitai-io/kaitai_struct_python_runtime/blob/314544c9d8a2bf0c86e0875b5159d70468a8f466/LICENSE)
is MIT at verified HEAD `314544c9d8a2bf0c86e0875b5159d70468a8f466`.
The compiler is a GPLv3+ host tool; keep compiler, format and runtime licensing
distinct. See the [official licence summary](https://kaitai.io/).

**First task:** if repeated wire parsing is becoming costly, write an original
bounded schema for the project's HMGU/HMUSC1 envelope and generate an independent
host reader. Cross-check existing C/Python decoders against owned malformed,
unaligned and truncated fixtures. Preserve explicit acceptance policy outside
the schema. For GPT, only use a parameterized 4096-byte adaptation on synthetic
offline images as a structural cross-check; do not weaken the current verifier.

## Leads deliberately not counted as new savings

Metal2Vulkan AIR parsing, Mesa packet XML, exact Google vendor MMU/panel code,
ipsw symbolication and licensed HakiOS adapters have dedicated audit owners.
Repeating their work would add no value. Another generic GPU/Vulkan project
cannot make DXT execution work without the current native kernel/compiler
dependencies. No accessible public project was verified here as a complete
native Tensor G5 iOS26 driver stack.
