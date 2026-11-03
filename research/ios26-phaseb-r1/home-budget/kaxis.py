#!/usr/bin/env python3
"""Print lines matching REGEX with the kernel axis time (s since root watch start = last preceding blazer-root watch/stage tick).
Usage: kaxis.py <decoded msgbuf text> <regex>"""
import re,sys
W=re.compile(r'blazer-root: (?:watch|stage) t (\d+) ms')
t=0;
pat=re.compile(sys.argv[2])
for ln in open(sys.argv[1],errors='replace'):
    m=W.search(ln)
    for m in W.finditer(ln): t=int(m.group(1))/1000
    if pat.search(ln): print(f"{t:8.1f} {ln.strip()[:170]}")
