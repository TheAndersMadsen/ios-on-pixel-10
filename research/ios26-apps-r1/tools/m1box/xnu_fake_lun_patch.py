"""Apply the QEMU-only fake-LUN mode to the release XNU tree (run in research/ios26-release-r1/work/xnu).
boot-arg blazer_ufs_fake_lun=1 (with blazer_ufs_fake/_size): the fake memory is a whole LUN with its own GPT; fake reads
and writes use absolute LBAs; attach resolves the root partition from that GPT (ufs_find_partition) instead of the
pinned phone value; the persist code resolves ios_data from that GPT instead of refusing. Without the boot-arg, nothing
changes. The phone never sets blazer_ufs_fake, so this path cannot run there."""
import pathlib, sys
U = pathlib.Path('bsd/dev/hakios.blazer_ufs.c'); I = pathlib.Path('bsd/dev/hakios.blazer_persist_disk.inc')
u = U.read_text(); i = I.read_text()

def rep(s, old, new, n=1):
    assert s.count(old) == n, (old[:80], s.count(old))
    return s.replace(old, new)

u = rep(u, "static const uint8_t *ufs_fake;\n",
        "static const uint8_t *ufs_fake;\n"
        "/* QEMU only (blazer_ufs_fake_lun=1): the fake memory is a whole LUN with a GPT, addressed by absolute LBA. */\n"
        "static uint32_t ufs_fake_lun;\n"
        "#define UFS_FAKE_BASE  (ufs_fake_lun ? 0 : ufs.first_block)\n")
u = rep(u, "\t\tif (lba < ufs.first_block || (lba - ufs.first_block) * UFS_BLOCK >= ufs_fake_bytes) {\n"
           "\t\t\tbzero(to, UFS_BLOCK);\n\t\t} else {\n"
           "\t\t\tmemcpy(to, ufs_fake + (lba - ufs.first_block) * UFS_BLOCK, UFS_BLOCK);\n",
        "\t\tif (lba < UFS_FAKE_BASE || (lba - UFS_FAKE_BASE) * UFS_BLOCK >= ufs_fake_bytes) {\n"
        "\t\t\tbzero(to, UFS_BLOCK);\n\t\t} else {\n"
        "\t\t\tmemcpy(to, ufs_fake + (lba - UFS_FAKE_BASE) * UFS_BLOCK, UFS_BLOCK);\n")
u = rep(u, "\tmemcpy((uint8_t *)(uintptr_t)ufs_fake + (absolute_lba - ufs.first_block) * UFS_BLOCK, from, (size_t)count * UFS_BLOCK);\n",
        "\tif (absolute_lba < UFS_FAKE_BASE || (absolute_lba - UFS_FAKE_BASE + count) * UFS_BLOCK > ufs_fake_bytes) {\n"
        "\t\tpanic(\"blazer-ufs: fake store outside the fake medium: lba %llu count %u\", absolute_lba, count);\n\t}\n"
        "\tmemcpy((uint8_t *)(uintptr_t)ufs_fake + (absolute_lba - UFS_FAKE_BASE) * UFS_BLOCK, from, (size_t)count * UFS_BLOCK);\n")
u = rep(u, "#define BP_FAKE                 (ufs_fake != NULL)\n",
        "#define BP_FAKE                 (ufs_fake != NULL)\n#define BP_FAKE_LUN             (ufs_fake != NULL && ufs_fake_lun != 0)\n")
u = rep(u, "\tif (ufs_fake != NULL) {\n\t\t/* The phone's values, so the view check in n892_xnu_selected_view is the same check. */\n"
           "\t\tufs.first_block = 2500838;\n",
        "\tif (ufs_fake != NULL && ufs_fake_lun) {\n"
        "\t\t/* QEMU fake LUN: the root partition comes from the fake medium's own GPT, as on the phone. */\n"
        "\t\terror = ufs_find_partition(want);\n"
        "\t} else if (ufs_fake != NULL) {\n\t\t/* The phone's values, so the view check in n892_xnu_selected_view is the same check. */\n"
        "\t\tufs.first_block = 2500838;\n")
u = rep(u, "\t\t\tprintf(\"blazer-root: FAKE device at %llx, %llu bytes, no MMIO\\n\", fake, ufs_fake_bytes);\n",
        "\t\t\t(void)PE_parse_boot_argn(\"blazer_ufs_fake_lun\", &ufs_fake_lun, sizeof(ufs_fake_lun));\n"
        "\t\t\tprintf(\"blazer-root: FAKE device at %llx, %llu bytes, no MMIO%s\\n\", fake, ufs_fake_bytes,\n"
        "\t\t\t    ufs_fake_lun ? \", whole LUN with GPT\" : \"\");\n")
i = rep(i, " * BP_FAKE_WRITE(lba, n, src).\n */\n",
        " * BP_FAKE_WRITE(lba, n, src), and optionally BP_FAKE_LUN (QEMU: the fake medium is a whole LUN with a GPT; default 0).\n */\n"
        "#ifndef BP_FAKE_LUN\n#define BP_FAKE_LUN 0\n#endif\n")
i = rep(i, "\tif (BP_FAKE) {\n\t\treturn \"the QEMU fake disk has no GPT\";\n\t}\n",
        "\tif (BP_FAKE && !BP_FAKE_LUN) {\n\t\treturn \"the QEMU fake disk has no GPT\";\n\t}\n")
U.write_text(u); I.write_text(i); print('patched')
