# W1 r4: Android's firmware (.57.31), the station role's two settings, and an RX witness (2026-11-03, m1box + Mac, HOST)

Labels: **physical** = phone log or a root read on the phone; **source** = Pixel 10 bcmdhd `bcm4390/*.c` (copied read-only from the Mac's
`research/upstream/patch-scout-chips/pixel10-aosp/.../bcm4390` to m1box `/data/hackios-qemu/wifi-r4/src-bcm4390`) and the release headers
`research/ios26-wifi-r1/dl-headers-s4`; **host** = built and run here; **inference** = untested. Nothing touched the phone except one
read-only adb root read of five files in Android (§2). No name, password, PMK or passphrase was printed, logged or committed.

## 1. What r3 showed (physical, `research/laguna-usb-fix/attempts/20261103-203419-a7-wifi-join-r3/ramdump/kernel.log`)

Both methods: every setting status 0, auth 0, link up, association 0, join result 0, then `PSK_SUP status 4, reason 14` and deauth 15.
Status 4 is `WLC_SUP_KEYXCHANGE_WAIT_M1` and reason 14 is `WLC_E_SUP_DEAUTH` ("Received FC_DEAUTH"; `wlioctl_defs.h`, `bcmevent.h`).
The AP's deauth reason 15 is 802.11's 4-way handshake timeout. So the AP sent M1, retried and gave up, and the dongle's supplicant never got
one. The firmware console has `Start PSK to PMK conversion 0` and no EAPOL line. **No boot has ever had an RX completion**: every Wi-Fi
attempt (stage 4 through r3) logs `rx: 0 items back` and no `rx: item` line. Scan results come as events, so the host RX buffers have never
carried a frame. Auth and association are management frames that the dongle handles internally. M1 is the first *data* frame, and on this
PCIe full dongle a received data frame lands in a host RX buffer (inference: split RX, and idsup fetching EAPOL back from it).

## 2. Our bring-up against Android's, item by item

| Item | Android (physical/source) | r1–r3 | r4 |
|---|---|---|---|
| Firmware | `27.10.1121.57.31 (g4159d38) FWID 01-765a5017`, db46afd6…2864, 2525684 bytes (root read just now; dmesg 7.52 s) | **.57.30** (ge2638ec) FWID 01-800a0c25, 3d3e386a, 2525692 bytes | **.57.31**, Android's bytes |
| NVRAM | `bcmdhd.cal_USI_G7BB_7311_V11` fe7cf292 | same file, same hash, 18268 bytes at 0x5bb8a0, token 0xee2811d7 = Android's | same |
| CLM | `blob file exists`, "This FW is not included CLM data", `clmload` → "CLM download succeeded", country US, clmver Google.BZ5 | **same**: `clmload` 22 chunks, country US event, clmver Google.BZ5 (9ad4c6ce = Android's) | same |
| TXCAP | `txcapload` "TXCAP download succeeded" (75c0515d) | **same**: 3 chunks | same |
| Preinit | `preinit_status` present → `dhd_optimised_preinit_ioctls` (source dhd_linux.c 12240): ver, wlc_ver, hostwake_oob, axierror, cur_etheraddr (GET), clm/txcap, country, roam_off, tdls_enable (GET), event_log_max_sets, **sup_wpa 1 (SET)**, pktfilters, clmver, wnm_bsstrans_resp, d3_hostwake_delay. With `fw_preinit` the firmware applies its own role defaults (dhd_cfg80211.c `dhd_config_dongle` returns early) | all the reads; country (DK, the network's); sup_wpa 1 before up (r3) | same, plus the two below |
| Station role | `init_sta_role_iovars` (wl_cfg80211.c 2294): assoc_listen, roam_off 0, roam periods, **PM 2**, bcn_timeout, assoc_retry_max, FAKEFRAG, **buf_key_b4_m4 1**, interworking, wnm, recreate_bi_timeout, then sup_wpa. At the connect: **PM 0** ("wl_cfg80211_set_pm: PM 0 done" 13.9148 s, 22 ms before PSK_SUP 6) | none of them; PM at the firmware's default | **buf_key_b4_m4 1 and PM 0 before up**, only said |
| roam / wsec_info / multi-AKM / join | Android's connect, r3 §2 | method 1 = Android's (r3) | unchanged |
| EAPOL | `MACEVENT: WLC_E_PSK_SUP, status 6 … eapol_start_m1 14555 m1_m2 70 m2_m3 17120 m3_m4 25` then "idsup status:6", "port authorized". The timings come in the dongle's event; dhd only logs them (dhd_common.c 5258). **No host-side EAPOL step, iovar or flow ring** is needed for idsup: the 4-way is entirely the dongle's | – | – |
| Host caps | "ENABLING DW:2" (inband device wake), EDL, TXPOST_EXT, TX_CSO, host_cap2 0x200; RX posts 2048-byte buffers, `rx_bufpost_threshold:64` | 0x801409 (no deep sleep, no EDL/CSO), host_cap2 0x200, 64 × 2048 RX buffers | unchanged (§5) |
| MAC | random per connection (`dhd_set_mac_address … 92:…`) | firmware's own local 02:1c:32:… | unchanged (association worked with it) |

The `host_rxbuf_post_t` layout in ring.c (`data_buf_len` at 10, `data_buf_addr` at 24, no metadata) matches `dhd_prot_rxbuf_post` (source
dhd_msgbuf.c 6777–6804). Nothing static shows the RX path is wrong; r1–r3 just never looked at it.

## 3. The change: nested XNU branch **`hk-wifi-join3`**, commit **885589f9dc9ebd2a9148108d2e952b877263e7f3** on 3da6bcc (hk-wifi-join2)

Patch `0001-blazer-wifi-join-r4.patch` (sha256 e41da70a…1841); sources in `src/` (join.c b0670925…, scan.c 0fe1896f…, ring.c 2de5b549…,
pcie1.h c911280f…). r3's two methods are unchanged.

- **Firmware**: `blazer_wifi_fw.c` `B4_FW_DIR` → `research/ios26-wifi-r1/fw-57.31/` (Mac, mode 700/600, git-ignored): Android's five files
  from the phone (hashes in `receipts/firmware.txt`, equal to `android-fw/adb-firmware.txt`), plus fw/'s other three NVRAMs. `fw/` is
  untouched and keeps .57.30 for every other branch. `blazer_bcm4390.c` logs the expected FWID 01-765a5017. No size or address is hard-coded:
  the shared area, console and rings are read from the dongle.
- **Station role** (`b4_join_pre_up`, after sup_wpa, only for a network with a password and the dry run): `buf_key_b4_m4 1`, then
  `WLC_SET_PM 0`. Both are only said, as stock does. Gate: both at the dry level.
- **RX witness** (`b4_rx_witness`, ring.c, read only): the RX post ring's write index against the read index the dongle DMAs back (did it
  ever take a buffer?), the RX completion ring's two indices, items/bytes/dropped. Logged after the posting, after the scan, and after each
  method's end.
- **Receive counters** (`b4_rx_counters`, scan.c): `counters` → the `wl_cnt_wlc_t` words before its first array, whose places don't depend
  on NFIFO: rxframe 15, rxerror 17, **rxnobuf 19**, rxnondata 20, rxnoscb 26, rxbadproto 27, rxbadda 29, rxfilter 30, summed over slices,
  each with `(+delta)` since the last look. After the scan (baseline) and after each method.
- Nothing new goes on the air. The boot line is r1's (1008 bytes, 913ab8d9…), with no new argument.

## 4. Host tests (m1box, `tests/run.sh`, receipts in `receipts/`)

- `join2_oracle.c` (r3's, extended): includes the real r4 `join.c`, links the real r4 `scan.c` (real gate, real `b4_rx_counters` on a
  scripted 221-word `wl_cnt_wlc_t`). **25 cases PASS**: r3's 24 with the new places (method 1's counters between its join and the
  disassociation, band then counters after keying), plus buf_key_b4_m4 1 and a 4-byte PM 0 right after sup_wpa, refusals only said, none
  for an open network, a witness and counters after each method with the exact `rxframe 114(+7) … rxnobuf 6(+3) … rxbadda 2(+1)` line, and
  gate positives/negatives (PM and buf_key at the dry level, not below; GET_PM never).
- `mutate_join2.py`: **37/37** mutants caught (r3's 26 + 11 r4: no buf_key, PM 1, PM refusal stops, no RX look on failure or keying, look
  before the band, wrong rxnobuf word, no delta, last look not kept, gate PM too low, gate without buf_key).
- r2's `kernel_oracle.c` + `test_compose_wifi_join.py` on the r4 sources (with `kernel_oracle_r4_stubs.c` for the two new externs): 18 OK.
- ARM64e objects with `-DBLAZER` (`objects.txt`): join, scan and ring objects (MH_MAGIC_64 ARM64 E), defining `_b4_join_pre_up …`,
  `_b4_rx_counters`, `_b4_rx_witness` and holding the r4 strings.

## 5. Kernel and image (Mac)

Kernel (`build_wifi_r4.py 885589f…`, r3's convention: refuses unless the 7 fw-57.31 files match their pins, fleet lock
`/tmp/fleet/kernel-build-slot.lock`, waits for make/mk.sh, refuses a dirty tree, `mk.sh -j8`, checks the kernel holds the .57.31 bytes and no
.57.30 string, then restores and rebuilds the original branch; `build_wifi_r4.out`): rc 0 in 12 s, CC of all nine Wi-Fi objects, 0 warnings
in them. Tree back on **p1 b228c4f**, rebuilt rc 0 (10 s; obj kernel 9eda8db3…).
- `research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r4` **ed6dbab1d7cf148f2bfbee23d6c3b3b4fcf36a03214fb17b7bc076b2e76c3693**,
  `.unstripped` c12905d4a1244bc8f1cd4d246d043e0acf95c91b27ec7100af80b579f93bb502. `receipts/kernel.txt`: the r4 symbols, every r4 string,
  `version 27.10.1121.57.31` present.

Image (`build_image_r4.sh` = r3's with the r4 kernel pin and string checks; `build_image_r4.out`): secret file facts yes/no only; overlay
`research/ios26-wifi-r1/secret/a7-r4-wifi-join-r4.ovl` 28ce487c…3bf4 (600, 47 records, the last one group 26 BWN2 with a passphrase, not
applied by the mask). The first try stopped in image_tool's shim link: my raw ssh lacked `/opt/homebrew/bin` (no `ld.lld`). The partial
image dir was deleted and the script rerun in the bridge's environment, reusing the overlay.
- **`research/images/a7-wifi-join-r4` (mode 700): boot.img `214641ba480945e26751a1dcff13b70a21d078a3c8110b6b286ee45345ae2ef6`**.
  `image_tool check`: `OK a7-wifi-join-r4 bootable`; AVB "Successfully verified sha256 hash of boot.img". Cmdline = r1's, 913ab8d9…669459.
  Built with the Mac's working `tools/image_tool.py` (HEAD e96cb64 plus the uncommitted W1 diff r3 also used).
- `verify_image_r4.py` (`verify_image_r4.out`): one network record, BWN2 176 bytes, name = file, PMK = PBKDF2(file), passphrase = file,
  boot.img holds the record and the whole overlay: all yes.
- **This image holds the Wi-Fi password in clear.** Keep it local, and run `sh research/ios26-connectivity-r1/wifi/r4/build_image_r4.sh wipe`
  after the boot. It removes the r3/r4 overlays, the image logs, `research/images/a7-wifi-join-r*` and the `mkwifisecret.py` blob; the secret
  file stays.

## 6. Boot (coordinator, owner present, transmits)

```sh
adb reboot bootloader
ANDROID_SERIAL=<serial> tools/bootios research/images/a7-wifi-join-r4/boot.img a7-wifi-join-r4 \
  --mach research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r4.unstripped --wait 480
fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-wifi-join-r4-after-boot
sh research/ios26-connectivity-r1/wifi/r4/build_image_r4.sh wipe
```

Expected PASS lines (`grep blazer-wifi ramdump/kernel.log`), in order:
```
blazer-wifi: the image holds a network. Its name and key won't be logged
blazer-wifi: fw: next: fw_bcmdhd.bin_4390_b1, 2525684 bytes to 0x2a0000
blazer-wifi: fw: UP. Shared flags 0x…: IPC version 9, trap 0. FWID 0x765a5017, the file's (27.10.1121.57.31, Android's) 01-765a5017
blazer-wifi: ioctl: ver: status 0: wl0: Sep 23 2026 12:15:34 version 27.10.1121.57.31 (g4159d38 b1 release2) FWID 01-765a5017
blazer-wifi: rx: witness after the posting: post ring written to 64, the dongle has read to …
blazer-wifi: blob: clmload took all of it: 22 chunks, …            blob: txcapload took all of it: 3 chunks, …
blazer-wifi: join: sup_wpa to 1 before the interface is up: status 0
blazer-wifi: join: buf_key_b4_m4 to 1: status 0
blazer-wifi: join: PM to 0 (off) for the handshake: status 0
blazer-wifi: rx: witness after the scan: post ring written to 64, the dongle has read to 64 (all taken); …
blazer-wifi: rx: counters after the scan, N slices: rxframe … rxnobuf … 
blazer-wifi: join: method 1: Android's order
blazer-wifi: join: next: try 1, method 1, any address, 2 channels: …
blazer-wifi: join: 4-way handshake: status 6, reason 0
blazer-wifi: join: joined in N ms
blazer-wifi: join: keyed by method 1: Android's order (wsec_info passphrase, multi-AKM, any address)   <- or "keyed by method 2: …" after "try 2, method 2"
blazer-wifi: join: on X GHz
blazer-wifi: rx: witness after method N: …; Items ≥4 …            (M1 and M3 at least)
blazer-wifi: rx: counters after method N, …: rxframe …(+k) … rxnobuf …(+0) …
blazer-wifi: net: address a.b.c.d … gateway …
blazer-wifi: en0 address err 0, default route err 0
blazer-wifi: net: gateway answered a ping in N ms
```
PASS = a `keyed by method N` line + an address + the ping. If it fails, the witness and counters lines decide:
- `the dongle has read to 0 (none taken)` after the posting and the scan: **the dongle never took an RX buffer**, so every data frame had
  nowhere to land. Next: the RX post ring's create/doorbell/index slot, and Android's host caps (inband DW, TXPOST_EXT, TX_CSO).
- `all taken`, `Items 0`, `rxnobuf (+n>0)` after method 1: frames arrive but are dropped for want of a host buffer. Next: the post size,
  the number of buffers, and the RX offset/metadata.
- `all taken`, `rxnobuf (+0)`, `rxframe (+k)`, still `status 4, reason 14`: frames are counted and M1 still doesn't reach idsup.
  `rxbadda`/`rxnoscb`/`rxbadproto` say where (address, station, protocol). Next: compare the console's `EL:` lines against `fw-57.31`'s map
  (inference: their arguments may be addresses in this build).
- `ioctl: ver` still shows .57.30: the kernel isn't r4's (check the `--mach` hash).
- status 8 or more: M2 went out, so the key is wrong.

## 7. Suggested NOTES line (replaces the Wi-Fi r3 line)

- **Wi-Fi (2026-11-03, PHYSICAL r1–r3, HOST r4):** r1–r3 associated and stayed in WAIT_M1 (PSK_SUP 4/14 = deauth by the AP, its reason
  15); no RX completion in any boot ever. CLM, TXCAP and NVRAM were already Android's; the firmware was .57.30 against Android's .57.31. r4
  (XNU `hk-wifi-join3` 885589f, kernel ed6dbab1…3693, image `a7-wifi-join-r4` 214641ba…2ef6, holds the password) loads Android's .57.31,
  sets buf_key_b4_m4 1 and PM 0 before up, keeps r3's two methods, and logs whether the dongle ever takes an RX buffer, plus its receive
  counters after each method. Built, not booted: `research/ios26-connectivity-r1/wifi/r4/FIX.md`.

## 8. For the coordinator (root index): paths and hashes

Submit (no firmware, image, overlay or secret): `research/ios26-connectivity-r1/wifi/r4/{FIX.md,0001-blazer-wifi-join-r4.patch,
build_wifi_r4.py,build_wifi_r4.out,build_image_r4.sh,build_image_r4.out,verify_image_r4.py,verify_image_r4.out}`, `r4/src/*`,
`r4/tests/{join2_oracle.c,mutate_join2.py,run.sh,kernel_oracle_r4_stubs.c}`, `r4/receipts/*` (not `r4/tests/build/`). Hashes: `receipts/SHA256SUMS`,
§3, §5. Commit message: "Wi-Fi r4: Android's .57.31 firmware, buf_key_b4_m4/PM 0, RX witness; kernel ed6dbab1, image a7-wifi-join-r4
214641ba (built, not booted)".
