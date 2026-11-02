# Storage and dual boot

Scope: an on-device Android / iOS chooser on Pixel 10 Pro, Android untouched on slot b, iOS on
its own `ios_system` / `ios_data` partitions. The run brief is `GOAL.md`; receipts are in
`research/ios26-dualboot-r8/` and the owner packet is its `NEEDS-OWNER.md`.

## Current result (2026-11-02, run r8)

- **Physical, read-only (A0):** full LUN0 GPT captured. Both copies are CRC-valid, the
  phone's `sgdisk --verify` is clean, and there are 0 free LBAs. Strict `tools/dualboot.py`
  refuses it because the backup header block repeats the entry array after byte 92. That is
  device-written media content, kept as a FAIL; the validator is not relaxed.
- **Host (A4):** `tools/gpt_plan.py` plans the one attended migration: userdata keeps its first
  LBA and shrinks, and `ios_system` and `ios_data` are appended (8 MiB-aligned, project type
  GUID, entries 35 → 37). Bytes exist only for LBA 1..5 and the last five LBAs. 14 tests;
  `sgdisk -p/-v` clean on a 4K loop device.
- **Chooser (A2/A3):** `shim/chooser.c` (gate `TGL_CHOOSER=1`): 5 s countdown, stock lz4
  kernel embedded as a TGLLNX01 segment, lowest admissible 2 MiB placement, EL2 jump with
  x0 = FDT.
  - **QEMU:** the stock kernel starts at EL2.
  - **Physical t1:** chain works (stock 6.12.81, ABL's Magisk init_boot ramdisk, placement
    0xc9c00000). Android fails at vold: KeyMint -33 for the /data key, because the test-key
    boot footer changes the root of trust. Android then requested recovery.
  - chooser-v1-r3 transplants the stock boot vbmeta; it waits for an attended boot.
- The menu is not visible yet (the shim draws into plain RAM). The volume keys are not read.
  The decode takes 122 s with caches off.

## Remaining work, in order

1. Attended r3 boot. Pass: vold mounts /data, boot completes, and Android's `/proc/iomem`
   shows the kernel at the chooser's base.
2. Cached EL2 identity map for the decode; then the visible startup menu and the volume-key
   pad read, each as its own candidate.
3. A6 migration (attended, packet), then A7: `ios_system` flash and an XNU writer bound to
   `ios_data` with an in-kernel allowlist.
4. A8: flash `boot_b` with the final chooser; ten alternating cold boots.

## Rules that stay

No write to any Android-owned extent; every write has a verified rollback; GPT rewrites,
flashes and resets are typed by the owner from the packet.
