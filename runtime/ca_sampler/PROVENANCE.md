# Source, licence and local evidence

The sampler, hook, tests and original helpers are original project C/Python.
The original author's record is
`research/ios26-opt-20261102/sampler/PROVENANCE.md`; it states that no external
implementation was copied and only ABI facts/offsets came from local inspection.
The MIT sidecar licence covers only this package's original project files.
External inputs retain their own terms and are not included or relicensed.

`MANIFEST.json` identifies every proposed source file and its SHA256, the exact
original byte copies, and which helper files have packaging changes. Runtime
files are copied without adding notices or reformatting; LICENSE supplies the
package's scoped notice. The C test harnesses are also byte-identical copies.

Changes to the Python helpers are confined to Git-root discovery, configurable
local inputs, ignored output locations, build/source comparisons and required
consumer execution. `prepare.inspect`, the composer transformation and the
original C tests keep their existing algorithms. The preparer additionally pins
the tested reference's whole-file hash and UUID. No vendor implementation,
extracted code, instruction listing, generated fingerprint header, artwork,
cache, dump, overlay or binary is included in the proposal or its patch.

## Local inputs, read only

| Input | Path and purpose |
|---|---|
| Exact 23G90 QuartzCore | `research/ios26-gpugl-r1/x/QuartzCore`; local execution oracle and generated hashes/offsets |
| Matching local instruction listing | `research/ios26-root-r1/apple/dis/QuartzCore.s`; preparer verifies the self-contained axis leaf |
| Existing PAC rewriter | `research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py` and sibling `renegade_platform.py`; invoked/imported in place, not copied; no licence inferred for this external tree |
| Existing overlay writer | `research/ios26-overlay-r1/tools/mkoverlay.py`; imported in place, not copied or relicensed |
| Actual XNU consumer headers | `research/ios26-release-r1/work/xnu/bsd/{miscfs/ramfs/varfs_overlay.h,miscfs/ramfs/varfs_tsv.h,kern/hk_exec_rules.h}`; compiled in place with BLAZER=1, no vendor context copied |
| Existing p29 RAM overlay | `research/ios26-gpugl-r1/phone/p5-merged-r2-gltrack.ovl`; SHA256 `61c38161efd809bdac15f9f167e5431a4f116b54bf42c7280411480fa37bea2a`; includes Apple artwork, never tracked |

Exact reference SHA256 is
`8836d8c530ff926cc2e2b44e74b444aba114774d1fe85818f18a9a7cb9f1defc`,
QuartzCore UUID `8f1e0b3f-add6-3710-a790-009333597ab4`. Axis function
`0x184129a9c`, size 256, SHA256
`1505a7e350ebecd68df9600cc1fb5a8d37933f61de08e4c0180e48ca8a24fcc3`;
projective function `0x184129684`, size 772, SHA256
`8082bfa8c775a36883659cf6ea532ef475a783c1277fcffc4d63f418f5acb560`.
Format1 table is `0x1ee985ce0`; axis slot 10 is `0x1ee985d30` and slots 12..15
point to the projective original. These are facts, not copied implementation.

`tests/differential.c` requires the local binary filename as its sole argument.
It validates fingerprints and maps that local file's complete text segment in
host memory, preserving the original instructions, constants and ADRP layout.
It never embeds or saves the oracle machine code. Its synthetic pixel data is
owned test input, not captured Apple artwork. The existing projective binary32
rounding counterexample remains in the unmodified test. The package imports no
libyuv/pixman renderer or alternate numerical reference.

Local dependencies, command arrays and exact hashes are recorded by each build
in ignored `receipts/build.json`. Their availability is a reproduction
prerequisite; the source-only patch does not distribute these dependencies.

## Review and physical evidence, not a new test

Original reviewer handoff:
`research/ios26-fleet/handoffs/opt-sampler_review.md`. Verdict: no code findings;
147 extra actual-original geometry/fallback cases plus wrapper/latch checks
passed. Review evidence: `research/ios26-opt-20261102/sampler_review/checks.json`.
The reviewer did not establish physical performance or projective coverage.

Physical VERIFY attempt: `20261102-110205-sampler-verify-p29-r1`.

- Image: `research/ios26-bootchain-r1/run/sampler-verify-p29-r1/boot.img`, SHA256
  `02b99c9554d504be6a0b072cafd1752b35e0d68c4c7629dff79f76275ec69b52`.
- p29 kernel SHA256
  `5aad89780e798d730aa00372dd17568917cc81d97fc231df0fcf1a9fda80fca8`;
  unstripped SHA256
  `cc97915354f63c1253bd84295dd5ba004b864bb336a82dd2bcffbf3eb57631cc`.
- Original signed dylib: `research/ios26-opt-20261102/sampler/build/hsampler.dylib`,
  SHA256 `b89c2a350d7e6f61fd2d2a075362856da1f2600790106102a9cbd1966b86b197`.
- VERIFY overlay:
  `research/ios26-opt-20261102/sampler/artifacts/sampler-verify-0a8046ad2822.ovl`,
  SHA256 `0a8046ad28223fa7a5f70a7da6362dbbfabb375f5be3e0a3af13a5f1a49e6096`.
- Raw live stream: `research/ios26-opt-20261102/parent/sampler-verify-p29-r1.raw`,
  SHA256 `5f489c28dbd11bbd2dca6d6a042159047a060f7eea4a2db0e8d6bbd1b73d8a2a`;
  associated `.times`, `.raw.json`, `-events.jsonl`, `-profiler.json` and
  `-final.json` are in the same parent directory.
- RAM log:
  `research/laguna-usb-fix/attempts/20261102-110205-sampler-verify-p29-r1/ramdump/kernel.log`,
  SHA256 `0184107434bcafd022484c399048e54517b8334f720cc290c7cdf0ec8107de18`.

The final complete live sampler record reports 598,888,390 verified full-span
pixels, 594,003,511 eligible interiors, mismatch=0/latch=0/verify_long=0 and
projective identity=0. Constructor installed once, selfcheck PASS/reprotect=0.
The coordinator reports no backboardd abort/push_surface failure, complete
66-token/1569-event script, working Home/Settings and unchanged visual issues.
Input callback/dispatch timings are not glass latency. The expected 300s deadline
ended this attempt; packaging performed no new device operation.

The 2,588,366 live bytes have zero reported loss, but RAM wrapped. Coordinator
head+tail comparison covers 2,096,461 bytes with 0 mismatches; 491,905 bytes are
live-only and 662 final dump bytes were not received live. The strict canonical
profiler verifies only 1,047,914 bytes in the current tail epoch. Do not label
the entire live file RAM-verified. Physical projective specialization coverage,
OFF/FAST performance and visible latency remain pending. No speed claim.
