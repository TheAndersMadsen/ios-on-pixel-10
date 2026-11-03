"""a7-ios-system-int1 -> a7-ios-system-int1-persist manifest diff. Exit 0 only for the intended line change on the same build inputs.
The ADT's seed_sha256 is random per build (it differs between pwr1 and int1 too); every other ADT fact must match."""
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
plus, minus = sorted(set(tb) - set(ta)), sorted(set(ta) - set(tb))
print(f"vs a7-ios-system-int1: cmdline {len(a['cmdline'])} -> {len(b['cmdline'])} B; tokens {len(ta)} -> {len(tb)}")
print('+', plus); print('-', minus); print('common order same:', [t for t in ta if t in tb] == [t for t in tb if t in ta])
want = (['blazer_persist=1', 'blazer_persist_period=15', 'hk_ustack=Preferences'], ['blazer_usbcon=1', 'blazer_usbcon_ch9=1', 'hk_ustack=Preferences,MobilePhone'])
facts = lambda m: {k: v for k, v in m['adt_facts'].items() if k != 'seed_sha256'}
same = {k: a.get(k) == b.get(k) for k in ('mach', 'var_overlay', 'window_base', 'bootcpu', 'cpus', 'route', 'dropped_diag', 'kernel_end', 'entry', 'segs', 'margin_bytes', 'payload_bytes')}
same['adt_facts except seed_sha256'] = facts(a) == facts(b)
print('same as int1:', same)
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k): print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:200]} -> {json.dumps(b.get(k), sort_keys=True)[:200]}")
print('CMDLINE', b['cmdline'])
rec = b.get('persist_ios_data') or {}
ok = (plus, minus) == want and all(same.values()) and rec.get('kernel_sha256') == b['mach'] == a['mach'] and rec.get('tokens') == ['blazer_persist=1', 'blazer_persist_period=15'] \
    and len(b['cmdline']) < 1024 and b.get('bootable') is True
print('MANIFEST-DIFF', 'OK' if ok else 'UNEXPECTED'); sys.exit(0 if ok else 1)
