# Bluetooth: kernel HCI/UART bridge and bluetoothd

Investigation date: 2026-11-03. **Read-only source/host investigation; no build, boot, phone access, or source edit.**
Evidence is labelled **SRC**, **HOST**, **QEMU**, **PHYSICAL**, or **INFERENCE**. Kernel line references below are to
`research/ios26-release-r1/work/xnu` at `hk-bt-b2` **9aa76a93** unless another revision is named. No firmware bytes,
memory-dump excerpts, serial numbers, or Bluetooth hardware addresses are reproduced here.

## Decisive verdict

- The BCM4390B1's AP-UART transport, power/reset sequence, firmware startup, 4 Mbaud RTS/CTS link, and passive LE
  reception already have **PHYSICAL** evidence. This is not a missing UART or firmware-loader problem.
- The mode-5 kernel-control/Skywalk/H4 bridge and its closed transmit gate exist and have **HOST/ARM64** evidence.
  B2 made registration happen only after the chip is ready, added a narrow Broadcom vendor allow-list, and added bounded
  opcode/status logging.
- With AKS wrap/unwrap and the B2 overlay, bluetoothd stays alive in **QEMU**, but its stack never starts: three runs
  produced **zero bluetoothd-originated HCI packets**. QEMU used a synthetic controller/nub and is not attachment proof.
- `a7-ios-system-bt2` is built and checked but **not booted**. There is no physical daemon-to-chip attachment, no
  daemon-originated Reset/Read Local Name exchange, no Settings Bluetooth service, and no pairing/profile service.
- The next real milestone is deliberately narrow: **one persistent bluetoothd opens the real channel; its HCI Reset
  (`0x0c03`) and Read Local Name (`0x0c14`) reach the physical controller and return Command Complete status 0.** The
  kernel's own earlier Reset/local-name probe does not count.

## 1. What it does today

### 1.1 Hardware and ownership are already characterised

The controller is the Bluetooth half of the Wi-Fi combo chip, not a PCIe Bluetooth device.

- Android's `/odm/btbcm` is `goog,nitrous`; it names device wake, host wake, timesync, REG_ON, and DBO pins
  (`research/ios26-dualboot-r8/truth/fdt.dts:32241-32252`). The PMIC line names identify REG_ON and DBO at
  `fdt.dts:16703-16712`.
- H4 uses LSIO_E CLI12, `uart@3a351000`, a DesignWare APB UART with register window `0x3a352000`, reset `0x16`,
  32-bit registers and `reg-shift = 2` (`fdt.dts:13338-13355`). The stock tree marks the UART disabled; the hackios
  driver explicitly votes/clocks/muxes it rather than relying on a serdev/tty driver.
- Device/host wake are AoC interrupt-capable pins (`fdt.dts:26894-26904`). `L4M_BT_AON` is a 1.2 V,
  monitor-only BT supply (`fdt.dts:15932-15940`), not another regulator the driver should toggle.
- The kernel implements the bounded LSIO_E/CLI12/pad/UART window and allowed SMC/CPM operations in
  `xnu/bsd/dev/blazer_btuart_hw.c:13-85,108-180`. REG_ON and DBO are the only PMIC GPIOs it uses
  (`xnu/bsd/dev/blazer_btuart_hw.h:63-70`). It does not touch Wi-Fi's REG_ON.

**Dependency:** BT waits for `blazer_wifi_state == 1` before touching hardware. `bt_thread()` waits up to 420 s and
otherwise exits with “No hardware touched” (`xnu/bsd/dev/blazer_btuart.c:263-285`). Thus a Wi-Fi firmware failure is
a prerequisite failure, not evidence of a BT UART failure.

### 1.2 Chip power, firmware and the fast H4 link work on the phone

The mode-1-through-4 driver path is real and previously exercised:

- `power_cycle()` drives REG_ON low for at least 30 ms, then high and waits 100 ms
  (`xnu/bsd/dev/blazer_btuart_hw.c:523-543`). `attempt()` issues ROM Reset and Read Local Version and records the
  answer (`:545-571`).
- `fw_check()` validates the entire HCD record stream before anything is sent; `fw_load()` performs Download
  Minidriver, Write RAM records and Launch RAM (`:574-632`). `fw_after()` verifies Reset after launch, version and
  Read Local Name (`:635-665`).
- `go_fast()` accepts only a 200 MHz UART clock, uses the fractional divisor, switches the chip and AP to 4 Mbaud,
  enables RTS/CTS, then verifies Reset and Version again (`:701-751`).
- `bu_run()` performs preparation, power attempts, firmware/fast-mode setup, then always goes through teardown;
  teardown lowers BT REG_ON and restores wake/pad state (`:850-872,951-996`).
- Mode 3/4's passive scan accepts only passive parameters and counts reports without logging addresses or payloads
  (`:754-847`). This is receive-only evidence, not association or bluetoothd service.

**PHYSICAL evidence:** `research/laguna-usb-fix/attempts/20261102-073555-bt-stream-r1/reader.txt:271-301`
records Launch RAM completion, successful post-firmware Reset and Read Local Name, the 4 Mbaud RTS/CTS Reset/Version
check, and actual passive LE reports. The controller identifies as BCM4390B1. The receipt's image and source identity
are in the same attempt's `meta.txt:1-14`.

### 1.3 Mode 5 is a real daemon transport, but only source/host-proven

`blazer_btuart_init()` is inert without `blazer_bt=1..5`; mode 5 defaults `blazer_bt_tx` to 0 if absent or invalid
(`xnu/bsd/dev/blazer_btuart.c:320-344`). For mode 5, `bt_thread()` selects firmware, fast mode and a bounded 120 s
serve session (`:274-305`).

The transport is:

```text
bluetoothd -> com.apple.uart.sk.bluetooth / Skywalk channel
           -> H4 framing -> gate -> down ring -> bu_serve() -> UART
UART -> bu_serve() -> H4 framing -> up ring -> channel/socket -> bluetoothd
```

The important implementation points are:

- `blazer_bt_bridge.c:1-23` documents the ABI and data path. `hakios_bt_put()` frames daemon bytes and applies the
  gate (`:145-191`); `blazer_bt_bridge_rx()` frames controller events and returns them (`:235-275`). Rings are bounded
  and losses are counted (`:49-95,287-297`).
- The kernel control is exactly `com.apple.uart.sk.bluetooth`; socket option `0x40105412` returns the nexus UUID,
  and termios changes are accepted without changing the kernel-owned 4 Mbaud RTS/CTS line
  (`xnu/bsd/dev/blazer_bt_bridge.c:378-445`).
- `hk_btsk.c:278-343` creates the kernel-pipe nexus. `btsk_sync_tx()` feeds whole channel bytes to the bridge and
  `btsk_sync_rx()` returns queued event bytes (`hk_btsk.c:172-247`); `hakios_btsk_kick()` notifies RX
  (`hk_btsk.c:250-258`).
- `bu_serve()` polls both directions, drains RX before sending one host packet per turn, and **rechecks every packet**
  against the gate immediately before UART transmission (`xnu/bsd/dev/blazer_btuart_hw.c:874-941`). RTS/CTS protects
  the UART FIFO; LSR errors and refused packets are stop evidence, not noise to ignore.
- It is a deliberately single-session diagnostic. Disconnect or 120 s timeout stops the endpoint with ENXIO and drains
  state; safe reconnect requires controller reset/drain and nexus teardown, which are not implemented
  (`xnu/bsd/dev/blazer_bt_bridge.c:299-350`; `xnu/bsd/dev/hk_btsk.c:34-45,103-129`).

### 1.4 What B2 changed

B2 is one XNU commit, `9aa76a93` on parent `cc42295`, touching six BT files:

1. **Late endpoint registration.** `struct bu_link` gained `ready`; `bu_serve()` calls it only once firmware and the
   fast link are up (`xnu/bsd/dev/blazer_btuart_hw.h:26-34`; `blazer_btuart_hw.c:877-887`). `bridge_ready()` calls
   `blazer_bt_bridge_start()` (`blazer_btuart.c:31-37`). This replaces the old registration one second into boot, so
   an early bluetoothd cannot consume the sole session while the lengthy chip startup is still running.
2. **Narrow vendor support.** `vendor_allowed[]` and `vendor_ok()` allow only Write BD_ADDR with exact length,
   the already-configured 4 Mbaud update, sleep mode 0, and two parameterless reads
   (`xnu/bsd/dev/blazer_bt_gate.c:6-16,156-176`). Other vendor commands get Unknown HCI Command; bad parameters get
   Command Disallowed (`:251-319`). Firmware download and radio-starting commands are not opened up.
3. **Safe flow evidence.** The bridge logs bounded opcodes/statuses only, never command parameters or addresses, and
   counts commands, completions and statuses (`xnu/bsd/dev/blazer_bt_bridge.c:49-65,165-185,245-295`).
4. **QEMU-only fake controller.** `qfake_serve()` avoids all physical register/PMIC/SMC/pad access and answers commands
   admitted by the same gate (`xnu/bsd/dev/blazer_btuart.c:219-260`). It is not admitted on a phone image and cannot
   prove real attachment.

**HOST/ARM64 evidence:** `bluetooth/b2/receipts/gate-host-test.txt:1-6` reports 16,909 passing checks and four caught
mutations. `kernel-bt2-objects.txt:1-35` records a full Apple-clang `DEVELOPMENT_ARM64_BLAZER` build and the expected
ARM64 symbols/disassembly. This is stronger than a syntax-only check.

### 1.5 Userspace changes and their actual evidence

The B1 AKS work adds gated software wrap/unwrap for the system bag in `SweetKeyStore.cpp`; the format and tests are in
`research/ios26-connectivity-r1/bluetooth/aks-wrap/src/blazer_aks_wrap.inc` and `aks-wrap/0001-sweet-aks-wrap-unwrap.patch`.
It uses a per-boot secret and does not provide persistent pairing identity. B1 physical evidence is summarised in
`research/ios26-phaseb-r1/int/INT1.md:73-75` (selector 10 succeeds; no failures).

The B2 overlay makes exactly two changes (`bluetooth/b2/receipts/overlay-bt2-r1.json:1-18`):

- record 42: remove bluetoothd from `hk_deny`, leaving Spotlight denied;
- record 39: give bluetoothd `BT_HCI_TRANSPORT=H4:POSIX` and `BT_CHIP=ACI BT`.

The release-consumer check passes 181 checks (`consumer-bt2-r1.txt:1`). The image also adds an `arm-io/bluetooth` nub
with transport encoding 7 and a **placeholder**, not the phone's hardware address.

**QEMU, not phone:** B2 q1/q2/q3 kept one bluetoothd pid alive, keychain adds succeeded, and q3 stayed up for 900 s.
Nevertheless all three had zero HCI packets; q3 remained `fStackStarted:0`, and BlueTool never launched. Static analysis
locates the intended path as LocalDevice asynchronous power init -> default power -> ChipBoot/BlueTool -> power on, but
power init was never called. bluetoothd also skips chip init when it detects a VM. See
`research/ios26-connectivity-r1/bluetooth/B2.md:52-74`.

### 1.6 Current integrated images have BT deliberately off

`a7-ios-system-int3` has no `blazer_bt` or `blazer_wifi` tokens (`research/images/a7-ios-system-int3/manifest.json:34-40`),
and its inherited overlay still contains `hk_deny bluetoothd,Spotlight` (`research/ios26-phaseb-r1/int/INT1.md:83,91-92`).
The physical int3 console confirms all three user-visible consequences:

- overlay contains `hk_deny bluetoothd,Spotlight` (`live-20261103-232046-a7-int3/console.txt:223`);
- bluetoothd is refused as a missing executable (`:736,752`);
- Preferences hides the Bluetooth row (`:3628`).

The B2 phone image is different: its manifest explicitly has `blazer_wifi=1`, `blazer_wifi_stage=5`,
`blazer_wifi_hold=1`, `blazer_bt=5`, AKS wrap, the BT nub and the B2 overlay
(`research/images/a7-ios-system-bt2/manifest.json:34-40,152-191`). It is bootable and AVB-checked
(`bluetooth/b2/receipts/image-check-a7-ios-system-bt2.txt:1`), but **not booted**.

## 2. What is missing

In dependency order:

1. **A physical trigger for LocalDevice power init.** QEMU proves daemon longevity only. It does not show what makes a
   real BTServer client start the stack. Opening Settings > Bluetooth on the phone is the cheapest deciding test;
   Buddy/first-unlock state or WirelessRadioManager check-in remain hypotheses, not established fixes.
2. **Proof of the stock BlueTool boot/init script.** No B2 run reached it. Once power init runs, stock BlueTool may
   accept the `ACI BT`/transport-7 identity or may reject this non-Apple platform. Do not install a stand-in before the
   log distinguishes this from power init never being called.
3. **Physical control/nexus/channel attachment.** There is no phone evidence yet for `bluetoothd connected`, a connected
   Skywalk channel, or a daemon packet on the UART.
4. **The real daemon-originated Reset and Read Local Name exchange.** The kernel already issues those commands for its
   own bring-up; the milestone requires them **after** `bluetoothd connected`, with matching bridge `to chip` and
   `from chip: complete ... status 0x00` lines. Read Local Version (`0x1001`) is useful but is not a substitute.
5. **A current instrumented integration.** B2 is based on r10-perf, while the useful live input/snapshot/HKL/HKOBS
   tools and Settings fixes are on `hk-int3` 3dc7fec. No image combines them. A read-only three-way merge preview for
   cherry-picking B2 onto int3 shows conflicts only in `blazer_bt_bridge.c` and `blazer_btuart.c`; the gate and UART
   hardware edits merge cleanly.
6. **Any required follow-on init commands.** If bluetoothd stops after Reset/local name, the bounded `held` opcodes and
   `BG_WHY_*` counters identify missing standard/vendor operations. They must be reviewed individually; a blanket
   vendor allow or transmit-level increase is not justified.
7. **Everything beyond first attachment:** session reconnect, a serve window suitable for normal use, host-wake/LPM,
   persistent keys/identity, owner-approved scanning/transmission, pairing, profiles, SCO/A2DP, suspend/resume and
   repeated reconnect. `blazer_bt_tx=0` intentionally cannot provide these.

## 3. Fix path

### Step 1 — Keep the proven UART sequence; make one `hk-bt3` integration branch

Start from `hk-int3` **3dc7fec3663746ed0390f360c3fa63031b970861** and cherry-pick **9aa76a93**. Do not rewrite
`blazer_btuart_hw.c` power/firmware logic.

Resolve the two conflicts as follows:

- **`xnu/bsd/dev/blazer_bt_bridge.c`:**
  - keep B2's `FLOW_LOGGED`, `cmds_sent`, `completes`, `statuses`, VPARAM handling and bounded `to chip`/`from chip`
    logging;
  - keep int3's `obs_cmd_*`, `obs_evt`, `obs_cc_*` and `blazer_bt_bridge_obs()` so HKOBS reports the same events;
  - use one authoritative sent-command counter (B2's `cmds_sent`, or update both deliberately), not two counters that
    can diverge;
  - preserve `any |= up_put(...)` after the merged event decoding, otherwise the logs would claim replies that were
    never delivered.
- **`xnu/bsd/dev/blazer_btuart.c`:**
  - remove int3's old one-second/early `blazer_bt_bridge_start()` and early-quit Wi-Fi wait; retain B2's `bridge_ready`
    callback and late registration;
  - retain B2's QEMU-only qfake branch and boot-arg parsing;
  - retain int3's `bt_phase` and `blazer_bt_obs()` (`hk-int3:bsd/dev/blazer_btuart.c:40-63`), setting phase around the
    qfake/hardware/serve paths so HKOBS cannot report a stale “waiting” state.

The other B2 files to carry are `blazer_bt_gate.c`, `blazer_bt_gate.h`, `blazer_btuart_hw.c`, and
`blazer_btuart_hw.h`. `hk_btsk.c` needs no B2 change.

### Step 2 — Derive `bt3-r1.ovl` from int3, not from perf-r1

Copy `bluetooth/b2/tools/bt2_overlay.py` to a B3 tool and make only these semantic changes:

- pin `research/ios26-phaseb-r1/int3/overlays/int3-r1.ovl` and its SHA, rather than perf-r1;
- keep record 42's `bluetoothd,Spotlight -> Spotlight` edit;
- append the same bluetoothd transport/chip rule to record 39. int3 already gives bluetoothd the HKL mirror rule, so
  relax the “program already has a rule” refusal **only for this additional BT rule**. Do not allow arbitrary duplicate
  variable rules.

This is valid because `hk_env_for_program()` emits every matching variable and merges only DYLD_INSERT_LIBRARIES
(`hk-int3:bsd/kern/hk_env_merge.h:102-155`). bluetoothd must receive the two BT variables **and** the mirror variables.

Postconditions: 65 records; only [39] and [42] differ; 63 records byte-identical; record 39 is **972 bytes including
NUL** (920 + 52), below the 1024-byte kernel bound; Spotlight remains denied. Run B2's release-consumer checks, int3's
`hkov_check`/cover checks, and OBS's per-program environment test. Explicitly assert bluetoothd's BT variables,
`HK_LOGMIRROR=1`, and logmirror injection all survive.

### Step 3 — Build `a7-ios-system-bt3` with a closed gate and live UI support

Start with `research/ios26-phaseb-r1/live/uidrive/tools/image_tool_int2.py`, which already admits the Wi-Fi tokens and
`hk_dbg`. Port only B2's `blazer_bt=5` / `blazer_bt_tx=0` allow-list entries, `--bt-nub`, nub construction and manifest
field from `bluetooth/b2/tools/image_tool_bt2.diff`. Keep `blazer_bt_qfake` out of PHONE_ALLOWED.

Use the int3 image recipe and overlay from Steps 1-2, `--bt-nub`, and these exact token changes from int3's final
manifest:

```text
add:    blazer_wifi=1 blazer_wifi_stage=5 blazer_wifi_hold=1 blazer_bt=5 blazer_bt_tx=0
change: hk_dbg=0x1e1e1f -> hk_dbg=0x3
remove: blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1
keep:   blazer_aks_wrap=1 blazer_netstack=1 hk_bright=140 hk_overlay=0xA0080081
```

Retain int3's `--drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1`. The resulting command line is **1020 bytes, 58
tokens, 3 bytes free**, with the default fast-core `blazer_deadline=900`. `hk_dbg=0x3` keeps exactly live input and
live snapshots; HKOBS needs no `hk_top`. The removed physical-key switches are test-only sacrifices for the 1023-byte
boot-line ABI, not BT requirements. Do not append anything without making corresponding room.

Build/check shape (hashes are supplied by the actual builder):

```sh
python3 -I <b3>/tools/image_tool_bt3.py image a7-ios-system-bt3 \
  --kernel <b3>/build/kernel.bt3 --kernel-sha <kernel-sha> --bt-nub \
  --phone-root --phone-route ufsroot --qemu-run overlay-1 \
  --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
  --var-overlay <b3>/overlays/bt3-r1.ovl --var-overlay-sha <overlay-sha> \
  --phone-args "$BT3_ARGS" \
  --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1
python3 -I <b3>/tools/image_tool_bt3.py check research/images/a7-ios-system-bt3
```

Do not pass `--phone-deadline 900`: this image tool accepts the fast-core 900 s default, but its explicit-value parser
only admits 300/1800/3600.

### Step 4 — Verify before spending a phone boot

- Full Apple-clang `DEVELOPMENT_ARM64_BLAZER` build on the Mac under the normal build-slot owner; zero undefined
  symbols. Inspect enabled-gate ARM64 objects and the linked kernel for `_bg_check`, `_vendor_ok`,
  `_blazer_bt_bridge_start`, `_bridge_ready`, `_blazer_bt_obs`, `_blazer_bt_bridge_obs`, `_hk_obs_start`, `_hk_dbg`,
  and the B2 flow-log strings.
- Re-run the real B2 gate test (16,909 checks plus mutations), OBS tests, overlay consumers and UI runner tests. A
  syntax-only compile is not acceptance.
- Assert the manifest has the exact token delta above, `blazer_bt_tx=0`, no qfake, `bt_nub=true`, deadline 900, and
  AVB/bootable checks passing.
- QEMU may be used to regression-test daemon longevity, environment merging, gate behaviour and HKL/HKOBS. Do **not**
  spend cycles expecting the existing QEMU setup to prove Reset: B2 already showed no power init, and the VM check can
  suppress ChipBoot even after that is fixed.

### Step 5 — Exact unattended physical boot and Settings > Bluetooth test

Add this as `ui/settings_bluetooth.ui` in the implementation change (it intentionally has no guessed Bluetooth-row
fallback and never touches the power toggle):

```text
wait_home
shot home
mark settings-bluetooth
tap 170 279 app=Preferences retry=1 verify=25
shot settings
tap_text "Bluetooth" region=all on_fail=stop
sleep 5
shot bluetooth
check_text "Bluetooth"
home
shot end
```

Run one full cycle. `hk cycle` uses `tools/live_boot.sh` for the console, runs the UI against the live snapshots,
waits for the deadline/park, runs the Android return check, and produces a report:

```sh
cd /srv/dev/repos/personal/hackios
HK_LOCK=BT3 hk cycle research/images/a7-ios-system-bt3 \
  --name a7-bt3 \
  --mach research/ios26-connectivity-r1/bluetooth/b3/build/kernel.bt3.unstripped \
  --ui ui/settings_bluetooth.ui
```

During the boot, split the live console without hiding dropped-line evidence:

```sh
python3 -I tools/hklog.py --follow <live-run>/console.txt -o /tmp/opencode/bt3-live
# bt.log, hkl/bluetoothd.log, hkl/BlueTool.log, proc.log, status.log, summary.txt
```

Afterward:

```sh
hk logs --attempt <attempt-id> --sub bt
hk logs --attempt <attempt-id> bluetoothd
hk logs --attempt <attempt-id> BlueTool
hk crash --attempt <attempt-id>       # tools/crashdoc.py census, signatures and known causes
hk report <attempt-id>
```

`live_boot` writes `console.txt`, markers and UI receipts; OBS supplies `HKL bluetoothd[...]`, `HKOBS ... bt:` and
respawn/drop counts; crashdoc separates the current boot from residue and catches bluetoothd/Preferences aborts rather
than letting them masquerade as transport failures.

### Acceptance for the first real milestone

Require all of the following in the same physical attempt:

1. Manifest/image checks pass; console shows bluetoothd's two BT environment variables, no `hk_deny: bluetoothd`, and
   one bluetoothd exec with no exit/respawn before the HCI exchange.
2. Wi-Fi firmware reaches the hold state; the normal kernel BT startup reaches 4 Mbaud. Only then do the nexus and
   kernel control register.
3. The UI script opens Settings > Bluetooth and saves a screenshot showing that page. A merely visible Home screen or
   a soft OCR check is not UI acceptance.
4. `blazer-bt-bridge: bluetoothd connected` and `btsk: the channel is connected` appear **after** registration.
5. Subsequently, bridge flow shows daemon-originated `to chip 0x0c03` / `from chip: complete 0x0c03 status 0x00` and
   `to chip 0x0c14` / `from chip: complete 0x0c14 status 0x00`. HKOBS's last command/completion fields and summary
   counters must agree.
6. No `serve-gate` stop, nonzero LSR error bits, up/down loss, malformed stream, unexpected panic, or bluetoothd crash
   loop occurs through the exchange. The planned deadline panic is normal. Android return check is PASS.

Do not count the kernel's pre-registration `GO: HCI Reset...` or `local name:` lines as criterion 5. Do not require a
scan, an On toggle, discovery, pairing or audio at gate level 0.

### Decision tree if it fails

- **No Wi-Fi firmware-up line:** fix/re-run the Wi-Fi prerequisite; BT correctly touched nothing.
- **Chip startup fails before endpoint registration:** use the existing `Next:`/`bu_stop_name` evidence in
  `blazer_btuart_hw.c`; userspace is not yet involved.
- **Endpoint registered, but no daemon connect and HKL still shows `fStackStarted:0`:** Settings did not trigger power
  init. Continue static analysis of LocalDevice's power-init caller and BTServer client sessions, then examine
  first-unlock/Buddy and WirelessRadioManager check-in. Do not change UART code or enable every radio daemon blindly.
- **Power init starts but stock BlueTool rejects the platform:** only then integrate the existing narrow stand-in
  `research/ios26-bt-r1/bluetool/bluetool.c`, functions `answer()` and `main()`, behind the same `com.apple.BlueTool`
  XPC job. It reports success because the kernel already performed chip startup. Keep its result/manufacturer contract;
  do not bypass keychain semantics.
- **Channel connects but commands are `held`:** review the exact standard/vendor opcode and parameters. Extend
  `levels[]` or `vendor_allowed[]`/`vendor_ok()` only for a required non-transmitting operation, with new host/mutation
  tests. Never blanket-allow vendor commands or daemon firmware downloads.
- **The 120 s serve window ends before Settings drives the stack:** this is a timing failure, not proof that power init
  is broken. Re-run with a deliberately reviewed larger `bt.serve_ms` in `bt_thread()` (for example 600000 ms, still
  inside the 900 s deadline), after the same host tests. Preserve teardown.
- **Any daemon/channel disconnect:** reboot for the next attempt. `hk restart bluetoothd` cannot produce a valid second
  session with the current one-shot bridge.

## 4. Risks

| Risk | Why it matters | Guardrail |
| --- | --- | --- |
| Accidental radio transmission | Scanning, advertising, inquiry and connections can emit before service is understood. | Keep `blazer_bt_tx=0`; level 0 admits reads/local settings only. Owner approval is required before levels 2/3. |
| Vendor command side effects | Write BD_ADDR changes controller identity; baud/sleep commands change link state. | Keep exact parameter checks and the five-entry list. The placeholder is not a production identity; never put the phone's address in git/docs. |
| Combo-chip interference | BT depends on the Wi-Fi firmware and shared power/pad state. | Preserve Wi-Fi hold, never touch Wi-Fi REG_ON, restore BT REG_ON/pads/wake on every exit, and run the Android return check. |
| One-shot/short session | BlueTool failure, a Settings reconnect, or slow UI can permanently consume or outlive the only session. | Drive Bluetooth immediately after Home; treat ENXIO/serve timeout separately; no daemon restart; extend the bound only deliberately. |
| Misleading QEMU negative | The synthetic nub/controller and VM detection suppress the very path under test. | Use QEMU for daemon/gate regressions only; require physical opcode/completion evidence for the milestone. |
| Missing stock BlueTool platform support | A working kctl/nexus can still sit idle while ChipBoot fails before opening it. | Read HKL BlueTool/bluetoothd first; use the narrow stand-in only after that signature appears. |
| Logging can lose the decisive lines | HKL has per-program and global budgets; compositor/userland crashes can bury a transport result. | Check HKOBS and bridge counters as an independent source; record `dropped` counts; run crashdoc; do not “fill in” missing log lines by inference. |
| Settings instability is not necessarily BT | Preferences/configd/compositor failures can prevent the trigger even with a healthy chip. | Keep int3's netstack and brightness fixes; distinguish UI failure from post-registration HCI evidence. |
| Boot-line overflow | XNU/shim expose a fixed 1023-byte command-line limit. | The proposed line is 1020 bytes; manifest-check every build and drop rather than append future diagnostics. |
| No persistent pairing security | AKS wrap uses a per-boot software secret and `/private/var` is volatile. | Do not claim reconnect/pairing persistence. Storing a secret on ios_data is a separate owner security decision. |
| Power/LPM is incomplete | Sleep mode 0 and polling avoid unimplemented wake handling but cost power/CPU; host wake is not an implemented service. | No LPM or suspend claim. Watch serve CPU/LSR/loss counters and keep the bounded teardown. |

## Primary references

- `research/ios26-connectivity-r1/bluetooth/PLAN.md` — hardware, prior physical stages, AKS and staged B1-B5 plan.
- `research/ios26-connectivity-r1/bluetooth/B2.md` — B2 source/build/overlay/QEMU results and unbooted bt2 recipe.
- `research/ios26-phaseb-r1/live/OBS.md` — HKL/HKOBS contracts, budgets, hklog usage and known B2 merge conflicts.
- `research/ios26-phaseb-r1/live/uidrive/UIDRIVE.md` — unattended live input/snapshot runner, `hk_dbg`, UI DSL and limits.
- `docs/debug/MAP.md` (`bt`, `obs`, `usb`, `settings`) and `docs/debug/BACKLOG.md` (`probe:bluetooth`).
