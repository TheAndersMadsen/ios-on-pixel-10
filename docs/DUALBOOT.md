# Storage and dual boot

Scope: preserve Android while establishing verified iOS storage, recovery and a physical OS chooser on Pixel 10 Pro.

## Current result

- **Physical:** Android is restored on slot b with normal boot and `/data`; restoration exceptions are recorded in the recovery handoff.
- **Physical:** no iOS root is deployed. Android recovery overwrote and reformatted `userdata_exp.ai`; old root, alias, capacity and write-approval instructions are historical.
- **Physical:** strict GPT r5a rejected nonzero backup-header reserved padding. Both header CRCs passed; no declared array was captured, so there is no GPT acceptance.
- **Offline/source:** the r5a padding holds 31 complete LUN0 entries packed after the 92-byte header, matching the factory FBPT `partition:0` table 31/31 (name, size, type and unique GUID). Transport, readback core, scratch and DMA-bounce reuse cannot produce that layout, so media contents written by the device GPT writer is the likely origin. This is unproven until the declared arrays are captured. `tools/dualboot.py` now saves the complete metadata plan raw before running the unchanged strict parser ([diagnosis](../research/ios26-dualboot-r7/gpt-r5a-trace/diagnosis.json)).
- **Inference:** LUN0 has no unallocated region. FBPT `userdata` grows to `last_usable`; Android shows 35 LUN0 partitions with `userdata` last; and `/data` (userdata + `userdata_exp.ai` multi-device F2FS) matches that size within 2 MiB. Isolated iOS storage therefore requires an attended Android shrink/migration ([decision](../research/ios26-dualboot-r7/STORAGE-DECISION.json)).
- **Physical gate:** no read-only GPT candidate is admissible. Every UFS readback recipe binds `blazer_ufs_root=userdata_exp.ai`, now part of Android `/data`.
- **Host/source:** readback, GPT validation, chooser policy and Android-handoff preparation exist, but they are not an operational phone menu, Android dispatcher or dual boot.

## Remaining work

1. Owner: approve a readback bind that names or exposes no Android partition, with a fresh CPU-context review, before one complete read-only capture. Do not relax the parser or allocate from this geometry.
2. Establish a fresh storage/recovery baseline: current strict GPT and ownership, independent verified backups, isolated iOS capacity, persistent data, migration and rollback, followed by explicit approval for any write.
3. Build a temporary chooser with physical display/input and a verified stock-Android handoff while preserving slots, firmware and the existing boot chain.
4. Test repeated switching, cold boot, interrupted power, recovery and OS failure before proposing any persistent chooser installation.

## Acceptance before expanding scope

- Repeated read-only captures pass strict checks for both GPT headers and complete entry arrays, with current Android ownership established.
- Independent backups and a tested Android rollback/recovery path survive the proposed storage operation; raw ciphertext alone is insufficient.
- A physical temporary menu boots both OSes through their intended chains without slot or firmware workarounds.
- Repeated iOS ↔ Android switches preserve both installations and iOS data, including cold boot and failure recovery.

## Evidence and source

- [GPT r5a failure analysis](../research/ios26-dualboot-r6/gpt-r5a-failure/analysis.json)
- [Backup-padding candidates](../research/ios26-dualboot-r6/gpt-r5a-failure/padding-entry-candidates.json)
- [Android restoration and exceptions](../research/factory-alias-restore-r1/HANDOFF.md)
- [Readback build and physical receipts](../research/ios26-dualboot-r2/HANDOFF.md)
- [Verified factory reference](../research/ios26-dualboot-r4/factory-google-dp11/HANDOFF.md)
- [Chooser/host integration](../research/ios26-dualboot-r5/integration/)
