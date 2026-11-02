<!-- SPDX-License-Identifier: MIT -->
# Implemented facts, API mapping and unresolved semantics

The raw decoder and complete-body analysis execute real supported code paths.
Their success means byte structure and the stated symbolic constraints pass.
It does not mean the program is executable or the GPU performed arithmetic.

## Independent raw bytes

hm_isa_raw.c imports no encoder, descriptor builder or inverse. Actual ARM64
`nm -u` confirms only stack-protector imports. Every loaded word is checked by
an explicit fixed-bit mask. FOP extensions have measured omitted defaults and
minimal1/2/3-word length; final bits must be in the last consumed word. CTRL
NOP/END consumes1/2 words with nonzero DESCHED extension only on NOP. DMA is
exactly4 words, including its absent ROBUST form and final flag. Unaligned input
is supported. Prefix decoding reports exactly the consumed group length.

FOP operand banks are the measured HWTEMP forms; incompatible banks, negation
other than logical SUB, modifiers, unknown opcode/classes and reserved bits
refuse. SUB recovers logical lhs/rhs rather than confusing negated SRC0 for lhs.
DMA distinguishes banks4/5/7, even canonical SH pointer indices and data regs.
It returns all encoded X/Y/stride/ADD-FIRST and both issue/wait namespaces. The
program analyzer accepts only scalar X4/Y1 with offset0 or aligned4..2044,
ordinary stride1 for no ADD-FIRST, and established absent-ROBUST forms.
Wider/zero-dimensional raw encoding facts do not imply memory semantics.

Stock pure codec calibration uses355 saved whole records. The new decoder
matches944 pinned independently recorded complete byte/56-word answers;48 new
raw DMA boundary groups and fresh32 normal LD/ST +36 END/NOP conversions also
match. Every bit of17 representative groups is flipped: of1440 single-bit
tests535 accepted changes agree with the entire independent descriptor,905
refuse. Every truncated prefix of those representatives refuses transactionally;
unaligned variants pass. These are group encoding tests, not whole-source proof.

## Whole-program analysis

Analysis consumes the EXACT supplied byte length. It does not stop at a prefix,
trust the producer's fragment kinds, ignore an unknown trailing group, or approve
unparsed tail. A present END must be the final group; duplicate END, NOP or
zero bytes afterward refuse. A body without END is a useful analyzed product
and has MISSING_END set. This is an explicit boundary, not a safe-fetch claim.

Each LOAD defines a register but leaves a pending write in its actual fence
slot. FOP reads must be defined and free of pending writes; FOP destinations
must be free of pending reads/writes and distinct from that instruction's
sources. x*x/x+x source alias is supported. Asynchronous FOP/STORE source reads
retain registers until their slot is explicitly waited, preventing premature
register overwrite even after SSA last-use. Waits are applied before the same
instruction's uses/defs/issue; same-slot DESCHED reuse after a matching wait is
supported. Issue reuse while active, wrong-namespace dependency, NONE issue in
the program profile, or pending work at body/END boundary refuses.

The slot model records known compiler dependency masks. Clearing a structural
slot is NOT an observed GPU retirement, visibility or task-release event.
The exact normal converters establish separate SYNC/DESCHED namespaces, not
that issuing/waiting a STORE establishes external memory visibility at END.

Memory instructions remain ordered: no second DMA while a previous DMA has an
outstanding dependency. Distinct symbolic bindings do not prove actual VA
nonaliasing. Waited accesses may read/write overlapping ranges in source order;
the actual aliased output test preserves this order. No unsupported generic
pointer provenance is assumed: temp-held addresses decode raw but refuse in
program analysis. Bank5 is its own canonical operand range, with no SH/PDS word
pair mapping inferred. Its high-water is reported separately from shared words.
The field is deliberately named input_index_high_water: it counts canonical
bank5 operand indices, NOT established 32-bit launch/input allocation words.

Resource facts are max consumed register+1 (not a guessed available budget),
unified0, exact SH pointer-pair read mask/high-water, distinct input high-water,
every access's code offset/group/binding/bank/index, byte displacement, and
buffer-relative half-open begin/end. All pointer extent, 64-bit overflow,
access rights, duplicate binding and overlapping canonical assignment checks
run on actual decoded instructions. Explicit caller limits are constraints,
not hardware capacity or launch authorization. SH510/511 and temp255 boundary
tests exercise real high bits; three-buffer AIR uses SH0..5/mask63 and separate
read/read/write authorities. The initial single-pointer route uses SH0/1/mask3.

## Layout and real native composition

hmisa_stage_link copies only each fragment's actual decoded canonical length
into one contiguous body, records exact byte offsets/AIR indices and zeroes
unused output storage. It independently analyzes the entire new body. It then
checks memory sidecars/binding/span/data register, each defining value's assigned
register and actual high-water against the allocator. A source hash or resource
metadata does not bypass any byte analysis. Tampered spans, registers, lengths,
waits, reserved bits and allocator count fail without modifying output.

hmisa_air_link calls the ACTUAL hmisa_air_prepare and allocator/memory/FOP APIs.
It preserves exact hm_air_info_t source/FP metadata unchanged. The AIR parser
input can be overwritten/freed before compilation. Original new multi.ll adds
a three-buffer read/read/write FSUB plan, with distinct initialized SH pairs
and accesses[4,8),[8,12),[12,16). It runs through the actual Rust parser and C
pipeline; no synthetic typed-plan accessor or parser stub is used. LLVM assembly
of this fixture is host test preparation only, not a runtime subprocess.

## Existing streams-r3 bridge / AIR-r4 adoption

No second frozen resource/queue bridge, wire ABI, collector, profile, parser,
factory or order harness is added. Add our header and three sources to the
SAME native userspace assembly. AIR-r3's compute hm_air.h is byte-identical to
the consumed AIR-r2 API, but these exact receipts use the pinned AIR-r2 dylibs.
Adopt intentionally into AIR-r4's existing hmna preparatory body/resource path;
keep its ownership/provenance and library identities. It must still expose
nonzero obligations and keep ready/compile_plan uninstalled.

Future authentic hmsr_verify_stage_fn must decode the actual uploaded USC span
from hmsr_frozen_resources and ALL code/tail consumed under the established
complete-stage policy, against the same pinned/frozen BO set. For the existing
narrow shared route, these structural fields map to hmsr_stage_usage:

| Existing bridge field | New raw fact |
| --- | --- |
| code_bytes | facts.code_bytes ONLY after complete termination/tail policy, never body length as approval |
| temps/unified_words/shared_words | facts.temps/unified_words/shared_words |
| shared_read_mask | facts.shared_read_mask[0], with all upper words0, input_index_high_water0 and initial route only SH0/1 |
| accesses[i].shared_word/access | facts.accesses[i].index/access, require bank7 |
| accesses[i].offset | facts.accesses[i].displacement, NOT begin_byte (origin may be nonzero) |
| accesses[i].bytes | end_byte - begin_byte =4 in the supported profile |

The bridge already resolves actual SH pointer values to the same BOs, rejects
code/control/PDS/stream/padding aliases, checks authority/closure and rounded
resource allocations. Do not duplicate or replace that logic with caller
symbolic pointer assertions. Common-init-before-main visibility, shared lifetime
through END and safe terminal release remain its separate verify_order seam.
Do not install an analysis-success adapter as verify_stage or verify_order.

## Proof obligations and next positive constraints

Successful analysis ALWAYS computes obligations31; bodies add MISSING_END32
(total63). No caller bool/hash/marker can clear them. Required facts are:

1. Complete STORE/END task retirement, including what the final dependency and
   shared allocation release mean. END's known SYNC mask alone is insufficient.
2. Safe tail/prefetch extent/alignment and interpretation of previously saved
   extra END. Named label-alignment NOP emission is not a universal tail rule.
3. Exact FP denorm/RNE/noncontraction environment for these operations and AIR
   modes. Opaque copied metadata and CPU arithmetic do not establish this.
4. Real HWTEMP/unified/SH-to-launch allocation mapping/capacity for the target
   kernel/firmware build and actual initialized shared padding.
5. Common-init visibility/lifetime AND terminal shared release, per SAME profile
   and streams, independently of engine completion/cache/UPL handback.

No full-output authorization API exists until these are genuinely established.
No END/padding policy is guessed. Real positive body production is available
now despite those distinct dependencies. Parent's existing five-OWN compile
CPIO2a1654e5 is the next source-bound reference input; no duplicate batch or
guest is run here. Old compute.log names /h/c.spv but does not bind a captured
source SHA to the compiler output; it is insufficient for these proofs. The
944 saved groups are explicitly instruction codec evidence, not source-bound
full shader records. Reference user-mode26.1@7036548 differs donor6967606;
matching bytes/resource size/PDS bits are NOT exact-build semantic evidence.

## Runtime and device separation

New compiler source is unguarded userspace C. Actual ARM64 T symbols and strict
real AIR dylib/consumer linking establish implementation compilation; syntax-
only/empty-TU checks are not used. No guarded XNU file is changed/tested, so no
new BLAZER feature gate applies. Host C code/tests carry ASan/UBSan; peer Rust
dylib is not rebuilt with sanitizer instrumentation. detect_leaks=0 is explicit.

System QEMU: no run. Physical: no attempt/capture/performance claim. HEALTH5
remains FAIL. p30 d8925f4f remains CPU/Trusty AND RAM-layout HOLD; the phone
reviewer owns reconciliation. No bootcpu/RAM replacement, new image, schedule,
health retry or lifecycle6/7. Apps registration guest and the one queued OWN
batch are left untouched. All OS/GPU/firmware/cache/VM/engine facts remain
external prerequisites, never inferred from this host implementation.
