#!/usr/bin/env python3
"""HOST ONLY. Build jb1 overlay from ABOUT's int2-about-r1 without changing unrelated records.

Changes only active hk_env record 39: extend tccd's existing insertion list and add one containermanagerd rule.
Appends the same signed probe dylib in their group (29). Every other record stays byte-identical.

Usage: jb1_overlay.py INT2_ABOUT_OVL HK_INJECT_PROBE_DYLIB OUT_OVL
"""
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[3]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MK = load("mkoverlay", "research/ios26-overlay-r1/tools/mkoverlay.py")
RC = load("rc", "research/ios26-overlay2-r1/tools/restore_cloudd.py")
sha = lambda b: hashlib.sha256(b).hexdigest()
BASE_SHA = "edbd799a3bc1651b03e3e4eb0bec0024aac69a80a663541104052543a3f795af"
MASK = 0xA0080081
PROBE = "/private/var/hk/hk_inject_probe.dylib"
OLD_TCCD = "tccd:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_stderr_console.dylib;HK_STDERR_CONSOLE=1;OS_ACTIVITY_DT_MODE=YES"
NEW_TCCD = "tccd:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_stderr_console.dylib:/private/var/hk/hk_inject_probe.dylib;HK_STDERR_CONSOLE=1;OS_ACTIVITY_DT_MODE=YES;HK_INJECT_PROBE=1"
CONTAINER = "containermanagerd:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_inject_probe.dylib;HK_INJECT_PROBE=1"


def active(row):
    return MASK >> row[1] & 1


def transform(blob, library):
    if sha(blob) != BASE_SHA:
        raise ValueError(f"base is not int2-about-r1 {BASE_SHA[:8]}")
    if library[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("probe is not a 64-bit Mach-O")
    rows = RC.decode(blob)
    if any(r[5] == PROBE for r in rows):
        raise ValueError("probe already present")
    envs = [i for i, r in enumerate(rows) if r[0] == ord("c") and r[5] == "hk_env" and active(r)]
    if envs != [39]:
        raise ValueError(f"expected active hk_env only at record 39, got {envs}")
    k, g, m, u, gi, path, data, _ = rows[39]
    old = data.decode("ascii")
    old_rules = old.split(",")
    if old_rules.count(OLD_TCCD) != 1 or any(r.startswith("containermanagerd:") for r in old_rules):
        raise ValueError("unexpected tccd/containermanagerd rules")
    new = old.replace(OLD_TCCD, NEW_TCCD) + "," + CONTAINER
    MK.env_ok(new)
    variables = [v for rule in new.split(",") for v in rule.split(":", 1)[1].split(";")]
    longest = max(len(v.encode()) for v in variables) + 1
    if len(new.encode()) + 1 > 1024 or longest > 384:
        raise ValueError("hk_env kernel bound exceeded")
    replacement = MK.pack(chr(k), g, m, u, gi, path, new.encode())
    extra = MK.pack("f", g, 0o755, 0, 0, PROBE, library)
    body = b"".join(replacement if i == 39 else r[7] for i, r in enumerate(rows)) + extra
    result = MK.MAGIC + struct.pack("<IIQ", 24 + len(body), len(rows) + 1, MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX:
        raise ValueError("overlay too large")
    out = RC.decode(result)
    assert len(out) == len(rows) + 1
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, out)) if i != 39)
    assert out[39][:6] == rows[39][:6] and out[39][6].decode() == new
    new_rules = new.split(",")
    assert [r for r in new_rules if not r.startswith("tccd:") and not r.startswith("containermanagerd:")] == [
        r for r in old_rules if not r.startswith("tccd:")]
    assert out[-1][0] == ord("f") and out[-1][5] == PROBE and out[-1][6] == library
    assert out[-1][1:5] == (g, 0o755, 0, 0)
    return result, {
        "base_sha256": BASE_SHA,
        "output_sha256": sha(result),
        "bytes": len(result),
        "records": len(out),
        "mask": hex(MASK),
        "record_39_hk_env_bytes_with_nul": len(new.encode()) + 1,
        "record_39_hk_env_capacity_remaining": 1024 - len(new.encode()) - 1,
        "longest_variable_with_nul": longest,
        "tccd_rule": NEW_TCCD,
        "containermanagerd_rule": CONTAINER,
        "appended": {PROBE: {"group": g, "mode": "0755", "sha256": sha(library), "bytes": len(library)}},
        "other_records_byte_identical": len(rows) - 1,
    }


if __name__ == "__main__":
    src, library, dst = sys.argv[1:4]
    if Path(dst).exists():
        raise SystemExit(f"{dst} exists, refusing")
    result, report = transform(Path(src).read_bytes(), Path(library).read_bytes())
    Path(dst).write_bytes(result)
    print(json.dumps(report, indent=2))
