# Wi-Fi investigation: BCM4390 association succeeds, M1 is lost before the firmware supplicant

Date: 2026-11-03. Scope: read-only source/log analysis; no phone action, build, or source edit.

**Bottom line.** `status 4 reason 14` is Broadcom `WLC_SUP_KEYXCHANGE_WAIT_M1` ending in `WLC_E_SUP_DEAUTH`; it is not IEEE reason 14, a group-cipher error, or a PTK/GTK-install error. The AP separately deauthenticates with IEEE reason 15 (4-way handshake timeout). r1-r3 posted only 64 host RX buffers while the firmware's two MAC units alone retain 538 and the shared area advertises a maximum of 6783. Every physical join produced firmware `EL: 30 b8c8` no-host-RX-buffer drops and no host RX completion. Static firmware analysis ties that event to freeing a host-bound packet when no posted buffer is available. The strong remaining inference is that M1 is among those packets; the buffer starvation itself is established, but r5's correction still needs a physical join to prove the final link.

## Evidence boundaries and source pins

- **PHYSICAL:** r1-r3 used firmware `.57.30`; they associated but never keyed. The dry run loaded firmware, scanned, attached `en0`, and transmitted nothing. r4 was **built but never booted**, so `.57.31`, `buf_key_b4_m4=1`, `PM=0`, and its RX witness have no phone result (`research/ios26-connectivity-r1/wifi/r5/FIX.md:3-6`). r5 is also unbooted.
- **HOST / FIRMWARE STATIC:** r5's firmware disassembly identifies the `EL: 30 b8c8` drop path and the EAPOL fetch-back path (`research/ios26-connectivity-r1/wifi/r5/receipts/fw-facts.txt:3-9`).
- **QEMU:** r5 only has a boot-regression comparison. QEMU removes `blazer_wifi*` as phone-only and has no BCM4390; it is not Wi-Fi evidence (`research/ios26-connectivity-r1/wifi/r5/receipts/qemu.txt:1-2,79-80`).
- Source paths below are relative to nested XNU `research/ios26-release-r1/work/xnu`. **R4** is `885589f9dc9ebd2a9148108d2e952b877263e7f3` (`hk-wifi-join3`); **R5** is `76bcd0325042ddd11ec52a7bcd2a6906c3a2da73` (`hk-wifi-join4`). r5 contains r4 and leaves its join methods unchanged.

## 1. WHAT IT DOES TODAY

### A. Gated PCIe/BCM4390 bring-up — works physically

- `blazer_wifi_init` is default-off and stages the probe; only stage 8 plus `blazer_wifi_join=1` arms transmission. `wifi_thread` maps only the required MMIO windows, supplies the embedded images, allocates one contiguous DMA arena, and calls the common driver (`bsd/dev/blazer_wifi.c:233-272,311-357`, R4).
- `p1_run` orders controller/power, PHY/root port, endpoint, chip discovery, firmware, then rings, with teardown on failure or when not held (`bsd/dev/blazer_pcie1.c:900-940`, R4).
- Phone evidence shows gen-1 x1 link-up, BCM4390 rev 5, 29-core backplane discovery, OTP-based NVRAM selection, and clean teardown: `research/laguna-usb-fix/attempts/20261102-065234-wifi-stage5-dry-r1/ramdump/kernel.log:535-551,763`.
- IPC9 control/event rings and ioctls are polled rather than interrupt-driven (`bsd/dev/blazer_bcm4390_ring.c:799-918`, R4). Firmware version/revision ioctls answer before scanning (`bsd/dev/blazer_bcm4390_ring.c:875-918`, R4).

### B. Firmware, NVRAM, CLM, TXCAP, and country — load and answer physically

- Build-time images are embedded by `B4_IMAGE`; `wifi_thread` selects firmware, four NVRAM choices, CLM, and TXCAP (`bsd/dev/blazer_wifi_fw.c:9-30`; `bsd/dev/blazer_wifi.c:251-257`, R4). r4/r5 select Android's `.57.31`; r1-r3 used `.57.30`.
- `fw_load` writes and reads back the whole firmware, installs processed NVRAM plus random seed and reset vector, enables bus mastering, releases the ARM core, and waits for the shared area (`bsd/dev/blazer_bcm4390.c:1002-1038`, R4). NVRAM token/address generation is in `load_nvram` (`bsd/dev/blazer_bcm4390.c:667-730`, R4).
- Physical evidence: full firmware readback, the expected NVRAM token, boot doorbell, IPC9 shared area, and `.57.30` version response (`.../20261102-065234-wifi-stage5-dry-r1/ramdump/kernel.log:562-596,642`).
- `blob_load` chunks CLM/TXCAP through `clmload`/`txcapload`; `load_clm_txcap` requires a usable CLM and rereads country (`bsd/dev/blazer_bcm4390_scan.c:489-600`, R4). The phone accepted 22 CLM chunks and 3 TXCAP chunks (`.../20261102-065234-wifi-stage5-dry-r1/ramdump/kernel.log:648-656`).
- Android's current firmware and the matching NVRAM/CLM/TXCAP identities are recorded without embedding the blobs in `research/ios26-connectivity-r1/wifi/android-fw/adb-firmware.txt:6-22`. r1-r3 already used the same NVRAM/CLM/TXCAP as Android; only firmware differed (`research/ios26-connectivity-r1/wifi/r4/receipts/firmware.txt:4-10`).

### C. Passive scan and event delivery — works physically

- `b4_scan` obtains the RX-post size, posts RX buffers, loads CLM/TXCAP, configures pre-up state, enables scan events, brings WLC up, starts/waits for a passive scan, and checks that no TX occurred (`bsd/dev/blazer_bcm4390_scan.c:905-976`, R4).
- Event completions use dedicated event buffers, separate from data RX buffers (`bsd/dev/blazer_bcm4390_ring.c:625-642`, R4). This distinction explains why scan events can work while EAPOL data delivery is starved.
- The dry run returned 29 results / 25 networks with zero unreadable results and zero data/probe TX (`.../20261102-065234-wifi-stage5-dry-r1/ramdump/kernel.log:692-714,754-764`). r3 later returned 37 results / 32 networks (`.../20261103-203419-a7-wifi-join-r3/ramdump/kernel.log:4981`).

### D. Security selection, authentication, and association — accepted physically; keying is not

- `parse_rsn` accepts CCMP (and records TKIP), PSK/PSK-SHA256, and MFPC/MFPR from the beacon RSN IE; `b4_join_heard` chooses usable observations and channels (`bsd/dev/blazer_bcm4390_join.c:482-541,544-614`, R4).
- r3/r4 method 1 reproduces Android's clear/security order, multi-AKM, `wsec=6`, `wsec_info` algorithms, join preferences, SSID-scoped passphrase, PMK, and wildcard join (`method1`, `pass_info`, `send_join`: `bsd/dev/blazer_bcm4390_join.c:895-1030,1133-1195`, R4). Method 2 retries the legacy passphrase/PMK order with RSN-derived cipher and PMF state (`method2`: `bsd/dev/blazer_bcm4390_join.c:1033-1074`, R4).
- `b4_join_pre_up` sets country, enables the in-dongle supplicant before `WLC_UP`, and in r4 adds `buf_key_b4_m4=1` and `PM=0` (`bsd/dev/blazer_bcm4390_join.c:400-477`, R4).
- r3 physical logs show every security operation status 0, then link-up and association status 0 for **both** methods (`.../20261103-203419-a7-wifi-join-r3/ramdump/kernel.log:5002-5016,5026-5027,5680-5693,5732-5733`). Thus association/RSN acceptance is working; 4-way keying is not.

### E. Supplicant/key path — firmware offload, not a host PTK/GTK implementation

- The kernel supplies a passphrase and/or 32-byte PMK through `WLC_SET_WSEC_PMK` or `wsec_info`, wipes temporary copies, then monitors firmware events (`give_key`, `wsec_info`, `pass_info`: `bsd/dev/blazer_bcm4390_join.c:831-917`, R4).
- `b4_join_event` treats `WLC_E_PSK_SUP` keyed/GTK-wait states as success and records the numeric status/reason (`bsd/dev/blazer_bcm4390_join.c:701-766`, R4).
- There is no host wpa_supplicant and no host PTK/GTK-install step in this design. Android's own evidence has the dongle reporting the M1-M4 timings and `idsup status:6`; the host merely logs them (`research/ios26-connectivity-r1/wifi/r4/FIX.md:29`). Therefore “PTK/GTK installation failed in XNU” is the wrong layer: XNU never reached data service, and the firmware had not reported keyed.

### F. Ethernet interface and packet-proof code — present; only attachment is physically proven

- `blazer_wifi_net_ready` creates Ethernet-family/Wi-Fi-subfamily `en0`; `blazer_wifi_net_rx` inputs mbufs and `blazer_wifi_net_addr` plumbs IPv4/default route (`bsd/dev/blazer_wifi_net.c:160-190,283-334,345-382`, R4).
- After keying, `net_run` enables frame flow; the flow ring gates TX; mode 1 implements DHCP, ARP, and one gateway ping (`bsd/dev/blazer_bcm4390_join.c:1363-1681,1694-1779`, R4).
- Physical dry-run evidence is only `en0 attached, mode 1` (`.../20261102-065234-wifi-stage5-dry-r1/ramdump/kernel.log:670`). No physical boot has produced a DHCP lease, gateway ping, DNS result, or useful packet service.

### G. Native iOS Wi-Fi contract — registry/GET subset only

- `bw_dispatch` rejects **every Apple80211 SET** with `EOPNOTSUPP`; it exposes limited power/link/role/capabilities/version/country/SSID/BSSID GETs (`bsd/dev/blazer_apple80211.c:30-65`, R4).
- `BlazerWiFiStart` can publish an `IO80211Controller`/`IO80211Interface` pair under the real `/arm-io/wlan` nub after `en0` exists (`iokit/Kernel/arm/BlazerWiFiServices.cpp:51-107`, R4). It does not implement scan/event or association ABIs.
- Consequently Settings/wifid cannot initiate a join through this adapter. The successful associations above are the kernel's armed test join, not a Settings join.

## 2. WHAT'S MISSING

### A. Precise reason-14 cause: host-RX starvation drops the EAPOL input path

1. **Decode the event correctly.** Status 4 is `SUP_WAIT_M1` (`bsd/dev/blazer_bcm4390_join.c:120`, R4); reason 14 is supplicant deauth. In both r3 methods the next physical event is AP deauth reason 15 (`.../20261103-203419-a7-wifi-join-r3/ramdump/kernel.log:5572-5574,6003-6006`). The AP associated the station, sent/retried M1, received no acceptable M2, and timed out while idsup still waited for M1.
2. **The host supplied too few data RX buffers.** r4 defines `RX_BUFS=64`, `RX_BUF_BYTES=2048`, and posts exactly 64 (`bsd/dev/blazer_bcm4390_ring.c:94-105,558-567`, R4). The r3 shared area says `max_host_rxbufs=6783`; firmware consoles report `nrxbufpost=384` and `154` on the two MAC units (`.../20261103-203419-a7-wifi-join-r3/ramdump/kernel.log:4780,4790,4803`). The initial MAC fill alone can therefore consume all 64, leaving no queued host buffer for a host-bound EAPOL fetch.
3. **Drops coincide with joins, not the dry run.** Distinct `EL: 30 b8c8` counts are 0 for the dry run, 4 for r1, 4 for r2, and 17 for r3; all have zero `rx: item` completions (`research/ios26-connectivity-r1/wifi/r5/receipts/physical-drops.txt:1-5`). r3's post-scan state is explicitly `rx: 0 items back` (`.../20261103-203419-a7-wifi-join-r3/ramdump/kernel.log:4997`).
4. **The firmware identifies the drop mechanism.** In `.57.31`, `pciedev_process_d2h_rxpyld` emits event-log format `0xb8c8` and calls `hnd_pkt_free` when `pciedev_process_rxpost_msg` returns host address 0. The firmware is split-RX mode 4; RX posts feed MAC RX DMA, and EAPOL fetch-back symbols exist (`research/ios26-connectivity-r1/wifi/r5/receipts/fw-facts.txt:3-9`). r5 counts this exact signature in `b4_console_note` (`bsd/dev/blazer_bcm4390.c:838-858`, R5).
5. **EAPOL is fetched back to idsup.** Static firmware analysis finds ethertype `0x888e` in `wlc_recvdata_ordered` calling `wlc_sup_eapol`, plus `wlc_eapol_pktfetch_required` / `wlc_recvdata_schedule_pktfetch` (`research/ios26-connectivity-r1/wifi/r5/receipts/fw-facts.txt:7-9`). Management auth/association can complete internally while M1—the first data-frame test of the host-RX path—never reaches idsup.

**Certainty boundary:** the no-buffer drops, inadequate 64-buffer supply, zero RX completions, and firmware drop semantics are observed/static facts. Identifying a particular dropped packet as M1 is not possible from the event's heap-pointer argument; M1 loss is the strongly supported inference from timing and the EAPOL path. A physical r5 join is the falsification test.

### B. Why the other proposed causes do not fit

- **Group cipher / RSN IE / AKM:** both r3 methods associated with status 0, one with multi-AKM + `wsec=6`, the other with PSK + RSN-derived `wsec=4`. A cipher/RSN rejection would fail association, not wait for M1 after association.
- **PMF/MFP:** r3 tried both `mfp=1` and `mfp=0` (required only when the RSN IE demands it), with association succeeding both ways (`bsd/dev/blazer_bcm4390_join.c:1039-1063`, R4; physical lines above). PMF is not the common failure.
- **Wrong passphrase/PMK:** a wrong PMK normally permits M2 and fails later (for example WAIT_M3), whereas every attempt stayed at WAIT_M1. r2 added the passphrase and r3 added Android's SSID-scoped `wsec_info` form without changing the result (`research/ios26-connectivity-r1/wifi/r3/FIX.md:9-15`).
- **PTK/GTK install:** there is no host install path, and firmware never reports keyed. This is downstream of M1 delivery, not the current failure.
- **Firmware `.57.30` versus `.57.31`:** the update is sensible and included in r4/r5, but cannot be called the fix: r4 never booted. The same no-buffer event exists in the r1-r3 consoles and is explained by the static `.57.31` path.

### C. Missing beyond the immediate blocker

- No physical keyed event, RX completion, DHCP lease, gateway ping, DNS, TLS, or reconnect.
- No flow-ring delete/rejoin lifecycle; `net_run` explicitly stops on link loss (`bsd/dev/blazer_bcm4390_join.c:1735-1753`, R4).
- No userland network-service/DNS publication and no Apple80211 scan/associate/power/key SETs or IO80211 event producer.
- The r4 failure message still says WAIT_M1 means the firmware “had no key it could use” (`join_wait`, `bsd/dev/blazer_bcm4390_join.c:1247-1253`, R4). That diagnosis is now misleading and should point to the RX witness/drop counters.

## 3. FIX PATH

### Step 1 — Make the next candidate the transport fix, not another security permutation

Keep r5's minimal delta on top of r4:

- `bsd/dev/blazer_bcm4390_ring.c`: `RX_BUFS=1024`, `RX_POST_DEPTH=RX_BUFS+64`, `RX_CPL_DEPTH=1024`, `B4_DMA_NEEDED=0x280000`; `b4_rx_bufs_wanted` caps at firmware `max_host_rxbufs`; `b4_rx_post_all` posts that count; `on_rx_item` reposts each completed buffer (`:94-115,158-161,562-580,670-700`, R5).
- `bsd/dev/blazer_wifi.c`: `WIFI_DMA_BYTES=0x280000`, allocated once by `dma_alloc` (`:58,150-161`, R5). Keep RX IDs below TX IDs and 2048-byte buffers; the static assertions enforce both (`bsd/dev/blazer_bcm4390_ring.c:158-163`, R5).
- `bsd/dev/blazer_bcm4390.c`: retain `b4_console_note` and expose its count in `b4_rx_witness` (`:838-858`, R5; `bsd/dev/blazer_bcm4390_ring.c:583-596`, R5).
- Keep r4's `.57.31`, pre-up supplicant, `buf_key_b4_m4=1`, `PM=0`, and r3's two join methods unchanged so the physical test isolates RX capacity.
- In the next source revision, correct `join_wait`'s WAIT_M1 text to “M1 was not observed; inspect RX-post indices, EL 30 b8c8, and rx* counters” rather than asserting missing key material.

**Proof before boot:** `research/ios26-connectivity-r1/wifi/r5/tests/run.sh`; its existing receipt passes ring/console oracles, 13/13 transport mutants, 25 join cases, 18 secret-reader tests, and checks ARM64e objects/kernel symbols (`research/ios26-connectivity-r1/wifi/r5/receipts/run.out:1-69`). `research/ios26-connectivity-r1/wifi/r5/receipts/kernel.txt:5-17` independently shows the 1024 selection and 2.5-MiB allocation in the built kernel. Use `tools/image_tool.py check` on the composed image; these are host/build checks, not join acceptance.

### Step 2 — Run one physical r5 join and accept only end-to-end evidence

With the coordinator/owner's normal transmit consent and temporary-boot procedure, boot r5 and collect the attempt through `hk find --feature wifi` and `hk logs --sub wifi`. Do not print credentials or the composed overlay.

Required order:

1. Firmware version is `.57.31`, proving the intended kernel booted.
2. `rx: 1024 buffers posted` (or a lower firmware-advertised cap), with the post-ring read index advancing; no contiguous-memory/NO-DMA stop.
3. `Firmware drops ... EL 30 b8c8: 0` after each method; no decoded no-host-buffer warning.
4. At least one `rx: item` / advancing RX completion index, then `PSK_SUP status 6`, `join: joined`, and `keyed by method N`.
5. Flow-ring creation succeeds; DHCP assigns an address; default route error is 0; gateway ping succeeds. Only that combination is W1 PASS.
6. Finish with the normal Android return check. A firmware “UP,” association, or `en0 attached` alone remains non-acceptance.

The relevant debug producers are `b4_rx_witness`, `b4_rx_counters`, `b4_console_note`, `b4_join_event`, and `net_run`; the reader is `hk logs --sub wifi`. `hk logs wifid` is useful only for separate native-service diagnosis, not as a substitute for the kernel join evidence.

### Step 3 — If no-buffer drops persist, fix posting/replenishment before touching WPA again

- If allocation fails or fewer than 1024 are posted, diagnose `dma_alloc`/`carve_all`; allocate earlier or use a smaller safe count above the 538 MAC-fill demand (r5 suggests at least 600). Do not silently continue with 64.
- If `EL 30 b8c8` remains nonzero, compare host write versus dongle read indices in `b4_rx_witness`. Extend `b4_rx_post_all` / `on_rx_item` to replenish in bursts toward `max_host_rxbufs`, as Android does, rather than only increasing a one-time allocation blindly.
- If the dongle read index stays zero, inspect `post_rx`'s item type/ID/length/address and H2D doorbell/index handling (`bsd/dev/blazer_bcm4390_ring.c:445-462`, R5) and then Android host-capability differences. The r4 `host_rxbuf_post_t` layout already matches DHD, so a static layout rewrite is not first priority (`research/ios26-connectivity-r1/wifi/r4/FIX.md:33-34`).

**Proof:** repeated `rx: witness` lines and `EL 30 b8c8` count via `hk logs --sub wifi`; host-side targeted cases belong in r5's `ring_oracle` / `console_oracle` and `mutate_r5.py`.

### Step 4 — If drops reach zero but status remains 4/14, classify the next RX loss

Use r4's `b4_rx_counters` (`bsd/dev/blazer_bcm4390_scan.c:722-726`, R5), which reports `rxframe`, `rxerror`, `rxnobuf`, `rxnondata`, `rxnoscb`, `rxbadproto`, `rxbadda`, and `rxfilter` deltas:

- `rxnobuf` still rising: buffer lifecycle/capacity remains wrong.
- `rxbadda`: destination/MAC/filtering path.
- `rxnoscb`: station/SCB association state.
- `rxbadproto` / `rxnondata`: protocol/data classification or EAPOL fetch-back.
- `rxframe` not rising: look below the host rings at radio/channel/link state.

Only after these counters clear should host capabilities, RX offset/metadata, or another firmware difference be changed. Do not return to random RSN/PMF/passphrase changes while association remains status 0. The proof remains `hk logs --sub wifi` plus the firmware console decoded against the matching map.

### Step 5 — If keyed but packet service fails, debug the post-key data path separately

Check in order: `b4_on_flow_created` → `b4_tx_post` / TX completion → `on_rx_item` offset/length → `take_dhcp` / `proof_tick` → `blazer_wifi_net_addr` (`bsd/dev/blazer_bcm4390_join.c:1512-1681,1683-1779`; `bsd/dev/blazer_wifi_net.c:345-382`, R4). Use `hk logs --sub wifi` for flow/DHCP/ARP/ping evidence. A keyed association without DHCP+ping is not W1 completion.

After W1, treat configd/DNS publication, disconnect/rejoin, lease renewal, flow-ring deletion, native Apple80211 SET/events, and Settings/wifid as separate milestones; none should be claimed from this fix.

## 4. RISKS

| Risk | Impact | Mitigation / falsifier |
|---|---|---|
| **r5 is unbooted; M1 identity is inferred** | The buffer defect is real but may not be the only M1 blocker. | Require physical zero-drop + RX-completion + status-6 evidence; if drops clear and 4/14 remains, execute Step 4 rather than declaring success. |
| **1024 is still below firmware max 6783** | Two MAC fills plus queued host traffic can exhaust the pool again. | Watch post/completion indices and EL count; implement burst replenishment before raising contiguous memory substantially. |
| **2.5-MiB contiguous, never-freed DMA arena** | Allocation failure or lasting memory pressure; a bad DMA address risks chip-visible corruption. | Fail closed before chip access, preserve static bounds/ID assertions, and keep the allocation lifetime until DMA is finally quiesced. |
| **Cleartext passphrase in r4/r5 boot artifacts** | Credential disclosure through images, overlays, logs, or accidental submission. | Keep artifacts local and access-controlled, log only yes/no facts, never commit them, and run the documented wipe after the test. |
| **Armed methods transmit** | Probe requests, joins, and a disassociation have regulatory/network side effects. | Owner/coordinator consent, correct country/CLM, temporary boot only, no source changes that broaden TX without review. |
| **Misleading WAIT_M1 diagnostic** | Future lanes may resume disproved password/cipher changes. | Correct `join_wait` text and always pair it with RX witness/drop evidence. |
| **Two security methods obscure causality** | A pass does not by itself identify the necessary transport setting if other variables change too. | Keep r4/r3 security bytes/order fixed for the r5 test; record which method keyed. |
| **No production lifecycle** | Link loss, reconnect, lease renewal, or repeated joins can leak DMA/flow-ring state. | Limit acceptance to the one-shot W1 proof, then implement/test teardown and reconnect before persistent service. |
| **QEMU/host overclaim** | A booting kernel or passing oracle says nothing about real M1/RX DMA. | Label evidence HOST/QEMU/PHYSICAL; only the phone can accept the Wi-Fi fix. |
| **Native Settings remains unsupported** | W1 success could be mistaken for user-visible Wi-Fi service. | Keep the GET-only limitation explicit; require separate Apple80211 SET/event and configd/DNS acceptance later. |
