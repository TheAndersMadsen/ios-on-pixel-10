# crashdoc: crash census over phone boot dumps (2026-11-03, HOST tool run on PHYS logs)

`tools/crashdoc.py` finds every crash-like event in boot dumps, splits each dump into boots, symbolicates the frames
against the dyld cache, groups the crashes by signature across attempts and attaches the known causes. Host only, standard
library, no device access. Evidence: the inputs are phone ramdumps and live consoles (PHYS). The names come from host
symbolication of dsc-r6. The cause hints come from today's findings (cited per hint) and are inferences unless the cited
document says otherwise.

Outputs of today's run: [`crashes.md`](crashes.md) (tables + per-signature frames) and [`crashes.json`](crashes.json)
(schema `crashdoc/1`).

## Use

```
python3 -I tools/crashdoc.py ATTEMPT_DIR|PARENT_DIR|LOG ... [--out DIR] [--json] [--cache DSC] [--no-symbols] [--print]
python3 -I tools/test_crashdoc.py                      # host tests, synthetic logs (13 cases; 1 needs dsc-r6)
```

- An attempt dir is read as `ramdump/kernel.log`, else `kernel.log`, else `console.txt` (tools/live_boot.sh), else
  `markers.txt` (only its `LIVEBOOT ... CRASH <proc>` lines). `reader.txt` gives the TSHIMST2 nonce, the verdict and the
  msgbuf tail. `markers.txt` gives `CONSOLE_CONNECTED nonce`. `meta.txt` gives `started:`. A parent dir means every child with a log.
- `--json` prints crashes.json on stdout and writes no files unless `--out` is given. Without `--json` the files go to `--out`
  (default `.`). This is the entry for hk_cycle and `hk crash` on a run dir. `crashdoc.run(paths, cache)` returns
  `(doc, markdown)` for in-process callers.
- Default cache `/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e` (uuid 0f1ee332). Without a cache, or with
  `--no-symbols`, frames keep their unslid addresses and signatures stay the same, but frames have no names.
- 26 logs (today's attempts) take about 43 s on m1box. One attempt takes about 2 s.

## What it does

1. **Events.** `usertrap:` header with its `called from` and `xN ->` lines. `userabort:` plus the `|proc| *** Terminating app`
   reason and `First throw call stack`. Frame lists cut by interleaved console text are rejoined, and a hex token glued to the
   next message is cut back to 9 digits. launchd `exited due to` / `exited with exit reason`. `exec: SIGKILL to ... reason
   namespace` (runningboard watchdogs). `CRASH <proc> reason ns 2 code <signal>` as its own event when no trap or abort precedes
   it (int1 and live boots run without hk_usertrace); the preceding `EXC_GUARD AST` line gives it a pid. Kernel `panic(cpu`.
   `HKMAIN: stall` + `HKMAIN: frames`. `Assertion failed`, `BUG IN CLIENT OF`, Swift `Fatal error`.
2. **Boots, never mixed.** A ramdump is a ring holding the newest boot first, then older boots and Android. The 4 MiB file
   also holds it twice (console zone and pmsg msgbuf mirror). Each NUL-separated region is cut into fragments at:
   - a banner (`TEGU-XNU STAGE0`, `Darwin Kernel Version`, `Linux version`);
   - a change of dyld slide (`shared cache slide`, `dsc_slide`, HGLTRACK/HKACCEL `slide`, HK USTACK `slide=`);
   - a launchd clock jump (back > 60 s or forward > 30 min). Whole-hour jumps are time-zone changes, so r9's 17:51 → 09:51 is
     not a cut;
   - the first userland line after a `panic(`. A panic ends its boot: gpu2's 462-line boot had absorbed dbg5's residue.
   Fragments with > 10 % non-printable characters (binary records, decayed RAM such as `installed-ios-crash`) join no boot.
   Fragments join into one boot when they share the slide or an exact unique line (launchd line with µs stamp, panic line,
   usertrap header, HKMAIN stall). A fragment without a slide also joins when its launchd times touch exactly one slid boot from
   the same file. **Two different slides never join.** The attempt's own boot is the fragment holding reader.txt's last
   msgbuf-tail lines. Without a reader, it is the banner fragment at line 1, or the largest fragment of a live console. Only
   that boot gets the attempt's nonce. **The nonce is per image, not per boot**: int1 (ramdump) and the 21:39 live boot share
   0x8bc64d7181cbb83c with different slides. Events are de-duplicated per boot, so mirror copies and residue in later dumps
   count once. Ordering uses the median launchd time (1970 stamps ignored), else the attempt start (UTC).
3. **Symbols.** unslid = addr − slide, the containing image (`tools/live_profile.py` CacheImages), and the function start from
   LC_FUNCTION_STARTS. The start is named by its exported nlist, else by `LOCAL_NAMES` (today's disassembly:
   Display_lut 0x1e2746810, Display_init 0x1e2741c1c, the BaseBoard caller 0x19075c400, the libsystem_platform compare
   0x2a440b050), else `func_<start>` with the nearest export. `<redacted>` nlists are skipped. Return addresses are looked up at
   addr − 4. Main-binary frames are `Proc+off` from `main header`, or from 0x100000000 + `main_slide` for HKMAIN. The
   function starts match the findings exactly: 0x1e2746924 is Display_lut+0x114, the lr is Display_init+0x67c, and
   0x2a4413fac is `_sandbox_extension_consume`+0x24 (test `test_real_cache_local_function_names`).
4. **Signatures.** kind + process + unslid culprit:
   - usertrap: the pc;
   - userabort, throw stack, stall: the first frame outside libsystem_*, libc++abi, libobjc, CoreFoundation, Foundation,
     libdispatch and libswiftCore (aborts with lost frames are `@frames-lost`);
   - CRASH: the exact `ns`/`code`; kill: killer, namespace and code; panic / message: the message with numbers normalised.

   An exit within 200 lines of that process's trap, abort or CRASH is `exit-of-crash` and is not counted as a separate crash.
   Counts are distinct pids per boot. Status is one of:
   - `open (latest boot)`;
   - `not seen since: N later boot(s) ran <proc> without it` (`likely fixed` from N ≥ 2);
   - `not exercised since`.

   It also adds `but <proc> still fails later as ...` when the process crashes later under another signature. A vanished
   signature is not a fix if the process still crashes.
5. **Known causes** (`HINTS`). Each signature lists the hints matched by any of its events (`matched/of`). A hint can require
   a kind, process, culprit, any-frame location, a frame symbol, a message, or a context string in the 30 lines before (e.g.
   `generic_extension="invalid"`).

| hint id | match | cause (source) |
| --- | --- | --- |
| corebrightness-calibration | usertrap with frame 0x1e2746924 | AppleARMBacklight (hk_bright=140) lacks calibration → NULL marketing table (`corebrightness/FINDINGS.md`) |
| mobilephone-contacts-tcc | MobilePhone pc MobilePhone+0x1e2bc0 | Contacts TCC: CNContactStore nil, force-unwrap (`ios26-apps-r1/crashes-r9/FINDINGS.md`) |
| preferences-sandbox-token | Preferences usertrap through `sandbox_extension_consume` | NULL token, Sandbox op 5 ENOENT; fix F1 (same) |
| configd-ionetworkstack | any frame `_SCDynamicStoreNotifyWait` | InterfaceNamer waits for IONetworkStack / 300 s (`configd/FIX.md`) |
| backboardd-nsurl-container | reason `initFileURLWithPath:]: nil string` | BaseBoard container path NULL (`ios26-apps-r1/receipts/l1-r16/LANE1.md`) |
| preferences-launch-watchdog | Preferences + `8badf00d` | runningboard launch watchdog; see configd (`configd/FIX.md`) |
| about-preferences-medialibrary | Preferences SIGABRT with kTCCServiceMediaLibrary / `generic_extension="invalid"` in the 30 lines before | Settings > About abort after tccd's MediaLibrary answer (ABOUT, int1; coordinator update) |
| axui-punctuation-model | AccessibilityUI* abort / CRASH / exit | root prune deleted AXSSPunctuationModel.momd (ABOUT, int1; coordinator update) |
| blastdoor-sandbox-check | MessagesBlastDoo* | Sandbox.swift fatalError after sandbox_check; SWEET stub returns 0 (ABOUT, int1; coordinator update) |
| blazer-deadline | panic `blazer-root: deadline` / `boot ended on purpose` | intended end of boot, not a crash (`A7.md`) |

## crashes.json schema `crashdoc/1` (stable)

Every key below is always present (null / empty when unknown). New keys may be added, and existing keys keep their meaning.
`signatures[].id` is `sha1(sig)[:10]`, which stays the same across runs and input sets. The `S##` numbers in crashes.md are
display order only.

- `schema`, `tool`, `cache {path, uuid, error}`
- `summary {sources, boots, signatures, crash_signatures, open: [id], unexplained: [id]}`. `open` = crash signatures in the
  latest boot that ran the process; `unexplained` = crash signatures with no hint.
- `sources[] {attempt, path, sha256, nonce, verdict, own_boot, boots: [boot id], fragments, decayed_fragments,
  own_crashes: [{id, sig, kind, proc, count, new, hints: [hint id]}]}`. `own_crashes` = the crash signatures of this run's
  own boot; `new` = first seen in that boot. This is what hk_cycle and `hk crash` should read.
- `boots[] {id, label, os, slide, nonce, current_in, seen_in, time, fragments: ["attempt:first-last"], decayed,
  boot_args {cpus, blazer_deadline, hk_bright, rd, blazer_usbnet, blazer_wifi_net, hk_container_ready}, events}`. Boot ids
  `B##` are per run (chronological), so do not store them across runs; use `slide` + `time`.
- `signatures[] {id, sig, kind, proc, crash, culprit, incidents, boots {boot id: pids}, first, last, status, also: [sig],
  hints: [{id, cause, ref, matched, of}], example, refs: ["attempt:line"]}`. `kind` is one of usertrap, userabort, crash,
  stall, kill, exit, panic, message.
- `example` (one event) `{kind, proc, pid, label, ref, ts, slide, main, exception, code, crash_reason, reason, message, why,
  benign, linked, stall_ms, regs, guard, context, boot, frames: [frame], throw: [frame], culprit: frame}` and
  frame `{addr, unslid, loc, text, image, func, how, nearest}`. `how` is export, known-local, function-start or nearest-export.

## Run receipt (2026-11-03 22:04, m1box)

- Command: `python3 -I tools/crashdoc.py research/laguna-usb-fix/attempts/20261103-* research/laguna-usb-fix/attempts/live-20261103-* --out research/ios26-phaseb-r1/crashdoc`
- Inputs: 26 logs. These are the 20 ramdump attempts of 2026-11-03, `installed-ios-crash` (decayed RAM, 66 of 68 fragments
  rejected), `213511-a7-int1-dbg` and `214001-a7-int1-live` (binary only, 0 boots), and 4 live consoles. Result: 39 boots,
  59 signatures, 31 crash-like, 19 without a known cause. Per-input sha256 in `crashes.json` `sources[]`.
- Tool sha256: `crashdoc.py` b54b4faf…e719, `test_crashdoc.py` fc0b610e…4d73. Outputs: `crashes.json` d668d22e…ee6b,
  `crashes.md` 645be833…1430.
- Tests: `python3 -I tools/test_crashdoc.py` → 13 tests OK, including the real-cache case.
- Cross-checks against the findings (PHYS logs):
  - r1 / r2 CoreBrightness traps: 7 / 9 distinct pids. These are the 14 / 18 trap lines of FINDINGS, halved for the mirror copy.
  - r9 MobilePhone ×3.
  - The Preferences SIGSEGV is wifi-join-r2's, as residue in r9's dump, not r9's.
  - The wifi-join-r2 watchdog has **5** pids (149, 156, 180, 189, 197); crashes-r9 counted 4 because pid 197 is only in the
    pmsg mirror copy.
  - r10's configd stall is Preferences → SystemConfiguration func_1af2c3148 (`__waitForInterfaces` area) with
    `_SCDynamicStoreNotifyWait` in the chain.

## Today's signature table (crash-like, by incidents)

| id | kind | process | culprit / message | n | boots | first → last | status | known cause |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1a4726cb12 | userabort | AccessibilityUIS | CoreData func_185bff4e0+0x1e0 (0x185bff6c0) | 161 | 16 | r3 → residue 19:41 | gone from aborts, but still CRASH SIGABRT in int1/live (no usertrace there) | axui-punctuation-model |
| 9cd6d756b6 | userabort | lsd | CoreServices func_18178707c+0x314 | 19 | 1 | dbg5 | not exercised since | - |
| 6a3e68d473 | crash | MessagesBlastDoo | CRASH SIGTRAP | 17 | 2 | int1 → live int1 | **open** | blastdoor-sandbox-check |
| 914a688344 | usertrap | backboardd | CoreBrightness Display_lut+0x114 (0x1e2746924) | 16 | 2 | r1 → r2 | likely fixed (20 later boots ran backboardd) | corebrightness-calibration |
| bddd8f644b | usertrap | iconservicesagen | CoreFoundation func_1836953ec+0x10 | 15 | 1 | r5-dsp | likely fixed (12) | - |
| d9a3a62632 | usertrap | appplaceholdersy | AppPlaceholderSync `_SelfDestruct`+0x28 | 15 | 1 | r8-settings | not exercised since | - |
| eb27d6b333 | usertrap | appprotectiond | libswiftCore `_assertionFailure`+0xa8 | 15 | 1 | dbg5 | not seen in 1 later boot | - |
| 4ec1e1b0ce | userabort | pkd | dyld func_18012010c+0x1b10 | 15 | 1 | dbg5 | not exercised since | - |
| a3d55bf4e6 | exit | magicswitchd | SIGKILL sent by launchd | 14 | 14 | r1 → residue 19:41 | likely fixed (3) | - |
| 136e79a851 | crash | AccessibilityUIS | CRASH SIGABRT | 12 | 3 | b1-aks → live int1 | **open** | axui-punctuation-model |
| 40eddda41a | kill | Preferences | runningboardd 0x8badf00d | 11 | 5 | wifi-join-r2 → residue 19:41 | likely fixed (2), but Preferences still SIGABRTs | preferences-launch-watchdog |
| 4f747a4a9b | exit | backboardd | SIGSEGV (exit whose trap was not in the ring) | 5 | 1 | r2 | likely fixed | - |
| 594b6147b0 | stall | Preferences | SystemConfiguration func_1af2c3148+0x60 | 5 | 2 | r10-perf → pwr1 | likely fixed (4) | configd-ionetworkstack |
| c483360ac4 | usertrap | MobilePhone | MobilePhone+0x1e2bc0 | 4 | 2 | r9 → pwr1 | likely fixed (2 later boots ran MobilePhone) | mobilephone-contacts-tcc |
| 2dd03fdf4b | exit | AccessibilityUI | SIGABRT | 3 | 1 | r8-settings | likely fixed | axui-punctuation-model |
| 9cafb39ebf | crash | Preferences | CRASH SIGABRT | 3 | 2 | int1 → live int1 | **open** | about-preferences-medialibrary |
| e9af6341d2 | userabort | backboardd | BaseBoard 0x19075c434 → -[NSURL initFileURLWithPath:] | 2 | 2 | b1-aks → wifi-join-r2 | likely fixed (10) | backboardd-nsurl-container |
| 46ad56b98d | exit | appplaceholdersyncd | SIGTRAP | 2 | 1 | r8-settings | not exercised since | - |
| bce1c21d8c | crash | backboardd | CRASH SIGSEGV | 1 | 1 | r2 | likely fixed | - |
| d677c38e17 | crash | iconservicesagen | CRASH SIGTRAP | 1 | 1 | r5-dsp | likely fixed | - |
| fef206cbef | userabort | AccessibilityUIS | frames lost to interleaving | 1 | 1 | b1-aks | (same loop) | axui-punctuation-model |
| a8634e49c6 | userabort | chronod | QuartzCore func_183f9a620+0x63c | 1 | 1 | wifi-join-r2 | likely fixed (9) | - |
| 02ac2a604e | userabort | PosterBoard | PosterBoard func_220638950+0x1b0 | 1 | 1 | wifi-join-r2 | likely fixed (8) | - |
| 3ac612fe61 | usertrap | Preferences | libsystem_platform 0x2a440b090 ← `sandbox_extension_consume`+0x24 | 1 | 1 | wifi-join-r2 | not seen since, but Preferences still fails | preferences-sandbox-token |
| 0bb9a19d52 | userabort | SpringBoard | UIKitCore func_189d1135c+0x250 (`initWithObjects:count:` nil) | 1 | 1 | r9 | likely fixed (9) | - |
| e74f2df5b9, bc218fd076 | kill | WidgetRenderer_Default, Spotlight | runningboardd ns 15 0xb111b111 | 1 each | 1 | r9 | likely fixed | - |
| 2ce6e04e19 | kill | InputUI | runningboardd 0x1a2b0011 | 1 | 1 | r9 | not exercised since | - |
| 356b2a1960, e360af9a0f | kill, crash | PosterBoard | runningboardd 0x4badca11 | 1 | 1 | residue 19:14 | likely fixed | - |
| e4979fe4c0 | crash | com.apple.Mobile… | CRASH ns 18 code 0x2 | 1 | 1 | dbg5 | - | - |

The deadline panics (every boot ending at `blazer_deadline`, and gpu2's `boot ended on purpose`) are listed in crashes.md
as intended, not as crashes.

## Limits (observed while building it)

- "likely fixed" only means the process ran in later boots without this signature. Usertrace settings differ per boot
  (int1 and live have no `usertrap:` / `userabort:` lines), so the same crash can move to a `crash` signature. The `but ... still
  fails later` note shows that.
- Main-binary frames of a `userabort` stay `?` (the line has no main header). Unowned residue boots (`residue@19:06`,
  `residue@19:14` slide 0x12380000, `residue@19:41` slide 0x640c000) have no local attempt dir; they appear in later dumps only.
- ObjC method names are not resolved; local functions show as `func_<unslid start>`. Use `research/ios26-phaseb-r1/corebrightness/cbdis.py` /
  `objcmeth.py` on a named function, then add it to `LOCAL_NAMES`.
