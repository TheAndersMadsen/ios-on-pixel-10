#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Mac only. Runs the committed tools/image_tool.py (git HEAD's blob, not the shared working tree, which other owners edit) with one allowlist hunk:
blazer_gpu_tipc=7, rung 7 (M3 S1, coremem only) of research/ios26-gpu-native-r1/COREMEM-INIT.md. __file__ is the real tools/image_tool.py so its paths resolve as usual.
The blob's sha256 and the hunk are printed, so the build is reproducible from the checkout's HEAD."""
import hashlib, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
src = subprocess.check_output(['git', '-C', str(ROOT), 'show', 'HEAD:tools/image_tool.py'])
head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], text=True).strip()
HUNK = "\n# research/ios26-gpu-native-r1/COREMEM-INIT.md: rung 7 (S1) only, the Trusty GPU route at cpus=1; the kernel refuses it beside blazer_gpu or blazer_aoc.\nPHONE_ALLOWED.update({'blazer_gpu_tipc': r'blazer_gpu_tipc=7'})\n"
anchor = b"\nPHONE_CANVAS = "
assert src.count(anchor) == 1
patched = src.replace(anchor, HUNK.encode() + anchor, 1)
print(f'image_tool_s1: HEAD {head} tools/image_tool.py sha256 {hashlib.sha256(src).hexdigest()} + hunk sha256 {hashlib.sha256(HUNK.encode()).hexdigest()}', file=sys.stderr)
sys.argv[0] = str(ROOT / 'tools/image_tool.py')
g = {'__name__': '__main__', '__file__': str(ROOT / 'tools/image_tool.py')}
exec(compile(patched, str(ROOT / 'tools/image_tool.py'), 'exec'), g)
