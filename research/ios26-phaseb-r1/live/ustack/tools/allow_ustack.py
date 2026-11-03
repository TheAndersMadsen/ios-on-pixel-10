#!/usr/bin/env python3
"""Mac, repo root: admit hk_ustack=, hk_ustack_s=, hk_ustack_n=, hk_ustack_max= in tools/image_tool.py (additive, idempotent),
and refuse them with a kernel that has no hk_ustack. Writes the before-copy and a unified diff next to this script. USTACK.md."""
import difflib, hashlib, sys
from pathlib import Path
P = Path('tools/image_tool.py'); OUT = Path('research/ios26-phaseb-r1/live/ustack/tools')
s = P.read_text()
if "'hk_ustack'" in s: sys.exit('already admitted: ' + hashlib.sha256(s.encode()).hexdigest())
A = "PHONE_ALLOWED.update({'blazer_gpu': r'blazer_gpu=3'})\n"
B = "        if 'blazer_keys=1' in extra and b'blazer-keys: polling pads' not in buf:"
assert s.count(A) == 1 and s.count(B) == 1, 'anchors moved'
t = s.replace(A, A + "# research/ios26-phaseb-r1/live/USTACK.md: read-only kernel sampler, user stacks of up to 4 named processes on the console.\n"
    "PHONE_ALLOWED.update({'hk_ustack': r'hk_ustack=[A-Za-z0-9._-]{1,16}(,[A-Za-z0-9._-]{1,16}){0,3}', 'hk_ustack_s': r'hk_ustack_s=([1-9]|[1-9][0-9]|[1-5][0-9][0-9]|600)',\n"
    "                      'hk_ustack_n': r'hk_ustack_n=[1-9][0-9]{0,3}', 'hk_ustack_max': r'hk_ustack_max=[1-9][0-9]{0,5}'})\n")
t = t.replace(B, "        if any(x.startswith('hk_ustack') for x in extra) and b'HK USTACK: every %u s' not in buf: die('kernel has no hk_ustack (hk-ustack-dbg4)')\n" + B)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'image_tool.before.py').write_text(s)
(OUT / 'image_tool-ustack.patch').write_text(''.join(difflib.unified_diff(s.splitlines(True), t.splitlines(True), 'tools/image_tool.py (before)', 'tools/image_tool.py')))
P.write_text(t)
print('before', hashlib.sha256(s.encode()).hexdigest()); print('after ', hashlib.sha256(t.encode()).hexdigest())
