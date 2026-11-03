# aud1-q-r1 result (QEMU TCG, m1box, 2026-11-03): PASS for RT and HAL. QEMU only, no sound path exists

Intent: `INTENT-aud1-q-r1.md`. Exit 0 at the 1500 s runtime limit, root unchanged. Bounded extract: `aud1-q-r1/audio-lines.txt`
(full console.log sha256 b5e26cb4…, m1box `/data/hackios-qemu/research/ios26-apps-r1/runs/aud1-q-r1/`).

- hkcover: HAL 3 entries / 69,359 B, VirtualAudio's 3 files copied, tunings 257 / 10,157,425 B: exactly the host consumer's numbers.
  The CoreUI colour cover still applied (`1 of 1 covers`).
- **RT:** `hk-audio-rt: audiomxd bootstrap 1200 -> 3125 ticks` (2×; 50 µs at QEMU's 62.5 MHz). No `thread_policy_set failed`, no
  `Failed to change thread to realtime` (audio-2 had 8).
- **HAL:** `hk-audio-test: AudioQueueStart 0` 4× (audio-2: -66681), `blazer-hal: StartIO` 9×, `playing` 9×, stops after 1.1-4.4 s with
  0 frames refused; `blazer-audio: first non-silent write, 512 frames`; 10 report lines, 750,116 frames since boot, 420,136 in
  non-silent writes, peaks after the cap 17-48 of 32768 (cap 327 held). Rate 16.6-23.8 k frames/s: TCG is slower than real time,
  so the HAL's mach-time clock outruns the guest; not a phone rate.
- audiomxd, SpringBoard, backboardd each exec'd once (no respawn). The only "panic" text is `blazer_panic=1` in boot-args.

Meaning: on root r3 with int1's kernel and the aud1 overlay, iOS's whole output path (AVAudioSession → AudioQueue → audiomxd HAL →
BlazerAudio Speaker → /dev/blazer-audio) runs in QEMU. The phone run (PLAN.md §7) checks the same on Tensor at 24.576 MHz.
