# W1 r2: why a7-wifi-join-r1's 4-way handshake failed, and the fix (2026-11-03, m1box + Mac, HOST)

Labels: **physical** = phone log; **firmware** = static reading of the pinned `fw_bcmdhd.bin_4390_b1` (sha256 3d3e386a…, byte-identical
to Android's `/vendor/firmware` copy) with its symbol map `fw_bcmdhd.map_4390_b1`, Thumb-2 disassembly of RAM code (load address 0x2a0000);
**source** = Pixel 10 bcmdhd `bcm4390/wl_cfg80211.c` (research/upstream/patch-scout-chips) and release headers (research/ios26-wifi-r1/dl-headers-s4);
**host** = built and run here. Nothing touched the phone. No name, password or PMK was printed, logged or committed. Mac-side checks
of the secret printed only yes/no facts.

## 1. What r1 showed (physical, attempts/20261103-163533-a7-wifi-join-r1/ramdump/kernel.log)

Every setting had status 0: `wpa_auth 0x80`, `mfp 1`, `wsec 4`, `sup_wpa 1`, `key given to the firmware, 32 bytes`. Auth, link, association
and the join's result were all status 0. Then `WLC_E_PSK_SUP status 4, reason 14` and deauth reason 15 about 2 s after the join (15:36:56.6 → 58.8).

- `status 4` = `WLC_SUP_KEYXCHANGE_WAIT_M1`, `reason 14` = `WLC_E_SUP_DEAUTH` (wlioctl_defs.h `sup_auth_status_t`, bcmevent.h; source).
  802.11 reason 15 = 4-way handshake timeout: the AP repeated M1 and got no M2 it could accept.
- **The supplicant never got past "waiting for M1"**. With a wrong PMK it would have answered M1 with an M2 whose MIC is wrong and been in
  `WAIT_M3` (8) when the network gave up. So the r1 failure was **not** a wrong password: the firmware had no key it could use.
- The firmware console's last lines: `Start PSK to PMK conversion 0`, right after the key was set (fw time 8.33 s).

## 2. Ruled out (host)

- PMK derivation: `mkwifisecret.pmk_of` = PBKDF2-HMAC-SHA1(passphrase, ssid, 4096, 32). It reproduces IEEE 802.11i-2004 H.4 ("password"/"IEEE" →
  f42c6fc5…, "ThisIsAPassword"/"ThisIsASSID" → 0dc0d6eb…) and an independent HMAC loop.
- The owner's secret file (Mac, booleans only): LF line ends, no CR, no BOM, no tab, no leading or trailing space in name or password,
  printable ASCII, not a 64-hex PSK. The r1 overlay's record holds that file's name and exactly PBKDF2(file).
- The ioctl itself: kernel `WLC_SET_WSEC_PMK` (268) with a 263-byte `wsec_pmk_t` (key_len 32, flags 0, key, opt_len 0). That is byte for byte
  what stock bcmdhd (`WL_PSK_OFFLOAD`, `wl_cfg80211_set_pmk`) and mainline brcmfmac (`brcmf_set_pmk`) send. The msgbuf request layout and lengths
  also match DHD. Order and RSN settings: wpa_auth PSK (AKM 2), AES, MFP capable, all as stock. Association succeeded, so the RSN IE was accepted.

## 3. Cause (firmware, inferred from RAM code and ranked first; the ROM part can't be read)

- `wlc_keymgmt_set_wsec_pmk` (RAM 0x2dd61c): `flags & 7` set → `wlc_pmk_add_passphrase` (key-management passphrase list).
  `flags == 0` on a STA → `wlc_sup_set_pmk` (ROM), and **0 is returned whatever it does** (also when `wlc_get_wpa_enab` is false).
- `wlc_join_infra` (RAM 0x363850) on a PSK join with the in-dongle supplicant: `printf("Start PSK to PMK conversion %d")` (the ROM string
  r1 printed), then `wlc_sup_set_ssid` (RAM 0x3d19d4). That calls `wlc_sup_passhash_deinit` and then `wlc_pmk_set_psk(passphrase from the list,
  join SSID)`. That function (RAM 0x2e1ad0) runs PBKDF2 on a timer (`init_passhash`, `km_pmk_psk_passhash_timer`) and reports through a callback.
  Meanwhile an arriving M1 is cached and answered once the PMK is ready (`wlc_sup_pmk_notif_cb` → `wlc_sup_eapol`).
  With no passphrase in the list, `wlc_pmk_set_psk` returns -0x1401 and hands the callback a NULL PMK entry.
- So this firmware's in-dongle PSK join is built around **the passphrase**. r1 gave it only a PMK, the join found no passphrase, and the
  supplicant stayed in WAIT_M1, which is exactly what r1 shows.
- Android on this phone (physical dmesg `ios26-dualboot-r8/attempts/return-after-restore/dmesg.txt` 13.66–13.94 s): `Passphrase set(wsec_info)`,
  then `pmk added succesfully`, then `WLC_E_PSK_SUP status 6` (keyed) 270 ms later. Android always gives the passphrase.
- Not proven: which ROM step drops the bare PMK (`wlc_sup_set_pmk`, `wlc_sup_passhash_deinit` and `wlc_sup_passhash_done_cb` are ROM).
  Second-ranked: no other candidate fits status 4 together with a correct PMK.

## 4. Fix

Kernel, nested release repo, branch **`hk-wifi-pass`**, commit **eef94c6fbb3cb4a40933d470387627ae186b56bf** on 7227fe7 (kernel.rootview's
commit), `0001-blazer-wifi-join-passphrase-then-pmk.patch` (cb0b5e14…), sources also in `src/`:
- `b4_net_parse` also reads **BWN2**: 176 bytes, BWN1 plus pass_len (8..63) and the passphrase (printable ASCII, zeros after it). BWN1 still works.
- `set_key`: the passphrase first, as `WLC_SET_WSEC_PMK` with flags `WSEC_PASSPHRASE` (stock's own fallback when `wsec_info` is missing,
  `wl_cfg80211_config_passphrase`; same gate entry, no new iovar). Then the 32-byte PMK, exactly as before. Each copy is wiped and the length
  is never logged. A refused passphrase stops an armed join.
- The failure line now separates `the firmware never answered M1: it had no key it could use` (status 4) from `most often a wrong password`.
- The kernel build (`build_wifi_r2.py`: fleet lock, `mk.sh -j8`, 26 s, rc 0; tree restored to `p1` b228c4f and rebuilt, rc 0;
  `build_wifi_r2.out`) produced `research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r2` **0de60bea…51ee** and `.unstripped` cfbeacaa…5651
  (Mach-O arm64). Every includer of blazer_pcie1.h recompiled. The disassembly shows `b4_net_parse` taking 0xb0/0x6c and "BWN1"/"BWN2", and
  `set_key` storing key_len=pass_len and flags 1 before `b4_ioctl(…, 0x10c, …, 0x107)`, then the PMK call.

Host tools (git-ignored research/, on m1box and the Mac, identical):
- `research/ios26-wifi-r1/tools/mkwifisecret.py` f107d012…: `blob(fields, version=2)` makes BWN2 by default. A CR in a value is refused.
  `check` prints yes/no facts only. A 64-hex PSK is BWN1-only.
- `tools/compose_wifi_join.py` adf35854…: writes BWN2 by default (`--v1` for r1's), pins the new mkwifisecret, and `check` reports
  `has_passphrase` (never a length).

Tests (host, `tests/run.sh`, receipts in `../receipts/`):
- `key_oracle.c` includes the real join.c and checks:
  - BWN2: the order wpa_auth, auth, sup_wpa, wsec, wpa_auth, mfp, passphrase (flags 1), PMK (flags 0), roam_off, both 263 bytes with
    opt_len 0, ioctl buffers wiped after each, network copy wiped, no name, passphrase or length in the log;
  - BWN1 sends the PMK alone;
  - refusals stop an armed join and are only said in a dry run;
  - no network: an all-ones PMK;
  - an open network sends no key;
  - 17 parse cases.
- `mutate_key.py` catches 15/15 mutants. `test_compose_wifi_join.py` (18 tests) adds IEEE vectors, the BWN2 layout and the secret-file edges,
  and runs the real kernel reader on both versions.
- `research/ios26-wifi-r1/tests/test_pcie1.c` (the full model, Mac): PASSED, output identical to 7227fe7's.

## 5. Image (built on the Mac from the kept secret, nothing secret printed): `build_image_r2.sh`

`research/images/a7-wifi-join-r2` (mode 700): boot.img **5e7325b5a4cfc123eda5fcb6ad37bb04c5ca0eb1ec49661ce86df9ae0620e8ff**, `image_tool check`
OK, bootable, AVB verified. The cmdline is r1's byte for byte (1008 bytes, 913ab8d9…). Overlay `secret/a7-r3-wifi-join-r2.ovl` bb600fea…
has 47 records, the last one group 26 BWN2 with a passphrase, not applied by the mask. Mac check (yes/no): name = file, PMK = PBKDF2(file),
passphrase = file, and boot.img holds the record. **This image holds the Wi-Fi password in clear** (r1 held only the PMK): keep it local and wipe it after the boot.

Rebuild (Mac, repo root): `sh research/ios26-connectivity-r1/wifi/r2/build_image_r2.sh` (any name `a7-wifi-join-rN`; it reuses the composed
overlay after the reader checks). Wipe after the boot: `sh research/ios26-connectivity-r1/wifi/r2/build_image_r2.sh wipe`. That removes
`secret/a7-r3-wifi-join*.ovl` (r1's too), the image logs, `research/images/a7-wifi-join-r*` and `mkwifisecret.py wipe`; the secret file stays.

Boot (coordinator, owner present, transmits): PLAN.md §6 with the r2 names:
```sh
adb reboot bootloader
ANDROID_SERIAL=<serial> tools/bootios research/images/a7-wifi-join-r2/boot.img a7-wifi-join-r2 \
  --mach research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r2.unstripped --wait 480
fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-wifi-join-r2-after-boot
sh research/ios26-connectivity-r1/wifi/r2/build_image_r2.sh wipe
```
Read `grep blazer-wifi` in order: `join: passphrase given to the firmware: status 0`, `key given … status 0`, `join: next: try 1`, then
`4-way handshake: status 6` or `joined in N ms`, `en0 address err 0`, `gateway answered a ping`. Diagnosis if not:
- `passphrase given: status ≠ 0`: the firmware refused the legacy form. Next: the `wsec_info` PMK_INFO_ADD form Android uses, with the SSID.
- status 4 again: the passphrase list lookup missed. Same next step.
- status 8 or more with reason 14/15: M2 went out, so the key really is wrong. Check the password.

## 6. Suggested NOTES line

- **Wi-Fi (2026-11-03, PHYSICAL r1 + HOST r2):** `a7-wifi-join-r1` associated (status 0), but the firmware's supplicant never answered M1
  (`WLC_E_PSK_SUP` 4/14, deauth 15): this firmware derives its PMK from a passphrase at join time, and r1 gave it only a PMK. r2 (XNU
  `hk-wifi-pass` eef94c6, kernel 0de60bea…, image `a7-wifi-join-r2` 5e7325b5…, holds the password) gives the passphrase, then the PMK, as Android
  does. Built, not booted: `research/ios26-connectivity-r1/wifi/r2/FIX.md`.
