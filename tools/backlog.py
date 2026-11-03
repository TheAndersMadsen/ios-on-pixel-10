#!/usr/bin/env python3
"""Turn the debug tools' output into one concrete, assignable backlog.

Ingests probe_eval.py (README-row verdicts) and crashdoc.py (crash census) over one or more boot
attempts, merges them with a curated notes file (owners, approaches, deferrals, standalone findings),
and emits docs/debug/BACKLOG.md + docs/debug/backlog.json.

Every not-working README row and every open crash becomes a backlog item with: id, subsystem, title,
severity, status, owner (which agent/lane, or UNASSIGNED), evidence (file:line), and the next step.

Usage:
  python3 -I tools/backlog.py ATTEMPT_DIR [ATTEMPT_DIR ...] [--notes docs/debug/backlog-notes.json]
                                          [--out docs/debug/BACKLOG.md] [--json docs/debug/backlog.json]
Run from the repo root on m1box. Read-only except the two output files.
"""
import argparse, json, os, subprocess, sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / 'tools/probe_eval.py'
CRASH = ROOT / 'tools/crashdoc.py'

SEV = {'none': 'high', 'open': 'high', 'partial': 'med', 'active': 'low'}
SEV_ORDER = {'high': 0, 'med': 1, 'low': 2, 'info': 3}


def run_json(tool, attempts):
    try:
        p = subprocess.run([sys.executable, '-I', str(tool), *attempts, '--json'],
                           capture_output=True, text=True, timeout=1200)
        return json.loads(p.stdout)
    except Exception as e:
        print(f'backlog: {tool.name} failed: {e}', file=sys.stderr)
        return {}


def load_notes(path):
    if path and Path(path).is_file():
        return json.loads(Path(path).read_text())
    return {'assign': [], 'defer': [], 'overrides': {}, 'items': []}


def assign(notes, text):
    """First keyword rule whose 'match' is a substring of the item's id/title/subsystem wins."""
    low = text.lower()
    for rule in notes.get('defer', []):
        if rule['match'].lower() in low:
            return ('DEFERRED', rule.get('owner', '-'), rule.get('reason', rule.get('approach', '')))
    for rule in notes.get('assign', []):
        if rule['match'].lower() in low:
            return (rule.get('status', 'IN-PROGRESS'), rule.get('owner', 'UNASSIGNED'), rule.get('approach', ''))
    return ('OPEN', 'UNASSIGNED', '')


def first_cite(ev):
    for e in ev or []:
        for c in e.get('cites', []):
            return c.split(': ', 1)[0] if ': ' in c else c
    return ''


def items_from_probe(doc, notes):
    out = []
    for r in doc.get('rows', []):
        v = r.get('verdict') or 'none'
        if v in ('works', 'pass'):
            continue
        if r.get('milestone') and v in ('works', 'pass'):
            continue
        rid, row = r.get('id', '?'), r.get('row', r.get('id', '?'))
        status, owner, approach = assign(notes, f"{rid} {row}")
        sev = SEV.get(v, 'med')
        if r.get('milestone'):
            sev = 'high'
        out.append({
            'id': f'probe:{rid}', 'subsystem': rid.split('-')[0], 'title': row,
            'kind': 'readme-row', 'verdict': v, 'phone_only': bool(r.get('phone_only')),
            'severity': sev, 'status': status, 'owner': owner, 'approach': approach,
            'evidence': first_cite(r.get('evidence')), 'next': r.get('next') or '',
        })
    return out


def items_from_crash(doc, notes):
    out = []
    for s in doc.get('signatures', []):
        if not s.get('crash'):
            continue
        st = (s.get('status') or '').lower()
        if 'open' not in st and 'still' not in st:
            continue  # only live/open crashes
        proc = s.get('proc', '?')
        status, owner, approach = assign(notes, f"{proc} {s.get('sig','')}")
        out.append({
            'id': f'crash:{s.get("id")}', 'subsystem': proc, 'title': s.get('sig', proc),
            'kind': 'crash', 'verdict': s.get('status', ''), 'phone_only': True,
            'severity': 'high', 'status': status, 'owner': owner, 'approach': approach,
            'evidence': (s.get('example') or {}).get('ref', ''),
            'next': '; '.join(h.get('cause', '') for h in s.get('hints', [])) or '',
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('attempts', nargs='+')
    ap.add_argument('--notes', default=str(ROOT / 'docs/debug/backlog-notes.json'))
    ap.add_argument('--out', default=str(ROOT / 'docs/debug/BACKLOG.md'))
    ap.add_argument('--json', default=str(ROOT / 'docs/debug/backlog.json'))
    a = ap.parse_args()

    notes = load_notes(a.notes)
    items = []
    if PROBE.is_file():
        items += items_from_probe(run_json(PROBE, a.attempts), notes)
    if CRASH.is_file():
        items += items_from_crash(run_json(CRASH, a.attempts), notes)
    items += notes.get('items', [])  # standalone curated findings

    # per-id overrides (owner/status/severity/approach)
    for it in items:
        ov = notes.get('overrides', {}).get(it['id'])
        if ov:
            it.update(ov)

    # de-dup by id (last wins)
    byid = {it['id']: it for it in items}
    items = list(byid.values())
    items.sort(key=lambda it: (SEV_ORDER.get(it.get('severity'), 9), it.get('status', ''), it['id']))

    groups = {}
    for it in items:
        groups.setdefault(it.get('status', 'OPEN'), []).append(it)

    lines = ['# hackios debug backlog', '',
             'Generated by `tools/backlog.py` from `probe_eval` + `crashdoc` over the latest boots, '
             'merged with `docs/debug/backlog-notes.json`. Regenerate after each boot. '
             'Each item is agent-assignable: UNASSIGNED items are ready to spawn.', '',
             f'Totals: {len(items)} items — ' +
             ', '.join(f'{k} {len(v)}' for k, v in sorted(groups.items())), '']
    order = ['OPEN', 'IN-PROGRESS', 'FIXED-PENDING-VERIFY', 'TEST-ONLY', 'DEFERRED']
    for g in order + [k for k in groups if k not in order]:
        if g not in groups:
            continue
        lines.append(f'## {g} ({len(groups[g])})')
        lines.append('')
        lines.append('| sev | id | subsystem | item | owner | evidence / next |')
        lines.append('|---|---|---|---|---|---|')
        for it in groups[g]:
            nxt = it.get('next', '')
            if isinstance(nxt, dict):  # probe_eval's structured next-step
                nxt = f"[{nxt.get('kind','?')} {nxt.get('minutes','?')}m] {nxt.get('test','')}"
            ev = str(it.get('evidence', '') or nxt or '').replace('\n', ' ').replace('|', '/')
            title = str(it.get('title', '')).replace('\n', ' ').replace('|', '/')
            lines.append(f"| {it.get('severity','?')} | `{it['id']}` | {it.get('subsystem','')} | "
                         f"{title} | {it.get('owner','UNASSIGNED')} | {ev[:80]} |")
        lines.append('')

    Path(a.out).write_text('\n'.join(lines))
    Path(a.json).write_text(json.dumps({'items': items, 'groups': {k: len(v) for k, v in groups.items()}},
                                       indent=2, default=str))
    print(f'backlog: {len(items)} items -> {a.out}')
    for g in order:
        if g in groups:
            print(f'  {g}: {len(groups[g])}')


if __name__ == '__main__':
    main()
