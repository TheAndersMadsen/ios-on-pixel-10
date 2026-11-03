#!/usr/bin/env python3
"""Compare every daemon's respawns/crashes in two qemu_preflight JSON reports.

Usage: compare_qemu_daemons.py BASE.json CANDIDATE.json [--allow NAME]...
An allowed name is printed but does not fail (use only QFARM's documented nondeterministic QEMU loops).
"""
import argparse
import json

p = argparse.ArgumentParser()
p.add_argument("base")
p.add_argument("candidate")
p.add_argument("--allow", action="append", default=[])
a = p.parse_args()
base = json.load(open(a.base))
candidate = json.load(open(a.candidate))
base = base.get("result", base)
candidate = candidate.get("result", candidate)
bd = base["daemons"]
cd = candidate["daemons"]
allowed = set(a.allow)
increases = []
new_crashes = []
for name in sorted(set(bd) | set(cd)):
    b = bd.get(name, {"execs": 0, "respawns": 0, "crashes": 0})
    c = cd.get(name, {"execs": 0, "respawns": 0, "crashes": 0})
    if c["respawns"] > b["respawns"]:
        increases.append((name, b["respawns"], c["respawns"], b["execs"], c["execs"]))
    if c["crashes"] > b["crashes"]:
        new_crashes.append((name, b["crashes"], c["crashes"]))
print("respawn increases (name: base -> candidate; exec base -> candidate):")
if not increases:
    print("  none")
for name, br, cr, be, ce in increases:
    print(f"  {name}: {br} -> {cr}; exec {be} -> {ce}" + (" [allowed QEMU loop]" if name in allowed else ""))
print("crash-count increases:")
if not new_crashes:
    print("  none")
for name, b, c in new_crashes:
    print(f"  {name}: {b} -> {c}")
bad_respawns = [x for x in increases if x[0] not in allowed]
bad_crashes = [x for x in new_crashes if x[0] not in allowed]
print(f"{'FAIL' if bad_respawns or bad_crashes else 'PASS'}: {len(bad_respawns)} unallowed respawn increases, "
      f"{len(bad_crashes)} unallowed crash increases")
raise SystemExit(bool(bad_respawns or bad_crashes))
