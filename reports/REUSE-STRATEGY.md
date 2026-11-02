# Native iOS reuse opportunities

## Conclusion

Reuse can materially reduce native-iOS bring-up work on Pixel 10 Pro at bounded
component, protocol and tooling seams. Matched Pixel sources, permissive helpers,
Apple's open classes and native-iOS test code are the best donors. None supplies a
drop-in Tensor G5 port or removes firmware, ABI, recovery and physical-validation work.

This report summarizes rationale and priorities. [docs/REUSE.md](../docs/REUSE.md)
is the implementation reference for exact sources, licences, boundaries and local
starting paths; this narrative is not a second task list.

## Evidence boundary

**Physical:** XNU 12377 and the real iOS 26 userland reached human-confirmed Home
and Settings. Five A725 cores, 12.92 GiB RAM, display/touch, UFS reads, RTC and
native battery samples have phone evidence. Backboardd respawns and queued presentations
prevent stability/FPS acceptance; strict GPU health, native Metal and radio service remain open.
See [current project notes](../NOTES.md).

**Host, source and QEMU:** portable Metal sources, parsers, enabled-object checks,
software CoreImage, app-registration tests and recovery tools shorten iteration. They
do not establish physical GPU execution, app foreground acceptance, real HCI, safe
storage or deployability. ARM64, QEMU and physical gates remain [separate](../docs/COORDINATION.md).

**Deployment:** **no iOS root is deployed.** Android recovery erased and reformatted
`userdata_exp.ai`; old aliases, capacity, persistence, approvals and dual-boot instructions
are historical. Fresh storage/recovery plans, qualified backup and explicit approval precede
writes. The product must remain a self-contained Pixel without a Mac runtime bridge.

## Why reuse helps

- **Matched hardware sources prevent rediscovery.** Pixel's Volcanic DDK and Laguna/Blazer trees expose exact layouts, sequences and device relationships.
- **Small Darwin-facing components avoid contract mismatches.** Apple's classes and icli address IOKit/LaunchServices directly, unlike compatibility layers.
- **Host tools and oracles isolate defects early.** AOSP parsers, fake MMIO, malformed inputs and QEMU readback reject bad adapters before phone runs.
- **Selective reuse preserves progress.** Fill missing callbacks in existing native transports, GPU builders, app tooling and display/input paths rather than adding stacks.

Expected savings are qualitative. Source proximity and host tests do not establish firmware compatibility or physical success.

## Top five opportunities

1. **Volcanic DDK firmware/VM/context callbacks.** Adapt MIT-selectable MMU,
   firmware-context, invalidation and cleanup routines into the existing ABI profile.
   Start with the retained dump and fake-MMIO lifetime/reset tests. This supplies
   neither a DXT compiler nor native Metal and cannot bypass strict firmware health.
2. **Board-matched FDT/ADT manifest and ARM64 helpers.** Combine stock facts,
   BSD-option mainline DTS and permissive parsers into an auditable mapping with
   negative tests. Container conversion cannot supply IOKit personalities, power
   semantics or Tensor-specific DMA behavior.
3. **AOSP boot/DTBO/AVB and recovery oracles.** Run pinned upstream tools on
   matching factory artifacts and synthetic failures. This reduces parser work but
   does not recover encryption keys, prove live rollback counters or authorize flashing.
4. **icli-style LaunchServices registration/readback.** Reuse plan → register →
   independent readback → launch/foreground with real app metadata. Keep errors,
   records, URL handlers, exec and foreground separate; do not import entitlement
   or foreign-app refusal bypasses.
5. **Apple open class families plus Laguna DWC3.** Reuse APSL ECM, storage/SCSI
   and HID behavior at matching ABIs while implementing Laguna clocks, resets,
   PHY firmware, DMA and role switching natively. Require real IP traffic or HID
   events, not descriptors alone.

## Dead ends and boundaries

- **No wholesale port:** Sandcastle is Android/Linux on iPhone; QEMU/Inferno are
  host device models, not native Tensor XNU drivers.
- **No GPU target substitution:** mainline PowerVR, Mesa and Asahi do not provide
  this DXT's compiler/firmware ABI. Metal-on-Vulkan and MoltenVK do not remove the
  native DXT driver dependency.
- **No direct Linux-driver import:** threading, memory, DMA, interrupts, discovery
  and power contracts differ. APSL/GPL obligations and per-file licences require
  deliberate boundaries; GPL vendor code is normally reference material.
- **No generic radio replacement:** older Broadcom drivers do not establish
  BCM4390 IPC9/NCI support, Apple80211 association or Bluetooth pairing.
- **No manufactured identity:** OpenSEP is not SEPOS/KeyStore/attestation;
  OpenBubbles and public NAC stubs do not provide legitimate self-contained identity.
- **No proprietary publication or host dependency:** firmware, keys, dumps,
  serials and Apple payloads stay out of Git. vphone, ipsw and QEMU are development
  aids, not Pixel services.

## Staged recommendation

1. **Preserve and diagnose offline.** Keep Android and backups intact; analyze
   retained GPU, GPT and app evidence without unchanged phone runs.
2. **Build narrow host adapters and oracles.** Establish the Volcanic profile,
   FDT/ADT manifest, AOSP negative tests and icli-style original fixture using
   existing owners and transports.
3. **Promote only through build evidence.** Run sanitizer/fake-MMIO/fault tests,
   enable feature gates, emit ARM64 objects and inspect expected symbols. Keep
   source, host, QEMU and physical claims separate.
4. **Rebaseline deployment before physical acceptance.** Qualify independent
   backup/recovery and an isolated allocation, then obtain exact approval. Start
   with an attended temporary boot and minimal known-good root, preserving return
   to unmodified Android.
5. **Expand behind independent gates.** Require stable presentation before
   performance, GPU health before compute and native Metal, LS readback before
   launch, and real association/pairing/traffic before connectivity claims. Dual
   boot additionally requires repeated switching and recovery.

Reuse enables contract-driven integrations; it cannot replace the original DXT/Metal, compositor, secure-identity, peripheral and dual-boot work.
