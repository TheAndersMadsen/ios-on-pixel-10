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
ROOT = next(p for p in HERE.parents if (p / "AGENTS.md").exists())
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
    return uuid_of(head)


def uuid_of(head):
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


def stamp_boots(slots):
    """Index of the first slot of each boot. Rebooting an image reuses its nonce:
    the shim appends to the same trail and cntvct restarts."""
    starts = [0] if slots else []
    for index in range(1, len(slots)):
        now, before = slots[index].get("cntvct"), slots[index - 1].get("cntvct")
        if now is not None and before is not None and now < before:
            starts.append(index)
    return starts


def refusal_text(live_text, stamps_text):
    """Why the shim stopped: its console line, or the first 8 bytes it stamped."""
    lines = re.findall(r"^(?:REFUSED|WHY)\s+(.+?)\s*$", live_text, re.M)
    if lines:
        return lines[-1]
    for arg in reversed(re.findall(r"REFUSED\s+0x([0-9a-f]{16})\b", stamps_text)):
        raw = bytes.fromhex(arg)[::-1]
        if all(0x20 <= byte < 0x7f for byte in raw):
            return raw.decode("ascii") + "..."
    return None


def not_entered_text(shim, entry, live_text, stamps_text):
    """Reason text for a boot with no proven XNU entry."""
    if shim.get("reused") and shim.get("reason") == 5:
        return "unproven: nonce reused, reader refuses the trail; rebuild the image for a new nonce"
    why = refusal_text(live_text, stamps_text)
    if why:
        return why
    if shim.get("present") is False:
        return "no shim stamps in this dump"
    if shim.get("reason") == 5:
        return f"shim handed off but no XNU entry record ({entry.get('status')})"
    return f"shim ended with reason {shim.get('reason_name') or shim.get('reason')}; no refusal text captured"


def root_io(text):
    """UFS root totals from the kernel's deadline panic, if it printed them."""
    match = re.search(r"(\d+) reads, (\d+) blocks, busy (\d+) ms", text or "")
    if not match:
        return None
    reads, blocks, busy = map(int, match.groups())
    if not blocks or not busy:
        return {"reads": reads, "blocks": blocks, "busy_ms": busy}
    return {"reads": reads, "blocks": blocks, "busy_ms": busy, "ms_per_block": round(busy / blocks, 2),
            "mib_per_s": round(blocks * 4096 / 1048576 / (busy / 1000), 2)}


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


# Order of a 12377 boot. The log prints EXECOK6 before EXECOK4, so rank by this list, not by position.
MILESTONES_12377 = (
    ("banner", r"^Darwin Kernel Version"),
    ("blazer-root start", r"^blazer-root: PAGE_SIZE"),
    ("BSD root", r"^BSD root: "),
    ("root mounted", r"stage mounted\b|^hfs: mounted "),
    ("UFS takeover", r"stage takeover\b"),
    ("varfs", r"stage varfs\b"),
    ("UFS test", r"^blazer-ufs-test: done"),
    ("load_init_program", r"^load_init_program: attempting"),
    ("exec launchd", r"^exec launchd"),
    ("EXECOK4", r"^EXECOK4:"),
    ("EXECOK6", r"^EXECOK6:"),
)
OPTIONAL_12377 = ("varfs", "UFS test")  # only images that ask for them
IS_12377 = re.compile(r"TEGU-XNU (?:STAGE0|EARLY \d+)|^blazer-root:", re.M)
STAGE_LINE = re.compile(r"^blazer-root: stage t (\d+) ms stage (\S+) reads (\d+) blocks (\d+) busy (\d+) ms", re.M)


def console_text(dump):
    """Text of the persistent_ram console zone: DBGC, start, size, then the bytes."""
    if dump[:4] != b"DBGC":
        return ""
    used = struct.unpack_from("<I", dump, 8)[0]
    return dump[12:12 + min(used, 0x200000 - 12)].decode("latin-1")


def console_matches(console, mirror):
    """The console has no nonce. It belongs to this boot only if it opens with the bound mirror's text."""
    head = mirror[:200]
    body = console.split("TEGU-XNU STAGE0\n", 1)[-1]
    return bool(head) and body.startswith(head)


def read_12377(mirror, console, wrapped, bound, why):
    """Milestones, UFS and panic of a 12377 boot from the mirror, which XNUENT1 binds to the
    shim's nonce. An unbound log is reported as such and nothing is read from it."""
    if not bound:
        return {"bound": False, "why": why}
    same = console_matches(console, mirror)
    # A wrapped mirror lost its start; only then is the console needed, and then it can't be compared.
    text = mirror + ("\n" + console if same or wrapped else "")
    early = [int(n) for n in re.findall(r"TEGU-XNU EARLY (\d+):", text)]
    reached = [name for name, pattern in MILESTONES_12377 if re.search(pattern, text, re.M)]
    stages = [dict(ms=int(m[0]), stage=m[1], reads=int(m[2]), blocks=int(m[3]), busy_ms=int(m[4]))
              for m in STAGE_LINE.findall(mirror)]
    done = re.search(r"^blazer-ufs-test: done, (\d+) errors", mirror, re.M)
    attach = re.search(r'^blazer-ufs: "([^"]+)" on LUN (\d+): first block (\w+), (\d+) MiB, read only', mirror, re.M)
    panic = re.search(r"^panic\(cpu (\d+) caller (0x[0-9a-f]+)\):\s*(.*)$", mirror, re.M)
    exited = re.search(r"^pid 1 exited -- (.*)$", mirror, re.M)
    return {"bound": True, "console_same": same, "wrapped": wrapped, "early_max": max(early) if early else None,
            "reached": reached, "furthest": reached[-1] if reached else (f"EARLY {max(early)}" if early else "XNU entry"),
            "missing": [name for name, _ in MILESTONES_12377 if name not in reached and name not in OPTIONAL_12377],
            "stages": stages,
            "ufs": {"attached": bool(attach), "partition": attach.group(1) if attach else None,
                    "lun": int(attach.group(2)) if attach else None,
                    "done": bool(done), "errors": int(done.group(1)) if done else None,
                    "dropped": "requested but no live" in mirror},
            "pid1_exit": exited.group(1) if exited else None,
            "panic": {"cpu": int(panic.group(1)), "caller": int(panic.group(2), 16), "message": panic.group(3)} if panic else None}


def payload_uuid(image):
    """LC_UUID of the kernel in the payload beside this image: what actually booted."""
    try:
        with open(Path(image).parent / "payload-usb.bin", "rb") as source:
            head = source.read(0x2a8 + 32)
            if head[:7] != b"TEGUXNU":
                return None
            source.seek(struct.unpack_from("<Q", head, 0x2a8 + 16)[0])
            macho = source.read(0x10000)
    except (OSError, struct.error):
        return None
    return uuid_of(macho)


def symbol_of(mach, address):
    """Nearest symbol through the reader's own Mach-O parser, or None."""
    try:
        return load("read_ramdump", HERE / "read-ramdump.py").ddp.MachSymCache(mach).lookup_code(address)
    except (OSError, ValueError, AttributeError):
        return None


def abl_facts(attempt):
    text = read_text(attempt / "ramdump/abl.log.txt")
    facts = {}
    for key, pattern in ABL_FIELDS:
        match = re.search(pattern, text)
        if match:
            facts[key] = match.group(1) if key != "battery" else \
                f"{match.group(1)}% {match.group(2)} mV"
    return facts


def _sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


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
    want_sha = (re.search(r"^image_sha256: (\w+)", meta, re.M) or [None, None])[1]
    # Files beside the image only describe the boot if the image is still the one booted.
    image_same = _sha256(image) == want_sha if image and want_sha else False
    ids = beside_image(image, "ufs-ids.json", "ids.json") if image_same else {}
    if "stamp" in ids:
        ids.setdefault("stamp_nonce", ids["stamp"])
    profile = beside_image(image, "profile.json") if image_same else {}
    if meta_mach and not Path(meta_mach).is_absolute():
        meta_mach = str(ROOT / meta_mach)
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
    slots = shim.get("slots") or []
    starts = stamp_boots(slots)
    live_text = read_text(attempt / "live.log")
    last_rows = re.findall(r"^\s+\d+\s+\d+\s+(\S+(?:\([^)]*\))?)\s+([A-Z|-]+)\s+0x", stamps_text, re.M)
    shim_view = dict(shim, reused=len(starts) > 1,
                     reason_name=(re.search(r"reason=(\S+)", stamps_text) or [None, None])[1])
    not_entered = None if entry_fresh else not_entered_text(shim_view, entry, live_text, stamps_text)
    ladder = doc.get("ladder") or {}
    console = console_text(dump)
    x = None
    if IS_12377.search(mirror_text or "") or IS_12377.search(console):
        bound = bool(entry_fresh and prologue.get("present") and prologue.get("entry_valid") and mirror_text and
                     prologue.get("boot_nonce") == shim.get("nonce"))
        x = read_12377(mirror_text or "", console, (mirror_doc.get("stream_total") or 0) > (mirror_doc.get("size") or 0),
                       bound, "no XNU entry record with the shim's nonce")
        booted = payload_uuid(image) if image_same else None
        kernel.update(booted_uuid=booted, match=None if not (booted and meta_uuid) else booted == meta_uuid)
        if x.get("panic") and meta_mach and kernel["match"]:
            x["panic"]["symbol"] = symbol_of(meta_mach, x["panic"]["caller"])
    return {
        "attempt": attempt.name, "image": image,
        "image_sha256": (re.search(r"^image_sha256: (\w+)", meta, re.M) or [None, None])[1],
        "verdict": doc["verdict"]["class"],
        "stage": doc["verdict"].get("stage_name"),
        "shim": {"nonce": shim.get("nonce"), "reason": shim.get("reason"),
                 "handoff": shim.get("handoff_proven"), "count": shim.get("count"),
                 "dropped": shim.get("dropped"), "valid": shim.get("valid"),
                 "boots": len(starts),
                 "boot_stamps": len(slots) - starts[-1] if starts else 0,
                 "last": f"{last_rows[-1][0]} [{last_rows[-1][1]}]" if last_rows else None},
        "not_entered": not_entered, "image_same": image_same,
        "nonce": {"stamps": shim.get("nonce"), "image": want_nonce, "xnu": prologue.get("boot_nonce"),
                  "image_match": None if want_nonce is None else shim.get("nonce") == want_nonce,
                  "xnu_match": prologue.get("boot_nonce") == shim.get("nonce") if prologue.get("present") else None,
                  "entry_fresh": entry_fresh, "entry_status": entry.get("status")},
        "ufs": decode_ufs(dump, ids, stamps_text, live_text, mirror_text, entry_fresh),
        "root_io": root_io(current["message"]) if current else None,
        "xnu12377": x,
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


def render_12377(x, lines):
    """Replaces the panic-region and old-ladder rows: this kernel writes no panic region."""
    if not x["bound"]:
        lines.append(f"12377     log not bound to this boot: {x['why']}; nothing read from it")
        return
    panic = x["panic"]
    if panic:
        lines.append(f"panic     {panic['message'][:WIDTH - 10]}")
        where = f" {panic['symbol']}" if panic.get("symbol") else ""
        lines.append(f"          caller {panic['caller']:#x}{where}, from the mirror")
    else:
        lines.append("panic     none in this boot's mirror")
    if x["pid1_exit"]:
        lines.append(f"pid 1     {x['pid1_exit']}")
    lines.append(f"early     EARLY up to {x['early_max']}; console {'same text as mirror' if x['console_same'] else 'not compared equal'}"
                 + ("; mirror wrapped" if x["wrapped"] else ""))
    if x["stages"]:
        last = x["stages"][-1]
        names = " ".join(row["stage"] for row in x["stages"])
        lines.append(f"root      {names}; at {last['ms']} ms: {last['reads']} reads, {last['blocks']} blocks, busy {last['busy_ms']} ms")
    ufs = x["ufs"]
    if ufs["dropped"]:
        lines.append("ufs test  shim dropped the UFS tokens: no live handoff")
    elif ufs["attached"] or ufs["done"]:
        result = f"{ufs['errors']} errors" if ufs["done"] else "NOT finished"
        lines.append(f"ufs test  {ufs['partition']} LUN {ufs['lun']}: {result}")
    lines.append(f"furthest  {x['furthest']}" + (f"; not seen: {', '.join(x['missing'])}" if x["missing"] else ""))


def render(s):
    def yn(value):
        return {True: "yes", False: "NO", None: "unknown"}[value]

    def hx(value):
        return f"{value:#018x}" if isinstance(value, int) else "none"

    shim, nonce, panic, kernel, mile, reset = (s["shim"], s["nonce"], s["panic"], s["kernel"],
                                               s["milestone"], s["reset"])
    lines = [f"{s['attempt']}  image {(s['image_sha256'] or 'unknown')[:12]}"]
    if s["not_entered"]:
        lines.append(f"XNU not entered: {s['not_entered']}")
    else:
        lines.append(f"verdict   {s['verdict']}; stage {s['stage'] or 'none this boot'}")
    full = " (ring full, stamps after this are lost; not a hang)" if shim["dropped"] else ""
    lines.append(f"shim      reason {shim['reason']} handoff {yn(shim['handoff'])} "
                 f"stamps {shim['count']} dropped {shim['dropped']}")
    if shim["boots"] > 1:
        lines.append(f"          NONCE REUSED: {shim['boots']} boots in this trail, newest has "
                     f"{shim['boot_stamps']} stamps")
    lines.append(f"          last {shim['last']}{full}")
    lines.append(f"nonce     stamps {hx(nonce['stamps'])}; image {yn(nonce['image_match'])}; "
                 f"XNU {yn(nonce['xnu_match'])}")
    lines.append(f"          XNU entry this boot: {yn(nonce['entry_fresh'])} ({nonce['entry_status']})")
    if not s["image_same"]:
        lines.append("          image rebuilt or gone since this boot; its nonce and UFS ids are not used")
    lines.append(f"ufs       {ufs_line(s['ufs'])}")
    io = s["root_io"]
    if io and "ms_per_block" in io:
        lines.append(f"          root {io['reads']} reads, {io['blocks']} blocks, busy {io['busy_ms']} ms: "
                     f"{io['ms_per_block']} ms/block, {io['mib_per_s']} MiB/s")
    x = s.get("xnu12377")
    if x:
        pass
    elif panic["current"]:
        message = panic["message"]
        lines.append(f"panic     {message[:WIDTH - 10]}")
        if len(message) > WIDTH - 10:
            lines.append(f"          {message[WIDTH - 10:WIDTH * 2 - 20].strip()}")
        lines.append(f"          caller {panic['caller']:#x}, {panic['seconds_after_entry']} s after XNU entry")
    elif panic["regions"]:
        gap = panic.get("gap")
        if nonce["entry_fresh"] and gap is not None:
            lines.append(f"panic     none shown for this boot; region is unbound, {gap:.1f} s from XNU entry")
            lines.append(f"          region says: {panic['residue_message']}")
        else:
            lines.append("panic     none this boot; the panic region is residue from an earlier boot")
    else:
        lines.append("panic     none in the panic region")
    if kernel.get("match") is False:
        lines.append(f"kernel    WRONG symbols in this attempt: {Path(kernel['decoded_with']).name} is not the booted kernel")
    elif kernel.get("match"):
        lines.append(f"kernel    symbols match: {Path(kernel['decoded_with']).name}")
    else:
        lines.append("kernel    symbols unverified")
    if x:
        render_12377(x, lines)
    elif nonce["entry_fresh"]:
        lines.append(f"furthest  {mile['last']}; next {mile['next']}; wall {mile['wall']}")
    else:
        lines.append("furthest  shim only" if not (shim["boots"] > 1 and shim["reason"] == 5)
                     else "furthest  unknown: reader refuses a reused nonce")
    lines.append("reset     " + " ".join(f"{k}={reset[k]}" for k in ("reason", "wdt_sub", "thermal", "pmic_main", "pmic_sub")
                                         if k in reset))
    lines.append(f"          {reset.get('rst_stat', 'RST_STAT unknown')}; SoC {reset.get('soc_temp', '?')}; "
                 f"battery {reset.get('battery', '?')}; park {s['park_seconds']} s")
    if reset.get("reason") == "0xbab9" and not panic["current"] and not (x and x.get("panic")):
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
