/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Narrow queue builder composition.
 */
#ifndef HM_SHARED_QUEUE_H
#define HM_SHARED_QUEUE_H
#include "hm_shared_bridge.h"
#include "hmg_queue.h"
#ifdef __cplusplus
extern "C" {
#endif
struct hmsr_queue_bridge {
    struct hms_heaps heaps;
    struct hmsr_validation_ops validation;
    void *cookie;
    /* Borrow the ACTUAL pin's full CPU/cache-authorized frozen alias. No
     * allocation/pin/release here. Queue keeps authority through build/publish
     * and true engine+cache handback, or proved quiescence. No raw KVA cast. */
    int (*frozen_view)(void *, const struct hq_bo *, struct hms_frozen_bo *);
    /* queue-r2 owns the real profile-specific firmware body and CSW/state.
     * NULL => UNAVAILABLE. Called ONLY after full frozen validation succeeds.
     * No production implementation of this missing FW seam lives here. */
    int (*emit_compute)(void *, struct hq_context *, const struct hmgpu_job *,
        const struct hmsr_validated *, struct hq_body *);
};
/* Exact hq_native_builders.build_compute signature. Internal cookie wrapper
 * may contain this object and forward here. Failure preserves *body; never
 * releases, publishes, changes context state or claims completion itself.
 * All callbacks are trusted kernel code, never data supplied in HMGU SUBMIT.
 */
int hmsr_queue_build_compute(void *, struct hq_context *, const struct hmgpu_job *,
    const struct hq_bo *, uint32_t, struct hq_body *);
#ifdef __cplusplus
}
#endif
#endif
