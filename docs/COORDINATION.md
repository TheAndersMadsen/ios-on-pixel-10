# Coordination and test queue

2026-11-02. This is the shared priority and test policy for the active iOS 26
work. Read the newest entry in [NOTES.md](../NOTES.md) for live state; this file
does not grant a device slot. The phone owner confirms each reservation.

## Ownership

| Responsibility | Owner | Boundary |
| --- | --- | --- |
| Priorities, cross-owner dependencies and this document | <t3-thread://v2/ee541e7a-b76f-4239-af63-d91e41f5105d/64220e88-9625-4f88-8783-6a5c2c7b344d> | No second USB, build or implementation owner |
| Phone, USB reader, release integration, full builds and boot scheduling | <t3-thread://v2/ee541e7a-b76f-4239-af63-d91e41f5105d/2ff85bbd-2161-4de0-b898-ee203a85dfb7> | Preserves running attempts and final captures |
| Native Metal and its ten scoped workers | <t3-thread://v2/ee541e7a-b76f-4239-af63-d91e41f5105d/c8b86fea-b67e-4af6-af2f-9f5b345360d5> | One frozen profile, ABI and composed adapter path |
| CPU prerequisites, clock acceptance and A520 review | <t3-thread://v2/ee541e7a-b76f-4239-af63-d91e41f5105d/4c1e0de2-55d6-4007-b334-bc4a8561461d> | Coordinates existing floor/governor work with release owner |
| Read-only storage discovery, backups and dual boot | <t3-thread://v2/ee541e7a-b76f-4239-af63-d91e41f5105d/35ce6a12-3365-4859-adf2-76570d8b2c7e> | No independent USB, Android boot or storage write |
| Stock apps, registration and host root candidate | <t3-thread://v2/ee541e7a-b76f-4239-af63-d91e41f5105d/1c8ae1db-6c50-41fa-add2-3d6c8c16e5fb> | Own clones; deployment and capacity remain separate gates |

The opening inventory contained five other coordinators and fifteen workers.
Every active owner's context was read, including the subsequent ECM reviewer.
These are snapshots, not a claim that an agent remains running indefinitely.
The native parent confirmed all ten workers received its frozen contract.
The phone parent maintains its existing requested fleet minimum and owns worker
replacement. Do not start another fleet or restart completed tasks for a count.

## Runtime architecture constraint

The user requires the Pixel to remain self-contained. Apps, authentication and
Apple-service work target native on-device operation; Mac-backed validation or
a tethered Apple-service bridge is excluded. OpenBubbles is research evidence
only. Online Apple services remain a goal, while models/research activation do
not establish Apple manufacturing identity. Host builds, offline QEMU reference
tests and debugging remain development tools, not a runtime service dependency.

## Priority order

1. Retain the completed sampler OFF/FAST pair and its capture evidence. FAST's
   initial BaseBoard NSURL-nil abort confounds the timing comparison; do not
   promote a speed/FPS claim or blindly repeat it. Diagnose startup readiness.
2. Use the next compatible UI run to gather several useful observations:
   one selected behavior change, with reviewed passive container, Spotlight,
   battery and existing profiler observations where ready.
3. In parallel, finish the apps guest registration/launch path and the native
   Metal composed adapter. Resolve an observed dependency before adding another
   isolated helper. Both have useful host work while the phone is occupied.
4. Take the changed GPU diagnostic and corrected read-only GPT capture through
   their CPU/context and artifact reviews, then the phone owner's separate slots.
5. CPU source/host handoff is complete and its goal is BLOCKED at 84% (fa5a08f),
   pending accepted runtime/context/artifact/capture evidence. Keep its existing
   floor/downvote stages and explicit unblock events; do not restart it for
   another helper, unchanged audit or host suite. Higher clocks remain held.

A ready useful test can proceed while another owner finishes optional work.
Readiness, dependency removal and user-visible benefit determine the order.
New source research must answer a concrete implementation blocker; reuse the
existing pinned source inventories.

## Physical queue at this checkpoint

| Item | Observed readiness / reservation | Evidence to collect together |
| --- | --- | --- |
| Sampler OFF | Attempt `20261102-111800-sampler-off-p29-r1` captured at expected deadline, unchanged p29, image `ee70fb73…`, raw `6ecc43d9…` | Existing 66-token/1,569-event workload, process CPU by actual phase, crashes, sampler mode, thermal/reset and capture integrity |
| Sampler FAST | Attempt `20261102-112806-sampler-fast-p29-r1`, image `128674c9…`, COMPLETE/captured; script matches OFF, live 997,224 bytes all match RAM; known startup abort confounds timing | Actual fast-path coverage is 1,437,573,559 eligible pixels, identity branch zero; FAST does not compare pixels. Owner missed the visual window. No speed/FPS/visual promotion |
| UI observations | `20261102-115426-phone-p29-art-container-15m-r1` COMPLETE/captured at intended900; unchanged p29/image `5e9bd94a…`/overlay `42bb3b73…`; all 1,450,057 live bytes match, 1,288 final tail absent live | User confirms Battery icon visible. HKART install2/recovered0/refused0; attribution limited. HKCONTAINER execution0 despite correct environment, so hook/retry acceptance stays held |
| p31r1 live diagnostics | RUNNING `20261102-121918-phone-p31r1-live-diag-r1`, image `3f7b1b40…`, source e67445e6, K9d60ca02/Ue07b62fc, five-A725 baseline/deadline300/976-byte line | Input1 plus passive presentation1/bounded AKS1; one attended input attempt after status check, no ambiguous retry or second USB reader. No CPUhealth/high/floors/GPU/Trusty/AoC/persist/ECM/RTC addition; source0847 excluded |
| New CPU health baseline | `7424c92` acceptance handoff, p30 present; proposed image NOT BUILT, literal-admission/common-config review pending; no slot request | New verification/floor/required-sensor/health gates need functional acceptance before sharing an unchanged configuration in later UI timing arms |
| GPU timeout diagnostic | Native parent independently verifies p30 SOURCE/LINK/IMAGE PASS; diagnostic stays BUILD ONLY for CPU/Trusty and RAM-layout context | Actual pending FWCCB raw words, SYS/COMP and original STOP; separate signed START/health/reset after exact accepted context |
| GPT readback r2 | Host PMBR correction `f329418`, reviewed hash and frozen profile; no reservation here | Both GPT copies, CRC/geometry/agreement, saved-byte offline verification and bounded failure evidence; separate storage capture |
| Thermal R1/R2 | Existing lowered-trip stages; not part of UI or sampler timing | Actual sensor downvote, floor release and the stage's own STOP criteria |

The OFF/FAST pair already uses a 990-byte command line. Do not append optional
boot flags or replace either artifact mid-pair. Additional diagnostics belong
in a subsequent checked image/overlay. A single comparison does not justify
a broad speed claim; repeat only if workload variance or a decision requires it.

The earlier explicit 900-second and 1,800-second UI proposals were both refused
before an image/boot. The five-A725 shape is qualified for the existing
`FC_DEADLINE=900` default when `--phone-deadline` is omitted; builder
`test_deadlines` covers this. The correct inspection window is 15 minutes.
This changes no allowlist, clock, guard or CPU context. The refused 30-minute
proposal is superseded; do not reuse it.

p30 is already linked once from release-tree source `af08a9f5`: parent reports
176-series/combined proof, zero undefined symbols and 276 checklist checks.
Native parent independently qualified the exact candidate source, final link
and image in its
`research/ios26-metal-native-20261102/integration/diagnostic-review-r1/p30-parent-review.json`: seven final
executable-text symbols, zero undefined, both length-prefixed 344,068-byte
firmware copies hash148aacc5…, exact image d8925f4f… and 471-byte command line.
This is artifact acceptance; it does not clear CPU/Trusty or memory-layout context.
Kernel SHA256:
`9bbc57038f46622e8faa2ac2d04fd595184a305d959bf8ee8c5202e825e74e55`;
unstripped:
`5dc553c614d2c9ee65fa21451aa72db550e696e2e3318cee5095a87b94aabeea`.
It contains floor0772/0773 with probe off and standalone GPU diagnostic compiled
on/runtime off. The subsequent p31 link failure at C++ get_user_regs is retained;
repaired C declaration1179 produces distinct p31r1/source e67445e6, 180-series
proof/288 checks/zero undefined/ten final text proofs. It includes reviewed
input1176/presentation1177/bounded AKS1178 and the timestamp-race repair. Its
physical diagnostics are running, not accepted. Source0847 and ECM/RTC remain
outside this frozen image; existing p29/p30 identities remain unchanged.

## Shared QEMU queue

The existing /tmp/fleet/qemu-guest-slot.lock remains the admission authority.
Both explicit release handoffs completed, without interruption or polling:

1. Apps registration-r4 completed its planned 900.4016465 seconds, exit0/root
   unchanged. All 837,227 console bytes match the final mirror; persona aborts
   and kernel panics zero, Photos/Settings home frame observed. Registrar exec
   occurred but HKAPPS/readback zero: registration/launch remain unaccepted.
   Final evidence: research/ios26-apps-r1/receipts/registration-r4-result.json.
2. The one native five-OWN-source reference batch then completed in 7.963927916
   seconds within its 300-second bound. Console155,033 bytes, runnerexit0;
   post-batch init-exit panic retained. Five pipeline/cache calls returned0;
   extraction/semantic analysis remains pending. All 60 inputs and CPIO hash
   stayed unchanged. The CPIO is hash-pinned, mode0644, not mode-readonly:
   `2a1654e53d9d22405bf44161896f223fde60064b527b13d9cb72f25a4301214f`,
   76,498,796 bytes. Reference output is not native GPU/health acceptance.
3. Release was relayed back to Apps. Registration-r5 completed its full planned
   900.6058925 seconds, exit0/root unchanged, source b840825 and candidate
   `196809464b5e8fe2fd46b4502a3665b7559285f6cabbf2a6c0cf118c6ce730cb`.
   Final evidence supersedes the earlier C-entry-only snapshot: C main,
   framework_load/framework_loaded and manifest_read are positive. Workspace,
   readbacks and launch requests were not reached; no API/launch PASS or cause
   is established. Live892,546 bytes match the mirror; 1,331 final tail bytes
   are retained separately and parsed (TOP900/TOTAL), merged final893,877 bytes.
   Final capture/cleanup/lock release is complete, with no reservation held.
4. Apps source98b4530 commits C-only startup/receipt formatting, removing the
   NSJSON class import. Its next own image will add narrow POSIX/header and
   NSData/plist enter/return probes around the observed manifest boundary.
   Concrete frozen candidate/argv is pending; no new guest is requested here.
   Registration plus conditional representative launches remain its acceptance
   goal. Existing reservations retain priority under the shared lock.

Apps and native Metal send release events directly to each other and the
coordination thread using mode auto. A refused claim gets one blocker report;
wait for the owner's next event. Do not interrupt a guest or poll its status or
lock. Host composition and launch preparation continue while the slot is occupied.

## Collect more evidence without losing attribution

Before a boot, the owner freezes the test manifest: source/patch identities,
kernel/unstripped/image/overlay hashes, exact argv arrays, enabled gates, CPU
context, workload, expected positive records, PASS/FAIL/STOP and rollback.
Use current handoffs; a report that an image was built is insufficient.

For a normal UI run, reuse the existing workload and collect its boot/startup,
home/Settings/scroll/return and idle phases from actual trace times. Compatible
passive probes can capture container API result/error/PID, bounded Spotlight
call/result/stack evidence, battery registry/powerd/getter observations and
ordinary CPU/thermal health in those same phases. Each probe needs its own
positive execution receipt. An absent failure is inconclusive.

Existing ordinary CPU/thermal logs may share a UI run. The new CPU health gates
in `research/ios26-cpu-complete-r1/acceptance/CPU-NEXT.md` change fail-stop and
floor-release policy; they are not passive probes. Their proposed p30 baseline
line is 1,000 bytes, or 1,020 with optional WFI counters. Establish the reviewed
common functional configuration before later UI comparisons; do not add these
gates to the frozen sampler pair. Current p30 is probe0/high0 and cannot run the
isolated lowered-trip R1/R2 stages, which require a separate probe1 kernel.

Spotlight's earlier userland interposition candidate is withdrawn. Its real
kernel AKS trace needs its final patch/token review and a new linked kernel.
Do not use an old overlay as a substitute. For a future reviewed composition,
the proposed health line plus `blazer_aks_trace=1` is 1,019 bytes; adding optional
WFI is 1,039 and exceeds the 1,023-byte limit. This is budget arithmetic, not
image admission; omit optional WFI if needed and verify the actual final line.
Ready artwork/container work need not wait for unfinished optional tracing.

Compose overlays through the actual release consumer. Extend the sole selected
hk_env rule in place, preserve the hgltrack chain and unrelated records, check
per-variable/cumulative limits and final signing/protection. Never append a
duplicate selected environment rule. Host-check the final composition, not just
each input separately. Keep passive observer settings common to both arms of
any subsequent timing comparison.

Do not combine first physical validation of new input/USB transport, CPU
startup, lower thermal trips, GPU firmware START or storage access with the
sampler comparison. Forced software CoreImage remains a separate compatibility
variant from native Metal acceptance. Brightness changes need their own bounded
panel/workloop acceptance; an ordinary UI run can only observe already accepted
brightness behavior.

Keep one live reader and preserve the complete stream and final RAM capture.
Report compared overlap, bytes lost/wrapped and final tail separately. HK TOP
layer/admission counters are not completed-frame FPS, and input injection times
are not touch-to-glass measurements.

## Cross-owner blockers that change scheduling

- **A520:** physical attempt `20261102-110932-cpu0-audit-p29-r1` completed
  at its intended deadline. Strict audit failed: ACTLR bit38 set, bit9 clear;
  five-A725 SMP passed. No A520/OFF/re-entry/cpu1/register write or unchanged retry.
  CPU parent is reviewing privilege/reset context on primary sources, host only.
  Latest CPU handoff300191 pins the exact r0p1 TRM: EL2 reads do not prove EL3
  permission for writes or persistence. No safe live write path is established;
  its ignored CAS-probe draft is withdrawn and never executed. Goal is now
  BLOCKED on the recorded external acceptance gates, with production unchanged.
- **One-core test recipes:** p30 GPU diagnostic `d8925f4f…` and dualboot
  `phone-test-r2.json` use `cpus=1` without `blazer_bootcpu`. CPU parent identified
  that GPU recipe as entering unfixed cpu0 A520; coordination also checked the
  GPT recipe and routed it for review. Both need explicit CPU and test-owner
  context acceptance before scheduling. A possible A725 recipe is a changed
  image/context, never an automatic argument substitution.
  Phone owner's existing context reviewer also found p30's RAM window base
  0x882000000 differs from prior health's 0xa00000000. Bind CPU, Trusty and full memory
  layout in the existing review; source/link/image PASS does not clear this
  difference. No automatic window or core replacement is accepted.
- **Apps:** commit `c214b86` supplies the inventory/registrar and host tests.
  The own 20 GiB clone restores all 49 bundles and passes signature/fs checks;
  it cannot fit the phone's current 8 GiB allocation. No registration, launch,
  physical deployment or genuine SEP/Apple-service acceptance was established
  at this checkpoint.
  QEMU r2 mounted the root, then failed seed line40 with EINVAL; retained console
  existed despite UART0. Coordination located the panic and exact p29 symbols.
  Apps owner confirmed the file extent at17,532,928,000 exceeds fake UFS's
  8,589,934,592-byte view, using the actual sanitized read path. Its r3 guest
  uses the full RAMDisk backend and the same root hash; it passed varfs and
  reached launchd, SpringBoard, lsd/MCM and the actual registrar. No registration
  readback/UI frames appeared; usermanagerd aborts on its missing persona
  manifest. Apps owner requested its own stop and is preparing apps-full-r2
  with the canonical current-r3 var.skel/prefs instead of the old light clone's
  baseline. This is not evidence of a new physical-root persona regression.
  Corrected apps-full-r2 is now guest r4 ACTIVE under the shared lock: root
  `bc9f588340425202c686074202c4d57e2b935d628c47cdf7095deeaa5b0ddd70`,
  source `64ffd35`. Owner reports all 55 canonical seed files/targets match,
  persona/Medina and 676 baseline jobs are retained, actual TSV consumer and
  all 49 signatures pass. Registration readback/launch remain pending; the
  corrected baseline is not physical deployment acceptance.
  Do not remove seed data or widen physical partition bounds to bypass this.
- **Native Metal:** `9db93cb` and the ignored
  `research/ios26-metal-native-20261102/integration/CONTRACT.md` freeze the
  measured profile. Completed UC-r2 is frozen; UC-r3 now owns the single actual
  kernel/provider composition and AIR-r4 the linked userspace assembly.
  FW ACTIVE/compatibility, true DMA/context/MMUCACHE, compute command body,
  USC retirement/launch and authentic engine/cache/UPL handback remain blockers.
  A diagnostic capture ending at timeout remains health FAIL.
  Local UM26.1@7036548 differs from donor/profile26.1@6967606. Agreement on a
  120-byte body, CSW or PDS alone does not establish compatibility; reconcile
  this through the existing shared contract, without a second broker/profile.
- **Recovery/storage:** saved init_boot has a valid metadata signature but
  fails its payload hash; the set also lacks matching dependencies/trusted AVB
  graph. It is not a verified restore set. Android integrity and isolated iOS
  storage remain unproved; no Android/root/slot/GPT/firmware change follows.
  Offline planning af2fcaf/05d8532 has not qualified an independent backup
  destination, bulk readback or recoverable key state. Its smallest later AVB
  proposal is selected root-vbmeta's first 4 KiB after accepted GPT/context,
  followed by separately reviewed exact extents; today's consumer stays GPT-only.
  The reuse attribution is corrected: pinned f2fs-tools refuses aliases in
  `do_defrag`, not `do_resize`. This proves no safe resize or migration route;
  see [the corrected storage report](reuse/2026-11-02/storage-filesystems.md).
  HOST milestones41828ff/45fbd6e also reject saved B init_boot and tiny vendor_boot
  payloads. Scratch Magisk restore/repack can report stock CPIO while both A/B
  payloads still fail and backup SHA1 differs; no restored artifact is accepted.
  Other signed archives use a different untrusted key and a Linux7.3-next kernel,
  not an established matching stock Android set. The user authorized the exact
  Google blazer DP11.261002.005 archive for offline verification only; its
  download receipt now reports the expected9ac046a4… hash and size matched.
  Component/AVB/key reconciliation is still pending with the existing owner.
  Reuse that one artifact/inventory; it may supply same-build provenance for the
  native GPU UM/donor gap (inference). Archive verification grants no factory
  script/flash/Android boot or expanded live reads. Refresh backup capacity:
  the post-download snapshot no longer fits the planned raw copy plus reserve;
  an independent destination remains unqualified.

## Efficient integration and handoff

Only the release owner integrates and links the shared kernel. Submit reviewed
default-off source together for a frozen release cutoff; build multiple test
images from that exact kernel when their gates and context permit. Do not wait
for unfinished optional work or force unrelated runtime gates on together.

Every ready submission includes: owner and changed source, exact hashes,
dependencies, meaningful host results, actual gate-ON ARM64 objects and named
executable symbols, OFF controls where relevant, exact build/boot argv, expected
coverage, PASS/FAIL/STOP, shareability and rollback. Re-run affected composition
when a source/dependency changes; do not repeatedly run unchanged suites.

Use existing per-owner handoffs and append the existing fleet BOARD. Do not
edit peers' source or repeatedly prepend competing NOTES updates. Send changed
milestones, blockers, readiness and completed captures to the coordination
thread with `t3_thread_send` mode `auto`; the event can resume coordination
when idle. Routine status polling is unnecessary. New delegate reviews still
use a new delegate task; a steering message is not a substitute.

Coordination evidence and exact inventory/delivery receipts live under ignored
`research/ios26-orchestration-20261102/`. Delivery alone does not prove adoption;
record actual owner acknowledgments. Preserve the running phone attempt and
shared QEMU lock. Destructive device steps still require the user's explicit
approval of the concrete plan.

