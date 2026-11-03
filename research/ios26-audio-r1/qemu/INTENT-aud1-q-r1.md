# aud1-q-r1 intent (written before the run, 2026-11-03, m1box QEMU TCG, one guest slot)

QEMU only: says nothing about Tensor, AoC or the amps.

- Kernel `kernel.int1` 0d0c99b2… (hk-int1 484717f), root r3 205cb0e2… (decoded from ios_system-phone-r3.simg, read-only map),
  overlay `aud1-r1.ovl` 89e72e57…, mask 0xA0080081 (int1's).
- One variable against the recovered `audio-2` QEMU run (Mac, p11 + 0901, overlay s1b, 2026-11-02): the kernel now has
  0903 behind `blazer_audio_rt=1`, and the overlay is int1's plus the audio records. Args = the harness base +
  `blazer_audio=3 blazer_audio_rt=1` (the old audio-rt-r1 request, handoffs/audio_sensors.md, never run until now).
- Question: does the RT bootstrap clamp let audiomxd's HAL I/O thread start, so StartIO runs and samples reach
  /dev/blazer-audio?
- PASS RT: `hk-audio-rt: audiomxd bootstrap 1200 -> N ticks`. PASS HAL: `hk-audio-test: AudioQueueStart 0`,
  `blazer-audio: first non-silent write`, report lines with non-silent frames, peak <= 327.
- FAIL: `AudioQueueStart -66681` again, no `first non-silent write`, `hkcover:` panic, audiomxd respawns, no SpringBoard.
- Read-out either way goes to `qemu/RESULT-aud1-q-r1.md`; no retry in the same form.
