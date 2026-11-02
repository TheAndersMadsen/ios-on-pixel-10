/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original frozen-resource integration.
 * This is an INTERNAL validator contract, not an HMGU/HMUSC wire extension.
 */
#ifndef HM_SHARED_BRIDGE_H
#define HM_SHARED_BRIDGE_H
#include "hm_shared.h"
#ifdef __cplusplus
extern "C" {
#endif
#define HMSR_MAX_MEMORY_ACCESSES 16u
/* A complete raw-byte validator must decode EVERY memory instruction, including
 * its SH address origin, byte displacement, width and access. This first route
 * permits the explicit bank7 SH0/1 pointer only. Literal SH inputs are allowed.
 * code_bytes is decoded consumed length from USC ENTRY, not allocation length.
 */
struct hmsr_memory_access { uint32_t shared_word, access; uint64_t offset, bytes; };
struct hmsr_stage_usage {
    uint32_t code_bytes, temps, unified_words, shared_words, shared_read_mask;
    uint32_t access_count;
    struct hmsr_memory_access accesses[HMSR_MAX_MEMORY_ACCESSES];
};
typedef int (*hmsr_verify_stage_fn)(void *, const struct hmsr_frozen_resources *,
    const struct hms_frozen_bo *, uint32_t, struct hmsr_stage_usage *);
/* This is a separate missing trusted prerequisite. Must establish common-init
 * DOUTW visibility before the main USC reads, common lifetime through END,
 * and safe terminal shared-store release/deallocation for this stream
 * for THIS exact CDM/PDS profile, not schema equality or an engine fence guess.
 * No production stage verifier or ordering witness is supplied in this owner.
 */
typedef int (*hmsr_verify_order_fn)(void *, const struct hms_heaps *,
    const struct hmgpu_job *, const struct hms_frozen_bo *, uint32_t,
    const struct hmsr_frozen_resources *, const struct hmsr_stage_usage *);
struct hmsr_validation_ops {
    void *cookie;
    hmsr_verify_stage_fn verify_stage;
    hmsr_verify_order_fn verify_order;
};
struct hmsr_validated {
    struct hmsr_frozen_resources resources;
    struct hmsr_stage_usage stage;
    uint32_t bo_mask;
};
/* Caller already holds the EXACT job-scoped pinned/frozen full BO allocations
 * and CPU/cache authority. No pin/release, publication, FW state/body, DMA,
 * readiness or completion side effects occur. Failure leaves *out unchanged.
 * Missing authentic verifier/order proof => DEPENDENCY. No HAS_CODE, metadata,
 * marker, resource decoder or encoder output is accepted as stage validation.
 */
int hmsr_validate_frozen(const struct hms_heaps *, const struct hmgpu_job *,
    const struct hms_frozen_bo *, uint32_t, const struct hmsr_validation_ops *,
    struct hmsr_validated *);
#ifdef __cplusplus
}
#endif
#endif
