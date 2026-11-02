# Development tooling reuse audit — 2026-11-02

Scope: build checks, boot/capture analysis, symbolication and QEMU host tooling.
This is source inspection, not a build, test run, emulator run or phone result.
No implementation, firmware, Apple artifacts, device data or identifiers were imported.

The best savings come from extending existing tools at three narrow seams:
per-file object acceptance, QMP event handling and reproducible symbolication.
The project already has much of the infrastructure usually proposed for a new port.

## Existing work to keep

Inspected local sources:

- `research/ios26-release-r1/tools/release.sh` and `verify.sh` prove the pristine
  tarball, combined patch and ordered patch series produce the expected tree.
- `stage.sh` checks ARM64, undefined symbols, symbol additions/removals,
  strings and selected disassembly against `expect.tsv` after the full link.
- `precheck.py` replays recorded per-file compiler arguments and requires BLAZER=1.
  It currently records compiler success without checking the emitted object's
  expected text symbols. The post-link acceptance is stronger than this local check.
- [`tools/bootios`](../../../tools/bootios) already compares the kernel UUID with
  the supplied image and records image/kernel hashes before invoking the runner.
- [`tools/usbcon.py`](../../../tools/usbcon.py) already journals byte ranges and
  supports comparison with the RAM capture; do not replace its proven transport.
- The active `ios26-opt-20261102/live_analysis/proposal/tools/live_profile.py`
  already reconstructs epochs/ring overlap, preserves gaps, tracks script timing,
  resolves cache image ownership, and checks QuartzCore disassembly bytes.
  Its label resolver is deliberately limited; it does not invent missing symbols.
- QEMU direct-loader, overlay, graphics and mux harnesses already use QMP,
  sparse file-backed memory, root hashes and cleanup. Their small copied QMP
  client reads until its reply ID and discards intervening event messages.
- CI already exercises host tools without the ignored research inputs. Some
  required local build fixtures cannot run on a clean clone; that is documented.

## 1. LLVM object inspection and FileCheck

**Priority P0; high confidence; direct reuse of installed host executables.**
Verified source reference: LLVM `llvmorg-21.1.0`, peeled commit
`3623fe661ae35c6c80ac221f14d85be76aa870f1`; not a claim that this is the newest
LLVM or the version installed on the owner’s machine.

The [Mach-O dumper](https://github.com/llvm/llvm-project/blob/3623fe661ae35c6c80ac221f14d85be76aa870f1/llvm/tools/llvm-readobj/MachODumper.cpp#L422)
already implements headers, sections and symbol interpretation, including
`MachODumper::printSymbols`/`printSymbol`. [FileCheck](https://github.com/llvm/llvm-project/blob/3623fe661ae35c6c80ac221f14d85be76aa870f1/llvm/utils/FileCheck/FileCheck.cpp)
supplies named check prefixes, ordered checks and negative checks; the
[lit runner](https://github.com/llvm/llvm-project/blob/3623fe661ae35c6c80ac221f14d85be76aa870f1/llvm/utils/lit/lit/TestRunner.py#L2300)
can execute those short host command sequences if their number later warrants it.
These files carry Apache-2.0 WITH LLVM-exception notices.

Integration seam: extend per-file precheck receipts with compiler version,
complete gate arguments, source/object hashes, target architecture and the
required symbol’s section/type. Reuse `llvm-readobj --file-headers --sections
--symbols`, `llvm-nm` and existing objdump rather than writing a Mach-O reader.
FileCheck is optional; a small verifier can consume the existing output first.
Do not rebuild LLVM or replace the XNU makefiles to obtain this benefit.

First task: select one existing BLAZER-gated C file, replay its recorded ARM64
compile and require a named implementation symbol in executable text. Add a
negative case with the gate disabled and another with an unexpected symbol.
Accept only when the enabled object passes and both inappropriate acceptance
cases fail. Preserve the full-link `stage.sh` checks as the final kernel gate.

Missing dependency: each feature owner must declare real expected implementation
symbols; a generic symbol such as a common stub is insufficient. Command output
must be tested against the actual installed LLVM/Apple tool version. In this
source reference JSON output is an ELF-style option; do not assume portable
Mach-O JSON output exists.

Labour saved: repeated hand-written architecture/nm/disassembly checks become a
single reusable per-file contract, catching empty guarded translation units
before a full kernel link. It does not prove runtime hardware behavior.

## 2. Official qemu.qmp client for the existing harness

**Priority P1; high confidence in the transport/event gap; host-only dependency.**
Verified current official GitLab commit:
`82006cb788d27b090a8b84fc7831feb9c528bcdc` (2026-03-30).
The [QMPClient implementation](https://gitlab.com/qemu-project/python-qemu-qmp/-/blob/82006cb788d27b090a8b84fc7831feb9c528bcdc/qemu/qmp/qmp_client.py)
provides command IDs, connection lifecycle and execution error handling.
[EventListener and Events.listener](https://gitlab.com/qemu-project/python-qemu-qmp/-/blob/82006cb788d27b090a8b84fc7831feb9c528bcdc/qemu/qmp/events.py)
preserve and filter asynchronous messages independently of command replies.
The package [licence declaration](https://gitlab.com/qemu-project/python-qemu-qmp/-/blob/82006cb788d27b090a8b84fc7831feb9c528bcdc/qemu/qmp/__init__.py)
is LGPL-2.0-or-later; other bundled command-line tools have different GPL terms.
Use the library as a host dependency; do not copy the optional shell utilities.

Local counterpart: the same synchronous `QMP.call` pattern exists in
`ios26-qemu-r1/tools/run.py`, `ios26-overlay-r1/tools/qemu-ufsroot.py`,
`ios26-gpugl-r1/tools/qemu-ufsroot.py` and `ios26-debug-r1/tools/qemu-mux.py`.
QMP itself is already in use. The gain is preserving events and sharing one
tested client adapter, not introducing another VM manager or replacing loaders.

First task: wrap one existing harness's QMP seam, retaining its single-guest
lease, root hashes, exact command line and cleanup. Record STOP, RESET,
SHUTDOWN and command errors in an attempt-local journal with host timestamps.
Keep the guest console as the source of XNU panic/acceptance information;
QMP events alone cannot tell whether an XNU feature worked.

Smallest host proof needs no guest: an in-process fake QMP endpoint sends a
greeting, an event interleaved with a matching reply, a command error and EOF.
Require the event and reply both survive, errors propagate, and disconnect
completes. Then replay representative existing protocol transcripts.
An actual QEMU smoke run remains a later coordinator-owned validation step.

Dependencies: Python asyncio integration and the package’s supported Python
version; its core declares Python >=3.8 and no mandatory external runtime
dependencies at this pin. QMP vocabulary depends on the running QEMU version,
so feature-detect commands and retain the existing loader’s compatibility.
QMP event timestamps are host event times, not guest frame latency. Some QMP
events are rate limited; the journal is not a complete instruction trace.

Labour saved: fewer manual investigations of whether a guest stopped, the
monitor disconnected or a host runner failed; less duplicated protocol code.
No Tensor hardware emulation or physical acceptance is supplied.

## 3. ipsw symbolication: reuse the resolver, preserve missing-data failures

**Priority P1 after resolving input completeness; high confidence in limitation.**
Verified `blacktop/ipsw` master at
`a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388`, root MIT licence.
The current [a2s command](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/cmd/ipsw/cmd/dyld/dyld_a2s.go#L103)
uses `DirectLookupSymbol` for a single address without a global `.a2s` index.
The [resolver](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/internal/commands/dsc/dsc.go#L390)
already handles containing-image lookup, function boundaries, export/symtab
names, available local symbols and stubs. Generated function labels are not
recovered source names.

Critical negative result: [dyld.Open/openSubCaches](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/pkg/dyld/file.go#L347)
still requires a referenced `.symbols` member to open successfully. Updating
ipsw or omitting `--cache` does **not** fix the current handoff's absent-symbols
blocker. Runtime subcache UUID mismatches must also remain hard failures.

Local overlap: older `ios26-overlay-r1/tools/{pc-profile,hog-sym,hk-sb-read}.py`
launch ipsw per unique PC; the new live analysis worker already resolves image
ownership without `.symbols`. Do not replace that conservative fallback.

First task: add an explicit symbol-source manifest to that worker: cache and
subcache UUIDs/hashes, slide, tool version, symbol-file availability, label
source and whether an output is a real symbol, function boundary or image only.
Test wrong-cache and missing-symbol inputs using synthetic fixtures first.
For a complete legitimate cache family, batch unique PCs in one local helper
and memoize results; no HTTP service is needed.

Missing dependency: a matching symbols member from the owner’s legitimate
inputs, or a separately tested opt-in partial-cache reader. A partial reader
must preserve required runtime-member/UUID checks and explicitly disable local
symbol lookup when absent. It is a development task, not an available upstream
switch. The resolver lives in Go `internal/`; an external module cannot simply
import it. Use CLI calls or a small maintained upstream-module helper, retaining
MIT notices if code is copied. Apple cache bytes and derived dumps stay ignored.

Labour saved: repeated image/slide/name lookups and stale-cache mistakes;
available export and function metadata reduce manual disassembly. It cannot
recover names stripped from the available inputs. The assets audit covers
ipsw's CAR tooling separately.

## 4. Hypothesis for byte-journal and parser sequence tests

**Priority P2; high confidence in fit; optional host test dependency.**
Verified upstream master `30f73af87f587b6911042552e24f1dea2577988a`.
The [state-machine engine](https://github.com/HypothesisWorks/hypothesis/blob/30f73af87f587b6911042552e24f1dea2577988a/hypothesis/src/hypothesis/stateful.py)
provides `RuleBasedStateMachine` and `run_state_machine_as_test`; the
[strategy source](https://github.com/HypothesisWorks/hypothesis/blob/30f73af87f587b6911042552e24f1dea2577988a/hypothesis/src/hypothesis/strategies/_internal/core.py#L981)
provides bounded binary data and lists. Both carry MPL-2.0 notices. This is a
source pin, not a request to install an unreleased head; select a supported
release before adoption. This source requires Python >=3.11.

Concrete seam: the live analysis worker’s Journal/Analyzer input contract.
Generate the same valid record stream in arbitrary byte chunks, journal gaps,
truncated final records, replacement epochs and non-finite timestamps. Compare
with a small independent byte-range model and require identical accepted events
for equivalent chunking; require explicit refusal or gaps for invalid inputs.
Shrinking supplies a small reproducer instead of hand-trimming a large capture.

Keep existing regression, mutation and ASan/UBSan tests. Property generation
does not validate a device protocol or GPU model merely by agreeing with that
same implementation. No proprietary capture is needed in public test fixtures.

## Work order and limits

1. Extend per-file object acceptance using existing LLVM tools and explicit text
   symbols, before requesting another full kernel link.
2. Preserve QMP events in one existing harness; prove the adapter on a fake socket.
3. Adopt the live analysis worker's source-identity/fallback contract and batch
   symbol lookup only when legitimate input completeness permits it.
4. Add Hypothesis only for parser/state sequences that manual regressions do not cover.

Generic XNU build wrappers, another boot runner, libvirt, a wholesale QEMU fork,
or DWARF tools alone would not remove the present bottlenecks. `dsymutil` and
`llvm-symbolizer` can use debug information that exists; they cannot manufacture
missing Apple debug symbols or emulate Tensor devices. No speedup is measured
or promised by this audit. Inspection used targeted local reads, primary docs,
pinned raw source and remote reference queries; no build/boot was run.
