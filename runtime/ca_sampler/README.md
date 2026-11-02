# QuartzCore CPU sampler

This package preserves the tested sampler implementation. It is a proposal for
`runtime/ca_sampler/`; the coordinator owns applying and committing it. The three
files in `src/` and both C tests are byte-identical to the originals in
`research/ios26-opt-20261102/sampler/`. No renderer, arithmetic, admission guard,
fallback or runtime mode changes are included.

The ARM64e dylib targets the pinned 23G90 QuartzCore format-1 sampler table in
backboardd. It checks the image UUID, all sixteen table targets, complete axis
and projective fingerprints and actual-original selfchecks before changing five
data pointers. It restores read-only protection and rolls back on failure.
`HK_SAMPLER_NEON` defaults to zero; builds explicitly test both zero and one.

Four adjacent unit-step pixels use the existing signed rounded NEON interpolation
in vertical-then-horizontal order. The real original handles borders and refused
inputs. Projective specialization additionally requires mode 0, W exactly 1, dW 0,
dY 0, dX 65536 and X/Y divisible by 128; genuine perspective remains original.

`HKSAMPLER=observe` retains original output and counts eligibility. `verify`
retains original output and compares eligible full spans up to 4096 pixels,
latching candidate suppression on a mismatch and counting skipped long spans.
`fast` uses the candidate for admitted interiors. With no HKSAMPLER value the
constructor does not install a hook. FAST mismatch counters do not prove a
comparison occurred.

## Reproduce locally

Run on an ARM64 Mac with Xcode's iPhoneOS SDK, Homebrew LLVM and the existing
local inputs listed in PROVENANCE.md. No reference implementation, overlay writer,
PAC rewriter or XNU headers are vendored. Missing local inputs are errors; the
tests do not substitute a scalar model or embed Apple machine code.

After the coordinator applies the patch, run from the repository root:

```sh
python3 -B runtime/ca_sampler/tools/build.py \
  --output-dir research/ios26-opt-20261102/sampler_package/run/applied-r1 \
  --compare-original research/ios26-opt-20261102/sampler
```

Before application, replace `runtime/ca_sampler` in that command with
`research/ios26-opt-20261102/sampler_package/proposal/runtime/ca_sampler` and
choose a fresh output directory. `--compare-original` is optional for a normal
build; it additionally checks source byte identity, freshly compiled old/new
objects, delivered objects/dylib, and a separate diagnostic DWARF build pair.

Repository discovery walks upward to the nearest `.git` directory or worktree
gitfile. It does not depend on the source's nesting depth or the shell's working
directory. Relative CLI arguments use the caller's working directory. Local
input paths can be changed with `--binary`, `--disassembly`, `--pacstrip`,
`--mkoverlay`, `--xnu`, `--base`, `--base-sha` and `--llvm-bin`; see `--help`.
The reference binary remains pinned to the tested SHA256 and UUID.

All output paths must be below this checkout's ignored `research/` directory.
The default output directory is `research/ca_sampler`. Builds, generated
`fingerprint.h`, signing data, disassembly, logs and composed overlays belong
there, never in this source package. `-B` and helper imports suppress bytecode
caches in local source/dependency directories.

The sequential build performs ARM64e gate0/gate1 code generation and TEXT-symbol
checks, strict signing and instruction checks, fatal ASan/UBSan plus release
executions against the unmodified local ARM64 originals, and the actual XNU
overlay/exec-rule consumer. Only authored C is sanitizer-instrumented; guard
pages and output checks bound the original machine code. A missing consumer is
an error, not a skipped passing test. Commands, source/input hashes, object
comparisons and logs are recorded in the output's `receipts/` directory.

To compose an additional local RAM overlay after a build:

```sh
python3 -B runtime/ca_sampler/tools/compose.py \
  --base research/ios26-gpugl-r1/phone/p5-merged-r2-gltrack.ovl \
  --base-sha 61c38161efd809bdac15f9f167e5431a4f116b54bf42c7280411480fa37bea2a \
  --library research/ios26-opt-20261102/sampler_package/run/applied-r1/build/hsampler.dylib \
  --mask 0xA0080081 --mode verify \
  --output research/ios26-opt-20261102/sampler_package/run/applied-r1/new-verify.ovl
```

Composition extends exactly one selected hk_env record, preserves the other
records byte for byte, retains hgltrack and adds one sampler library. Multiple
selected hk_env records and repeated sampler injection are refused. The default
mode is off. The composed overlay contains existing Apple artwork and remains
local. These commands never build an image, kernel or guest and never access a
device. There is no deployment step.

## Existing physical evidence and remaining work

The coordinator's completed physical VERIFY attempt
`20261102-110205-sampler-verify-p29-r1` compared 598,888,390 full-span pixels,
with 594,003,511 eligible interior pixels, mismatch=0/latch=0/verify_long=0 and
identity=0. Installation/selfcheck/reprotection passed. There was no backboardd
abort or push_surface failure; the user reported working Home/Settings with
the same visual issues. See PROVENANCE.md for exact evidence paths and hashes.

Projective identity specialization has **no physical coverage** in that attempt.
Independent pre-boot review found no code findings and passed 147 additional
boundary/fallback cases; that review is not a performance result. Missing logos,
other visual issues and slow interaction remain unresolved. VERIFY deliberately
does extra work. Repeated controlled OFF/FAST comparisons and visible latency
measurements remain pending. No phone speed, FPS, GPU/Metal or end-to-end latency
improvement is claimed. Host microbenchmark lines are diagnostic logs only.
