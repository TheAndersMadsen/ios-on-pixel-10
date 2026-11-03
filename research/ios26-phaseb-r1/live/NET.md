# NET: IPv4 between iOS and the Mac over the USB cable (2026-11-03, HOST + BUILD only, not booted)

Status: **ready for one attended boot.** Kernel built, image built and `check` OK, host tests PASS. There is no
physical evidence yet: Mac driver binding, bulk DMA, ARP/ICMP and console coexistence over ECM have never run on the phone.

| Item | Value |
| --- | --- |
| Image | `research/images/a7-ios-system-dbg1-net/boot.img` **21357130f9bd3a512f15133e10c76530d6ba99f8907b1988340e7a6931d2c33b** (manifest e2f397e7…, `check` OK, cmdline 990 bytes) |
| Kernel (Mac) | `research/ios26-phaseb-r1/live/net/build/kernel.dbg1-net` 2d7897e1de13c5059f5b9510c441390c85bf48c29dbffd2e38570875d490c0ab, `.unstripped` b476de96f19c53bf9f67e234582e61ec91f8f6804204dd11cb06f34e8e5f36f4 |
| XNU | Mac `research/ios26-release-r1/work/xnu`, branch **hk-usbnet-dbg1** = hk-touch-direct e731e68 + **ef73d1b** (`net/patches/0001-…patch` 5f48e198…). Tree restored to p1 b228c4f, clean, p1 rebuilt (obj kernel 02fe6cdd…) |
| Addresses | phone en2 **192.168.77.2/24** (MAC 02:68:6b:00:00:02), Mac **192.168.77.1/24** on the ECM interface (MAC 02:68:6b:00:00:01). No default route, DHCP, DNS or NAT |
| USB identity | 1209:0003 "hackios XNU console", one composite gadget: EP0 = console (same wire protocol as 1209:0002), interfaces 0/1 = CDC-ECM |

## Why 192.168.77.x and not 10.42.0.x

The existing kernel (`UNQ_PHONE_IP`/`UNQ_MAC_IP` in `bsd/dev/blazer_usbnet_queue.h`, log text in `blazer_usbnet.c`) and the
owner's Mac helper `tools/usbnet_mac.py` (uncommitted, read only here) already agree on 192.168.77.0/24, and the helper
refuses a plan on a conflict. Moving to 10.42.0.0/24 would have meant editing that helper. `tests/test_net_consistency.py`
pins the two together.

## What was already there (source, e731e68) and what changed

Already present and reused unchanged: the CDC-ECM function on the one DWC3 gadget (`osfmk/arm64/blazer_usbcon_core.inc`:
IAD, notify EP 0x82, bulk 0x81/0x01, SET_ETHERNET_PACKET_FILTER only, explicit END_TRANSFER retirement), with both
opt-ecm_final_review findings already fixed in this tree (F1: a BUSERR during the END wait now stops the transport; F2:
SET_INTERFACE on interface 0 STALLs). Also the BSD `en2` ifnet with a static address (`blazer_usbnet=1`, plus
`blazer_usbnet_direct=1` for no default route), and `tools/usbcon.py` accepting PID 0003 (da49d1b).
Coexistence with the console is designed in: vendor requests 0xc0/0x40 bypass `un_setup`, the console keeps EP0, ECM
moves the event ring to its own 1 MiB arena (`0xbef00000`, the abl@be000000 reservation's last MiB).

Changed (ef73d1b, 2 files, +112): `bsd/dev/blazer_usbnet.c` prints one console line per ARP or ICMP frame in each
direction, using `bsd/dev/blazer_usbnet_log.h`, a describer with no XNU types that the host tests include. It prints the
first 64 frames per direction, then one count line every 256. TX copies the frame head before `unq_push`, because the
queue owns the mbuf after the push. Nothing else changes, and it is inactive without `blazer_usbnet`.

```
blazer-usbnet: rx arp request who-has 192.168.77.2 tell 192.168.77.1
blazer-usbnet: tx arp reply 192.168.77.2 is-at 02:68:6b:00:00:02
blazer-usbnet: rx icmp echo request 192.168.77.1 > 192.168.77.2 id 0x1a2b seq 0 len 84
blazer-usbnet: tx icmp echo reply 192.168.77.2 > 192.168.77.1 id 0x1a2b seq 0 len 84
```

## Evidence (host and build only)

- `net/receipts/tests.txt`: C host test of the actual header under ASan/UBSan, **108 checks, 0 failed**. Six mutants,
  **6/6 killed** (`receipts/mutants.txt`). `tests/test_net_consistency.py` **6/6 OK** against `git archive e731e68`:
  descriptor parses as one ECM function, 1209:0003, the iMACAddress string equals the helper's HOST_MAC, the IPs equal
  the helper's, TX copy precedes the push, and `usbnet_mac.py --plan` on a synthetic snapshot emits exactly the commands
  below (and refuses on a 192.168.77/24 conflict).
- ARM64 (Mac build): `blazer_usbnet.o` is a Mach-O arm64 object with `_un_note` (t), `_un_seen` (b), `_uc_net_rx/_tx/_link/_error`
  and `_blazer_usbnet_bsd_ready`. The kernel holds `_uc_net_rx`, `_uc_net_tx`, `_blazer_usbcon_start` and
  `_blazer_usbnet_bsd_ready`, plus the strings `arp request who-has`, `icmp echo %s`, `arp/icmp frames` and
  `blazer_usbnet_direct`. e731e68's `sweet_touch_indirect` and f24a98d's `backlight-calibration-parameters` are present.
  p1's `blazer_ufs_fake_lun` and the AKS branch's `blazer_aks_wrap` are absent.
- Build pitfall, recorded: the first build (kernel 8d79818e…, deleted) lacked the change. `shutil.copy2` had kept the
  source's older mtime, and another owner's build had just produced a newer `blazer_usbnet.o`, so make skipped the file.
  `build_net.py` now uses a plain copy plus a touch, and refuses a kernel without `arp/icmp frames`.

## Image recipe (`net/mkimg_net.sh`, run on the Mac)

This is `research/ios26-apps-r1/usersession/mkimg.sh`'s ufs variant (r9-apps-ufs): same overlay f5d4c367…, `--phone-route
ufsroot` (`rd=ufsroot0`), 5 cores, bootcpu 0x200, deadline 300, canvas 1125x2511. Differences from r9-apps-ufs's cmdline:
- removed `blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_persona_log=1`, which e731e68 does not read (they belong to
  the hk-aks-usersession branch; `git grep` on e731e68 finds only `blazer_aks_log`, kept);
- added `blazer_usbnet=1 blazer_usbnet_direct=1`.
So this boot has no AKS wrap. r3, which reached Home, had none either.

`tools/image_tool.py` on the Mac had no `blazer_usbnet` entry. `net/tools/allow_usbnet.py` adds one allowlist line and a
gate: usbnet needs both tokens plus `blazer_usbcon`, and a kernel with the ARP/ICMP log. The patch is
`net/tools/image_tool-usbnet.patch` (Mac 45eadfe3 → b4909202). **The coordinator should carry it into the root
`tools/image_tool.py`.** The m1box copy differs and is another owner's working copy.

## The attended boot (coordinator runs the phone; everything below is on the Mac, from the repo root)

The deadline is 300 s from XNU entry, Home comes at about 110 s, and en2 is configured early in bsd_init. Do steps 2-6
within roughly 4 minutes. Shells: A = runner, B = console, C = network.

```sh
# 0 (C, before the boot): baseline
mkdir -p research/ios26-phaseb-r1/live/net/attempt
/sbin/ifconfig -a > research/ios26-phaseb-r1/live/net/attempt/ifconfig-before.txt

# 1 (A): the boot, bare fastboot boot via the runner, force-fastboot on, as for A7
tools/bootios research/images/a7-ios-system-dbg1-net/boot.img a7-ios-system-dbg1-net \
  --mach research/ios26-phaseb-r1/live/net/build/kernel.dbg1-net.unstripped --wait 480

# 2 (B): live console as soon as 1209:0003 appears (sole EP0 reader; read only)
/tmp/tegu-venv/bin/python -u tools/usbcon.py --timeout 420 --gone-exit 15 \
  --output research/ios26-phaseb-r1/live/net/attempt/usbcon.log
#   expect (order varies): "blazer-usbnet: mode 1, on, arena 0xbef00000", "blazer-usbnet: configured, data alt 0",
#   "blazer-usbnet: data interface alt 1", "blazer-usbnet: link up", "blazer-usbnet: en2 attached, mode 1, ...",
#   "blazer-usbnet: en2 192.168.77.2/24 err 0, direct IPv4, no default route"
#   macOS may ask to allow the new accessory (1209:0003 is a new identity): the owner clicks Allow.

# 3 (C): binding and the interface (the helper only prints; it never runs anything)
ioreg -l -w0 | grep -i -B2 -A6 'AppleUserECM' | head -40 > research/ios26-phaseb-r1/live/net/attempt/ioreg-ecm.txt
/sbin/ifconfig -a > research/ios26-phaseb-r1/live/net/attempt/ifconfig-after.txt
python3 -I tools/usbnet_mac.py --plan --snapshot research/ios26-phaseb-r1/live/net/attempt/ifconfig-after.txt
#   It names enN (the interface whose ether is 02:68:6b:00:00:01). If it says "must already be UP and active", check
#   the console for "link up", then `sudo /sbin/ifconfig enN up` and re-snapshot.

# 4 (C): the alias the plan prints (enN from step 3)
sudo /sbin/ifconfig enN inet 192.168.77.1 netmask 255.255.255.0 alias

# 5 (C, second tab): Mac-side capture, bounded
sudo /usr/sbin/tcpdump -ni enN -c 24 -l 'arp or icmp' | tee research/ios26-phaseb-r1/live/net/attempt/tcpdump.txt

# 6 (C): THE TEST, exactly the plan's probe
/sbin/ping -n -c 4 -t 8 -W 1000 -b enN -S 192.168.77.1 192.168.77.2 | tee research/ios26-phaseb-r1/live/net/attempt/ping.txt
#   (plain `ping 192.168.77.2` works too once the alias exists)

# 7 (C): undo only this alias (it also disappears when the phone leaves the bus)
sudo /sbin/ifconfig enN inet 192.168.77.1 -alias

# 8 (after the deadline park, B's output finished): console vs ramdump
python3 -I tools/usbcon.py --verify research/ios26-phaseb-r1/live/net/attempt/usbcon.log --dump <attempt>/ramdump/kernel.log
```

Then the usual Android return check.

**PASS** requires all of the following:
- `ping.txt` shows at least 1 of 4 replies from 192.168.77.2 (4/4 expected);
- `usbcon.log` (or the ramdump) holds `blazer-usbnet: rx arp request who-has 192.168.77.2 tell 192.168.77.1` and
  `blazer-usbnet: rx icmp echo request 192.168.77.1 > 192.168.77.2 …` with matching `tx … reply` lines;
- `tcpdump.txt` shows the same exchange;
- the console stream keeps flowing during the ping, and `--verify` passes.

**FAIL / stop, no retry or alt cycling:**
- no 1209:0003, or no AppleUserECM binding (record `ioreg`);
- `en2 … err` is nonzero;
- `blazer-usbnet: stopped, DMA ownership not reusable` (a bus error, terminal by design);
- the console stops;
- an unexpected reset.

Ruled out by design: a Mac reply with no phone `rx` line means the frame arrived but was not ECM traffic.

## Diagnosis guide for the one boot

| Console shows | Meaning |
| --- | --- |
| no `blazer-usbnet: mode 1` | usbcon refused (shim stamps): look at the `blazer-usbcon: refused:` line |
| `configured`, never `alt 1` | the host did not select the data interface: AppleUserECM not bound or the accessory not allowed |
| `alt 1`, no `rx arp` while the Mac pings | the Mac sends nothing to us (wrong enN or alias) or RX bulk DMA does not complete |
| `rx arp request`, no `tx arp reply` | ARP or the address on en2 (check `en2 … err 0`) |
| `tx arp reply` but the Mac sees no reply | TX bulk path (TRB/pad), or the host drops it |
| `rx icmp` + `tx icmp reply`, ping times out | TX bulk path, as above |

## Not changed / open

- No ZLP: TX still pads a 512-multiple frame with one byte (Linux's fallback; IP ignores it). Explicit ZLP is the
  usb-networking audit's cleaner target.
- `blazer_usbnet_bounds` was not enabled. The non-strict path is the one that has existed all along.
- No configd/IONetworkStack registration (mode 2), DNS, Internet or NAT; this is a kernel-only direct link for debugging.
- Composition: another lane has uncommitted live-input/snapshot changes to `blazer_usbcon*.c/.inc` and SweetHID (m1box
  mirror). ef73d1b touches only `bsd/dev/blazer_usbnet.c` and the new header, so the two merge by file.

## Files (`research/ios26-phaseb-r1/live/net/`)

`xnu-src/` (blazer_usbnet.c 47fade3e…, blazer_usbnet_log.h b37be9ec…, build_net.py 3db8d621…), `patches/0001-…patch`,
`tests/` (test_usbnet_log.c f15799e4…, test_net_consistency.py c3ca56f1…), `tools/` (allow_usbnet.py, image_tool-usbnet.patch),
`mkimg_net.sh` 593fee01…, `receipts/` (tests.txt, mutants.txt, image-*.out, check-*.out). The kernels and the boot.img
stay out of git (Mac `net/build/`, `research/images/a7-ios-system-dbg1-net/`).
