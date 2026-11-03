# NFC investigation: ST21NFC/ST54L on Pixel 10 Pro

Date: 2026-11-03. Scope: read-only SOURCE/HOST/ARM64 investigation. This investigation did not build, boot, or touch the phone. **No PHYSICAL NFC result exists.** In particular, host-model success and a linked ARM64 driver are not controller identification.

## Executive finding

Do not start a second NFC driver. The restored shared XNU `p1` has no NFC runtime, but branch **`hk-nfc1`** (`f4fa53021d154cb99906f7325056b421bcb92d08`, on `hk-obs1` `2841211`) already implements the requested staged driver: pad survey, chip enable/reset, CLI10 I2C probe, power-up `CORE_RESET_NTF` version parsing, NCI reset/init, and optional RF discovery. Its host model passes 118 checks and all 15 mutation tests; the full ARM64 kernel linked with the expected symbols. A bootable `a7-ios-system-nfc1` image exists, but it has not been booted on the phone (`research/ios26-nfc-r1/DESIGN.md:32-69`, `receipts/tests-m1box.txt:1-3`, `receipts/build_nfc1.out:3-16`, `receipts/kernel-verify.txt:1-24`).

The first milestone is therefore **physical stage-2 proof of the ST21NFC hardware/firmware versions**, not more host-only driver code. NCI init is stage 3. Kernel tag detection is stage 4 and is still not an iOS NFC service: there is no `nfcd`/Stockholm-compatible provider and no `nfcd` HKL mirror rule yet (`research/ios26-nfc-r1/DESIGN.md:109-116`).

All `xnu/...` line references below are to `hk-nfc1` unless explicitly marked as the haptics reference on the restored shared tree.

## 1. What it does today

### 1.1 Device-tree hardware contract

Source: `research/ios26-dualboot-r8/truth/fdt.dts`.

| Item | What the FDT says | Driver interpretation / evidence |
| --- | --- | --- |
| NFC controller and bus | `st21nfc@8`, compatible `st,st21nfc`, 7-bit I2C address **0x08**, under `i2c@3a331000` (CLI10); the bus is `okay` and its nominal FDT frequency is 1 MHz (`fdt.dts:12823-12842,12857-12872`). | `CHIP_ADDR 0x08` at `xnu/bsd/dev/blazer_nfc_hw.c:105`; the driver deliberately uses 400 kHz timing at `:92-95,500-517`, as haptics does. |
| Shared-bus peers | eUSB2 repeater at **0x3e** (`fdt.dts:12844-12855`) and CS40L27B haptics at **0x43** (`:12874-12896`) share CLI10. | Only address 0x08 is allowed for NFC. No bus clear or DesignWare controller reset; the bus is serialized with haptics (`blazer_nfc_hw.c:8-14`). |
| Chip enable / reset | `reset-gpios = <hsion 1 0>` (`:12861-12864`), named `AP2NFC_CHIP_EN_1V2` in the HSION line table (`:24256-24271`). Its sleep state is output-high (`:24353-24368`). | Treated as active-high enable/reset, page `0x0c581000`. `en_set()` drives DOUT before OE and refuses an unexpected mux; `power_up()` applies a 30 ms low interval only if the chip was already on, then drives high (`blazer_nfc_hw.c:404-453`). Active-high behavior remains an FDT/HAL inference until PHYSICAL. |
| Power-state input | `pidle-gpios = <hsion 3 0>`, `st,pidle_active_check`; the line is `NFC2AP_PWR_STATE_1V2` (`:12864-12866,24271`), configured input/pull-down (`:24452-24467`). | Read-only survey in `pads_read()` (`blazer_nfc_hw.c:219-223`); no PIDLE write exists. |
| Host IRQ | `irq-gpios = <gdmc 3 0>` and `interrupt-parent = <gdmc>` (`:12861-12864`); GDMC line 3 is `NFC2AP_HOST_IRQ_1V2` (`:26915-26928`), input/pull-down/function `gdmc_int` (`:27086-27101`). | Read-only at page `0x06483000`. If input is enabled, the driver polls RX high before reading; otherwise it polls the I2C read at 5 ms intervals (`blazer_nfc_hw.c:225-234,672-731`). There is no GIC IRQ handler yet. |
| ST options | `st,extpad_control_en` and `st,clk_pinctrl_switch` (`:12865-12870`). | The meaning/effect of `extpad_control_en` is not established by this investigation; the driver does not guess at it. |
| 19.2 MHz clock | Default/func pinctrl selects CPM CLKOUT0 and CLKOUT0_EN (`:12867-12870,24868-24883,25152-25169`); the named clock is `AP2NFC_CLK_19P2MHZ_1V2` (`:24515-24530`). | **Not touched.** Whether identification or RF needs this clock is still open (`research/ios26-nfc-r1/DESIGN.md:109-112`). |
| Firmware-download interface | No separately named firmware-download GPIO is present in `st21nfc@8`. | Loader mode is recognized from `CORE_RESET_NTF` and stops before NCI (`blazer_nfc_hw.c:781-802`). No firmware download is implemented or authorized. Do not relabel the chip-enable, PIDLE, IRQ, or eSE pins as a guessed download pin. |
| Companion eSE | Separate `ese@0`, compatible `st,st54spi`, `power_mode = "ST54L"`, on `spi@db51000`, with its own enable/reset/CS (`fdt.dts:13872-13911`). | **Not the NFC I2C transport and never touched** (`blazer_nfc_hw.c:12-13`). ST54L is the package/platform context, not evidence for an SPI NFC driver. Apple Pay/eSE operation is out of scope. |

### 1.2 Kernel implementation that already exists

The restored shared `p1` tree was verified not to contain the `blazer-nfc` string (`research/ios26-nfc-r1/receipts/build_nfc1.out:13-16`). The unmerged `hk-nfc1` commit adds seven files/changes:

- **XNU glue:** `xnu/bsd/dev/blazer_nfc.c`. `blazer_nfc_init()` is off without `blazer_nfc=N`, accepts stages 1..4 plus delay/listen/keep arguments, and starts one delayed thread (`:102-144`). `nfc_thread()` maps only the allow-listed pages, calls `nf_run()`, and prints a terminal result (`:21-31,102-119`). Logging uses the stable prefix `blazer-nfc: ` (`:86-95`).
- **Pure hardware/NCI logic:** `xnu/bsd/dev/blazer_nfc_hw.c` and `.h`. Stages are defined at `blazer_nfc_hw.h:14-20`; the ops/state interface is at `:22-62`. This is the same host-testable split as haptics.
- **Ordered state machine:** `nf_run()` performs `pads_read()`; then takes the CLI10 lock; then `votes()`, `block_check()`, and `probe()`; then conditionally `nci_init()` and `discover()`; finally RF-off, bus-down, enable restoration, and unlock (`blazer_nfc_hw.c:997-1020`).
- **Haptics-derived power/bus sequence:** `votes()` repeats the physical haptics LPB/SMC/LPCM votes and CLI pull setup (`:354-384`; compare shared `blazer_haptic_hw.c:333-366`). `block_check()` requires the DesignWare component type and existing CLI10 I2C mux (`blazer_nfc_hw.c:386-402`; compare `blazer_haptic_hw.c:370-390`).
- **Bounded transport:** `read_bytes()` bounds outstanding reads and reports aborts (`blazer_nfc_hw.c:582-622`); `send()` permits only the stage-gated command table and retries writes three times (`:119-127,624-649`). `read_packet()` handles the ST three-byte header, separate payload read, and leading idle bytes (`:672-731`).
- **Identification:** `on_ntf()` rejects loader mode and parses HW, FW, loader, NCI, and manufacturer fields from `CORE_RESET_NTF` (`:774-803`). `probe()` requires both an address ACK and the power-up reset notification (`:909-926`).
- **NCI handshake:** `nci_init()` sends `CORE_RESET`, waits for its response and reset notification, then sends NCI 2.0 `CORE_INIT` (`:928-945`). `transact()` matches the response GID/OID and requires status zero (`:842-877`).
- **Optional reader-mode proof:** `discover()` enables ST NFC mode and poll A/B/F/V discovery, listens for a bounded interval, and logs technology/protocol/ID when parsed (`:947-964`; notification parsing at `:750-840`). This is not NDEF or Core NFC.
- **Shared haptics locking:** `xnu/bsd/dev/blazer_cli10_bus.h:1-9` declares the lock. It is defined in `xnu/bsd/dev/blazer_haptic.c:36-38`; haptic ROM service returns `EBUSY` when NFC owns the bus (`:75-77`), and the initial haptic run also locks (`:216-218`).
- **Build/init registration:** `xnu/bsd/conf/files:132-133`; `blazer_nfc_init()` after haptics in `xnu/bsd/kern/bsd_init.c:736-737`.
- **Safety gates:** physical-address and CPM-frame allow-lists are at `blazer_nfc_hw.c:152-205,242-301`. Cleanup is in `rf_off()`, `bus_down()`, and `en_restore()` (`:455-478,520-536,966-984`). `blazer_nfc_keep=1` intentionally skips enable restoration and should not be used for the first probe.

### 1.3 Evidence available now

- **HOST:** 118 checks pass and 15/15 mutants are caught on both m1box and Mac (`research/ios26-nfc-r1/receipts/tests-m1box.txt:1-3`, `tests-mac.txt:1-3`). The cases cover no-chip, NAK/idle handling, loader mode, NCI errors, cleanup, and bus faults (`DESIGN.md:58-65`).
- **ARM64:** the full build succeeded; `_blazer_nfc_init`, `_nf_init`, `_nf_run`, and the CLI10 lock symbols are present, with no undefined symbols (`receipts/build_nfc1.out:4-12`, `kernel-verify.txt:1-24`).
- **HOST image check:** `a7-ios-system-nfc1` is marked bootable and uses `blazer_nfc=4 blazer_nfc_wait=30` (`research/images/a7-ios-system-nfc1/manifest.json:34-39,60-75`). This is an image-format check, not a boot result.
- **QEMU:** no NFC hardware exists in the rig; a QEMU boot without phone-only arguments cannot identify the controller (`research/ios26-nfc-r1/DESIGN.md:103-107`). No QEMU NFC pass is claimed here.
- **PHYSICAL:** none (`DESIGN.md:68-69`). `docs/debug/BACKLOG.md:45` still lists NFC as not assigned/no test, while `docs/probes.yaml:654-679` contains the prepared acceptance markers.

## 2. What is missing

1. **PHYSICAL pad survey.** HSION/GDMC page indexing and `DMUX_GPIO=1` are inferred from other Laguna blocks. Stage 1 must show sensible enable, power-state, and IRQ pad values before any write. A fault after `next gdmc pad 3` would specifically challenge the GDMC mapping.
2. **PHYSICAL power + enable + bus ACK.** No phone result proves active-high enable, the 30 ms pulse, the haptics-derived votes on this consumer, or an ACK at 0x08.
3. **First milestone: controller ID / firmware version.** Require a power-up `CORE_RESET_NTF` parsed into nonzero/plausible HW/FW versions, plus `address 0x08 acked, power-up reset ntf received`. A bare I2C controller ID or ACK alone is not the NFC controller ID.
4. **PHYSICAL NCI init handshake.** Stage 3 must return status zero for `CORE_RESET` and `CORE_INIT`, receive the second reset notification, and print `nci init ok`. Host-model responses do not prove the real firmware accepts this sequence.
5. **Clock/RF configuration answer.** If stage 2 NAKs, or stage 4 reports a generic error/no RF, determine whether CPM CLKOUT0 or ST configuration is required from the stock HAL/vendor path. Do not toggle CPM clock pads speculatively.
6. **Loader/firmware path, only if actually needed.** Loader mode currently stops cleanly. There is no verified firmware image/download state machine, and none should be attempted before recovering the exact stock protocol and owner approval.
7. **Production transport features.** The prototype polls rather than registering an interrupt, has no runtime PM, and holds CLI10 for an entire run. Those are acceptable for a bounded first probe, not a finished always-on NFC service.
8. **iOS service integration.** There is no Apple Stockholm/`nfcd` ABI implementation, IOKit-facing NFC provider, NDEF/Core NFC path, or eSE support. A kernel `tag:` line proves only kernel RF discovery. The release XNU search exposes no Apple NFC implementation to reuse; generic PN53x/libnfc drivers do not match this ST controller or Apple's user-space ABI (`docs/reuse/2026-11-02/media-radios.md:149-153`).
9. **`nfcd` observability.** The obs1 mirror list does not include `nfcd` (`research/ios26-nfc-r1/DESIGN.md:113-114`). Its requests/errors cannot yet be correlated with the kernel probe through `HKL nfcd[...]` lines.

## 3. Fix path and exact proof tests

### 3.1 Reuse and validate the existing rungs

Do not rewrite the transport. Use `hk-nfc1`; for stage-specific first boots, rerun the existing image recipe with a new image name and only the NFC tokens in `research/ios26-nfc-r1/tools/mkimg_nfc1.sh:11,24` changed. The driver needs no source change for stages 1..4. The already-built image is the combined stage-4 run.

| Order | Boot arg | Exact code path | Required evidence before advancing |
| --- | --- | --- | --- |
| 1. Read-only pad admission | `blazer_nfc=1` | `blazer_nfc_init()` → `nfc_thread()` → `nf_run()` → `pads_read()` (`blazer_nfc.c:103-144`; `blazer_nfc_hw.c:210-237,997-1005`) | Enable/power/IRQ pad lines appear; no CPM/I2C/pad write; `ends: ok, stage 1`. Stop on a pad fault, unexpected mux, or implausible values. |
| 2. **First milestone: ID/FW** | `blazer_nfc=2` | `votes()` → `block_check()` → `probe()` → `power_up()`/`bus_up()` → `read_packet()`/`on_ntf()` (`blazer_nfc_hw.c:355-453,500-517,672-731,774-803,909-926`) | `controller type 0x44570140`; `chip enable high`; `chip st21nfc fw 0x........ hw 0x.. ...`; `address 0x08 acked, power-up reset ntf received`; `ends: ok, stage 2, chip answered`; enable restored. This is the controller-ID/firmware-version pass. |
| 3. NCI handshake | `blazer_nfc=3` | `nci_init()` and `transact()` (`blazer_nfc_hw.c:842-877,928-945`) | `rsp CORE_RESET status 0x0`, a following reset NTF, `rsp CORE_INIT status 0x0`, `nci init ok`, clean stage-3 end/restoration. |
| 4. Optional kernel tag proof | Existing `blazer_nfc=4 blazer_nfc_wait=30` | `discover()` and notification parser (`blazer_nfc_hw.c:750-840,947-984`) | `rsp ST_NFC_MODE_ON status 0x0`, `rsp RF_DISCOVER status 0x0`, `discovery on`; with an owner-held card, a `tag:` line and `ends: ok, stage 4`. No tag is required for the stage-2/3 milestones. |

The combined stage-4 image also yields the stage-2 and stage-3 markers before RF discovery. Thus it can be the first combined hardware run after the read-only pad admission; a later RF failure does not erase an already valid ID or NCI-init result. `docs/probes.yaml:666-677` treats identification as partial success and tag discovery as full kernel-side success.

### 3.2 Exact existing-image test and log readout

For the prepared combined run, the coordinator/phone owner should use the normal temporary-boot admission path (no installation or partition change):

```sh
# Attended live console; boot ends at the configured deadline.
tools/live_boot.sh research/images/a7-ios-system-nfc1

# In a second terminal, split the growing live console.
python3 -I tools/hklog.py --follow <live-attempt>/console.txt -o /tmp/nfc-hk

# After the run, evaluate the prepared NFC contract and return to Android.
hk logs --grep 'blazer-nfc' <attempt>
python3 -I tools/probe_eval.py <attempt> --only nfc
hk back
```

Alternatively, the prepared unattended entry is `hk queue add research/images/a7-ios-system-nfc1 --note "nfc1: ST21NFC stages 1-4 + haptic tap coexistence"` (`research/ios26-nfc-r1/DESIGN.md:71-97`). For a stage-2-only first-milestone run, substitute the stage-2 image described above and require every stage-2 row in the table. Do not publish raw packet dumps, firmware blobs, tag UIDs, or device serials in the report.

Haptics is the regression check: taps after the NFC run should return `rc 0`; a tap during the run may be skipped with `rc 16`/`EBUSY`. Any persistent tap failure, USB-repeater/console failure, or failure to restore the enable pad blocks promotion (`DESIGN.md:94-97`; `blazer_haptic.c:75-77`).

### 3.3 Add `nfcd` observation, then design the service from evidence

1. Add **`nfcd` to the full existing `PROGRAMS` list** in `research/ios26-phaseb-r1/live/obs/tools/obs_overlay.py:45-47` (or pass the full list plus `nfcd` through `--programs`, not `--programs nfcd` alone). Regenerate overlay record 39 (`hk_env`) with the same `hk_logmirror.dylib` record 50; the format and 1024-byte bound are checked at `obs_overlay.py:58-105`.
2. On a later obs-capable image, use `hk logs nfcd`, or split a dump/live console with `python3 -I tools/hklog.py --grep hkl/nfcd.log <kernel.log>`. For live operation, keep the `--follow .../console.txt` reader above running and watch `hkl/nfcd.log`. `HKL` is the daemon's os_log/stderr mirror, while `blazer-nfc:` remains the kernel hardware trace (`research/ios26-phaseb-r1/live/OBS.md:30-60,187-218`).
3. Only after stage-2/3 physical proof and captured `nfcd` expectations, recover the exact Apple NFC/Stockholm user-client or XPC contract and implement the minimal compatible provider. Do not expose a generic NCI packet socket and call it iOS NFC. Keep RF tag/NDEF work separate from eSE/payment work.
4. When promoting the probe, integrate the existing build/image gates as well as the driver: `xnu/bsd/conf/files`, `bsd/kern/bsd_init.c`, the haptics CLI10 lock, `docs/probes.yaml:654-679`, and the NFC additions to `PHONE_ALLOWED`/kernel-string checks shown in `research/ios26-nfc-r1/receipts/image_tool.diff:5-12`. Re-run the host model and ARM64 object/symbol checks on the chosen integration base.

## 4. Risks and stop conditions

- **Shared CLI10 collateral.** The USB repeater and haptics share the wire. A bus clear, controller reset, wrong-address write, or unserialized haptics transaction can break unrelated functions. Keep the 0x08-only rule and CLI10 lock; stop on bus-busy or unexpected aborts.
- **Pad-map/power assumptions.** HSION/GDMC mapping and active-high enable are not physically proven. Stage 1 is mandatory for a conservative bring-up. `en_set()` only changes mux 0→GPIO and refuses a foreign function; do not relax that guard to make a failure disappear (`blazer_nfc_hw.c:407-435`).
- **CPM clock side effects.** CLKOUT0 is a shared CPM resource and is currently untouched. NAK/no-NTF or RF errors are clues, not permission to write arbitrary CPM pads. First compare the recovered stock HAL/clock sequence.
- **ST54L package/eSE.** The eSE has a separate SPI interface and enable, but it shares the package/platform. Do not probe SPI, assert eSE lines, attempt firmware download, or infer payment support from NFC NCI success.
- **Long bus ownership.** Discovery holds CLI10 for the listen interval (30 s in the built image, up to 60 s accepted), so haptic feedback is intentionally skipped during that window. Keep discovery bounded and restore the bus/pad on every exit.
- **Polling and malformed peers.** The driver polls IRQ/RX and bounds packets, but a real chip can expose timing or framing cases absent from the model. `no-ntf`, `bad-packet`, repeated NAKs, or a generic NCI error must stop the run rather than trigger retries with new register writes.
- **Loader mode.** `chip in loader mode` is a stop condition, not a request to invent a downloader. No firmware image or download command is part of this plan.
- **Host/ARM64 evidence ceiling.** The model can faithfully reproduce a wrong assumption. Linked symbols and 118 host checks justify a staged physical probe, not a claim that the controller works.
- **Older integration base.** `hk-nfc1` is based on obs1, and the prepared command line still contains `hk_bright=140` (`manifest.json:38`), whose known CoreBrightness/backboardd issue was removed in the later r3 line (`NOTES.md:22-26`). Do not misattribute an old compositor failure to NFC; rebase/revalidate before claiming integrated UI+NFC acceptance.
- **Service confusion and privacy.** Kernel RF discovery does not make `nfcd`, Core NFC, NDEF, or Apple Pay work. Keep raw NCI payloads and tag identifiers in restricted attempt evidence, not in summaries or committed documentation.
