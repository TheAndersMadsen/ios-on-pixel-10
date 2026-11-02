# Native Metal on Pixel 10 Pro

Active effort started 2026-11-02. The target is native Metal execution on the
Pixel 10 Pro under iOS 26. Ten implementation agents work on separate layers;
this coordinator reviews, integrates and commits. The existing phone/release
coordinator exclusively owns full release builds, USB and physical testing.

## Starting evidence

The recorded physical boots show iOS 26 UI, touch and a GPU core ID read.
They do not establish GPU firmware execution, shader execution or accelerated
Metal. Host work includes a firmware health path, HMGU v1 wire definitions,
Metal resource uploads, restricted IOSurface imports and three fixed-layout
DXT arithmetic group encodings. These are components, not a working stack.

Later physical checkpoint, 2026-11-02: SEND2 accepted the signed firmware
(`20261102-101843-native-metal-send-p29-r1`). HEALTH5 then failed
(`20261102-102719-native-metal-health-p29-r1`): started1, KCCB consumed1/1,
FW connection0, pending FWCCB1/0 and no execution return. No unchanged retry
is scheduled. Capture/decode the pending firmware message in a reviewed
diagnostic before requesting another device test. Native Metal is unproved.

The standalone timeout diagnostic now passes independent parent review:
actual health/hook sanitizer tests, three rejected behavioral mutations,
byte-identical vendor layout measurement, sparse patch application and
enabled ARM64 text-symbol checks with gate-off controls. It captures bounded
pending FWCCB entries without acknowledging or consuming them. Its corrected
compatibility offsets also show why the old log's layout words were not BVNC.
Exact review, patch hashes and build request are under
`research/ios26-metal-native-20261102/integration/diagnostic-review-r1/`.
This qualifies a new diagnostic artifact for build review; it establishes no
firmware execution and schedules no boot. Lifecycle/queue diagnostics remain
separate candidates.

Current source reuse decisions and refresh instructions are in
[NATIVE-METAL-UPSTREAM.md](NATIVE-METAL-UPSTREAM.md), alongside the broader
[reuse audit](REUSE.md). Adopt exact compatible code with its notices and
preserve the native PowerVR execution path.

Local evidence and earlier source are under `research/ios26-fleet/handoffs/`.
The active roster, exact delegated tasks, source paths and result receipts are
under `research/ios26-metal-native-20261102/`. That directory stays out of git.

## Implementation owners

| Owner | Deliverable |
|---|---|
| firmware | Signed firmware initialization, execution health and lifecycle |
| uc | HMGU IOKit user client, task ownership and BO handles |
| vm | DXT GPU page tables, heap allocation and wired memory mapping |
| queue | Firmware contexts, submission and actual job completion |
| isa | DXT instruction encoding, allocation and executable shader rules |
| air | Faithful AIR/LLVM lowering into the supported native shader subset |
| streams | PDS and CDM compute streams, then render control/state streams |
| metal | Metal pipeline, command buffer and native driver integration |
| surfaces | Authorized IOSurface import, cache ownership and fence lifetimes |
| validation | Native Metal smoke application and reproducible execution checks |

Use the existing HMGU v1 and HMUSC1 contracts. Propose changes explicitly;
keep unknown engines and operations unavailable until implemented. Each owner
writes only its own topic directory and returns source, tests, exact build
commands, object symbols, hashes and remaining integration requirements.
Completed owners receive their next bounded task through a new delegation.

## Acceptance

1. Load the legitimate GPU firmware and prove fresh execution completion on
   the phone. Queue consumption or a firmware PING alone is insufficient.
2. Run an owned compute shader through the native Metal path. Initialize the
   output and guard words to sentinels, submit using real GPU virtual memory,
   wait for actual engine completion, synchronize caches and compare readback.
3. Exercise malformed inputs, missing completion, repeated allocation and
   destruction, and teardown while work is pending. Resources must remain
   pinned until completion or established DMA quiescence.
4. Produce a known rendered image through Metal, verify pixels and connect
   its completion to IOSurface presentation. Only then measure application
   behavior and frame timings on the phone.

Host tests, ARM64 objects, link checks and QEMU results are recorded separately
from physical evidence. A synthetic backend cannot establish native execution.
Build guarded XNU code with BLAZER and the tested feature gates enabled, emit
ARM64 objects and inspect expected text symbols before claiming compilation.

## Device and repository constraints

Use temporary RAM boot images. Preserve Android, partitions, bootloaders,
slots, persistent firmware and backups. Each destructive operation requires
the owner's confirmation. Device access stays with one coordinator and must
be reconciled with any active attempt before another boot.

Keep firmware, Apple artifacts, device dumps and identifiers out of git.
Review provenance before promoting original source from local research into
tracked paths. Record each milestone, commit and exact physical attempt result
in `NOTES.md`; distinguish observations from inferences.
