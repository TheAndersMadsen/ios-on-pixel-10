/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original DXT71 resource extension.
 * See PROVENANCE.md. Internal API only; HMGU v1 and HMUSC1 are unchanged.
 */
#ifndef HM_SHARED_H
#define HM_SHARED_H
#include "hm_streams.h"
#ifdef __cplusplus
extern "C" {
#endif
#define HMSR_MAX_SHARED_WORDS 32u
#define HMSR_MAX_INPUTS 32u
#define HMSR_MAX_BOS (HMS_MAX_POINTERS + 6u)
#define HMSR_STREAM_BYTES 68u
#define HMSR_COMMON_PACKET_BYTES 32u
#define HMSR_GATE "BLAZER=1,HMGPU_NATIVE_SHARED_INIT=1"
enum hmsr_input_kind { HMSR_LITERAL32 = 1, HMSR_POINTER64 = 2 };
struct hmsr_input {
    uint32_t word, kind, literal, min_bytes;
    /* POINTER64 only: actual owned BO slice; its GPU VA is relocated here. */
    struct hms_region buffer;
};
struct hmsr_desc {
    struct hms_heaps heaps;
    struct hms_region usc;
    /* These are trusted compiler resource requirements, NOT shader validity.
     * Caller must obtain them from a complete OWN stage. No default metadata.
     * Code bytes/entry are bounded here; no USC instructions are decoded. */
    uint32_t code_bytes, entry_offset, temps, unified_words, shared_words;
    uint32_t input_count;
    struct hmsr_input inputs[HMSR_MAX_INPUTS];
};
struct hmsr_layout {
    uint32_t shared_words_allocated;
    uint32_t init_data_bytes, init_code_bytes, main_data_bytes, main_code_bytes;
    uint32_t stream_bytes, alignment, guard;
};
struct hmsr_segment {
    struct hms_region region;
    void *cpu;
    size_t capacity;
};
struct hmsr_storage { struct hmsr_segment init_data, init_code, main_data, main_code, stream; };
struct hmsr_product {
    uint64_t stream_va;
    uint32_t stream_bytes, bo_count;
    struct hmgpu_bo_ref bos[HMSR_MAX_BOS];
};
/* Only literal64 DOUTW pairs, even destinations, destination mode1 (shared).
 * Each call generates fields, not an assertion of USC bank semantics. */
int hmsr_shared_control_encode(uint32_t word, uint32_t last, uint32_t *);
int hmsr_shared_control_decode(uint32_t, uint32_t *word, uint32_t *last);
/* Separate common initialization CDM kernel: ALL, K1.bit1, K8.low11, no END.
 * Allocation request16/32 words; no local memory, flags, barriers or builtins. */
int hmsr_common_cdm_encode(uint64_t data_offset, uint64_t code_offset,
    uint32_t data_words, uint32_t shared_words_allocated, void *, size_t);
struct hmsr_common_decoded { uint32_t data_offset, code_offset, data_words_allocated, shared_words_allocated; };
int hmsr_common_cdm_decode(const void *, size_t, struct hmsr_common_decoded *);
int hmsr_plan(const struct hmsr_desc *, struct hmsr_layout *);
/* Allocation-free, failure is transactional for every segment and product.
 * Builds zero-filled common image including16-word allocation padding, then
 * a separate ordinary DOUTU launch and CDM main kernel+terminate. One invocation.
 * No HMGU job or executable/ready receipt is produced by this resource API. */
int hmsr_build(const struct hmsr_desc *, const struct hmsr_storage *, struct hmsr_product *);
struct hmsr_frozen_resources {
    uint64_t usc_entry_va;
    const void *usc;
    size_t usc_bytes_available;
    uint32_t usc_handle, temps_allocated, unified_words_allocated;
    uint32_t shared_words_allocated, shared_image[HMSR_MAX_SHARED_WORDS];
    uint32_t resource_bo_mask;
};
/* Independent frozen resource decoder, NOT shader or submit validation.
 * Follow actual CDM->PDS->USC VAs through already authorized/pinned/frozen BOs.
 * Returns actual initialized shared words for the ISA verifier. It does not
 * identify which shared words a USC instruction treats as a pointer. Queue
 * MUST also run ISA verification proving ALL banks, memory ranges, scheduling,
 * termination and code length against these bytes and this same pinned BO set.
 * Missing ISA proof remains unavailable; this API cannot manufacture it. */
int hmsr_decode_resources(const struct hms_heaps *, const struct hmgpu_job *,
    const struct hms_frozen_bo *, uint32_t, struct hmsr_frozen_resources *);
#ifdef __cplusplus
}
#endif
#endif
