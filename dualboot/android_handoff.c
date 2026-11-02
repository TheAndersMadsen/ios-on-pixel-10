/* SPDX-License-Identifier: MIT
 * Original preparation-only validator; performs no memory-mapped I/O, source
 * hashing, storage access, CPU instructions, reset, copy, overlay or dispatch.
 */
#include "android_handoff.h"

#if HK_ANDROID_HANDOFF
#include "android_reference_data.h"
#define NELTS(a) ((uint32_t)(sizeof(a) / sizeof((a)[0])))
_Static_assert(NELTS(hk_a_sources) == HK_ANDROID_SOURCE_COUNT, "source pins complete");
_Static_assert(NELTS(hk_a_components) == HK_ANDROID_COMPONENT_COUNT, "component pins complete");

static int same(struct hk_android_sha256 a, struct hk_android_sha256 b)
{
    uint8_t difference = 0;
    for (uint32_t i = 0; i < 32; ++i) difference |= (uint8_t)(a.bytes[i] ^ b.bytes[i]);
    return difference == 0;
}

static int present(struct hk_android_sha256 a)
{
    uint8_t any = 0;
    for (uint32_t i = 0; i < 32; ++i) any |= a.bytes[i];
    return any != 0;
}

static int identity_valid(const struct hk_android_identity *a)
{
    return a->boot_nonce && a->boot_entry && a->capture_generation &&
        present(a->device) && present(a->temporary_image) && present(a->capture) && present(a->gpt);
}

static int identity_same(const struct hk_android_identity *a, const struct hk_android_identity *b)
{
    return a->boot_nonce == b->boot_nonce && a->boot_entry == b->boot_entry &&
        a->capture_generation == b->capture_generation && same(a->device, b->device) &&
        same(a->temporary_image, b->temporary_image) && same(a->capture, b->capture) && same(a->gpt, b->gpt);
}

static int receipt(const struct hk_android_evidence *e, uint32_t kind)
{
    const struct hk_android_receipt *r = &e->receipts[kind];
    return r->kind == kind && r->scope == HK_ANDROID_ACTUAL_CURRENT && r->sequence &&
        r->sequence <= e->current.latest_sequence && present(r->payload) &&
        identity_same(&r->identity, &e->current.identity);
}

static int valid_range(struct hk_android_range r)
{
    return r.size && r.base <= UINT64_MAX - r.size;
}

static int contains(struct hk_android_range a, struct hk_android_range b)
{
    return valid_range(a) && valid_range(b) && b.base >= a.base &&
        b.base - a.base <= a.size && b.size <= a.size - (b.base - a.base);
}

static int overlaps(struct hk_android_range a, struct hk_android_range b)
{
    return a.base < b.base + b.size && b.base < a.base + a.size;
}

static int disjoint_ranges(const struct hk_android_range *ranges, uint32_t n)
{
    for (uint32_t i = 0; i < n; ++i) {
        if (!valid_range(ranges[i])) return 0;
        for (uint32_t j = 0; j < i; ++j)
            if (overlaps(ranges[i], ranges[j])) return 0;
    }
    return 1;
}

static int covered(const struct hk_android_range *ranges, uint32_t n, struct hk_android_range r)
{
    for (uint32_t i = 0; i < n; ++i)
        if (contains(ranges[i], r)) return 1;
    return 0;
}

static int memory_valid(const struct hk_android_evidence *e)
{
    const struct hk_android_memory *m = &e->memory;
    const struct hk_android_output *o = &e->output;
    struct hk_android_range targets[3] = {o->kernel, o->initrd, o->dtb};
    struct hk_android_range fdt = {e->current.fdt_pa, e->current.fdt_bytes};
    if (!receipt(e, HK_AR_MEMORY) || !m->ram_count || m->ram_count > HK_ANDROID_MAX_RAM ||
        !m->reservation_count || m->reservation_count > HK_ANDROID_MAX_RESERVATIONS ||
        !m->resident_count || m->resident_count > HK_ANDROID_MAX_RESIDENTS || m->unresolved_reservations ||
        !same(m->current_fdt, e->current.fdt) || !present(m->ram_manifest) ||
        !same(m->ram_manifest, e->receipts[HK_AR_MEMORY].payload) ||
        !present(m->reservation_manifest) || !present(m->resident_manifest) ||
        !same(o->dtb_memory_manifest, m->ram_manifest) ||
        !same(o->dtb_reservation_manifest, m->reservation_manifest) ||
        !disjoint_ranges(m->ram, m->ram_count) ||
        !disjoint_ranges(m->reservations, m->reservation_count) ||
        !disjoint_ranges(m->residents, m->resident_count) || !disjoint_ranges(targets, 3) ||
        !covered(m->residents, m->resident_count, fdt) ||
        !covered(m->residents, m->resident_count, e->current.executing_shim) ||
        !covered(m->residents, m->resident_count, e->current.abl_initrd)) return 0;
    for (uint32_t i = 0; i < 3; ++i) {
        if (!covered(m->ram, m->ram_count, targets[i])) return 0;
        for (uint32_t j = 0; j < m->reservation_count; ++j)
            if (overlaps(targets[i], m->reservations[j])) return 0;
        for (uint32_t j = 0; j < m->resident_count; ++j)
            if (overlaps(targets[i], m->residents[j])) return 0;
    }
    return 1;
}

static int avb_valid(const struct hk_android_evidence *e)
{
    const struct hk_android_avb *a = &e->avb;
    if (!receipt(e, HK_AR_AVB_GRAPH) || !receipt(e, HK_AR_ROOT_ROLLBACK) ||
        !same(a->current_graph, e->receipts[HK_AR_AVB_GRAPH].payload) ||
        !same(a->root_rollback_manifest, e->receipts[HK_AR_ROOT_ROLLBACK].payload) ||
        !same(a->configured_root, hk_a_root) || a->flags || a->node_count != 5 ||
        a->signed_nodes != 5 || a->chains != 4 || a->hashes != 28 || a->hashtrees != 6) return 0;
    for (uint32_t i = 0; i < 5; ++i) {
        const struct hk_android_avb_node *n = &a->nodes[i], *p = &hk_a_nodes[i];
        if (n->source_id != p->source_id || n->rollback_location != p->rollback_location ||
            n->image_rollback != p->image_rollback || n->protected_rollback > n->image_rollback ||
            !same(n->key, p->key)) return 0;
    }
    return 1;
}

static int selection_valid(const struct hk_android_evidence *e)
{
    const struct hk_android_selection *s = &e->selection;
    if (!receipt(e, HK_AR_BOARD_SELECTION) || s->kernel_component != HK_A_KERNEL ||
        s->ramdisk_count < 3 || s->ramdisk_count > 4 || s->dtb_index >= NELTS(hk_a_dtbs) ||
        !s->overlay_count || s->overlay_count > HK_ANDROID_MAX_OVERLAYS ||
        !present(s->actual_board) || !present(s->abl_selection_rule) ||
        !same(s->selection_manifest, e->receipts[HK_AR_BOARD_SELECTION].payload) ||
        !same(s->source_dtb, hk_a_components[HK_A_DTB_BLOB].sha256) ||
        !same(s->source_dtbo, hk_a_sources[HK_A_DTBO].sha256)) return 0;
    uint32_t mask = 0;
    for (uint32_t i = 0; i < s->ramdisk_count; ++i) {
        uint32_t id = s->ramdisk_components[i];
        if (id < HK_A_GENERIC_RAMDISK || id > HK_A_VENDOR_KERNEL_PLATFORM_RAMDISK ||
            (mask & (1u << id))) return 0;
        mask |= 1u << id;
    }
    /* Membership only. No ordering, variant compatibility or ABL selection
     * rule is invented here; the mandatory producer receipt must prove them. */
    if (!(mask & (1u << HK_A_GENERIC_RAMDISK)) ||
        !(mask & (1u << HK_A_VENDOR_KERNEL_PLATFORM_RAMDISK)) ||
        !(mask & ((1u << HK_A_VENDOR_PLATFORM_RAMDISK) | (1u << HK_A_VENDOR_16K_RAMDISK)))) return 0;
    for (uint32_t i = 0; i < s->overlay_count; ++i) {
        if (s->overlays[i] >= NELTS(hk_a_dtbos)) return 0;
        for (uint32_t j = 0; j < i; ++j)
            if (s->overlays[i] == s->overlays[j]) return 0;
    }
    /* No uncounted selections may be hidden after the declared list. */
    for (uint32_t i = s->ramdisk_count; i < 4; ++i)
        if (s->ramdisk_components[i]) return 0;
    for (uint32_t i = s->overlay_count; i < HK_ANDROID_MAX_OVERLAYS; ++i)
        if (s->overlays[i]) return 0;
    return 1;
}

static int output_valid(const struct hk_android_evidence *e)
{
    const struct hk_android_output *o = &e->output;
    uint64_t payload = 0;
    if (!receipt(e, HK_AR_PREPARED_BYTES) || !receipt(e, HK_AR_FINAL_DTB) ||
        !receipt(e, HK_AR_BOOTCONFIG) || o->reserved || !valid_range(o->kernel) ||
        !valid_range(o->initrd) || !valid_range(o->dtb) ||
        (o->kernel.base & 3u) || (o->dtb.base & 7u) || o->dtb.size > 2u*1024u*1024u ||
        o->entry_pa < o->kernel.base || o->entry_pa - o->kernel.base >= o->kernel.size ||
        (o->entry_pa & 3u) || !present(o->kernel_sha256) || !present(o->initrd_sha256) ||
        !present(o->dtb_sha256) || !same(o->prepared_manifest, e->receipts[HK_AR_PREPARED_BYTES].payload) ||
        !same(o->final_dtb_manifest, e->receipts[HK_AR_FINAL_DTB].payload) ||
        !same(o->bootconfig_manifest, e->receipts[HK_AR_BOOTCONFIG].payload) ||
        !present(o->bootconfig_sha256) || !o->bootconfig_bytes ||
        o->bootconfig_offset > o->initrd.size ||
        o->bootconfig_bytes > o->initrd.size - o->bootconfig_offset ||
        o->dtb_initrd_start != o->initrd.base || o->dtb_initrd_end != o->initrd.base + o->initrd.size ||
        o->dtb_slot != e->current.selected_slot) return 0;
    for (uint32_t i = 0; i < e->selection.ramdisk_count; ++i) {
        uint64_t size = hk_a_components[e->selection.ramdisk_components[i]].bytes;
        if (payload > UINT64_MAX - size) return 0;
        payload += size;
    }
    /* The separately verified output receipt binds padding/trailer bytes and
     * final bootconfig content, including both exact reference config extents
     * and current dynamic values. This validator does not append anything. */
    return payload == o->initrd_payload_bytes && payload <= o->bootconfig_offset &&
        e->receipts[HK_AR_CAPTURE].sequence < e->receipts[HK_AR_PREPARED_BYTES].sequence &&
        e->receipts[HK_AR_PREPARED_BYTES].sequence < e->receipts[HK_AR_QUIESCENCE].sequence;
}

static int lun_present(const struct hk_android_storage *s, const struct hk_android_extent *e)
{
    if (e->reserved || !e->blocks || e->lba > UINT64_MAX-e->blocks) return 0;
    for (uint32_t i = 0; i < s->lun_count; ++i)
        if (s->luns[i].id == e->lun)
            return e->lba <= s->luns[i].blocks && e->blocks <= s->luns[i].blocks-e->lba;
    return 0;
}

static int extents_overlap(const struct hk_android_extent *a, const struct hk_android_extent *b)
{
    return a->lun == b->lun && a->lba < b->lba+b->blocks && b->lba < a->lba+a->blocks;
}

static int extent_group(const struct hk_android_storage *s, const struct hk_android_extent *a, uint32_t n)
{
    if (!n || n > HK_ANDROID_MAX_EXTENTS) return 0;
    for (uint32_t i = 0; i < n; ++i) {
        if (!lun_present(s, &a[i])) return 0;
        for (uint32_t j = 0; j < i; ++j)
            if (extents_overlap(&a[i], &a[j])) return 0;
    }
    return 1;
}

static int storage_valid(const struct hk_android_evidence *e, uint64_t *raw_bytes)
{
    const struct hk_android_storage *s = &e->storage;
    uint64_t blocks = 0;
    if (!receipt(e, HK_AR_STORAGE_ISOLATION) || s->block_bytes != 4096 || !s->lun_count ||
        s->lun_count > HK_ANDROID_MAX_LUNS || s->reserved[0] || s->reserved[1] || s->reserved[2] ||
        !present(s->alias_ownership) || !present(s->android_integrity) ||
        !same(s->allocation_manifest, e->receipts[HK_AR_STORAGE_ISOLATION].payload)) return 0;
    for (uint32_t i = 0; i < s->lun_count; ++i) {
        if (s->luns[i].reserved || !s->luns[i].blocks || blocks > UINT64_MAX-s->luns[i].blocks) return 0;
        blocks += s->luns[i].blocks;
        for (uint32_t j = 0; j < i; ++j)
            if (s->luns[i].id == s->luns[j].id) return 0;
    }
    if (blocks > UINT64_MAX/s->block_bytes) return 0;
    *raw_bytes = blocks*s->block_bytes;
    if (!extent_group(s, s->android, s->android_count) ||
        !extent_group(s, s->ios_root, s->ios_root_count) ||
        !extent_group(s, s->ios_data, s->ios_data_count)) return 0;
    for (uint32_t i = 0; i < s->android_count; ++i) {
        for (uint32_t j = 0; j < s->ios_root_count; ++j)
            if (extents_overlap(&s->android[i], &s->ios_root[j])) return 0;
        for (uint32_t j = 0; j < s->ios_data_count; ++j)
            if (extents_overlap(&s->android[i], &s->ios_data[j])) return 0;
    }
    for (uint32_t i = 0; i < s->ios_root_count; ++i)
        for (uint32_t j = 0; j < s->ios_data_count; ++j)
            if (extents_overlap(&s->ios_root[i], &s->ios_data[j])) return 0;
    return 1;
}

static int backup_valid(const struct hk_android_evidence *e, uint64_t raw_bytes)
{
    const struct hk_android_backup *b = &e->backup;
    return receipt(e, HK_AR_BACKUP_RAW) && receipt(e, HK_AR_BACKUP_USER) && receipt(e, HK_AR_BACKUP_KEYS) &&
        raw_bytes && b->required_raw_bytes == raw_bytes && b->verified_raw_bytes == raw_bytes &&
        same(b->raw_manifest, e->receipts[HK_AR_BACKUP_RAW].payload) &&
        present(b->independent_destination) && present(b->rollback_procedure) &&
        same(b->readable_user_recovery, e->receipts[HK_AR_BACKUP_USER].payload) &&
        same(b->encryption_key_recovery, e->receipts[HK_AR_BACKUP_KEYS].payload);
}

static int cpu_valid(const struct hk_android_evidence *e)
{
    const struct hk_android_cpu *c = &e->cpu;
    uint32_t boots = 0;
    if (!receipt(e, HK_AR_CPU) || c->reserved || !c->count || c->count > HK_ANDROID_MAX_CPUS ||
        c->boot_mpidr != e->current.boot_mpidr || (c->current_el != 4 && c->current_el != 8) ||
        (c->sctlr & ((UINT64_C(1) << 25) | UINT64_C(5))) ||
        (c->daif & UINT64_C(0x3c0)) != UINT64_C(0x3c0) ||
        !present(c->errata_requirements) || !present(c->errata_acceptance) || !present(c->cache_maintenance) ||
        !same(c->context_manifest, e->receipts[HK_AR_CPU].payload) ||
        e->receipts[HK_AR_CPU].sequence != e->current.latest_sequence) return 0;
    for (uint32_t i = 0; i < c->count; ++i) {
        if (c->cpus[i].reserved) return 0;
        if (c->cpus[i].state == HK_ANDROID_CPU_BOOT) {
            if (c->cpus[i].mpidr != c->boot_mpidr) return 0;
            ++boots;
        } else if (c->cpus[i].state != HK_ANDROID_CPU_HELD) return 0;
        for (uint32_t j = 0; j < i; ++j)
            if (c->cpus[i].mpidr == c->cpus[j].mpidr) return 0;
    }
    return boots == 1;
}

static int firmware_valid(const struct hk_android_evidence *e)
{
    const struct hk_android_firmware *f = &e->firmware;
    return receipt(e, HK_AR_FIRMWARE_IDENTITY) && receipt(e, HK_AR_QUIESCENCE) &&
        same(f->running_identity, e->receipts[HK_AR_FIRMWARE_IDENTITY].payload) &&
        same(f->quiescence_manifest, e->receipts[HK_AR_QUIESCENCE].payload) &&
        e->receipts[HK_AR_QUIESCENCE].sequence == e->current.latest_sequence &&
        present(f->secure_state) && present(f->trusty_state) && present(f->dma_inventory) &&
        present(f->ufs_quiet) && present(f->usb_quiet) && present(f->display_quiet) &&
        present(f->interrupts_quiet) && present(f->watchdog_contract);
}
#endif

enum hk_android_result hk_android_prepare(const struct hk_android_evidence *e)
{
#if !HK_ANDROID_HANDOFF
    (void)e;
    return HK_ANDROID_DISABLED;
#else
    if (!e) return HK_ANDROID_CURRENT_REQUIRED;
    if (e->abi != HK_ANDROID_ABI || e->bytes != sizeof(*e) || e->runtime_enable != 1 || e->reserved)
        return HK_ANDROID_BAD_INPUT;
    const struct hk_android_current *c = &e->current;
    if (e->scope != HK_ANDROID_ACTUAL_CURRENT || !identity_valid(&c->identity) ||
        !c->latest_sequence || !c->fdt_pa || (c->fdt_pa & 7u) || !c->fdt_bytes ||
        c->fdt_bytes > 2u*1024u*1024u || c->fdt_pa > UINT64_MAX-c->fdt_bytes ||
        !valid_range(c->executing_shim) || !valid_range(c->abl_initrd) ||
        (c->active_slot != 'a' && c->active_slot != 'b') ||
        (c->selected_slot != 'a' && c->selected_slot != 'b') || !present(c->fdt) ||
        !present(c->slot_selection) || !receipt(e, HK_AR_CAPTURE) || !receipt(e, HK_AR_GPT_SLOT) ||
        !same(c->identity.capture, e->receipts[HK_AR_CAPTURE].payload) ||
        !same(c->identity.gpt, e->receipts[HK_AR_GPT_SLOT].payload)) return HK_ANDROID_CURRENT_REQUIRED;
    if (!same(e->reference_artifacts, hk_a_artifacts) || !same(e->reference_archive, hk_a_archive))
        return HK_ANDROID_REFERENCE_MISMATCH;
    if (e->source_count != HK_ANDROID_SOURCE_COUNT) return HK_ANDROID_SOURCE_REQUIRED;
    for (uint32_t i = 0; i < HK_ANDROID_SOURCE_COUNT; ++i) {
        const struct hk_android_source *s = &e->sources[i];
        if (s->id != i || s->slot != c->selected_slot || s->bytes != hk_a_sources[i].bytes ||
            s->capture_generation != c->identity.capture_generation ||
            !same(s->sha256, hk_a_sources[i].sha256) || !present(s->capture_receipt) ||
            !present(s->partition_identity)) return HK_ANDROID_SOURCE_REQUIRED;
    }
    if (!avb_valid(e)) return HK_ANDROID_AVB_REQUIRED;
    if (!selection_valid(e)) return HK_ANDROID_SELECTION_REQUIRED;
    if (!output_valid(e)) return HK_ANDROID_PREPARED_BYTES_REQUIRED;
    if (!memory_valid(e)) return HK_ANDROID_MEMORY_REQUIRED;
    uint64_t raw_bytes = 0;
    if (!storage_valid(e, &raw_bytes)) return HK_ANDROID_ISOLATION_REQUIRED;
    if (!backup_valid(e, raw_bytes)) return HK_ANDROID_BACKUP_REQUIRED;
    if (!cpu_valid(e)) return HK_ANDROID_CPU_REQUIRED;
    if (!firmware_valid(e)) return HK_ANDROID_QUIESCENCE_REQUIRED;
    /* Receipt digests and ACTUAL_CURRENT labels cannot verify themselves.
     * Require the real producer to validate the payload-to-field bindings
     * for every domain; the native integration deliberately has no producer.
     * This verification call is not an Android entry/dispatch callback. */
    const struct hk_android_producer *p = e->producer;
    if (!p || p->abi != HK_ANDROID_ABI || p->scope != HK_ANDROID_ACTUAL_CURRENT || !p->verify)
        return HK_ANDROID_EVIDENCE_REQUIRED;
    for (uint32_t i = 0; i < HK_AR_COUNT; ++i)
        if (p->verify(p->context, e, (enum hk_android_receipt_kind)i) != 1)
            return HK_ANDROID_EVIDENCE_REQUIRED;
    return HK_ANDROID_PREPARED;
#endif
}

const char *hk_android_result_name(enum hk_android_result r)
{
    switch (r) {
    case HK_ANDROID_DISABLED: return "disabled";
    case HK_ANDROID_BAD_INPUT: return "bad input";
    case HK_ANDROID_CURRENT_REQUIRED: return "current capture required";
    case HK_ANDROID_REFERENCE_MISMATCH: return "exact reference mismatch";
    case HK_ANDROID_SOURCE_REQUIRED: return "current graph sources required";
    case HK_ANDROID_AVB_REQUIRED: return "current AVB key and rollback required";
    case HK_ANDROID_SELECTION_REQUIRED: return "actual board and selection required";
    case HK_ANDROID_PREPARED_BYTES_REQUIRED: return "prepared output bytes required";
    case HK_ANDROID_MEMORY_REQUIRED: return "memory and reservations required";
    case HK_ANDROID_BACKUP_REQUIRED: return "recoverable current backup required";
    case HK_ANDROID_ISOLATION_REQUIRED: return "storage isolation required";
    case HK_ANDROID_CPU_REQUIRED: return "accepted current CPU context required";
    case HK_ANDROID_QUIESCENCE_REQUIRED: return "firmware quiescence required";
    case HK_ANDROID_EVIDENCE_REQUIRED: return "independent current evidence verifier required";
    case HK_ANDROID_PREPARED: return "PREPARED ONLY; Android dispatch unavailable";
    }
    return "unknown Android preparation result";
}

const struct hk_android_source_pin *hk_android_source_pin(uint32_t i)
{
#if HK_ANDROID_HANDOFF
    if (i < NELTS(hk_a_sources)) return &hk_a_sources[i];
#else
    (void)i;
#endif
    return 0;
}

const struct hk_android_component_pin *hk_android_component_pin(uint32_t i)
{
#if HK_ANDROID_HANDOFF
    if (i < NELTS(hk_a_components)) return &hk_a_components[i];
#else
    (void)i;
#endif
    return 0;
}

const struct hk_android_tree_pin *hk_android_dtb_pin(uint32_t i)
{
#if HK_ANDROID_HANDOFF
    if (i < NELTS(hk_a_dtbs)) return &hk_a_dtbs[i];
#else
    (void)i;
#endif
    return 0;
}

const struct hk_android_tree_pin *hk_android_dtbo_pin(uint32_t i)
{
#if HK_ANDROID_HANDOFF
    if (i < NELTS(hk_a_dtbos)) return &hk_a_dtbos[i];
#else
    (void)i;
#endif
    return 0;
}

uint32_t hk_android_dtb_count(void)
{
#if HK_ANDROID_HANDOFF
    return NELTS(hk_a_dtbs);
#else
    return 0;
#endif
}

uint32_t hk_android_dtbo_count(void)
{
#if HK_ANDROID_HANDOFF
    return NELTS(hk_a_dtbos);
#else
    return 0;
#endif
}
