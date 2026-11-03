# Modem, SIM/eSIM and GNSS investigation (iOS 26 on laguna)

Date: 2026-11-03. Read-only investigation; no build, phone action or source change. This document contains no radio images,
subscriber/device identifiers or raw daemon logs.

## Evidence boundaries and source references

- **SOURCE/FDT:** `research/ios26-dualboot-r8/truth/fdt.dts` is the saved Android device tree.
- **PHYSICAL/ANDROID:** `research/ios26-dualboot-r8/attempts/chooser-v1-r3-t1/android/dmesg.txt` proves how stock Android
  brings up the hardware. It is not an iOS result.
- **PHYSICAL/iOS:** the latest int3 capture is `research/laguna-usb-fix/attempts/live-20261103-232046-a7-int3/console.txt`.
  It contains no `blazer-modem` result. Older userland sightings are called out separately.
- **HOST/ARM64:** `research/ios26-modem-r1/receipts/host-tests.txt` records 97 passing checks and an ARM64 object with the
  expected modem symbols. `research/ios26-modem-r1/MODEM.md:71-80` also reports a Mac kernel build and explicitly says
  **PHYSICAL: none yet**. This investigation did not rebuild or boot either claim.
- **XNU:** paths below are under `research/ios26-release-r1/work/xnu`. The shared checkout is `p1` (`b228c4f`); the
  candidate modem topic is **`hk-modem1` (`a97bdc6`)**, based on `hk-int3`. The topic is not evidence of a phone boot.
- **Vendor reference:** the pinned, online-origin GPL CPIF snapshot is under
  `research/ios26-connectivity-r1/resources/s5400/`; its provenance and upstream URLs are in `resources/manifest.json`.
  The manifest explicitly says phone-source identity is unproven and no implementation was imported into XNU.

## 1. What it does today

### Hardware and transport established by FDT/stock Android

| Item | Finding | Evidence |
| --- | --- | --- |
| Baseband | External Samsung **S5400** CP, not an Apple/Intel baseband. | `fdt.dts:35242-35255`; Android `dmesg.txt:4824` |
| AP transport | **PCIe0**, `pcie@c500000`, HSIO_N, one lane, up to gen 4. CPIF selects PCI channel 0 and link name `PCIE`. PCIe1 is Wi-Fi and is a different device. | `fdt.dts:30889-30921`, `35242-35256`, `30924-30964` |
| PCIe0 ownership | `hsio_n_pcie_pd` is HSIO_N subdomain 1. PCIe0 has its own PHY/reset/ATU/config windows and CP CLKREQ/PERST pads. | `fdt.dts:31718-31724`, `30894-30921`, `24273-24312` |
| CP power/control | AP2CP power/reset/active pads plus CP2AP status pads are described in CPIF. CP PMIC and S5910 clock buffer are on a separate bit-banged SPMI bus. | `fdt.dts:35352-35368`, `35748-35774` |
| CP shared memory | Four reserved regions: IPC/GNSS staging (`cp_rmem`), MSI/boot registers (`cp_msi_rmem`), packet rings (`cp_rmem_1`) and CP/AOC voice (`cp_aoc_rmem`). These are Android-owned carvouts, not free XNU RAM. | `fdt.dts:950-975`, `35686-35744` |
| ROM link | Stock Android trains the CP boot ROM at gen 1 before downloading an image. | Android `dmesg.txt:7083`; summarized with the config ID at `research/ios26-modem-r1/MODEM.md:10-16` |
| Full boot | Stock userspace drives BL1, bootloader and normal-boot stages through `umts_boot0`, then handles INIT_START/PHONE_START. | Android `dmesg.txt:6834-6839`, `6893-6896`, `7157-7165`, `7259-7261`, `8155-8161`, `8196-8197` |
| Control protocol | **Samsung IPC/SIPC 5**, with `0xABCD` framing. It is not QMI, MBIM or AT. | `fdt.dts:35251-35256`; `resources/s5400/include/exynos_ipc.h:21,40-53`; channel map at `fdt.dts:35517-35682` |
| SIM/eSIM | The CP owns card access. AP-visible services are RIL IPC, remote files and an eSIM trace channel; there is no independent AP SIM driver in the investigated XNU. | `fdt.dts:35519-35536`, `35675-35682`; Android `dmesg.txt:6896` |
| GNSS | Samsung **KEPLER** has a 50 MHz SPI node and AP/AOC request/time-sync lines. Its image is transferred through the CP `gnss_boot` channel into the GNSS_FW subregion. | `fdt.dts:13661-13693`, `35737-35744`, `35777-35786`, `35657-35672`; Android `dmesg.txt:3523-3535`, `4809`, `4932-4933` |

The reserved-memory layout is more specific than “shared memory”: IPC occupies 8 MiB at `cp_rmem`, GNSS_FW the following
4 MiB, packet DL/UL rings occupy `cp_rmem_1`, and boot status lives in `cp_msi_rmem` (`fdt.dts:35694-35744`). The current
modem core refuses all four regions (`XNU:bsd/dev/blazer_modem_core.c:200-208`). XNU's low-bank allocator also does not
offer the large `0xe8000000..0xeb000000` CP span (`XNU:osfmk/arm/pmap/blazer_lowbank.h:10,29-33`); the other CP regions
are outside its offered ranges as well.

### XNU implementation that exists now

**Shared `p1`:** `blazer_modem=1` is only a delayed pad reader. Its header explicitly says no register writes, CPM frames,
PCIe, power or reset (`XNU:bsd/dev/blazer_modem.c:2-5` on `p1`), and `modem_probe` prints pad state
(`:37-53`). It has no SIM, GNSS or iOS-service integration.

**Candidate `hk-modem1`:** this superset is default-off and selected by `blazer_modem=N` or `hk_dbg` bits 24..27
(`XNU:bsd/dev/blazer_modem.c:2-8,179-200`). `bsd_init` calls `blazer_modem_init` (`XNU:bsd/kern/bsd_init.c:759-760`).
The XNU glue maps only an MMIO allowlist, supplies read/write/delay/CPM-lock operations and prints a terminal verdict
(`XNU:bsd/dev/blazer_modem.c:31-47,53-117,127-161`). The hardware-independent core runs these stages from `m0_run`
(`XNU:bsd/dev/blazer_modem_core.c:960-986`):

1. **READ:** mailbox magic and LPB domain reads, then CP/PCIe pad snapshots (`stage_read`, `:457-492`). It estimates whether
   the CP was off and refuses later power-on if that precondition is not met.
2. **CTRL:** PHY-clock put, PCIe0 power vote, init/power-up/PERST reset release and PHY SRAM status (`stage_ctrl`, `:495-543`).
   The CP remains off.
3. **PHY:** the existing 20,480-word laguna PCIe PHY table, root-port setup and gen-1/x1 restrictions (`stage_phy`, `:546-632`;
   table glue at `XNU:bsd/dev/blazer_modem.c:26-29`). The CP remains off.
4. **LINK:** PERST low, stock CP power-on sequencing, CLKREQ/PERST/LTSSM training, bus-1 ATU and read-only endpoint config
   identity (`stage_link`, `cp_power_on`, `train`, `map_bus_1`, `read_identity`, `:656-876`). No CP image is needed for this
   ROM-only milestone.

The current safety policy is narrow: CP reserved memory is denied, endpoint config writes are denied, only named CPM frames
are allowed, and only listed output pads/root-port registers can change (`m0_read_allowed`, `m0_write_allowed`,
`frame_allowed`, `:232-360`). `tidy` drives PERST low, stops LTSSM, powers the CP off and restores driven pads unless an
explicit hold was requested (`:881-953`). It deliberately leaves the PCIe power vote, released resets and PHY-clock put in
place (`XNU:bsd/dev/blazer_modem_core.h:4-9`).

The console already reports the useful first milestone: link speed/width, Samsung CP-ROM config ID, furthest stage, stop
reason and whether the CP was powered off again (`XNU:bsd/dev/blazer_modem.c:152-160`). `blazer_modem_obs` can format the
same state for HKOBS, but its own comment says it is **not hooked into `hk_obs.c`** (`:164-175`; compare
`XNU:bsd/kern/hk_obs.c:173-200`).

### What iOS userland does today

- The root is for `iPhone12,3`; the saved ARI reference says Intel basebands use ARI between the baseband and CommCenter,
  while Qualcomm uses QMI (`research/ios26-connectivity-r1/resources/aristoteles-readme.txt:11-17`). The S5400 instead
  expects Samsung RIL/SIPC. No SIPC-to-ARI translator, Apple baseband nub or CoreTelephony replacement exists here.
- A historical iOS capture did exec CommCenter and showed locationd as on-demand
  (`research/laguna-usb-fix/attempts/20261102-021907-wifi-stage2-r1/reader.txt:186,508`). That was not cellular service.
- The latest int3 physical capture execs only `CommCenterMobileHelper` (`console.txt:1647`). configd, SpringBoard,
  Preferences and MobilePhone report `com.apple.commcenter.coretelephony.xpc` as “No such process” (for example
  `:1178`, `2511`, `3987-3989`, `16272-16273`). Thus even the Apple-facing service prerequisite is currently absent in
  that configuration; its cause is not established by this investigation.
- The obs1 phone-root inventory includes CommCenter, locationd and **WirelessRadioManagerd**, with WirelessRadioManagerd in
  launchd's disabled set (`research/ios26-phaseb-r1/live/OBS.md:82-99`). It does not establish a literal `wirelessd`
  executable or a Samsung baseband path. Do not treat WirelessRadioManagerd/wirelessd as a substitute for CommCenter.
- locationd has no KEPLER/CoreLocation provider. A Samsung SPI endpoint by itself would not give locationd a position feed.

## 2. What is missing, by stage

### Cellular: transport -> image load -> control -> attach

| Stage | Existing reach | Missing work and proprietary boundary |
| --- | --- | --- |
| **A. Transport link-up** | Stages 1..4 exist on `hk-modem1`; host tests/ARM64 object exist; stock Android proves the hardware sequence. | No physical XNU result, no accepted candidate image receipt, no persistent HKOBS modem provider. First validate CP-off detection, PCIe0 power/PHY/reset, gen-1 link and read-only ROM ID. The CP's on-chip ROM is enough; no downloaded CP image is needed. |
| **B. ROM boot handshake** | Stage 4 stops after config reads. Vendor `set_cp_rom_boot_img` and `check_boot_status` show the next operations (`resources/s5400/modem_ctrl_s5100.c:1853-1930`). | No BAR0/doorbell assignment, endpoint bus mastering, MSI mapping, inbound ATU/IOMMU setup or CP-memory access. These are new DMA/ownership risks even before an image is loaded. |
| **C. CP image load / normal boot** | Stock Android proves BL1 -> bootloader -> main image and stage transitions. | No read-only active-slot image reader, staging into `cp_rmem`, boot-stage state machine, link retrain or INIT_START/PHONE_START handling. Full boot requires the phone's signed proprietary CP image, read at runtime with owner approval; the open CPIF source does not replace it. |
| **D. Control channel** | FDT supplies queue offsets/channels; GPL references supply outer framing and legacy circular-queue mechanics (`resources/s5400/link_device_memory_legacy.c:90-202`). | No XNU SIPC transport, interrupt/doorbell handling, channel lifecycle or Samsung RIL message implementation. Outer framing is not the closed RIL command set. QMI/MBIM/AT work would be the wrong protocol. |
| **E. NV/RFS prerequisite** | Android opens `umts_rfs0`; FDT names the channel. | No RFS server. A read-only server is required if the CP requests its calibration/configuration files. Every mutation must be refused; sensitive values and file contents must not enter logs. |
| **F. SIM/eSIM and radio attach** | CP owns card access; planned acceptance lines exist only in `docs/probes.yaml:621-636`. | No card status/APDU path, radio-power control, network selection or registration state. This needs CP online, RFS and reverse-engineered Samsung RIL. eSIM profile provisioning/modification is out of scope. |
| **G. Packet service** | FDT names `rmnet` and pktproc DL/UL rings; GPL ring layouts are available. | No pktproc DMA driver, PDP context, IONetworkInterface, address/DNS publication or packet test. This follows control/attach, not PCIe link-up. |
| **H. CommCenter integration** | Apple-facing clients and the ARI reference identify the expected kind of interface. | No SIPC↔ARI translation or alternative CoreTelephony provider; latest int3 lacks a running CommCenter service. A carrier indicator is therefore much farther away than a kernel registration probe. |

### GPS/GNSS separately

| Stage | Existing reach | Missing work and proprietary boundary |
| --- | --- | --- |
| **G0. Static/read-only survey** | FDT identifies SPI, request lines and shared-memory layout. A pad/controller read-only survey is reachable without transmitting or loading an image. | No `blazer-gnss` XNU driver exists. A survey alone proves neither KEPLER presence nor a fix. |
| **G1. KEPLER image and SPI ready** | Android shows `gnss_boot`/`gnss_dump` and KEPLER probe. Vendor PCIe code skips GNSS_FW ATU mapping during CP boot because it is loaded later (`resources/s5400/s51xx_pcie.c:398-407`). | Depends on CP normal boot and the CP transfer channel. Requires the proprietary KEPLER image, bounded GNSS_FW mapping, SPI transport and Samsung's control protocol. |
| **G2. Position/locationd** | locationd exists and is on-demand. | No LAL protocol implementation, GNSS session/time-sync handling, NMEA/fix decoder or CoreLocation provider. A location fix requires both proprietary image and closed-protocol work. |

**Scope honestly:** stages A and the non-DMA part of B are concrete near-term bring-up. Full cellular attach and GNSS are
large proprietary-firmware/protocol programs, not small follow-ups to PCIe enumeration.

## 3. Fix path

### First reachable phone milestone: power + PCIe0 ROM link + truthful report

Use the already implemented `hk-modem1` stage 4 design, in one later coordinator-owned unattended boot; this investigation
did not run it:

1. Confirm the candidate image contains `a97bdc6`, select stage 4 with `blazer_modem=4` **or** OR `0x04000000` into the
   existing `hk_dbg` word. Keep `blazer_modem_hold=0` and `blazer_modem_force=0`. The packed `hk_dbg` form avoids extending
   the nearly full integrated command line (`research/ios26-modem-r1/MODEM.md:47-65`).
2. Let `m0_run` execute READ -> CTRL -> PHY -> LINK once. It should power only the CP ROM, train gen 1/x1, read the Samsung
   ROM class/ID, then execute `tidy`; it must not stage an image or touch CP reserved memory.
3. Required evidence is all of: `blazer-modem: link: UP`, the expected CP-ROM class/ID line,
   `verdict: PASS stage 4, at id` with `CP off again`, and `tidy: ... errors 0x0`. The expected patterns and failure rows
   already exist at `docs/probes.yaml:585-619`. An Android return check is mandatory after the temporary boot.
4. Stop on CP-not-off, controller-already-live, mailbox/domain failure, four failed training attempts, wrong vendor, link
   loss or any tidy error. Do not use force/hold to turn a failed precondition into a pass.
5. Collect with `hk logs --grep 'blazer-modem:'`. Direct console output is sufficient for this first run; do not wait for an
   HKOBS integration to classify it.

As a small observability follow-up, declare/call `blazer_modem_obs` from `hk_obs_report` in `XNU:bsd/kern/hk_obs.c:173-200`,
and add a `modem` classification to `tools/hklog.py` (`SUBSYSTEMS`, currently `tools/hklog.py:36-55`). Preserve the direct
verdict as the authoritative first-boot receipt.

### Staged implementation beyond link-up

| Rung | Exact implementation seam | Exit evidence / gate |
| --- | --- | --- |
| **5: ROM handshake** | Extend `M0_STAGE_*` in `XNU:bsd/dev/blazer_modem_core.h`; add a `stage_rom_handshake` called by `m0_run`; extend the explicit windows in `blazer_modem.c` and the per-stage permissions in `m0_read_allowed`/`m0_write_allowed`. Model BAR0/doorbell, MSI boot status and inbound ATU after vendor `set_cp_rom_boot_img`, `check_boot_status` and `setup_iommu_mapping`. | Report initial boot-stage/MSI state and a bounded doorbell round-trip without an image payload; do not claim BL1 progress until rung 6. Keep `m0_is_cp_memory` as a backstop and add narrow region-specific exceptions; never globally allow CP RAM. Owner review is required before endpoint bus mastering/DMA. |
| **6: BL1 + bootloader** | Add a proposed `XNU:bsd/dev/blazer_modem_fw.c` for a read-only active-slot partition reader and bounded image staging; add core boot-state functions called after `stage_rom_handshake`. Reuse UFS/GPT resolution rather than hardcoding a slot. | Vendor-equivalent BL1/bootloader stage values, then CP off/tidy. Requires explicit owner approval for proprietary image execution. No partition writes and no image copies into git. |
| **7: Normal boot + SIPC link** | Extend the same firmware state machine for the main image and link retrain; add proposed `blazer_modem_sipc.c` for framing/queues and doorbell/MSI lifecycle, based on `exynos_ipc.h` and `link_device_memory_legacy.c`. | INIT_START/PHONE_START and CP ONLINE. Retrain/link loss must fail closed. |
| **8: Read-only RFS** | Add proposed `blazer_modem_rfs.c` behind `umts_rfs0`; implement open/read/close and explicit failure for every write/create/delete/resize request. | Requests served with zero mutations and no sensitive payload logging. |
| **9: SIM + registration** | Add proposed `blazer_modem_ril.c` over `umts_ipc`; first implement only card status, radio state and registration reporting. Keep eSIM trace/profile operations disabled. | `cell: SIM ready|absent|locked|error`, then `cell: registered <rat>` as defined in `docs/probes.yaml:621-636`. |
| **10: Data** | Add proposed `blazer_modem_pktproc.c` for bounded DL/UL rings and a new IONetworkInterface adapter; do not overload the Wi-Fi driver. | One PDP context, interface/address/DNS state and bidirectional packet test. |
| **11: Apple service** | Add a userland translation daemon or CoreTelephony-level provider after capturing the actual iPhone12,3 contract. The kernel SIPC/RIL driver remains below it. | CommCenter stays running and Settings reports real SIM/carrier state. Only then attempt call/SMS scope. |
| **G1/G2: GNSS** | Add proposed `blazer_gnss.c` (SPI/XNU glue) and `blazer_gnss_core.c` (bounded protocol state). Load through CP `gnss_boot` only after rung 7, map GNSS_FW only for that transfer, then start KEPLER SPI. A separate location provider feeds locationd. | `KEPLER ready`, then an owner-confirmed position. No raw location traces in tracked receipts. |

## 4. Risks and invariants

1. **Android firmware and slots are immutable.** Never flash, erase, reformat or update a modem partition; never write CP
   images into Android storage. Read the active slot's image at runtime only after approval. Preserve both slots and all
   backups. The first four stages must remain image-free.
2. **NV/RFS and eSIM are read-only.** Refuse every mutation, provisioning operation and reset-to-factory request. Do not log
   subscriber/device identifiers, file contents, authentication material or raw RFS/RIL payloads. A successful network
   attach is not permission to persist CP state.
3. **Reserved RAM is not a general-purpose pool.** The four CP carvouts remain excluded from XNU allocation. Current code
   denies them in both read/write allowlists and `m0_is_cp_memory`; retain all checks. The host mutation receipt has one
   surviving removal of a redundant CP-memory guard (`receipts/host-tests.txt:10`), so the allowlist backstop must not be
   deleted either.
4. **DMA raises the risk at rung 5.** Stage 4 reads endpoint config only. BAR assignment, bus mastering and inbound ATU can
   expose RAM to the CP. Require bounded IOMMU/ATU mappings, cache-coherency rules and link-down teardown before enabling
   them. Do not borrow Android's mappings blindly or map unrelated Android regions.
5. **Leave no live CP for Android to inherit unexpectedly.** Default to no-hold, CP-off tidy and pad restoration. Do not use
   `blazer_modem_force` when pads say the CP is active or the controller is already live. Note that tidy intentionally
   leaves PCIe power/reset/clock votes changed; this must be documented in the boot receipt and reviewed before power
   management is expanded.
6. **Do not touch neighboring owners.** The modem allowlist excludes UFS, Wi-Fi and NFC pads and never votes their domains
   off. Keep CPM queue locking (`blazer_cpmq_enter/exit`) around every frame. Do not speak SPMI to the CP PMIC/S5910 in the
   ROM-link milestone.
7. **Userland logs need redaction.** HKL can expose telephony and location data. Publish only bounded status lines, never raw
   CommCenter/RIL/location streams. Absence of a daemon log is not proof that hardware is absent.
8. **Evidence cannot be promoted across classes.** GPL-source agreement, host tests, QEMU thread execution and stock Android
   success do not prove an iOS phone link. Full attach requires separate physical proof at every rung.

## Debug tools for the first and later rungs

- **Kernel:** `hk logs --grep 'blazer-modem:'`; after the provider hook, `HKOBS ... modem:` should carry only stage, stop,
  CP/link state, speed/width, config ID and counters.
- **Host splitter:** `python3 -I tools/hklog.py <ramdump/kernel.log>` writes per-daemon `hkl/` logs and a summary;
  `research/ios26-phaseb-r1/live/OBS.md:187-218` documents live/follow use.
- **Apple daemons:** the obs1 overlay rule mirrors CommCenter, locationd and WirelessRadioManagerd as
  `HKL <prog>[<pid>] ...` (`OBS.md:70-99`). Use `hk logs CommCenter`, `hk logs locationd` and
  `hk logs WirelessRadioManagerd`; a literal `wirelessd` can be added only if a root inventory proves it exists.
- **Loss accounting:** check `HKL ... lines dropped` and `HKOBS ... con:/proc:` before concluding that CommCenter or
  locationd was silent (`OBS.md:120-148,167-180`). QEMU obs runs did not start CommCenter/locationd (`OBS.md:306-307`), so
  QEMU cannot validate their modem attachment.

The immediate next action remains exactly the backlog item: a PCIe0 link-up kernel and one unattended link-state boot
(`docs/debug/BACKLOG.md:35`). SIM waits on modem boot (`:49`); GPS is not independently assignable yet (`:38`).
