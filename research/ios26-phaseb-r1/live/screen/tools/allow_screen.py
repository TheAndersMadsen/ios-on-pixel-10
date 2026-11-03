#!/usr/bin/env python3
"""Mac, repo root: admit hk_screen=, hk_screen_box= (hk-screen-dbg5) and blazer_usbcon_snap=1 (DBG3's snapshot) in
tools/image_tool.py (additive, idempotent), and refuse them with a kernel that lacks the code. Writes the before-copy and
a unified diff next to this script. SCREEN.md."""
import difflib, hashlib, sys
from pathlib import Path
P = Path('tools/image_tool.py'); OUT = Path('research/ios26-phaseb-r1/live/screen/tools')
s = P.read_text()
if "'hk_screen'" in s:
    sys.exit('already admitted: ' + hashlib.sha256(s.encode()).hexdigest())
A = "PHONE_ALLOWED.update({'blazer_gpu': r'blazer_gpu=3'})\n"
B = "        if 'blazer_keys=1' in extra and b'blazer-keys: polling pads' not in buf:"
assert s.count(A) == 1 and s.count(B) == 1, 'anchors moved'
t = s.replace(A, A + "# research/ios26-phaseb-r1/live/SCREEN.md: the glass into the dumped ramoops zone; DBG3's usbcon framebuffer snapshot.\n"
    "PHONE_ALLOWED.update({'hk_screen': r'hk_screen=(0|1|[1-9][0-9]|[1-9][0-9]{2,3})', 'hk_screen_box': r'hk_screen_box=[01]',\n"
    "                      'blazer_usbcon_snap': r'blazer_usbcon_snap=1'})\n")
t = t.replace(B, "        if any(x.startswith('hk_screen') for x in extra) and b'HK SCREEN: on, record' not in buf: die('kernel has no hk_screen (hk-screen-dbg5)')\n"
    "        if 'blazer_usbcon_snap=1' in extra and b'blazer_usbcon_snap' not in buf: die('kernel has no usbcon snapshot (DBG3 0001)')\n" + B)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'image_tool.before.py').write_text(s)
(OUT / 'image_tool-screen.patch').write_text(''.join(difflib.unified_diff(s.splitlines(True), t.splitlines(True), 'tools/image_tool.py (before)', 'tools/image_tool.py')))
P.write_text(t)
print('before', hashlib.sha256(s.encode()).hexdigest()); print('after ', hashlib.sha256(t.encode()).hexdigest())
