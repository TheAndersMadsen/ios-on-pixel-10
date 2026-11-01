# Current — 2026-11-01: ufs-observe-r2 clean; device is unpowered-looking and held in reset

### 2026-11-01: ufs-observe-r2 read power, pads and SMMU on the phone

- Physical, attempt `20261101-174259-ufs-observe-r2b`, image `a7fd3cbd…`, capture `261fa855…`,
  fresh stamp nonce. All 22 + 13 read-only reads committed, rc 0, ISR 0, in 33 ms. Values:
  `research/ufs-observe-r2/result.json`. No storage or register writes; no UFS link attempted.
- Observed: PSM_HSIOS, PSM_UFS_HC and PSM_UFS_PHY all ON (0x10). PWR_CTRL `0x23c4c24` matches warm
  mode 2. HCLKDIV 0x190, TOP+0x200 0, HCS 0x108 (DP=0, same as r1). Last UIC command was
  HIBERNATE_ENTER, result 0. Pad 8 (`AP2PMIC_UFS_EN`) reads low. Pad 0 (reset) reads low.
- Observed, `inf_smmu`: CR0=0, CR0ACK=0, GERROR=0, STRTAB_BASE=0, GBPA=0x2e1f with ABORT clear.
  First read of this SMMU. By my reading of SMMUv3 fields, it is disabled and bypassing, not
  aborting. Confirm against the Arm spec before relying on it for DMA.
- Guess, not measured: pad 8 low means the device has no power. No rail voltage was read. Refclk
  dout/oe fields from the decoder are undefined (known defect); use the raw words.
- Link preconditions hold, so ufs-link-r1 may run. It will be the first boot that writes UFS
  registers. Next: build it from the host code, with both LINKs in one boot.
- Same boot continued to XNU, root mount, launchd exec and dyld, then panic. `launchd` main no.
- Failed first boot, `20261101-174018-ufs-observe-r2`: refused with -11 before any UFS read, because
  I changed nonce/epoch without updating `n742_generated_binding.h`. Fixed, no phone effect. Phone
  parks by itself within about 2 minutes; `tools/bootios` now waits for that and captures.
- Phone: parked in fastboot, slot b, force-fastboot on.

### 2026-11-01: first UFS read, link plan reviewed, work now run the tegu way

- Parent alone owns USB. No helpers running.
- Last UFS boot, ufs-observe-r1: eight read-only reads at `0x3c400000`, no writes. HCE=0x3,
  HCS=0x108 (UCRDY=1, **DP=0**), doorbells 0, run-stop 1/1. Controller enabled, device not
  present. Values: `research/laguna-usb-fix/native-fleet-20261031/N900-root-current-ufs-observation/CURRENT-UFS-OBSERVATION.json`.
- Last native boot: I-cache transition and 16 KiB baseline captured, still compact root and
  panic. `launchd` main not reached.
- ABL fully initializes UFS, then logs `[UFS] shutdown complete` about 30 s before our reads.
  The old "device dead at DME level" conclusion was a misread of the status column; corrected
  in the ledger.
- Hypothesis, not proven: the shim never runs the stock pre-link sequence after ABL's shutdown.
  Sequence from the shipped `ufs.ko` (Linux 6.12.81):
  1. reset=0, power=1 (pad 8), wait 8 ms, refclk on, wait ~300 µs, reset=1 (pad 0)
  2. cycle HCE 1→0→1, keeping crypto bit 1
  3. HCLKDIV=0xc8, TOP+0x200=0x101
  4. DME 0x8118=0, DME 0xd085=1
  5. DME_LINKSTARTUP, check IS.ULSS and HCS.DP
  Expected: DP=1 and ULSS. Refuted if LINK still gives result 1 with pads verified high and
  HCE cycled.
- Review of this plan found nothing unsafe, but "device unpowered" is not supported. Strongest
  alternative: LINK result 1 in ~80 µs is a local UIC refusal, independent of device state. So
  ufs-link-r1 runs both LINKs in one boot, with per-LINK duration. Review:
  `research/laguna-usb-fix/native-fleet-20261031/N916-verify-o2-w1/VERDICTS.json`.
- Next: ufs-observe-r2. Read-only: power domains, pads, PWR_CTRL, HCS, then `inf_smmu`. Four
  review fixes first: record ISR_EL1.A after the SMMU reads, a checkpoint after each pad group,
  twelve SMMU words instead of three, and read the 8-byte STRTAB_BASE as two 32-bit words. Then
  ufs-link-r1 only if both UFS domains and HSIOS are ON and PWR_CTRL shows warm mode 2.
- Host-only and unapplied: ufs-observe, ufs-link and post-link code link but have not run:
  `research/laguna-usb-fix/native-fleet-20261031/N914-integration-next-candidate/`. READ(10) stays blocked until `inf_smmu`
  (`0x35100000`, SID 0x8100) is measured; treat UFS as non-coherent.
- Full root gaps: 23 (4 delivered, 8 partial, 10 missing, 1 unknown). First stops are the
  shim-to-XNU handoff and `rd=ufsroot0` with libignition:
  `research/laguna-usb-fix/native-fleet-20261031/N915-ios-from-fullroot/`. No physical window above 1 GiB yet.
- Decisions (user delegated 2026-11-01): parent runs temporary boots through `tools/bootios`
  and leaves the phone in fastboot with force-fastboot on. Read-only LUN discovery approved.
  Kodiak's platform file stays unfetched. No GitHub remote until `xnu/patches/` licensing is
  fixed. Storage writes and destructive steps still need the user's confirmation.

Previous handover: `research/legacy-root-20261101/handover.md`.
