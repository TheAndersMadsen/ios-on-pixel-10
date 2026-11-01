# Current — 2026-11-01: UFS has no link yet; O2 and W1 link on the host; final O2 not built

### 2026-11-01: N900 baseline, W1 hypothesis, host-side integration

- Phone: on stock Android, force-fastboot off (note from the previous lead agent,
  2026-11-01 16:01Z). No boot has run since N900.
- Latest UFS physical result: N900, attempt
  `20261101-161514-gate-139540efc89b484cadbccae5993eb201`, eight read-only reads
  at `0x3c400000`, no writes. HCE=0x3, HCS=0x108 (UCRDY=1, **DP=0**), doorbells 0,
  run-stop 1/1. Controller enabled, device not present. Values:
  `research/laguna-usb-fix/native-fleet-20261031/N900-root-current-ufs-observation/CURRENT-UFS-OBSERVATION.json`.
- Latest native boot result: N857, I-cache transition and 16 KiB baseline captured,
  still compact root and panic. `launchd` main not reached.
- ABL fully initializes UFS, then logs `[UFS] shutdown complete` about 30 s before
  our reads. The old "device dead at DME level" conclusion (M4) was a misread of
  the status column and is corrected in the ledger.
- Hypothesis W1, not proven: after ABL's shutdown the device is unpowered or held in
  reset, and the shim never runs the stock pre-link sequence. Sequence from the
  shipped `ufs.ko` (Linux 6.12.81):
  1. reset=0, power=1 (pad 8), wait 8 ms, refclk on, wait ~300 µs, reset=1 (pad 0)
  2. cycle HCE 1→0→1, keeping crypto bit 1
  3. HCLKDIV=0xc8, TOP+0x200=0x101
  4. DME 0x8118=0, DME 0xd085=1
  5. DME_LINKSTARTUP, check IS.ULSS and HCS.DP
  Expected: DP=1 and ULSS. Refuted if LINK still gives result 1 with pads verified
  high and HCE cycled.
- Host work: N914 composed O2, W1 and post-link L2. All link and none has run on
  hardware. The full cold-start route lacks 12 real hardware bindings and refuses the real FDT.
  READ(10) over DMA stays blocked until UFS's `inf_smmu` (`0x35100000`, SID 0x8100) is measured; treat UFS
  as non-coherent. Patches are unapplied:
  `research/laguna-usb-fix/native-fleet-20261031/N914-integration-next-candidate/`.
- Full root: N915 lists 23 gaps (4 delivered, 8 partial, 10 missing, 1 unknown).
  First stop is the shim-to-XNU handoff (G1). First userland stop is `rd=ufsroot0`
  and libignition (G15). No physical window above 1 GiB yet.
- N916 reviewed O2 and W1: nothing unsafe. W1's explanation is not supported, but its
  action plan survives. Strongest alternative (ALT-L): LINK result 1 in ~80 µs is a
  local UIC refusal, independent of device state. Discriminator: W1 with device-on
  compiled out, or both LINKs in one boot with per-LINK duration. O2 needs N916's
  requested changes first:
  `research/laguna-usb-fix/native-fleet-20261031/N916-verify-o2-w1/VERDICTS.json`.
- Next: apply N916's O2 changes, build O2, boot it, decode, and run W1 only if both UFS
  PSMs and PSM_HSIOS are ON and PWR_CTRL shows warm mode 2. Add ALT-L's discriminator to W1.
- Unfinished: N916–N920 were interrupted at 17:09 and N921 has no report; partial work is under
  `research/laguna-usb-fix/native-fleet-20261031/`. No agents are running. The phone state above comes from a note, so check it before relying on it.
- Decisions (user delegated them 2026-11-01, following the ios-tegu approach): the working
  agent runs temporary boots itself through `tools/bootios`, one at a time, and leaves the
  phone in fastboot with force-fastboot on between tests. Read-only LUN discovery is approved
  for W3. W1 runs both LINKs in one boot (N916's discriminator). The interrupted agents are
  not restarted; read their partial work when a step needs it. Kodiak's platform file stays
  unfetched. No GitHub remote or publishing until `xnu/patches/` licensing is fixed.
- Not delegated: storage writes and other destructive steps still need the user's confirmation.

Previous handover in full: `research/legacy-root-20261101/handover.md`.
