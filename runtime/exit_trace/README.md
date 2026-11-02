# Bounded exit observation

Original MIT diagnostic for native daemon startup. Default off. It observes an
explicit process name without changing its exit status or preventing exit.
This is diagnostic infrastructure, not a working Bluetooth implementation.

The saved `bt-3` kernel `84385359…` has a misplaced `noreturn` attribute on its
old returning trace helper. Its actual ARM64 code ignores filter/copy failures,
walks frames indefinitely and has no normal `exit1` continuation. Do not rerun
that kernel. Its 1.36 GB capture reports 1,034,263,045 lost bytes. The current
release contains no such helper.

The replacement uses XNU's existing `backtrace_user` API, with a maximum of
12 addresses including the current PC. A saturating atomic counter permits
32 selected records per boot. `TUNABLE_STR` initializes the process filter
during kernel startup. The empty default emits nothing. `noreturn` remains on
the actual `exit()` function. No new unwinder or manual PAC mask is introduced.

Each `hk_exittrace_v2` record has a unique ID, status, PC/LR, actual task Mach-O
header address, shared-cache slide with an explicit known flag, bounded
addresses and an ending count/error/info record. Concurrent records may
interleave; group by ID. Missing end/frames or any `invalid_count` is incomplete
evidence. A zero main address cannot establish a slide. Raw addresses may still
contain PAC if the kernel configuration does not strip it.

For a later approved diagnostic guest, the process selector is
`hk_exittrace=bluetoothd`. This package does not admit a phone boot argument,
create an image, acquire a guest/phone slot or change any radio policy.

Run from the repository root:

```sh
python3 -I runtime/exit_trace/check.py \
  --base research/ios26-release-r1/work/xnu \
  --output research/ios26-connectivity-r1/exit-trace-check-NEW
```

The output must be new. The command reads the release and stages three files:
the original observer under `osfmk/arm64`, its source-list entry, and the small
BSD exit hook. It never edits or links the release. Generated XNU-context
patches and compiler outputs stay ignored.

Validation runs the actual observer under ASan/UBSan and TSan with modeled
kernel APIs: disabled/name/state refusals, return to the caller, unwind faults,
invalid counts and concurrent record exhaustion. The unwinder itself remains
an existing XNU dependency, not hardware tested by those mocks.

Four real Mach-O ARM64 objects use the current release's generated recipes:
observer and actual `kern_exit.c`, each with `BLAZER=1` and `BLAZER=0` controls.
Symbol/relocation checks require the real observer, `backtrace_user` reference,
and the exit hook followed by the original `exit1`/`thread_exception_return`
continuation. Gate-off observer has no executable implementation. An accidental
`noreturn` mutation must fail compilation.

First complete qualification: `exit-trace-check-r4/receipt.json`, release
`e67445e600f080c2ccba0c639052ca9db1be53ca`, patch SHA256
`437dc391cfbfd23357da213e143707f59cb6d6107c7a98c6b05bde248cd6a63e`.
Earlier failed source/header/checker attempts remain in r1–r3. No full link,
guest execution or physical Bluetooth acceptance is claimed.
