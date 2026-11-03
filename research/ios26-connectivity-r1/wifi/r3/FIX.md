# W1 r3: two join methods in one boot (2026-11-03, m1box + Mac, HOST)

Labels: **physical** = phone log; **source** = Pixel 10 bcmdhd `bcm4390/wl_cfg80211.c`, `dhd_linux.c` (Mac:
`research/upstream/patch-scout-chips/pixel10-aosp/private/google-modules/wlan/bcmdhd/bcm4390`, `.c` only, no `.h` in that copy) and the
release headers `research/ios26-wifi-r1/dl-headers-s4` (`wlioctl.h`, `wlioctl_defs.h`); **host** = built and run here; **inference** = untested.
Nothing touched the phone. No name, password, PMK or passphrase was printed, logged or committed; the Mac-side image step prints only
yes/no facts, sizes and hashes.

## 1. What r2 showed (physical, `research/laguna-usb-fix/attempts/20261103-184333-a7-wifi-join-r2/ramdump/kernel.log`)

Every setting status 0, including `passphrase given to the firmware` and the PMK. Auth, link up, association and the join's result were all 0;
then `4-way handshake: status 4, reason 14` and deauth reason 15, as r1. The passphrase did not change it. The firmware console after the stop
has `Start PSK to PMK conversion 0` and no EAPOL line. The join went to the best record, 2.4 GHz RSSI -43 (3 records heard).
So r2/FIX.md §3's cause (a bare PMK) is not sufficient: a passphrase in the legacy form, after the interface was up, with a targeted passive
join, still left the supplicant in WAIT_M1 and the host never saw an EAPOL frame.

## 2. What Android does differently (physical dmesg `ios26-dualboot-r8/attempts/return-after-restore/dmesg.txt`, 13.62–13.94 s; source)

| Step | Android (this phone, this network) | r2 |
|---|---|---|
| supplicant on | `sup_wpa 1` at interface init (`dhd_preinit_ioctls` BCMSUP_4WAY_HANDSHAKE; `wl_is_4way_hs_offld_enabled`) | at the join, after WLC_UP |
| roam | `roam_off 0` ("roam enabled for wlan0") before the connect | `roam_off 1` after the keys |
| clear | `wl_cfg80211_clear_security`: wsec 0, auth 0, wpa_auth 0, empty `join_pref`, `wsec_info` algos 0/0x1c010 | none |
| AKM | wpa_auth 0xc0, auth 0, then multi-AKM (AKMs 2, 6, 8, 0x18) **wpa_auth 0x2048080**, mfp 1 (forced capable), `join_pref` 5 WPA tuples | wpa_auth 0xc0, 0x80 |
| cipher | **wsec 6** + `wsec_info` BSS_ALGOS **0x14014 / mask 0x1c010** | wsec 4 |
| passphrase | **`wsec_info` PMK_PASSPHRASE** (0x108) with the SSID ("Passphrase set(wsec_info)"), then sae_pwe | WSEC_PMK flags 1, no SSID |
| PMK | WSEC_PMK flags 0 ("pmk added succesfully") | same |
| join | **wildcard BSSID**, chan_cnt 2, untargeted join scan (80 ms active, 4 probes, 400 ms passive) | one BSSID, one chanspec, passive |
| result | AKM 0xFAC02 (PSK) from the assoc IE; `PSK_SUP status 6` 40 ms after association, on 5 GHz | status 4/14 on 2.4 GHz |

Not mirrored (inference: not needed for a non-MLO PSK join): `mlo_config`, EHT features, packet monitor, BSSID blacklist flush.
The running driver logs "Set Multi AKMs wpa_auth 0x2048080"; the source copy here does not set wpa_auth in `wl_set_multi_akm` (version
difference), so the physical log decides. Android's `sae_pwe` value is debug-only in its log: r3 sends 3 (LOOP|H2E, inference) and only logs
the answer. `WL_JOIN_DEFAULT_SCAN_TYPE` and the home time are in a `.h` not in this copy: r3 uses scan type 0 ("0 use default", wlioctl.h) and
home time -1 (older bcmdhd's literal), inference.

Which of these differences matters is unknown. r3 therefore runs both in one boot and logs which one keyed.

## 3. The change: nested XNU branch **`hk-wifi-join2`**, commit **3da6bcc16870ebbfc1805bc71752310de718dce9** on eef94c6 (hk-wifi-pass)

Patch `0001-blazer-wifi-join-two-methods.patch` (sha256 8a246602…92fe); sources in `src/` (join.c 48cab634…, scan.c e55694bb…, pcie1.h f017fb59…).

- `b4_join_pre_up`: `sup_wpa 1` before WLC_UP for any network with a password (and the dry run), status only said, as stock.
- `b4_join_heard`: also records pairwise TKIP and the two best distinct channels the network was heard on (method 1's list, best first).
- **Method 1** (Android's order, §2 table, top to bottom). A refused essential step (wpa_auth, auth, mfp, wsec, algos, join_pref, passphrase,
  PMK) or a refused join ends method 1 without stopping the boot; the clear steps, roam and sae_pwe are only said.
- If method 1's join does not key (handshake failure, link lost, join result ≠ 0, or 20 s): `WLC_DISASSOC` reason 3, 1.5 s of its events,
  the firmware console (shows whether an EAPOL M1 line ever appeared), then the per-join state is reset.
- **Method 2** (r2's order, two changes): clear as Android, delete method 1's passphrase entry (`wsec_info` PMK_INFO_DEL), wpa_auth 0xc0,
  auth 0, sup_wpa 1, **wsec from the network's RSN IE** (AES, plus TKIP if the group or a pairwise suite is TKIP), wpa_auth 0x80/0x8000,
  **mfp 0** (2 only if the network requires MFP), passphrase (WSEC_PMK flags 1), PMK, roam_off 1, r2's targeted passive join. Its failures stop
  the boot with r2's codes (`JOIN_FAILED` 0x10e etc.).
- Success logs `join: joined in N ms`, **`join: keyed by method N: …`** and the band (`join: on X GHz`), then r2's DHCP/ARP/ping path.
- Secrets: every ioctl copy wiped at once (`wsec_info` buffers too); `cfg.net`'s passphrase and PMK wiped after method 2's settings and on every
  way out of `b4_join_run`. No name, passphrase or length is logged; channels are logged as bands only.
- Gate (`blazer_bcm4390_scan.c`): `wsec_info`, `join_pref`, GET `chanspec` at the dry level; **only when armed**: `WLC_DISASSOC` and a join in
  Android's form (wildcard BSSID exactly, 1–2 nonzero chanspecs, exact length, scan type 0, ≤4 probes, ≤80 ms active, 400 ms passive, home -1,
  no assoc flags or BSSID list). The escan stays passive. **What r3 transmits beyond r2:** method 1's join-scan probe requests for the one SSID
  on ≤2 channels, and one disassociation between the methods.
- Boot line: unchanged (r1's 1008 bytes, 913ab8d9…); no new boot argument.

## 4. Host tests (m1box, `tests/run.sh`, receipts in `receipts/`)

- `join2_oracle.c` includes the real r3 `join.c` and links the real r3 `scan.c`, so every ioctl passes the real gate at the boot's level;
  scripted firmware statuses and events per try. 24 cases, PASS: method 1 keys (exact Android order and bytes: algos TLV, PMK_PASSPHRASE entry
  layout with SSID at 36 and padding, join_pref tuples 00-0f-ac-18/08/02, 00-50-f2-02, 00-0f-ac-06, wildcard join v3 with both channels best
  first, no method 2, no disassociation); method 1 waits for M1 as r1/r2 → disassociation → method 2 keys (late method-1 events don't count);
  both fail → `JOIN_FAILED` 0x10e; method 1 no end (20 s) → method 2; refusals at wpa_auth/mfp/algos/join_pref/passphrase/PMK/join; method 2's
  wsec/mfp from the RSN IE (CCMP 4, TKIP group 6, TKIP pairwise 6); dry run (both methods' settings, no join, no disassociation); no network;
  gate positives and negatives; channel bookkeeping; sup_wpa before up (and refused: only said; open: none); BWN1; not heard. Each case checks no
  name/passphrase/length in the log and that cfg.net's passphrase and PMK are gone.
- `mutate_join2.py`: **26/26** mutants caught.
- r2's `kernel_oracle.c` + `test_compose_wifi_join.py` on the r3 sources: 18 tests OK.
- ARM64 objects with `-DBLAZER` (`objects.txt`): `blazer_bcm4390_join.arm64e.o` (MH_MAGIC_64 ARM64 E) defines `_b4_net_parse _b4_join_run
  _b4_join_heard _b4_join_event _b4_net_rx _b4_on_flow_created _b4_join_pre_up _b4_join_pre_clm` and holds the r3 strings;
  `blazer_bcm4390_scan.arm64e.o` defines `_b4_ioctl_allowed _b4_gate_level _b4_scan` and the gate's `wsec_info join_pref chanspec`.

## 5. Kernel and image (Mac)

Kernel (`build_wifi_r3.py 3da6bcc…`, r2's convention: fleet lock `/tmp/fleet/kernel-build-slot.lock`, wait while any make/mk.sh runs, refuse a
dirty tree, the edit worktree removed once clean, `mk.sh -j8`; `build_wifi_r3.out`): rc 0 in 14 s, `CC blazer_pcie1.o blazer_bcm4390_scan.o
blazer_bcm4390_join.o blazer_wifi_net.o blazer_wifi.o` in `research/ios26-release-r1/logs/wifi-r3-build.log`. Then the tree went back to
**p1 b228c4f** and was rebuilt (rc 0, 13 s). Observed afterwards: the tree is on `hk-pwr1` c798a68: another owner took the lock after this
build. Not touched here.
- `research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r3` **6ebd1a64686859d3a885a5e7b35c42e625ed7adbdedcc3df59a0df091b81356c**
  (Mach-O arm64), `.unstripped` 6453951d87c571081a6f627c1dc08f2b7eb6b08d9fce9d47cf9e7ea67e257909. `receipts/kernel.txt`: the r3 symbols and
  every r3 log string present (0 missing).

Image (`build_image_r3.sh` = r2's script with the r3 kernel pin and r3 string checks; `build_image_r3.out`): secret file facts yes/no only;
overlay `research/ios26-wifi-r1/secret/a7-r3-wifi-join-r3.ovl` 77878d99f70a1c1c…241e (mode 600, 47 records, the last one group 26 BWN2 with a
passphrase, not applied by the mask; a fresh hash, not r2's bb600fea, because mkwifisecret's blob carries a random salt). The secret file and
the composer/mkwifisecret pins are unchanged since r2 (adf35854, f107d012).
- **`research/images/a7-wifi-join-r3` (mode 700): boot.img `824c17bce69ae58099e7a6e90babc9a5f444d6a0bf674ec5f0ddc2c9b08f79fa`**.
  `image_tool check`: `OK a7-wifi-join-r3 bootable`; AVB verified (vbmeta and boot hash). Cmdline = r1's, 913ab8d9…669459.
- `verify_image_r3.py` (yes/no only, `verify_image_r3.out`): one network record; BWN2 176 bytes; name = file; PMK = PBKDF2(file);
  passphrase = file; boot.img holds the record and the whole overlay: all yes.
- **This image holds the Wi-Fi password in clear.** Keep it local; `sh research/ios26-connectivity-r1/wifi/r3/build_image_r3.sh wipe` after
  the boot (removes `secret/a7-r3-wifi-join*.ovl`, the image logs, `research/images/a7-wifi-join-r*`, `mkwifisecret.py wipe`; the secret
  file stays).

## 6. Boot (coordinator, owner present, transmits)

```sh
adb reboot bootloader
ANDROID_SERIAL=<serial> tools/bootios research/images/a7-wifi-join-r3/boot.img a7-wifi-join-r3 \
  --mach research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r3.unstripped --wait 480
fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-wifi-join-r3-after-boot
sh research/ios26-connectivity-r1/wifi/r3/build_image_r3.sh wipe
```

Expected PASS lines (`grep blazer-wifi ramdump/kernel.log`), in order:
```
blazer-wifi: the image holds a network. Its name and key won't be logged
blazer-wifi: join: sup_wpa to 1 before the interface is up: status 0
blazer-wifi: join: the network was heard on N records, 0 of them not of the kind it should be, on 2 channels
blazer-wifi: join: method 1: Android's order
blazer-wifi: join: wpa_auth to 0x2048080: status 0
blazer-wifi: join: wsec_info algos 0x14014, mask 0x1c010: status 0
blazer-wifi: join: join_pref WPA, 5 AKM tuples: status 0
blazer-wifi: join: passphrase given to the firmware by wsec_info, with the name: status 0
blazer-wifi: join: key given to the firmware, 32 bytes: status 0
blazer-wifi: join: next: try 1, method 1, any address, 2 channels: …
blazer-wifi: join: 4-way handshake: status 6, reason 0
blazer-wifi: join: joined in N ms
blazer-wifi: join: keyed by method 1: Android's order (wsec_info passphrase, multi-AKM, any address)      <- or "keyed by method 2: r2's order, no mfp, wsec from the RSN IE" after "try 2, method 2"
blazer-wifi: join: on X GHz
blazer-wifi: net: address a.b.c.d … gateway …
blazer-wifi: en0 address err 0, default route err 0
blazer-wifi: net: gateway answered a ping in N ms
```
PASS = a `keyed by method N` line + an address + the ping; the method number is the result to record. Diagnose:
- `method 1 refused at X: status S`: that iovar/form is not in this firmware (`.57.30`); method 2 still runs.
- method 1 `status 4, reason 14` again, then method 2 keys: the difference is in r2's mfp 1 / wsec 4 (method 2's changes), not Android's form.
- both `status 4, reason 14`: neither Android's ioctls nor the RSN changes are it. Next suspects (inference): firmware `.57.30` vs Android's
  `.57.31`, the 2.4 GHz BSS (Android keyed on 5 GHz; method 1's `join: on X GHz` shows which band it took), or something in the PCIe/event path
  that drops EAPOL in the dongle. The console dump after `method 1 over` shows whether the firmware saw an M1.
- status 8 or more: M2 went out: the key is wrong.

## 7. Suggested NOTES line (replaces the Wi-Fi r2 line)

- **Wi-Fi (2026-11-03, PHYSICAL r1+r2, HOST r3):** r1 (PMK) and r2 (passphrase, then PMK) both associated and stayed in WAIT_M1 (4/14, deauth
  15); no EAPOL reached the host. r3 (XNU `hk-wifi-join2` 3da6bcc, kernel 6ebd1a64…356c, image `a7-wifi-join-r3` 824c17bc…79fa, holds the password) tries
  Android's exact connect sequence first (sup_wpa before up, multi-AKM 0x2048080, wsec 6 + wsec_info algos, wsec_info passphrase with SSID,
  wildcard 2-channel join), then r2's order without mfp and with wsec from the RSN IE, and logs which keyed. Built, not booted:
  `research/ios26-connectivity-r1/wifi/r3/FIX.md`.
