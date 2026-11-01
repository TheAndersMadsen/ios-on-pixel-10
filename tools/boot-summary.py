#!/usr/bin/env python3
"""One screen on one boot attempt: stage, nonce, UFS, panic, furthest milestone.

  tools/boot-summary.py <attempt dir> [--json]

Host only; reads the attempt directory and the files beside its image. Everything
from log RAM is checked against this boot. A value that cannot be bound to it is
called residue or unknown. Exit 0 after a summary, 2 if the dump is missing.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
import zlib

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DUMP_BASE = 0x95200000
READ_RECORD = 0x22a000
READ_BYTES = 0x2000
LINK_RECORD = 0x227c00
LINK_BYTES = 256
WIDTH = 100
KINDS = {b"UFSRDR1\0": "read", b"UFPLPR1\0": "post-link", b"DCSR1LOG": "display"}
ABL_FIELDS = (
    ("rst_stat", r"RST_STAT:\s*(0x[0-9a-fA-F]+[^\n]*)"),
    ("reason", r"GDMC reboot reason:\s*(0x[0-9a-fA-F]+)"),
    ("wdt_sub", r"APC WDT sub reason:\s*(0x[0-9a-fA-F]+)"),
    ("thermal", r"CPM thermal trip breadcrumb:\s*(0x[0-9a-fA-F]+)"),
    ("pmic_main", r"Main-PMIC reset reason:\s*(0x[0-9a-fA-F]+)"),
    ("pmic_sub", r"Sub-PMIC reset reason:\s*(0x[0-9a-fA-F]+)"),
    ("soc_temp", r"SOC Temp:\s*(-?\d+C)"),
    ("battery", r"\[max77779fg\]\s*SOC\((\d+)\),\s*VCELL\((\d+)\)"),
)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_text(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def macho_uuid(path):
    """LC_UUID of a 64-bit Mach-O, or None."""
    try:
        with open(path, "rb") as source:
            head = source.read(0x10000)
    except OSError:
        return None
    if len(head) < 32 or struct.unpack_from("<I", head)[0] != 0xfeedfacf:
        return None
    off = 32
    for _ in range(struct.unpack_from("<I", head, 16)[0]):
        if off + 8 > len(head):
            return None
        cmd, size = struct.unpack_from("<II", head, off)
        if cmd == 0x1b:
            raw = head[off + 8:off + 24].hex().upper()
            return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
        off += size
    return None


def beside_image(image, *names):
    """First JSON file of these names in the image's directory or the one above."""
    folder = Path(image).parent
    for where in (folder, folder.parent):
        for name in names:
            try:
                return json.loads((where / name).read_text())
            except (OSError, ValueError):
                continue
    return {}


def decode_ufs(dump, ids, stamps_text, live_text, mirror_text, entry_fresh):
    """UFS result of this boot only. A record with another boot's nonce is residue."""
    out = {"record": None, "link": None, "read": None, "xnu": None,
           "live": None, "ladder": None}
    match = re.findall(r"^UFS\s+steps=\S+ live=(\S+)", live_text, re.M)
    out["live"] = match[-1] if match else None
    ladder = re.findall(r"ufs-ladder\s+(DONE|REFUSED|FAULT)\s+(0x[0-9a-f]+)", stamps_text)
    if ladder:
        out["ladder"] = {"flag": ladder[-1][0], "arg": ladder[-1][1]}
    raw = dump[READ_RECORD:READ_RECORD + READ_BYTES]
    kind = KINDS.get(raw[:8])
    want = ids.get("record_nonce")
    if kind and want:
        out["record"] = {"kind": kind, "current": raw[16:32] == bytes.fromhex(want)}
    elif kind:
        out["record"] = {"kind": kind, "current": None}
    if ids:
        out["link"] = _link(dump, ids)
        if out["record"] and out["record"]["kind"] == "read" and out["record"]["current"]:
            out["read"] = _read(raw, ids)
    if entry_fresh and mirror_text:
        done = re.findall(r"blazer-ufs-test: done, (\d+) errors", mirror_text)
        reads = re.findall(r"blazer-ufs-test: (?:raw|part) lba", mirror_text)
        if done or reads:
            out["xnu"] = {"reads": len(reads), "errors": int(done[-1]) if done else None,
                          "done": bool(done)}
    return out


def _link(dump, ids):
    """Link record of this boot. Offsets from shim/decode_ufs_boot.py, which runs on import."""
    raw = dump[LINK_RECORD:LINK_RECORD + LINK_BYTES]
    if raw[:8] != b"UFSLNKR1":
        return {"current": False, "why": "no link record"}
    word = lambda off: struct.unpack_from("<I", raw, off)[0]
    if word(8) != 3 or word(252) != 0x314b4e4c or word(248) != zlib.crc32(raw[:248]):
        return {"current": False, "why": "version, commit or CRC"}
    nonce, epoch = struct.unpack_from("<QQ", raw, 16)
    if (nonce, epoch) != (int(ids["stamp_nonce"], 16), int(ids["epoch"], 16)):
        return {"current": False, "why": "another boot"}
    return {"current": True, "rc": struct.unpack_from("<i", raw, 40)[0], "up": raw[170]}


def _read(raw, ids):
    try:
        decoder = load("decode_read", ROOT / "research/ufs-read-r2/decode_read.py")
        rec = decoder.decode_record(raw, bytes.fromhex(ids["record_nonce"]), int(ids["epoch"], 16))
    except (ValueError, KeyError, OSError, struct.error, IndexError) as error:
        return {"why": str(error)[:60]}
    end = rec.get("end") or {}
    return {"rc": end.get("rc"), "phase": end.get("phase"), "blocks": end.get("read_blocks"),
            "sealed": rec.get("sealed")}


def abl_facts(attempt):
    text = read_text(attempt / "ramdump/abl.log.txt")
    facts = {}
    for key, pattern in ABL_FIELDS:
        match = re.search(pattern, text)
        if match:
            facts[key] = match.group(1) if key != "battery" else \
                f"{match.group(1)}% {match.group(2)} mV"
    return facts


def summarize(attempt):
    attempt = Path(attempt)
    dump_path = attempt / "ramdump/kernel.log"
    dump = dump_path.read_bytes()
    reader = load("read_ramdump", HERE / "read-ramdump.py")
    region = load("panic_region", HERE / "panic_region.py")
    doc = reader.analyze(dump, None, "boot-summary: no symbols", dump_path, DUMP_BASE,
                         reader.RAMOOPS_PA, 1 << 21, None, None, None, True, None)
    meta = read_text(attempt / "meta.txt")
    image = (re.search(r"^image: (.*)$", meta, re.M) or [None, None])[1]
    meta_mach = (re.search(r"^mach: (.*)$", meta, re.M) or [None, None])[1]
    ids = beside_image(image, "ufs-ids.json", "ids.json") if image else {}
    if "stamp" in ids:
        ids.setdefault("stamp_nonce", ids["stamp"])
    profile = beside_image(image, "profile.json") if image else {}
    stamps_text = read_text(attempt / "stamps-decode.txt")
    fresh = doc["freshness"]
    shim = fresh["shim_stamps"]
    entry = fresh["handoff_entry"]
    pmsg = dump[reader.PMSG_OFF:reader.PMSG_OFF + reader.PMSG_SIZE]
    prologue = (doc.get("xnu_msgbuf_mirror") or {}).get("entry_prologue") or {}
    mirror_doc, mirror_text = reader._parse_msgbuf_mirror(pmsg, tail_count=1 << 21)
    entry_fresh = bool(entry.get("fresh"))
    current, regions = region.select(dump, entry)
    want_nonce = int(ids["stamp_nonce"], 16) if ids.get("stamp_nonce") else None
    panic = {"current": bool(current), "regions": len(regions)}
    if current:
        panic.update(message=current["message"], caller=current["caller"],
                     uuid=current["kernel_uuid"],
                     seconds_after_entry=round((current["mach_absolute_time"] -
                                                entry["entry_cntvct"]) / region.CNTFRQ, 3))
    elif regions:
        panic.update(residue_message=regions[0]["message"], uuid=regions[0]["kernel_uuid"],
                     gap=region.boot_gap_seconds(regions[0], entry))
    meta_uuid = macho_uuid(meta_mach) if meta_mach else None
    kernel = {"decoded_with": meta_mach, "uuid": meta_uuid, "booted_uuid": panic.get("uuid") if current else None}
    if current and meta_uuid:
        kernel["match"] = meta_uuid == current["kernel_uuid"]
    elif profile.get("mach_sha256") and meta_mach:
        try:
            kernel["match"] = hashlib.sha256(Path(meta_mach).read_bytes()).hexdigest() == profile["mach_sha256"]
        except OSError:
            kernel["match"] = None
    ladder = doc.get("ladder") or {}
    return {
        "attempt": attempt.name, "image": image,
        "image_sha256": (re.search(r"^image_sha256: (\w+)", meta, re.M) or [None, None])[1],
        "verdict": doc["verdict"]["class"],
        "stage": doc["verdict"].get("stage_name"),
        "shim": {"nonce": shim.get("nonce"), "reason": shim.get("reason"),
                 "handoff": shim.get("handoff_proven"), "count": shim.get("count"),
                 "dropped": shim.get("dropped"), "valid": shim.get("valid"),
                 "last": (re.search(r"last stage: (.*)", stamps_text) or [None, None])[1]},
        "nonce": {"stamps": shim.get("nonce"), "image": want_nonce, "xnu": prologue.get("boot_nonce"),
                  "image_match": None if want_nonce is None else shim.get("nonce") == want_nonce,
                  "xnu_match": prologue.get("boot_nonce") == shim.get("nonce") if prologue.get("present") else None,
                  "entry_fresh": entry_fresh, "entry_status": entry.get("status")},
        "ufs": decode_ufs(dump, ids, stamps_text, read_text(attempt / "live.log"), mirror_text, entry_fresh),
        "panic": panic, "kernel": kernel,
        "milestone": {"last": ladder.get("last"), "next": ladder.get("next_expected"),
                      "wall": ladder.get("wall"),
                      "launchd_main": doc["milestones"].get("launchd_main")},
        "reset": abl_facts(attempt),
        "park_seconds": (re.search(r"boot_to_park_wall_s: (\d+)", read_text(attempt / "park-timeline.txt")) or [None, None])[1],
    }


def ufs_line(ufs):
    parts = []
    link = ufs["link"]
    if link:
        parts.append(f"link rc={link.get('rc')} up={link.get('up')}"
                     if link.get("current") else f"link record: {link.get('why')}")
    record = ufs["record"]
    if ufs["read"]:
        read = ufs["read"]
        parts.append(f"shim read {read.get('rc')} {read.get('blocks')} blocks" if "rc" in read
                     else f"shim read undecoded ({read.get('why')})")
    elif record:
        state = {True: "this boot", False: "residue", None: "unbound"}[record["current"]]
        parts.append(f"{record['kind']} record: {state}")
    if ufs["xnu"]:
        xnu = ufs["xnu"]
        parts.append(f"XNU {xnu['reads']} reads, {xnu['errors']} errors" if xnu["done"]
                     else f"XNU {xnu['reads']} reads, NOT finished")
    if not ufs["ladder"]:
        parts.append("no UFS stamp this boot")
    elif ufs["ladder"]["arg"] != "0x0" or not parts:
        parts.append(f"ladder {ufs['ladder']['flag']} {ufs['ladder']['arg']}, no decoded record")
    return "; ".join(parts)


def render(s):
    def yn(value):
        return {True: "yes", False: "NO", None: "unknown"}[value]

    def hx(value):
        return f"{value:#018x}" if isinstance(value, int) else "none"

    shim, nonce, panic, kernel, mile, reset = (s["shim"], s["nonce"], s["panic"], s["kernel"],
                                               s["milestone"], s["reset"])
    lines = [f"{s['attempt']}  image {(s['image_sha256'] or 'unknown')[:12]}",
             f"verdict   {s['verdict']}; stage {s['stage'] or 'none this boot'}"]
    full = " (ring full, stamps after this are lost; not a hang)" if shim["dropped"] else ""
    lines.append(f"shim      reason {shim['reason']} handoff {yn(shim['handoff'])} "
                 f"stamps {shim['count']} dropped {shim['dropped']}")
    lines.append(f"          last {shim['last']}{full}")
    lines.append(f"nonce     stamps {hx(nonce['stamps'])}; image {yn(nonce['image_match'])}; "
                 f"XNU {yn(nonce['xnu_match'])}")
    lines.append(f"          XNU entry this boot: {yn(nonce['entry_fresh'])} ({nonce['entry_status']})")
    lines.append(f"ufs       {ufs_line(s['ufs'])}")
    if panic["current"]:
        lines.append(f"panic     {panic['message']}")
        lines.append(f"          caller {panic['caller']:#x}, {panic['seconds_after_entry']} s after XNU entry")
    elif panic["regions"]:
        gap = panic.get("gap")
        why = (f"unbound, {gap:.1f} s from XNU entry" if nonce["entry_fresh"] and gap is not None
               else "residue from an earlier boot")
        lines.append(f"panic     none shown for this boot; region is {why}")
        lines.append(f"          region says: {panic['residue_message']}")
    else:
        lines.append("panic     none in the panic region")
    if kernel.get("match") is False:
        lines.append(f"kernel    WRONG symbols in this attempt: {Path(kernel['decoded_with']).name} is not the booted kernel")
    elif kernel.get("match"):
        lines.append(f"kernel    symbols match: {Path(kernel['decoded_with']).name}")
    else:
        lines.append("kernel    symbols unverified")
    if nonce["entry_fresh"]:
        lines.append(f"furthest  {mile['last']}; next {mile['next']}; wall {mile['wall']}")
    else:
        lines.append("furthest  shim only; XNU did not start this boot")
    lines.append("reset     " + " ".join(f"{k}={reset[k]}" for k in ("reason", "wdt_sub", "thermal", "pmic_main", "pmic_sub")
                                         if k in reset))
    lines.append(f"          {reset.get('rst_stat', 'RST_STAT unknown')}; SoC {reset.get('soc_temp', '?')}; "
                 f"battery {reset.get('battery', '?')}; park {s['park_seconds']} s")
    if reset.get("reason") == "0xbab9" and not panic["current"]:
        lines.append("note      0xbab9 reads \"Early Kernel PANIC\", but no panic is bound to this boot")
    return "\n".join(line[:WIDTH] for line in lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("attempt")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not (Path(args.attempt) / "ramdump/kernel.log").is_file():
        print(f"boot-summary: no ramdump/kernel.log in {args.attempt}", file=sys.stderr)
        return 2
    summary = summarize(args.attempt)
    print(json.dumps(summary, indent=1) if args.json else render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
