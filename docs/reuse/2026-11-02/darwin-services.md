# Darwin services and networking reuse audit

Audited 2026-11-02. Research only: no build, guest, phone operation or runtime
change. Source pins were checked with public Git refs and the linked raw files.
Nothing here establishes faster startup, network connectivity or a fixed crash.

The largest immediate saving is a **tested service-profile planner**, followed by
**network service contract diagnostics**. Replacing the system daemons or
CoreFoundation would add substantial incompatibility work.

## Current local evidence and work already owned

- `research/ios26-opt-20261102/boot_services/src/hk_container_ready.c` already
  implements an opt-in, bounded retry around the real container-path call.
  Do not create another nil-path interposer or substitute a fabricated path.
- `research/ios26-fleet/handoffs/crashes.md` traces the early backboardd nil URL
  to a null `container_system_path_for_identifier` result. A startup race is an
  inference; permission, metadata and persona failures have different remedies.
- `research/ios26-fleet/handoffs/overlay_perf.md` already has an overlay that
  restores cloudd alone, with host validation and an explicit unrun guest A/B.
  Its cited old guest has repeated failed lookups, not proof restoration helps.
- The physical profile records high Spotlight and CPU renderer costs. A daemon
  name/CPU total alone does not identify indexing, rendering or retry causation.
- `BlazerNetServices.cpp` already publishes the single shared IONetworkStack
  discovery service. `BlazerWiFiServices.cpp` publishes an en0 registry object
  only after actual `ifnet_attach`; neither should be duplicated.

## 1. Reuse vphone's service selection and ownership bookkeeping

**Priority P0; high confidence in code reuse, unproved performance benefit.**

Verified [vphone-cli fd1610d7928aacd6cbc060722bb27fd7d2c76315](https://github.com/Lakr233/vphone-cli/tree/fd1610d7928aacd6cbc060722bb27fd7d2c76315),
with its [MIT licence](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/LICENSE).
The useful file is
[GuestServiceProfile.swift](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/VPhoneDaemon/Daemon/GuestServiceProfile.swift).
Its `select`, `reconcile`, `owned(after:)` and versioned `Record` separate planning
from execution and preserve responsibility for changes. Its `base26` targets
23G90; its `neverDisable` records dependencies observed on the author's VM.

**Concrete reuse:** adapt these pure functions and their existing
[host logic tests](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/VPhoneDaemon/Tests/run-logic-tests.sh)
into our overlay-generation workflow. Retain MIT notices. Avoid importing its
VM management or daemon installation machinery.

**Local seam:** current overlay tooling edits disabled.plist and validates blob
checksums, but this audit found no equivalent ownership-aware planner in the
reviewed overlay/boot-services directories. The cloudd candidate is already
implemented; the reusable improvement is enforcing and documenting future diffs.

**Smallest host proof:** feed the planner the actual selected overlay's labels,
a recorded baseline, and a proposed change. Verify unknown OS/group rejection,
dependency conflicts, sorted deterministic output, failed-enable ownership and
rollback that touches only this change's labels. Preserve unrelated records
byte-for-byte. This can run entirely against fixture plists.

**Limits:** its dependency findings are evidence from a different VM. Some keep
rules serve vphone features absent here; some of our hardware owners require
different choices. Use conflicts as review inputs, not an automatic enable list.
The upstream CPU/memory figures do not predict our phone. Benefit is less manual
list comparison and fewer dependency regressions; actual speed needs an A/B.

## 2. Reuse Apple's network naming contract, after observing a request

**Priority P1 diagnostic; high confidence in source gap, conditional runtime relevance.**

Verified [configd 585b7f2fca293f4642d21d15c5daf187f63c4796](https://github.com/apple-oss-distributions/configd/tree/585b7f2fca293f4642d21d15c5daf187f63c4796).
Its APSL-2.0
[InterfaceNamer/ifnamer.c](https://github.com/apple-oss-distributions/configd/blob/585b7f2fca293f4642d21d15c5daf187f63c4796/Plugins/InterfaceNamer/ifnamer.c)
contains `registerInterfaceWithIORegistryEntryID`: a command number, an eight-byte
registry-entry ID and interface unit are passed through `IOConnectSetCFProperties`.
`stackCallback` acquires the shared stack connection. These are concrete protocol
details we do not need to reconstruct manually.

The corresponding
[IONetworkStack.cpp](https://github.com/apple-oss-distributions/IONetworkingFamily/blob/bb910e2b458939f6b1f53c0fa6907f258b431ea4/IONetworkStack.cpp)
at verified IONetworkingFamily `bb910e2b458939f6b1f53c0fa6907f258b431ea4`
defines a user-client `setProperties` forwarding path and a provider-side parser,
real interface lookup, naming dispatch, retention and privilege checks.
**That file explicitly carries APSL-1.1, not APSL-2.0.** Treat it as a contract
reference unless its terms are deliberately handled; preserve per-file notices
if source is reused. Do not label the whole family permissively licensed.

**Observed local difference:** p29's `BlazerNetServices.cpp` has no `setProperties`
override; its `externalMethod` returns Unsupported. The inherited
`IORegistryEntry::setProperties` also returns Unsupported. Publishing the class
therefore does not implement the above naming request.

**Important qualification:** en0 is already given its name and unit in the local
Wi-Fi registry publisher. InterfaceNamer may accept an already-named interface
without issuing registration. No current capture in this audit proves this gap
blocks en0 or causes a wait. The public configd pin is a contract reference,
not proof its implementation is byte-identical to the phone's daemon.

**Smallest task:** instrument the existing shared service to record request
operation, argument types and result without changing behavior. Build a host
dictionary fixture from the published contract. Only if a real request is seen,
add the necessary handler bound to the retained, actually attached interface.
Reject wrong-size IDs, foreign/stale entries, conflicting units, unsupported
commands and unauthorized callers; exercise detach during a request.

**Do not** report success by setting registry strings alone, rename an attached
BSD interface behind its owner, bypass caller checks, or add a second stack for
USB. Coordinate with the Wi-Fi/USB owners. Reuse saves protocol discovery and
failure-case design; a complete IONetworkingFamily import is unnecessary.

## 3. Reuse read-only SystemConfiguration and DNS-SD probes

**Priority P1 after a real interface exists; high diagnostic confidence.**

The same configd pin provides APSL-2.0
[scutil commands](https://github.com/apple-oss-distributions/configd/blob/585b7f2fca293f4642d21d15c5daf187f63c4796/scutil.tproj/commands.c)
and [SCD.c](https://github.com/apple-oss-distributions/configd/blob/585b7f2fca293f4642d21d15c5daf187f63c4796/SystemConfiguration.fproj/SCD.c).
Reuse the `open`, `list`, `get` and `show` workflows as a small read-only probe,
using the system framework instead of replacing configd or writing store values.

Verified [mDNSResponder d4658af3f5f291311c6aee4210aa6d39bda82bbe](https://github.com/apple-oss-distributions/mDNSResponder/tree/d4658af3f5f291311c6aee4210aa6d39bda82bbe).
[dnssd_clientstub.c](https://github.com/apple-oss-distributions/mDNSResponder/blob/d4658af3f5f291311c6aee4210aa6d39bda82bbe/mDNSShared/dnssd_clientstub.c)
is BSD-3-Clause and supplies asynchronous connection/result handling, including
daemon/version errors. Prefer calling the existing `DNSServiceGetAddrInfo` and
`DNSServiceProcessResult` APIs in a tiny diagnostic rather than vendoring a second
resolver. Its
[dns-sd.c](https://github.com/apple-oss-distributions/mDNSResponder/blob/d4658af3f5f291311c6aee4210aa6d39bda82bbe/Clients/dns-sd.c)
is a useful CLI example but carries its own Apple sample-code licence; it is not
covered automatically by the client's BSD notice.

**Concrete seam:** produce one staged receipt: real ifnet/link state → configd
interface state → assigned address/route → resolver configuration → a bounded
DNS result. This distinguishes working packets from system service discovery
and DNS readiness, avoiding a misleading single “network works” result.

**Host proof first:** use fixture store dictionaries and recorded result/error
events to test the receipt's ordering and bounded timeout/cancellation. A Mac
probe can establish API linkage only. Later guest/physical tests must query the
guest's real store and interface, and separate local discovery from Internet DNS.

**Limits:** no interface, DHCP lease, route or resolver can be conjured by these
probes. The current public `mDNSMacOSX/mDNSMacOSX.c` URL returned 404 at this pin;
the portable collection is not a complete modern iOS platform replacement.
Reuse saves custom diagnostic/parsing work, not the remaining Wi-Fi/USB backend.

## Negative findings and tasks to avoid

- [Darling configd 98e52de19c52f7938e581ed20385f38abd7fa197](https://github.com/darlinghq/darling-configd/blob/98e52de19c52f7938e581ed20385f38abd7fa197/SystemConfiguration.fproj/CMakeLists.txt)
  explicitly builds framework stubs. Its
  [top-level build](https://github.com/darlinghq/darling-configd/blob/98e52de19c52f7938e581ed20385f38abd7fa197/CMakeLists.txt)
  substitutes a resolv.conf reader for dnsinfo. This is Linux compatibility glue,
  not a tested iOS26 configd/network-state implementation. Apple's inherited
  SCD.c is APSL-2.0; separate Darling changes need their own licence audit.
- Apple's public launchd main `d448a1c8f70a61202f8705f94337f686b87c30c4`
  resolves to tag launchd-842.1.4; public 842.92.1 is also a legacy line. Its
  [Apache-2.0 source](https://github.com/apple-oss-distributions/launchd/blob/d448a1c8f70a61202f8705f94337f686b87c30c4/src/launchd.c)
  is not a drop-in replacement for iOS26 launchd/XPC/private service contracts.
- Apple's CF main `dc54c6bb1c1e5e0b9486c1d26dd5bef110b20bf3` is CF-1153.18.
  Its [APSL-2.0 CFURL.c](https://github.com/apple-oss-distributions/CF/blob/dc54c6bb1c1e5e0b9486c1d26dd5bef110b20bf3/CFURL.c)
  cannot fix BaseBoard's missing container path. Replacing Foundation/CoreFoundation
  or accepting null paths would obscure the actual dependency failure.
- [Libnotify 715d461778f6b93c821d99390a0078bd6f6d8c04](https://github.com/apple-oss-distributions/Libnotify/blob/715d461778f6b93c821d99390a0078bd6f6d8c04/notify_client.c)
  exposes APSL-2.0 `notify_register_dispatch`/bootstrap behavior for diagnostics;
  there is no evidence the existing notifyd needs replacement. Event correlation
  is useful after a specific missing notification is identified.
- No public `apple-oss-distributions/libnetwork` README was found at the tested
  URL. That limited negative result does not establish absence of every source;
  it provides no basis for a Network.framework replacement recommendation.
- Disabling Spotlight, cloudd, CommCenter or container services is not justified
  by this audit. Correlate sampled stacks, failed endpoints and comparable CPU
  windows, then test one reversible change with its dependent clients alive.

Recommended order: reuse the planner on host fixtures; complete the already-owned
container/cloudd experiments; record real naming calls; add staged network probes
when packets and the actual interface backend are ready.
