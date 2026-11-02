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

While the phone owner runs the existing console reader with a fresh output path,
a second host terminal may tail its files. This decoder has no device ownership:

```sh
python3 -I tools/live_profile.py --raw CAPTURE.raw --follow --events \
  --manifest IMAGE/manifest.json --json LOCAL-report.json
```

NDJSON records are flushed when a complete diagnostic line arrives. `--follow`
waits for the files to appear, consumes only newline-committed `.times` records,
and stops when usbcon writes the final `.json`, or on Ctrl-C. The final report
records interrupted status. File replacement, shrinking, changed committed
prefix, overlapping offsets and host-clock rollback fail instead of merging
boots. Do not reuse an old capture path for a new boot. `--verify-dump` is a
post-capture check; it needs the final status's nonce/entry tick/frequency.

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

The tests run the real p29 captures through raw/follow/canonical-dump paths,
verify byte/epoch identity, compare the actual C replay implementation with both
manifest schedules, and exercise truncation, sparse holes, wraps, interleaving,
clock/sequence rollback and rejected symbol bytes. Private-source tests skip
when the relevant local artifacts are absent; they are not fixture copies.
