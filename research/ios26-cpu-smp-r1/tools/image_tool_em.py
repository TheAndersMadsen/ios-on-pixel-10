#!/usr/bin/env python3
"""tools/image_tool.py with --cpu-audit in mode 2 (blazer_cpu0_audit=2: + Errata ABI queries).

Loads the shared tool's source, makes exactly the two replacements below (each must
match once, or this refuses), and runs it as tools/image_tool.py, so its sibling
imports and paths are unchanged. The shared file is not edited. Mode 2 is read only:
shim/tgl_cpu_audit.c, research/ios26-cpu-smp-r1/SMP.md.

  python3 -I research/ios26-cpu-smp-r1/tools/image_tool_em.py image NAME ... --cpu-audit ...
"""
import hashlib
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[3] / 'tools' / 'image_tool.py'
SWAPS = (
    ("    if audit: c += ' blazer_cpu0_audit=1'\n", "    if audit: c += ' blazer_cpu0_audit=2'\n"),
    ("rec['cpu_audit'] = dict(mode=1, core=0, read_only=True, a520_support_accepted=False)",
     "rec['cpu_audit'] = dict(mode=2, core=0, read_only=True, a520_support_accepted=False)"),
)


def source():
    text = TOOL.read_text()
    for old, new in SWAPS:
        if text.count(old) != 1:
            sys.exit('image_tool_em: shared image_tool.py changed; %r is not there once' % old.strip())
        text = text.replace(old, new)
    return text


if __name__ == '__main__':
    text = source()
    print('image_tool_em: base image_tool.py sha256 %s, mode 2 swaps applied' %
          hashlib.sha256(TOOL.read_bytes()).hexdigest(), file=sys.stderr)
    sys.argv[0] = str(TOOL)
    sys.path[:0] = [str(TOOL.parent)]
    g = {'__name__': '__main__', '__file__': str(TOOL)}
    exec(compile(text, str(TOOL), 'exec'), g)
