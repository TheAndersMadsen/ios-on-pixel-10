#!/usr/bin/env python3
"""Mac only, from the repo root. Yes/no facts about the W1 r4 image against the kept secret file. Prints booleans only: never the name,
the password, the PMK, a length or a hash of any of them.

  python3 -I research/ios26-connectivity-r1/wifi/r4/verify_image_r4.py [NAME]     default a7-wifi-join-r4
"""
import importlib.util, sys
from pathlib import Path

REPO = Path.cwd()
CWJ = REPO / 'research/ios26-connectivity-r1/wifi/tools/compose_wifi_join.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else 'a7-wifi-join-r4'
    cwj = load(CWJ, 'cwj')
    mk = cwj.load(cwj.MKOVERLAY, 'mkoverlay')            # pinned
    ws = cwj.load(cwj.MKWIFISECRET, 'mkwifisecret')       # pinned
    f = ws.parse(cwj.SECRET_DIR / 'wifi.secret')
    ssid, pw = f['ssid'], f.get('password', b'')
    ovl = (cwj.SECRET_DIR / f'a7-r4-wifi-join-{name.removeprefix("a7-wifi-join-")}.ovl').read_bytes()
    recs = [r for r in cwj.records(mk, ovl) if r['group'] == cwj.GROUP and r['kind'] == 'f' and r['path'] == cwj.PATH]
    d = recs[0]['data'] if len(recs) == 1 else b''
    boot = (REPO / f'research/images/{name}/boot.img').read_bytes()
    facts = {
        'one network record': len(recs) == 1,
        'record is BWN2, 176 bytes': len(d) == 176 and d[:4] == b'BWN2',
        'name = the file': len(d) == 176 and d[24] == len(ssid) and d[44:44 + len(ssid)] == ssid,
        'PMK = PBKDF2(the file)': len(d) == 176 and d[76:108] == ws.pmk_of(pw, ssid),
        'passphrase = the file': len(d) == 176 and d[108] == len(pw) and d[109:109 + len(pw)] == pw and not any(d[109 + len(pw):]),
        'boot.img holds the record': len(d) == 176 and d in boot,
        'boot.img holds the whole overlay': ovl in boot,
    }
    for k, v in facts.items():
        print(f'{k}: {"yes" if v else "no"}')
    return 0 if all(facts.values()) else 1


sys.exit(main())
