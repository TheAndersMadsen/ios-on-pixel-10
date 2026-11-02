/* SPDX-License-Identifier: MIT
 * Synthetic consistency tests. All device, receipt, placement and backup
 * values below are invented in host RAM. They establish no physical fact.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "android_handoff.h"

static unsigned checks;
#define CHECK(expr) do { ++checks; if (!(expr)) { \
    fprintf(stderr, "%s:%u: failed: %s\n", __FILE__, __LINE__, #expr); return 1; } } while (0)

static struct hk_android_sha256 synthetic_digest(unsigned tag)
{
    struct hk_android_sha256 d;
    for (unsigned i = 0; i < 32; ++i) d.bytes[i] = (uint8_t)(tag + 3*i + 1);
    return d;
}

#if HK_ANDROID_HANDOFF
struct synthetic_verifier_context {
    const struct hk_android_evidence *expected;
    unsigned calls;
    int forced_result;
};
static int synthetic_verify(void *context, const struct hk_android_evidence *e,
                            enum hk_android_receipt_kind kind)
{
    struct synthetic_verifier_context *c = context;
    ++c->calls;
    if (c->forced_result) return c->forced_result;
    /* Independent immutable golden fixture: any field/list/order change
     * without a replacement verified payload must fail. No real evidence or
     * hardware is consulted, and this verifier is tests-only. */
    return kind < HK_AR_COUNT && memcmp(c->expected, e, sizeof(*e)) == 0;
}

static struct hk_android_sha256 hex_digest(const char *s)
{
    struct hk_android_sha256 d;
    for (unsigned i = 0; i < 32; ++i) {
        unsigned byte = 0;
        (void)sscanf(s+2*i, "%2x", &byte);
        d.bytes[i] = (uint8_t)byte;
    }
    return d;
}

static void complete_synthetic(struct hk_android_evidence *e)
{
    memset(e, 0, sizeof(*e));
    e->abi = HK_ANDROID_ABI;
    e->bytes = sizeof(*e);
    e->runtime_enable = 1;
    e->scope = HK_ANDROID_ACTUAL_CURRENT;
    e->reference_artifacts = hex_digest("5602d21e13c15de69730ea223baaa90982cd3c036556b4db481a3b7ffda5423c");
    e->reference_archive = hex_digest("9ac046a4275f1a5032cb6e7768de349d8b01811c0de7b41fc259a178f5fde40c");
    e->current.identity.boot_nonce = 0xf00d;
    e->current.identity.boot_entry = 1;
    e->current.identity.capture_generation = 19;
    e->current.identity.device = synthetic_digest(1);
    e->current.identity.temporary_image = synthetic_digest(2);
    e->current.identity.capture = synthetic_digest(3);
    e->current.identity.gpt = synthetic_digest(4);
    e->current.latest_sequence = 4;
    e->current.fdt_pa = 0x100000;
    e->current.fdt_bytes = 0x1000;
    e->current.executing_shim = (struct hk_android_range){0x110000, 0x1000};
    e->current.abl_initrd = (struct hk_android_range){0x120000, 0x1000};
    e->current.boot_mpidr = 0x102;
    e->current.active_slot = 'a';
    e->current.selected_slot = 'a';
    e->current.fdt = synthetic_digest(5);
    e->current.slot_selection = synthetic_digest(6);
    for (unsigned i = 0; i < HK_AR_COUNT; ++i) {
        e->receipts[i].kind = i;
        e->receipts[i].scope = HK_ANDROID_ACTUAL_CURRENT;
        e->receipts[i].sequence = 2;
        e->receipts[i].identity = e->current.identity;
        e->receipts[i].payload = synthetic_digest(20+i);
    }
    e->receipts[HK_AR_CAPTURE].sequence = 1;
    e->receipts[HK_AR_CAPTURE].payload = e->current.identity.capture;
    e->receipts[HK_AR_GPT_SLOT].payload = e->current.identity.gpt;
    e->receipts[HK_AR_PREPARED_BYTES].sequence = 3;
    e->receipts[HK_AR_CPU].sequence = 4;
    e->receipts[HK_AR_QUIESCENCE].sequence = 4;
    e->source_count = HK_ANDROID_SOURCE_COUNT;
    for (unsigned i = 0; i < e->source_count; ++i) {
        const struct hk_android_source_pin *p = hk_android_source_pin(i);
        e->sources[i].id = i;
        e->sources[i].slot = 'a';
        e->sources[i].bytes = p->bytes;
        e->sources[i].capture_generation = e->current.identity.capture_generation;
        e->sources[i].sha256 = p->sha256;
        e->sources[i].capture_receipt = synthetic_digest(50+i);
        e->sources[i].partition_identity = synthetic_digest(90+i);
    }
    e->avb.node_count = 5;
    e->avb.signed_nodes = 5;
    e->avb.chains = 4;
    e->avb.hashes = 28;
    e->avb.hashtrees = 6;
    e->avb.configured_root = hex_digest("244baaf78d0fee555a562fdd3f70ef61036492fba7ad192b83bb8d427e380b17");
    e->avb.current_graph = e->receipts[HK_AR_AVB_GRAPH].payload;
    e->avb.root_rollback_manifest = e->receipts[HK_AR_ROOT_ROLLBACK].payload;
    const unsigned source_ids[5] = {HK_A_VBMETA, HK_A_BOOT, HK_A_INIT_BOOT, HK_A_VBMETA_SYSTEM, HK_A_VBMETA_VENDOR};
    const unsigned locations[5] = {0, 2, 4, 1, 3};
    for (unsigned i = 0; i < 5; ++i) {
        e->avb.nodes[i].source_id = source_ids[i];
        e->avb.nodes[i].rollback_location = locations[i];
        e->avb.nodes[i].image_rollback = 1791158400;
        e->avb.nodes[i].protected_rollback = 1791158399;
        e->avb.nodes[i].key = i == 3 ?
            hex_digest("4f4e0de312557832cbf792f571d50003e9cf18ab205cf43101dad7c3d18d5a2f") : e->avb.configured_root;
    }
    /* Deliberately synthetic policy: this example chooses indexes in host
     * memory. It is NOT a suggested board/fragment/overlay choice for blazer. */
    e->selection.kernel_component = HK_A_KERNEL;
    e->selection.ramdisk_count = 3;
    e->selection.ramdisk_components[0] = HK_A_VENDOR_KERNEL_PLATFORM_RAMDISK;
    e->selection.ramdisk_components[1] = HK_A_VENDOR_PLATFORM_RAMDISK;
    e->selection.ramdisk_components[2] = HK_A_GENERIC_RAMDISK;
    e->selection.dtb_index = 1;
    e->selection.overlay_count = 2;
    e->selection.overlays[0] = 8;
    e->selection.overlays[1] = 32;
    e->selection.actual_board = synthetic_digest(140);
    e->selection.abl_selection_rule = synthetic_digest(141);
    e->selection.selection_manifest = e->receipts[HK_AR_BOARD_SELECTION].payload;
    e->selection.source_dtb = hk_android_component_pin(HK_A_DTB_BLOB)->sha256;
    e->selection.source_dtbo = hk_android_source_pin(HK_A_DTBO)->sha256;
    e->output.kernel = (struct hk_android_range){0x20000000, 0x4000000};
    uint64_t payload = 0;
    for (unsigned i = 0; i < e->selection.ramdisk_count; ++i)
        payload += hk_android_component_pin(e->selection.ramdisk_components[i])->bytes;
    e->output.initrd_payload_bytes = payload;
    e->output.bootconfig_offset = payload;
    e->output.bootconfig_bytes = 512;
    e->output.initrd = (struct hk_android_range){0x30000000, payload+512+20};
    e->output.dtb = (struct hk_android_range){0x40000000, 0x10000};
    e->output.entry_pa = e->output.kernel.base;
    e->output.dtb_initrd_start = e->output.initrd.base;
    e->output.dtb_initrd_end = e->output.initrd.base+e->output.initrd.size;
    e->output.dtb_slot = 'a';
    e->output.kernel_sha256 = synthetic_digest(142);
    e->output.initrd_sha256 = synthetic_digest(143);
    e->output.dtb_sha256 = synthetic_digest(144);
    e->output.prepared_manifest = e->receipts[HK_AR_PREPARED_BYTES].payload;
    e->output.final_dtb_manifest = e->receipts[HK_AR_FINAL_DTB].payload;
    e->output.bootconfig_sha256 = synthetic_digest(145);
    e->output.bootconfig_manifest = e->receipts[HK_AR_BOOTCONFIG].payload;
    e->memory.ram_count = 1;
    e->memory.ram[0] = (struct hk_android_range){0, UINT64_C(0x100000000)};
    e->memory.reservation_count = 1;
    e->memory.reservations[0] = (struct hk_android_range){0x80000000, 0x100000};
    e->memory.resident_count = 3;
    e->memory.residents[0] = (struct hk_android_range){e->current.fdt_pa, e->current.fdt_bytes};
    e->memory.residents[1] = e->current.executing_shim;
    e->memory.residents[2] = e->current.abl_initrd;
    e->memory.current_fdt = e->current.fdt;
    e->memory.ram_manifest = e->receipts[HK_AR_MEMORY].payload;
    e->memory.reservation_manifest = synthetic_digest(146);
    e->memory.resident_manifest = synthetic_digest(147);
    e->output.dtb_memory_manifest = e->memory.ram_manifest;
    e->output.dtb_reservation_manifest = e->memory.reservation_manifest;
    e->storage.block_bytes = 4096;
    e->storage.lun_count = 2;
    e->storage.luns[0] = (struct hk_android_lun){0, 0, 0x100000};
    e->storage.luns[1] = (struct hk_android_lun){2, 0, 0x100000};
    e->storage.android_count = 1;
    e->storage.android[0] = (struct hk_android_extent){0, 0, 0, 0x10000};
    e->storage.ios_root_count = 1;
    e->storage.ios_root[0] = (struct hk_android_extent){2, 0, 0, 0x20000};
    e->storage.ios_data_count = 1;
    e->storage.ios_data[0] = (struct hk_android_extent){2, 0, 0x20000, 0x10000};
    e->storage.alias_ownership = synthetic_digest(148);
    e->storage.android_integrity = synthetic_digest(149);
    e->storage.allocation_manifest = e->receipts[HK_AR_STORAGE_ISOLATION].payload;
    e->backup.required_raw_bytes = UINT64_C(0x200000)*4096;
    e->backup.verified_raw_bytes = e->backup.required_raw_bytes;
    e->backup.raw_manifest = e->receipts[HK_AR_BACKUP_RAW].payload;
    e->backup.independent_destination = synthetic_digest(150);
    e->backup.readable_user_recovery = e->receipts[HK_AR_BACKUP_USER].payload;
    e->backup.encryption_key_recovery = e->receipts[HK_AR_BACKUP_KEYS].payload;
    e->backup.rollback_procedure = synthetic_digest(151);
    e->cpu.boot_mpidr = e->current.boot_mpidr;
    e->cpu.current_el = 8;
    e->cpu.sctlr = UINT64_C(1) << 12; /* I-cache may be on; M/C/EE must be off. */
    e->cpu.daif = 0x3c0;
    e->cpu.count = 2;
    e->cpu.cpus[0] = (struct hk_android_cpu_observation){0x102, HK_ANDROID_CPU_BOOT, 0};
    e->cpu.cpus[1] = (struct hk_android_cpu_observation){0x206, HK_ANDROID_CPU_HELD, 0};
    e->cpu.errata_requirements = synthetic_digest(152);
    e->cpu.errata_acceptance = synthetic_digest(153);
    e->cpu.cache_maintenance = synthetic_digest(154);
    e->cpu.context_manifest = e->receipts[HK_AR_CPU].payload;
    e->firmware.running_identity = e->receipts[HK_AR_FIRMWARE_IDENTITY].payload;
    e->firmware.secure_state = synthetic_digest(155);
    e->firmware.trusty_state = synthetic_digest(156);
    e->firmware.dma_inventory = synthetic_digest(157);
    e->firmware.ufs_quiet = synthetic_digest(158);
    e->firmware.usb_quiet = synthetic_digest(159);
    e->firmware.display_quiet = synthetic_digest(160);
    e->firmware.interrupts_quiet = synthetic_digest(161);
    e->firmware.watchdog_contract = synthetic_digest(162);
    e->firmware.quiescence_manifest = e->receipts[HK_AR_QUIESCENCE].payload;
}

static enum hk_android_result evaluate(const struct hk_android_evidence *e)
{
    return hk_android_prepare(e);
}
#endif

int main(void)
{
    static struct hk_android_evidence base, changed;
#if !HK_ANDROID_HANDOFF
    memset(&base, 0xff, sizeof(base));
    CHECK(hk_android_prepare(0) == HK_ANDROID_DISABLED);
    CHECK(hk_android_prepare(&base) == HK_ANDROID_DISABLED);
    CHECK(hk_android_source_pin(0) == 0);
    CHECK(hk_android_component_pin(0) == 0);
    CHECK(hk_android_dtb_pin(0) == 0);
    CHECK(hk_android_dtbo_pin(0) == 0);
    CHECK(hk_android_dtb_count() == 0);
    CHECK(hk_android_dtbo_count() == 0);
    (void)changed;
    (void)synthetic_digest;
    printf("{\"gate\":0,\"checks\":%u,\"result\":\"DISABLED\",\"physical_acceptance\":false}\n", checks);
    return 0;
#else
    complete_synthetic(&base);
    struct synthetic_verifier_context verifier_context = {&base, 0, 0};
    const struct hk_android_producer verifier = {HK_ANDROID_ABI, HK_ANDROID_ACTUAL_CURRENT,
                                                synthetic_verify, &verifier_context};
    base.producer = &verifier;
    CHECK(evaluate(0) == HK_ANDROID_CURRENT_REQUIRED);
    CHECK(hk_android_dtb_count() == 2);
    CHECK(hk_android_dtbo_count() == 34);
    CHECK(hk_android_source_pin(HK_ANDROID_SOURCE_COUNT) == 0);
    CHECK(hk_android_source_pin(UINT32_MAX) == 0);
    CHECK(hk_android_component_pin(HK_ANDROID_COMPONENT_COUNT) == 0);
    CHECK(hk_android_dtb_pin(2) == 0);
    CHECK(hk_android_dtbo_pin(34) == 0);
    CHECK(evaluate(&base) == HK_ANDROID_PREPARED);
    CHECK(verifier_context.calls == HK_AR_COUNT);
    /* The complete structure is preserved byte-for-byte by the validator. */
    changed = base;
    CHECK(evaluate(&changed) == HK_ANDROID_PREPARED);
    CHECK(memcmp(&base, &changed, sizeof(base)) == 0);
#define REJECT(statement, result) do { changed = base; statement; CHECK(evaluate(&changed) == (result)); } while (0)
    REJECT(changed.abi++, HK_ANDROID_BAD_INPUT);
    REJECT(changed.bytes--, HK_ANDROID_BAD_INPUT);
    REJECT(changed.runtime_enable = 2, HK_ANDROID_BAD_INPUT);
    REJECT(changed.producer = 0, HK_ANDROID_EVIDENCE_REQUIRED);
    REJECT(changed.reserved = 1, HK_ANDROID_BAD_INPUT);
    REJECT(changed.scope = HK_ANDROID_REFERENCE_ONLY, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.identity.boot_nonce = 0, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.active_slot = 0, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.selected_slot = 0, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.slot_selection = (struct hk_android_sha256){{0}}, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.fdt_pa = UINT64_MAX-7, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.fdt_bytes = 2u*1024u*1024u+1u, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.executing_shim.size = 0, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.current.abl_initrd.size = 0, HK_ANDROID_CURRENT_REQUIRED);
    REJECT(changed.reference_archive.bytes[4] ^= 1, HK_ANDROID_REFERENCE_MISMATCH);
    REJECT(changed.reference_artifacts.bytes[4] ^= 1, HK_ANDROID_REFERENCE_MISMATCH);
    REJECT(changed.source_count--, HK_ANDROID_SOURCE_REQUIRED);
    for (unsigned i = 0; i < HK_ANDROID_SOURCE_COUNT; ++i) {
        REJECT(changed.sources[i].id = UINT32_MAX, HK_ANDROID_SOURCE_REQUIRED);
        REJECT(changed.sources[i].bytes--, HK_ANDROID_SOURCE_REQUIRED);
        REJECT(changed.sources[i].sha256.bytes[i%32] ^= 1, HK_ANDROID_SOURCE_REQUIRED);
        REJECT(changed.sources[i].slot = 'b', HK_ANDROID_SOURCE_REQUIRED);
        REJECT(changed.sources[i].capture_generation--, HK_ANDROID_SOURCE_REQUIRED);
        REJECT(changed.sources[i].capture_receipt = (struct hk_android_sha256){{0}}, HK_ANDROID_SOURCE_REQUIRED);
        REJECT(changed.sources[i].partition_identity = (struct hk_android_sha256){{0}}, HK_ANDROID_SOURCE_REQUIRED);
    }
    REJECT(changed.avb.configured_root.bytes[2] ^= 1, HK_ANDROID_AVB_REQUIRED);
    REJECT(changed.avb.flags = 2, HK_ANDROID_AVB_REQUIRED);
    REJECT(changed.avb.hashes--, HK_ANDROID_AVB_REQUIRED);
    REJECT(changed.avb.hashtrees--, HK_ANDROID_AVB_REQUIRED);
    for (unsigned i = 0; i < 5; ++i) {
        REJECT(changed.avb.nodes[i].key.bytes[7] ^= 1, HK_ANDROID_AVB_REQUIRED);
        REJECT(changed.avb.nodes[i].rollback_location ^= 1, HK_ANDROID_AVB_REQUIRED);
        REJECT(changed.avb.nodes[i].image_rollback--, HK_ANDROID_AVB_REQUIRED);
        REJECT(changed.avb.nodes[i].protected_rollback = UINT64_MAX, HK_ANDROID_AVB_REQUIRED);
    }
    REJECT(changed.selection.kernel_component = 99, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.ramdisk_count = 0, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.ramdisk_count = UINT32_MAX, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.ramdisk_components[1] = changed.selection.ramdisk_components[0], HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.ramdisk_components[2] = HK_A_VENDOR_16K_RAMDISK, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.ramdisk_components[3] = HK_A_VENDOR_16K_RAMDISK, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.dtb_index = 2, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.overlay_count = 0, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.overlay_count = UINT32_MAX, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.overlays[0] = 34, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.overlays[1] = changed.selection.overlays[0], HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.overlays[2] = 31, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.actual_board = (struct hk_android_sha256){{0}}, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.abl_selection_rule = (struct hk_android_sha256){{0}}, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.source_dtb.bytes[0] ^= 1, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.source_dtbo.bytes[0] ^= 1, HK_ANDROID_SELECTION_REQUIRED);
    REJECT(changed.selection.ramdisk_components[0] = base.selection.ramdisk_components[1];
           changed.selection.ramdisk_components[1] = base.selection.ramdisk_components[0], HK_ANDROID_EVIDENCE_REQUIRED);
    REJECT(changed.selection.overlays[0] = base.selection.overlays[1];
           changed.selection.overlays[1] = base.selection.overlays[0], HK_ANDROID_EVIDENCE_REQUIRED);
    REJECT(changed.output.entry_pa = changed.output.kernel.base+changed.output.kernel.size, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.kernel.base = UINT64_MAX-3, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.initrd.base = UINT64_MAX-3, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.dtb.base |= 1, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.initrd_payload_bytes++, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.bootconfig_offset = UINT64_MAX, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.bootconfig_offset--, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.bootconfig_bytes = UINT64_MAX, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.kernel_sha256 = (struct hk_android_sha256){{0}}, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.dtb_initrd_end++, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.output.dtb_slot = 'b', HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.memory.ram_count = UINT32_MAX, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.reservation_count = UINT32_MAX, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.resident_count = UINT32_MAX, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.unresolved_reservations = 1, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.current_fdt.bytes[0] ^= 1, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.ram[0].size = changed.output.kernel.base, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.reservations[0] = changed.output.initrd, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.reservations[0].size = UINT64_MAX, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.resident_count = 2, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.memory.residents[1] = changed.memory.residents[0], HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.output.dtb.base = changed.output.initrd.base, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.output.dtb_reservation_manifest.bytes[0] ^= 1, HK_ANDROID_MEMORY_REQUIRED);
    REJECT(changed.storage.lun_count = UINT32_MAX, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.android_count = UINT32_MAX, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.ios_root_count = UINT32_MAX, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.ios_data_count = UINT32_MAX, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.alias_ownership = (struct hk_android_sha256){{0}}, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.android_integrity = (struct hk_android_sha256){{0}}, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.luns[1].id = changed.storage.luns[0].id, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.luns[0].blocks = UINT64_MAX, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.ios_root[0].lba = UINT64_MAX, HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.ios_data[0] = changed.storage.android[0], HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.ios_root[0] = changed.storage.android[0], HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.storage.ios_data[0] = changed.storage.ios_root[0], HK_ANDROID_ISOLATION_REQUIRED);
    REJECT(changed.backup.verified_raw_bytes--, HK_ANDROID_BACKUP_REQUIRED);
    REJECT(changed.backup.required_raw_bytes--, HK_ANDROID_BACKUP_REQUIRED);
    REJECT(changed.backup.independent_destination = (struct hk_android_sha256){{0}}, HK_ANDROID_BACKUP_REQUIRED);
    REJECT(changed.backup.readable_user_recovery = (struct hk_android_sha256){{0}}, HK_ANDROID_BACKUP_REQUIRED);
    REJECT(changed.backup.encryption_key_recovery = (struct hk_android_sha256){{0}}, HK_ANDROID_BACKUP_REQUIRED);
    REJECT(changed.backup.rollback_procedure = (struct hk_android_sha256){{0}}, HK_ANDROID_BACKUP_REQUIRED);
    REJECT(changed.cpu.boot_mpidr ^= 1, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.current_el = 12, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.sctlr |= 1, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.sctlr |= 4, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.sctlr |= UINT64_C(1) << 25, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.daif = 0, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.count = UINT32_MAX, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.cpus[0].state = HK_ANDROID_CPU_HELD, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.cpus[1].state = HK_ANDROID_CPU_BOOT, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.cpus[1].mpidr = changed.cpu.cpus[0].mpidr, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.errata_acceptance = (struct hk_android_sha256){{0}}, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.cpu.cache_maintenance = (struct hk_android_sha256){{0}}, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.firmware.running_identity = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.trusty_state = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.secure_state = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.dma_inventory = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.ufs_quiet = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.usb_quiet = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.display_quiet = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.interrupts_quiet = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.firmware.watchdog_contract = (struct hk_android_sha256){{0}}, HK_ANDROID_QUIESCENCE_REQUIRED);
    REJECT(changed.output.initrd_sha256.bytes[0] ^= 1, HK_ANDROID_EVIDENCE_REQUIRED);
    REJECT(changed.current.slot_selection.bytes[0] ^= 1, HK_ANDROID_EVIDENCE_REQUIRED);
    verifier_context.forced_result = 2;
    CHECK(evaluate(&base) == HK_ANDROID_EVIDENCE_REQUIRED);
    verifier_context.forced_result = -1;
    CHECK(evaluate(&base) == HK_ANDROID_EVIDENCE_REQUIRED);
    verifier_context.forced_result = 0;
    /* Every domain must cite the same exact attempt; stale/mixed identities
     * and reference-only receipt reuse are refused in every one of 16 roles. */
    for (unsigned i = 0; i < HK_AR_COUNT; ++i) {
        changed = base;
        changed.receipts[i].identity.temporary_image.bytes[0] ^= 1;
        CHECK(evaluate(&changed) != HK_ANDROID_PREPARED);
        changed = base;
        changed.receipts[i].scope = HK_ANDROID_REFERENCE_ONLY;
        CHECK(evaluate(&changed) != HK_ANDROID_PREPARED);
        changed = base;
        changed.receipts[i].identity.capture_generation++;
        CHECK(evaluate(&changed) != HK_ANDROID_PREPARED);
        changed = base;
        changed.receipts[i].sequence = base.current.latest_sequence+1;
        CHECK(evaluate(&changed) != HK_ANDROID_PREPARED);
        changed = base;
        changed.receipts[i].payload = (struct hk_android_sha256){{0}};
        CHECK(evaluate(&changed) != HK_ANDROID_PREPARED);
    }
    REJECT(changed.receipts[HK_AR_PREPARED_BYTES].sequence = 1, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    REJECT(changed.receipts[HK_AR_CPU].sequence = 3, HK_ANDROID_CPU_REQUIRED);
    REJECT(changed.receipts[HK_AR_QUIESCENCE].sequence = 3, HK_ANDROID_PREPARED_BYTES_REQUIRED);
    /* Gate accepts no physical authority from the Google reference alone. */
    memset(&changed, 0, sizeof(changed));
    changed.abi = HK_ANDROID_ABI;
    changed.bytes = sizeof(changed);
    changed.runtime_enable = 1;
    changed.scope = HK_ANDROID_REFERENCE_ONLY;
    changed.reference_archive = base.reference_archive;
    changed.reference_artifacts = base.reference_artifacts;
    changed.source_count = base.source_count;
    memcpy(changed.sources, base.sources, sizeof(changed.sources));
    CHECK(evaluate(&changed) == HK_ANDROID_CURRENT_REQUIRED);
    CHECK(strstr(hk_android_result_name(HK_ANDROID_PREPARED), "dispatch unavailable") != 0);
    CHECK(strstr(hk_android_result_name((enum hk_android_result)UINT32_MAX), "unknown") != 0);
    /* Bounded count fuzzing, independent of the known negative examples. */
    uint32_t rng = 0x12f00d34;
    for (unsigned i = 0; i < 20000; ++i) {
        rng = rng*1664525u+1013904223u;
        changed = base;
        switch (i%8) {
        case 0: changed.source_count = rng; break;
        case 1: changed.selection.ramdisk_count = rng; break;
        case 2: changed.selection.overlay_count = rng; break;
        case 3: changed.memory.ram_count = rng; break;
        case 4: changed.memory.reservation_count = rng; break;
        case 5: changed.memory.resident_count = rng; break;
        case 6: changed.storage.lun_count = rng; break;
        case 7: changed.cpu.count = rng; break;
        }
        CHECK(evaluate(&changed) != HK_ANDROID_PREPARED);
    }
    printf("{\"gate\":1,\"checks\":%u,\"fixture\":\"complete explicit SYNTHETIC\",\"result\":\"PREPARED ONLY\",\"reference_only\":\"CURRENT_REQUIRED\",\"physical_acceptance\":false,\"dispatch\":false}\n", checks);
    return 0;
#endif
}
