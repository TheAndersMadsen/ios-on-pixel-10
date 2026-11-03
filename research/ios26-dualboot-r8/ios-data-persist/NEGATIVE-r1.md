# ios_data persist: QEMU negative test r1 (2026-11-03, m1box rig, TCG). Verdict: PASS (QEMU)

Claim tested: XNU dd000c8's persistence writes nothing outside `ios_data`. QEMU evidence only; the phone has not run it.

## What ran

- Kernel `kernel.fakelun-b228c4f` (sha256 3563a0406a24d510…): release tree b228c4f = 7227fe7 (root view takes the
  partition's real size) + dd000c8 (ios_data persist) + the QEMU fake-LUN mode added for this test
  (`research/ios26-apps-r1/tools/m1box/xnu_fake_lun_patch.py`): with `blazer_ufs_fake_lun=1` the fake memory is a whole
  LUN with its own GPT, fake reads/writes use absolute LBAs (stores outside the medium panic), attach resolves the root
  with `ufs_find_partition`, and persist resolves `ios_data` instead of refusing. Without that boot-arg nothing changes;
  the phone never sets `blazer_ufs_fake`. Persist host test with the patched `.inc`: 107,623 + 5 checks, 0 failed.
- Medium `fakelun-r6.img` (`tools/m1box/mkfakelun.py`), 4096-byte LBAs, primary and backup GPT with valid header and
  array CRCs (re-read independently): `userdata` 6..261, `ios_system` 512..5,243,391 (= `apps-full-r6.img`, byte-exact,
  aff3ebbe…), `ios_data` 5,243,392..5,259,775 (16,384 blocks, hackios type 364eb72d…). The run used a reflink copy mapped
  writable (`qemu-ufsroot.py --root-rw`); the pristine file is the reference.
- Boot-args: r13's (rd=ufsroot0, blazer_ufs_root=ios_system) + `blazer_ufs_fake_lun=1 blazer_persist=1
  blazer_persist_period=15`. 600 s, exit 0. Intent: `intent-negative-r1.json`.

## Console (deciding lines)

```
blazer-root: FAKE device at a02e00000, 21546139648 bytes, no MMIO, whole LUN with GPT
blazer-ufs: "ios_system" on LUN 0: first block 200, 20480 MiB, read only, DMA at f0b2d8000
blazer-persist: mode 1, target ios_data, 4099 blocks in 1 extents, table a71bd369, slot 2049 blocks
blazer-persist: ios_data at LBA 5243392, 16384 blocks, above userdata's 261, seal 2b747b9b, armed
blazer-persist: saved slot 0, generation 1, 7864 bytes, 29 entries, crc 1fb80f3d, 4 commands, 1 ms, period
...
blazer-persist: saved slot 1, generation 12, 35656 bytes, 81 entries, crc 9d846bd9, 4 commands, 1 ms, period
```

12 saves, alternating slots; 0 panics; 0 refusals.

## Host diff (`tools/m1box/fakelun_diff.py`, whole medium, 21,546,139,648 bytes)

| Changed LBAs | Blocks | Partition |
| --- | --- | --- |
| 5,243,394 .. 5,243,403 | 10 | ios_data (table blocks 2..11: slot 0) |
| 5,245,443 .. 5,245,452 | 10 | ios_data (table blocks 2051..2060: slot 1) |

Allowed range: ios_data's table extent, LBA 5,243,393..5,247,491 (ios_data blocks 1..4099). Outside it: **nothing**.
GPT (both copies), `userdata`, `ios_system`, the unused tail of `ios_data` and every unallocated block are byte-identical.

## Limits

QEMU's fake LUN is not the phone's UFS: the write path here is `ufs_fake_store` after `n882_port_write_guard`, not
WRITE(10) FUA on the controller. The guard, the GPT resolve, the seal and the slot layout are the same code the phone
runs. `tools/image_tool.py` still refuses every `blazer_persist*` token until a physical test (after A7) is admitted.
