# Sound on iOS 26 (blazer): hardware, what iOS needs, staged plan, first step built

2026-11-03, m1box, implementation sub-agent. No phone access. Labels: **FDT** (`research/ios26-dualboot-r8/truth/fdt.dts`,
the phone's DT; line numbers are that file's), **FILE/SOURCE** (stock or vendor file, our code), **QEMU**, **PHYSICAL**
(read on this phone in an earlier attempt, named), **HOST** (host test, static reading), **INFERRED** (my reasoning).
Earlier work reused here (Mac, untracked until now): `research/ios26-audio-r1/` (0900/0901 HAL device and cover, 0903 RT
bootstrap, QEMU `audio-1`/`audio-2`), `research/ios26-feature-audio-r1/` (0904 PCM ring), `research/ios26-fleet/handoffs/`
`audio.md`, `audio_sensors.md`, `feature-audio.md`, `aoc.md`; repo `docs/reuse/2026-11-02/audio-haptics.md`.

## 1. Hardware: what is on the AP and what is behind AoC

| Part | What | Control bus | Audio data | AP-reachable? |
|---|---|---|---|---|
| Speaker amp L | Cirrus **CS35L43** `cs35l43@0` (FDT 14007) | SPI `lsion_cli18_int1_spi: spi@db11000` (reg `0xdb13000`, FDT 13984), CS0, 10 MHz | TDM0 (`be_tdm0_rx`, `dsp_a`, FDT 1958-1979), clocked by BCLK (`sys@cs35l43_l src BCLK`, FDT 2289) | **control: yes** (AP SPI controller, stock's AP Linux driver owns it); **PCM: no** |
| Speaker amp R | CS35L43 `cs35l43@1`, `sound-name-prefix = "R"` (FDT 14029) | same SPI, CS1 | same TDM0 | same |
| Haptics | Cirrus **CS40L27B** `cs40l27b@43` (dev-name cs40l26a, FDT 12874) | AP I2C `lsioe_cli10_i2c: i2c@3a331000`, 0x43 | its `cs40l26-codec` ASP also clocked by AoC BCLK (FDT 2280) | **yes** (ROM effects PHYSICAL: `haptic-3-r2`, chip 40a270 rev b2; `blazer_haptic_tap=1` is on int1's line) |
| Microphones | 3 PDM DMICs: pads `DMIC1..3_DATA/CLK` on the AoC pinctrl (FDT 25242), functions `aoc_pdm0..3` (FDT 25668-), supplies `L20M_DMIC1`, `L20S_DMIC2`, `L19S_DMIC3` (FDT 16097, 16528, 16538) | none (PDM) | AoC PDM blocks | **no** |
| HAC amp | `hac_amp_en-gpios` on the DA9188 PMIC GPIO 14 (FDT 1188, 16691) | GPIO | from the AoC card | enable only |
| Codec | **none**: no WCD/discrete codec node. AoC's DSP is the codec/router (`google-aoc-snd-card`, FDT 1182; `aoc_path`, `aoc_pcm_drv` ...) | | | |

Amp wiring detail (FDT): SPI pads `XAOC_SPI1_SCLK/MOSI/MISO` in function `aoc_cli_int_1` (FDT 26587-26631), chip selects are
GPIOs on the AoC pinctrl, pads 41/42 `AOC2AMP2_SPI_CS_L_1V2`/`AOC2AMP1_SPI_CS_L_1V2` (`cs-gpios = <0x3d8 0x2a 1 0x3d8 0x29 1>`;
0x3d8 = `aoc_pinctrl`, FDT 25224; `gpio-line-names` FDT 25242). Shared reset `AP2AMP_RESET_L_1V2` on `lsion_pinctrl` GPIO 6
(FDT 22476/22585), shared IRQ `AMP2AP_IRQ_OD_L_1V2` on `cpm_pinctrl` line 41 (FDT 24484/24487). VA from `buck_12s`
(FDT 16310), VP from the `V_SYS_DUMMY` fixed regulator (FDT 1125). TDM pads `XAOC_TDM1_BCLK/WS/SDO` out and `SDI` in, function
`aoc_tdm1` (FDT 25650-25705; line names `AOC2AMP_TDM_BCLK_R_1V2`, `AOC2AMP_TDM_FS_R_1V2`, `AOC2AMP_TDM_SDA_R_1V2`, `AMP2AOC_TDM_SDA_1V2`).
Firmware on Android: `vendor/firmware/cs35l43-dsp1-spk-prot.*` (handoffs/aoc.md, FILE; not re-read here).

**Answer:** the speaker amps are **half AP-reachable**. Their control port is an AP-owned SPI controller (so the AP can
reset them, read their ID and configure them without AoC), but their PCM input (ASP) only comes from AoC's TDM1 block, and
their PLL takes BCLK from it. The vendor driver's DAC input sources are ASPRX1/2, monitor channels and the Halo DSP
(`cs35l43.h`: `CS35L43_INPUT_SRC_*`, SOURCE GPL, `ios26-hwmap-r1/dl-gos-6.12/.../amplifiers/cs35l43`); no tone generator
source exists. The mics are AoC-only. Earlier AoC review (handoffs/aoc.md) reached the same: "TDM and PDM pads have no AP
peripheral function".

## 2. What iOS 26 needs

- iOS reaches built-in audio two ways (blazer_audio_plugin.c header, from dada f1ae906f, APSL): IOAudio2 kernel drivers
  (AppleEmbeddedAudio class family; their devices arrive in the HAL by IOAudio2) or **AudioServerPlugIns** in
  `/Library/Audio/Plug-Ins/HAL`. On 23G90 the HAL runs in **audiomxd** (not mediaserverd). VirtualAudio (Apple's
  `VirtualAudio.plugin`, disabled on root r3) is the VAD layer above it; it matches physical devices **by UID**:
  `Speaker` (+ the companion `Hawking` input; without it everything stays on the null port), `Actuator`, `Codec`.
- **We do not need an IOAudio2 kernel family.** Our `BlazerAudio.driver` plug-in presents those UIDs and writes PCM to
  `/dev/blazer-audio`. QEMU `audio-2` (Mac, 2026-11-02, same root r3) showed: plug-in loaded, VA init 0, route port `pspk`
  UID `Speaker`, VAD volume set on chain `d42_speaker_general`, hk-audio-test `AudioQueueNewOutput 0`, `setActive 1`, but
  **`AudioQueueStart -66681`**: 8× `configure_thread_for_realtime ... thread_policy_set failed` with
  `{1200, 1200, 1200, 1}`; zero StartIO, zero samples (receipts `audit-audio-2.json`, QEMU).
- 0903 (`blazer_audio_rt=1`, in hk-int1 / int1's kernel): only audiomxd's exact preemptible {1200,1200,1200} request in its own
  task is raised to XNU's minimum RT quantum (50 µs = 1229 ticks at 24.576 MHz, 3125 at QEMU's 62.5 MHz). Host 66 checks.
- The **BTAudioHALPlugin flood** is already fixed and not an audio blocker: it came only from r8 putting bluetoothd in
  launchd's disabled set (485,871 failed lookups); r9/r10/int1 keep bluetoothd loaded and refused at exec, 0 such lines
  (`research/ios26-phaseb-r1/perf/FIX.md` §1, PHYSICAL). Keep it that way; if Bluetooth is ever disabled again, do it with
  hk_deny, not the disabled set.
- int1's physical boot (`laguna-usb-fix/attempts/20261103-205514-a7-ios-system-int1`): audiomxd runs, quiet (≤2 s CPU per 30 s),
  AudioConverterService spawns, `IODeviceTree:/product/audio -> none` from SpringBoard; no audio plug-in, so iOS has only the
  null device.

## 3. Smallest path to a beep, ranked

| Option | What makes sound | Verdict |
|---|---|---|
| **A. AoC audio** (chosen long path) | AoC firmware (GSA/Trusty load, rungs 1-4 in handoffs/aoc.md), AoC `audio_playback0` ring fed by 0904 `blazer_audio_pcm_bind`, AoC routes to TDM0, AP SPI configures the CS35L43s | Only path to real speaker PCM. Weeks: AoC 1-2 weeks + audio routing 2-4 weeks (aoc.md estimates). Rung 1 (GET_STATE) is built (0910) and never booted |
| B. AP bit-bangs TDM on the AoC pads in GPIO mode (as the IMU's I2C) | amp ASP from AP GPIO toggling | Rejected for now: needs ≥256 kHz BCLK jitter-free from MMIO writes; the amp's PLL locks to BCLK; without the protection firmware (`spk-prot`) speaker damage risk; no repo evidence the pads are fast enough |
| C. CS35L43 alone over AP SPI (open-loop PLL + Halo DSP program) | a tone synthesized in the amp's DSP | Rejected: no tone generator source in the register map; would need our own Halo firmware; no datasheet in the repo (a lookup needs the owner's OK) |
| D. Haptic CS40L27B ROM effect | buzz, not sound | Already physical (`blazer_haptic_tap=1`); proves only the actuator |
| **E. Stage-1 null/discard device** (first step, built) | nothing: samples are capped (peak 327/32768) and dropped in the kernel | Proves the whole iOS side up to the kernel PCM sink on the phone, at zero hardware risk. When A exists, only the sink changes (0904 is the producer it binds to) |

## 4. Staged plan

| Stage | What | Evidence now | Needs |
|---|---|---|---|
| **A1** | **Stage 1 on the int1 line: `a7-ios-system-aud1`** (null/discard Speaker device + RT clamp + tone client) | built, host tests, `check` OK; QEMU `aud1-q-r1` (§6) | attended boot (§7) |
| A2 | Read-only amp census over AP SPI: reset high, CS35L43 DEVID/REVID/OTP id on CS0 and CS1, IRQ line state; no write but reset, no boost, no clocks | none | XNU driver for `google,spi` at 0xdb13000 (clock 0x3d9/pclk via the CPM queue, power domain `lsio_n_cli`, pads `aoc_cli_int_1` + CS GPIO 41/42), pad ownership with sensors (pads 41/42 are `shared-pads`) |
| A3 | AoC rung 1 (0910, GET_STATE only) | patch, 32 host checks | link into the release, image_tool `blazer_aoc=1`, attended boot (deliberate panic) |
| A4 | AoC rungs 2-4: GSA load `aoc.bin` (16164591-polygon), start, carve-out, IPC up | plan only | rung 1 PASS, SMMU (aoc.md run 2), owner OK for `aoc.bin` in the image |
| A5 | AoC audio control: `audio_output_control`, path to TDM0, `audio_playback0` DOWN ring; bind 0904 | 0904 producer, 35 host assertions | A4, the closed routing built up from `aoc-interface-lga.h` + `etc/audio` |
| A6 | Amp bring-up over AP SPI with Cirrus protection firmware, level cap kept | none | A2, A5; `cs35l43-dsp1-spk-prot.*` hashes from Android (read-only) |
| A7 | First audible tone: hk-audio-test 440 Hz at peak ≤327 | — | A5 + A6, owner present |
| A8 | Mics (PDM through AoC `audio_capture0` → `Codec` input), volume, StopIO/drain, A2DP over host Bluetooth | — | A5; Bluetooth lane |

## 5. First step built: `a7-ios-system-aud1` (HOST, Mac build)

Changes against int1 (`research/ios26-phaseb-r1/int/INT1.md`), nothing else:
- **Kernel unchanged**: `kernel.int1` 0d0c99b2… (hk-int1 484717f) already holds hkcover (0900/0901), `/dev/blazer-audio`
  with the cap, the 0903 RT adapter and the 0904 PCM gate (strings and `_blazer_audio_pcm_bind` checked by the tool).
- **Overlay `aud1-r1.ovl`** 89e72e57… (10,963,640 B, 317 records), `tools/aud1_overlay.py`: int1-r1 (c440b6ea) byte-identical
  except record [39]: SpringBoard's one `DYLD_INSERT_LIBRARIES` becomes `hkbattery.dylib:hkaudiotest.dylib` (a second rule
  would only add a duplicate variable: `hk_exec_env_add` appends every match). Appended from audio-s1b (9c4a7dde, the
  overlay audio-2 ran): group 24 (BlazerAudio.driver, 5 records) and 25 (D421 tunings, 259) byte-identical, and the tone
  client `hkaudiotest.dylib` (9ac32206…) moved to group 29. Mask unchanged `0xA0080081`; 24/25 are never in it.
- **Line** (1017 B of 1023): int1's − `hk_ustack=Preferences,MobilePhone` (diagnostic sampler; makes room) +
  `blazer_audio=3 blazer_audio_rt=1`. `blazer_audio_pcm` refused.
- **Tool** `tools/image_tool_aud1.py` (1b0948eb…) = int1's `image_tool_int1.py` (728bdd21) + allow-list and checks
  (`receipts/aud1/image_tool_aud1.patch`): overlay holds 24 and 25, mask without bits 24/25, kernel strings, rt only with
  audio, pcm refused. `tools/mkimg_aud1.sh` (holds `/tmp/fleet/kernel-build-slot.lock`; the XNU tree was not touched).

| Artifact | sha256 |
|---|---|
| **`research/images/a7-ios-system-aud1/boot.img`** | **`272d9799cca3069ed93a40a7443a443c6f49d3a3f3637b687a9a3fcbb26e2649`** |
| payload-usb.bin (margin 29,627,456 B) | `6f3c1e108cdd02ab092fccb2ffdc64188bb9cea3417a22e2ec72918f068c53f5` |
| manifest.json | `607fa23a925f97144a90b9875fc45215abe44a63afa16a3bd3c6f91a2f5c892e` |
| overlay `build/aud1-r1.ovl` (derived, not for git) | `89e72e571fd3aff7ac0b8d2a7e4adb314871a412a58a74803001a014f3f0f626` |

`check`: `OK a7-ios-system-aud1 bootable 272d9799…` with image_tool_aud1.py and with the shared `tools/image_tool.py`, on the
Mac and on m1box (`receipts/aud1/image-check.txt`). Manifest vs int1: only kernel_end/ADT placement (larger overlay), line,
overlay, ids, tool hash (`receipts/aud1/manifest-diff.txt`).

Host tests (`receipts/aud1/host-tests.txt`):
- `tests/test_aud1_overlay.py`: 23 checks with an independent walker (records in place, [39] diff only the tone path, one
  SpringBoard DYLD variable, groups 24/25 byte-identical, mask, limits, refusals). `tests/mutants_aud1.py`: 7/7 caught.
- `tests/aud1_consumer.c` (ASan/UBSan) with **hk-int1's own** `varfs_overlay.h`, `varfs_tsv.h`, `hk_exec_rules.h`
  (`inputs/hk-int1/`, `git show hk-int1:…`): hkov_check, groups vs mask, cover check, rule append + hk_env_check, the
  env SpringBoard/backboardd/audiomxd get, hkcover_entries selection: 340 checks, 0 failed; int1-r1 alone fails it (no 24/25).
- `tests/test_image_tool_aud1.py`: 7 refusal cases, each stops before the image directory exists.

## 6. QEMU `aud1-q-r1` (m1box TCG, one slot)

**PASS (QEMU).** `qemu/RESULT-aud1-q-r1.md`, intent written first (`qemu/INTENT-aud1-q-r1.md`). Kernel int1, root r3 (205cb0e2,
decoded from the ios_system simg), overlay aud1-r1, args = harness base + `blazer_audio=3 blazer_audio_rt=1`; 1500 s, exit 0.
`hk-audio-rt: audiomxd bootstrap 1200 -> 3125 ticks`, no realtime refusal (audio-2: 8), `AudioQueueStart 0` 4× (audio-2:
-66681), `blazer-hal: StartIO` 9×, `first non-silent write`, 750,116 frames reached the kernel, peaks after the cap ≤ 48 of
32768. No respawns. The RT clamp was the wall audio-2 hit; QEMU shows nothing about Tensor timing.

## 7. Attended test (coordinator runs; owner present; bare `fastboot boot`, ANDROID_SERIAL set, return check after)

```
tools/bootios research/images/a7-ios-system-aud1/boot.img a7-ios-system-aud1 --mach research/ios26-phaseb-r1/int/build/kernel.int1.unstripped --wait 1080
grep -a 'hkcover\|blazer-audio\|blazer-hal\|hk-audio' <attempt>/ramdump/kernel.log
```
Same recipe, root and deadline (900 s) as int1. **No sound is expected or possible**: nothing reaches the amps (no sink,
no SPI, no AoC). Owner: after Home, wait ~4 min (the tone client plays a system sound and a 2 s 440 Hz tone every 120 s from
120 s after SpringBoard loads), press the lock button once and unlock (lock sound), open Settings > Sounds & Haptics and move the
ringer slider once, then watch Home until the deadline.
- **PASS:** `hkcover: /Library/Audio/Plug-Ins/HAL, 3 entries`, `hkcover: /Library/Audio/Tunings/D421, 257 entries`,
  `blazer-audio: opened by audiomxd`, `blazer-hal: the speaker is with the HAL`, `hk-audio-rt: audiomxd bootstrap 1200 -> N ticks`
  (N ≈ 1229 at 24.576 MHz), `hk-audio-test: AudioQueueStart 0`, `blazer-audio: first non-silent write`, report lines with
  non-silent frames near 48000 frames/s and peak ≤ 327; Home, touch and Settings as in int1.
- **Partial:** everything up to the route, but `AudioQueueStart -66681` again → the RT clamp is not the only wall; read the
  `hk-audio-rt` line and audiomxd's crash/exception lines before any next change.
- **FAIL/stop:** any `hkcover:` panic (the boot ends early; a reason is printed), audiomxd or SpringBoard respawning,
  backboardd worse than int1, no Home. Any audible sound: not possible by design; hold power and report.
- **Rollback:** none needed: RAM-only boot, root read-only, nothing written.

## 8. Read-only Android queries wanted (coordinator, `adb`, no writes)

```
adb shell 'cat /proc/asound/cards /proc/asound/pcm'
adb shell 'lsmod | grep -iE "cs35l43|cs40l26|aoc|snd_soc"'
adb shell 'ls -l /sys/bus/spi/devices/; for d in /sys/bus/spi/devices/*; do echo $d $(cat $d/modalias); done'
adb shell 'ls /sys/bus/aoc/devices/ 2>/dev/null; getprop | grep -iE "audio|aoc"'
adb shell 'dumpsys media.audio_flinger | head -120; dumpsys media.audio_policy | head -80'
adb shell 'ls -l /vendor/firmware | grep -iE "cs35l43|cs40l2|aoc"; sha256sum /vendor/firmware/cs35l43* 2>/dev/null'
adb shell su -c 'dmesg | grep -iE "cs35l43|cs40l2|aoc_alsa|aoc: |snd_soc" | head -200'
adb shell su -c 'ls /sys/kernel/debug/regmap/ | grep -i cs35'   # names only; no regmap reads of AoC
```
Wanted for A2/A6: which SPI CS is the bottom speaker, the amps' REVID in dmesg, the firmware names/hashes, the TDM slot
map AoC uses (from audio_policy/route logs), and whether the AP driver keeps the amps in reset when idle.

## 9. Open questions

- Is RT the only wall? A1 answers it on the phone (QEMU §6 first).
- Which CS35L43 is L/R (bottom/earpiece)? `sound-name-prefix = "R"` on CS1 only (FDT); placement INFERRED.
- `PMICS2AMP3_RESET_L_1V2` (FDT 16642) names a third amp with no DT node: unknown.
- AoC audio routing commands are closed (stock AIDL HAL); the largest unknown after AoC itself (aoc.md).
- Keep the 327/32768 cap until amp protection firmware is confirmed active (audio.md rule).
