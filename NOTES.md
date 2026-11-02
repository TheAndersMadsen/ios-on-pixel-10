## Stock apps and Apple identity goal, 2026-11-02 — host candidate, guest in progress

User requires all apps running plus legitimate device identity/Apple services
and SEP, and explicitly requested GitHub reuse. Goal ACTIVE, not achieved.
Original implementation/source assessment committed **c214b86**. No new agents.
Own namespace `research/ios26-apps-r1/`, `tools/ios_app_*`, tests and
`docs/IOS-APPS-IDENTITY.md`; phone owner retains sole USB/release/deployment.
Existing MCM/artwork/sampler/Spotlight hooks were not duplicated or modified.

Read-only actual stock/r3 inventory:206 top-level app/service bundles retained;
all49 staged stock apps absent, and first-boot registration is an explicit no-op.
Missing staged regular bytes1,166,707,757 exceed r3 free553,840,640 before other
resources. Own20GiB APFS clone restores49 to /Applications, all staged regular
paths/executables present,4,183,437,312B free before re-seal. Repaired inherited
stale resource seals in own clone;49 deep ad-hoc signature checks PASS. Real
registrar uses URL API + fresh installed/nonplaceholder/path readback; never
invents signer/UDID/registration/launch success. Own51-app explicit manifest.

HOST PASS:7 Python inventory methods; actual Objective-C readback/input policy
under ASan/UBSan; gate-ON ARM64e objects emit3 expected text symbols, OFF omits;
final registrar signature/entitlements match; complete current CI PASS (existing
capture skip1), tracked scanner219 clean. Candidate fsck read-only exit0/OK
(after raw open fell back to NO WRITE). Registrar SHA714d2c0a…; full candidate
SHAf4a9a59f07bc8d261ae5d99361a5e3f50247b52439917b90ab73992bf98dc1ee.
Original light edd8d9fb… and canonical r3 205cb0e2… rehashed unchanged.
Exact hashes/build/guest argv and diagnostics in own `receipts/`.

QEMU only:registration-r1 failed backing-file open before CPU; own harness now
uses QEMU-advised readonly=on,rom=off for immutable MAP_PRIVATE root. r2 mounted
20GiB HFS then panicked varfs seed40 errno22, saved console7,880B/ramoops. Exact
file extent17,532,928,000 exceeds fakeUFS's hardcoded8GiB view; actual p29
n892_read ASan/UBSan test reproduces ARGUMENT/no backend call, mapped toEINVAL.
No seed file was removed and physical partition bounds were not widened.
r3 uses existing whole-RAMDisk ADT/rd=md0 contract, SAME root/p29/overlay, no
fakeUFS/MMIO args, shared guest lock; runner81301. It passes varfs and executes
launchd, SpringBoard, lsd/MCM; registration/representative launch still pending.
No physical boot/attempt ID, root/partition/Android/slot/firmware operation here.

GitHub26 text sources pinned/rehashed: MIT OpenSEP ead61b7 boots SEP firmware
on virtual Apple platforms but needs SEP execution/mailbox/device backend;
vphone fd1610d7 documents research activation and no iCloud support. OpenBubbles
provides Mac-backed Apple-service clients; rustpush's own licence differs.
Anisette/APNs/provisioning results are not full native iPhone identity. Current
SweetKeyStore remains fixed-state compatibility, not a supported SEP backend.
No account login, credential collection, activation request or genuine SEP claim.

Next: finish registration-r3 and extract real51-app results, repair the actual
failing service if any, then representative app launch/UI survival.20GiB guest
candidate cannot deploy into current8GiB root; storage isolation/review/concrete
user approval precede a phone root change. Keep phone queue with its owner.

## Native Metal diagnostic qualified, 2026-11-02 11:21 CET — build only

Checkpoint committed **9db93cb**. Subsequent orchestration steer delivered to
all ten EXISTING owners, with one source/ABI/ownership contract at
research/ios26-metal-native-20261102/integration/CONTRACT.md. UC-r2 owns the next
runnable combined native-adapter/provider host path; peers resolve exact shared
ABI/lock/ref mismatches there. Sent concise blockers/minimal candidate to the
repo orchestration coordinator; exact11 delivery receipts in
integration/orchestration-deliveries.json. This coordination started no new
delegate/review/implementation and changed no device ownership or physical gate.

Independent parent review selected firmware's standalone pending-FWCCB
diagnostic, not the queue alternative or lifecycle/combined patches. Exact
source/gate/tool patch SHAs: fee036ca368ac3e0fc23144c57deb2aeca07b7e29f628fd306e3ba376550a8a2,
afb560a7f96281d79c8ce61ce1edd33b9b0768825c0a9eb8f4dc9b3f821ce07c,
0bb6deef70de4ad4b189f2cad7f7f8926480d420716ca07e466c96289f8f1372.
Current release HEAD b03d04d1e8111d8bfae34379c1565ed370105524; tipc7efcfe4d…
unchanged. Sparse apply+byte comparison PASS. Parent isolated actual health/
hook/core ASan/UBSan PASS; three compiled behavioral mutations rejected;
fresh vendor header measurement byte-identical; canonical profile + four
drift controls PASS; two enabled ARM64 objects/named text symbols and two
gate-off controls PASS; actual image-token positive/negative controls PASS.
Exact commands, source/object/profile hashes, receipts and request:
research/ios26-metal-native-20261102/integration/diagnostic-review-r1/
{HANDOFF.md,REVIEW.json,receipts/,coordination.json}.

Reader captures actual pending READ slot, max4 whole112-byte entries before
timeout/failed return, all28 raw words/type/flags/race + SYS/COMP metadata.
No ack/consume, invented return bit, extra kick, power/clock/SMC/firmware change.
Correct compatibility offsets show old labelled BVNC words were layout/padding.
Runtime requires rung5+diag1; original timeout/result unchanged. Host diagnostic
qualification is NOT physical health or execution acceptance. HEALTH5 remains
FAIL at attempt20261102-102719-native-metal-health-p29-r1, no unchanged retry.

Phone/release owner read request and acknowledged BUILD ONLY source review of
these three patches, with new p30/interactive input subject to its own review.
It will return source/kernel/unstripped/image hashes, enabled final symbols and
exact embedded firmware proof before any new sequential health-slot request.
No health boot scheduled; exclusive USB/current cpu0-audit then sampler queue
preserved. This goal parent ran no device command, full build/link or image.

All previous-wave owners returned;17 bounded milestones now in terminal history.
Ten fresh Sol implementation owners launched/steered successfully: firmware-r2
runtime profile; uc-r2 queue/failed-work wiring; vm-r2 FW context/MMUCACHE;
queue-r2 native compute state/body; isa-r3 native C ALU/control/allocator;
streams-r3 shared/frozen integration; metal-r3 readiness lease; surfaces-r3
imported failed-data handback; air-r3 typed VS/FS; validation-r4 real IOKit BO
acceptance app. Exact IDs/links/briefs in fleet.json,FLEET.md and
successor-wave3-briefs.json. Each writes only its new ignored directory; old
milestones frozen. Ten coordination deliveries recorded, no delegate polling.
Other milestones' test totals remain child-reported pending parent integration.

Existing upstream collector refreshed eight exact GitHub heads: unchanged;
all24 text source/licence files rehashed PASS. Additional reuse audit retained
and conveyed to current successors. Firmware canonical measured profile
68f5ba78e85ec7750668de3a4ed1cebe5ba0b4a7a84017e39dda2cc486ef967c
and queue agreement header must be reconciled/adopted across real adapters;
no fourth constant set. Runtime ABI, complete USC/FP/launch rules, real MMU/
context/cache/UPL handback and authentic engine completion remain unproved.
Next parent work: review returned implementations/owned offline compiler
request and returned p30 artifacts; only then request a phone diagnostic slot.
Native Metal/original goal remain ACTIVE, not complete.

## Saved Android AVB recovery gap, 2026-11-02 11:22 CET (host only)

Android structural inventory committed **7e43b70**;8owned-fixture/AOSP testsPASS,
vendored unmodified Apache unpacker+licence/provenance; readback16tests nowinCI.
PMBR host fix **f329418** ready, delivered for coordinator review/later slot.
No new phone attempt/USB use here; coordinator still owns current physical work.

**New observed recovery blocker in SAVED FILES:** bounded buffer audit with
pinned MIT AOSP avbtool761178607206f4cb2af79ed9eec52d8cbd814adb
(SHAe5a664a38db623da00f080219bc0ee60a640a9dc4a872803616fae4938ac749b,
same version as existing builder tool) validates boot_a RSA4096 signature+payload;
init_boot_a RSA4096 METADATA signature valid but PAYLOAD HASH FAIL.
Its signed hash descriptor image_size2998272 exceeds footer original_size2838528
and includes metadata/padding. Cause UNKNOWN. Independent AOSP verify_image on
separate mode0400 copies confirms boot exit0, init_boot exit1/digest mismatch,
vendor_boot exit0 with algorithmNONE (unsigned, NOT signature-valid proof).
All originals/copies hashes unchanged before/after. No top-level trusted-key or
chain verification available. Saved-file result does NOT establish live Android
integrity or authorize Android boot/reset/recovery writes.

Exclude saved init_boot_a from any VERIFIED restore set; get matching fresh
copies and trusted AVB graph. Phone owner received exact evidence via steering.
Full source/metadata receipts (no raw IDs in git): r3/inspect_saved_avb.py,
stock-a-avb-footer-evidence.json, avb-cli-oracle/{results.json,*.stdout,*.stderr}.
No new core implementation claim for this one-off audit. Full GPT capture,
complete backups/isolated allocation and native chooser/Android return still
unfinished. Keep goal active and all existing storage/boot holds intact.

## CPU clock-table validation, 2026-11-02 — audit boot in progress

CPU goal ACTIVE, score84 unchanged. Committed **bd7326c** adds original host
`tools/cpu_dvfs_check.py` +7 regression methods and extends docs/CPU.md. Reuses
existing clk-probe decoder pinnedSHAa3baf953…; no second wire decoder/governor.
Actual saved nonce/epoch/sealed clock capture validates18 domain/rung rows
against BOTH exact p29 source and reviewed0773 source0d1c4acf… . Explicit
firmware IDs34/35 are separated from MMIO vote domains1/2; duplicate IDs/names/
levels, unsupported/override-only OPP, missing rows, wrong units and altered
existing domain ceilings refused. New tests PASS; four mutated copies of the
ACTUAL saved record (nonce/truncation/torn/no-end) fail CLI as required.
Original capture unchanged. No additional device operation or source admission.

Independent unmodified GPL donor lookup functions from exact6.12@5940a317
compile/run ASan/UBSan:103 actual assertions PASS incl unit width/round-trip.
Copied donor text+notices stay IGNORED in research/ios26-cpu-complete-r1/dvfs/;
no GPL implementation imported into tracked/XNU source. Full CI PASS including
new7 (and other owners' new dualboot suites); CPU CI invocation landed with
parent7e43b70 while preserving its separately staged files. Receipts: own
dvfs/{p29,0773,vendor-oracle,real-input-negative,capture-source}.json.
These are table correctness checks, NOT physical speed or higher-cap permission.

Phone owner confirms mode1 audit **started**, attempt
`20261102-110932-cpu0-audit-p29-r1`, unchanged image226eba4f…/p29/Ucc979153… .
Observed actual bootios PID96987 + run-attempt97010 alive at3m22; capture absent
at this checkpoint, not a failure. Sole phone owner retains USB; this CPU goal
issued no device command. Keep no-OFF/reentry/high-clock scope. Await its fresh
capture, independently run strict audit + SMP/reset/thermal acceptance, and
only then select the next A520 step; no blind retry or fabricated completion.

Parent integrated floor0772=f9f6ec67/series1172 and0773=b03d04d1/1173;
current governor hash matches independently reviewed0d1c4acf… . Diagnostic
compile0 and high0 unchanged; parent reports full link still pending. Existing
p29/audit images immutable, CPU audit kept separate from future stepdown tests.

## CoreImage fallback verified in QEMU, 2026-11-02 (host only)

Committed source/audit/reproduction: **55d423d**, `docs/INFERNO.md` and
`tools/coreimage/`. Exact root r3: iOS26.6.2/23G90, `205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7`.
CoreImage UUID6f5abd16-0e3c-3fc3-bcc7-ccefeafbca00. All12 Inferno targets match
stock after existing PAC rewriting; none of its return stubs was present.
Selected ONLY `_isWidget` at0x19e041778: eight instruction bytes + one32-byte
page hash in an owned host clone. CandidateSHA6ba62469f05e553c21c965e092b356e7f2509406064d24299a0b0f9193915a8f.
Complete-image masked comparison and source rehash PASS; independent5318-page
signature check0invalid. A second exclusive clone reproduced identical bytes.

**Actual QEMU acceptance:** `control-r3`235.242s and `widget-r3`244.994s, same
p29kernel5aad8978…, unchanged harness098b2597…, same probe70f877c5…/overlaydedb25c3….
Control isWidget0: default/GPU/BooleanCPU context nil; numeric software_renderer2
positive control selects SW and passes all red/CIColorInvert pixels + guards.
Changed isWidget1: all4 cases selectSW and pass the same pixels/guards. Both
exit0, input roots unchanged, no recorded console loss; observers restored.
Strict verifier PASS; eight altered failure receipts rejected. ARM64e object
has actual probe/observer/pixel-check text symbols; linked probe signature PASS.
No new kernel build. Full evidence: `research/ios26-inferno-coreimage-r1/receipts/`.

Earlier `control-r1` refused observer ABI; r2 bitmap-backed input failed pixels.
Those are preserved failures, not acceptance. Bitmap cause remains UNISOLATED.
No missing-icon, UI speed, Settings/home-script or physical claim. Runs ended
before480s UI script. Source image unchanged; own read-only mounts detached,
other owner's stock mount preserved; both owned test inputs parked0444. No USB,
phone boot, firmware command/download, radio, slot/partition/root write or flash.

Reuse3139238/d18fbb4 incorporated. Battery glyph/container-ready/cloudd/sampler
remain separate owners' candidates. hgltrack stays single-applied. Forced SW
must remain separate from native Metal acceptance. Next useful extension is an
isolated bitmap/import readback diagnostic or process-scoped runtime fallback;
any phone candidate still belongs to the existing coordinator and is untested.

Shared QEMU lock was free/no QEMU process at11:15:11CET after both guests
finished; check released immediately. Apps owner1c8ae1db notified by steer
`inferno-coreimage-slot-released-20261102-r3`; phone coordinator2ff85bbd received
results/limits via `inferno-coreimage-qemu-evidence-20261102-r3`. Both deliveries
reported steered/running; neither requests a new task or physical action.
Coordination receipts are in the ignored experiment directory. Handoff7eaed8c.

## Phone owner result, 2026-11-02 11:11 CET — sampler correct on tested spans; CPU audit live

PhysicalsamplerVERIFY20261102-110205 COMPLETE/captured, image02b99c95… matching
p29/overlay0a8046ad… . Realconstructorinstalled once, selfcheckPASS/reprotect0,
hgltrackpreserved. Final598888390fullspanpixelscompared,594003511eligibleinterior
pixels,0mismatch/0latch/0longspan. Projectiveidentity0: thatfastbranchhasNOphysical
coverage. NoBBabort/push_surface; userHomeSettingsworks/samevisualissues. Script
66tokens/1569eventscomplete,maxlate2437us/maxcall2763us; notglasslatency. Noactual
speedgainclaimedfromVERIFY. Independentreviewreturnednocodefindings,147additional
boundary/fallbackcasesPASS; no physicalproofconflation.

DumpSHA0184107434bcafd022484c399048e54517b8334f720cc290c7cdf0ec8107de18.
Live2588366bytes/0lost,662finaldumpbytesnotlive; retainedhead+tail2096461bytescompare
0mismatch,491905bytesliveonlybecauseRAMwrapped. Strictepochcanonicalprofilerchecks
only1047914currenttailbyteswhenheadhasnooverlap; doNOTclaimentirelivefileRAMverified.
Expecteddeadline300,XNU300.6s/payload327.2s,PSCI-SW,39C/SOC89/4332,0CPMerrors.
Newtools/live_profile.pyreportretainsinterleavedTOPwarnings/nofabricatedFPS.

Currentexclusivephoneattempt `20261102-110932-cpu0-audit-p29-r1` RUNNING: image
226eba4f…/unchangedp29,read-onlycpu0MRSbeforeexistingfiveA725baseline533handoff,
noOFF/reentry/highclocks. Parent reviewedactualsource/gates andreran7hosttestsPASS;
exactimage/kernel/Uhashesmatch/checkPASS. Runner39426/live53040. Nootherdevice
commanduntilcapture. CPUparentkeepssource/acceptance; resultnotyetknown.

Releaseonly: floor0772addedf9f6ec67/series1172,0773addedb03d04d1/series1173;
source/exportscommitted, clean; probecompile0/high0. No fullnewkernel/linkyet.
Typedliveinput1410+nativeGPUstandalonetimeoutdiagnosticreview/buildnext; noGPU
healthretryuntilreviewednewartifactsandseparateslot. Sampleroffimageee70fb73… and
fast128674c9… built/checkspending; oldp29unchanged. Artworkisolatedf89f74c6… built
andchecked, notbooted. UpdatedGPThostprofilef329418 received,queuedforlaterreview.
FiveownSolactiveafterreviewcompletion; addedSpotlight-runtime successorbecause
newcapturestillshows~onecoreCPUafterUIreplayends. Actualcauseunproved; nofakeSEP/
authsuccess/blanketdaemonkillrequested. Otherappsgoalownsios26-apps-r1, noUSB.

## Android boot-chain inventory milestone, 2026-11-02 11:11 CET (host only)

PMBR/failure-evidence correction committed **f329418**. Changed host profile and
explicit reviewed MBR hash delivered for coordinator review after sampler;
no new physical attempt by this thread, no USB use. r1 physical result remains
ONE exact LBA0 read, host GPT rejection, not a successful GPT snapshot.

Implemented `tools/android_bootset.py` using UNMODIFIED pinned AOSP unpacker
`d2bb0af5ba6d3198a3e99529c97eda1be0b5a093`, SHAa9d26097…; Apache notice,
full licence and source provenance in third_party/aosp_bootimg/. Original wrapper
independently bounds every v4 component/vendor-fragment, then compares extracted
bytes + fragment metadata with AOSP. No generated commands executed. Input
hash/stat preserved, only ignored extract/inventory outputs. **8 host tests PASS**
on owned AOSP-produced fixtures/malformed extent and name cases; both bootset
and readback tests included in CI's research-free list. No kernel/C change here.

**Observed saved slot-a recovery gap:** boot kernel20437225bytes; init_boot
ramdisk2830598; vendor_boot two variants (empty/platform +16K/none), NO DTB.
No saved vendor_kernel_boot_a, DTBO or AVB metadata in that set. Old files marked
slot b have mixed capture histories and different structural contents; they are
NOT a proved matching/current/stock recovery set. A valid header/extraction is
not a trusted AVB key/chain, complete backup, Android integrity or safe dispatch.
Exact private hashes/extents/results: research/ios26-dualboot-r3/{HANDOFF.md,
inventory-evidence.json,stock-a-r2/inventory.json,saved-b-mixed-r1/inventory.json}.
Next: finish real GPT capture, get matching boot dependency copies and verified
AVB graph/key provenance; full backups/isolation/chooser/Android return unfinished.
No Android/slot/root/GPT/firmware/force-fastboot operation or new agent here.

## Dual-boot physical discovery and host correction, 2026-11-02 11:05 CET

Phone owner completed/captured **20261102-105345-dualboot-gpt-readback-r1**;
this thread independently rehashed raw kernel.log to
`8845074b9436c8c372b07cd1d1c832173ebd7494ed4b25ec90c7934b9bc04761`
and inspected current decoded mode/deadline lines. Native exact LU0/LBA0 read
physically worked, same nonce/entry/LUN/generation1/CRC through cached readback.
**Full GPT snapshot FAIL:** host rejected saturated PMBR size0xffffffff at start1
versus31147008-block capacity BEFORE any GPT-header read. The phone owner
retained cached bytes with INFO/DATA only, no SELECT/storage retry, then ordinary
deadline300 reset/park (XNU300.5s/payload326.6s,38C/89%/4332mV,0CPMerrors).
Live304353bytes match RAM0mismatch;296panic-tail bytes not received live.

Retained raw block hash independently matches
`28894fedd22215fa7fa86b04eeeee270e1ca040c9ca5ec6d157adbe2b2a8c302`,
CRC0x161dd6f8. One EE protective entry, other3records allzero. Read primary Linux
v6.12 efi.c:is_pmbr_valid and UEFI2.10A: the former explicitly recognizes maximum
32-bit size regardless of disk size; UEFI describes canonical bounded size.
Original host fix keeps strict default and requires EXPLICIT reviewed whole-block
SHA256 for this saturated form. No arbitrary sizes, hybrid records or GPT checks
are relaxed. Source receipts/byte analysis ignored in r3/pmbr-review/.

Also fixed observed evidence-loss bug: save EVERY received block before parse;
failure.json labels incomplete/refused evidence and no successful capture.json
is written. Saved observations reverify against final metadata offline. **16
Python tests PASS**, including actual C protocol, no-extra-read failure retention,
explicit hash requirement, malformed sizes/CRC refusal and observation corruption.
Kernel/C/image unchanged; no reason to repeat ARM64 builds for this host-only fix.

Separate reviewed follow-up profile prepared in
`research/ios26-dualboot-r2/phone-test-r2.json`: same immutable image/own --mach,
new phone-r2 capture directory and explicit reviewed PMBR hash. NOT yet scheduled;
phone owner is now running sampler verification. Do not independently accessUSB.
Full GPT/isolation/backups/Android return still unproven. Offline AOSP boot-chain
inventory is advancing in r3 separately; saved slot-a lacks vendor_kernel_boot,
DTBO and AVB metadata, and its vendor_boot contains two variants and noDTB.
No Android, slot, root, partition, firmware or force-fastboot operation here.

## Phone owner live slot, 2026-11-02 11:03 CET — sampler verification

Prior readback attempt20261102-105345 COMPLETE/captured, all304353 livebytes match
RAM;296finalbytesnotreadlive. RawkernelSHA8845074b9436c8c372b07cd1d1c832173ebd7494ed4b25ec90c7934b9bc04761.
Expecteddeadline300, XNU300.5s/payload326.6s, PSCI-SW, postreset38C/89%/4332mV,
0CPMerrors. GPTcapture FAIL protection-MBR geometry; preservedcachedLBA0 raw+CRC,
noSELECTretry; dualbootparentnotified. FullGPT/Android/isolation remainunknown.

Now exclusive physical attempt `20261102-110205-sampler-verify-p29-r1` RUNNING:
image02b99c9554d504be6a0b072cafd1752b35e0d68c4c7629dff79f76275ec69b52, samep29
kernel/unstripped and exact990-byte command line as capturedprofile; onlyoverlay
changes to0a8046ad28223fa7a5f70a7da6362dbbfabb375f5be3e0a3af13a5f1a49e6096.
Originaloutput VERIFYmode, noGPU/clock/persistchange. Parent reviewed source,
identity, pixel-oracle and exactcomposition; independentreviewstillrunning.
Boot5376/live79750/decoder81693; raw/profiler inios26-opt-20261102/parent.
Don'tlaunchanotherphoneattempt until captured. CPUmode1audit queued; root/app
stagingnewparentownsios26-apps-r1 andtools/ios_app_*, noUSB/rootwriteauthorizedbyit.

Committedhostprofiler **e4e4c9c**,17tests+realcaptureverification PASS. Returned
settings_assets andcpu_fast/boot_services milestones remainHOSTONLY. NewRTC
integration/presentation-trace agents replaced completed work; sixownSolconfirmed
11:00 beforeboot_servicesfinished (nowfive). Maintain>=5 andonlySol; exactroster
underios26-opt-20261102. Nevercountothergoalchildrenfortheminimum.

## Reuse findings communicated, 2026-11-02 — 21 active owners updated

At the user's explicit request, read the live T3 project inventory and recent
context for related coordinators/subagents, then delivered **22 tailored
steering messages to 21 distinct active recipients: 5 coordinators and 16
subagents**. All other live threads in the closing inventory have successful
receipts. Exact text, thread links and message IDs:
`docs/reuse/2026-11-02/communications.{md,json}`. Audit remains commit3139238.

Updates covered current native Metal firmware/UC/VM/queue/ISA/AIR/streams/
frontend/surfaces/validation; phone/release, CPU, dualboot and Inferno parents;
settings assets, container/services, governor, interactive USB, USB networking,
profiler and the existing sampler reviewer. Messages preserve their actual
current assignments, newer source evidence, file licences and physical gates.
No duplicate collector, renderer, allocator, profiler or bootloader requested.
Peripheral findings went to the coordinator for future allocation.

One profiler finished between inventory and steering; the tool returned
`thread_not_sendable` (no running turn). Its full update was relayed to the
phone parent without restarting it. Two newly active owners were read and
updated in the closing inventory. Historical completed agents remain idle.
Delivery is confirmed; the phone parent's10:57checkpoint explicitly acknowledges
receipt. Other owners' adoption is not established by transport receipts.

Verification: 22 successful message IDs/run IDs and21 distinct thread links;
JSON/count/content/link/whitespace checks PASS. No new delegate, review task,
restart, cancellation, device operation or runtime implementation by this
communication step. Preserve the phone owner's current running attempt and
capture exclusivity in its latest checkpoint below; no new boot authority.

## CPU completion milestone, 2026-11-02 (host only)

User goal: take CPU's84% feature score to100%. Counted gaps are sustained
higher clocks and both A520s under XNU; X4 remains excluded by the existing
status model. Goal ACTIVE, score unchanged84. No new agents/delegates started.
Source/test/docs commit **a338f4a** (handoff3763fe3) adds a read-only cpu0 firmware audit,
strict dedicated image profile and nonce-bound verifier; acceptance docs/CPU.md.
Reuse3139238/d18fbb4 and four requested reports read; no vendor source import,
new frequency, duplicate governor/thermal implementation or allowlist expansion.

**HOST PASS:** actual audit+fastcore C ASan/UBSan incl actual Cstamp->verifier,
7 methods; image-tool78 and decoder14; complete CI PASS (existing capture skip1).
Enabled ARM64 ELF objects have named T symbols and ACTLR MRS, no audit MSR/SMC
or ABS64. Audit-disabled loader/fastcore objects byte-identical13a77d8 baseline.
Initial comparator's differing C basename caused FILE-symbol-only mismatch;
corrected fixture, code unchanged. No XNU source change/full kernel link here.
Full shim0undefined, route87/speed55/stage9,20/20+21/21+14/14 mutants,
7/7 capture replays and brightness1007 PASS. Source/object receipts:
research/ios26-cpu-complete-r1/{arm64.json,sources.json,HANDOFF.md}.

**Built/check-verified, NOT BOOTED:** research/images/cpu0-audit-p29-r1/boot.img
SHA256226eba4f07398ebdacbe378e7d8ddc06b6b596598e248a4f4eb587d59af03dab.
Unchanged p29 kernel5aad8978…/unstrippedcc979153…; exact hashes+argv arrays in
research/ios26-cpu-complete-r1/phone-test.json.588B command line, bootcpu0x200,
5A725s at baseline533, deadline300, thermal2/panic70, SMP report/self-test,
USBconsole/ch9; no touch/overlay/governor/persist/Trusty/GPU additions. cpu0
register audit continues the established A725 handoff, no CPU_OFF/A520 startup
or workaround write. The new verifier matches the ACTUAL p29 five-e6-DONE/raw
MPIDR/EL_DROP/headerreason5 protocol; a synthetic HANDOFF-DONE slot is not real.
Its PASS is only cpu0 bits9/38 prerequisite; A520 support stays unaccepted.

**No new physical attempt, USB/device command, emulator boot, firmware send,
root/partition/slot write or flash.** Phone owner has confirmed the image/argv
received and QUEUED for a reviewed sequential slot after the current GPT
capture/deadlinepark and sampler check; no new audit attempt/capture yet.
Owner alone boots/usesUSB. Trap, missing bit, refusal or unexpected reset STOPs
this A520 stage; no blind retry/speculative workaround write. Higher-clock
0773 remains with cpu_fast/phone owner, no duplicate import. Next: owner reviews
and captures this immutable audit, then independent cpu1/workaround/topology/
coherency/sustained acceptance; separate actual thermal downvote/floor-release
and higher-clock acceptance still required before CPU can reach100%.

CPU parent independently reviewed existing floor0772 + cpu_fast0773
SHAfe42596427faa1551ee594731b524ec3f89f9dcc5c118c84aa8448dba4a249fc.
Reran actual unchanged thermal producer + governor ASan/UBSan to OWN namespace:
probe0=709 assertions PASS, probe1=3840 PASS; existing ARM64 object identities
and named implementation (__TEXT,__text) symbols rechecked. Sources/patch
unchanged; no duplicate apply, release build/image-tool change or physical claim.
Receipt research/ios26-cpu-complete-r1/stepdown-review/review.json. Baseline
cap16, high HOLD; retain separate verify/floors/required/health/R1/R2 stages.

## Phone owner checkpoint, 2026-11-02 10:57 CET — live profiler integrated, GPT validation stopped

Integrated the returned actual live profiler as `tools/live_profile.py`, tests and
usage notes. Parent reran17 test methods PASS with ResourceWarning fatal, then
verified all967,660 p29-profile live bytes against the matching RAM epoch;479
final bytes absent live contain the expected deadline panic. Three saved PCs
resolve to exact QuartzCore software samplers. **HK TOP frames+ is per eligible
layer/admitted flip, NOT completed frames/FPS**; saved PCs do not give CPU shares,
and injection timestamps do not prove touch-to-glass latency. Original benchmark
interpolated phases are superseded by actual UITRACE callback times.

Read-only dualboot attempt `20261102-105345-dualboot-gpt-readback-r1` is still
running its original deadline300. Image21cba4e8… and own unstripped0ce50d8b… hashes
match; no Android/root/slot/partition write. Host capture stopped exit2 at
protective MBR geometry mismatch: actual typeEE,start1,sectors0xffffffff versus
supplied31147008 blocks. No SELECT/read retry. Preserved already-cached LBA0 using
INFO/DATA only with matching nonce/entry/LUN/generation1/CRC in ignored
`research/ios26-dualboot-r2/captures/phone-r1-failure/`; blockSHA
28894fedd22215fa7fa86b04eeeee270e1ca040c9ca5ec6d157adbe2b2a8c302. Dualboot parent
received exact failure. Normal deadline/capture still pending; no GPT success,
Android integrity, full backup or dualboot claim. Live reader session61948,
boot runner11250; no second phone action until both end/capture.

Sampler verify image built from exact p29: `run/sampler-verify-p29-r1/boot.img`
SHA02b99c9554d504be6a0b072cafd1752b35e0d68c4c7629dff79f76275ec69b52; actual
hgltrack-preserving overlay0a8046ad… . Independent review running. Verify mode
retains original pixels and logs candidate comparisons; physical test pending,
no speedup claim. Six own Sol workers were active after sampler/live_analysis
completed: settings_assets,cpu_fast,live_input,boot_services,sampler_review,
usb_network; exact roster underios26-opt-20261102. Reuse audit context received;
keep these owners/actual runtime paths, no duplicate renderer/profiler. Native
GPU prior health FAIL still blocks progression/retry without a reviewed change.

## Native Metal upstream refresh and physical STOP, 2026-11-02 10:56 CET

User explicitly requests GitHub reuse and an up-to-date fleet. Completed source
inventory: eight exact GitHub branch heads,24 immutable text source/license
files, rehashed PASS. Original collector `tools/native_gpu_upstream.py` + curated
`docs/NATIVE-METAL-UPSTREAM.md` committed as **4cc8c3d**. Output stays ignored in
`research/ios26-metal-native-20261102/upstream/current.json`; refresh reports head
changes and never merges. Outside-research output refusal PASS. Linked/hash-bound
seven existing audit documents from the parallel24-domain audit (3139238/d18fbb4),
not a second audit collector. Tegu is PRIVATE: authenticated API verified tip
8e2d75b (three commits/17 files beyond d807098); earlier public404 remains valid.
No root licence, facts-only use. Main reuse: MIT AdrenoMetal frontend831a9dc,
standalone AIR parser219f013 (GPL2+ OR LGPL3+,Rust1.98,no Vulkan dependency),
matching Pixel26.1 donor5940a317 already current17-qpr3-base. No drop-in DXT stack.

**Physical checked, phone-owner captures:** SEND2 attempt
`20261102-101843-native-metal-send-p29-r1`: len8/cmd1/result0 in185ms,
purposeful PASS; raw SHA49bff66a19a3da5b1dc42508ee906917ade02385923ebf645413b00563ebaba4.
HEALTH5 attempt `20261102-102719-native-metal-health-p29-r1` **FAILED**:
START0,started1,FWconn0/OS1,KCCB1/1,FWCCB1/0,sysdata0/0,compBVNC0/0,
no execution return, STOP1s/purposeful reset. Raw SHA
a402278beac84b5b617a1c5b22608296331fb6c44d998a260fdcb79e15b935f6.
Parent independently rehashed both dumps/selected fresh XNU fields and reran
strict verifier: FAIL as required. Phone owner added fw==2 acceptance check;
no duplicate tool edit. Existing26.1 send path shows no separately ORed return
request flag; do not invent one. Firmware/queue prioritize bounded raw pending
FWCCB snapshot on timeout and exact matching ABI. **No unchanged retry or
progression; phone owner holds USB.** This goal parent ran no device command.

Seven implementation milestones returned (validation1/2,AIR1,ISA1,streams1,
Metal1,surfaces1), with source/packages and host/ARM64 receipts; parent integration
review remains. Each completed slot was replaced with a fresh implementation
task: AIR reuse/native bridge, complete ISA, PDS input/resource initialization,
frontend loading/reuse, actual surface UC/queue wiring and render validation.
**Ten current owners**, all ten delivered upstream coordination through active
steers; no delegate polling. Exact current/terminal task IDs, links and briefs:
`research/ios26-metal-native-20261102/{fleet.json,FLEET.md,successor-briefs.json}`.
Reports/host test totals never establish phone rendering or execution.

Next: consume source-reviewed firmware diagnostic, compose one shared DDK/BVNC/
define/layout profile and real VM/context/invalidation/queue adapters; adopt
reused AIR/frontend code where compatible. Keep compiler, UPL/cache handback and
authentic engine completion requirements intact. No new physical boot request
until the diagnostic/repair candidate is concrete and reviewed. Native Metal
and full original goal remain unproved and active.

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
