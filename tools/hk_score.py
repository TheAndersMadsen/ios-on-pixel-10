#!/usr/bin/env python3
"""Hardware scoreboard for one phone boot: a ladder per subsystem, from hardware to user-visible.

  python3 -I tools/hk_score.py <attempt dir | live dir>            one boot (the other half is paired automatically)
  python3 -I tools/hk_score.py --latest                            newest boot in research/laguna-usb-fix/attempts
  python3 -I tools/hk_score.py BOOT --md | --json                  markdown report / machine-readable
  python3 -I tools/hk_score.py BOOT --diff OTHER                   per-subsystem rung changes OTHER -> BOOT
  python3 -I tools/hk_score.py BOOT --baseline OTHER|score.json    exit 1 if any subsystem regressed vs the baseline
  python3 -I tools/hk_score.py --best [--since 20261104] [BOOT..]  best-known rung per subsystem across boots (+ top actions)
  python3 -I tools/hk_score.py --validate [--since 20261104]       where each rung of docs/scoreboard.yaml matches

A boot is a fastboot attempt directory (ramdump/kernel.log, reader.txt, live.log, boot.log) and/or the live
directory (live-<time>-<name>/console.txt, markers.txt) of the same boot. Given either, the other is found in the
same parent: the live markers' ATTEMPT_DIR name, else the same run name within 20 minutes.

Rungs live in docs/scoreboard.yaml (same check syntax as docs/probes.yaml; tools/probe_eval.py loads the sources,
decodes the XNU-MSGBUF mirror and runs the checks). A reached rung implies the rungs below it unless it is marked
independent: the ramdump keeps only the last 1 MiB of the ring, so early lines of a long boot are gone.
Per subsystem: LEVEL = rungs satisfied from the bottom, BEST = highest rung with its own evidence (the cited line,
<= 160 chars, with its time: live console wall/kernel time, or the ramdump's last status tick 't>=Ns'), the first
missing rung and the next action from the scoreboard's rules table (with its source).

Host only, read only. Exit 0, 1 on a regression versus --baseline, 2 on bad input.
"""
import argparse
import bisect
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BOARD = ROOT / "docs" / "scoreboard.yaml"
ATTEMPTS = ROOT / "research" / "laguna-usb-fix" / "attempts"
PAIR_WINDOW_S = 20 * 60
RUN_NAME = re.compile(r"^(?:live-)?(\d{8})-(\d{6})-(.+)$")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pe = _load("probe_eval", HERE / "probe_eval.py")
hklog = _load("hklog", HERE / "hklog.py")

# Planned ends: the kernel deadline, the host reset op (usbcon 0x5c, docs/DEBUG-LOOP.md) and a GPU rung's PASS stop.
UNPLANNED_PANIC = re.compile(r"panic\(cpu \d+ caller 0x[0-9a-f]+\): (?!blazer-root: deadline|blazer-usbcon: the host asked to end this boot|HK GPUTA: rung \d+ PASS)")
METRIC_KINDS = ("msgbuf", "console", "live")
METRICS = ("unplanned_panics", "uptime_s", "respawn_max", "crashes", "usertraps", "codesign")
UPTIME_RX = [(re.compile(r"HKOBS \d+ \S+ t=(\d+) "), 1.0), (re.compile(r"blazer-root: watch t (\d+) ms"), 0.001),
             (re.compile(r"blazer-root: deadline (\d+) s, stage"), 1.0),
             (re.compile(r"^\d\d:\d\d:\d\d\.\d+ \[\s*(\d+)\.\d+\] "), 1.0)]
CRASH_RX = re.compile(r"CRASH (\S+) reason")
USERTRAP_RX = re.compile(r"usertrap: ([^\[\s]+)\[")
CODESIGN_RX = re.compile(r"CODE SIGNING: \d+\[([^\]]+)\]")
PROC_RX = re.compile(r"HKOBS \d+ \S+ t=\d+ proc: (.*?)(?:HKOBS|$)")
CONSOLE_TIME = re.compile(r"^(\d\d:\d\d:\d\d)\.\d+ (?:\[\s*([\d.]+)\] )?")
MARKER_TIME = re.compile(r"^[A-Z]+ (\d\d:\d\d:\d\d)\.\d+ \+([\d.]+) ")
CITE = re.compile(r"^(.*?):(\d+): (.*)$")


# ---------------------------------------------------------------- scoreboard

def load_board(path=BOARD):
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml
        doc = yaml.safe_load(text)
    except ImportError:
        doc = pe.yaml_subset_load(text)
    validate_board(doc)
    return doc


def _checks(spec):
    out = []
    for c in (spec.get("all") or []) + (spec.get("any") or []):
        if isinstance(c, dict) and "all" in c and "re" not in c and "metric" not in c:
            out.extend(c["all"])
        else:
            out.append(c)
    return out


def validate_board(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("subsystems"), list):
        raise ValueError("scoreboard: top-level 'subsystems' list missing")
    seen = set()
    for sub in doc["subsystems"]:
        if not sub.get("id") or sub["id"] in seen:
            raise ValueError(f"scoreboard: missing or duplicate subsystem id {sub.get('id')!r}")
        seen.add(sub["id"])
        rids = set()
        if not sub.get("rungs"):
            raise ValueError(f"{sub['id']}: no rungs")
        for r in sub["rungs"]:
            where = f"{sub['id']}.{r.get('id')}"
            if not r.get("id") or r["id"] in rids:
                raise ValueError(f"{where}: missing or duplicate rung id")
            rids.add(r["id"])
            if not r.get("label") or not r.get("next"):
                raise ValueError(f"{where}: label and next are required")
            if bool(r.get("sample")) == bool(r.get("unverified")):
                raise ValueError(f"{where}: exactly one of sample / unverified is required")
            checks = _checks(r)
            if not checks:
                raise ValueError(f"{where}: no checks")
            for c in checks:
                if "metric" in c:
                    if c["metric"] not in METRICS or not ("le" in c or "ge" in c):
                        raise ValueError(f"{where}: bad metric check {c!r}")
                else:
                    pe._compile_check(c, where)
                    _prefilter(c)
        for c in sub.get("fails") or []:
            pe._compile_check(c, f"{sub['id']}.fails")
            _prefilter(c)


def _prefilter(c):
    """Multiline twin of a check's regex: one C-speed search over a whole source skips sources without a match
    (a per-line match always matches the joined text too)."""
    if "re" in c:
        c["_mrx"] = re.compile(c["re"], re.M)


# ---------------------------------------------------------------- boots

def _run_time(name):
    m = RUN_NAME.match(name)
    if not m:
        return None, name
    d, t, rest = m.groups()
    secs = int(t[:2]) * 3600 + int(t[2:4]) * 60 + int(t[4:])
    return (int(d), secs), rest


def _attempt_dir_of_live(live):
    markers = live / "markers.txt"
    if markers.is_file():
        for line in markers.read_text(errors="replace").splitlines():
            m = re.search(r" ATTEMPT_DIR (\S+)", line)
            if m:
                return Path(m.group(1)).name
    return None


def _near(name, candidates, live_first):
    when, rest = _run_time(name)
    best = None
    for c in candidates:
        cw, crest = _run_time(c.name)
        if when is None or cw is None or crest != rest or cw[0] != when[0]:
            continue
        delta = (cw[1] - when[1]) if live_first else (when[1] - cw[1])
        if 0 <= delta <= PAIR_WINDOW_S and (best is None or delta < best[0]):
            best = (delta, c)
    return best[1] if best else None


def pair(path):
    """(attempt dir or None, live dir or None) for one boot given either half."""
    p = Path(path)
    if not p.is_dir():
        return None, None
    parent = p.parent
    if p.name.startswith("live-"):
        named = _attempt_dir_of_live(p)
        if named and (parent / named).is_dir():
            return parent / named, p
        others = [d for d in parent.iterdir() if d.is_dir() and not d.name.startswith("live-")]
        return _near(p.name, others, live_first=True), p
    lives = [d for d in parent.iterdir() if d.is_dir() and d.name.startswith("live-")]
    for d in lives:
        if _attempt_dir_of_live(d) == p.name:
            return p, d
    return p, _near(p.name, lives, live_first=False)


class Boot:
    def __init__(self, attempt_dir=None, live_dir=None, files=()):
        self.parts = [str(x) for x in (attempt_dir, live_dir) if x] + [str(f) for f in files]
        base = attempt_dir or live_dir or (Path(files[0]) if files else None)
        name = Path(base).name if base else "?"
        self.name = name[5:] if name.startswith("live-") else name
        if attempt_dir is None and live_dir is not None:
            self.name = Path(live_dir).name
        self.att = pe.Attempt(self.name, base)
        for part in [x for x in (attempt_dir, live_dir) if x] + list(files):
            a = pe.load_attempt(part)
            self.att.sources.extend(a.sources)
            self.att.notes.extend(a.notes)
            self.att.boot_args = self.att.boot_args or a.boot_args
        self._joined = {}
        self._anchors = {}
        self.by_cite = {s.cite: s for s in self.att.sources}
        kinds = {s.kind for s in self.att.sources if s.fresh}
        self.coverage = "+".join(k for k in ("console", "msgbuf", "live", "reader") if k in kinds) or "none"
        self.metrics, self.metric_detail = compute_metrics(self)
        msg = [s for s in self.att.sources if s.kind == "msgbuf" and s.fresh]
        if "console" not in kinds and msg and not any("Darwin Kernel Version" in l for s in msg for l in s.lines):
            self.att.notes.append("ramdump ring tail only (no live console; early boot lines lost): "
                                  "lower rungs show as implied or missing")

    def joined(self, s):
        j = self._joined.get(id(s))
        if j is None:
            j = self._joined[id(s)] = "\n".join(s.lines)
        return j

    def stamp(self, cite_line):
        m = CITE.match(cite_line)
        if not m:
            return "", cite_line
        cite, n, text = m.group(1), int(m.group(2)), m.group(3)
        s = self.by_cite.get(cite)
        raw = s.lines[n - 1] if s and 0 < n <= len(s.lines) else text
        mm = MARKER_TIME.match(raw)
        if mm:
            return f"{mm.group(1)} +{float(mm.group(2)):.0f}s", text
        mc = CONSOLE_TIME.match(raw)
        if mc:
            k = f"k={float(mc.group(2)):.0f}s " if mc.group(2) else ""
            return f"{k}@{mc.group(1)}", CONSOLE_TIME.sub("", text, count=1)[:160]
        if s is not None and s.kind == "msgbuf":
            anchors = self._anchors.get(cite)
            if anchors is None:
                anchors = []
                for i, line in enumerate(s.lines, 1):
                    for rx, scale in hklog.ANCHORS:
                        a = rx.search(line)
                        if a:
                            anchors.append((i, int(a.group(1)) * scale))
                            break
                self._anchors[cite] = anchors
            k = bisect.bisect_right([a[0] for a in anchors], n) - 1
            if k >= 0:
                return f"t>={anchors[k][1]:.0f}s", text
            return (f"t<={anchors[0][1]:.0f}s" if anchors else "ramdump"), text
        return (s.kind if s else ""), text


def compute_metrics(boot):
    srcs = boot.att.text_sources(METRIC_KINDS)
    panics, uptime, crashes, traps, codesign, procs = 0, 0.0, {}, {}, {}, {}
    for s in srcs:
        n_panic, c_crash, c_trap, c_cs = 0, {}, {}, {}
        for line in s.lines:
            if "panic(" in line and UNPLANNED_PANIC.search(line):
                n_panic += 1
            for rx, scale in UPTIME_RX:
                m = rx.search(line)
                if m:
                    uptime = max(uptime, int(m.group(1)) * scale)
            for rx, acc in ((CRASH_RX, c_crash), (USERTRAP_RX, c_trap), (CODESIGN_RX, c_cs)):
                m = rx.search(line)
                if m:
                    acc[m.group(1)] = acc.get(m.group(1), 0) + 1
            if "proc: " in line:
                m = PROC_RX.search(line)
                if m:
                    for name, (execs, *_rest) in hklog.parse_proc(m.group(1)).items():
                        procs[name] = max(procs.get(name, 0), execs)
        panics = max(panics, n_panic)
        for tot, acc in ((crashes, c_crash), (traps, c_trap), (codesign, c_cs)):   # same boot in two sources: max
            for k, v in acc.items():
                tot[k] = max(tot.get(k, 0), v)
    metrics = {"unplanned_panics": panics, "uptime_s": round(uptime), "respawn_max": max(procs.values(), default=0),
               "crashes": sum(crashes.values()), "usertraps": sum(traps.values()), "codesign": sum(codesign.values())}
    top = lambda d: dict(sorted(d.items(), key=lambda kv: -kv[1])[:6])
    detail = {"respawns": top({k: v for k, v in procs.items() if v > 3}), "crashes": top(crashes),
              "usertraps": top(traps), "codesign": top(codesign)}
    return metrics, detail


# ---------------------------------------------------------------- evaluation

def run_check(check, boot):
    if "metric" in check:
        v = boot.metrics.get(check["metric"], 0)
        ok = (("le" not in check or v <= check["le"]) and ("ge" not in check or v >= check["ge"]))
        return {"passed": ok, "count": 1, "cites": [f"metric {check['metric']}={v}"], "metric": True}
    kinds = tuple(check.get("src") or pe.DEFAULT_KINDS)
    mrx = check.get("_mrx")
    if mrx is not None and "seq" not in check:
        if not any(mrx.search(boot.joined(s)) for s in boot.att.text_sources(kinds)):
            lo, hi = check.get("min", 1), check.get("max")
            numeric = check.get("group") and any(k in check for k in ("ge", "le", "distinct_min", "span_min", "sustain"))
            return {"passed": 0 >= lo and (hi is None or hi >= 0) and not numeric, "count": 0, "cites": []}
    return pe.run_check(check, boot.att, max_cites=1)


def eval_spec(spec, boot):
    """(passed, evidence cite or None, label of the alternative that passed)."""
    cites = []
    for c in spec.get("all") or []:
        r = run_check(c, boot)
        if not r["passed"]:
            return False, None, None
        cites.extend(r["cites"][:1])
    anys = spec.get("any") or []
    if anys:
        for alt in anys:
            if isinstance(alt, dict) and "all" in alt and "re" not in alt and "metric" not in alt:
                ok, cite, _ = eval_spec({"all": alt["all"]}, boot)
                if ok:
                    return True, cite or (cites[0] if cites else None), alt.get("label")
                continue
            r = run_check(alt, boot)
            if r["passed"]:
                return True, (r["cites"][:1] or cites[:1] or [None])[0], alt.get("label")
        return False, None, None
    real = [c for c in cites if not c.startswith("metric ")]
    return True, (real or cites or [None])[0], None


def score_subsystem(sub, boot):
    rungs = sub["rungs"]
    direct = [None] * len(rungs)
    for i, r in enumerate(rungs):
        if not r.get("gated"):
            direct[i] = eval_spec(r, boot)
    state = _states(rungs, direct)
    for i, r in enumerate(rungs):                       # gated rungs, bottom-up: need the rung below satisfied
        if r.get("gated"):
            ok = i > 0 and state[i - 1] in ("reached", "implied")
            direct[i] = eval_spec(r, boot) if ok else (False, None, None)
            state = _states(rungs, direct)
    out = []
    for i, r in enumerate(rungs):
        ok, cite, alt = direct[i] if direct[i] else (False, None, None)
        when, text = boot.stamp(cite) if cite else ("", None)
        out.append({"id": r["id"], "label": r["label"], "state": state[i], "time": when, "evidence": text,
                    "via": alt, "unverified": bool(r.get("unverified")), "independent": bool(r.get("independent"))})
    fails = []
    for c in sub.get("fails") or []:
        res = run_check(c, boot)
        if res["passed"] and res["count"]:
            when, text = boot.stamp(res["cites"][0]) if res["cites"] else ("", "")
            ctx = ", ".join(f"{k}={v}" for k, v in (res.get("ctx") or {}).items() if v)
            fails.append({"label": c.get("label") or c["re"], "count": res["count"], "time": when,
                          "evidence": text, "ctx": ctx})
    reached = [i for i, x in enumerate(out) if x["state"] == "reached"]
    best = max(reached) if reached else None
    level = next((i for i, x in enumerate(out) if x["state"] == "missing"), len(out))
    fm = rungs[level] if level < len(rungs) else None
    exercised = bool(reached) or bool(fails) or bool(sub.get("always"))
    return {"id": sub["id"], "title": sub.get("title", sub["id"]), "exercised": exercised, "level": level,
            "total": len(rungs), "best": best, "best_id": rungs[best]["id"] if best is not None else None,
            "best_label": rungs[best]["label"] if best is not None else None,
            "best_time": out[best]["time"] if best is not None else "",
            "best_evidence": out[best]["evidence"] if best is not None else None,
            "first_missing": fm["id"] if fm else None, "first_missing_label": fm["label"] if fm else None,
            "next": fm["next"] if fm else "complete", "next_src": fm.get("src", "unknown") if fm else "",
            "action": (fm.get("action") or f"{sub['id']}:{fm['id']}") if fm else None,
            "rungs": out, "fails": fails}


def _states(rungs, direct):
    n = len(rungs)
    state = ["reached" if direct[i] and direct[i][0] else "missing" for i in range(n)]
    top_chain = max((i for i in range(n) if state[i] == "reached" and not rungs[i].get("independent")), default=-1)
    for i in range(top_chain):
        if state[i] == "missing" and not rungs[i].get("gated"):
            state[i] = "implied"
    return state


def score_boot(boot, board):
    return {"boot": boot.name, "parts": boot.parts, "coverage": boot.coverage, "notes": boot.att.notes,
            "boot_args": boot.att.boot_args, "metrics": boot.metrics, "metric_detail": boot.metric_detail,
            "subsystems": [score_subsystem(sub, boot) for sub in board["subsystems"]]}


def boot_from_path(path):
    p = Path(path)
    if p.is_file():
        return Boot(files=[p])
    att, live = pair(p)
    if att is None and live is None:
        raise ValueError(f"not a boot directory: {path}")
    return Boot(att, live)


def list_boots(root=ATTEMPTS, since=None, until=None):
    """Every boot under root (attempt dirs with their paired live dirs, plus unpaired live dirs), oldest first."""
    root = Path(root)
    dirs = sorted(d for d in root.iterdir() if d.is_dir() and RUN_NAME.match(d.name))
    if since:
        dirs = [d for d in dirs if RUN_NAME.match(d.name).group(1) >= since]
    if until:
        dirs = [d for d in dirs if RUN_NAME.match(d.name).group(1) <= until]
    boots, used = [], set()
    for d in dirs:
        if d.name.startswith("live-"):
            continue
        att, live = pair(d)
        if live is not None:
            used.add(live.name)
        boots.append((att, live))
    for d in dirs:
        if d.name.startswith("live-") and d.name not in used:
            boots.append((None, d))
    key = lambda b: _run_time((b[0] or b[1]).name)[0] or (0, 0)
    return sorted(boots, key=key)


def latest(root=ATTEMPTS):
    boots = list_boots(root)
    if not boots:
        raise ValueError(f"no boots under {root}")
    return Boot(*boots[-1])


# ---------------------------------------------------------------- diff / baseline

def diff(new, old):
    """Per subsystem: (id, old, new, verdict), verdict progress|regression|same|n/a|lost. 'lost': the baseline
    exercised it, this boot printed nothing for it (gate off, or the boot died first; subsystems marked always:
    true in the scoreboard are always exercised, so a dead boot is a regression there)."""
    olds = {s["id"]: s for s in old["subsystems"]}
    rows = []
    for s in new["subsystems"]:
        o = olds.get(s["id"])
        if o is None:
            rows.append((s["id"], None, s, "new"))
            continue
        if not s["exercised"] or not o["exercised"]:
            verdict = "lost" if (o["exercised"] and not s["exercised"]) else ("n/a" if not s["exercised"] else "progress")
        else:
            ob, nb = (o["best"] if o["best"] is not None else -1), (s["best"] if s["best"] is not None else -1)
            if s["level"] < o["level"] or nb < ob:
                verdict = "regression"
            elif s["level"] > o["level"] or nb > ob:
                verdict = "progress"
            else:
                verdict = "same"
        rows.append((s["id"], o, s, verdict))
    return rows


def load_score(path, board):
    p = Path(path)
    if p.is_file() and p.suffix == ".json":
        return json.loads(p.read_text())
    return score_boot(boot_from_path(p), board)


# ---------------------------------------------------------------- aggregate (--best)

def aggregate(scores, board):
    """Best-known state per rung across boots: reached (first boot that proved it) > implied > missing."""
    subs = []
    for i, sub in enumerate(board["subsystems"]):
        rungs = []
        for j, r in enumerate(sub["rungs"]):
            proof = next(((sc["boot"], sc["subsystems"][i]["rungs"][j]) for sc in scores
                          if sc["subsystems"][i]["rungs"][j]["state"] == "reached"), None)
            implied = any(sc["subsystems"][i]["rungs"][j]["state"] == "implied" for sc in scores)
            state = "reached" if proof else ("implied" if implied else "missing")
            rungs.append({"id": r["id"], "label": r["label"], "state": state, "boot": proof[0] if proof else None,
                          "time": proof[1]["time"] if proof else "", "evidence": proof[1]["evidence"] if proof else None,
                          "unverified": bool(r.get("unverified")), "rule": r})
        reached = [k for k, x in enumerate(rungs) if x["state"] == "reached"]
        best = max(reached) if reached else None
        level = next((k for k, x in enumerate(rungs) if x["state"] == "missing"), len(rungs))
        subs.append({"id": sub["id"], "title": sub.get("title", sub["id"]), "rungs": rungs, "best": best,
                     "level": level, "total": len(rungs)})
    return subs


def top_actions(subs, n=10):
    """Rank actions by the rungs they unblock: the first missing rung of each subsystem gates every missing rung
    above it; one action shared by several subsystems (same 'action' id) sums them."""
    acts = {}
    for s in subs:
        if s["level"] >= s["total"]:
            continue
        r = s["rungs"][s["level"]]["rule"]
        key = r.get("action") or f"{s['id']}:{r['id']}"
        unblocks = sum(1 for x in s["rungs"][s["level"]:] if x["state"] == "missing")
        a = acts.setdefault(key, {"action": key, "unblocks": 0, "subsystems": [], "next": r["next"],
                                  "src": r.get("src", "unknown")})
        a["unblocks"] += unblocks
        a["subsystems"].append(f"{s['id']}.{r['id']}")
    return sorted(acts.values(), key=lambda a: (-a["unblocks"], a["action"]))[:n]


# ---------------------------------------------------------------- output

def _rung_name(s, idx):
    return f"{s['rungs'][idx]['id']}" if idx is not None and idx < len(s["rungs"]) else "-"


def print_table(score, out=None, verbose=True):
    out = out or sys.stdout
    m = score["metrics"]
    out.write(f"hk_score {score['boot']}  [{score['coverage']}]  up {m['uptime_s']} s, panics {m['unplanned_panics']}, "
              f"crashes {m['crashes']}, usertraps {m['usertraps']}, codesign {m['codesign']}, "
              f"max execs {m['respawn_max']}\n")
    for note in score["notes"]:
        out.write(f"  note: {note}\n")
    out.write(f"{'SUBSYSTEM':<10} {'LVL':>5}  {'BEST RUNG':<22} {'FIRST MISSING':<20} NEXT\n")
    for s in score["subsystems"]:
        lvl = f"{s['level']}/{s['total']}" if s["exercised"] else "--"
        best = s["best_id"] or "-"
        fm = s["first_missing"] or "(complete)"
        mark = "?" if s["first_missing"] and s["rungs"][s["level"]]["unverified"] else ""
        out.write(f"{s['id']:<10} {lvl:>5}  {best:<22} {fm + mark:<20} {s['next'][:90]}\n")
        if verbose and s["best_evidence"]:
            via = s["rungs"][s["best"]]["via"]
            out.write(f"{'':<10}        proof [{s['best_time'] or 'metric'}] {s['best_evidence'][:160]}"
                      + (f"  (via {via})" if via else "") + "\n")
        if verbose:
            for f in s["fails"][:2]:
                ctx = f" ({f['ctx']})" if f["ctx"] else ""
                out.write(f"{'':<10}        blocker x{f['count']}: {f['label']}{ctx}\n")
    d = score["metric_detail"]
    for k in ("respawns", "crashes", "usertraps", "codesign"):
        if d.get(k):
            out.write(f"  {k}: " + ", ".join(f"{p} {n}" for p, n in d[k].items()) + "\n")
    out.write("  ? = first missing rung has no physical sample yet (UNVERIFIED-NO-SAMPLE)\n")


def _md_escape(t):
    return (t or "").replace("|", "\\|").replace("`", "'")


def render_md(score):
    m = score["metrics"]
    lines = [f"# hk_score: {score['boot']}", "",
             f"Sources: {score['coverage']} ({', '.join(score['parts'])}). Uptime {m['uptime_s']} s, unplanned panics "
             f"{m['unplanned_panics']}, crashes {m['crashes']}, usertraps {m['usertraps']}, CODE SIGNING {m['codesign']}, "
             f"max execs of one daemon {m['respawn_max']}.", ""]
    lines += ["| Subsystem | Level | Best rung (proof) | First missing | Next (source) |", "|---|---|---|---|---|"]
    for s in score["subsystems"]:
        lvl = f"{s['level']}/{s['total']}" if s["exercised"] else "not exercised"
        best = f"{s['best_label']} [{s['best_time']}] `{_md_escape(s['best_evidence'])[:160]}`" if s["best_label"] else "-"
        fm = s["first_missing_label"] or "complete"
        if s["first_missing"] and s["rungs"][s["level"]]["unverified"]:
            fm += " (UNVERIFIED-NO-SAMPLE)"
        lines.append(f"| {s['title']} | {lvl} | {_md_escape(best)} | {_md_escape(fm)} | "
                     f"{_md_escape(s['next'])} ({_md_escape(s['next_src'])}) |")
    boot = next(s for s in score["subsystems"] if s["id"] == "boot")
    lines += ["", "## Boot timeline", ""]
    for r in boot["rungs"]:
        lines.append(f"- {r['state']:<8} {r['label']}" + (f" [{r['time']}] `{_md_escape(r['evidence'])}`" if r["evidence"] else ""))
    lines += ["", "## Blockers seen", ""]
    for s in score["subsystems"]:
        for f in s["fails"]:
            ctx = f" ({f['ctx']})" if f["ctx"] else ""
            lines.append(f"- {s['id']}: {f['label']} x{f['count']}{ctx} [{f['time']}] `{_md_escape(f['evidence'])[:160]}`")
    d = score["metric_detail"]
    lines += ["", "## Stability detail", ""] + [f"- {k}: " + ", ".join(f"{p} {n}" for p, n in v.items())
                                                for k, v in d.items() if v]
    return "\n".join(lines) + "\n"


def print_diff(rows, new_name, old_name, out=None):
    out = out or sys.stdout
    out.write(f"hk_score diff {old_name} -> {new_name}\n")
    for sid, o, s, verdict in rows:
        ol = f"{o['level']}/{o['total']} {_rung_name(o, o['best'])}" if o and o["exercised"] else "--"
        nl = f"{s['level']}/{s['total']} {_rung_name(s, s['best'])}" if s["exercised"] else "--"
        out.write(f"  {sid:<10} {ol:<28} -> {nl:<28} {verdict.upper() if verdict in ('regression', 'lost') else verdict}\n")
        if o and verdict in ("progress", "regression"):
            ost = {r["id"]: r["state"] for r in o["rungs"]}
            for r in s["rungs"]:
                was = ost.get(r["id"])
                if was and (was == "missing") != (r["state"] == "missing"):
                    out.write(f"  {'':<10}   {r['id']}: {was} -> {r['state']}\n")


def validate(boots, board, out=None):
    """Which boots each rung's checks match (ignoring implication and gating). Returns problems."""
    out = out or sys.stdout
    problems, hits = [], {}
    for att, live in boots:
        b = Boot(att, live)
        names = {b.name} | {Path(p).name for p in b.parts}
        for sub in board["subsystems"]:
            for r in sub["rungs"]:
                if eval_spec(r, b)[0]:
                    hits.setdefault((sub["id"], r["id"]), []).append(names)
    for sub in board["subsystems"]:
        for r in sub["rungs"]:
            hs = hits.get((sub["id"], r["id"]), [])
            h = [min(n, key=len) for n in hs]
            status = f"VERIFIED x{len(h)} (newest: {', '.join(h[-2:])})" if h else "UNVERIFIED-NO-SAMPLE"
            if r.get("sample") and not any(r["sample"] in n for n in hs):
                problems.append(f"{sub['id']}.{r['id']}: sample {r['sample']} does not match")
            if r.get("unverified") and h:
                problems.append(f"{sub['id']}.{r['id']}: marked unverified but matches {h[0]}")
            out.write(f"  {sub['id'] + '.' + r['id']:<32} {status}\n")
    for p in problems:
        out.write(f"PROBLEM {p}\n")
    return problems


def render_matrix(scores):
    """Level per subsystem per boot (oldest first): a drop between neighbouring rows of the same image line is a
    regression to look at; '--' = not exercised in that boot."""
    ids = [s["id"] for s in scores[0]["subsystems"]] if scores else []
    lines = ["| Boot | " + " | ".join(ids) + " |", "|---" * (len(ids) + 1) + "|"]
    for sc in scores:
        cells = [f"{s['level']}" if s["exercised"] else "--" for s in sc["subsystems"]]
        lines.append(f"| {sc['boot']} | " + " | ".join(cells) + " |")
    return lines


def render_best_md(subs, actions, boots_desc, scores=None):
    lines = ["# Hardware status baseline (best-known rung per subsystem)", "",
             "Generated by `python3 -I tools/hk_score.py --best --md` from physical boots: " + boots_desc + ".",
             "A rung counts once any boot proves it with its own line; `implied` means a higher rung was proved "
             "but this rung's line was not captured (ramdump ring tail). PHYSICAL evidence only.", "",
             "| Subsystem | Level | Best rung | Proved by | First missing rung | Next (source) |",
             "|---|---|---|---|---|---|"]
    for s in subs:
        b = s["rungs"][s["best"]] if s["best"] is not None else None
        fm = s["rungs"][s["level"]] if s["level"] < s["total"] else None
        fml = (fm["label"] + (" (UNVERIFIED-NO-SAMPLE)" if fm["unverified"] else "")) if fm else "complete"
        nxt = f"{fm['rule']['next']} ({fm['rule'].get('src', 'unknown')})" if fm else ""
        lines.append(f"| {s['title']} | {s['level']}/{s['total']} | {_md_escape(b['label']) if b else '-'} | "
                     f"{b['boot'] if b else '-'} | {_md_escape(fml)} | {_md_escape(nxt)} |")
    lines += ["", "## Top next actions (ranked by rungs unblocked)", ""]
    for k, a in enumerate(actions, 1):
        lines.append(f"{k}. **{a['action']}** - unblocks {a['unblocks']} rung(s) ({', '.join(a['subsystems'])}): "
                     f"{_md_escape(a['next'])} _(source: {_md_escape(a['src'])})_")
    if scores:
        lines += ["", "## Level per boot (rungs satisfied from the bottom)", ""] + render_matrix(scores)
    lines += ["", "## Evidence per rung", ""]
    for s in subs:
        lines.append(f"### {s['title']}")
        for r in s["rungs"]:
            ev = f" - {r['boot']} [{r['time']}] `{_md_escape(r['evidence'])[:160]}`" if r["evidence"] else ""
            unv = " (UNVERIFIED-NO-SAMPLE)" if r["unverified"] and r["state"] != "reached" else ""
            lines.append(f"- {r['state']:<8} {r['label']}{unv}{ev}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("boots", nargs="*", help="attempt dir, live dir or log file (with --best: several)")
    ap.add_argument("--board", default=str(BOARD))
    ap.add_argument("--attempts", default=str(ATTEMPTS), help="where --latest/--best/--validate look")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--brief", action="store_true", help="table only, no proof lines")
    ap.add_argument("--diff", metavar="OTHER", help="compare with another boot (dir or --json file)")
    ap.add_argument("--baseline", metavar="OTHER", help="exit 1 if any subsystem regressed versus this boot/json")
    ap.add_argument("--strict", action="store_true", help="with --baseline: a subsystem lost (not exercised) also fails")
    ap.add_argument("--best", action="store_true", help="best-known rung per subsystem across boots")
    ap.add_argument("--since", help="YYYYMMDD: with --best/--validate, only boots from that day on")
    ap.add_argument("--until", help="YYYYMMDD: with --best/--validate, only boots up to that day")
    ap.add_argument("--validate", action="store_true", help="where each rung matches across the attempts")
    args = ap.parse_args(argv)
    try:
        board = load_board(args.board)
        if args.validate:
            problems = validate(list_boots(args.attempts, args.since, args.until), board)
            return 1 if problems else 0
        if args.best:
            pairs = [pair(p) if Path(p).is_dir() else (None, None) for p in args.boots] if args.boots \
                else list_boots(args.attempts, args.since, args.until)
            scores = [score_boot(Boot(a, l), board) for a, l in pairs if a or l]
            subs = aggregate(scores, board)
            acts = top_actions(subs)
            if args.json:
                for s in subs:
                    for r in s["rungs"]:
                        r.pop("rule", None)
                print(json.dumps({"boots": [s["boot"] for s in scores], "subsystems": subs, "actions": acts}, indent=1))
            else:
                desc = f"{len(scores)} boots" + (f" from {args.since}" if args.since else "") + \
                    (f" to {args.until}" if args.until else "")
                text = render_best_md(subs, acts, desc, scores)
                sys.stdout.write(text)
            return 0
        if args.latest:
            boot = latest(args.attempts)
        elif len(args.boots) == 1:
            boot = boot_from_path(args.boots[0])
        else:
            ap.error("give one boot (attempt or live dir), or --latest / --best / --validate")
        score = score_boot(boot, board)
        rc = 0
        if args.baseline:
            base = load_score(args.baseline, board)
            rows = diff(score, base)
            bad = ("regression", "lost") if args.strict else ("regression",)
            if any(v in bad for *_x, v in rows):
                rc = 1
            if not (args.json or args.md):
                print_diff(rows, score["boot"], base["boot"])
        if args.diff:
            other = load_score(args.diff, board)
            rows = diff(score, other)
            if args.json:
                print(json.dumps([{"subsystem": sid, "verdict": v,
                                   "old": {"level": o["level"], "best": o["best_id"]} if o else None,
                                   "new": {"level": s["level"], "best": s["best_id"]}} for sid, o, s, v in rows], indent=1))
            else:
                print_diff(rows, score["boot"], other["boot"])
            return rc
        if args.json:
            print(json.dumps(score, indent=1))
        elif args.md:
            sys.stdout.write(render_md(score))
        else:
            print_table(score, verbose=not args.brief)
        return rc
    except Exception as error:  # bad input: unreadable dir, malformed yaml, bad regex
        if not isinstance(error, (OSError, ValueError)) and type(error).__module__.split(".")[0] != "yaml":
            raise
        print(f"hk_score: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
