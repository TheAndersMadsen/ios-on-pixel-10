# Audio and haptics reuse audit — 2026-11-02

The strongest available reuse is test and lifecycle code around our existing
HAL and haptic driver. No inspected repository supplies a drop-in iOS 26 audio
driver for Tensor G5. The speaker transport dependency remains blocked; this
audit does not propose restarting the rejected AoC work.

## Current local baseline, verified from source

- `research/ios26-audio-r1/src/blazer_audio_plugin.c` already implements the
  AudioServerPlugIn function table, properties, virtual devices, timestamps,
  StartIO/StopIO and sample writes. Its header credits dada `f1ae906f` and
  APSL 2.0; this audit has not independently re-audited dada's complete ancestry.
- The plug-in is approximately 1,000 lines, not a missing component to rewrite.
  The existing QEMU `audio-2` evidence shows VirtualAudio initialization and a
  Speaker route, followed by rejected realtime scheduling and no sample writes.
  No new guest run or sound result is established here.
- **Already integrated:** current release series `1144` incorporates audio
  `0903`'s narrowly scoped realtime bootstrap adjustment; `1145`, release commit
  `d5600bd`, incorporates `0904`'s capped S16LE/stereo/48 kHz PCM ring producer.
  The corresponding functions are present in the actual release source.
  Older feature handoffs describing these as awaiting integration are stale.
- The PCM producer still has no verified running hardware consumer/bind caller.
  Host tests and compilation do not establish sound, remote start/stop or drain.
- **Separate deliverable:** `research/ios26-feature-haptics-r1/patches/`
  `0832-blazer-haptic-native-rom.patch` supplies a bounded ROM-service API and
  cleanup fixes. No `blazer_haptic_play_rom`/service gate was found in the current
  release driver; it is not another already-integrated audio patch.
- Earlier haptics captures establish chip identification and command/STOP
  completion. Felt motion and calibrated strength remain unconfirmed.
  The ROM API cannot reproduce iOS Actuator PCM waveforms.

## Candidate 1 — Google haptics mocks and lifecycle tests

**Priority P1; high confidence as test reuse, medium as a future service design.**

Verified primary source: AOSP `platform/hardware/google/pixel`, commit
`1f4d83fe1cd8cade90e7335b46b8278021c43a34`:

- [tests/test-vibrator.cpp](https://android.googlesource.com/platform/hardware/google/pixel/+/1f4d83fe1cd8cade90e7335b46b8278021c43a34/vibrator/cs40l26/tests/test-vibrator.cpp),
  especially `setExternalControl_enable`, `setExternalControl_disable` and
  parameterized `ComposeTest.compose`.
- [tests/mocks.h](https://android.googlesource.com/platform/hardware/google/pixel/+/1f4d83fe1cd8cade90e7335b46b8278021c43a34/vibrator/cs40l26/tests/mocks.h)
  separates actuator state, calibration and callbacks from transport.
- [Vibrator.cpp](https://android.googlesource.com/platform/hardware/google/pixel/+/1f4d83fe1cd8cade90e7335b46b8278021c43a34/vibrator/cs40l26/Vibrator.cpp)
  supplies `setAmplitude`, `setExternalControl` and completion sequencing.

Each inspected file explicitly carries Apache-2.0. Retain its notices when
adapting code. This is a historical verified commit, not a claim that old Pixel
calibration and effects match the target motor. Current AOSP main resolves to
`8612656e216075f79a1efa3bb9be6b6943d6e8cc`, but the former `vibrator/cs40l26`
path returned 404 there; a branch name alone is not a usable source pin.

**Integration seam:** adapt the mock boundary and ordered lifecycle assertions
to the existing ROM service. Preserve unsupported amplitude/waveform refusals.
The old Google tests exercise a richer driver using Android AIDL, Linux input
force-feedback, ALSA and calibrated effects. Do not advertise those capabilities
or transplant its effect indices into the ROM-only service.

**First host proof:** use a synthetic chip backend to assert readiness,
silence/no-transaction, play/STOP/standby ordering, cleanup after each failed
transition, and no completion notification before actual completion. Retain
the existing service's 39-index and nominal-only restrictions. No real motor,
firmware or AoC action is needed. Existing 0832 already tests many cleanup cases;
only add uncovered lifecycle/callback cases after reviewing that suite.

**Work saved:** reuse a mature separation of concerns and test matrix instead
of inventing a second actuator lifecycle. It does not supply iOS CoreHaptics
integration, a PCM endpoint, matching calibration or an audible speaker path.

## Candidate 2 — matching Cirrus source, selected by version

**Priority P1 for decoding the existing result; high confidence as a reference.**

Local verified repository: GrapheneOS `kernel_pixel_6.12`, commit
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`, at
`research/ios26-hwmap-r1/dl-gos-6.12/`.
The directory contains **three** cs40l26 implementations: `dev`,
`v14.5.0+v4.1.1`, and `v16.4.0+v5.1.0`. Saved stock-module inspection in the
existing haptics literal checker identifies `v14.5.0+v4.1.1`.
Do not default to `dev` because its path looks current.

Exact source locations at that pin:

- [v14.5 header](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/amplifiers/cs40l26/v14.5.0%2Bv4.1.1/cs40l26.h)
  defines L27 A/B identities and revision-specific register facts.
- [v14.5 driver](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/amplifiers/cs40l26/v14.5.0%2Bv4.1.1/cs40l26.c)
  supplies mailbox, power-state, protection-error and gain-control handling.
- [v14.5 codec](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/amplifiers/cs40l26/v14.5.0%2Bv4.1.1/cs40l26-codec.c)
  supplies `cs40l26_pcm_hw_params`, DAPM state transitions and ASP format rules.

These files carry GPL-2.0 headers. Local contents and git pin were inspected;
the GitLab web request returned 403, so no current remote availability or
latest-branch equivalence is claimed. Linux regmap/ASoC/DAPM/IRQ/PM dependencies
make a whole-driver import unsuitable for the current XNU driver.

**Integration seam:** use the matching header and protection handlers as the
reference for an original host diagnostic that explains the previously recorded
status changes. This avoids guessing which protection condition followed a
command that otherwise returned success. Keep unknown bits explicitly unknown.

**First host proof:** synthetic single-bit and combined-bit fixtures against
the selected revision; compare table entries with the saved pinned source.
This is a report decoder, not authority to clear faults, raise limits, load
firmware, tune gains or issue another effect.

**Work saved:** a versioned chip-state/protection map avoids rediscovering the
mailbox and error vocabulary. Existing hardware command code already uses
many of these facts. The codec file documents a waveform path but does not
provide the missing Tensor audio clock/routing or iOS lifecycle adapter.

## Candidate 3 — libASPL for HAL conformance and narrow helper reuse

**Priority P2; high confidence in source availability, medium in iOS applicability.**

Verified current git ref: `gavv/libASPL`,
`633e0f70203edd87d320fc5a3cae901e1363aac5`:

- [Device.cpp](https://github.com/gavv/libASPL/blob/633e0f70203edd87d320fc5a3cae901e1363aac5/src/Device.cpp)
  has `StartIO`, `StopIO`, `GetZeroTimeStampImpl`, property notification and
  operation dispatch closely comparable to our plug-in.
- [Device.hpp](https://github.com/gavv/libASPL/blob/633e0f70203edd87d320fc5a3cae901e1363aac5/include/aspl/Device.hpp)
  documents callback and object ownership contracts.
- [DoubleBuffer.hpp](https://github.com/gavv/libASPL/blob/633e0f70203edd87d320fc5a3cae901e1363aac5/include/aspl/DoubleBuffer.hpp)
  is an MIT-marked control-thread/write versus realtime/read helper.

The inspected files are MIT-marked; the repository also includes separate
Apple sample licences. Inspect every selected file rather than labelling the
entire dependency uniformly MIT. libASPL targets macOS and includes
`CoreAudio/AudioServerPlugIn.h`; our iOS build locally declares the relevant ABI.
A C++17 wholesale replacement would add work and would not establish ABI parity.

**Integration seam:** compare the existing plug-in's property sizes, unsupported
operations, start counts, timestamp handling and failure propagation against
this independent implementation. Reuse a small MIT helper only for a measured
need. Both implementations use system-clock timestamps, not a proven hardware
playback clock; neither establishes drift-free remote audio.

**First host proof:** drive our actual plug-in function table through a fake HAL
host: enumerate all advertised objects, wrong-object/undersized-buffer cases,
StartIO/StopIO/restart, timestamp calls around a long gap, and missing/failed
speaker and actuator writes. Existing `actuator_write` ignores write results;
its diagnostic must not equate submitted samples with felt motion.

**Work saved:** independent property/lifecycle expectations reduce hand-debugging
inside audiomxd. Hardware transport, virtual tuning and iOS 26 acceptance still
need their existing separate evidence.

## Lower-value leads and rejected shortcuts

- [PortAudio pa_ringbuffer.c, v19.7.0](https://github.com/PortAudio/portaudio/blob/147dd722548358763a8b649b3e4b41dfffbcfbb6/src/common/pa_ringbuffer.c)
  is MIT-style and supplies split-region SPSC copying/publication. It requires
  power-of-two capacity and has a different ownership/layout contract from our
  firmware ring. Useful as a differential oracle or future host staging FIFO;
  replacing 0904 now would duplicate working host code and break its wire ABI.
- [IOAudioFamily IOAudioEngine.cpp](https://github.com/apple-oss-distributions/IOAudioFamily/blob/6fdf514055a9868fe20e4dc3845b78dfa5e27110/IOAudioEngine.cpp)
  is verified APSL **1.1** in this file, not a blanket APSL 2.0 assumption.
  `startAudioEngine`, `stopAudioEngine` and `takeTimeStamp` describe the macOS
  IOAudio family. This source does not implement the missing iOS IOAudio2 path.
- The pinned vendor tree also has a GPL-2.0 CS35L43 amplifier driver. Its ALSA,
  power, protection and firmware dependencies do not make it a standalone
  speaker sink. No amp initialization or transport route is proposed here.
- TinyALSA or Android's full vibrator HAL depends on Linux interfaces absent
  from native XNU. An Android HAL service is not an iOS daemon ABI adapter.
- No generic resampler is needed to prove the current fixed-format 48 kHz path.
  Importing one before samples reach a consumer would not remove the blocker.

## Concrete handoff

First finish the already-requested HAL diagnostic using integrated 0903, and
record realtime admission separately from actual StartIO and non-silent writes.
In parallel, build the matching-version haptic status decoder and extend only
missing lifecycle cases from Google's tests. Review 0832 independently before
calling its service integrated. Keep speaker transport blocked, ROM versus PCM
capabilities distinct, and felt/audible output separate from command success.

This audit changed documentation only. No source was imported, no implementation
was built, no guest/device operation occurred, and no new physical result or
performance gain is claimed. Upstream pins were checked with targeted git ref
queries and raw primary-source reads; GitHub API requests hit a shared rate
limit, and inaccessible current paths are identified above.
