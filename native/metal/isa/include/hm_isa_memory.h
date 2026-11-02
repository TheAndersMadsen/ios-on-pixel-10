/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original DXT71 scalar memory lowering; encoding facts from bounded local
 * vendor codec/conversion observations. See notes/SEMANTICS.md and PROVENANCE.md.
 */
#ifndef HM_ISA_MEMORY_H
#define HM_ISA_MEMORY_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

enum hmisa_status {
    HMISA_OK = 0, HMISA_E_ARGUMENT = -1, HMISA_E_DISABLED = -2,
    HMISA_E_UNSUPPORTED = -3, HMISA_E_BOUNDS = -4, HMISA_E_CAPACITY = -5,
    HMISA_E_FORMAT = -6, HMISA_E_ALIAS = -7
};
enum hmisa_access { HMISA_READ = 1, HMISA_WRITE = 2 };
enum hmisa_bank { HMISA_HWTEMP = 4, HMISA_VERTEX_INPUT = 5, HMISA_SHARED = 7 };
enum hmisa_issue { HMISA_ISSUE_SYNC = 0, HMISA_ISSUE_DESCHED = 1 };
#define HMISA_ENABLE_GROUPS 1u
#define HMISA_DMA_BYTES 16u
#define HMISA_DESCRIPTOR_WORDS 56u

/* These names identify compiler fence namespaces, NOT verified GPU retirement.
 * Raw masks are preserved. The caller still needs an established whole-stage
 * scheduler. No implicit issue/wait, END, completion or engine readiness here.
 */
struct hmisa_schedule {
    uint32_t issue_kind, issue_index, wait_desched, wait_sync;
};
/* An individual four-word DMA group. Scalar lowerer fixes X=4 bytes, Y=1 and
 * an absent robust argument. Wider bursts are only raw codec functionality.
 * address_index is the CANONICAL register number, not a PDS word, VA or byte
 * offset. Hardware type1 -> bank5, type10 -> bank4, type3 -> bank7 is proven;
 * the PDS DOUTW input-word relation is not established by this interface.
 */
struct hmisa_dma {
    uint32_t access, data_reg, address_bank, address_index;
    uint32_t x_bytes, y_count, stride, add_first;
    struct hmisa_schedule schedule;
};
int hmisa_dma_descriptor(const struct hmisa_dma *, uint32_t descriptor[56]);
int hmisa_dma_encode(uint32_t enable, const struct hmisa_dma *, void *, size_t);
/* Strict whole-record / native inverse. Failure preserves outputs. */
int hmisa_dma_from_descriptor(const uint32_t descriptor[56], struct hmisa_dma *);
int hmisa_dma_decode(const void *, size_t, struct hmisa_dma *);

/* Explicit symbolic pointer assignment supplied by the caller. No allocation
 * or pointer initialization is performed. min/max are buffer-relative bytes;
 * byte_origin is the address held in the assigned canonical pointer register.
 */
struct hmisa_pointer {
    uint32_t binding, bank, index, access;
    uint64_t byte_origin, bytes_available;
};
struct hmisa_memory_request {
    uint32_t binding, access, value_reg, reserved;
    uint64_t byte_offset;
};
struct hmisa_memory_product {
    struct hmisa_dma dma;
    uint32_t binding, access;
    uint64_t begin_byte, end_byte; /* Exact half-open buffer-relative span. */
    uint8_t code[HMISA_DMA_BYTES];
};
/* Lower ONE f32 request into a real native DMA group and exact accessed range.
 * Allocation/scheduling are explicit caller inputs. No temp count is invented.
 * Supports byte delta 0..2044, four-byte aligned; unknown larger forms refuse.
 * No stage validator, HMUSC packer, HAS_CODE or Metal compile-success API exists.
 */
int hmisa_memory_lower(uint32_t enable, const struct hmisa_pointer *,
    const struct hmisa_memory_request *, uint32_t hwtemp_words,
    const struct hmisa_schedule *, struct hmisa_memory_product *);

/* An atomic bundle of supported memory accesses. Useful to prepare the two
 * loads/store of one-invocation buffer arithmetic before a whole-stage scheduler
 * exists. This is NOT a runnable USC program; no return/END/ALU is fabricated.
 * Sources/products must be disjoint. No writes occur until all accesses pass.
 */
#define HMISA_MAX_ACCESSES 16u
int hmisa_memory_lower_many(uint32_t enable, const struct hmisa_pointer *, size_t,
    const struct hmisa_memory_request *, const struct hmisa_schedule *, size_t,
    uint32_t hwtemp_words, struct hmisa_memory_product *, size_t);
#ifdef __cplusplus
}
#endif
#endif
