/* SPDX-License-Identifier: MIT
 * Original host-reviewed Android preparation contract. No I/O or dispatch.
 * This API consumes trusted, independently verified producer observations;
 * nonzero receipt hashes are identities, not signatures or evidence verifiers.
 */
#ifndef HK_ANDROID_HANDOFF_H
#define HK_ANDROID_HANDOFF_H
#include <stdint.h>

#ifndef HK_ANDROID_HANDOFF
#define HK_ANDROID_HANDOFF 0
#endif
#if HK_ANDROID_HANDOFF != 0 && HK_ANDROID_HANDOFF != 1
#error HK_ANDROID_HANDOFF must be 0 or 1
#endif

#define HK_ANDROID_ABI 1u
#define HK_ANDROID_SOURCE_COUNT 37u
#define HK_ANDROID_COMPONENT_COUNT 8u
#define HK_ANDROID_MAX_DTBS 8u
#define HK_ANDROID_MAX_OVERLAYS 8u
#define HK_ANDROID_MAX_RAM 32u
#define HK_ANDROID_MAX_RESERVATIONS 256u
#define HK_ANDROID_MAX_RESIDENTS 32u
#define HK_ANDROID_MAX_CPUS 16u
#define HK_ANDROID_MAX_LUNS 8u
#define HK_ANDROID_MAX_EXTENTS 16u

struct hk_android_sha256 { uint8_t bytes[32]; };
struct hk_android_range { uint64_t base, size; };
enum hk_android_result {
    HK_ANDROID_DISABLED = 0, HK_ANDROID_BAD_INPUT, HK_ANDROID_CURRENT_REQUIRED,
    HK_ANDROID_REFERENCE_MISMATCH, HK_ANDROID_SOURCE_REQUIRED,
    HK_ANDROID_AVB_REQUIRED, HK_ANDROID_SELECTION_REQUIRED,
    HK_ANDROID_PREPARED_BYTES_REQUIRED, HK_ANDROID_MEMORY_REQUIRED,
    HK_ANDROID_BACKUP_REQUIRED, HK_ANDROID_ISOLATION_REQUIRED,
    HK_ANDROID_CPU_REQUIRED, HK_ANDROID_QUIESCENCE_REQUIRED, HK_ANDROID_EVIDENCE_REQUIRED,
    HK_ANDROID_PREPARED
};
enum hk_android_scope { HK_ANDROID_REFERENCE_ONLY = 1, HK_ANDROID_ACTUAL_CURRENT = 2 };
enum hk_android_source_id {
    HK_A_BOOT, HK_A_INIT_BOOT, HK_A_VENDOR_BOOT, HK_A_VENDOR_KERNEL_BOOT,
    HK_A_DTBO, HK_A_VBMETA, HK_A_VBMETA_SYSTEM, HK_A_VBMETA_VENDOR
};
enum hk_android_component_id {
    HK_A_KERNEL, HK_A_GENERIC_RAMDISK, HK_A_VENDOR_PLATFORM_RAMDISK,
    HK_A_VENDOR_16K_RAMDISK, HK_A_VENDOR_KERNEL_PLATFORM_RAMDISK,
    HK_A_VENDOR_BOOTCONFIG, HK_A_VENDOR_KERNEL_BOOTCONFIG, HK_A_DTB_BLOB
};
enum hk_android_receipt_kind {
    HK_AR_CAPTURE = 0, HK_AR_GPT_SLOT, HK_AR_AVB_GRAPH, HK_AR_ROOT_ROLLBACK,
    HK_AR_BOARD_SELECTION, HK_AR_PREPARED_BYTES, HK_AR_FINAL_DTB,
    HK_AR_BOOTCONFIG, HK_AR_MEMORY, HK_AR_BACKUP_RAW, HK_AR_BACKUP_USER,
    HK_AR_BACKUP_KEYS, HK_AR_STORAGE_ISOLATION, HK_AR_CPU,
    HK_AR_FIRMWARE_IDENTITY, HK_AR_QUIESCENCE, HK_AR_COUNT
};

/* All receipts are normalized by a trusted producer to ONE current attempt.
 * Older backup evidence may be cited by payload hash, but must be reviewed
 * against this current capture/GPT/device before acquiring this binding.
 * No code here can create a receipt from an untrusted caller assertion.
 */
struct hk_android_identity {
    uint64_t boot_nonce, boot_entry, capture_generation;
    struct hk_android_sha256 device, temporary_image, capture, gpt;
};
struct hk_android_receipt {
    uint32_t kind, scope;
    uint64_t sequence;
    struct hk_android_identity identity;
    struct hk_android_sha256 payload;
};
struct hk_android_current {
    struct hk_android_identity identity;
    uint64_t latest_sequence, fdt_pa, fdt_bytes, boot_mpidr;
    struct hk_android_range executing_shim, abl_initrd;
    uint32_t active_slot, selected_slot; /* ASCII 'a' or 'b', explicitly observed/selected */
    struct hk_android_sha256 fdt, slot_selection;
};
struct hk_android_source_pin {
    char file[32];
    uint64_t bytes;
    uint32_t header_version, page_size;
    struct hk_android_sha256 sha256;
};
struct hk_android_component_pin {
    uint32_t source_id, fragment_type, fragment_index, reserved;
    uint64_t offset, bytes;
    char fragment_name[8];
    uint32_t board_id[16];
    struct hk_android_sha256 sha256;
};
struct hk_android_tree_pin {
    uint64_t offset, bytes;
    uint32_t id, revision, custom[4];
    struct hk_android_sha256 sha256;
};
struct hk_android_source {
    uint32_t id, slot;
    uint64_t bytes, capture_generation;
    struct hk_android_sha256 sha256, capture_receipt, partition_identity;
};
struct hk_android_avb_node {
    uint32_t source_id, rollback_location;
    uint64_t image_rollback, protected_rollback;
    struct hk_android_sha256 key;
};
struct hk_android_avb {
    uint32_t node_count, signed_nodes, chains, hashes, hashtrees, flags;
    struct hk_android_sha256 configured_root, current_graph, root_rollback_manifest;
    struct hk_android_avb_node nodes[5];
};

/* Selection is supplied, never discovered by a fragment name, slot filename,
 * board ID guess or table order. The board receipt must bind the actual ABL
 * rule/current board, the complete ordered list and final output identities.
 * The separate kernel_16k is intentionally outside this first pinned recipe.
 */
struct hk_android_selection {
    uint32_t kernel_component, ramdisk_count, dtb_index, overlay_count;
    uint32_t ramdisk_components[4], overlays[HK_ANDROID_MAX_OVERLAYS];
    struct hk_android_sha256 actual_board, abl_selection_rule, selection_manifest;
    struct hk_android_sha256 source_dtb, source_dtbo;
};
struct hk_android_output {
    struct hk_android_range kernel, initrd, dtb;
    uint64_t entry_pa, initrd_payload_bytes;
    uint64_t bootconfig_offset, bootconfig_bytes;
    uint64_t dtb_initrd_start, dtb_initrd_end;
    uint32_t dtb_slot, reserved;
    struct hk_android_sha256 kernel_sha256, initrd_sha256, dtb_sha256;
    struct hk_android_sha256 prepared_manifest, final_dtb_manifest;
    struct hk_android_sha256 bootconfig_sha256, bootconfig_manifest;
    struct hk_android_sha256 dtb_memory_manifest, dtb_reservation_manifest;
};
struct hk_android_memory {
    uint32_t ram_count, reservation_count, resident_count, unresolved_reservations;
    struct hk_android_range ram[HK_ANDROID_MAX_RAM];
    struct hk_android_range reservations[HK_ANDROID_MAX_RESERVATIONS];
    struct hk_android_range residents[HK_ANDROID_MAX_RESIDENTS];
    struct hk_android_sha256 current_fdt, ram_manifest, reservation_manifest, resident_manifest;
};
struct hk_android_backup {
    uint64_t required_raw_bytes, verified_raw_bytes;
    struct hk_android_sha256 raw_manifest, independent_destination;
    struct hk_android_sha256 readable_user_recovery, encryption_key_recovery;
    struct hk_android_sha256 rollback_procedure;
};
struct hk_android_lun { uint32_t id, reserved; uint64_t blocks; };
struct hk_android_extent { uint32_t lun, reserved; uint64_t lba, blocks; };
struct hk_android_storage {
    uint32_t block_bytes, lun_count, android_count, ios_root_count, ios_data_count;
    uint32_t reserved[3];
    struct hk_android_lun luns[HK_ANDROID_MAX_LUNS];
    struct hk_android_extent android[HK_ANDROID_MAX_EXTENTS];
    struct hk_android_extent ios_root[HK_ANDROID_MAX_EXTENTS];
    struct hk_android_extent ios_data[HK_ANDROID_MAX_EXTENTS];
    struct hk_android_sha256 alias_ownership, android_integrity, allocation_manifest;
};
enum hk_android_cpu_state { HK_ANDROID_CPU_BOOT = 1, HK_ANDROID_CPU_HELD = 2 };
struct hk_android_cpu_observation { uint64_t mpidr; uint32_t state, reserved; };
struct hk_android_cpu {
    uint64_t boot_mpidr, current_el, sctlr, daif;
    uint32_t count, reserved;
    struct hk_android_cpu_observation cpus[HK_ANDROID_MAX_CPUS];
    struct hk_android_sha256 errata_requirements, errata_acceptance;
    struct hk_android_sha256 cache_maintenance, context_manifest;
};
struct hk_android_firmware {
    struct hk_android_sha256 running_identity, secure_state, trusty_state;
    struct hk_android_sha256 dma_inventory, ufs_quiet, usb_quiet, display_quiet;
    struct hk_android_sha256 interrupts_quiet, watchdog_contract;
    struct hk_android_sha256 quiescence_manifest;
};
struct hk_android_evidence;
struct hk_android_producer {
    uint32_t abi, scope;
    /* Invoked for every domain after structural checks, not an accepted bit.
     * Exact 1 means the producer verified the actual immutable payload AND
     * every field it binds (including list ordering, output digests and live
     * identity) against its independently obtained current observations.
     * Production code has no such producer yet. A host test verifier is not
     * a runtime producer and is never copied to a shim fixture.
     */
    int (*verify)(void *context, const struct hk_android_evidence *, enum hk_android_receipt_kind);
    void *context;
};
struct hk_android_evidence {
    uint32_t abi, bytes, runtime_enable, scope;
    const struct hk_android_producer *producer; /* trusted caller object; never a wire field */
    struct hk_android_sha256 reference_artifacts, reference_archive;
    struct hk_android_current current;
    struct hk_android_receipt receipts[HK_AR_COUNT];
    uint32_t source_count, reserved;
    struct hk_android_source sources[HK_ANDROID_SOURCE_COUNT];
    struct hk_android_avb avb;
    struct hk_android_selection selection;
    struct hk_android_output output;
    struct hk_android_memory memory;
    struct hk_android_backup backup;
    struct hk_android_storage storage;
    struct hk_android_cpu cpu;
    struct hk_android_firmware firmware;
};

/* PREPARED is a consistency result only; it grants no authority/capability to
 * jump, change CPU/Trusty state, write storage, set slots or reset firmware.
 * No actual runtime producer or Android dispatcher exists in this package.
 * Inputs must remain immutable while checked. A future dispatcher must own
 * and revalidate the machine state immediately before its separately reviewed
 * handoff. NEVER deserialize arbitrary JSON into this trusted interface.
 */
enum hk_android_result hk_android_prepare(const struct hk_android_evidence *);
const char *hk_android_result_name(enum hk_android_result);
const struct hk_android_source_pin *hk_android_source_pin(uint32_t);
const struct hk_android_component_pin *hk_android_component_pin(uint32_t);
const struct hk_android_tree_pin *hk_android_dtb_pin(uint32_t);
const struct hk_android_tree_pin *hk_android_dtbo_pin(uint32_t);
uint32_t hk_android_dtb_count(void);
uint32_t hk_android_dtbo_count(void);
#endif
