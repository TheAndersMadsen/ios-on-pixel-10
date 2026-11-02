# Native Metal on Pixel 10 Pro

Scope: native PowerVR firmware, GPU execution, and Metal under iOS 26; host, source, and QEMU results are supporting evidence only.

## Current result

- **Physical:** the one-A725 strict-health attempt **failed**: no executed health return or rung-5 completion was observed. Firmware execution is not established; rendering and native Metal are unproved.
- **Physical evidence retained:** one complete 112-byte pending `DEBUG_DUMP` FWCCB was captured read-only without acknowledgement. Its type and flags are identified, but its payload remains uninterpreted.
- **Source/host:** firmware, HMGU/HMUSC1, VM, queue, ISA/streams, user-client, surface, and Metal components have focused tests and ARM64 link/symbol checks. These successes are not native execution or proof of an integrated working stack.
- **QEMU/offline references:** compiler, cache, and synthetic-backend results establish implementation facts only; they do not establish firmware health, shader execution, or render admission.

## Remaining work

1. Interpret the retained dump and firmware-state evidence against the matched Volcanic DDK callbacks; keep raw observations separate from inferred meaning.
2. Make an evidence-driven firmware lifecycle/health correction, with host/fake-MMIO tests first and enabled-gate ARM64 object/symbol checks. Do not retry the failed attempt unchanged.
3. Only after fresh physical strict health passes, integrate real GPU virtual memory, submission/completion, and resource lifetime through an owned Metal compute shader.
4. After compute readback passes, add rendering, IOSurface presentation, malformed-input, timeout, teardown, and repeated-lifetime validation.

## Acceptance before expanding scope

- On the phone, obtain a fresh executed health return and bounded completion; queue consumption or a firmware PING alone is insufficient.
- Run an owned compute shader with real GPU virtual memory, actual engine completion, cache synchronization, and sentinel/output/guard-word readback.
- Keep resources pinned until completion or established DMA quiescence; reject malformed inputs and handle missing completion and pending-work teardown safely.
- Verify known rendered pixels and connect completion to IOSurface presentation before claiming native Metal rendering or measuring frame performance.

## Evidence and source

- [Physical one-A725 GPU records](../research/ios26-opt-20261102/gpu_a725_physical/) — strict-health failure and retained phone capture.
- [Physical FWCCB analysis](../research/ios26-metal-native-20261102/integration/physical-a725-analysis-r1/) — lossless 112-byte report and explicitly limited interpretation.
- [Diagnostic review](../research/ios26-metal-native-20261102/integration/diagnostic-review-r1/) — read-only capture design, host tests, and ARM64 build evidence.
- [FWCCB decoder](../research/ios26-metal-native-20261102/queue-r5/) — host decoder, layout proofs, and fixtures; not device execution evidence.
- [Portable native source](../native/metal/) — ISA, streams, and related implementation with feature gates and source documentation.
- [Upstream reuse policy](NATIVE-METAL-UPSTREAM.md) — compatible source pins, notices, and native-path constraints.
