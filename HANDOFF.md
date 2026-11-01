# Current — 2026-11-01: UFS has no link yet; ufs-observe-r2 next, then ufs-link-r1

### 2026-11-01: first UFS read, link plan reviewed, work now run the tegu way

- Phone: in fastboot (seen 2026-11-01). Parent alone owns USB. No helpers running.
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
