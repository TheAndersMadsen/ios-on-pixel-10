# cam1 phone test: flash LED under iOS (designed 2026-11-04; NOT run)

The coordinator and the phone owner run this. This lane never touches the phone. One attended boot, about 8 minutes, bare `fastboot boot`.

## What is booted

| Item | Value |
| --- | --- |
| Image | `research/images/a7-ios-system-cam1/boot.img` **51900a1a2bfbc761c016801ffe2dc484114dae391da546744f32eb826881fb44** (check: `OK … bootable`, receipts/image-check.txt) |
| Payload | `payload-usb.bin` 73966a781191cc0824637063aa4ea7ad81fbf77e569dcc88f9ec6534f23845fa |
| Kernel | `build/kernel.cam1` c4c4795480ad74f0f1e0d35332fed6bb42fd772f66556f27dd3309608e789a5f; `.unstripped` 02f27329d9eee53ab34c610f19c844fa6cd71df840b35509e4286f92b6b6d304 (XNU hk-cam1 2e8d777 = 7227fe7 + patch da630c6c…) |
| Recipe | a7-ios-system-r3 (owner-confirmed Home, 5 cores, deadline 300, same overlay) + `blazer_torch=4`. Command line 1014 B, r3 999 B; the only difference is that token (receipts/cmdline-diff.txt) |
| Variable | one: stage 4 of the flash driver (CLI7 I2C select, LM3644 id, LED1 then LED2 torch at 12 mA for 2 s each) |

## Risk and what it may touch

- Writes: CLI7 config word 0 (UART→I2C) and pad words, SCL/SDA mux (LSIO_E pins 0/1 to CLI7), the flash EN GPIO (LSIO_S pin 22),
  the CLI7 I2C controller, and LM3644 registers 0x01/0x05/0x06 with exact values only. CPM frames: LPB GET and LPCM clock/reset
  of CLI7 only, no PMIC frame. Everything is put back; EN low resets the LM3644.
- Never touched: storage writes (none in this image; read-only root as r3), PMIC rails, camera sensors, Android partitions, reserved memory.
- Light: 12.2 mA torch (24.4 mA if the part is the TT variant), 2 s per LED. Dim; not a flash pulse (flash mode cannot be written).
- Worst case: a panic while lit leaves the LED on until the reset into fastboot (seconds). INFERENCE: reset drops the AP GPIO,
  and HWEN has an internal pull-down.

## Command (coordinator, m1box)

```sh
export ANDROID_SERIAL=<phone serial>   # as every boot
export HK_LOCK=coord
tools/hk cycle research/images/a7-ios-system-cam1 --mach research/ios26-camera-r1/build/kernel.cam1.unstripped \
  --expect research/ios26-camera-r1/expect/cam1.yaml --name cam1-r1
# or through the queue (no UI script: empty ui argument)
tools/hk queue add research/images/a7-ios-system-cam1 '' research/ios26-camera-r1/expect/cam1.yaml \
  --mach research/ios26-camera-r1/build/kernel.cam1.unstripped --name cam1-r1 --note "cam1: flash LED stage 4"
```

hk cycle includes the return to Android and the return check. kernel.cam1.unstripped is on the Mac and on m1box (same sha).

## Owner (attended)

Hold the phone with the rear camera bump visible, not pointed at anyone's eyes. Start watching about **40 s after the
`fastboot boot` command** and keep watching until about 100 s. The driver starts 45 s after the kernel's BSD init. Expected: one
dim glow of about 2 s, about 1 s of dark, then a second glow of about 2 s (LED2). If the module has only one LED wired, there
may be just one glow. Record exactly what was seen: `tools/hk note <attempt> "owner: flash glowed twice ~2 s each"` (or once,
or never). Do not cold-reset the phone; the boot ends at its own 300 s deadline.

## Success lines (console / ramdump kernel.log)

```
blazer-torch: stage 4, starts in 45 s, torch 2000 ms (hk-cam1)
blazer-torch: lsio_e 2 (2 on)
blazer-torch: lsio_s 2 (2 on)
blazer-torch: cli was 2,1,1
blazer-torch: cli select uart -> i2c
blazer-torch: pads were scl 0x<n> sda 0x<n>
blazer-torch: chip answered: id register 0x2, enable register 0x80        (0x4 = LM3644TT)
blazer-torch: led1 on: torch code 0x8, enable 0x89, for 2000 ms
blazer-torch: led1 off: standby, 2000 ms lit, flags 0x0 0x0
blazer-torch: led2 on: torch code 0x8, enable 0x8a, for 2000 ms
blazer-torch: led2 off: standby, 2000 ms lit, flags 0x0 0x0
blazer-torch: ends: ok, chip answered 1, id 0x2, enable 0x80
blazer-torch: summary stage 4 stop ok detail 0x0 lit 2000 2000 ms, cli0 2, pads 0x<n> 0x<n>, flags 0x<n> 0x<n>
```

Then `blazer-root: deadline 300 s` (planned end), return check PASS. Evaluate with
`python3 -I tools/probe_eval.py --row 'Cameras, flash' <attempt>` (the row reaches `partial` only with the owner's confirmation).

## Reading a stop (one line: `blazer-torch: stop <name>, detail 0x<d>`)

| stop | Meaning | Next variable |
| --- | --- | --- |
| `cli` (detail 0x2 before `cli select`) | wrong kernel or stage (< 3) | image check |
| `pad-not-i2c` detail `i<<16 \| v` | SCL (i=0) / SDA (i=1) mux in an unexpected function v | add v to the mux rule if the FDT supports it |
| `lines-low` | SCL/SDA low once muxed: pull-up rail unpowered (INFERENCE: CAMIO `ldo_22s`) | F2: read/enable LDO22S through blazer_cpmq (owner decision) |
| `nak` detail = abort source | chip did not answer: HWEN path or chip power | EN pad readback lines; F2 rail check |
| `not-lm3644` detail = id | another part at 0x63 | nothing is written; re-read the FDT/vendor driver |
| `not-standby` | enable register not 0x80 at power-up | nothing is written |
| `flags` detail `f1<<8 \| f2` | a fault flag in torch (short, TSD, UVLO, OVP…) | stop the lane; read the flag bits (CAMERA.md) |
| `cleanup failed: …` | one restoration step failed; EN low still follows | read the following lines; review before any retry |

No unchanged retry (COORDINATION.md). A FAIL is recorded, not requeued.
