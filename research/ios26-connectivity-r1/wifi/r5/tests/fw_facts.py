#!/usr/bin/env python3
"""HOST ONLY. W1 r5: the firmware facts r5 stands on, read statically from Android's .57.31 fw_bcmdhd.bin_4390_b1 (RAM image, load address
0x2a0000) and its map. Thumb-2 via capstone. ROM code can't be read; every fact here is RAM code or RAM data. Prints facts, exits 1 if one fails.
Usage: fw_facts.py <bin> <map>"""
import bisect, hashlib, struct, sys
import capstone
BIN_SHA = "db46afd65f4e3d9ec4f825bc52f2487195f9bb0d43062baade35c68b26c92864"
MAP_SHA = "12cf65692efd15050479bfd6b70e0a287350b609b13e71ad62261ef0b0f990eb"
BASE = 0x2a0000
fb, fm = sys.argv[1], sys.argv[2]
data = open(fb, "rb").read()
bad = 0
def fact(ok, text):
    global bad
    print(("ok   " if ok else "FAIL ") + text)
    bad += not ok
fact(hashlib.sha256(data).hexdigest() == BIN_SHA, f"bin sha256 {BIN_SHA[:8]} (Android's .57.31, android-fw/adb-firmware.txt)")
fact(hashlib.sha256(open(fm, "rb").read()).hexdigest() == MAP_SHA, f"map sha256 {MAP_SHA[:8]}")
sym = {}
rows = []
for l in open(fm):
    p = l.split()
    if len(p) >= 3:
        try:
            a = int(p[0], 16)
        except ValueError:
            continue
        sym.setdefault(p[2], a)
        rows.append((a, p[2]))
rows.sort()
addrs = [r[0] for r in rows]
def where(a):
    i = bisect.bisect_right(addrs, a) - 1
    return f"{rows[i][1]}+{a - rows[i][0]:#x}"
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
def dis(name, n):
    a = sym[name] & ~1
    return list(md.disasm(data[a - BASE:a - BASE + n], a))
def target(i):
    try:
        return int(i.op_str.split("#")[-1], 16)
    except ValueError:
        return None

# 1. Split RX, mode 4
b = data[sym["_bcmsplitrx"] - BASE]
m = data[sym["_bcmsplitrx_mode"] - BASE]
fact(b == 1 and m == 4, f"_bcmsplitrx = {b}, _bcmsplitrx_mode = {m} (RAM data at {sym['_bcmsplitrx']:#x}, {sym['_bcmsplitrx_mode']:#x})")

# 2. pciedev_process_d2h_rxpyld: after pciedev_process_rxpost_msg gives no host address, event_log2(0x30, 0xb8c8, pkt, rxfrag) and hnd_pkt_free
ins = dis("pciedev_data$pciedev_process_d2h_rxpyld", 0x800)
calls_rxpost = [i.address for i in ins if i.mnemonic == "bl" and target(i) == sym["pciedev_data$pciedev_process_rxpost_msg"]]
k = [n for n, i in enumerate(ins) if i.mnemonic.startswith("movw") and i.op_str.endswith("#0xb8c8")]
ok = False
if len(k) == 1:
    w = ins[k[0]:k[0] + 12]
    tl = [target(i) for i in w if i.mnemonic == "bl"]
    ok = len(tl) >= 2 and tl[0] == sym["event_log2__bcmromfn"] and tl[1] == sym["hnd_pkt_free"] and any(
        i.mnemonic == "movs" and i.op_str.endswith("#0x30") for i in w)
fact(ok and len(calls_rxpost) >= 1, f"EL 0x30/0xb8c8 is event_log2 then hnd_pkt_free at {ins[k[0]].address:#x} ({where(ins[k[0]].address)}); "
     f"pciedev_process_rxpost_msg called at {', '.join(hex(c) for c in calls_rxpost)}")
# the branch into it: the host address pciedev_process_rxpost_msg returned is 0 (low word, then high word)
j = [i for i in ins if i.mnemonic.startswith("beq") and target(i) == ins[k[0]].address - 0xe] if k else []
fact(len(j) >= 1, f"reached when the returned host address is 0: {', '.join(f'{i.address:#x} {i.mnemonic} {i.op_str}' for i in j)}")

# 3. pciedev_process_rxpost_msg: message type 0x11 and data_buf_len >= 0x7f8, else osl_sys_halt
ins = dis("pciedev_data$pciedev_process_rxpost_msg", 0x320)
c11 = sum(1 for i in ins if i.mnemonic == "cmp" and i.op_str.endswith("#0x11"))
c7f8 = [i for i in ins if i.mnemonic.startswith("cmp") and i.op_str.endswith("#0x7f8")]
halt = [i for i in ins if i.mnemonic == "bl" and target(i) == sym["osl_sys_halt__bcmromfn"]]
fact(c11 >= 2 and len(c7f8) >= 1 and len(halt) >= 1, f"rxpost item: type 0x11 checked {c11}x, length vs 0x7f8 at {', '.join(hex(i.address) for i in c7f8)}, "
     f"osl_sys_halt at {', '.join(hex(i.address) for i in halt)}")

# 4. EAPOL reaches the in-dongle supplicant from wlc_recvdata_ordered (ethertype 0x888e, wlc_sup_eapol)
ins = dis("wlc_recvdata_ordered", 0x1400)
e = [i.address for i in ins if i.mnemonic.startswith("movw") and i.op_str.endswith("#0x888e")]
s = [i.address for i in ins if i.mnemonic == "bl" and target(i) == sym["wlc_sup_eapol"]]
fact(len(e) >= 1 and len(s) >= 1, f"wlc_recvdata_ordered: 0x888e at {', '.join(map(hex, e))}, bl wlc_sup_eapol at {', '.join(map(hex, s))}")

# 5. The host RX post handler refills the MAC's RX DMA from host buffers
ins = dis("pciedev_handle_h2d_msg_rxsubmit", 0x300)
f = [i.address for i in ins if i.mnemonic == "bl" and target(i) == sym["pktpool_invoke_dmarxfill__bcmromfn"]]
fact(len(f) >= 1, f"pciedev_handle_h2d_msg_rxsubmit calls pktpool_invoke_dmarxfill at {', '.join(map(hex, f))}")

# 6. Split-RX EAPOL fetch-back exists (rxfrag in host memory)
fact(all(n in sym for n in ("wlc_pktfetch$wlc_eapol_pktfetch_required", "__ramfnptr_wlc_recvdata_schedule_pktfetch", "pciedev_lbuf_rxfrag_cb")),
     "symbols: wlc_eapol_pktfetch_required, wlc_recvdata_schedule_pktfetch, pciedev_lbuf_rxfrag_cb")
print(f"fw_facts: {'all facts hold' if not bad else f'{bad} FAILED'}")
sys.exit(1 if bad else 0)
