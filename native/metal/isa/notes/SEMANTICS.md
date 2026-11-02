<!-- SPDX-License-Identifier: MIT -->
# Native scalar implementation and remaining stage facts

This is native C code generation and allocation over AIR-r2's typed semantic
plan, composed with ISA-r2 memory lowering and actual streams-r2 shared resource
construction/decoding. It does not produce a complete executable USC stage.
No API registers a compiler provider or approves a stage/dispatch/publication.

## FOP and control facts

The original MIT isa/ FOP bank4 operand bit positions and scalar selectors are
preserved. New C code inserts semantic dst/lhs/rhs, picks canonical1/2/3-word
extensions and enforces the final-word framing bit. Logical FSUB places rhs in
SRC0 with negate0x100 and lhs in SRC2. FMUL rhs is limited127; other indices255.
These encoding limits are not measured available resources or FP conformance.

FOP scheduling is now explicit. SYNC issue0/1, DESCHED issue0/1/2 and NONE
(canonical kind2,index0) match fresh complete stock codec descriptors. Waiting
on the same SYNC slot being issued refuses; both wait namespaces retain their
distinct masks and noncontiguous extension bits. NONE clears first-word bit23;
it is not equivalent to the older zero-filled descriptor's implicit SYNC0.

`UscasmUpdateDataFences`0x2342b0 confirms, by actual normal pure calls, internal
issue0/NONE -> canonical2,1/SYNC ->0,2/DESCHED ->1. FOP/DMA canonical+38 is
wait_desched and+3c wait_sync. CTRL has a different union: +30 wait_desched,
+34 wait_sync, +38 opcode. Thus isa/'s raw `fence_34` now has a proved namespace.
The saved END with+34=2 waits SYNC bit1; it is not generic END padding evidence.

Normal `ConvertENDToUseasm`0x134540 and `ConvertNOPToUscasm`0x134620 are executed
on fresh own synthetic IR records. They produce all supported wait masks and
named opcodes12/10. NOP supports DESCHED0..7/SYNC0..3 in1/2 words. END is one
word with SYNC0..3; nonzero DESCHED waits are rejected by the stock assembler.
Do not silently convert an outstanding DESCHED dependency to an END SYNC wait.

Important normal-converter/codec normalization: the two UNUSED CTRL operand
banks+6c/+7c are zero immediately after normal conversion, while disassembly
canonicalizes them to7. Tests retain the full raw normal record, require exactly
those two differences, assemble it unchanged and compare ALL decoded224 bytes
against the native canonical descriptor. END framing+dc=1 is added explicitly;
NOP's own repeat count1 sets it through its normal metadata. No other normal
field is masked, dropped, overwritten or ignored in a comparison.

Both strict native inverses extract semantic fields then demand exact re-encode
and length. Whole descriptor inverses compare all56 words including zeros.
Unknown flags/banks/modifiers/lengths are unavailable. External byte/descriptor
comparisons and real mutated C implementations detect shared-inverse mistakes.

## Implemented scheduling and allocation constraints

`hmisa_allocate` performs complete bounded def/use validation first, computes
inclusive last-use indices including STORE/USE and requested live-outs, then
allocates the lowest free register at each LOAD/ALU definition. No source is
freed during its final read instruction. Distinct live inputs may not alias;
two uses of the SAME SSA value (x*x or x+x) are valid. Undefined/forward/self
uses, duplicate definitions, malformed USE/LOAD, duplicate live-outs and
pressure preserve the entire output. Actual high_water is max assigned index+1;
peak_live is the maximum simultaneous inclusive live count, not a guessed cap.
The fixed1..128 budget is an explicit multiply-profile encoding restriction.

Allocation boundaries assume prior asynchronous work has been waited. The
native AIR composition implements that constraint: every DMA producer uses
DESCHED0 and is followed immediately by NOP wait_desched1; every FOP producer
uses SYNC0 and is followed by NOP wait_sync1. There is no outstanding issue
slot before the next operation, register reuse, read, or memory operation.
No memory reordering occurs, including output aliasing a previously read range.

This conservative serialized fragment policy follows named normal compiler
paths: `InsertSyncWaitsBlockBP`0x141cb0 stores1<<prior_issue in IR+a8 (SYNC),
and `EmitDeschedulingFence`0x142390 ORs its wait mask into+a4 (DESCHED), inserting
NOP opcode0x97 where needed. Pure converter calls map those exact fields to
our emitted bytes. It is a real implemented constraint, not an invented device
retirement observation. Full task/END semantics still require their own proof.

## AIR and memory composition

Actual `hm_air_info/buffer/instruction` accessors supply verified typed IR in
process. Supported native preparation: static scalar f32 LOAD/FADD/FSUB/FMUL,
one STORE then RETURN; <=64 AIR instructions/values and16 memory accesses.
Unknown schema fields, constants, gid.x, thread strides, unsupported metadata
and operations refuse before output is published. There is no parser fork or
production Python/LLVM/subprocess call. No algebraic folding or contraction.

hm_air_info_t is copied unchanged, including exact input SHA256, pointer width,
AIR version, opaque denorm mode, RNE and contraction requirement. Preparation
may retain opaque denorm0/1, but always reports FP_ENVIRONMENT unresolved.
Successful preparation does not assert either mode is implemented by hardware.

Memory operations call actual `hmisa_memory_lower` read-only from isa-r2/.
Scalar4-byte width/Y1, byte offsets0..2044 with ADD-FIRST, absent robust bank0,
buffer origin/range/overflow/access and caller register bounds stay unchanged.
Raw memory APIs retain distinct banks4/5/7. Preparation uses the established
bank7 even32-bit SH pointer numbering; no bank5/PDS-input equivalence is guessed.
All allocation, memory errors and missing bindings leave the caller result
unchanged; retry success has no stale allocator/schedule state to clean up.

## Whole-stage facts investigated but still missing

Targeted static receipts (`receipts/named-paths.json`) retain exact commands,
input hash and address ranges. No general audit, constructor, OS, Vulkan device,
source compiler entry or full-system guest executed in this task.

- `UseAssembleInstructions`0x233eb4..0x233fac aligns a label's instruction-word
  offset to its explicit alignment by encoding CTRL NOP10; it does NOT establish
  a universal duplicate-END or prefetch-tail rule. `AssembleProgram`0x146590
  records actual assembled length. Neither proves a safe USC fetch extent or
  task END protocol. No arbitrary alignment/tail bytes were added to our output.
- END's SYNC namespace is established. That alone does not prove that a store
  issue fence means external memory visibility or task teardown can release
  every DMA resource. The saved second END0 remains unexplained. Our unlinked
  output appends neither END nor an unproved padding policy.
- `InsertComparisonDenormFlush`0x21c830 is gated by compiler-state bits and calls
  IsStrictMaths; it is not a direct proof of FOP FTZ/RNE. `GetPCKRoundMode`
  0x7e230 explicitly requires pack IR opcode0x66, so its round-mode metadata
  cannot be applied to scalar FOP by analogy. We do not infer RNE/denorm behavior
  from pack helpers, ARM CPU arithmetic or a byte-exact codec roundtrip.
- HWTEMP is bank4, but mapping actual high_water3/4 to complete DOUTU/dispatch
  resource requests still needs compiler/launch evidence. A resource fixture
  with3 requested/4 rounded words tests the builder only. Likewise a fully
  decoded16-word SH image is not common-init-before-main visibility/lifetime.

The parent-only five OWN SPIR-V request in isa-r2/messages.md is unchanged.
Full USC/resource outputs and primary/common-init PDS/CDM capture can resolve
these facts; a cache hash alone cannot. No guest was launched or waited on here.

## Frozen streams and Metal verifier contract

Read actual streams-r3/include/hm_shared_bridge.h, current peer messages and
integration/CONTRACT.md. No replacement stage callback or surface/backend ABI.
Future authentic verify_stage must decode the actual uploaded USC span passed
in hmsr_frozen_resources, consume precise entry-to-termination length, reject
unknown scheduling/END/padding/FP forms and recompute all register/shared reads
and memory accesses. It cannot trust this producer's fragment metadata as proof.

For the initial shared route: authorize only bank7 SH0/1, read-mask3, actual
pointer decoded from the SAME initialized SH image. Decode every LD/ST's byte
offset/width/access; return each access in existing hmsr_memory_access (<=16),
with its shared_word0. Return exact consumed code_bytes, actual temp high-water,
unified requirement0 and minimal shared requirement2. Compare these against the
rounded actual PDS/CDM allocations; initialized shared padding must be checked.
Check BO aliases/authority/access through the same frozen set and reject writes
to code, control, PDS, or padding. No synthetic VA or inferred permission.

Common-init visibility/lifetime belongs to the existing separate verify_order
callback, including terminal shared release. The latest streams-r3 static
AddCDMDeallocFenceAndTerminate/WriteCDMMCUFlushFence findings are additional
evidence that a plain common/main/terminate resource packet is not an ordering
or deallocation witness; no duplicate writer/flag policy is added here.
Queue-owned CSW/FW-body/completion/cache/quiescent handback are separate
from ISA validation. Metal's hmn_compiler_config.ready/compile_plan must stay
uninstalled until complete producer AND raw verifier support exist. This module
returns unlinked.unresolved=31 on every success, never a complete certificate.

Native source is userspace C, explicitly gated by HMISA_ENABLE_GROUPS at emission
and preparation. It is not guarded XNU. The composed resource HOST test enables
BLAZER=1,HMGPU_NATIVE_STREAMS=1,HMGPU_NATIVE_SHARED_INIT=1 for actual peer code.
No production gates, shared profile, HMGU1 or HMUSC1 were changed.
