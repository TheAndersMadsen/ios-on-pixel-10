<!-- SPDX-License-Identifier: MIT -->
# Portable PDS/CDM resources and frozen validation seams

Original frozen sources from streams, streams-r2 and streams-r3, with C and
headers unchanged. The single build/test entry point is
[`../isa/CMakeLists.txt`](../isa/CMakeLists.txt); see
[`../isa/README.md`](../isa/README.md) for exact commands, dependencies and
acceptance boundaries. There is no second build/helper/provider assembly.

`hm_streams` supplies the original low-level resource builders and decoder.
`hm_shared`/`hm_shared_decode` supply the existing common-init SH0/1 resource
path. `hm_shared_bridge` requires an authentic raw stage validator and a
separate common-init visibility/lifetime/release proof. `hm_shared_queue`
requires the existing real queue emitter. Missing prerequisites still refuse;
no callback, ready state or completion event is fabricated by this import.

`LICENSE` retains the complete original streams/r2 MIT notice and Imagination
protocol-definition attribution. `licenses/streams-r3.LICENSE` retains that
owner's exact MIT notice. The per-file source/license ledger is at
`../isa/{SOURCE-INVENTORY,LICENSE-MANIFEST}.json`. Canonical shared ABI headers,
queue definitions and frozen AIR-r4 integration references stay external.

The existing C tests keep their original notices and explicitly modeled
external BO/engine/cache/ISA/order boundaries. Test success is source evidence,
never native shader execution, HEALTH5 acceptance or hardware capability.
