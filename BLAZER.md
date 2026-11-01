# Pixel 10 Pro (blazer) bring-up

Target is now iOS 26 (branch `ios26`), which has not booted on this phone. Everything below is iOS 16 evidence; its hardware results carry over.

The Pixel 10 Pro boots our XNU from RAM, mounts the full iOS root from UFS and runs `launchd`, backboardd and
SpringBoard, which draw frames to RAM. iOS's frames don't reach the panel yet, and there is no touch. The active work is UFS, so
that the full iOS root can load. The ledger is
`research/laguna-usb-fix/ATTEMPTS.md`; captures and hashes outrank this summary.

## 2026-11-01 status: UI processes run

phone-r1: backboardd made 3 frame swaps and SpringBoard ran, no crash, until a manual long press:
`research/laguna-usb-fix/attempts/20261101-203354-ufs-ui-r1`.

## 2026-11-01: launchd runs from the full root

ufs-root-r2: 16 KiB pages, 4 GiB, APFS over UFS, launchd `hello`, xpcproxy, then our own 300 s deadline panic:
`research/ufs-root-r1/run/root/decoded-r2.json`.

## 2026-11-01: XNU reads UFS

ufs-xnu-r1: XNU took over from the shim and read staged blocks with 0 errors:
`research/ufs-integrate-r1/run/xnu-r1/decoded.json`.

## 2026-11-01: root staged and read back

ufs-stage-r1 rewrote `userdata_exp.ai` with user approval; ufs-read-r3 matched 12 of 12 samples:
`research/ufs-read-r3/run/decoded.json`.

## 2026-11-01: UFS READ works

ufs-read-r2: GPT valid on 4 LUs, `userdata_exp.ai` found at LU0 LBA 2500838, staged image absent:
`research/ufs-read-r2/run/decoded.json`.

## 2026-11-01: UFS commands work

ufs-postlink-r2: NOP IN, fDeviceInit, TUR GOOD after UNIT ATTENTION, REPORT LUNS 4 LUs, data DMA landed:
`research/ufs-postlink-r2/run/decoded.json`.

## 2026-11-01: first UFS link

ufs-link-r2: with device power and reset driven, LINK result 0 in 9.3 ms, HCS=0xf, DP=1. Without them,
result 1 in 50 ms, DP=0. One boot: `research/ufs-link-r2/decoded.json`.

## 2026-11-01: UFS controller readable

ufs-observe-r2 read UFS power domains ON, warm mode 2, pads 8 and 0 low and `inf_smmu` not
enabled, on the phone with no writes: `research/ufs-observe-r2/result.json`.

ufs-observe-r1 read the controller without writing: HCE=0x3, HCS=0x108, DP=0. ABL logs full UFS
init of the Samsung KLUDG4UHGC and then shuts it down about 30 s before our reads.
 Full detail in `HANDOFF.md`.

## Memory checkpoint (2026-11-01)

page16k-r1: 16 KiB pages, 4 GiB at `0xa00000000`, 262144 pages, same compact-root panic: `research/page16k-phone-r1/rootkernel/decoded.txt`.

## Panel checkpoint (2026-11-01)

display-frame-r1d: pixels from RAM reached the panel; OPR followed the nonce (0, 423, 423, 0, 0, 0), underrun on the first kick only. Not confirmed on glass: `research/display-frame-r1/run/boot-r1d/decoded.json`.

display-frame-r1c: DPU test pattern reached the panel; the owner saw it, and the panel's OPR followed the sequence: `research/display-frame-r1/run/boot-r1c/decoded.json`.

display-dcs-r2: native DSI commands reached the panel, it replied with its ID and power mode `0x9f`, flash commands sent. Visible effect not filmed. `research/display-dcs-r2/run/decoded.json`.

## Native boot checkpoint (2026-11-01)

The latest native boot captured the I-cache transition (SCTLR `30c50990→30c51990`) and a correct 16 KiB
baseline, 28 of 28 expected captures with none missing. The post-I measurement hit its deadline.
Still compact root and panic. Result:
`research/laguna-usb-fix/native-fleet-20261031/N857-root-cpu-phase-timing/PHYSICAL-RESULT.json`.

An earlier boot measured the USB `amb_smmu` (`0x05b80000`) in 24 reads; UFS's `inf_smmu` was first read by ufs-observe-r2. Others gave a fresh XNU v2 message buffer through
root, launchd and dyld, then panic.

## UFS checkpoint (2026-10-28)

The staging write put the system image in `userdata_exp.ai`; by 2026-11-01 it was gone, and it was rewritten that day. LINK_STARTUP completes with result 1. Testing refuted reset as the cause.
Hibern8 exit works for TX; RX stayed in state 1. "Device dead at DME level" was a misread, corrected on 2026-11-01. The shim has never driven the
device pads or cycled HCE.

## Userland checkpoint (2026-10-28)

- composite-root22-0002: first dyld exec on the phone.
- composite-v2-e14: pid 1 ran userspace with a symbolicable backtrace.
- composite-v3-reloc: the relocation fix holds on hardware.
- composite-v6-write: dyld's plaintext trail reached `M11.initializers`.
- composite-v8-full: all fixes composed; one NULL+0x18 dereference remains.
- composite-v9-core, v10-tsd: read-only root and wrong-root regressions.

## Recovery checkpoint (2026-10-28)

pscireset-0002-park was the first autonomous reset and park, and unified-pan2-reset the
second, with capture through the reset. Earlier "parks" were manual long-press resets
and were retracted. Recovery is not qualified for unattended use.

## Non-native evidence

- pKVM VM (2026-10-25): iOS 16.5 home screen with touch on this phone
  (`research/notes/AVF-NEXT.md`). Not bare metal.
- QEMU: lock and home screens rendered from the full APFS root
  (`research/laguna-foundation/UPSTREAM-ON-QEMU.md`). Guest evidence only.
