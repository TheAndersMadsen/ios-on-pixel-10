<!-- SPDX-License-Identifier: MIT -->
# Source and license boundary

`SOURCE-INVENTORY.json` maps imported files to exact original paths/hashes and
identifies every textual transformation. `LICENSE-MANIFEST.json` maps those
origins to their complete scoped notices. This import includes only original
MIT C/header/test/documentation/build code and original MIT LLVM fixture text.
No Apple source/SDK file, unlicensed tegu context, binary shader/template,
vendor helper/cache, firmware, device dump or compiled artifact is payload.

ISA-r2 memory, ISA-r3 ALU/control/allocator/AIR composition and ISA-r4 raw/body
analysis are copied intact. The earlier original MIT encoding measurements
are their evidence; proprietary codec/converter implementations and answers
are not imported. Frozen `notes/SEMANTICS.md` and `notes/CONSTRAINTS.md` retain
the original limits and explicitly non-executable proof obligations.

Streams/r2/r3 construction, decoding and validation/queue callback seams retain
their original full notices, including Imagination's protocol-definition MIT
notice. No Mesa source, generated vendor schema header or proprietary PDS/USC
program is included. Their positive format/roundtrip results do not establish
stage termination, ordering, launch mapping, engine execution or handback.

The six `tests/fixtures/*.ll` text files originate in the original MIT
AIR-r2 `tests/prepare.py` outputs. The import prepends an explicit MIT notice;
`single_add.ll` additionally renames `@test` to `@air_single_add`. They are
hand-authored test grammar/source, not Apple LLVM disassembly. `chain.ll` and
`multi.ll` are unchanged original ISA-r3/r4 source. The test C bodies are
unchanged; the documented raw-bitcode fixture substitution is intentional.

CMake, this provenance text, README and machine-readable manifests are
original 2026 hackios contributors MIT work under `LICENSE`. CMake resolves
include paths through caller-supplied HACKIOS_ROOT and a build-only subset of
symlinks to pinned original headers. No alternative wire header is authored.

The AIR frontend implementation is not part of the import. AIR-r4 retains
metal2vulkan-air0.2.0 at219f01365dc4c8eb346816c405b5b17403793764, licensed
GPL-2.0-or-later OR LGPL-3.0-or-later, with LGPL-3.0-or-later selected there.
Its notices, exact corresponding source archive/source lock, locked Rust
sources and replacement/relinking materials remain in that sole assembly.
The host/iOS frontend library hashes are external dependency pins, not MIT
payload or a license grant over those libraries. No parser is rebuilt/copied.

The canonical HMGU/HMUSC1 and queue measured headers remain external at their
unchanged owner paths. The import makes no new licensing claim about those
files and does not ship them. The parent must preserve their shared identity
and review any later promotion/location change separately. Likewise the root
repository's broader mixed licensing is not altered by these scoped notices.
