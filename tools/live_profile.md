# Live console/profile decoding

`live_profile.py` consumes the files written by the existing `usbcon.py`. It is
host only: it never imports pyusb, opens a device, changes a boot argument, starts
a guest or modifies a capture. It handles the current p29 formats and scripted
replay grammar. Keep reports, device captures and Apple disassembly out of git.

For an offline raw capture, pass the complete image manifest, rather than the
launchd boot-argument line (which is truncated/interleaved in both p29 captures):

```sh
python3 -I tools/live_profile.py \
  --raw research/ios26-fleet/resume-20261102/p29-profile.raw \
  --manifest research/ios26-bootchain-r1/run/phone-p29-profile-r1/manifest.json \
  --verify-dump research/laguna-usb-fix/attempts/20261102-101134-phone-p29-profile-r1/ramdump/kernel.log \
  --summary --json research/ios26-opt-20261102/live_analysis/receipts/p29-profile.json
```

For an uncontrolled manual workload, opt in explicitly with `--manual` and the
actual complete image manifest. It must contain **exactly no `hk_ui` arguments**;
even bare, empty, invalid or duplicate arguments are refused. `--script` is
forbidden in manual mode. The default still requires exactly one complete,
valid `hk_ui` in a supplied manifest. If both `--script` and `--manifest` are
supplied in scripted mode, they must agree; an explicit script cannot override
the actual manifest.

```sh
python3 -I tools/live_profile.py \
  --raw research/ios26-opt-20261102/parent/art-container-15m-r1.raw \
  --manifest research/ios26-bootchain-r1/run/phone-p29-art-container-15m-r1/manifest.json \
  --manual \
  --verify-dump research/laguna-usb-fix/attempts/20261102-115426-phone-p29-art-container-15m-r1/ramdump/kernel.log \
  --summary --json LOCAL-manual-report.json
```

The report labels `workload.mode=manual`, `control=uncontrolled` and
`script.state=not_applicable`; it invents no replay, expected events, issue
phases, idle windows or screen transitions. Runtime `HK UI`/`HK UITRACE` evidence,
including malformed replay lines, conflicts with manual mode (exit 1). Byte
holes, partial lines, epoch/byte verification, presentation-evidence checks and
PC-label validation use the same paths as scripted decoding. Manual diagnostics
support no causal speed, FPS or touch-to-glass claim.

While the phone owner runs the existing console reader with a fresh output path,
a second host terminal may tail its files. This decoder has no device ownership:

```sh
python3 -I tools/live_profile.py --raw CAPTURE.raw --follow --events \
  --manifest IMAGE/manifest.json --json LOCAL-report.json
```

Append `--manual` for a manifest with no replay. This is a read-only host tail,
not an input injector or another USB reader. Run it only against the phone
owner's selected capture; it does not authorize a new boot or input command.

NDJSON records are flushed when a complete diagnostic line arrives. `--follow`
waits for the files to appear, consumes only newline-committed `.times` records,
and stops when usbcon writes the final `.json`, or on Ctrl-C. The final report
records interrupted status. File replacement, shrinking, changed committed
prefix, overlapping offsets and host-clock rollback fail instead of merging
boots. Do not reuse an old capture path for a new boot. `--verify-dump` is a
post-capture check; it needs the final status's nonce/entry tick/frequency.
`source.capture_state` distinguishes `final_summary`,
`provisional_no_final_summary`, `interrupted_provisional` and a dump's
`current_header_reconstruction`. A journal without its final `.json` remains
provisional even if an offline invocation exits 0; a final summary can still
contain gaps. A reconstructed dump is not necessarily a completed boot.
`source.manifest_sha256` pins the manifest bytes, without claiming a manifest
path or image `epoch=` proves the raw stream's kernel identity.

For a dump without a live capture:

```sh
python3 -I tools/live_profile.py --dump ATTEMPT/ramdump/kernel.log \
  --manifest IMAGE/manifest.json --summary --json LOCAL-report.json
```

The decoder reads the current `XNU-MSGBUF v2`/`XNUENT1` headers, unwraps the tail
by stream position, verifies the console/tail overlap, and includes each byte
once. With no overlap, an unbound RAM-console head is omitted and reported. It
never scans the entire 4 MiB for strings from stale/duplicate regions. Lost
stream spans remain holes; their partial lines are discarded, and timestamp
log-neighbor associations cannot cross them. Truncated headers, rings, journals and committed
raw bytes fail with exit 2. An unfinished final text line is counted separately
and never promoted to a complete diagnostic record.

Symbols default to the **actual current root cache** at
`research/ios26-debug-r1/mnt/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64e`,
and labels at `research/ios26-root-r1/apple/dis/QuartzCore.s`. `--cache` and
`--quartzcore` override them. `--no-symbols` needs neither Apple artifact. If the
default cache is absent, decoding continues with unresolved PCs. An explicitly
requested missing/invalid cache fails rather than silently selecting another
build. The tool reads the current main/subcache mapping and image tables and
checks executable Mach-O segment bounds. It does not copy or extract caches.
For QuartzCore, a function label additionally requires matching instruction
bytes at the requested unslid address. Other cache images are named without
pretending their private functions resolved. Main-binary addresses remain
relative/unresolved. `.symbols` presence is reported; that file is not required
or loaded. `ipsw` is not invoked. Reports include cache UUID and disassembly hash.

Interpretation rules:

- Kernel times are absolute monotonic seconds, including time before XNU entry;
  they are not elapsed since console connection or the image's `epoch=` value.
  TOP's integer `t` means `[t,t+1)`. Events lacking their own kernel stamp get
  neighboring log stamps, not interpolated timestamps or guaranteed event-time
  bounds. Concurrent writers can timestamp before printing; cross-writer stamp
  inversion is reported, not misclassified as a new boot. Same-thread TOP/trace
  clock reversal and repeated trace sequences fail.
- `.times` gives **host receipt** of the read completing a line. It is a separate
  clock. No transport delay, input latency or wall-clock alignment is inferred.
- `HK UITRACE token` records only each token's first callback. `done` reports
  maxima across all callbacks/events. A smaller token-head maximum does not
  replace the done maximum. The manifest's repeat expansion and counts are
  checked against the trace; missing token sequences/phases remain incomplete.
  Without a manifest or `--script`, expectations are unknown; no dry run is
  fabricated from an incomplete boot log.
- Issue phases group replay operations, not verified screens. Waits and windows
  after the script are not automatically idle. TOP windows retain their full CPU
  and logged counter deltas plus phase intersections. CPU is never divided among
  phases by assuming a uniform work rate. The initial TOP sample includes extant
  tasks' lifetime CPU; later interval bounds come from successive TOP stamps.
- TOP task listings are the eight largest surviving deltas; exited-task CPU can
  be absent. Interleaved lines keep intact headers/task prefixes and mark the
  task list incomplete. In p29 SweetFramebuffer.cpp, `sweet_fb_frames_presented`
  increments per eligible copy-path layer **before surface validation**, or after
  flip admission. The logged `frames+` does not count completed frames. CPU per
  counter increment is not frame-rendering/completion or touch-to-glass latency.
- `HK HOG` inspects selected `TH_RUN` threads' saved user registers at their last
  kernel entry, **after** the preceding TOP CPU window. Its three 20 ms rounds
  are not a statistical profile. Record counts do not give function CPU shares.
- Crash diagnostics and affected PIDs are separate: CoreFoundation, libc++abi,
  libsystem_c and userabort lines may describe one termination. Spawn/exit
  records and TOP PID changes expose restarts without counting each line as a
  new crash. A surviving PID alone does not prove correct screen behavior.

`--json` writes the full report atomically; `--summary` prints a short report.
`--events` writes NDJSON; it cannot be combined with `--summary`. Exit 0 means the
capture decoded without consistency errors, **not** a completed script or a
working phone. Inspect `script.state`, phases, gaps and warnings. Exit 1 means
the observed trace conflicts with expectations/completion; exit 2 means input,
epoch, format or integrity failure. No GPU/UI/performance fix is implied.

`HKAKSTRACE` v1 uses the same analyzer, raw journal, epoch, offsets, receipt times
and canonical-dump reconstruction. A parsed `ready` line only proves trace
initialization (`aks.state=ready_only`). A parsed selector record is separate
execution evidence (`execution_observed`), even if its ready line was not
captured. An intact fixed header followed by a damaged/short frame suffix is
`record_integrity=prefix_only`; a capture with only these is
`execution_prefix_observed`. Its requested/reported sizes, writes, DER header
bytes and PC/LR remain observations. **No frame addresses** are retained unless
the entire suffix matches the declared count, avoiding false addresses from cut
hex values. The exact damaged suffix and original line remain in the report
with a warning. Complete and partial record counts stay separate. Unknown
versions and damaged fixed headers remain verbatim in `aks.unknown_records`,
never counted as execution. Extra trailing fields remain in the unparsed suffix.
Unterminated lines stay partial and lines cut by holes are discarded.

The existing source filters Spotlight selector17: first8 calls then powers of2,
up to65536 calls and300s after its first sampled stamp. The final sampled call
number and record count are not total boot calls. Duplicate calls or ready
lines fail; concurrent print/call order can differ. Missing observations do not
prove no execution, success or idle.

Each observation retains `in_scalars/in_struct`, requested
`out_req_scalars/out_req_struct`, reported `out_actual_scalars/out_actual_struct`,
input/output type, handle presence/value, `emitted`, `wrote`, `tag`, `short_len`,
`ret`, saved user state, PC, LR and up to8 frame addresses. The writeBytes return
can be short even when the existing handler reports success and the full output
size. The decoder preserves those differences. The tag/short length are only
two header bytes from the source buffer; there is no captured/validated DER
payload or genuine SEP/authentication result. Unknown tag/return values remain
values, not invented function or error names.

`t_ms` truncates the absolute kernel clock to a millisecond interval; host
receipt time remains separate. AKS v1 prints no ASLR slide or main image base,
so its PC/LR/frames stay unresolved. The decoder never borrows another record's
slide. Existing HOG cache bounds and instruction-byte label checks still apply.

Validation:

`HK PRESENT` v1 is an optional default-off kernel observation stream. The
decoder retains its exact stream byte offsets, receipt times and explicit
`mach_absolute_time` microseconds within the same validated capture epoch as
UITRACE. `epoch=` in an image is not its clock origin. No USB reader/protocol
change is needed. Event sequence numbers order observations under the trace
lock; console print order may differ. Duplicate sequence numbers are refused.
Missing/interleaved/partial lines remain missing; do not interpolate them.

Kernel `hk_present_trace=1` enables fixed sampling (first four selected
aggregates, then every 32nd), at most 448 event lines plus 64 counter snapshots
and one config line per boot. The existing TOP thread requests a snapshot after
each TOP interval. The new token needs the phone owner's explicit exact-1
image-allowlist integration; this decoder does not add or bypass that policy.
Without a config/counter line, trace enablement or final totals are unknown.
Counters continue after the event cap; snapshots also stop after their bound.
`event_drops` counts sampled observations suppressed by the event cap, not
transport loss or all unsampled work. A last snapshot is not a final boot total.

Each boot-local `id` names one accepted queue record, even when the client
reuses a `swap` ID. Replaced records need not be selected or submitted. Stages:

- `layer_copy`: an actual bounded row helper returned success. `bytes` is its
  destination span (width × height × 4), including blend destinations; it is
  neither memory-bus traffic nor a completed display frame. A plane trial and
  fallback can perform two copy operations for one layer. `copy_refused` is
  recorded separately. Empty partial damage may invoke no helper. This proves
  CPU loop return/stores issued, without a new barrier or PoC/visibility claim.
- `copy_aggregate`: the selected copy-path loop returned, with accumulated
  successful helper bytes. It can have zero copied bytes. It precedes the
  original panel-buffer selection/kick and does not prove publication.
- `submitted`: the existing `tdpu_kick` returned `TDPU_OK` for this aggregate
  and generation. `submit_not_ok` records any other kick return; a negative
  return can follow partial register programming, so it is not proof of a safe
  pre-submit refusal. Inactive/no-hardware paths are separate events.
  No ownership, retry, MMIO, polling, refresh, brightness or quarantine rule is
  changed by tracing. Probes/black frames without a UI tag are not UI totals.
- `fetch_layer0`: the existing terminal `tdpu_poll` observed FRM_DONE and
  FE_LAYER_DONE with no fetch-bus error. Its stamp is CPU observation time,
  potentially later than hardware completion. It does not independently prove
  Layer1 completion or FE-status freshness; the original driver's FE status
  clearing/attribution rules are unchanged. Fault, timeout, missing evidence,
  overlapping observer flight or undrained stop yields an unproved event.
  `observed` is a register-evidence mask: 1 means the status argument was read,
  2 means the FE argument was read. Other zero fields are placeholders, not
  observations of a zero register. Timeout passes status only; SError passes
  neither. Full existing terminal evidence has mask 3.

Timestamp differences include observer work, lock contention, earlier sampled
prints and scheduling. They are not pure renderer time. Keep the same trace
configuration for an off/fast experiment and inspect event caps and correctness
separately. The trace does not repair the existing flip-admission/stop lifetime
gaps or make zero-copy safe to enable. Counter `pending` is only the observer's
pending correlation ID; it says nothing about held surfaces or a safe drain.

The report's `presentation` field preserves observations and cumulative
snapshots. It reports glass timing and input causality as unavailable.
UITRACE temporal proximity can guide inspection; it cannot bind a response to
an injected or physical touch. Neither fetch evidence nor layer/copy counters
are scanout/glass timestamps or FPS. Physical visible-response measurement
remains separate and coordinator-owned.

```sh
python3 -I -W error::ResourceWarning tools/test_live_profile.py
```

To run all Python decoder checks without rebuilding the unchanged C replay
oracle, select the Python test classes explicitly:

```sh
python3 -I -W error::ResourceWarning tools/test_live_profile.py \
  CaptureTests JournalTests SymbolTests PresentationTests ManualTests AKSTraceTests
```

The tests run the real p29 captures through raw/follow/canonical-dump paths,
verify byte/epoch identity, compare the actual C replay implementation with both
manifest schedules, and exercise truncation, sparse holes, wraps, interleaving,
clock/sequence rollback and rejected symbol bytes. Private-source tests skip
when the relevant local artifacts are absent; they are not fixture copies.

Manual admission requires the build manifest's name, exact UTF-8 command-line
length, image/Mach-O/payload/ADT hashes and nonzero stamp nonce. A known capture
nonce mismatch is refused; streams lacking final status remain explicitly
`pending_unverified`. A matching stamp nonce binds this assertion only and does
not independently prove the whole image or kernel identity.

AKS dispatch preserves headers before considering interleaved TOP/presentation
suffixes. A retained frame list must satisfy the emitted writer's address range
0x100000000..0x7fffffffff, exact declared count and whole suffix syntax. In-range,
count-preserving text corruption remains undetectable; this is no complete-stack
or authentication claim.
