#!/usr/bin/env python3
"""Repo root (m1box or Mac): write usbhost/tools/image_tool_usbhost.py = int/tools/image_tool_int1.py (728bdd21, the tool
a7-ios-system-obs1 was built with) + the blazer_usbhost allowlist and gate. Additive; the shared tools/image_tool.py and
int1's copy are never written. Prints both hashes and writes the diff to usbhost/receipts/image_tool_usbhost.patch.

Gate (refused unless all hold): blazer_usbhost=1 present for any blazer_usbhost_* token; no blazer_usbcon*/blazer_usbnet*
token (one controller, one owner); the kernel holds the ENUM line (hk-usbhost1); wait + window + 45 s ends before the
deadline (the result must be in the msgbuf before the deadline panic)."""
import difflib, hashlib, sys
from pathlib import Path
SRC = Path('research/ios26-phaseb-r1/int/tools/image_tool_int1.py')
DST = Path('research/ios26-phaseb-r1/usbhost/tools/image_tool_usbhost.py')
RCP = Path('research/ios26-phaseb-r1/usbhost/receipts/image_tool_usbhost.patch')
SRC_SHA = '728bdd21dc853746b2e7d10597565d2584c29af3134797120c1d43b0c3f6ecfd'
s = SRC.read_text()
if hashlib.sha256(s.encode()).hexdigest() != SRC_SHA:
    sys.exit(f'{SRC} is not int1\'s 728bdd21: refusing')
A = "PHONE_ALLOWED.update({'blazer_netstack': r'blazer_netstack=1'})"
B = "        if 'blazer_keys=1' in extra and b'blazer-keys: polling pads' not in buf:"
assert s.count(A) == 1 and s.count(B) == 1, 'anchors moved'
a_line = next(l for l in s.splitlines(True) if l.startswith(A))
t = s.replace(a_line, a_line +
    "# research/ios26-phaseb-r1/usbhost/USBHOST.md: DWC3 host mode, USB2 root ports, enumerate one device; no console in that boot.\n"
    "PHONE_ALLOWED.update({'blazer_usbhost': r'blazer_usbhost=1', 'blazer_usbhost_wait': r'blazer_usbhost_wait=([0-9]|[1-9][0-9]{1,2})',\n"
    "                      'blazer_usbhost_window': r'blazer_usbhost_window=[1-9][0-9]{0,2}'})\n")
t = t.replace(B,
    "        if any(t.startswith('blazer_usbhost') for t in extra):\n"
    "            if 'blazer_usbhost=1' not in extra: die('blazer_usbhost_* needs blazer_usbhost=1 (usbhost/USBHOST.md)')\n"
    "            if any(t.startswith(('blazer_usbcon', 'blazer_usbnet')) for t in extra): die('blazer_usbhost=1 owns the controller: no blazer_usbcon*/blazer_usbnet* in that image (results come back in the ramdump)')\n"
    "            if b'blazer-usbhost: ENUM port %u speed %s dev %04x:%04x' not in buf: die('kernel has no blazer_usbhost (hk-usbhost1)')\n"
    "            uw = {t.split('=')[0]: int(t.split('=')[1]) for t in extra if t.startswith(('blazer_usbhost_wait=', 'blazer_usbhost_window='))}\n"
    "            if uw.get('blazer_usbhost_wait', 90) + uw.get('blazer_usbhost_window', 150) + 45 > (getattr(a, 'phone_deadline', None) or 900): die('blazer_usbhost: wait + window + 45 s must end before --phone-deadline')\n"
    + B, 1)
t = t.replace("# int/tools/image_tool_int1.py: the Mac's acf48b98 + pwr1 + netstack (INT1.md), run from here",
              "# usbhost/tools/image_tool_usbhost.py: int1's 728bdd21 + blazer_usbhost (usbhost/tools/mk_image_tool_usbhost.py)", 1)
assert "Path(__file__).resolve().parents[4]/'tools'" in t, 'depth: usbhost/tools is as deep as int/tools'
DST.write_text(t)
RCP.parent.mkdir(parents=True, exist_ok=True)
RCP.write_text(''.join(difflib.unified_diff(s.splitlines(True), t.splitlines(True), str(SRC), str(DST))))
print('source', SRC_SHA)
print('copy  ', hashlib.sha256(t.encode()).hexdigest(), DST)
