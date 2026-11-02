/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original DXT71 semantic stream builders. See PROVENANCE.md for field evidence.
 * No allocation, firmware submission, readiness assertion, or Mesa dependency.
 */
#ifndef HM_STREAMS_H
#define HM_STREAMS_H
#include <stddef.h>
#include <stdint.h>
#include "hmgpu_uc.h"

#ifdef __cplusplus
extern "C" {
#endif

enum hms_status {
    HMS_OK = 0, HMS_E_ARGUMENT = -1, HMS_E_RANGE = -2,
    HMS_E_ALIGN = -3, HMS_E_UNSUPPORTED = -4, HMS_E_CAPACITY = -5,
    HMS_E_FORMAT = -6, HMS_E_DEPENDENCY = -7, HMS_E_SHADER = -8,
    HMS_E_ALIAS = -9
};
enum hms_heap { HMS_GENERAL = 1, HMS_USC = 2, HMS_PDS = 3 };
enum hms_pds_bank { HMS_PDS_CONSTANT = 1 };
enum hms_dout { HMS_DOUTW = 1, HMS_DOUTU = 2 };
#define HMS_MAX_POINTERS 8u
#define HMS_PDS_CONST_WORDS 192u
#define HMS_PDS_TEMP_WORDS 32u
#define HMS_CDM_WORDS 9u
#define HMS_CDM_BYTES 36u
#define HMS_STREAM_GUARD 64u
#define HMS_PROFILE_SINGLE_COMPUTE 1u

struct hms_heap_span { uint64_t base, bytes; };
struct hms_heaps {
    struct hms_heap_span general, usc, pds;
    uint32_t page_size;
};
/* Describes an already allocated, owned, resident BO slice; never allocates VA.
 * The task/VM authority and its immutable contents must be checked by the
 * caller (queue pins them). Numeric handles/addresses alone are not authority.
 */
struct hms_region {
    struct hmgpu_bo_out bo;
    uint64_t offset, bytes;
    uint32_t heap, access;
};

/* Only literal constant-bank sources in this milestone. DXT's physical source
 * fields can name other banks, but those are deliberately not accepted.
 * src0_word is an EVEN 32-bit word index naming a 64-bit source pair.
 */
struct hms_pds_dout {
    uint32_t kind, end, conditional;
    uint32_t src0_bank, src0_word, src1_bank, src1_word;
};
int hms_pds_dout_encode(const struct hms_pds_dout *, uint32_t *word);
int hms_pds_dout_decode(uint32_t word, struct hms_pds_dout *);

/* Single phase compute DOUTU immediate payload: USC heap-relative bytes / 4,
 * temporary count rounded to two. All graphics/dynamic resource flags zero.
 */
int hms_pds_launch_encode(uint64_t entry_offset, uint32_t temps, uint64_t *word);
int hms_pds_launch_decode(uint64_t word, uint64_t *entry_offset, uint32_t *temps_allocated);

/* Two literal words written to two adjacent unified input words. The exact
 * USC source-bank interpretation is the ISA validator's responsibility.
 * Common/shared and other destination modes are intentionally unavailable.
 */
int hms_pds_pointer_control_encode(uint32_t input_word, uint32_t last, uint32_t *word);
int hms_pds_pointer_control_decode(uint32_t word, uint32_t *input_word, uint32_t *last);

/* Exact known direct CDM format-5 subset. No common-store allocation, indirect
 * fields, barriers, coefficients, SD, stream links, or unclassified flag bits.
 * Quantities are SEMANTIC 32-bit word counts, not already-shifted raw fields.
 */
struct hms_cdm_direct {
    uint64_t pds_data_offset, pds_code_offset;
    uint32_t pds_data_words, pds_temp_words, usc_unified_words;
    uint32_t groups[3], local[3];
};
struct hms_cdm_decoded {
    uint32_t pds_data_offset, pds_code_offset;
    uint32_t pds_data_words_allocated, pds_temp_words_allocated;
    uint32_t usc_unified_words_allocated, max_instances;
    uint32_t groups[3], local[3];
};
int hms_cdm_encode(const struct hms_cdm_direct *, void *bytes, size_t capacity);
int hms_cdm_decode(const void *bytes, size_t length, struct hms_cdm_decoded *);

/* Trusted compiler INTERNAL sidecar; not an HMUSC1 or HMGU wire extension.
 * A validator must establish these facts from the complete owned USC stage,
 * including resource lifetime/control termination and pointer input bank.
 * This library does not turn HAS_CODE or a caller boolean into shader validity.
 */
struct hms_pointer_arg {
    uint32_t input_word, min_bytes, access;
};
struct hms_entry {
    uint32_t profile, entry_offset, temps, unified_words;
    uint32_t pointer_count;
    struct hms_pointer_arg pointers[HMS_MAX_POINTERS];
};
typedef int (*hms_validate_usc_fn)(void *cookie, const void *hmusc, size_t length,
                                 const struct hms_entry *entry);
struct hms_compute_desc {
    struct hms_heaps heaps;
    const void *hmusc;
    size_t hmusc_bytes;
    struct hms_entry entry;
    hms_validate_usc_fn validate_usc;
    void *validate_cookie;
    struct hms_region usc;
    struct hms_region buffers[HMS_MAX_POINTERS];
    uint32_t groups[3], local[3];
};
struct hms_compute_layout {
    uint32_t pds_data_bytes, pds_code_bytes, stream_bytes;
    uint32_t pds_alignment, stream_alignment, stream_guard;
};
struct hms_compute_storage {
    struct hms_region pds_data, pds_code, stream;
    void *data_cpu, *code_cpu, *stream_cpu;
    size_t data_capacity, code_capacity, stream_capacity;
};
/* Minimal BO refs cover stream, both PDS slices, USC, and pointer buffers;
 * repeated handles are coalesced, access ORed. No firmware pointers here.
 */
struct hms_compute_product {
    uint64_t stream_va;
    uint32_t stream_bytes, bo_count;
    struct hmgpu_bo_ref bos[HMS_MAX_POINTERS + 4];
};

int hms_heaps_from_open(const struct hmgpu_open_out *, struct hms_heaps *);
int hms_region_check(const struct hms_heaps *, const struct hms_region *,
                     uint32_t heap, uint32_t access, uint64_t required, uint64_t alignment,
                     uint64_t *va);
int hms_compute_plan(const struct hms_compute_desc *, struct hms_compute_layout *);
/* No partial writes: every validation precedes copying any generated bytes.
 * Callers must supply immutable descriptors/USC and nonoverlapping outputs.
 */
int hms_compute_build(const struct hms_compute_desc *, const struct hms_compute_storage *,
                      struct hms_compute_product *);
/* Independent semantic decoder, does not call any encoder or re-encode bytes.
 * Run on frozen BO contents before queue publication; validate_usc still must
 * check the actual USC upload is byte-identical to the supplied stage.
 */
int hms_compute_validate(const struct hms_compute_desc *, const struct hms_compute_storage *,
                         const struct hms_compute_product *);
/* Fill the existing v1 COMPUTE job: zero inline FW bodies/static pointers.
 * The kernel/queue must perform frozen-content validation before publication.
 */
int hms_compute_job(const struct hms_compute_product *, uint32_t bo_first, struct hmgpu_job *);

/* Kernel-side HMGU closure validation. No HMUSC1 sidecar travels through SUBMIT:
 * resolve the addresses in the CDM/PDS bytes against the actual pinned BO set,
 * then give the ISA verifier the actual immutable code/launch resources. This
 * avoids inventing a second wire header or trusting a user metadata pointer.
 * Each BO here is an already-pinned authorized full allocation, CPU-readable
 * for at least bo.bytes, with CPU writes frozen. nbo is exactly this job's
 * [bo_first, bo_first+bo_count) slice, not all BOs in a multi-job batch.
 */
struct hms_frozen_bo {
    struct hmgpu_bo_out bo;
    uint32_t heap, access;
    const void *cpu;
    size_t cpu_bytes;
};
struct hms_frozen_pointer {
    uint64_t va, bytes_available;
    uint32_t input_word, handle, access;
};
struct hms_frozen_dispatch {
    const void *usc;
    size_t usc_bytes_available; /* not an assertion of shader length */
    uint64_t usc_entry_va;
    uint32_t usc_handle, temps_allocated, unified_words_allocated, pointer_count;
    struct hms_frozen_pointer pointers[HMS_MAX_POINTERS];
};
/* Must decode the complete supported OWN USC stage from actual bytes, prove
 * termination/scheduling, check temp/unified resource allocation + input bank,
 * and validate EVERY USC memory access against the pointer ranges/access.
 * No callback => DEPENDENCY. No existing production callback is supplied here.
 */
typedef int (*hms_validate_frozen_usc_fn)(void *, const struct hms_frozen_dispatch *);
int hms_compute_validate_frozen(const struct hms_heaps *, const struct hmgpu_job *,
    const struct hms_frozen_bo *, uint32_t nbo, hms_validate_frozen_usc_fn, void *cookie,
    struct hms_frozen_dispatch *);
const char *hms_status_string(int);

#ifdef __cplusplus
}
#endif
#endif
