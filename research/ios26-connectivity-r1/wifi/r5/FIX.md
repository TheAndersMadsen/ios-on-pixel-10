# W1 r5: the dongle drops packets for want of a host RX buffer; 1024 buffers instead of 64 (2026-11-03, m1box + Mac, HOST + QEMU)

Labels: **physical** = phone log already captured (r1–r3); **firmware** = static reading of Android's `.57.31` `fw_bcmdhd.bin_4390_b1`
(db46afd6) with its map (12cf6569), Thumb-2 RAM code at load address 0x2a0000 (ROM can't be read); **source** = Pixel 10 bcmdhd `bcm4390/*.c`;
**host** = built and run on m1box; **QEMU** = m1box rig; **inference** = untested. Nothing touched the phone. No name, password, PMK or
passphrase was printed, logged or committed. r4 (`a7-wifi-join-r4`) was never booted; r5 contains all of r4.

## 1. What "status 4, reason 14" is (it is not an IEEE reason code)

`join: 4-way handshake: status 4, reason 14` is our print of the dongle event `WLC_E_PSK_SUP` (46). Its `status` is Broadcom's
`sup_auth_status_t`, 4 = `WLC_SUP_KEYXCHANGE_WAIT_M1`. Its `reason` is Broadcom's supplicant reason, 14 = `WLC_E_SUP_DEAUTH`
("received FC_DEAUTH") (`wlioctl_defs.h`, `bcmevent.h`, as r2–r4 FIX §1). It is **not** IEEE 802.11 reason 14, which is "MIC failure"
(16 = group-key handshake timeout, 18 = invalid group cipher), and it says nothing about the group cipher. The IEEE reason in these logs
is the AP's deauth, **15 = 4-way handshake timeout** (`join: deauth by the network: status 0, reason 15`). Together: the AP associated us,
sent M1, never got M2 and gave up, while the in-dongle supplicant was still waiting for its first M1. Physical r3 (both methods,
`attempts/20261103-203419-a7-wifi-join-r3/ramdump/kernel.log`): every setting status 0, auth/assoc/link/join all 0, then 4/14 and deauth 15.
RSN/AKM/PMF/cipher mismatches end at association (status ≠ 0). That never happened: r3 associated with mfp 1 + wsec 6 + multi-AKM and
with mfp 0 + wsec 4 + AKM 2. Wrong key material ends in WAIT_M3 (8) after an M2. That never happened either. The frame never reached
the supplicant.

## 2. Root cause: the dongle dropped packets for want of a host RX buffer at every join

The firmware console printed by r1–r3 holds a line we never decoded: `EL: 30 b8c8 <addr> 0`. It is an event-log record: tag 0x30,
format 0xb8c8, two arguments.

| Fact | Evidence |
|---|---|
| Format 0xb8c8 occurs once in the RAM code: `movw r1,#0xb8c8; movs r0,#0x30; bl event_log2; ... bl hnd_pkt_free` at 0x2c45f8 in `pciedev_process_d2h_rxpyld` | firmware, `receipts/fw-facts.txt` (`tests/fw_facts.py`) |
| It is reached (0x2c4312 `beq.w 0x2c45ea`) when `pciedev_process_rxpost_msg` (0x2c4306) returns host address 0 for a packet held in dongle memory (pkt flag 0x2000 clear, the record's second argument 0). The packet is then freed. In short: a packet for the host, and no host RX buffer queued for it | firmware |
| This firmware is split-RX: `_bcmsplitrx` = 1, `_bcmsplitrx_mode` = 4 (RAM data 0x2a0149/0x2a014a). The host RX post handler calls `pktpool_invoke_dmarxfill` (0x2c4934), so host buffers feed the MAC's RX DMA. EAPOL fetch-back exists (`wlc_eapol_pktfetch_required`, `wlc_recvdata_schedule_pktfetch`) | firmware |
| Its MAC units keep `nrxbufpost = 384` (unit 0) and `154` (unit 1) buffers posted | physical, r3 console at 0.29 s and 0.58 s |
| The firmware asks for `max_host_rxbufs` = **6783** (shared area +0x22 = 0x1a7f in r3's dump). Android posts exactly that (`max_rxbufpost:6783`) | physical r3 `fw: shared +20: 1a7f0096`; Android dmesg 7.499 s |
| r1–r4 post **64** RX buffers (`RX_BUFS 64u`, "for a passive scan's firmware… nothing more") | source |
| Drops (distinct lines): stage-5 dry run, no join: **0**. r1: **4**, r2: **4**, r3: **9 + 4 + 4**. Every join has them, 1–25 ms after the firmware's `Start PSK to PMK conversion 0`, i.e. in the window where Android gets M1 (14.5 ms after start). In r3, 9 more came during method 1's join scan. No boot ever had an RX completion (`rx: item`: 0) | physical, `receipts/physical-drops.txt` |
| EAPOL reaches the supplicant only from the RX data path: `wlc_recvdata_ordered` tests ethertype 0x888e and calls `wlc_sup_eapol` (0x3f62f2, 0x3f6630) | firmware |

Cause (firmware + physical; the last link is inference): with 64 buffers, the two MAC units' RX fill (384 + 154 wanted) absorbs every host
buffer, and the dongle's RX post queue is empty when the join's first data packets arrive. `pciedev_process_d2h_rxpyld` frees them
(`EL 30 b8c8`). The M1 the AP sent never got as far as `wlc_sup_eapol`, so the supplicant stayed in WAIT_M1 until the AP's deauth 15.
Which packet each drop was is not readable statically (the first argument is a heap address). That M1 was among them is inferred
from the timing and from there being no other loss on the data path. The buffer shortfall itself is not inferred: it is the firmware's own
record, at every join.

Why r2–r4 missed it: r2's passphrase theory fit status 4. r3 then copied Android's whole connect sequence (unchanged result). r4 added the RX
witness that would have shown this, but was never booted.

## 3. Fix: nested XNU branch **`hk-wifi-join4`**, head **2b7de9e165c542f6a0dd17a1ab19e73124700e2f** (2 commits on 885589f = hk-wifi-join3, r4)

Commit a `76bcd03` = the RX supply and the drop counter; commit b `2b7de9e` = the M1 and MAC-fill lines (the coordinator's ask: the live boot
must show buffers posted ≥ 538, M1 received, then the 4-way completing).

Patch `0001-blazer-wifi-join-r5.patch` (both commits, f8994837…251e); sources in `src/` (6 files, +64/−12):
- `blazer_bcm4390_ring.c`: `RX_BUFS` 64 → **1024**, posted as `min(1024, max_host_rxbufs)` (`b4_rx_bufs_wanted`; stock posts
  max_host_rxbufs). 1024 is above both units' fill (538) with 486 spare, and it is the most that fits below the TX id range
  (RX ids 0x400–0x7ff). RX post ring depth `RX_BUFS + 64` (every buffer fits at once, so posting never waits). RX completion ring 1024.
  Buffers stay 2048 bytes: `pciedev_process_rxpost_msg` halts the firmware on a buffer under 0x7f8 (`cmp 0x7f8` → `osl_sys_halt`), now a
  `_Static_assert`. `B4_DMA_NEEDED` 0x60000 → **0x280000** (stage JOIN carves 0x244000).
- `blazer_wifi.c`: `WIFI_DMA_BYTES` → 0x280000, one physically contiguous 2.5 MiB `kmem_alloc_contig` (was 384 KiB). If it fails, the
  existing path stops the stage (`no contiguous host memory`, NO_DMA) before anything touches the chip.
- `blazer_bcm4390.c`: `b4_console_note` counts console lines `EL: 30 b8c8 ` (`p->fw_rx_nobuf`) and says once
  `rx: the firmware dropped a packet for the host: no host RX buffer was queued (EL 30 b8c8)`.
- `blazer_bcm4390_ring.c` witness line adds `Firmware drops for want of a host buffer (EL 30 b8c8): N`. `blazer_bcm4390_scan.c`: the post
  line says how many the firmware takes, then `rx: posted N, above the 538 the MAC fill holds: yes|NO` (`B4_MAC_RX_FILL` = 384 + 154).
- `blazer_bcm4390_join.c` (b): after each `WLC_E_PSK_SUP`, `join: M1 received: yes|no|unknown (supplicant <state>)` from
  `sup_auth_status_t`: 4 (WAIT_M1) = no; 5 (PREP_M2), 6 (KEYED), 8–11 (WAIT_M3…PREP_G2) = yes; anything else = unknown. The firmware sends
  PSK_SUP when the handshake ends, not when M1 arrives (Android: one PSK_SUP, status 6, after the whole 4-way). So "M1 received" is read
  from the supplicant's final state. No separate firmware event exists for it.
- Otherwise join.c is r4's: r3's two methods, r4's .57.31 firmware, buf_key_b4_m4 1 and PM 0 are unchanged. Nothing new goes on the air.
  **Boot line unchanged:** r1's 1008 bytes (913ab8d9…), so **+0 boot-arg bytes**, no new argument. Overlay: r4's layout (47 records, the last
  one group 26 BWN2, not applied by the mask), freshly composed. The int1 line budget (1023) is untouched.

## 4. Host tests (m1box, `tests/run.sh`, receipts in `receipts/`)

- `ring_oracle.c` includes the real r5 `ring.c` (fake chip RAM and doorbell): stage JOIN fits in 2.5 MiB and r4's 384 KiB is now refused;
  1024 posted for max_host_rxbufs 6783, 100 for 100, 1024 for 0. Every item is type 0x11, ids 0x400+i, 2048 bytes, address in the RX area,
  no metadata, epoch in sequence. Host-memory write index and doorbell `0xff010400` follow. A completion reposts the same buffer past
  index 1024 without RING_FULL. The witness carries the drop count. PASS.
- `console_oracle.c` links the real r5 `blazer_bcm4390.c` and feeds r3's own console lines through the real window code: 13 drops in method 1,
  17 in total, `EL: 30 b8c0`, `EL: 31 b8c8` and `EL: e6 d838` not counted, said once, every line still logged. PASS.
- `join2_oracle_r5.c` = r4's join oracle (real join.c + real gate) plus the M1 checks: `M1 received: yes (supplicant keyed)` after the
  keying, `no (supplicant waiting for M1)` after method 1's WAIT_M1, and states 8/5/11 yes, 7/3/12 unknown. 25 cases PASS.
- `mutate_r5.py`: **16/16** mutants caught (64 buffers, ring with no room, r4's completion depth, r4's memory, cap ignored, 0 as cap,
  buffer < 0x7f8, witness without count, completion not reposted, tag too loose/wrong, said every time, lines not counted, M1 only when
  keyed, M1 for every state but 4, state names out of order).
- r2's kernel-reader oracle + `test_compose_wifi_join.py`: 18 OK.
- ARM64e objects with `-DBLAZER` (MH_MAGIC_64 ARM64 E): ring defines `_b4_rx_post_all _b4_rx_bufs_wanted _b4_rx_witness _b4_rings
  _b4_poll`. bcm4390 defines `_b4_console _b4_console_note`. The r5 strings are present. `_b4_rx_bufs_wanted` compares with 0x400.
  `receipts/objects.txt`.
- `fw_facts.py`: the §2 firmware facts, all hold (`receipts/fw-facts.txt`).

## 5. Kernel (Mac) and QEMU

`build_wifi_r5.py 2b7de9e…` (parent pin 76bcd03) (r4's script: fw-57.31 pins, fleet lock, clean tree, `mk.sh -j8`, restore): rc 0 in 18 s. It checks for the
.57.31 bytes, no .57.30 string, and the r5 strings (drops, MAC fill, M1). Tree back on **p1 b228c4f**, rebuilt rc 0 (`build_wifi_r5.out`).
- `research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r5` **f0a08477c42762c92bab0cfc769dfbdd5e3e05f1694725c4711c956932f7948a**,
  `.unstripped` 73b10f57ea6ec24328624ecc3870cd167ae0ce1f8f36072cd20126d1223ab880. `receipts/kernel.txt`: `_b4_rx_bufs_wanted` (`mov w8,#0x400`,
  `csel`) and `wifi_thread`'s `mov w1,#0x280000` in the unstripped kernel, and both new strings. `run.sh K=` found every r5 symbol and string.
Commit a's kernel (62ae0508…cdd7) was built first and replaced under the same name. It never booted.

QEMU (`receipts/qemu.txt`): the rig has no BCM4390, and qemu_preflight drops `blazer_wifi*` as phone-only. **The handshake can't be shown
in QEMU.** What was run: the r5 kernel on a7-ios-system-r3's root, line and overlay, side by side with r3's own kernel, 600 s TCG each.
Result: runs `qf-wifi-r5-base-r3` and `qf-wifi-r5-k1` have the same milestones (root on UFS, overlay 12 applied,
launchd, usermanagerd, backboardd, SpringBoard, display, iconservicesagent). Both show 0 panics and 0 respawns/crashes of backboardd and
SpringBoard. Both end on the recipe's 300 s deadline and both miss PosterBoard: the same verdict, FAIL on `home-daemons`, with r3's own
kernel too. The r5 kernel boots like r3's. That is a regression check, not Wi-Fi evidence. These runs used commit a's kernel. `qf-wifi-r5-k2` repeated
the check on the final kernel (f0a08477): the same probes and verdict, 0 panics (`receipts/qemu.txt`).

## 6. Image (Mac, built from the kept secret; nothing secret printed): `build_image_r5.sh` (= r4's with the r5 kernel pin and strings)

- **`research/images/a7-wifi-join-r5` (mode 700): boot.img `a181b2bce9a512a7e15e6ed4377e249579566e5b2d9380569365d5e4928ee590`.**
  `image_tool check` OK. The cmdline is r1's (913ab8d9…669459). Overlay `research/ios26-wifi-r1/secret/a7-r5-wifi-join-r5.ovl` 217da41b…331f
  (600, 47 records, BWN2 with a passphrase). `verify_image_r5.py`: one record, BWN2 176 bytes, name/PMK/passphrase = the file, boot.img holds
  the record and the whole overlay: all yes (`build_image_r5.out`).
- **This image holds the Wi-Fi password in clear.** r4's unbooted `a7-wifi-join-r4` and commit a's r5 image were wiped before this build.
  `sh research/ios26-connectivity-r1/wifi/r5/build_image_r5.sh wipe` after the boot (images, r3/r4/r5 overlays, logs, mkwifisecret blob).

## 7. Phone join test (coordinator, owner present: it transmits)

```sh
adb reboot bootloader
ANDROID_SERIAL=<serial> tools/bootios research/images/a7-wifi-join-r5/boot.img a7-wifi-join-r5 \
  --mach research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r5.unstripped --wait 480
fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-wifi-join-r5-after-boot
sh research/ios26-connectivity-r1/wifi/r5/build_image_r5.sh wipe
```

PASS lines (`grep blazer-wifi ramdump/kernel.log`), in order. The three proofs: (1) buffers ≥ 538, (2) no drops and M1 received,
(3) the 4-way completes:
```
blazer-wifi: fw: UP. Shared flags 0x…: IPC version 9, trap 0. FWID 0x765a5017, the file's (27.10.1121.57.31, Android's) 01-765a5017
blazer-wifi: rx: 1024 buffers posted. The firmware takes up to 6783 (max_host_rxbufs); r1-r4 posted 64          (1)
blazer-wifi: rx: posted 1024, above the 538 the MAC fill holds: yes                                              (1)
blazer-wifi: rx: witness after the posting: post ring written to 1024, the dongle has read to … ; … Firmware drops for want of a host buffer (EL 30 b8c8): 0
blazer-wifi: join: next: try 1, method 1, any address, 2 channels: …
blazer-wifi: join: 4-way handshake: status 6, reason 0                                                           (3)
blazer-wifi: join: M1 received: yes (supplicant keyed)                                                           (2)
blazer-wifi: join: joined in N ms
blazer-wifi: join: keyed by method 1: Android's order (wsec_info passphrase, multi-AKM, any address)     <- or method 2
blazer-wifi: rx: witness after method N: …; Items ≥1 … Firmware drops for want of a host buffer (EL 30 b8c8): 0
blazer-wifi: net: address a.b.c.d … gateway …
blazer-wifi: en0 address err 0, default route err 0
blazer-wifi: net: gateway answered a ping in N ms
```
Absent on PASS: `rx: the firmware dropped a packet for the host`, any `fw says: … EL: 30 b8c8`, and `M1 received: no`. PASS = `status 6` + `keyed by method N` +
an address + the ping. Return check PASS afterwards.

If it fails, the new lines decide:
- `above the 538 the MAC fill holds: NO`, `rx: N buffers posted` with N < 1024, or `no contiguous host memory` / `NO-GO … no DMA`: the 2.5 MiB allocation or the cap. Next: post
  fewer (≥ 600) or allocate earlier.
- drop count > 0 again with 1024 posted: the fill absorbs even 1024. Next: post closer to 6783 in rounds as the dongle reads (the ring
  read index in the witness shows how far it got), as stock's `rx_buf_burst`.
- drop count 0, still `status 4, reason 14` / `M1 received: no (supplicant waiting for M1)`: the buffer shortfall was real but not what lost M1. r4's witness and counters (`rxnobuf`,
  `rxbadda`, `rxnoscb`) are the next evidence.
- `M1 received: yes (supplicant waiting for M3)` (status 8) or later, then a deauth: M1 got through and M2 went out, so the buffer fix
  worked and the key is now the problem. Check the password.

## 8. Suggested NOTES line (replaces the Wi-Fi r3/r4 line)

- **Wi-Fi (2026-11-03, PHYSICAL r1–r3, HOST+QEMU r5):** `status 4, reason 14` is Broadcom's WAIT_M1/SUP_DEAUTH (the AP's IEEE reason is
  15, handshake timeout), not a cipher error. Root cause: the firmware console's `EL: 30 b8c8` records at every join, 0 in a dry run. In
  `pciedev_process_d2h_rxpyld` that record means a packet for the host was dropped because no host RX buffer was queued (split-RX mode 4;
  the MAC fill keeps 384+154; firmware asks 6783; we posted 64). r5 (XNU `hk-wifi-join4` 2b7de9e, kernel f0a08477…948a, image
  `a7-wifi-join-r5` a181b2bc…e590, holds the password) posts 1024 in 2.5 MiB, counts the drops and logs buffers ≥ 538 and M1 received;
  +0 boot-arg bytes.
  Built, not booted: `research/ios26-connectivity-r1/wifi/r5/FIX.md`.
