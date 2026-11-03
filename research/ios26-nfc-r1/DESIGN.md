# NFC r1: ST21NFC/ST54L power, identify, report (2026-11-03, m1box + Mac, no phone)

Labels: **SOURCE** (FDT, ST's HAL, our code), **HOST** (model test on m1box and the Mac), **ARM64** (the linked kernel), **QEMU**,
**PHYSICAL** (none yet), **INFERENCE**. Nothing here touched the phone.

## 1. The controller (SOURCE: `research/ios26-dualboot-r8/truth/fdt.dts`)

| What | FDT | Pad / address |
| --- | --- | --- |
| controller | `st21nfc@8`, `compatible = "st,st21nfc"`, on `lsioe_cli10_i2c: i2c@3a331000` (lines ~12857) | I2C address **0x08**, the haptics' bus (CS40L27B 0x43) and the eUSB2 repeater (0x3e) |
| chip enable | `reset-gpios = <hsion_pinctrl 1 0>`, gpio-line-names[1] `AP2NFC_CHIP_EN_1V2`, pin XHSION_GPIO7 | `pinctrl@C580000` page 1 = **0x0c581000** |
| power state | `pidle-gpios = <hsion 3>` `NFC2AP_PWR_STATE_1V2` (`st,pidle_active_check`) | page 3 = 0x0c583000, read only |
| host IRQ | `irq-gpios = <gdmc_pinctrl 3>` `NFC2AP_HOST_IRQ_1V2`, function gdmc_int, pull-down | `pinctrl@6480000` page 3 = 0x06483000, read only |
| 19.2 MHz clock | `st,clk_pinctrl_switch`; default state CLKOUT0/CLKOUT0_EN as cpm_int (off), "func" state cpm_clkout | CPM pads, **not touched** (OPEN) |
| eSE | `ese@0` `st,st54spi`, ST54L, its own `ese_chip_enable-gpio <hsion 6>` on spi | **not touched** |

ST54L = ST21NFC NFC controller + eSE in one package. Pad page = gpio-line-names index: the same rule holds for the Wi-Fi pads on
`pinctrl@3C590000` (page 0x0d = `AP2WLAN_REG_ON_1V2`, physical in blazer_pcie1). HSIO_N (`sswrp_hsio_n_pd`, on-at-init) is the USB
console's domain, so the pads are readable whenever the console runs. GDMC's pinctrl has no power-domain (INFERENCE: always on).
Stock sleep state of the enable pad is output-high: **high = on** (INFERENCE from the FDT; the kernel driver source was unreachable).

ST HAL facts (SOURCE: android `platform/hardware/st/nfc` main, `st21nfc/adaptation/i2clayer.cc`, `st21nfc/hal/hal_fd.cc`,
`st21nfc/hal_wrapper.cc`; facts only, nothing copied):
- open = a **30 ms pulse** on the reset line, then the chip sends **CORE_RESET_NTF (60 00 …)** by itself.
- reads: **3-byte header**, then the payload length `b[2]` as a **second, separate read**; leading **0x7E** bytes are idle (shifted out).
  Writes retried 3× with 4 ms. IRQ polarity set high; data pending while high.
- CORE_RESET_NTF (router mode, `b[1]==0 && b[3]==1`): HW version `b[8]`, **FW version `b[10..13]`** (big-endian 32 bit), loader
  `b[14..16]`, customer `b[31..32]`. Loader mode: `b[2]==0x39 && b[3]==0xA1`, or ST54L `b[2]==0x41 && b[3]==0xA2`.
- commands: CORE_RESET `20 00 01 01`, CORE_INIT (NCI 2.0) `20 01 02 00 00`, ST NFC mode on `2F 02 02 02 01`.
- NCI 2.0 (spec): RF_DISCOVER `21 03`, RF_INTF_ACTIVATED_NTF `61 05`, RF_DISCOVER_NTF `61 03`, RF_DEACTIVATE `21 06 01 00` (idle).

## 2. Driver (SOURCE; branch **hk-nfc1** = hk-obs1 2841211 + one commit, Mac nested repo)

Files (`xnu-src/`, full copies; patch `receipts/0001-hk-nfc1.patch`):

| File | What |
| --- | --- |
| `bsd/dev/blazer_nfc_hw.{h,c}` (new, pure) | the logic, no XNU types; the host test compiles this file |
| `bsd/dev/blazer_nfc.c` (new) | boot args, mappings, one thread after `blazer_nfc_delay` (default 60 s), prefix `blazer-nfc: ` |
| `bsd/dev/blazer_cli10_bus.h` (new) | `blazer_cli10_enter/exit`: one owner of the bus |
| `bsd/dev/blazer_haptic.c` | defines the cli10 lock; the ID stage runs under it; each ROM effect try-locks it (busy → EBUSY = tap skipped, the tap policy's existing path) |
| `bsd/conf/files`, `bsd/kern/bsd_init.c` | the two files; `blazer_nfc_init()` after `blazer_haptic_init()` |

Boot args: `blazer_nfc=1..4`, `blazer_nfc_wait=1..60` (stage 4 listen, default 20), `blazer_nfc_delay=30..600`, `blazer_nfc_keep=1`.

| Stage | Does | Writes |
| --- | --- | --- |
| 1 pads | reads PARAM/DMUX/TX/RX of the enable, power-state and IRQ pads (HSIO_N first, then "next gdmc pad 3" so a fault is located) | none, no CPM, no I2C |
| 2 probe | haptics' votes frame for frame (LSIO_E on, SMC PD/clk, LPCM clocks, CLI pulls, rate, reset deassert), DesignWare + I2C pad mux check, enable high (30 ms low first if it was on; mux 0→GPIO only), TAR 0x08, read the power-up CORE_RESET_NTF (IRQ if its input is enabled, else polled reads every 5 ms, 1 s) | CPM frames as haptics; enable pad TX (+DMUX 0→1); I2C regs |
| 3 init | CORE_RESET → RSP + NTF, CORE_INIT → RSP | + two NCI commands |
| 4 discover | ST NFC mode on, RF_DISCOVER poll A/B/F/V, listen `blazer_nfc_wait` s for RF_INTF_ACTIVATED/RF_DISCOVER (tech, protocol, NFCID1/NFCID0/UID), RF_DEACTIVATE | + three NCI commands |

Safety: a PA allow-list (pages above only; writes only MBA, CLI pulls, I2C, enable pad DMUX/TX), a CPM frame allow-list (haptics'),
an NCI command table gated by stage (nothing else can be sent), a packet bound per wait (64), every way out: RF off → controller
disabled → enable pad back to the found TX/DMUX (unless keep) → bus lock released. Never: the eSE, the clock pads, the I2C pads,
a bus clear, a controller reset, another address, a PMIC frame.

## 3. Evidence so far

- **HOST** `tests/run.sh` (m1box `receipts/tests-m1box.txt`, Mac `receipts/tests-mac.txt`): model of CPM mailbox, DesignWare I2C
  (abort flush until CLR_TX_ABRT, STOP_DET, RX FIFO bound 64), pads, ST21NFC. **118 checks PASS** under ASan/UBSan; **mutants 15/15
  caught**. Cases: stage 1 reads only; stage 2 versions parsed and pad restored; stage 3 exactly two commands; stage 4 tag (UID
  04a1b2c3d4e5f6) and no tag; IRQ unreadable (idle bytes, NAKs); no chip; enable found on (≥30 ms off, left on); loader mode (no NCI);
  NCI error; CPM dead (no pad/I2C write); bus busy; idle-byte shift; chatty chip bounded; foreign mux never written; mux 0 set and
  restored; keep; refusals (stage-gated command, eSE pad, IRQ pad).
- **ARM64** single-file `clang --target=arm64-apple-darwin -ffreestanding -Werror` of blazer_nfc_hw.c: `_nf_init _nf_run _nf_stop_name`.
  Full kernel and its verify: section 5.
- **QEMU**: no NFC hardware. Section 6.
- **PHYSICAL**: none.

## 4. Phone test (designed here; the coordinator runs it, the phone owner admits it)

Image **a7-ios-system-nfc1** (`tools/mkimg_nfc1.sh`) = a7-ios-system-obs1's recipe with kernel.nfc1 and one line change:
`hk_ustack=Preferences,MobilePhone` → `blazer_nfc=4 blazer_nfc_wait=30` (1015 B ≤ 1023). Overlay obs1-r1 unchanged.
Owner optional: hold an NFC card/tag flat on the back of the phone, upper half, from about 60 s after the iOS kernel starts for 30 s.

```
hk queue add research/images/a7-ios-system-nfc1 --note "nfc1: ST21NFC stages 1-4 + haptic tap coexistence"
# or, attended: tools/live_boot.sh research/images/a7-ios-system-nfc1   (console streams; boot ends at the 900 s deadline, then hk back)
hk logs --grep 'blazer-nfc' <attempt>
python3 -I tools/probe_eval.py <attempt> --only nfc
```

Expected lines (order), each the evidence for its rung:

| Rung | Success line | First failure line → meaning |
| --- | --- | --- |
| thread | `blazer-nfc: stage 4, starts in 60 s` | absent → kernel/line wrong |
| 1 pads | `blazer-nfc: pad chip-enable (hsion 1) param … dmux 0x1 tx … rx …`, `pad host-irq (gdmc 3) … irq readable` | panic after `next gdmc pad 3` → GDMC pads not readable this way; `dmux` ≠ 0/1 → `stop enable-pad` |
| 2 votes | `blazer-nfc: lsio_e 2 (2 on)`, `i2c clock 200000000 Hz`, `controller type 0x44570140` | `stop mba/lsioe-off/smc/lpcm` → as haptics |
| 2 power/probe | `blazer-nfc: chip enable high`, `rx N bytes: 60 00 …`, **`blazer-nfc: chip st21nfc fw 0x%08x hw 0x%02x loader … nci 0x20 manuf 0x02 …`**, `address 0x08 acked, power-up reset ntf received` | `address 0x08 never acked` + `stop nak` → chip not powered (enable polarity/mux, or needs the clock); `acked, … not received` + `stop no-ntf`; `chip in loader mode` → firmware not in router mode |
| 3 init | `rsp CORE_RESET status 0x0`, `rsp CORE_INIT status 0x0`, **`nci init ok: nci 0x20, fw 0x…`** | `stop nci-status, detail 0x1NN` (NN = NCI status) |
| 4 discover | `rsp ST_NFC_MODE_ON status 0x0`, `rsp RF_DISCOVER status 0x0`, `discovery on (poll a/b/f/v), listening 30 s`, then with a card **`blazer-nfc: tag: nfc-a, protocol 0x…, id …`** or `discovery: no tag after N rf notifications` | `core generic error ntf, status 0x…` → RF needs ST config/clock (OPEN) |
| end | **`blazer-nfc: ends: ok, stage 4, chip answered, fw 0x…, ntfs N, tags M`**, `chip enable restored to tx 0x… (ok)` | any `ends: <stop>` names the rung |
| coexistence | haptic taps after the NFC run still `blazer-haptic: tap N rc 0`; a tap during the run is `rc 16` (EBUSY, skipped) | a `tap … rc` other than 0/16 → regression (tap feedback turns off) |

Return check after the boot as always (`hk back`). The boot changes no partition; the NFC chip is left as found (off).

## 5. Kernel and image (Mac; build lock held, p1 restored)

| Artifact | sha256 / id | Where |
| --- | --- | --- |
| XNU branch **hk-nfc1** | **`f4fa53021d154cb99906f7325056b421bcb92d08`** (one commit on hk-obs1 2841211; message ends `src-sha256: 69a1a54d…`) | Mac nested repo `research/ios26-release-r1/work/xnu`; tree restored to p1 b228c4f |
| patch `receipts/0001-hk-nfc1.patch` | the commit as `git format-patch` (8 files) | here; full files in `xnu-src/` |
| `build/kernel.nfc1` | `d458026064e52c301fb243449b80dc58ca67d1260b715db8d94da570f86453ce` | m1box + Mac, not for git |
| `build/kernel.nfc1.unstripped` | `381b948ee3d7f465d6499ec0eb20e7bcf32a78ec730827ae4dc8cfce26a732a2` | same |
| **a7-ios-system-nfc1** boot.img | **`ee451c6c5dc49f13fdc22fcee5027f734f63ea1e383430406d25382ae867db16`** | `research/images/` (Mac, copied to m1box) |
| payload-usb.bin / manifest.json | `55e68a4c…be334` / `57390a5e…2863e` | same |
| `tools/image_tool_nfc1.py` | `ff71be4c5f556e62a0bfebdae33e4cec75d78726d427a3badef02487b1dec80d` (int1's 728bdd21 + the blazer_nfc tokens, `receipts/image_tool.diff`) | here |

- Build (`tools/build_nfc1.py`, `receipts/build_nfc1.out`): lock taken with no make running, tree p1 clean; branch made in a throwaway
  worktree (removed); `mk.sh -j8` rc 0; p1 checked out again and rebuilt rc 0; the restored p1 kernel has no `blazer-nfc: ` string.
- **ARM64** (`receipts/kernel-verify.txt`, llvm-nm/objdump on the unstripped kernel): **0 undefined symbols**; `_blazer_nfc_init _nf_init
  _nf_run _nf_stop_name _blazer_cli10_enter _blazer_cli10_exit` defined; `_bsd_init → _blazer_nfc_init` and `→ _blazer_haptic_init`;
  every format string once; no warning in a changed file. Objects (`receipts/kernel-verify-obj.txt`, branch relocations):
  `_haptic_thread`: lck_mtx_lock → `_hh_run` → lck_mtx_unlock (the cli10 lock, inlined), then the haptic lock as before;
  `_blazer_haptic_play_rom`: 2 lck_mtx_try_lock (haptic, cli10), `_hh_play_rom`; `_nfc_thread`: `_ml_io_map`, `_nf_init`, `_nf_run`;
  `_k_bus_enter/_exit → _blazer_cli10_enter/_exit`, `_k_cpm_* → _blazer_cpmq_*`.
- Image (`tools/mkimg_nfc1.sh`, `receipts/manifest-diff.txt`): versus obs1 only the kernel, the line (`-hk_ustack=Preferences,MobilePhone
  +blazer_nfc=4 +blazer_nfc_wait=30`, 1018 → 1016 B, 57 tokens) and what follows (sizes, placement, payload, AVB, nonces).
  `check`: `OK a7-ios-system-nfc1 bootable ee451c6c…` with image_tool_nfc1.py and with the Mac's shared `tools/image_tool.py` (acf48b98…).

## 6. QEMU (m1box TCG, `receipts/qemu-preflight-nfc1.txt`)

QEMU has no NFC, CPM, LSIO_E or HSIO_N pads, so `tools/qemu_preflight.py` drops `blazer_nfc*` (today as "not proven on the
rig"; `tools/patches/qemu_preflight.py.patch` lists it as PHONE_ONLY) and `blazer_haptic_tap`. **VERDICT PASS, 0 findings**: hk-nfc1's
kernel with obs1's line boots to the Home equivalent (409 s), panics 0, backboardd/SpringBoard never respawned, overlay 18 applied,
the same respawn set as obs1-era runs (fairplayd.H2 etc.). This shows only that the kernel change does not regress a boot without
the hardware. The transaction logic is covered by the HOST model (section 3). The NFC path itself is PHYSICAL-only.

## 7. OPEN

- The 19.2 MHz clock (`st,clk_pinctrl_switch`, CPM CLKOUT0): whether RF discovery needs it, or ST config (`CORE_SET_CONFIG` from
  libnfc-hal-st.conf), is unknown. Stage 4's first result will say (generic error NTF vs tag).
- nfcd: no mirror rule yet (the image keeps obs1's overlay). Once the kernel side identifies the chip, an iOS-facing service
  (nfcd's IOKit/XPC expectations) is the next lane; mirror nfcd via the overlay's HKL rule list then.
- Field-detect (listen mode, RF_FIELD_INFO_NTF 61 07) needs a listen-mode discover entry and routing config; not sent in r1
  (the parser logs `rf field info` if it ever arrives).
