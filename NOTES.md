## Reuse audit completed, 2026-11-02 — 24 specialists, 16 concrete follow-ups

Committed **3139238** (`Audit reusable code and tooling across 24 bring-up
 domains`): `docs/REUSE.md`, 24 topic reports, completed native-agent roster,
11 parent-verified source-file receipts and 16 proposed integration tasks.
All 24 inherited GPT-6.1-Sol assignments returned; no continuing fleet promised.
Documentation index links the audit. This is completed research, not runtime
implementation or hardware acceptance.

**Best reusable source:** MIT-side Pixel Volcanic MMU/context/cleanup code;
MIT matching panel/revision/command helpers; MIT ipsw CAR manifests; licensed
HakiOS WLAN discovery/station glue. Newly recovered from the correct GitLab
6.12 tree: BSD-option Wave6 register header and Samsung U100 GPL transport,
plus Apache AOSP UCI schemas/tests. These close earlier missing-source leads.
Standalone metal2vulkan-air is a real frontend boundary but copyleft/Rust costs
and existing MIT scalar AIR overlap make host evaluation the first task.
No inspected project supplies a complete DXT71 compiler/native Metal stack.

**Avoid duplicated labour:** actual p29 already contains many patches older
handoffs call pending. Keep current sampler/VM/queue/overlay owners; finish
adapter wiring and composed acceptance instead of new driver stacks. Existing
RTC0657, wake/palm1270, MotionProbe and completed bt-3 capture are actionable
local backlog. Exact paths/pins/licences/prerequisites/first tests are in the
reports and `docs/reuse/2026-11-02/next-tasks.json`. Extend the native-Metal
parent's concurrent source collector rather than creating another one.

**Verification:** parent fetched11 pinned public text files; panel/MMU bytes
match local donors. Source markers/hash metadata PASS; corrected Wi-Fi report's
release SHA to independently verified237e3889640333558525c8082593e68cc5401405.
All28 audit artifacts passed local-link/content/JSON/whitespace checks; staged
scanner and pre-commit check PASS (`clean:188files`). No kernel compile/link or
runtime test performed for this audit; no FPS/boot-time improvement claimed.
GitHub unauthenticated API limits and unavailable Tegu URLs are explicit limits.

**No new device attempt ID:** no USB command, boot, firmware action/download,
radio operation, root/partition/slot write or flash by this fleet. Other parents'
implementation changes remain theirs. Physical evidence used includes captured
health attempt20261102-102719-native-metal-health-p29-r1 FAIL; SEND/KCCB
consumption is not shader execution. Follow the phone owner's newest handoff
for any subsequent attempts. Prior blocked AoC and failed Claude Mesa tasks were
not restarted. Native non-Mesa production policy and storage constraints hold.

Next implementation order: extend source/feature receipts; finish measured
sampler/assets/container paths; reconcile GPU ABI and existing callbacks; add
small WLAN/ECM adapters; consume Wave6/U100 host decoders. These16 follow-ups
remain **proposed**, not built, integrated, scheduled or physically verified.

## Dual-boot checkpoint commit, 2026-11-02 10:47 CET

Implementation committed as **13a77d8** (`Add native read-only UFS capture for
dual-boot storage discovery`), including original service/host tools/tests,
image-token guards, licensing and docs. Pre-commit tracked-artifact check PASS,
160files clean. Read-only candidate image/hash, all build receipts and phone
acceptance remain in the 10:44 entry and `research/ios26-dualboot-r2/HANDOFF.md`.
Internal request to the sole phone owner delivered as steering; awaiting its
scheduling/result event, not independently using USB. No physical attempt by
this thread; full dual boot and Android integrity remain unproved. Next: obtain
fresh GPT capture, then design isolated storage and complete data backups before
any destructive migration approval. Goal remains active.

## Dual-boot readback implementation, 2026-11-02 10:44 CET (host only)

Original native read-only USB/UFS discovery service and strict host GPT verifier
implemented in `dualboot/` + `tools/dualboot.py`. Independent worker, runtime
exact-1 gate, attached physical LUN only, validated exact READ10 receipts; no
write/reset/slot path. Source staging/validation tools, tests and acceptance in
`docs/DUALBOOT.md`; all context-bearing patches/captures stay ignored in
`research/ios26-dualboot-r2/`. Full handoff and exact phone-owner argv:
`research/ios26-dualboot-r2/{HANDOFF.md,phone-test.json}`.

**PASS (host):** ASan/UBSan C state machine + actual XNU adapter on real N882 ABI;
13 Python suites including actual C-to-host-to-snapshot; existing USB model20cases
+25seeds, USB tool22tests, image-tool78tests. Final stage-r3 emits BOTH real ARM64
BLAZER=1 objects and expected implementation symbols. Private patch
`14eba083d3cab4670d21ade61eb2ac95ca3a778d7d540db63f073746bfef6fcd`
applies to p29 source `237e3889640333558525c8082593e68cc5401405`; proper private
BSD header export included. Release source/artifacts unchanged.

**Full candidate link PASS, 0 undefined, all266 original symbol/string/disassembly
checks PASS.** Baseline relink equals p29 byte-for-byte except16-byte LC_UUID;
every release object hash unchanged before/after, only USB/UFS objects replaced.
Initial link-r1 baseline mismatch was corrected by archive placement, then sole
UUID difference explicitly verified in r2/r3. Final candidate kernel
`30db07c53a167af55df5de265e17fb3d9551c14e8eacb63cbc02a277a2dce14e`,
unstripped `0ce50d8bbc92bb7b998c636406b7f97d3aab5fe7809dc1bd23b72e2dfeb99cf5`.
Image `research/images/dualboot-gpt-readback-r1/boot.img`
`21cba4e8bc71f0217432e043bffba0d3b5b8c5dcc1ede73fa523e782d97cc8d0`
build+check PASS; cpus1/deadline300,507-byte line, no persist/GPU/Trusty/clock
additions. No boot result implied by image-tool's structural "bootable" label.

**No new device attempt or USB command by this parent.** Sequential read-only
capture slot requested from the existing phone owner via internal steering and
shared BOARD; delivery confirmed, scheduling/physical acceptance not confirmed.
Do not independently boot. First capture binds nonce0x4f7ef40d422dc249 and LU0
READ CAPACITY31147008blocks, verifies both GPT copies/CRCs/geometry twice and
re-verifies saved bytes offline. It is metadata only, NOT a full partition
backup, Android integrity or isolated-root proof. EP0 throughput/full backups,
Android F2FS reservation, dedicated allocation/migration/rollback and native
chooser/Android handoff remain unfinished. Goal stays active. No destructive
approval requested before a concrete verified storage plan exists.

## Reuse audit launched, 2026-11-02 (24 research agents)

User requests a large fleet to find existing resources/code that remove manual
porting work. Started **24 native GPT-6.1-Sol research agents** in this thread;
all 24 reported running at the launch inventory. Scope/roster and topic reports:
`docs/reuse/2026-11-02/`. Each compares actual current release source to pinned
primary upstream code, checks file-level licensing and returns concrete adapter
and validation tasks. Parent will verify, synthesize and commit the audit.

Research only: no implementation change, kernel build, device command, boot,
firmware send/download, radio association, partition/root/slot write or flash by
this fleet. Existing phone/native-Metal/dualboot parents keep ownership. The
newer physical health STOP in the phone owner's handoff below remains binding;
firmware SEND/command consumption is not proven GPU execution. Prior blocked
AoC work and failed Claude Mesa task are not restarted. Native non-Mesa GPU
production policy preserved; other stacks are inspected as references only.

Early findings: many supposedly pending patches already exist in p29. Matching
6.12 vendor source includes individually MIT-licensed panel and dual-MIT GPU
interfaces; old6.6 and newest6.18 must not be substituted indiscriminately.
GitHub unauthenticated API rate limits affected discovery; pinned raw source,
GitLab and local snapshots remain usable. Findings are not speedup claims.

## Phone owner result, 2026-11-02 10:33 CET — health test STOP, six optimization agents active

Physical health attempt `20261102-102719-native-metal-health-p29-r1` COMPLETE/captured, session48156 exited0 (runner success, **GPU test FAIL**). Supplied imageSHA `2df3ec84f3894ea36ac200cf350a46eb43e51d6e4dc9b4c34f2f4dad222b8bf7`, p29. Rawkernel.logSHA `a402278beac84b5b617a1c5b22608296331fb6c44d998a260fdcb79e15b935f6`. Fresh current mirror decoded to attempt/decoded.txt. Exact records: SEND result0/202ms; shareddata mainheap+0x22d000; SMCSTART0; started1/ts0xb8d; **connfw0/os1, KCCBw1/r1, FWCCBw1/r0**, sysdata0/0, compBVNC0/0. No returnslot1. STOP:noKCCBexecution1s, purposeful panicblazer_gpu_tipc.c670. XNU2.0s/payload28.1s, softwarePSCIreset, postreset38C SOC89 VCELL4332,0CPMerrors/thermalbreadcrumb. Phone backinfastboot. No unmodified retry/progression; native-Metal parent received exact failure via steer. Queued FWCCB diagnostic needs decoding; no render/nativeMetal claim. MCU startup and command consumption are physically observed, full firmware/host execution acceptance remains failed.

Independent strict verifier on freshdecodedcapture FAIL as expected. Parent found it parsed FW connection but did not requireACTIVE2; added actual regression demonstrating falsePASS for0/1/3/99, then fixed predicate. Existing8unittestmethods nowPASS, including4badconnectioncases. Local patch/hash in `research/ios26-opt-20261102/parent/`; no kernel change. Other native-Metal namespace untouched. Source references GTA_FW_ACTIVE2/GTA_OS_READY1 in p29driver.

Latestuser goal requires>=5activeSolagentsinTHISthread; prior feature fleet allfinished. At10:24 started6named runtime optimization tasks underios26-opt-20261102: sampler, settings_assets,cpu_fast,live_input,boot_services,live_analysis. `roster.json` records exact IDs/links/model. Parent alone ownsUSB/release/commits; separate native-Metal goal still owns its10hostdelegates and namespace. Keep no-less-than5 here at work boundaries/completionevents, replenish with useful implementation; don't restart blockedAoC task or oldClaude workers. No task may equate a host-only helper with a working hardwarefeature.

Currentprogress: p29 nativeHome/Settings and verifiedliveUSB physicallywork. UI stillheavy lag/missinglogos perowner. Profile identified CPU CAimage_sampler variants; sixworkers are implementing wired fixes, parent will build/test actualcandidates. Fullgoal veryfast/perfectnativeiOS26 remainsunmet/active. Earlier host-only delivered labels and45%figure are not completionproof.

## Inferno source assessment, 2026-11-02 (host only)

Committed assessment: `a127747`, `docs/INFERNO.md`. Reviewed the current official
Inferno `26b36cc8d59535ed1d9963faab25ac576111edcb` and website
`596403e772703cc8478a7444dec26a3203ff2a58` through their public Git API; the old
GitHub mirror was archived/moved, so its older support issues are stale.
Current guide documents iOS26 support and software-rendering limitations.

**Observed source:** filesystem patcher fixes the same SWContext missing
`track_surface` call addressed by our physically tested hgltrack. Additional
CoreImage (`_isWidget` and GPU/GL choices), wallpaper and Neutrino software paths
are concrete leads, not established fixes for our missing assets or lag. No
native Tensor G5 DXT driver supplied. Do not layer duplicate surface tracking
or globally disable renderer paths during native Metal validation.

**No build, emulator/phone boot, device command, restore, firmware download,
root/partition/slot write or runtime deployment in this assessment.** Existing
phone attempts remain with their coordinator; the active device handoff below
is preserved. Public source copies/hash receipts: `research/ios26-inferno-r1/`
(ignored). Next: inventory exact23G90 cache symbols/patch state, then one
optional reversible compatibility change in our existing QEMU harness before
returning a concrete candidate to the phone owner. Benefit remains untested.

## Active optimization goal, 2026-11-02 10:25 CET (phone owner)

Latest user goal: native iOS26 very fast/perfect, keep at least5 GPT-6.1Sol agents active in THIS thread. Inventory at10:21 found0 active children here (separate native-Metal parent has10). Started6 own Sol workers under `research/ios26-opt-20261102/`: sampler, settings_assets, cpu_fast, live_input, boot_services, live_analysis. Exact task IDs/links in `roster.json`. They are host-only, must wire runtime fixes and deliver actual diffs/test candidates, no isolated helper pretending hardware works. Parent checks inventory at work boundaries/replenishes on completion events; no polling delegates. Only parent usesUSB/release/boots/commits. Other parents' namespaces preserved. User's onlySol restriction persists.

**Recovered SEND physical result:** attempt `20261102-101843-native-metal-send-p29-r1`, supplied image6e34330f…, matching p29. Exact `SEND_FIRMWARE_IMAGE len8 cmd0x1 result0 in185ms`, then `rung2PASS` purposeful panic atblazer_gpu_tipc.c665. Raw4MiB SHA `49bff66a19a3da5b1dc42508ee906917ade02385923ebf645413b00563ebaba4`. XNU1.0s/payload27.0s, PSCI-SW, postreset38C SOC89 VCELL4332,0CPMerrors/thermalbreadcrumb. Not GPU execution. Version warning24.2/26.1 + process_st_info278 is documented gpufw.md result0-with-warning GO case, also seen in stock10-22logs; source/stock caveat checked before progression. No change to TEE/authentication/firmware partitions.

**Next device action:** separate native-metal-health-p29-r1 temporary RAM boot launched by phone owner after SEND capture, cpus1, tipc5, deadline300, no otherTrusty/persist tokens. ImageSHA `2df3ec84f3894ea36ac200cf350a46eb43e51d6e4dc9b4c34f2f4dad222b8bf7`, samekernel5aad8978…/unstrippedcc979153… . One bounded HEALTH command, no rendering. PASS needs fresh START0, started1, expectedconnection, returnslotexact1, KCCBw1/r1, emptyFWCCB, rung5PASS + purposefulend. Any refusal/timeout/unexpectedreset STOP/no retry and retaincapture. Runner session recorded below when tool returns. Do not independently boot; native-Metal parent notified via steer and BOARD.

**Preserved physical evidence:** p29 liveconsole1,533,021bytes and profile967,660bytes each compare0mismatch againstRAM, only479panic-tail bytes not readlive. Profileattempt20261102-101134 completeddeadline300, XNU300.6s, postreset38C. QuartzCore.s resolves sampledPC184129b58/1841298f8 to ARGB8_Host CPU image_sampler variants. Cache.symbols absent: broad ipswa2s cannot currentlyresolve allPCs; don't fabricate names. Home/Settings user-confirmed, logosmissing and heavylag remain failures. Earlybackboarddnilpathintermittent. Need integrated optimization + repeated physical measurement, not morefinished-agent counts. Tracking commit6cbb07e has verifiedliveUSB and45% physical-status figure.

## Native Metal firmware test preparation, 2026-11-02 10:20 CET

Concrete progress, HOST ONLY: built/check-verified two isolated p29 RAM images:
`native-metal-send-p29-r1` SHA256 `6e34330fa3b2e1e94d44a2b7f45ec00db1aab9e9f31bbc7ed96be905704ae261`;
conditional `native-metal-health-p29-r1` SHA256 `2df3ec84f3894ea36ac200cf350a46eb43e51d6e4dc9b4c34f2f4dad222b8bf7`.
Both in `research/ios26-bootchain-r1/run/`, cpus1, deadline300,448-byte cmdline,
no competing Trusty/persist arg. Image-tool check, shim route87/speed55/stage9,
route20/20 and speed21/21 mutants, seven replays and brightness1007 PASS.
Reused existing p29 `5aad8978…` / unstripped `cc979153…`; no new full kernel link.
Verified complete signed GPU firmware byte-identical in each kernel, correct
length prefix, and real start/health symbols in __TEXT_EXEC,__text.

Parent reran current release's actual firmware C/header/transport in isolated
`research/ios26-metal-native-20261102/integration/p29-host`: ASan/UBSan **85 checks,
zero failures,51/51 mutants detected**, exit0. Harness path relocation only;
source identity and full receipts saved. These are modeled host backend tests,
NOT firmware/Metal execution on the phone. A premature image check before the
health build finished found no manifest; rerun after successful completion PASS.

SEND-only test slot requested from existing phone coordinator after its current
capture; message delivery recorded, **scheduling not confirmed and no new
physical attempt by this goal parent**. Health image is conditional only: fresh
SEND len8/cmd1/result0+rung2PASS first; any refusal stops progression. No new
USB/device operation, guest, firmware send, root/partition/slot write or flash.
Exact commands/hashes/source proofs and acceptance:
`research/ios26-metal-native-20261102/integration/HANDOFF.md` + firmware-tests.json.

Ten implementation delegates remain assigned; no terminal event consumed or
task polling. Firmware/queue steered toward real shared allocator/KCCB/persistent
startup composition. Still missing: integrated GPU VM/contexts/completion,
complete own DXT compute shader and native Metal dispatch/readback. Starting
goal commits `b887615`, `9c8affe`; original scope and ten-agent target unchanged.
Next: consume implementation milestones, integrate/test actual adapters and
obtain the scheduled firmware capture. Native Metal remains unproved.

## Dual-boot goal started, 2026-11-02 10:20 CET

User explicitly asks to finish proper iOS 26 + Android dual boot, using
`oosexgang/hakios-uefi`, and to proceed with our recommendation. Active goal in
this thread. `docs/DUALBOOT.md` defines acceptance and implementation order.
Reviewed the completed prior dualboot feature: only a chooser policy, no menu,
Android dispatcher or isolated persistent storage. Upstream pinned UEFI
`687fa6c6a5a70f43184de92980e0a76eea5f2c4b` targets Mu-Silicium/Qualcomm;
Pixel ABL's Android-v4 envelope does not supply EFI Boot Services.

**Observed:** saved stock fstab lists userdata_exp.ai as Android F2FS exp_alias;
its alias-file/reservation state remains UNKNOWN. Current root r3 occupies it;
earlier approved writes spent their authorization, no original alias backup.
Do not boot Android or call this isolated storage. Existing fullcheck validates
the iOS bytes, not Android integrity. p29 supplies native exact whole-LUN reads
and physically verified USB console; implement read-only GPT/backup transport
against those APIs next, with bounded receipts and host verification.

**No new device attempt, USB command, Android boot, slot/force-fastboot change,
root/partition write or flash in this milestone.** The other parent owns phone
attempts and release integration; leave its active p29/profile work alone.
Next: implement/test readback in own tracked sources + ignored r2 integration
fixture; gate-on ARM64 objects and symbol checks, then request a concrete
read-only capture through the phone owner. Storage migration approval comes only
after a verified layout/backup/rollback exists. Android integrity, persistent
chooser and full dual boot remain unfinished.

## Physical milestone, 2026-11-02 10:04 CET — combined p29 + live iOS console

**Actually tested on Pixel:** `20261102-095609-phone-p29-live-r1`, image `c203c70e6faccaeb57a62fc3225696eb8d66fc5bf22bc8b85e318e66b8072eba`; kernel p29 `5aad89780e798d730aa00372dd17568917cc81d97fc231df0fcf1a9fda80fca8`, unstripped `cc97915354f63c1253bd84295dd5ba004b864bb336a82dd2bcffbf3eb57631cc`. Parent combined33 source commits since p28 (37 since p27), resolved prerequisites + four additive governor conflicts,172-file series/combined proof PASS, full ARM64 link0undefined,266 existing checklist checks PASS, physical touch bus trace unchanged. Combined patch `research/ios26-release-r1/combined/ios26-p29-all-in-one.patch` SHA `257d218bf950edcd3737eb84dda320a0d451045fa318f080ad6370f0df1f6a47`. Integration journals `resume-20261102/p29-{integration,dependencies}.json`; selected kernel paths added105 globals, including real IOSurface GPU imports and native BT bridge. Source-only planners and missing adapters are NOT functional hardware. Later feature returns still await integration.

**Live console PASS (physical):** `blazer_usbcon=1 blazer_usbcon_ch9=1`; Mac registered1209:0002. Standard tracked `tools/usbcon.py` byte-identical to tested reader. Raw stream `research/ios26-fleet/resume-20261102/p29-live.raw` + .times/.json. 1,533,021 live bytes,5,645 reads,0timeouts,0lost,0stalls,0controller restarts; one expected USB error/disconnect at reset. `tools/usbcon.py --verify ... --dump <attempt>/ramdump/kernel.log`: ok true, compared1,533,021, mismatched0.479 final panic-tail bytes were not read live, retained in RAM capture. Reader ended cleanly. Console thread last sampled0.375%CPU; measured protocol overhead only, not system power. Existing22 tool tests PASS.

**Script/home-transition PASS for this run:** `hk_ui_trace=1`, script startsHID+120. Completed14 token executions/169events; maximum callback lateness1,128us, maximum dispatch call1,334us, accumulated drift241,745us. HGLTRACK installed and tracked2new surfaces. No push_surface assert or second backboardd abort after home returns; same pid102 survived. Separate early backboardd22 NSURL-nil startup abort still exists and respawned; does NOT count as stable startup. Input dispatch measurements are scripted events, not physical touchscreen-to-glass latency.

**User observation:** home works, Settings opens, missing logos/other rendering, slow touch/heavy lag. Preserve these as FAILURES, not completed UI/GPU. In live HKTOP t1702,32frames costbackboardd7060ms; later46frames cost10872ms. Spotlight consumed28700ms then30823ms per30s near end. These mixed scripted/manual windows aren't controlled FPS benchmarks. Need sampled stacks to fix renderer/Spotlight hot paths. No Metal acceleration or performance gain claimed.

**End:** expected deadline300s panic, PSCI software reset; XNU305.3s/payload331.9s. Tj max37C, post-resetABL38C, SOC89%,VCELL4332mV,0CPMerrors/thermalbreadcrumb. Phone parked/captured; both host sessions24864and72019 complete. Capturekernel.log SHA `918fecdd47feee6b89285c442134ff89e06815999186015345f0bfb6f414ad86`. No partition/root write. Existing force-fastboot stayson.

**Next action already running:** build `phone-p29-profile-r1`, unified exec25930. Same p29+liveUSB/hgltrack, remove repetitive memory selftest, addhk_hog3 and scriptHID+90 for home-swipes/Settings. Command JSON underresume-20261102. Build image only so far; must verify result/hash then start dedicated reader and temporaryboot. Parent still alone usesUSB. All54 dedicated feature tasks launched as explicitGPT6.1Sol; AoC task remains review-blocked with no reroute. Others return host milestones, never physical completion. Main goal remains active. Native GPU firmware/kernel VM/shader execution and most peripherals remain incomplete.

## Native Metal goal started, 2026-11-02 10:09 CET

User explicitly requests native Metal on Pixel 10 Pro / iOS 26 with ten agents
continuously working. **Ten new background implementation delegates launched;
all ten launch responses reported `running`, inherited Codex gpt-6.1-sol.**
Scopes: firmware, HMGU user client, GPU VM, submission/completion, DXT ISA, AIR
frontend, PDS/CDM streams, Metal command path, IOSurface integration and native
execution smoke test. Exact task IDs, thread links and prompts:
`research/ios26-metal-native-20261102/{fleet.json,FLEET.md,launch-spec.json,PLAN.md}`.
Each writes only its own subdirectory, HANDOFF.md and messages.md; older fleet
and release sources are read-only. No nested agents. At each completion, review
and start a fresh bounded task to maintain ten; no delegate polling/waits.

Starting physical evidence remains the earlier captured boots: iOS UI/touch and
GPU core ID, **no proven native GPU shader/Metal execution**. First GPU target is
an own compute shader, fresh real engine completion, cache-synchronized matching
readback and sentinel guards. Host/model tests never count as physical success.
Firmware health alone is insufficient. Current release may be newer than the
09:35 handoff; reconcile source/captures before integration.

Committed acceptance/ownership document: `b887615`, `docs/NATIVE-METAL.md`.
Validation: documentation diff check and tracked-artifact pre-commit scan PASS
(clean 148 files); no new runtime/build/boot test claimed. **No new device
attempt, USB command, guest, firmware send, root write or destructive operation
in this startup milestone.** Another project parent thread is active: coordinate
phone ownership before any boot and never interrupt its attempts. Preserve Android,
bootloaders, slots, firmware and backups; confirm each destructive step.

Next: consume delegate completion events, reconcile cross-layer APIs, rerun
meaningful tests/ARM64 gate-on symbol checks, review provenance, integrate and
commit completed implementation. The long-running native Metal goal stays active.

## Fleet review block, 2026-11-02 09:35 CET

AoC feature task rejected for possible cybersecurity risk, stopped without rephrasing/rerouting. Other hardware work continues. Freed slot assigned dedicated A725 owner (explicit gpt-6.1-sol); roster now31 launched including1 rejected,23 pending capacity. Details in features-20261102/fleet.json and BOARD.

## Phone result, 2026-11-02 09:34 CET (parent)

Attempt `20261102-092638-bench-p27-track-r1` is complete/captured; unified exec13328 exited0. **Owner long press**, DER7/RST_STAT4, at XNU238.1s, payload264.7s. No kernel panic observed. No scripted token execution before termination (`HK UI: 18 tokens, start in300s` only). Therefore Settings/home transition benchmark remains untested; no speed claim.

Physical evidence: `hk_env: backboardd gets DYLD_INSERT_LIBRARIES=...`, `HGLTRACK: SWContext slot wrapped, slide0x5440000, reprotect0` (after backboardd respawn too), and `SWEET FB: display on`. **New finding:** backboardd[22] startup NSInvalidArgumentException, NSURL initFileURLWithPath nil string; later backboardd[104] survives to lastHKTOP. This resembles gpugl-p1's documented startup path but cause not isolated. No observed push_surface assert in this capture, but transition wasn't exercised, so not a fix proof. Tj max38C, post-resetABL39C, SOC89%, VCELL4329mV, noCPMerrors/thermalbreadcrumb. The4MiB dump contains duplicated logs. Next: diagnose nil path and await UI owner's controlled shorter script proposal before repeat; do not conflate longpress with autonomous failure. Other thermal/slot/root constraints unchanged.

Fleet dedicated feature roster: first30 launched as explicit gpt-6.1-sol,24 pending capacity. Newly requested dualboot owner is running and must preserve existing storage while investigating hakios/UEFI. Completion events free next slots; no task polling.

## Parent milestone, 2026-11-02 09:32 CET

**Physical recovered:** `20261102-091607-sensor-stream-r2` completed by deadline 300 s (not a spontaneous crash). Read-only named capture recovered after its host runner was interrupted. Accel + gyro samples through 2400, changing orientation/HID activity; application rotation still unproved. Tj max38C, post-reset ABL39C, SOC89%, VCELL4332mV. Raw kernel log SHA256 `af1cb2cb105a5d3bb7b376db5eff80779de033c847fd1153c6a5e58d1a9e103d`. Decoder output `decoded.txt` inside attempt. README sensor wording corrected, score unchanged.

**p27 built and booting:** release tree `8cc70ae0`, only 0662 scroll/repeat since p26. Host C ASan/UBSan legacy+repeat suites and Python simulator pass. Gated ARM64 SweetHID object contains start/uiFired. Combined/series source proof, unchanged physical touch trace, all261 checklist lines and zero undefined pass. Kernel `b2b28c37017a2f7bc259b5392720d88c22a4959346896c79106a215bea59655c`; unstripped `c6d0a4fb88df4f56c221c40e959c757bb06fbd47810570cd4b548ea1006d0337`. Image bench-p27-track-r1 `e9d2725f5385c40fd510826e5617f50a39e06ad8633dba00ab1eea16b850606a`, hgltrack overlay unchanged61c38161…, cap16 tested1075MHz, scripted Settings scrolls/repeats. Attempt `20261102-092638-bench-p27-track-r1`, unified exec session **13328**, runner wait1200, deadline900. Fastboot boot returned OK; EP0 live. **No benchmark result yet; do not boot again until this attempt is captured.** Existing force-fastboot left on; no root/partition write.

**Benchmark reader repaired locally:** complete explicit image manifest takes precedence over launchd's truncated/interleaved boot-args. Invalid logged script fails rather than falsely becoming a dry run. Six source-selection tests pass, resource warnings treated as errors. On g1, reader now recovers22/22tokens. Earlier untimed SpringBoard exec can be omitted by interpolation; output now labels first *timed* exec. Files in ios26-bench-r1; parent owns reader until handed off.

**Fleet:** first11 recovery agents returned host-only milestones, see their handoffs and BOARD. Parent reran battery0697 ASan/UBSan6973 checks; patch cleanly applies. Returned patches await review/integration, not physical proof. New user asks a dedicated6.1Sol owner per feature including dualboot: **54 scoped assignments, first30 launched**, remaining24 pending capacity. Exact prompts/roster/task IDs/links: `research/ios26-fleet/features-20261102/fleet.json`. All explicit Codex gpt-6.1-sol. Parent alone now updates NOTES to avoid concurrent prepend races. Queue remaining owners on completion events, not polling delegates. GPU production route stays non-Mesa; do not restart failed Claude Mesa task. Dualboot owner must verify hakios upstream and storage isolation; current userdata_exp.ai is an Android/data F2FS alias, not spare. No Android boot, slot/GPT/root changes authorized by that investigation.

## WLBT implementation recovery, 2026-11-02 09:25 CET (host only)

Bounded native H4 transport patch ready for parent review/link: `research/ios26-wlbt-r1/patches/1135-blazer-bt-native-h4.patch`, SHA256 `9081dd763002b7fb576751175c79927b9fdbdae9e8ab410813d4cb8c0167742a`, on p26 + BT 1133/1134. Recovered partial sources preserved. Fixed unreachable mode 5 and bounded UART service; denied/unknown HCI commands now return errors, never fake success. ASan/UBSan gate + UART-model tests pass; BLAZER-enabled ARM64 objects/symbols pass; clean-base apply check passes. No full link, guest, device boot or commit by child. Wi-Fi mailbox/Apple80211 fragments remain unfinished/excluded. bt-3 has only ADT generation files, no runtime log to read. Exact parent-only next commands, pass/fail and limitations: `research/ios26-fleet/handoffs/wlbt.md`. Country/network/transmit decisions still owner-gated.

## Performance recovery handoff, 2026-11-02 (implementation agent, host only)

Recovered interrupted depth/cpumem trees without discarding partial work. Ready for parent review/link: `research/ios26-depth-r1/patches/0990-blazer-ufs-adapt.patch` (`f2d2e65c…`, removes unsafe shorter poll), `0991-blazer-gov-idle.patch` (`1c80d589…`, default-off long idle tick/touch wake registration fix). BLAZER-enabled ARM64 objects + symbols inspected; UFS ASan/UBSan 131 checks, 14/14 mutants; idle 17 checks; governor 225 regressions. Exact hashes/results/parent-only pending boot request: `research/ios26-fleet/handoffs/depth.md`. No full kernel link, boot attempt, QEMU or device command. Parent owns commits; no commit made here.

High-clock WIP preserved/exported but DO NOT LINK; cap13 five-core queued bench held by recommendation pending reconciliation with limits P7 and physical step-down evidence. No high-clock/A520/RAM recommendation or allowlist expansion. Audit/prerequisites: `research/ios26-fleet/handoffs/cpumem.md`. Next: parent review/link depth patches, build `depth-idle-r1` on cap16 baseline, then separate UFS mode1 test. Phone behavior remains unproven.

## Active fleet handoff, 2026-11-02 09:22 CET (Codex)

User renewed the goal: native iOS 26 on Pixel 10 Pro, optimized non-Mesa GPU and broad hardware completion. **11 Codex agents launched**, replacing usage-limited Claude work; roster with task IDs and links: `research/ios26-fleet/resume-20261102/fleet.json` (local, ignored). Owners: gpudrv, gpucc, metaldrv, gpumem, dpu, performance, wlbt, audio_sensors, power_input, peripherals, overlay_perf. All read and append BOARD.md; parent alone handles USB, phone boots, release integration and commits. Earlier native resume agents were interrupted; new owners recover their partial files.

**Verified in this recovery:** old fleet failed on Claude usage; existing source/artifacts preserved. Last completed physical UI benchmark remains `20261102-084446-bench-g1-r1` (Settings launched; home transition abort). The queued `/tmp/fleet/bench3.sh` requests p26 + hgltrack + cap13 (1536 MHz), but **no completion result verified**. `20261102-091607-sensor-stream-r2` has no captured result verified yet. At 09:20 process inventory found no matching bootios/run-attempt/fleet shell; reconcile device and attempt state before another boot. Do not assume interrupted host jobs imply phone reset.

**Immediate integration priorities:** verify compositor hgltrack and IOSurface 1200 fixes; finish/test UFS adaptive waiting and governor idle tick; measure a controlled speed benchmark. Depth recovery identified that allowing `blazer_ufs_step_us < N882_POLL_US` invalidates the poll bound: excluded pending correction. Higher clock limits must follow measured guard prerequisites; existing notes disagree in age, so read gov.md and exact captures before use. GPU firmware execution, DXT compiler and real Metal acceleration remain unproved.

No new physical test, root write or flash performed by this recovery. Destructive steps still require explicit approval. Research, firmware, Apple artifacts and dumps stay out of git. Older handoffs below contain stale running-agent and boot-state claims; dated physical captures take precedence.

## Handoff, 2026-11-02 09:15 (parent): read `research/ios26-fleet/STATUS.md` first

Tracked tree: status refreshed after `0e91414`; this note's commit is the newest on `origin/ios26`. `research/` stays git-ignored.

**Physical since 07:58** (captures under `research/laguna-usb-fix/attempts/`, kernel p26):
- `gov-g1-r1`, image `91fbe420…`: PASS, deadline end at 900 s. 125 `blazer-clock` reads, 0 off by more than 2%; cores step 533<->1075 MHz; Tj 33-35 C; about 240 mW idle (estimate). `handoffs/gov.md`.
- `20261102-084446-bench-g1-r1` (p26 + gov + fallback `hk_ui`): all 22 script tokens ran; scripted tap 147,274 -> `exec Preferences` pid 177, Settings launched from a script for the first time. Home key -> backboardd new surface 1125x2511 -> `push_surface` assertion (`ogl-context.cpp:1186`) -> SIGABRT; SpringBoard, Preferences, Spotlight respawned. Owner's long press ended it at 480 s, Tj max 35 C. `handoffs/bench.md`.

**QEMU or host only, not phone evidence:** `colour-1` (QEMU, p26, `qemu-test5.ovl`): cover works, Settings draws its titles, text and coloured icons; a sampler dylib injected into SpringBoard ran. `hgltrack.dylib` overlay `p5-merged-r2-gltrack.ovl` `61c38161…` (bench-g2-r1) is built, host-checked, not run: unknown whether our kernel allows `vm_protect` copy on shared-cache data. `hk_panel_hz=120|60|30|10` is compiled (release 1074), never run. `handoffs/gpugl.md`, `overlay.md`, `release.md`.

**Agents running (host or QEMU, none commits; parent alone boots):** GPU kernel driver, shader compiler, Metal user driver, GPU memory/IOSurface, Mesa hardware route, display DPU, Wi-Fi/BT iOS integration, depth tuning, gpugl (p3 in QEMU, detached pid 78844), bench.

**Next:** bench-g2-r1 on the phone with `hgltrack` (look for `HGLTRACK: SWContext slot wrapped`, then the home key without a backboardd abort); gov on the daily line; Settings' colours on the phone; GPU ID read; Wi-Fi regulatory then join (owner's transmit decision). Open owner decisions unchanged from `STATUS.md`.
`README.md` status comes from `docs/status.json`: edit it, run `python3 -I tools/readme_status.py`.

# iOS 26 on blazer (Pixel 10 Pro, Tensor G5) - working notes

## Pixel 10 Pro port handoff (2026-11-01, current)

**Active state, 2026-11-02 01:15:** iOS 26 root r3 is on the phone (one approved write, spent); home screen and touch work physically (`HANDOFF.md` top). Owner holds phone boots until they say. Order and owners: `research/ios26-fleet/PLAN.md`, state `research/ios26-fleet/STATUS.md`, next boot table: `research/ios26-fleet/handoffs/release.md`, section "Next try". Newest kernel: `research/ios26-release-r1/artifacts/`. Don't boot Android: it may destroy the root (`handoffs/android-partition.md`). A root change needs new owner approval.


Workspace `/Users/andersmadsen/Developer/personal/hackios`. Evidence history: `BLAZER.md`.
Latest detail: `HANDOFF.md`.

- Goal: **Boot native iOS 26 with visible interactive UI, working touch, stability and
  repeatable boots.** The owner dropped iOS 16 on 2026-11-01; that line is frozen on branch `ios16`, tag
  `ios16-final`. Work here on branch `ios26`. Dated notes below are iOS 16 history, but their hardware facts hold.
- Reached on the phone, all with iOS 16 and `xnu-8796.121.2`: UFS at HS gear 4, 16 KiB pages, 4 GiB, launchd and SpringBoard from the full root,
  RAM scanout to the panel from the shim. Not reached: anything on iOS 26 or XNU 12377, iOS's frames on the panel, touch, automatic recovery.
- Use temporary `fastboot boot`. Confirm each destructive step with the user.

Current blocker: can iOS 26 draw without a GPU driver? Tegu reports a buggy iOS 26 UI on its Pixel 9a, but through its Mali Metal driver; our GPU is Imagination. Open: no recorded UI without Metal.
Next concrete action: read `research/ios26-root-r1/FINDINGS.md` (go/no-go) and `research/ios26-kernel-r1/FINDINGS.md` (tegu series plus blazer hardware layer).
Detail in `HANDOFF.md`.

### Carried from iOS 16 to this branch

- `shim/`: HS gear 4, PHY check, PWM fallback, stage marks (gates off by default) and the DPU code `tgl_dcs.c` from r1d, built with `TGL_ALL_STAGES`, `TGL_ALL_DCS`, `TGL_FRAME_RUNG=3`.
- `tgl_dcs.h` keeps r1d's record address `0x9542a000`, which is also the UFS record's. Before enabling the DPU stage with UFS on, move it to `0x955e0000`, as `research/ui-integrate-r1/snapshot/` does.
- `frame_tables.h` holds offsets and PPS generated from GPL-2.0 vendor source; decide its license before publishing.
- `xnu/ios16-base/patches/`: 8796 drivers, the parts source for a 12377 port. They don't apply to 12377 as they stand.
- Kernel base: `research/upstream/ios-tegu-gh-20261101`, branch `ios26-bringup`, `d807098` (Pixel 9a, Tensor G4), at the owner's instruction. No license: local use only, nothing published without the author's permission. Its hardware values don't apply here.

### 2026-11-01: ufs-observe-r2

Physical read-only boot succeeded, 35 reads. Link preconditions hold. Detail in `HANDOFF.md`.

### 2026-11-01: helpers running

Parent started link, post-link, SMMU, handoff, APFS, dyld, launchd, display and tools agents,
host-only, in `research/<topic>-r1`. Not yet reviewed. Parent boots ufs-link-r1 after review.

### 2026-11-01: tools agent reviewed

Parent reran tool tests. `capture-fastboot.py --named-only` no longer needs a lease; `tools/bootios`
waits for park and captures. Neither has run on the phone since the change.

### 2026-11-01: SMMU, dyld, launchd and display agents reviewed

Parent spot-checked; none of this ran on the phone except the capture it reads.
- Parent confirmed in the r2b capture at offset `0x1000ca`: `initproc failed to start -- exit reason
  namespace 2 subcode 0xb`. Parent decoded GBPA `0x2e1f`: bypass, Outer Shareable, cacheable. Inference: keep
  cache maintenance; refuse DMA unless GBPA still matches. Plan: `research/ufs-dma-r1/FINDINGS.md`.
- Launchd agent: the panic is a compact-root defect (stale ADRP, 8,572 sites by static scan; cause inferred).
  Do not patch sites one at a time. Reader's "no panic string" and `run-attempt.sh`'s default `--mach` are
  wrong for current boots. `research/launchd-panic-r1/FINDINGS.md`.
- Dyld agent: cache needs 16 KiB signatures accepted and a window above 1 GiB; 4 KiB-hardware behaviour
  untested. `research/dyld-cache-r1/FINDINGS.md`.
- Display agent: cheapest visible test is display-dcs-r1, one DSI0 boot, user films. Specified, not built.
  Its ABL reading is from slot a. `research/ui-touch-r1/FINDINGS.md`.
- An earlier firmware-lifetime task was stopped by a platform safety flag (N520 `STOP-RECORD.md`). Do not
  reroute it. SMMU and display agents read small ABL sections; no further ABL disassembly is requested.
- Started: qemu agent, `research/fullroot-qemu-r1`, to test the full root in a guest.

### 2026-11-01: handoff agent reviewed

Host only, unapplied: XNU takes over UFS from the shim, gated off by `TGL_UFS_HANDOFF`, `rd=md0` then switch root.
Not linked, not booted; needs a working link and READ first. `research/ufs-root-handoff-r1/DESIGN.md`.

### 2026-11-01: QEMU agent reviewed

QEMU only, parent checked the log: full 20F66 root, `rd=md0`, 16 KiB pages: cache maps and launchd says `hello`, no
panic in 290 guest seconds. Supports that the phone's panic is a compact-root defect; not isolated. Phone still
needs a physical window above 1 GiB and 16 KiB signatures. `research/fullroot-qemu-r1/FINDINGS.md`.

### 2026-11-01: APFS agent reviewed

Host only; parent checked receipts. Reader reads staged root `637103e1…`: 45,044 files, 5.64 GB, 0 errors. Not run under real
XNU VFS or UFS. Unapplied: `requests` race fix, short-read check before UFS. `research/apfs-reader-r1/FINDINGS.md`.

### 2026-11-01: input agent reviewed

Host only, unapplied: keys are AP pads on `cpm_pinctrl`, not AoC; battery gauge max77779 on SPMI. No service stubs known to be required for a first UI
boot, resting on a QEMU run. `research/buttons-power-r1/{FINDINGS,STUBS}.md`. Probe keyprobe-r1 not run; it needs someone pressing keys.

### 2026-11-01: page16k-r1

Physical: XNU ran at shift 14 with 4 GiB at `0xa00000000`, same compact-root panic. Detail in `HANDOFF.md`.

### 2026-11-01: userland agent's lead, phone-r1 booting

QEMU, not the phone: with md1 `de340c95` (407 jobs) the same root spawned SpringBoard and backboardd, and drew the boot logo. The Restore branch is not the wall.
SpringBoard aborts on a bounding path bitmap; suspect missing `/product`. Stability agent's tool fixes applied: `tools/bootios --mach --wait`, `tools/boot-summary.py`.

### 2026-11-01: ufs-speed-r1

Physical: HS gear 4, 30 MiB/s, up from 0.53. Detail in `HANDOFF.md`.

### 2026-11-01: display-frame-r1c

Physical: native test pattern on the panel. The owner saw it flash. Detail in `HANDOFF.md`.

### How work runs

- One parent agent does the work, owns USB and runs the boots. It records results here and in
  `HANDOFF.md` as dated bullets, newest first.
- Use helpers for independent work, as many as the work supports, named by purpose ("touch agent",
  "shader agent"). The parent checks each result itself and reruns its tests before relying on
  it, and writes what it found ("Parent reviewed ...: ...; requested ...").
- Experiments live in `research/<topic>-rN`, with N going up per retry. Say whether each is
  built, deployed or verified.
- `research/laguna-usb-fix/native-fleet-20261031/` holds older N-numbered work. Read it as
  history; do not add to it or use N-numbers.

### Hardware facts

- `google,lga-blazer`, "BLAZER MP based on LGA". Blazer device tree:
  `research/laguna-foundation/kernel-blazer/devices/blazer/fdt/laguna.dtb`.
- Log RAM: 4 MiB dump at `0x95200000`. ramoops `0x95200000..0x953FFFFF`, pmsg
  `0x95400000`, shim stamps at pmsg+0x30000. Decode with `--dump-base 0x95200000`.
- USB: DWC3 `0x0c400000`, wrapper `0x0c450000`.
- UFS: HC `0x3c400000`, pinctrl `0x3C590000` (pad 0 reset, pad 8 `AP2PMIC_UFS_EN`).
  Samsung KLUDG4UHGC, UFS 3.1, 4 LUNs, HS gear 4 under ABL.
- Source order for UFS: shipped `ufs.ko` (6.12.81), `kernel_pixel_6.12@5940a317`,
  kodiak, then `e214813c` (6.6). The `*_OFFSET` constants in the latter's
  `ufs-regs-gen.h` are wrong.
- Sizes: `system.apfs` 2,476,732,416 B; 20F66 shared cache 2,722,512,896 B. They do
  not fit the 64 MiB RAM-boot path.

### Local artifact locations

- Attempt ledger: `research/laguna-usb-fix/ATTEMPTS.md`. Captures:
  `research/laguna-usb-fix/attempts/`, `research/laguna-usb-fix/automation/state/device-attempts/`.
- Older agent work: `research/laguna-usb-fix/native-fleet-20261031/N*/`.
- Kernel tree and build: `research/laguna-foundation/kernel-blazer/`; iOS 16 port patches: `xnu/ios16-base/patches/`.
- Boot runner: `research/laguna-usb-fix/run-attempt.sh`, called by `tools/bootios`.
- Root images: `research/workspace/iosroot/`, `research/laguna-image/`,
  `research/laguna-usb-fix/root-upgrade/`.
- Vendor sources: `research/upstream-20261101-pixel10pro/`. Other sources: `research/upstream/`,
  `research/workspace/sources/`. Hardware dumps: `research/workspace/hardware/`.
- Old builds: `research/workspace/builds/`. Finished work: `research/archive/`.
- Earlier documents: `research/notes/`, `research/laguna-usb-fix/docs/`, `research/SESSION-STATE.md`.
  They are dated records and may link old paths.
- Every move: `research/legacy-root-20261101/PATH-MAP.json` and `path-maps/*.json`.

## 2026-11-01: documentation restructured

Root documents rewritten to the layout and working style of the Pixel 9a `ios-tegu`
repository, and the root and `research/` reorganised to match. No tegu code or hardware
facts were copied. Moved only, except 24 empty session folders removed. Stopped `loopapi`,
disabled the campaign state and deleted the old scheduled tasks. Boot through `tools/bootios`; it sets persistent
`fastboot oem force-fastboot on` and does not turn it off, so tell the user first.

Known leftovers, none used by the build chain: old October scripts and dated docs still
name old paths; some old git worktrees have stale `.git` pointers (fix with
`git worktree repair` before `git gc`); `tools/check_v3_integration.py` fails because its
fixture no longer matches `shim.c`.
Tool tests pass.

### 2026-11-02 09:24 power_input (host-only recovery milestone)

Recovered interrupted power2/battery/input/sleep/panel folders in place; no panel edits. New default-off battery hold patch `research/ios26-power2-r1/patches/0697-blazer-battery-hold.patch` SHA256 `52b8b3e2e8c1f76a5a7b88f5677932a02c6342970f4fe79c288040fba1f4e175`: keep last valid SOC on read failure, mark stale/invalid and clear current/charging/critical claims. Actual pollGauge host harness 6973 assertions PASS under ASan/UBSan; five enabled ARM64 objects compile, pollGauge symbol and new strings checked. Applies to release `8cc70ae0`. No link, boot, device operation or commit (parent owns). Next: parent integration + batt-hold-r1 stable daily line adding blazer_battery_hold=1; physical behavior untested. Full recovery/receipts/boot pass-fail: `research/ios26-fleet/handoffs/power_input.md`. Charger programming remains unapproved and unperformed.

## 2026-11-02 audio_sensors recovery milestone (implementation sub-agent, host only)

Parent handoff: `research/ios26-fleet/handoffs/audio_sensors.md`. Preserved old
partial audio/AoC/haptic/sensor work. Finished default-off `blazer_audio_rt=1`
adapter restricted to audiomxd's own exact 1200-tick RT bootstrap request;
0903 patch sha256 `eb5d2e210dc89099e170482c4d389e7d6264376a34fd29e3d930e2bf812f3d1f`.
66 ASan/UBSan checks pass; real ARM64 BLAZER=1 object with expected symbols
`7a9459c9889c38a2294fa29ecb2bfcda5045a3e3abe2713d1db30ef4292e5615`.
Applies release `8cc70ae`; no full link, boot or commit (parent owns these).
Recovered QEMU audio-2 shows VA initialized and Speaker routed, but RT policy
rejections and no samples. Parent physical sensor-stream-r2 capture now shows
accel/gyro streams and HID opens, not app rotation. Next: parent links 0903
instead of partial 0902, allocates audio-rt-r1 guest slot; exact command/pass/fail
in handoff. Audio sample delivery, AoC start, light/prox/barometer unfinished.

### 2026-11-02: dpu/panel recovery, host-only milestone

Recovered 0840..0842 intact in `research/ios26-dpu-r1`; added default-off 0843 generation-bound damage guard (newer queued swaps retain damage). Cumulative patch `patches/0840-0843-dpu-ready.patch` SHA256 `042b74cf540339aa1eaa71876dc9f7caee1f72c0254933f3f7c72f8cec14606d`. Seven ASan/UBSan host suites: 12,997,270 checks, zero failures; three BLAZER=1 ARM64 objects emitted and expected symbols inspected. Not full-linked, booted or physically proven. No device commands or commits; parent owns both. Isolated boot request dpu-zc-r1: current UI recipe plus hk_dpu=1 hk_fb_stats=1, 60 Hz; bootchain must allow hk_dpu. Exact requested command/pass/fail and object hashes in `research/ios26-fleet/handoffs/dpu.md`. Panel tree had no partial diff; preserved. CPU renderer remains dominant in captured slow frames; DPU copy removal does not prove GPU acceleration.

### 2026-11-02: overlay_perf recovery milestone (host only)

Recovered overlay2 audit lists and persist work intact. New reversible overlay `research/ios26-overlay2-r1/artifacts/p5-gltrack-cloudd-r1.ovl`, SHA256 `02437877f216eec98514d596176d7e7247a7df2e22111efc2a0a2bbf3b5fc333`: restore only cloudd from disabled.plist, retain hgltrack + 42 other records byte-identical, mask `0xA0080081`. Four host tests and release parser ASan/UBSan PASS. No QEMU, USB, phone write, kernel link or commit (parent owns integration/commits). Existing colour-1 log shows 39 failed cloudd lookups; benefit remains a hypothesis. Requested parent sequential QEMU A/B and exact commands/pass/fail: `research/ios26-fleet/handoffs/overlay_perf.md`. Icon caches remain excluded by persistence; MobileGestalt already refused. FairPlay/AX fixes and persistent icons unfinished; no new physical claims.

### 2026-11-02: gpudrv recovery, host-only milestone

Implementation sub-agent, no commit/link/boot (parent owns them). `research/ios26-fleet/handoffs/gpudrv.md` supersedes the old PING interpretation for TA **16325047**: static recovered code returns 180 until SEND sets firmware-loaded state; same explanation on physical older 16121595 remains inferred. Original gpufw/TA partial files preserved. New `research/ios26-gpudrv-r1/patches/0924-gpu-health-execution.patch` SHA256 `f291d743039588fd8bf4ca2b9b9aa74c5a44b63b312c3a3ea4123148eaf21a44`, after 0923+0916b+0922, default-off rung 5: clear stale return slot, require CMD_EXECUTED, refuse live ring/unexpected status. Host **81 checks, 0 fail; 51/51 mutations rejected**, ASan/UBSan. Actual XNU ARM64 BLAZER=1 object `afaf5da1983ab17c91bd55c6a29e11fddf803f497e30419d1f07146f6dfa78de`, expected entry+health symbols inspected. Patch apply exact. No new physical attempt ID. Parent next: resolve existing GPU firmware decision, link prerequisites + 0924, SEND rung 2 then health rung 5 per handoff. Accepted metaldrv HMGU ABI v1 on BOARD; IOKit client/BO/VM/render jobs still unfinished, no hardware acceleration claim.

### 2026-11-02 09:25: peripherals host recovery milestone

Parent handoff: `research/ios26-fleet/handoffs/peripherals.md`. Preserved cellular/usbcon/media originals. Incremental 1135 patch under `research/ios26-media-r1/peripherals-r2/patches/`, SHA256 `f0ab72e6aa8719b44a93e66d5814b96fa4642b10b3eb5a52834ac9b70e9fcbe9`: non-I2C torch pad inventory without controller access; cleanup faults no longer discarded as success. Enabled BLAZER ARM64 objects + expected symbols, ASan/UBSan suite including 510 refusal cases, three regressions caught, apply check on release 8cc70ae0 PASS. Not linked/booted/committed (parent owns those). Actual captures audited: modem-1 reads nine pads only; torch-1 stops on CLI2 (UART per FDT), no chip; USB r2 partially enumerates but never configured and host reads zero bytes. Exact next parent-only torch-1-r2 command/pass/fail in handoff. No USB/device commands, guests, radio operations or root writes performed. Remaining: physical pad inventory, bus ownership decision; USB descriptor audit; modem/GNSS/NFC/UWB/camera/video service implementation.

### 2026-11-02 gpucc recovery, host-only milestone

Recovered partial `research/ios26-gpucc-r1` in place; own DXT framing/class decoder and strict HMUSC1 container validator delivered. Handoff `research/ios26-fleet/handoffs/gpucc.md`. Host: 22,807 saved stock-answer records match accepted framing/class, 66 unknown selectors refused; ASan/UBSan validator tests pass (39 refusal cases, all truncations, unaligned, 20,000 mutations). ARM64 object emits `_gpucc_hmusc_validate`; header SHA256 `d1fd05ad659c5b3194ff474450ea38510f5f4668d97ff60b22315c8265861b83`. No runnable DXT shader/emitter yet, no phone performance claim. No USB, QEMU launch, physical boot, link, commit or deployment. Parent owns commits. Next: readable operand layouts with codec agreement; no boot requested. Other owners' source untouched.

### 2026-11-02: metaldrv recovery, host-only implementation milestone

Implementation agent preserved ios26-metaldrv-r1/gpushell partial work and added native HMUSC1 stage validation + HMGU BO upload/rollback + explicit-opt-in IOKit adapter in its own topic. gpudrv accepted HMGU v1 on BOARD, but kernel user client/BO allocation remains absent. Host ASan/UBSan: 137 stage-boundary cases PASS; recovered CPU runtime sampler min/max LOD bug reproduced then fixed, 1052 reference assertions PASS. ARM64 iOS objects emitted, expected symbols inspected, IOKit adapter bundle linked. These are host/reference checks, not GPU execution, compositor correctness or phone speed evidence. No guest/phone attempt, USB command, release-tree edit or commit (parent owns commits). Package research/ios26-metaldrv-r1/receipts/metaldrv-recovery-src.tar.gz sha256 237a7fb527092704aa57cc13c4c35910e7d49643510202ad2a8937805765686d; runtime patch 41925b6ffcca980822a0afddd8a9651ed0c00ad687d23a12c524983c8a37c9b9. Next: parent-only gpushell census slot request and remaining kernel/compiler/stream blockers in research/ios26-fleet/handoffs/metaldrv.md. No new physical boot recommended by this milestone.

### 2026-11-02 09:28 gpumem implementation recovery (host only)

Recovered 1200 commit `6fe8468`/patch `691b4cada5266c52bbc39baeeec3b7418cb9402627c3a09cd7f9a8ac3895cbe5`; interrupted 1201 saved intact in `research/ios26-gpumem-r1/notes/recovery-20261102`. New bounded 1201 patch `198106d89a1e893a0ef8f447e0da1a079d283d3dbbc4f335fcbf895e635f9a10`: owned aligned surface import, retained object/id table/wiring/use count, explicit cache sync with errors, real external GPU fence required; caller/physical/flip memory refused. Both compile to ARM64 with BLAZER enabled and expected nm symbols. Policy/walker/hgltrack logic tests pass ASan+UBSan; cache instructions observed in object. hgltrack dylib and overlay rebuild exact original hashes. p3 guest has no UART log, no new guest result. No USB, boot, guest launch, full link or commit by this agent (parent owns those). Handoff `research/ios26-fleet/handoffs/gpumem.md` contains hashes, commands, pass/fail, integration gaps. Next physical test is parent-built bench-p27-track-r1 hgltrack stability; later linked 1200 with hk_surf=1 after image whitelist. No claim of hardware import/cache/fence correctness from host tests.
