# PowerVR DXT compiler and command-stream reuse audit

Research only, 2026-11-02. No implementation change, build, guest, phone command,
firmware operation or runtime performance measurement was performed for this audit.
The native non-Mesa production route remains the project target.

## Findings that affect the plan

1. Reuse licensed Volcanic packet definitions as an independent host oracle.
   They can replace repeated manual CDM field transcription, but do not provide
   a complete DXT USC compiler or all required PDS launch fields.
2. Use an existing typed AIR reader rather than keep expanding a handwritten
   LLVM-text grammar. The separate [Metal runtime audit](metal-runtime.md)
   investigates `metal2vulkan`; LLVM's native reader is another concrete option.
3. Recover the newer local original MIT ISA emitter before starting another.
   The old `gpucc/rogue_enc.py` and current Mesa PCO/PDSc have incompatible
   instruction layouts; a BVNC substitution cannot make them DXT encoders.

## Verified source pins and evidence

| Source | Verified reference | Scope and licence |
|---|---|---|
| Mesa upstream | `bd830ce2eead03d775486234902fe22215e334b8` | GitLab commit API and pinned raw source; examined Imagination files carry MIT notices |
| LLVM upstream | `f4009f12358d5fff9ef6413b675df4bd240afedb` | Exact `HEAD` advertisement and pinned raw headers/implementation; Apache-2.0 WITH LLVM-exception |
| YuAo/MetalLibraryArchive | `de573ba4a7b986bbecb3e4ce2464945d266a28e9` | Exact `HEAD` advertisement, Archive.swift, Package.swift and MIT licence |
| Khronos SPIRV-LLVM-Translator | `06db465fc87a0d926b2307d27f6ee0730dc6e1c9` | Exact `HEAD` advertisement, README, writer and University of Illinois/NCSA licence |

Only the exact `HEAD` ref was used for the GitHub pins: LLVM's advertisement also
contains an unrelated remote-tracking ref whose hash must not be mistaken for HEAD.
Downloaded public source snapshots are under ignored
`research/reuse-audit-20261102/powervr-compiler/`.

The local `research/ios26-mesa-r1/work/mesa/` is an unpacked source directory,
not a Git checkout. `git -C` there walks up to hackios and returns **our** commit.
That command is not valid Mesa provenance; record snapshot receipts or an upstream pin.

## P1: MIT packet schemas and generator, bounded reference reuse

Exact upstream files:

- [Volcanic CDM schema](https://gitlab.freedesktop.org/mesa/mesa/-/blob/bd830ce2eead03d775486234902fe22215e334b8/src/imagination/csbgen/volcanic/cdm.xml)
- [Volcanic PDS payload schema](https://gitlab.freedesktop.org/mesa/mesa/-/blob/bd830ce2eead03d775486234902fe22215e334b8/src/imagination/csbgen/volcanic/pds.xml)
- [gen_pack_header.py](https://gitlab.freedesktop.org/mesa/mesa/-/blob/bd830ce2eead03d775486234902fe22215e334b8/src/imagination/csbgen/gen_pack_header.py)
- [pvr_packet_helpers.h](https://gitlab.freedesktop.org/mesa/mesa/-/blob/bd830ce2eead03d775486234902fe22215e334b8/src/imagination/csbgen/pvr_packet_helpers.h)

The CDM schema specifies packet types, KERNEL0 resource fields, code/data address
alignment, direct/indirect workgroup records, KERNEL9 local dimensions and a
64-byte guard. The generator produces C structures and packing/unpacking helpers.
Both schemas are MIT; generator/helper carry permissive notices attributed to
Imagination and their Intel/Broadcom antecedents. Preserve all applicable notices.

Current counterpart: `research/ios26-metal-native-20261102/streams/src/hm_streams.c`
already has independent `hms_cdm_direct_*`, `hms_pds_*` and transactional compute
builders. Its messages explicitly identify these Volcanic definitions as evidence.
This is **already partly used**, not a newly discovered complete stream implementation.

Integration-sized task: pin the upstream generator and CDM schema in an isolated
host fixture, generate the narrow CDM pack/unpack oracle and compare all supported
`hms_cdm_direct_encode/decode` fields at their boundaries. Keep the generated
reference out of the native runtime; use own synthetic descriptors and refuse
unsupported nonzero fields. An independent generator catches common transcription
mistakes more effectively than a second test that repeats the runtime masks.

Important limits: CDM KERNEL8 defines only bits25..31; the local DXT71 stock-format
observations identify additional low fields. The public schema does not establish
those fields as reserved or zero in every dispatch mode. Volcanic `pds.xml` has
DOUTD and DOUTI payload records, but no DOUTU launch encoding or full PDS ISA.
The existing first profile's zero/common-store restrictions must remain explicit.
Packet helpers use assertions for some range checks; they are not a replacement
for the native builder's always-on validation or BO/heap authority checks.

Confidence: high for replacing repetitive field transcription and generating
host checks; medium for applicability beyond the already calibrated DXT subset.
No shader validity or execution follows from successful packing.

## P1/P2: existing AIR readers instead of extending text parsing

The more immediately relevant external AIR project is assessed in the
[Metal runtime report](metal-runtime.md), including its copyleft licence boundary.
Do not introduce two competing parser replacements without comparing that work.

LLVM offers a fully specified parser independent of a GPU backend:

- [IR reader C API](https://github.com/llvm/llvm-project/blob/f4009f12358d5fff9ef6413b675df4bd240afedb/llvm/include/llvm-c/IRReader.h)
- [Bitcode reader C API](https://github.com/llvm/llvm-project/blob/f4009f12358d5fff9ef6413b675df4bd240afedb/llvm/include/llvm-c/BitReader.h)
- [parseIR implementation](https://github.com/llvm/llvm-project/blob/f4009f12358d5fff9ef6413b675df4bd240afedb/llvm/lib/IRReader/IRReader.cpp)
- [LLVM licence](https://github.com/llvm/llvm-project/blob/f4009f12358d5fff9ef6413b675df4bd240afedb/llvm/LICENSE.TXT)

`parseIR` handles LLVM text or bitcode; C bindings provide context-specific
parsing with diagnostic errors. A typed module visitor can preserve exact LLVM
types, operand identity, attributes and metadata before translating to our IR.
This removes grammar, quoted-name and multiline-metadata maintenance from hackios.
It does **not** implement AIR intrinsics, Metal resource layout or DXT codegen.

Current counterpart: newer `air/airfront/metallib.py` already invokes installed
`llvm-dis`, then `airfront/frontend.py` parses the text into the narrow scalar IR.
The older `gpucc/llfront.py` contains a larger hand-built type/metadata grammar.
Thus LLVM bitcode reading is already reused; the remaining candidate is typed
module traversal instead of custom text parsing. Do not count llvm-dis as new reuse.

Smallest host proof: build a separate reader adapter around the **installed**
LLVM version; enumerate types, def/use, metadata and FP flags for our owned
`single_add` and `buffer_add` outputs and compare with scalar IR. Include malformed
input and unsupported AIR modes. Keep the existing refusal contract. Do not
optimize or normalize unknown AIR intrinsics before their semantics are handled.

Pin the installed LLVM ABI separately: source HEAD's `LLVMParseIRInContext2`
does not establish that symbol exists in installed LLVM23. No new full LLVM build
or on-phone LLVM dependency is necessary for a host-only proof. Native runtime
packaging, library size and bitcode-version compatibility remain separate decisions.
Confidence: high for reducing parser labour, medium for integration value compared
with the standalone AIR frontend from the other audit.

## P2: MetalLibraryArchive as independent container oracle, already referenced

[Archive.swift](https://github.com/YuAo/MetalLibraryArchive/blob/de573ba4a7b986bbecb3e4ce2464945d266a28e9/Sources/MetalLibraryArchive/Archive.swift)
implements `Archive.init(data:)`, function-tag scanning, bitcode slicing and
per-function hash comparison. [Package.swift](https://github.com/YuAo/MetalLibraryArchive/blob/de573ba4a7b986bbecb3e4ce2464945d266a28e9/Package.swift)
shows the Swift dependency boundary; the [licence](https://github.com/YuAo/MetalLibraryArchive/blob/de573ba4a7b986bbecb3e4ce2464945d266a28e9/LICENSE)
is MIT. This is directly reusable host-side Swift source.

Current `air/PROVENANCE.md` already cites its layout; our Python reader is original.
Add a separate host extractor and compare names, stage tags, slice sizes and hashes
for **owned freshly compiled** libraries. This gives useful independent format
coverage without replacing our stricter supported-library profile. Do not import
the upstream test bundle's shader outputs into tracked files without review.

The upstream SHA check is conditional on `canImport(Crypto)`. Package.swift adds
swift-crypto in the normal build but removes it for its WASM configuration.
Ensure the oracle actually verifies hashes; a parser that returns data is not
automatically an integrity oracle. This saves container-debugging labour, not
the missing DXT ISA, register, synchronization or Metal-driver implementation.

## High-confidence dead ends: avoid restarting incompatible work

- **Mesa PCO is not a DXT USC backend.** Its MIT
  [pco_isa.py](https://gitlab.freedesktop.org/mesa/mesa/-/blob/bd830ce2eead03d775486234902fe22215e334b8/src/imagination/pco/pco_isa.py)
  defines byte-oriented Rogue instruction-group headers. The current
  [Vulkan build](https://gitlab.freedesktop.org/mesa/mesa/-/blob/bd830ce2eead03d775486234902fe22215e334b8/src/imagination/vulkan/meson.build)
  instantiates only `rogue`. Neither the old local Rogue encoder nor PCO should
  emit executable DXT71 stages by renaming its target. NIR/allocator infrastructure
  can inform a future compiler design, but substantial DXT legalization remains.
- **New Mesa PDSc also contains incompatible launch fields.** Its MIT
  [pdsc_isa_pack.h](https://gitlab.freedesktop.org/mesa/mesa/-/blob/bd830ce2eead03d775486234902fe22215e334b8/src/imagination/pdsc/pdsc_isa_pack.h)
  `pdsc_doutu_src0_pack` uses byte `exe_off` bits0..31 and ceil(temps/4) bits35..40.
  Our calibrated DXT streams use relative byte offset/4 in bits0..29 and
  ceil(temps/2) in bits33..39; DOUT register-source positions differ too. Some
  conceptual resource names transfer; these bit patterns do not.
- **SPIRV-LLVM-Translator is not an AIR or graphics frontend.** The pinned
  [README](https://github.com/KhronosGroup/SPIRV-LLVM-Translator/blob/06db465fc87a0d926b2307d27f6ee0730dc6e1c9/README.md)
  restricts its SPIR-V to OpenCL Kernel capability. It cannot by itself preserve
  AIR resource semantics or supply a DXT backend. A generic LLVM→SPIR-V→GPU route
  adds conversions and still needs the missing compiler/driver.
- Imagination's [public ISR scope](https://docs.imgtec.com/reference-manuals/powervr-instruction-set-reference/html/topics/general-architecture-information.html)
  primarily covers Series6XT; it is architecture background, not DXT encoding proof.
  Its [profiling compiler guide](https://docs.imgtec.com/performance-guides/graphics-recommendations/html/topics/pvrshadereditor.html)
  lists Rogue and Volcanic B/C offline tools behind a developer account, without
  establishing DXT71 support or a source-reuse grant. Treat these as leads for
  legitimate supported tooling, not an available redistributable compiler.

## Existing local work to preserve and compose

Read `isa/src/dxtisa.py`, `isa/notes/{ENCODINGS,PROVENANCE}.md`,
`isa/messages.md`, `streams/include/hm_streams.h` and `air/SCALAR-IR.md` under
`research/ios26-metal-native-20261102/` before assigning another compiler task.
They contain original MIT variable FOP/DMA/CTRL emitters, linear-scan ALU allocation,
explicit scalar IR and a bounded stream builder; the old gpucc handoff predates them.
The existing owner's recorded codec checks are host evidence, not tests rerun here.

The concrete missing composition is a proved pointer-input convention, DMA
address/operand meaning, END/fence rules, resource metadata and complete-stage
validator. Codec roundtrips and HMUSC1 container validity do not discharge those
requirements. No examined public project supplied a complete licensed DXT71 USC
backend; claiming otherwise would hide rather than remove the main manual work.
