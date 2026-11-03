#!/usr/bin/env python3
"""Evaluate docs/probes.yaml over boot attempts: one evidence-based verdict per README row.

  python3 -I tools/probe_eval.py <attempt dir or log file>...           per-row verdicts
  python3 -I tools/probe_eval.py --propose-status <attempts>...          compare with docs/status.json
  python3 -I tools/probe_eval.py --propose-status --apply <attempts>...  write the promotions
  python3 -I tools/probe_eval.py --queue [<attempts>...]                 cheapest next test per row
  python3 -I tools/probe_eval.py --json [--qemu] [--row ID]... <attempts>...  machine-readable

Importable (tools/hk_cycle.py, tools/qemu_preflight.py):
  probe_eval = importlib.util ... load tools/probe_eval.py
  rows = probe_eval.evaluate(["<attempt dir>", ...], rows=["wifi", "Battery gauge"])
  -> one dict per probe: id, row, phone_only, milestone, verdict, attempt, evidence
     [{label, passed, count, cites}], pending_confirm, fails, exercised_in, note, next.
  qemu=True drops phone_only probes. Cites are "path:line: text".

Host only, read only (except --apply, which rewrites docs/status.json, and
--text-dir, which writes the decoded XNU mirror text so evidence lines are
clickable). An attempt is a fastboot attempt directory (ramdump/kernel.log,
reader.txt, live.log, boot.log ...), a live directory (console.txt) or a plain
log file. XNU mirror text counts only when the attempt's reader.txt says
current-fresh=yes (tools/read-ramdump.py freshness gate); otherwise it is listed
as unverified and ignored unless --trust-unverified.

Promotions only: --propose-status never proposes a demotion. A status the
attempts do not reproduce is reported as "unsupported here" (it may rest on
older boots or owner reports). Exit 0 on success, 2 on bad input.
"""
import argparse
import fnmatch
import json
import re
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROBES = ROOT / "docs" / "probes.yaml"
STATUS = ROOT / "docs" / "status.json"
CONFIRMATIONS = ROOT / "docs" / "owner_confirmations.txt"

RANK = {"open": 0, "active": 1, "built": 2, "partial": 3, "works": 4}
LEVELS = ("works", "partial", "built", "active")
ICON = {"works": "✅", "partial": "🟡", "built": "🔧", "active": "⏳", "open": "❌", "out": "🚫"}
NEXT_KIND = {"unattended": 0, "build": 1, "attended": 2, "none": 3}

# XNU-MSGBUF mirror geometry (same ABI as tools/read-ramdump.py).
PMSG_OFF = 0x200000
MIRROR_HDR2_OFF = 0x3F800
MIRROR_RING_OFF = 0x40000
MIRROR_V1_OFF = 0x40000
MIRROR_MAGIC_V2 = b"XNU-MSGBUF v2"
MIRROR_MAGIC_V1 = b"XNU-MSGBUF v1"
MIRROR_HEADER = struct.Struct("<16sIIQQIIQII")
MIRROR_RING_MAX = 0x100000

TEXT_SOURCES = (  # (relative path, kind)
    ("reader.txt", "reader"), ("live.log", "live"), ("console.txt", "console"),
    ("markers.txt", "console"), ("boot.log", "fastboot"), ("capture.log", "fastboot"),
    ("park-timeline.txt", "reader"), ("stamps-decode.txt", "reader"),
    ("ramdump/abl.log.txt", "abl"),
)
DEFAULT_KINDS = ("msgbuf", "live", "console", "fastboot")  # reader.txt repeats the mirror tail: opt in with src
BOOT_ARGS_RX = re.compile(r"boot-args = (.*)$")


# ---------------------------------------------------------------- YAML subset

class YamlError(ValueError):
    pass


def _strip_comment(line):
    out, quote, i = [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                if quote == "'" and line[i + 1:i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _scalar(tok):
    tok = tok.strip()
    if tok == "" or tok in ("null", "~"):
        return None
    if tok in ("true", "false"):
        return tok == "true"
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    if re.fullmatch(r"-?\d+\.\d+", tok):
        return float(tok)
    return tok


class _Flow:
    """Flow collections: [a, 'b', {k: v}] and {k: v, k2: [..]}."""

    def __init__(self, text):
        self.s, self.i = text, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self, stops):
        self.ws()
        ch = self.s[self.i] if self.i < len(self.s) else ""
        if ch == "[":
            return self.seq()
        if ch == "{":
            return self.map()
        if ch in "'\"":
            return self.quoted()
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in stops:
            self.i += 1
        return _scalar(self.s[start:self.i])

    def quoted(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch == q:
                if q == "'" and self.s[self.i + 1:self.i + 2] == "'":
                    out.append("'")
                    self.i += 2
                    continue
                self.i += 1
                return "".join(out)
            if q == '"' and ch == "\\":
                nxt = self.s[self.i + 1:self.i + 2]
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, "\\" + nxt))
                self.i += 2
                continue
            out.append(ch)
            self.i += 1
        raise YamlError(f"unterminated quote in {self.s!r}")

    def seq(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.s[self.i:self.i + 1] == "]":
                self.i += 1
                return out
            out.append(self.value(",]"))
            self.ws()
            if self.s[self.i:self.i + 1] == ",":
                self.i += 1
            elif self.s[self.i:self.i + 1] != "]":
                raise YamlError(f"bad flow sequence: {self.s!r}")

    def map(self):
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.s[self.i:self.i + 1] == "}":
                self.i += 1
                return out
            key = self.value(":")
            if self.s[self.i:self.i + 1] != ":":
                raise YamlError(f"bad flow mapping: {self.s!r}")
            self.i += 1
            out[key] = self.value(",}")
            self.ws()
            if self.s[self.i:self.i + 1] == ",":
                self.i += 1
            elif self.s[self.i:self.i + 1] != "}":
                raise YamlError(f"bad flow mapping: {self.s!r}")


def _inline(text):
    text = text.strip()
    if not text:
        return None
    if text[0] in "[{'\"":
        f = _Flow(text)
        v = f.value("")
        f.ws()
        if f.i != len(text):
            raise YamlError(f"trailing text after value: {text!r}")
        return v
    return _scalar(text)


def _split_key(text):
    """'key: value' -> (key, value) or None. Keys are plain or quoted."""
    if text[:1] in "'\"":
        f = _Flow(text)
        key = f.quoted()
        rest = text[f.i:]
        if not rest.startswith(":"):
            return None
        return key, rest[1:]
    m = re.match(r"([^\s'\"\[\]{},:][^:]*?):(\s|$)(.*)", text)
    if not m:
        return None
    return m.group(1), m.group(3)


def yaml_subset_load(text):
    """Block mappings and sequences with flow collections and quoted scalars.

    Enough for docs/probes.yaml (no anchors, tags, multi-line scalars or documents).
    """
    lines = []
    for raw in text.splitlines():
        if raw.strip() in ("---",):
            continue
        body = _strip_comment(raw)
        if body.strip():
            if "\t" in body[:len(body) - len(body.lstrip())]:
                raise YamlError("tabs in indentation")
            lines.append((len(body) - len(body.lstrip(" ")), body.strip()))
    pos = 0

    def block(indent):
        nonlocal pos
        if pos >= len(lines):
            return None
        if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
            return seq(lines[pos][0])
        return mapping(lines[pos][0])

    def mapping(indent):
        nonlocal pos
        out = {}
        while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
            kv = _split_key(lines[pos][1])
            if kv is None:
                raise YamlError(f"expected 'key: value': {lines[pos][1]!r}")
            key, rest = kv
            pos += 1
            if rest.strip():
                out[key] = _inline(rest)
            elif pos < len(lines) and (lines[pos][0] > indent or
                                       (lines[pos][0] == indent and lines[pos][1].startswith("- "))):
                out[key] = block(lines[pos][0])
            else:
                out[key] = None
        if pos < len(lines) and lines[pos][0] > indent:
            raise YamlError(f"bad indentation: {lines[pos][1]!r}")
        return out

    def seq(indent):
        nonlocal pos
        out = []
        while pos < len(lines) and lines[pos][0] == indent and (lines[pos][1].startswith("- ") or lines[pos][1] == "-"):
            item = lines[pos][1][1:].strip()
            if not item:
                pos += 1
                out.append(block(lines[pos][0]) if pos < len(lines) and lines[pos][0] > indent else None)
                continue
            kv = _split_key(item) if item[:1] not in "[{" else None
            if kv is None:
                out.append(_inline(item))
                pos += 1
                continue
            # "- key: value" opens a mapping whose further keys sit at indent + 2.
            child = indent + 2 + (len(lines[pos][1]) - len(lines[pos][1][1:].lstrip()) - 2)
            lines[pos] = (child, item)
            out.append(mapping(child))
        return out

    doc = block(0)
    if pos != len(lines):
        raise YamlError(f"unparsed line: {lines[pos][1]!r}")
    return doc


def load_probes(path=PROBES):
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # optional; the subset loader is the reference for CI
        doc = yaml.safe_load(text)
    except ImportError:
        doc = yaml_subset_load(text)
    validate_probes(doc)
    return doc


def validate_probes(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("probes"), list):
        raise ValueError("probes.yaml: top-level 'probes' list missing")
    seen = set()
    for p in doc["probes"]:
        for key in ("id", "row"):
            if not p.get(key):
                raise ValueError(f"probe without {key}: {p}")
        if not isinstance(p.get("phone_only"), bool):
            raise ValueError(f"{p['id']}: phone_only must be true or false")
        if not isinstance(p.get("milestone", False), bool):
            raise ValueError(f"{p['id']}: milestone must be true or false")
        if p["id"] in seen:
            raise ValueError(f"duplicate probe id {p['id']}")
        seen.add(p["id"])
        for level in LEVELS:
            spec = p.get(level)
            if spec is None:
                continue
            checks = (spec.get("all") or []) + (spec.get("any") or [])
            if not checks:
                raise ValueError(f"{p['id']}.{level}: no checks")
            if spec.get("confirm") not in (None, "owner", "screenshot", "owner_or_screenshot"):
                raise ValueError(f"{p['id']}.{level}: bad confirm {spec.get('confirm')!r}")
            for c in checks:
                _compile_check(c, f"{p['id']}.{level}")
        for c in p.get("fails") or []:
            _compile_check(c, f"{p['id']}.fails")
        nxt = p.get("next") or {}
        if nxt and nxt.get("kind") not in NEXT_KIND:
            raise ValueError(f"{p['id']}.next: bad kind {nxt.get('kind')!r}")


def _compile_check(c, where):
    if not isinstance(c, dict) or not ("re" in c or "seq" in c):
        raise ValueError(f"{where}: check needs re or seq: {c!r}")
    try:
        if "re" in c:
            c["_rx"] = re.compile(c["re"])
        else:
            c["_rx_seq"] = [re.compile(r) for r in c["seq"]]
    except re.error as error:
        raise ValueError(f"{where}: bad regex: {error}") from error
    group = c.get("group")
    if group and group not in c["_rx"].groupindex:
        raise ValueError(f"{where}: group {group!r} not in {c['re']!r}")


# ---------------------------------------------------------------- sources

def decode_mirror(dump):
    """XNU-MSGBUF mirror text from a 4 MiB ramoops dump, or (None, reason)."""
    pmsg = dump[PMSG_OFF:PMSG_OFF + 0x200000]
    for hdr_off, ring_off, magic in ((MIRROR_HDR2_OFF, MIRROR_RING_OFF, MIRROR_MAGIC_V2),
                                     (MIRROR_V1_OFF, MIRROR_V1_OFF + MIRROR_HEADER.size, MIRROR_MAGIC_V1)):
        if len(pmsg) < hdr_off + MIRROR_HEADER.size:
            continue
        (m, seq, _flags, _p, _c, size, write, total, tail_off, tail_len) = \
            MIRROR_HEADER.unpack_from(pmsg, hdr_off)
        if m != magic.ljust(16, b"\0"):
            continue
        if not seq or not 0 < size <= MIRROR_RING_MAX or tail_len > size or total < tail_len \
                or tail_off >= size or write % size != total % size \
                or (tail_len and tail_off != (total - tail_len) % size):
            return None, f"{magic.decode()} header invalid"
        ring = pmsg[ring_off:ring_off + size]
        if len(ring) < size:
            return None, "ring truncated"
        if tail_off + tail_len <= size:
            linear = ring[tail_off:tail_off + tail_len]
        else:
            linear = ring[tail_off:] + ring[:tail_len - (size - tail_off)]
        return linear.replace(b"\0", b"").decode("utf-8", "replace"), None
    return None, "no mirror header"


class Source:
    def __init__(self, kind, cite, lines, fresh=True, note=""):
        self.kind, self.cite, self.lines, self.fresh, self.note = kind, cite, lines, fresh, note


class Attempt:
    def __init__(self, name, path):
        self.name, self.path = name, path
        self.sources, self.screens, self.confirm_lines, self.notes = [], [], [], []
        self.boot_args = None

    def text_sources(self, kinds, trust_unverified=False):
        return [s for s in self.sources if s.kind in kinds and (s.fresh or trust_unverified)]


def _reader_fresh(path):
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    m = re.search(r"XNU-MSGBUF mirror: .*current-fresh=(yes|no)", text)
    return None if not m else m.group(1) == "yes"


def _kind_for_file(path):
    name = path.name
    for rel, kind in TEXT_SOURCES:
        if name == Path(rel).name:
            return kind
    if name == "kernel.log":
        return "msgbuf"
    return "console"


def _lines(text):
    """Split on newlines only, so cited line numbers match grep -n and editors
    (str.splitlines also breaks on \\r, \\x0b, \\x1c.. and U+2028 found in log noise)."""
    lines = text.split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def load_attempt(path, text_dir=None):
    path = Path(path)
    if path.is_dir():
        att = Attempt(path.name, path)
        base = path
        files = [(base / rel, kind) for rel, kind in TEXT_SOURCES if (base / rel).is_file()]
        kernel = base / "ramdump" / "kernel.log"
        reader = base / "reader.txt"
        att.screens = sorted(base.glob("screen*.png"))
        confirm = base / "confirm.txt"
        if confirm.is_file():
            att.confirm_lines = [(f"{confirm}:{i}", l) for i, l in enumerate(confirm.read_text().splitlines(), 1)]
    else:
        att = Attempt(path.parent.name if path.parent.name not in ("", "ramdump") else path.stem, path)
        if path.parent.name == "ramdump":
            att.name = path.parent.parent.name
        kind = _kind_for_file(path)
        files = [] if kind == "msgbuf" else [(path, kind)]
        kernel = path if kind == "msgbuf" else None
        reader = (path.parent.parent if path.parent.name == "ramdump" else path.parent) / "reader.txt"
    for f, kind in files:
        lines = _lines(f.read_text(encoding="utf-8", errors="replace"))
        att.sources.append(Source(kind, str(f), lines))
    if kernel is not None and kernel.is_file():
        text, why = decode_mirror(kernel.read_bytes())
        fresh = _reader_fresh(reader) if reader.is_file() else None
        if text is None:
            att.notes.append(f"msgbuf: {why}")
        else:
            cite = f"{kernel}#msgbuf"
            if text_dir:
                out = Path(text_dir) / f"{att.name}.msgbuf.txt"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                cite = str(out)
            note = {True: "current-fresh=yes", False: "reader: current-fresh=no (stale, ignored)",
                    None: "freshness unverified: no reader.txt verdict (ignored)"}[fresh]
            att.sources.append(Source("msgbuf", cite, _lines(text), fresh=bool(fresh), note=note))
            if not fresh:
                att.notes.append(f"msgbuf: {note}")
    for s in att.sources:
        if not s.fresh:
            continue
        for line in s.lines:
            m = BOOT_ARGS_RX.search(line)
            if m:
                att.boot_args = m.group(1)
                break
        if att.boot_args:
            break
    return att


# ---------------------------------------------------------------- checks

def _num(value):
    try:
        return float(int(value, 0)) if isinstance(value, str) and value.lower().startswith("0x") else float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(v):
    return str(int(v)) if v is not None and float(v).is_integer() else str(v)


def run_check(check, attempt, trust=False, max_cites=3):
    kinds = tuple(check.get("src") or DEFAULT_KINDS)
    sources = attempt.text_sources(kinds, trust)
    result = {"label": check.get("label") or check.get("re") or " -> ".join(check["seq"]),
              "passed": False, "count": 0, "cites": [], "ctx": {}}
    if "seq" in check:
        for s in sources:
            idx, cites = 0, []
            for n, line in enumerate(s.lines, 1):
                if check["_rx_seq"][idx].search(line):
                    cites.append(f"{s.cite}:{n}: {line.strip()[:160]}")
                    idx += 1
                    if idx == len(check["_rx_seq"]):
                        result.update(passed=True, count=1, cites=cites[:max(max_cites, len(cites))])
                        return result
        return result
    rx, group = check["_rx"], check.get("group")
    values, last = [], {}
    for s in sources:
        for n, line in enumerate(s.lines, 1):
            m = rx.search(line)
            if not m:
                continue
            result["count"] += 1
            last = {k: v for k, v in m.groupdict().items() if v is not None}
            if group and m.group(group) is not None:
                v = _num(m.group(group))
                if v is not None:
                    values.append((v, f"{s.cite}:{n}: {line.strip()[:160]}"))
            if len(result["cites"]) < max_cites:
                result["cites"].append(f"{s.cite}:{n}: {line.strip()[:160]}")
    lo, hi = check.get("min", 1), check.get("max")
    ok = result["count"] >= lo and (hi is None or result["count"] <= hi)
    ctx = dict(last)
    if group and values:
        nums = [v for v, _ in values]
        best_hi = max(values, key=lambda x: x[0])
        best_lo = min(values, key=lambda x: x[0])
        if "ge" in check:
            ok = ok and best_hi[0] >= check["ge"]
            ctx[group] = _fmt_num(best_hi[0])
            result["cites"] = [best_hi[1]] + [c for c in result["cites"] if c != best_hi[1]][:max_cites - 1]
        if "le" in check:
            ok = ok and best_lo[0] <= check["le"]
            ctx[group] = _fmt_num(best_lo[0])
            result["cites"] = [best_lo[1]] + [c for c in result["cites"] if c != best_lo[1]][:max_cites - 1]
        if "distinct_min" in check:
            distinct = sorted(set(nums))
            ok = ok and len(distinct) >= check["distinct_min"]
            ctx[group] = "/".join(_fmt_num(v) for v in distinct[:8])
        if "span_min" in check:
            ok = ok and (best_hi[0] - best_lo[0]) >= check["span_min"]
            ctx[group] = f"{_fmt_num(best_lo[0])}–{_fmt_num(best_hi[0])}"
            result["cites"] = [best_lo[1], best_hi[1]] + result["cites"][:max(0, max_cites - 2)]
    elif group and any(k in check for k in ("ge", "le", "distinct_min", "span_min")):
        ok = False
    result["passed"] = ok
    result["ctx"] = ctx
    return result


# ---------------------------------------------------------------- confirmations

def load_confirmations(paths):
    """Lines: <attempt glob> <probe id> <level> <owner|screenshot>: <text>."""
    out = []
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            parsed = parse_confirmation(line)
            if parsed:
                parsed["cite"] = f"{p}:{n}"
                out.append(parsed)
    return out


def parse_confirmation(line):
    line = line.split(" #", 1)[0].strip() if not line.lstrip().startswith("#") else ""
    m = re.match(r"(\S+)\s+(\S+)\s+(works|partial|built|active)\s+(owner|screenshot):\s*(.*)$", line)
    if not m:
        return None
    return {"attempt": m.group(1), "probe": m.group(2), "level": m.group(3),
            "kind": m.group(4), "text": m.group(5)}


def _confirmed(confirms, attempt, probe_id, level, need):
    kinds = {"owner": {"owner"}, "screenshot": {"screenshot"},
             "owner_or_screenshot": {"owner", "screenshot"}}[need]
    for c in confirms:
        if c["probe"] == probe_id and c["level"] == level and c["kind"] in kinds \
                and fnmatch.fnmatch(attempt.name, c["attempt"]):
            return c
    return None


# ---------------------------------------------------------------- screenshots

def png_mean_luma(path):
    """Mean luma (0..255) of an 8-bit RGB/RGBA/grey non-interlaced PNG, stdlib only."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, ihdr = 8, [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
        pos += 12 + length
    width, height, depth, ctype, _c, _f, interlace = ihdr
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or channels is None or interlace:
        raise ValueError("unsupported PNG format")
    raw = zlib.decompress(b"".join(idat))
    stride = width * channels
    prev = bytearray(stride)
    total, i = 0, 0
    for _ in range(height):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = prev[x]
            c = prev[x - channels] if x >= channels else 0
            if ftype == 1:
                line[x] = (line[x] + a) & 0xFF
            elif ftype == 2:
                line[x] = (line[x] + b) & 0xFF
            elif ftype == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        prev = line
        if channels >= 3:
            total += sum((299 * line[x] + 587 * line[x + 1] + 114 * line[x + 2]) // 1000
                         for x in range(0, stride, channels))
        else:
            total += sum(line[x] for x in range(0, stride, channels))
    return total / (width * height)


def screenshot_check(spec, attempt):
    out = []
    for png in attempt.screens:
        if not fnmatch.fnmatch(png.name, spec.get("file", "screen*.png")):
            continue
        try:
            luma = png_mean_luma(png)
        except (ValueError, zlib.error, struct.error, TypeError) as error:
            out.append({"file": str(png), "error": str(error)})
            continue
        nonblack = luma > spec.get("threshold", 8)
        out.append({"file": str(png), "mean_luma": round(luma, 1), "nonblack": nonblack,
                    "content": spec.get("expect", ""), "content_checked": False})
    return out


# ---------------------------------------------------------------- evaluation

def _level_passes(spec, attempt, trust, max_cites):
    alls = [run_check(c, attempt, trust, max_cites) for c in spec.get("all") or []]
    anys = [run_check(c, attempt, trust, max_cites) for c in spec.get("any") or []]
    ok = all(r["passed"] for r in alls) and (not anys or any(r["passed"] for r in anys))
    ctx = {}
    for r in alls + anys:
        if r["passed"]:
            ctx.update(r["ctx"])
    return ok, alls + [r for r in anys if r["passed"]] + ([] if ok else [r for r in anys if not r["passed"]]), ctx


def exercised(probe, attempt, trust=False):
    needs = probe.get("needs") or {}
    markers = needs.get("markers") or []
    if not markers:
        return None, "no markers"
    kinds = DEFAULT_KINDS + ("abl",)
    for rx in markers:
        r = re.compile(rx)
        for s in attempt.text_sources(kinds, trust):
            if s.kind == "abl":
                continue
            for n, line in enumerate(s.lines, 1):
                if r.search(line):
                    ba = needs.get("boot_args") or []
                    if attempt.boot_args is not None:
                        missing = [b for b in ba if not re.search(b, attempt.boot_args)]
                        if missing:
                            return False, f"boot-args lack {', '.join(missing)}"
                    return True, f"{s.cite}:{n}"
    return False, "markers absent"


def evaluate_probe(probe, attempt, confirms, trust=False, max_cites=3):
    doc = {"attempt": attempt.name, "verdict": None, "pending_confirm": None, "evidence": [],
           "fails": [], "screens": [], "ctx": {"attempt": attempt.name}, "confirmation": None}
    ex, why = exercised(probe, attempt, trust)
    doc["exercised"], doc["exercised_why"] = ex, why
    if not ex:
        return doc
    for level in LEVELS:
        spec = probe.get(level)
        if not spec:
            continue
        ok, results, ctx = _level_passes(spec, attempt, trust, max_cites)
        if not ok:
            continue
        need = spec.get("confirm")
        conf = _confirmed(confirms, attempt, probe["id"], level, need) if need else None
        if need and not conf:
            if doc["pending_confirm"] is None:
                doc["pending_confirm"] = level
                doc["pending_evidence"] = results
                doc["pending_ctx"] = ctx
            continue
        doc.update(verdict=level, evidence=results, confirmation=conf, note_template=spec.get("note"))
        doc["ctx"].update(ctx)
        break
    for c in probe.get("fails") or []:
        r = run_check(c, attempt, trust, max_cites)
        if r["count"] >= c.get("min", 1):
            doc["fails"].append(r)
    if probe.get("screenshot"):
        doc["screens"] = screenshot_check(probe["screenshot"], attempt)
    return doc


def aggregate(probe, per_attempt):
    """Best verdict across attempts (latest attempt wins a tie); blockers from the latest exercised run."""
    best = None
    for d in per_attempt:
        if d["verdict"] and (best is None or RANK[d["verdict"]] >= RANK[best["verdict"]]):
            best = d
    pending = None
    for d in per_attempt:
        if d["pending_confirm"] and (pending is None or RANK[d["pending_confirm"]] >= RANK[pending["pending_confirm"]]):
            pending = d
    ran = [d for d in per_attempt if d["exercised"]]
    latest = ran[-1] if ran else None
    fails, seen = [], set()
    for d in [x for x in (best, latest) if x]:
        for f in d["fails"]:
            if (f["label"], d["attempt"]) not in seen:
                seen.add((f["label"], d["attempt"]))
                fails.append({**f, "attempt": d["attempt"]})
    return {
        "id": probe["id"], "row": probe["row"],
        "phone_only": probe["phone_only"], "milestone": bool(probe.get("milestone")),
        "has_levels": any(probe.get(l) for l in LEVELS),
        "verdict": best["verdict"] if best else None,
        "attempt": best["attempt"] if best else None,
        "evidence": best["evidence"] if best else [],
        "confirmation": best["confirmation"] if best else None,
        "note": _note(best) if best else None,
        "pending_confirm": pending["pending_confirm"] if pending and (
            not best or RANK[pending["pending_confirm"]] > RANK[best["verdict"]]) else None,
        "pending_attempt": pending["attempt"] if pending else None,
        "pending_evidence": pending.get("pending_evidence", []) if pending else [],
        "exercised_in": [d["attempt"] for d in ran],
        "fails": fails,
        "screens": [s for d in per_attempt for s in d["screens"]],
        "owner": probe.get("owner"),
        "next": probe.get("next") or {},
    }


def _note(doc):
    tmpl = doc.get("note_template")
    if not tmpl:
        return None

    class Missing(dict):
        def __missing__(self, key):
            return "?"
    return tmpl.format_map(Missing(doc["ctx"]))


def select_probes(probes_doc, rows=None, qemu=False):
    """Probes by id or row name (None = all), without phone_only ones when qemu."""
    want = set(rows) if rows else None
    out = [p for p in probes_doc["probes"]
           if (want is None or p["id"] in want or p["row"] in want) and not (qemu and p["phone_only"])]
    if want:
        unknown = want - {p["id"] for p in probes_doc["probes"]} - {p["row"] for p in probes_doc["probes"]}
        if unknown:
            raise ValueError(f"unknown probe(s): {', '.join(sorted(unknown))}")
    return out


def evaluate_attempts(probes, attempts, confirms, trust=False, max_cites=3):
    rows = []
    for probe in probes:
        per = [evaluate_probe(probe, a, confirms, trust, max_cites) for a in attempts]
        rows.append(aggregate(probe, per))
    return rows


def load_attempts(paths, text_dir=None):
    paths = [Path(p) for p in paths]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing: {', '.join(missing)}")
    return sorted((load_attempt(p, text_dir) for p in paths), key=lambda a: a.name.removeprefix("live-"))


def gather_confirmations(attempts, confirm_files=None):
    confirms = load_confirmations([str(CONFIRMATIONS)] if confirm_files is None else confirm_files)
    for a in attempts:
        for cite, line in a.confirm_lines:
            parsed = parse_confirmation(line)
            if parsed:
                parsed.update(cite=cite, attempt=a.name)
                confirms.append(parsed)
    return confirms


def evaluate(paths, rows=None, *, qemu=False, probes=PROBES, confirm_files=None,
             trust_unverified=False, cites=3, text_dir=None):
    """Per-probe verdict dicts (JSON-ready) for attempt directories or log files.

    rows: probe ids or status.json row names to keep (None = all).
    qemu: drop phone_only probes (QEMU consoles cannot exercise them).
    """
    doc = load_probes(probes)
    selected = select_probes(doc, rows, qemu)
    attempts = load_attempts(paths, text_dir)
    confirms = gather_confirmations(attempts, confirm_files)
    return _jsonable(evaluate_attempts(selected, attempts, confirms, trust_unverified, cites))


# ---------------------------------------------------------------- status

def status_rows(status):
    return {f[0]: {"block": b["name"], "status": f[1], "note": f[2]}
            for b in status["blocks"] for f in b["features"]}


def compare(rows, status):
    current = status_rows(status)
    out = []
    for r in rows:
        if r.get("milestone"):
            continue
        cur = current.get(r["row"])
        if cur is None:
            out.append({**_cmp_base(r, None), "kind": "unknown-row"})
            continue
        s, v = cur["status"], r["verdict"]
        base = _cmp_base(r, cur)
        if s == "out":
            kind = "out"
        elif not r["has_levels"]:
            kind = "no-log-probe"
        elif not r["exercised_in"]:
            kind = "not-exercised"
        elif v is None and r["pending_confirm"] is None:
            kind = "unsupported-here" if RANK[s] >= RANK["active"] else "agree"
        elif v is not None and RANK[v] > RANK[s]:
            kind = "promote"
        elif r["pending_confirm"] and RANK[r["pending_confirm"]] > RANK[s] and (v is None or RANK[v] <= RANK[s]):
            kind = "needs-confirmation"
        elif v is not None and RANK[v] == RANK[s]:
            kind = "agree"
        elif r["pending_confirm"] and RANK[r["pending_confirm"]] >= RANK[s]:
            kind = "log-short-of-confirmed"
        else:
            kind = "unsupported-here"
        out.append({**base, "kind": kind})
    return out


def _cmp_base(r, cur):
    return {"row": r["row"], "id": r["id"], "current": cur["status"] if cur else None,
            "current_note": cur["note"] if cur else None, "log": r["verdict"],
            "pending_confirm": r["pending_confirm"], "attempt": r["attempt"],
            "proposed_note": r["note"]}


def apply_status(status, comparisons):
    changed = []
    for b in status["blocks"]:
        for f in b["features"]:
            for c in comparisons:
                if c["kind"] == "promote" and c["row"] == f[0]:
                    old = list(f)
                    f[1] = c["log"]
                    if c["proposed_note"]:
                        f[2] = c["proposed_note"]
                    changed.append((old, list(f)))
    return changed


# ---------------------------------------------------------------- queue

def queue(rows, status):
    current = status_rows(status)
    scores = status.get("scores", {})
    out = []
    for r in rows:
        if r.get("milestone"):
            continue
        cur = current.get(r["row"], {}).get("status")
        nxt = r["next"]
        kind = nxt.get("kind", "none")
        if cur is None or cur == "out":
            continue
        higher = [l for l in ("active", "built", "partial", "works") if RANK[l] > RANK[cur]]
        target = higher[0] if higher else None
        gain = (scores.get(target) or 0) - (scores.get(cur) or 0) if target else 0
        minutes = nxt.get("minutes") or 0
        out.append({"row": r["row"], "id": r["id"], "current": cur, "target": target,
                    "gain": gain, "kind": kind, "minutes": minutes, "test": nxt.get("test", ""),
                    "per_min": gain / max(minutes, 1)})
    out.sort(key=lambda q: (q["kind"] == "none" or q["gain"] == 0, NEXT_KIND.get(q["kind"], 9),
                            -q["per_min"], q["minutes"], q["row"]))
    return out


# ---------------------------------------------------------------- output

def _icon(level):
    return ICON.get(level, "·") if level else "·"


def print_rows(rows, comparisons=None, evidence=True, out=sys.stdout):
    cmp = {c["row"]: c for c in comparisons or []}
    for r in rows:
        c = cmp.get(r["row"])
        cur = f" (status {_icon(c['current'])} {c['current']}; {c['kind']})" if c else ""
        v = r["verdict"]
        line = f"{_icon(v)} {r['row']}: {v or 'no log verdict'}"
        if r["attempt"]:
            line += f" [{r['attempt']}]"
        if r["pending_confirm"]:
            line += f"; log reaches {r['pending_confirm']} pending confirmation [{r['pending_attempt']}]"
        if not r["has_levels"]:
            line = f"· {r['row']}: no log probe"
        elif not r["exercised_in"]:
            line = f"· {r['row']}: not exercised by these attempts"
        print(line + cur, file=out)
        if not evidence:
            continue
        for e in r["evidence"]:
            for cite in e["cites"][:2]:
                print(f"    + {e['label']}: {cite}", file=out)
        if r["confirmation"]:
            print(f"    + confirmed ({r['confirmation']['kind']}): {r['confirmation']['cite']}: {r['confirmation']['text']}", file=out)
        if r["pending_confirm"]:
            for e in r["pending_evidence"]:
                if e["passed"]:
                    for cite in e["cites"][:1]:
                        print(f"    ? {e['label']}: {cite}", file=out)
        for f in r["fails"]:
            for cite in f["cites"][:1]:
                print(f"    - blocker {f['label']} (x{f['count']}, {f['attempt']}): {cite}", file=out)
        for s in r["screens"][:2]:
            if "error" in s:
                print(f"    ~ screenshot {s['file']}: {s['error']}", file=out)
            else:
                print(f"    ~ screenshot {s['file']}: mean luma {s['mean_luma']} "
                      f"({'not black' if s['nonblack'] else 'black'}); content unchecked: {s['content']}", file=out)
        if r["note"]:
            print(f"    note: {r['note']}", file=out)


def print_comparisons(comparisons, out=sys.stdout):
    order = ("promote", "needs-confirmation", "log-short-of-confirmed", "unsupported-here",
             "not-exercised", "agree", "no-log-probe", "out", "unknown-row")
    for kind in order:
        items = [c for c in comparisons if c["kind"] == kind]
        if not items:
            continue
        print(f"\n== {kind} ({len(items)})", file=out)
        for c in items:
            log = c["log"] or "-"
            extra = f", pending {c['pending_confirm']}" if c["pending_confirm"] else ""
            print(f"  {c['row']}: status {c['current']} / log {log}{extra}"
                  + (f" [{c['attempt']}]" if c["attempt"] else ""), file=out)
            if kind == "promote":
                print(f"      proposed: {c['current']} -> {c['log']}; note: {c['proposed_note'] or c['current_note']}", file=out)


def print_queue(items, out=sys.stdout):
    print("\n== next tests (cheapest first; unattended before build before attended)", file=out)
    for i, q in enumerate(items, 1):
        if q["kind"] == "none" or q["gain"] == 0:
            tag = "done/none"
        else:
            tag = f"{q['kind']}, ~{q['minutes']} min, +{q['gain']} pts -> {q['target']}"
        print(f"  {i:2}. {q['row']} ({q['current']}) [{tag}]: {q['test']}", file=out)


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("attempts", nargs="*", help="attempt directories, live directories or log files")
    ap.add_argument("--probes", default=str(PROBES))
    ap.add_argument("--status", default=str(STATUS))
    ap.add_argument("--confirm", action="append", default=None,
                    help=f"confirmation file(s); default {CONFIRMATIONS.relative_to(ROOT)} (attempt confirm.txt always read)")
    ap.add_argument("--propose-status", action="store_true", help="compare with status.json and propose promotions")
    ap.add_argument("--apply", action="store_true", help="with --propose-status: write the promotions to --status")
    ap.add_argument("--queue", action="store_true", help="print the cheapest next test per row")
    ap.add_argument("--text-dir", help="write decoded XNU mirror text here and cite it (clickable evidence)")
    ap.add_argument("--trust-unverified", action="store_true", help="count mirror text without a fresh reader verdict")
    ap.add_argument("--cites", type=int, default=3, help="evidence lines kept per check")
    ap.add_argument("--brief", action="store_true", help="verdict lines only")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--qemu", action="store_true", help="skip phone_only probes (QEMU consoles)")
    ap.add_argument("--row", action="append", help="probe id or row name to evaluate (repeatable)")
    args = ap.parse_args(argv)
    if args.apply and not args.propose_status:
        ap.error("--apply needs --propose-status")
    try:
        probes_doc = load_probes(args.probes)
        selected = select_probes(probes_doc, args.row, args.qemu)
        attempts = load_attempts(args.attempts, args.text_dir)
    except (OSError, ValueError) as error:
        print(f"probe_eval: {error}", file=sys.stderr)
        return 2
    confirms = gather_confirmations(attempts, args.confirm)
    rows = evaluate_attempts(selected, attempts, confirms, args.trust_unverified, args.cites)
    status = None
    if args.propose_status or args.queue or not args.json:
        try:
            status = json.loads(Path(args.status).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            if args.propose_status or args.queue:
                print(f"probe_eval: {args.status}: {error}", file=sys.stderr)
                return 2
    comparisons = compare(rows, status) if status else None
    queued = queue(rows, status) if args.queue and status else None
    changed = apply_status(status, comparisons) if args.apply else []
    if args.apply and changed:
        Path(args.status).write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        doc = {"attempts": [{"name": a.name, "path": str(a.path), "boot_args": a.boot_args,
                             "sources": [{"kind": s.kind, "cite": s.cite, "lines": len(s.lines),
                                          "fresh": s.fresh, "note": s.note} for s in a.sources],
                             "notes": a.notes} for a in attempts],
               "rows": rows}
        if args.propose_status:
            doc["comparisons"] = comparisons
            doc["applied"] = [{"row": n[0], "from": o[1], "to": n[1], "note": n[2]} for o, n in changed]
        if queued is not None:
            doc["queue"] = queued
        print(json.dumps(_jsonable(doc), indent=2, ensure_ascii=False))
        return 0
    if attempts:
        print(f"{len(attempts)} attempt(s):")
        for a in attempts:
            kinds = ", ".join(f"{s.kind}{'' if s.fresh else '(ignored)'}" for s in a.sources) or "no readable logs"
            print(f"  {a.name}: {kinds}" + (f"; {'; '.join(a.notes)}" if a.notes else ""))
        print()
        print_rows(rows, comparisons, evidence=not args.brief)
    if args.propose_status:
        print_comparisons(comparisons)
        if args.apply:
            print(f"\napplied {len(changed)} change(s) to {args.status}; rebuild with python3 -I tools/readme_status.py")
        else:
            print("\n(proposal only; nothing written. --apply writes the promotions)")
    if queued is not None:
        print_queue(queued)
    return 0


if __name__ == "__main__":
    sys.exit(main())
