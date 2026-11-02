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

The resulting p30 source/link/image now passes independent artifact review,
including final text symbols and exact embedded signed firmware. Its image is
HELD: cpus1/no-bootcpu enters cpu0 A520 with ACTLR bit9 observed clear, and its
RAM base differs from the prior health image. The existing CPU/phone reviewer
must reconcile CPU/Trusty/memory layout before any changed diagnostic slot.
See [coordination policy](COORDINATION.md) and newest NOTES; no automatic core
or RAM-base substitution is accepted.

A separate, explicitly reviewed one-A725 image now passes exact artifact
checks: `01eae6c83e7e0c3f3adedf3816672fa6e8152b7746e2cf11349eebbb6919135f`.
It retains the p30 kernel, firmware and RAM base, with one running ADT CPU at
reg0x200 and the exact 492-byte command line. This is conditional acceptance
of the bounded diagnostic proposal. CPU/Trusty/IRQ/full-layout and attended
recovery acceptance remain with the CPU and phone owners; it has not run.

## Portable source checkpoint

The original portable implementation is now under [native/metal/isa](../native/metal/isa/README.md)
and `native/metal/streams`. This 56-file source import preserves all 35 C/header
files byte-for-byte, scoped MIT notices and exact external dependencies. Its
default feature gates are off. Parent verification passed 12 host ASan/UBSan
tests, strict iOS ARM64 links and 44 named executable symbols across 12
implementation objects. This baseline is ISA revision4; revision5 and the
runtime import require a coherent, separately reviewed migration.

The reserved offline reference batch has completed and released its QEMU lock.
All five owned sources produced compiler/cache results; all 60 host input
hashes remained unchanged. The second shader END is a separate coefficient
entry, not padding. These results establish compiler reference facts only.
Current ISA obligations remain nonzero, and the preserved AIR parser loses
some FP attributes; its requirements query cannot authorize native code.
No native execution, firmware health or render admission follows.

The composed kernel review found a firmware-status snapshot race. The parent
candidate uses the admission result from the same status snapshot in all
three affected callers. Fresh enabled ARM64 objects and focused baseline/fix
reproducers pass. Both surface handback corrections are already present in
the frozen UC-r3 composition. Exact source, build and review receipts remain
under `integration/review-fixes-parent-r1/` in the ignored research namespace.

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
