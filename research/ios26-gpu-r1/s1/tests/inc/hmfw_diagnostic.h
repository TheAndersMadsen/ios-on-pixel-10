/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors
 * Original bounded, observation-only FWCCB capture. See PROVENANCE.md.
 */
#ifndef HMFW_DIAGNOSTIC_H
#define HMFW_DIAGNOSTIC_H
#include <stdint.h>
#define HMFD_MAX_ENTRIES 4u
#define HMFD_WORDS 28u
enum hmfd_result { HMFD_OK, HMFD_INVALID, HMFD_IO, HMFD_RACED };
struct hmfd_reader {
    void *ctx;
    /* ONLY read operations exist: no ack, consume, reply, restart or write. */
    int (*read32)(void *, uint32_t off, uint32_t *out);
};
struct hmfd_layout {
    uint32_t bytes, fctl, fccb, slots;
};
struct hmfd_entry { uint32_t slot, words[HMFD_WORDS]; };
struct hmfd_snapshot {
    uint32_t result, write, read, mask, write_after, read_after, mask_after;
    uint32_t pending, captured, truncated;
    struct hmfd_entry entries[HMFD_MAX_ENTRIES];
};
int hmfd_capture(const struct hmfd_reader *, const struct hmfd_layout *, struct hmfd_snapshot *);
const char *hmfd_command_name(uint32_t command);
/* Emits numeric payload fields using measured ABI offsets; never follows
 * firmware-supplied pointers or interprets a message as job completion. */
void hmfd_dump(const struct hmfd_snapshot *, const char *reason);
#endif
