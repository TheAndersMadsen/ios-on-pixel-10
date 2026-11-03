# Live root shell + debug tools for the running iOS (2026-11-03, HOST build + host test, not booted)

Goal (this task): once DBG1's USB network is up (iOS `192.168.77.2`, Mac `192.168.77.1`), give a **root shell** in the
running iOS plus the system's own debug tools, and a **no-network fallback** that keeps producing diagnostics into
the ramdump/console. Delivered as an overlay built **on top of `perf/overlays/perf-r1.ovl`**, so it layers onto
whatever image DBG1 boots.

**Address note:** the task brief named `10.42.0.2`/`10.42.0.1`, but DBG1's committed, built-and-tested USB net
(`net/NET.md`) uses **`192.168.77.2` (phone `en2`) / `192.168.77.1` (Mac)** over the 1209:0003 ECM gadget, and
explains why (the existing kernel's `UNQ_PHONE_IP`/`UNQ_MAC_IP` and the owner's `tools/usbnet_mac.py` already agree on
192.168.77.0/24, pinned by a consistency test). `hk_shell` therefore binds `192.168.77.2` — the address the phone
actually has. `ADDR`/`PORT` stay configurable (§4) if DBG1's addressing changes.

**Verdict:** built, ad-hoc signed (arm64e), unit- and host-functional-tested; overlay composed and re-parsed by the
release kernel's own consumers. **Not booted** (QEMU can't reach Home; the phone needs the owner). One assumption is
unverified on-device and is called out in §4: whether the host daemon's seatbelt profile lets it open a listening
socket / spawn. The no-network fallback is designed to need only routes already proven on the phone.

Evidence class: HOST (m1box compose + Mac toolchain build + host loopback test) and a read-only read of the QEMU-rig
root for the tool inventory. Nothing here is phone evidence.

## 1. What is on the root (debug-tool check)

Read-only mount of the accepted apps root (`/data/hackios-qemu/.../apps-full-r6.img`, HFSX; its userland is the one
the `a7-ios-system`/`ios_system` boots use), scratch COW copy deleted after. Full inventory: `receipts/toolcheck.txt`.

| task-required | on root | note |
| --- | --- | --- |
| `spindump` | **yes** `/usr/sbin/spindump` | one-shot sampler; also covers the missing `sample` |
| `ps` | **yes** `/bin/ps` | (not `/usr/bin/ps`) |
| `top` | **no** | use on-root `ltop`, `taskinfo`, `vm_stat` |
| `sample` | **no** | use `spindump`, or `debugserver`+lldb from the Mac |
| `log stream` | **no CLI** | only the daemons `logd`/`logd_reporter`/`logd_helper`; no `/usr/bin/log`, so `log stream`/`log show` cannot run on-device |
| `debugserver` | **yes** `/usr/libexec/debugserver` | so the task's "if debugserver isn't on the root" fallback is **not needed** |

**Decisive finding:** there is **no shell on this root at all** — `/bin` holds only `df` and `ps`; no `/bin/sh`, `bash`,
`zsh`, or `launchctl`. A TCP "shell" therefore **cannot exec an existing shell**. `hk_shell` is a self-contained
command runner that spawns the binaries that *are* present (`ps`, `spindump`, `ltop`, `taskinfo`, `vm_stat`, `ioreg`,
`ifconfig`, `nvram`, `mount`, `debugserver`, …).

## 2. Why injection into a launchd daemon (not a new LaunchDaemon plist)

launchd's job search paths (`/System/Library/LaunchDaemons`, `/Library/LaunchDaemons`) are on the **read-only root**;
the `/private/var` overlay cannot drop a plist there (`varfs_tsv_path_ok` restricts the overlay to `/private/var`).
The only overlay-reachable launch vector is the project's existing **`hk_env` dylib injection** into a daemon launchd
already starts — the same mechanism as `hgltrack`/`hkart`/`hkbattery`/`hk_mainwatch` (perf/FIX.md). So `hk_shell` ships
as a dylib injected into **`powerd`** (root, early, always running, already carrying `hkbattery.dylib`); launchd starts
powerd, powerd's loader runs `hk_shell`'s constructor, and that starts the shell. The host is a one-line change in the
overlay, so it can be retargeted without a rebuild (§4, §6).

## 3. Design of `hk_shell.dylib` (`src/hk_shell.c`)

Gate: `HK_SHELL=1` in the environment **and** `getprogname() == "powerd"` (so even though only powerd's row injects it,
the dylib is inert anywhere else). It opens the socket, `/dev/console` and whatever a typed command does; it never
writes the root (read-only) and keeps no disk state. Two independent facilities:

- **(A) Network root shell** — needs DBG1's link. A listener binds `HK_SHELL_ADDR:HK_SHELL_PORT` (default
  `192.168.77.2:2222`). If the address isn't assigned yet it retries ~60 s, then (ANY_FALLBACK=1) falls back to `0.0.0.0`
  so it still comes up once the link appears. Each connection is served on its own pthread: read a line → split argv
  (quoting/escapes) → builtins (`cd`, `pwd`, `setenv`, `help`, `exit`) or PATH-resolve and `posix_spawn` with the
  socket wired to the child's stdin/stdout/stderr, then print `[exit N]`. A crashing command is just one child; powerd
  is untouched (no `fork()` of the host). Connect from the Mac with `nc 192.168.77.2 2222`.

- **(B) No-network console fallback** — needs no link; always on (unless `CONSOLE_SECS=0`). Every `CONSOLE_SECS` (30)
  it writes a CPU-sorted process table to `/dev/console`, built **in-process from libproc** (`proc_listallpids` +
  `proc_pid_rusage` deltas, `proc_name`) — i.e. using only the `/dev/console`-write + mach/libproc routes `hkbattery`/
  `hk_mainwatch` already exercise from inside their hosts, so it needs no exec and no socket. The existing ramdump and
  live console capture the `HKSHELL top:` lines. When `SPINDUMP=1`/`PS=1` it *also* `posix_spawn`s the real
  `/usr/sbin/spindump` and `/bin/ps` to `/dev/console` (best-effort; if the spawn is denied it logs that and the
  in-process table still lands).

### AMFI / sandbox posture (the one unverified assumption)

- **Code signing: fine, proven route.** The kernel accepts ad-hoc, non-platform, entitlement-free Mach-Os
  (`kern_exec.c` ~9170: sets `CS_SIGNED|CS_VALID` for exactly this case) — the path every `hk_*` dylib already loads
  through. `hk_shell.dylib` is built identically (arm64e, `pacstrip --sign`, `codesign --verify --strict` clean, no
  PAC code; links only libSystem). The libproc symbols resolve in libsystem_kernel at runtime.
- **Sandbox: active, and this is the risk.** MACF/seatbelt is compiled in (board `blazer`) and NOTES records a live
  "sandbox op 5" token, so the sandbox is enforced. Whether powerd's profile permits `bind`/`listen`/`accept` and
  `posix_spawn` is **not verified** (no boot reached here). Mitigations built in:
  - Facility **(B)** avoids exec and sockets entirely for its core output → highest odds of working regardless.
  - The read-out (§7) tells "bound/accepting" from "blocked by sandbox" from the console lines.
  - If powerd's sandbox blocks (A): retarget the host in the overlay (§6) to a daemon whose profile permits inbound
    network, **or** add a one-line blazer-XNU hook to drop the host's sandbox for the shell (named, not built here:
    an `hk_unsandbox=NAME` gate alongside `hk_deny`/`hk_env` in `bsd/kern/kern_exec.c`). Both are follow-ups, not part
    of this overlay.

Security: (A) is an **unauthenticated root shell**. It binds only the USB point-to-point address `192.168.77.2`; keep
`NET=1` only on bring-up images on the isolated ECM link, never on anything that could reach a real network. Set
`NET=0` in the conf to ship the console fallback alone.

## 4. Config `hk_shell.conf` (`/private/var/hk/hk_shell.conf`)

KEY=VALUE lines, each overridable by env `HK_SHELL_<KEY>`; comments `#`. Keys: `ADDR` (192.168.77.2) `PORT` (2222)
`ANY_FALLBACK` (1) `NET` (1) `CONSOLE_SECS` (30) `TOP` (12) `SPINDUMP` (0) `PS` (0) `SPINDUMP_SECS` (120) `PATH`
(`/usr/bin:/bin:/usr/sbin:/sbin:/usr/libexec`). Changing any value is an overlay recompose (§6), no dylib rebuild. The
`spindump`/`ps` argv for facility (B) are compiled in (standard BSD flags); tune in `src/hk_shell.c` if the on-root
tools differ.

## 5. The overlay `live-r1.ovl`

- Base: `research/ios26-phaseb-r1/perf/overlays/perf-r1.ovl` `95701ed9…` (r10; pinned in `tools/live_overlay.py`).
- Tool: `tools/live_overlay.py` (host-only; mkoverlay pack/fnv1a/env_ok, restore_cloudd decode as the second walker,
  pinned base hash, refuses to overwrite). Three changes, 48 records byte-identical:
  - `[39]` hk_env: powerd's rule gains `:/private/var/hk/hk_shell.dylib` in `DYLD_INSERT_LIBRARIES` and `;HK_SHELL=1`
    (710→752 B, +NUL 753 < HK_RULES_MAX 1024; longest var 84 < HK_VAR_MAX 384). Only powerd's rule changes — the
    Preferences `hk_mainwatch` rule and all others are untouched.
  - appended `/private/var/hk/hk_shell.dylib` (group 29, 0755 root:root, 52,912 B).
  - appended `/private/var/hk/hk_shell.conf` (group 29, 0644 root:root, 986 B).
  - `hk_deny` (`bluetoothd,Spotlight`) and `disabled.plist` carried through unchanged → bluetoothd/Spotlight stay
    denied exactly as in perf-r1.
- Output **`8b4bc28446b525c5c055e543202d61a18282e602d5d3e1289762e0693d8b68ce`** (665,224 B, 51 records).
- `receipts/consumer.txt` — `tools/live_consumer.c` built with ASan/UBSan against the **release kernel's own**
  `varfs_overlay.h`/`hk_exec_rules.h` (`research/ios26-release-r1/work/xnu/bsd`, sha in `receipts/release-headers.txt`):
  `hkov_check`/cover/groups pass; the one changed record and the two appended files are the ones varfs writes under
  mask `0xA0080081` (not overridden); `hk_env`/`hk_deny` parse; every process's exec environment is identical except
  powerd's, which gains `hk_shell.dylib` + `HK_SHELL=1`. **PASS, 289 checks.**
- `receipts/mainwatch`→ n/a; build receipts for the dylib are in `receipts/` (pacstrip, codesign, otool, nm, vtool).

## 6. How the coordinator layers it onto DBG1's image

`live-r1.ovl` **already contains all of perf-r1** plus the shell, so it is a drop-in replacement for the var-overlay.

- **If DBG1's bring-up image uses `perf-r1.ovl` as its `--var-overlay`** (the current newest overlay in this phase):
  point the image at `live-r1.ovl` instead. With the repo's `image_tool.py`:
  ```
  python3 -I tools/image_tool.py image <NAME> --kernel <K> --kernel-sha <KS> \
    --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 \
    --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
    --var-overlay research/ios26-phaseb-r1/live/overlays/live-r1.ovl \
    --var-overlay-sha 8b4bc28446b525c5c055e543202d61a18282e602d5d3e1289762e0693d8b68ce \
    --phone-args "<the image's existing args, unchanged>" --phone-deadline <as DBG1 chooses>
  ```
  (kernel, args, cpus, canvas, deadline = whatever DBG1's image already uses; only the overlay + its sha change. The
  boot-arg `hk_overlay=0xA0080081` already selects group 29, which is where the appended files and the hk_env row live.)

- **If DBG1 builds on a *different* base overlay B** (not perf-r1): re-run the compose on B. `live_overlay.py` pins the
  perf-r1 hash, so either (a) change `BASE_SHA` in a copy of the tool to B's sha and keep the same three edits, or (b)
  apply the generic recipe to B with `mkoverlay.py`: append the two group-29 files (`hk_shell.dylib` 0755 root:root,
  `hk_shell.conf` 0644 root:root) and extend B's single active `hk_env` record so the host daemon's rule gains
  `:/private/var/hk/hk_shell.dylib` in `DYLD_INSERT_LIBRARIES` and `;HK_SHELL=1`. Re-run `live_consumer.c` (base B, out)
  to confirm only that daemon's env changed. To put the shell in a **different host daemon**, change `HOST` in
  `live_overlay.py` from `powerd` to that daemon's exec name (it must have an active `hk_env` rule or add one), recompose.

DBG1 provides the USB networking (ECM, iOS `192.168.77.2` / Mac `192.168.77.1`); `hk_shell` binds the iOS side. Nothing here
changes the kernel, the root, the AVB/boot chain, the GPT or Android.

## 7. Attended boot: connect, read-out, fallback, rollback

Boot DBG1's image the usual attended way (bare `fastboot boot`, `ANDROID_SERIAL` set, disks by-name, return check
after). Once Home is up and DBG1's link shows `192.168.77.2` reachable from the Mac:

1. **Network shell:** first bring up the Mac's ECM alias (same as NET.md step 4, `enN` = the AppleUserECM interface):
   `sudo /sbin/ifconfig enN inet 192.168.77.1 netmask 255.255.255.0 alias`. Then `nc 192.168.77.2 2222` (or
   `socat - TCP:192.168.77.2:2222`). Expect the banner and an `ios:/ #` prompt. Try: `ps -Awwx -o pid,comm | head`,
   `spindump -notarget 2 -stdout`, `vm_stat`, `ltop`, `ioreg -l | head`, `ifconfig`,
   `debugserver 192.168.77.2:1234 --attach=backboardd` (then `lldb` from the Mac). `exit` to close; drop the alias
   afterwards with `sudo /sbin/ifconfig enN inet 192.168.77.1 -alias`.
2. **Console read-out** (ramdump / live console), independent of the link:
   - `HKSHELL: powerd[N] up; net=1 addr=192.168.77.2:2222 console=30s …` — the dylib loaded in powerd.
   - `HKSHELL net: listening on 192.168.77.2:2222` → (A) bound. `… listening on 0.0.0.0` → the addr wasn't up yet; link late.
   - `HKSHELL net: bind … failed (1 Operation not permitted)` or a spawn failure line → **host sandbox blocks it**;
     use the retarget / XNU-hook options in §3/§6. The console table (below) still works.
   - `HKSHELL top: K procs, 400 ms window …` then `HKSHELL  <pid> <cpu%> <name>` lines every 30 s — facility (B),
     the no-network fallback. With `SPINDUMP=1`/`PS=1`, also `HKSHELL spindump: exit 0` / `HKSHELL ps: exit 0` (or a
     "spawn failed … sandbox may forbid exec" note).
3. **Stop:** a panic other than the image's deadline, Home lost, or a powerd crash loop (powerd now carries the dylib —
   watch for `powerd` respawns in `HK TOP`). **Rollback:** the image's deadline/PSCI reset returns to fastboot, then
   `return-check.sh`. Nothing is written (root read-only, `/private/var` in RAM; the shell writes only the socket and
   `/dev/console`).

## 8. Files and sha256

| file | sha256 | what |
| --- | --- | --- |
| `src/hk_shell.c` | `d2cac1956ad2ee0f85040f2283fabcd0f1f4cec2f21923ca8ef076ac772ba80a` | the injected daemon + fallback |
| `overlays/hk_shell.conf` | `b9b9da55a67fc20afe7fb3100c89db2e97bc13c24b8971e208386e19be752c84` | runtime config |
| `out/hk_shell.dylib` | `682a68598cd9ccb037f9a5e99200d874d6a436c37c714dff5093c3f06c3af687` | arm64e, ad-hoc signed, 52,912 B |
| `overlays/live-r1.ovl` | `8b4bc28446b525c5c055e543202d61a18282e602d5d3e1289762e0693d8b68ce` | **the overlay to boot**, 665,224 B |
| `tools/live_overlay.py` | `4a2305eaf6eade1f4d6c08c37d5519839c33519795185d65fd08e6415675237b` | compose on perf-r1 |
| `tools/live_consumer.c` | `8bf5c6b93bdacac76c1784408160fda58e5e04793642d19f269e23c3ca3800b9` | release-header check |
| `build-mac/build.sh` | `3e52c08f0e1570f7da50fa401b78454f7b31f7812fa4f1a9de085247f4ee92be` | Mac build (unit+func+arm64e) |
| `tests/test_shell.py` | `f510213707641657f7f318f27fa4fe6a303baa8d9ac75ac9576b22117e87923a` | host loopback driver |
| base `perf/overlays/perf-r1.ovl` | `95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55` | (unchanged input) |

Receipts: `receipts/toolcheck.txt` (root inventory), `receipts/consumer.txt` (PASS 289), `receipts/unit.txt`,
`receipts/host-func.txt` + `receipts/host-console.txt` (loopback test, all PASS), `receipts/SHA256SUMS`,
`receipts/release-headers.txt`, and the dylib build receipts (`pacstrip.txt`, `codesign-verify.txt`, `file.txt`,
`otool-L.txt`, `build-version.txt`, `nm-undefined.txt`, …).
