#!/usr/bin/env python3
"""Build the README's status block and animated SVGs from docs/status.json.

Usage: python3 -I tools/readme_status.py        rewrite docs/assets/*.svg and README.md's block
       python3 -I tools/readme_status.py --check exit 1 if they are out of date

Percent = mean of each feature's score (status.json "scores"). Features marked "out"
are left out of the percentage and listed separately, so the number can reach 100.
"""
import json
import pathlib
import sys
from html import escape

ROOT = pathlib.Path(__file__).resolve().parent.parent
BEGIN, END = '<!-- status:begin -->', '<!-- status:end -->'
ICON = {'works': '✅', 'partial': '🟡', 'built': '🔧', 'active': '⏳', 'open': '❌', 'out': '🚫'}
WORD = {'works': 'Works on the phone', 'partial': 'Partly working', 'built': 'Built, not run',
        'active': 'In progress', 'open': 'Not started', 'out': 'Likely out of reach'}
COLOUR = {'works': '#30d158', 'partial': '#ffd60a', 'built': '#64d2ff', 'active': '#bf5af2', 'open': '#636366', 'out': '#3a3a3c'}
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Display','Helvetica Neue',Helvetica,Arial,sans-serif"
GRADIENT = ('<linearGradient id="g" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#5e5ce6"/>'
            '<stop offset=".5" stop-color="#bf5af2"/><stop offset="1" stop-color="#ff375f"/></linearGradient>')


def percent(features, scores):
    counted = [scores[f[1]] for f in features if scores[f[1]] is not None]
    return round(sum(counted) / len(counted)) if counted else None


def rise(delay, dur=1.0):
    """Fade and rise by SMIL. Base attributes hold the final state, so a viewer with no animation still shows it all."""
    total = delay + dur
    k = f'0;{delay / total:.3f};1'
    spline = 'calcMode="spline" keySplines="0 0 1 1;.2 .8 .2 1"'
    return (f'<animate attributeName="opacity" values="0;0;1" keyTimes="{k}" {spline} dur="{total:.2f}s" fill="freeze"/>'
            f'<animateTransform attributeName="transform" type="translate" values="0 22;0 22;0 0" keyTimes="{k}" {spline} dur="{total:.2f}s" fill="freeze"/>')


def text(x, y, size, fill, body, delay, weight=400, spacing=0, dur=1.0):
    extra = f' letter-spacing="{spacing}"' if spacing else ''
    return (f'<text font-family="{FONT}" x="{x}" y="{y}" text-anchor="middle" font-size="{size}" font-weight="{weight}"{extra} fill="{fill}">'
            f'{body}{rise(delay, dur)}</text>')


def hero(pct, data):
    r = 118
    circumference = 2 * 3.14159265 * r
    target = circumference * (1 - pct / 100)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 640" role="img" aria-label="iOS 26 on Pixel 10 Pro: {pct} percent of reachable hardware">
<defs>{GRADIENT}
<radialGradient id="glow" cx=".5" cy=".5" r=".55"><stop offset="0" stop-color="#5e5ce6" stop-opacity=".5"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
<linearGradient id="t" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#a1a1a6"/></linearGradient></defs>
<rect width="1200" height="640" rx="28" fill="#000"/>
<rect width="1200" height="640" rx="28" fill="url(#glow)" opacity=".85"><animate attributeName="opacity" values=".55;1;.55" dur="6s" repeatCount="indefinite"/></rect>
{text(600, 84, 24, "#bf5af2", "Pixel 10 Pro", 0, 600)}
{text(600, 150, 64, "url(#t)", "iOS 26. Running natively.", .15, 700, -1.5)}
<g transform="rotate(-90 600 342)"><circle cx="600" cy="342" r="{r}" fill="none" stroke="#1c1c1e" stroke-width="20"/>
<circle cx="600" cy="342" r="{r}" fill="none" stroke="url(#g)" stroke-width="20" stroke-linecap="round" stroke-dasharray="{circumference:.1f}" stroke-dashoffset="{target:.1f}"><animate attributeName="stroke-dashoffset" values="{circumference:.1f};{circumference:.1f};{target:.1f}" keyTimes="0;.17;1" calcMode="spline" keySplines="0 0 1 1;.3 .7 .2 1" dur="3s" fill="freeze"/></circle></g>
{text(600, 360, 76, "#f5f5f7", f"{pct}%", .9, 700, -2)}
{text(600, 394, 18, "#86868b", "of reachable hardware", 1.1)}
{text(600, 526, 27, "#f5f5f7", "Real XNU. Real iOS. On Tensor G5. No emulator.", 1.3, 500)}
{text(600, 566, 19, "#86868b", f"Experimental bring-up, booted from RAM. Updated {escape(data["updated"])}.", 1.5)}
</svg>
'''


def blocks_svg(rows):
    h = 76 + 60 * len(rows)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {h}" role="img" aria-label="Progress by hardware block"><defs>{GRADIENT}</defs><rect width="1200" height="{h}" rx="28" fill="#000"/>']
    y = 62
    for i, (name, pct, n) in enumerate(rows):
        delay = i * .08
        out.append(f'<text font-family="{FONT}" x="48" y="{y}" font-size="23" font-weight="600" fill="{"#636366" if pct is None else "#f5f5f7"}">{escape(name)}</text>')
        if pct is None:
            out.append(f'<text font-family="{FONT}" x="1152" y="{y}" text-anchor="end" font-size="19" fill="#636366">Likely out of reach</text>')
        else:
            w = 8 * pct
            out.append(f'<rect x="250" y="{y-16}" width="800" height="16" rx="8" fill="#1c1c1e"/>')
            if w:
                total = delay + 1.6
                out.append(f'<clipPath id="c{i}"><rect x="250" y="{y-16}" width="{w}" height="16" rx="8"/></clipPath>')
                out.append(f'<g clip-path="url(#c{i})"><rect x="250" y="{y-16}" width="{w}" height="16" fill="url(#g)"><animate attributeName="width" values="0;0;{w}" keyTimes="0;{delay/total:.3f};1" calcMode="spline" keySplines="0 0 1 1;.2 .8 .2 1" dur="{total:.2f}s" fill="freeze"/></rect>'
                           f'<rect x="{250 + w}" y="{y-16}" width="110" height="16" fill="#fff" opacity=".22"><animate attributeName="x" values="{250-110};{250 + w}" dur="3.2s" begin="{total:.2f}s" repeatCount="indefinite"/></rect></g>')
            out.append(f'<text font-family="{FONT}" x="1152" y="{y}" text-anchor="end" font-size="23" font-weight="600" fill="#f5f5f7">{pct}%</text>')
        y += 60
    out.append('</svg>\n')
    return '\n'.join(out)


def stats_svg(stats):
    cols, cw, ch = 3, 400, 196
    h = ch * ((len(stats) + cols - 1) // cols) + 24
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {h}" role="img" aria-label="Measured on the phone"><defs>{GRADIENT}</defs><rect width="1200" height="{h}" rx="28" fill="#000"/>']
    for i, s in enumerate(stats):
        x, y = cw * (i % cols) + 200, ch * (i // cols) + 92
        unit = f'<tspan font-size="30" font-weight="600" dx="6">{escape(s["unit"])}</tspan>' if s.get('unit') else ''
        d = i * .15
        out.append(text(x, y, 68, "url(#g)", escape(s["value"]) + unit, d, 700, -1.5, .9))
        out.append(text(x, y + 38, 21, "#f5f5f7", escape(s["label"]), d + .1, 500, 0, .9))
        out.append(text(x, y + 66, 16, "#86868b", escape(s["note"]), d + .2, 400, 0, .9))
    out.append('</svg>\n')
    return '\n'.join(out)


def markdown(data, pct, rows, feats):
    lines = [BEGIN, '', '<p align="center"><img src="docs/assets/hero.svg" alt="iOS 26 on Pixel 10 Pro: ' + f'{pct}% of reachable hardware" width="100%"></p>', '',
             '<h2 align="center">A phone that was never meant to do this.</h2>',
             '<p align="center">Apple\'s open-source kernel. iOS 26\'s own userland. Google\'s Tensor G5.<br>Custom drivers, written block by block, for one extraordinary piece of hardware.</p>', '',
             '<p align="center"><img src="docs/assets/stats.svg" alt="Measured on the phone" width="100%"></p>', '',
             '<h2 align="center">Every block. Tracked.</h2>',
             f'<p align="center"><b>{pct}%</b> across {sum(1 for f in feats if f[1] != "out")} reachable features. Updated {data["updated"]}.</p>', '',
             '<p align="center"><img src="docs/assets/blocks.svg" alt="Progress by hardware block" width="100%"></p>', '',
             '| | Status | Features | Counts as |', '| --- | --- | ---: | ---: |']
    for key in ICON:
        count = sum(1 for f in feats if f[1] == key)
        score = data['scores'][key]
        lines.append(f'| {ICON[key]} | {WORD[key]} | {count} | {"not counted" if score is None else str(score) + "%"} |')
    lines += ['', '<details><summary><b>See every feature</b></summary>', '', '| Block | Feature | Status |', '| --- | --- | --- |']
    for block in data['blocks']:
        for i, (name, status, note) in enumerate(block['features']):
            head = f'**{block["name"]}**' if i == 0 else ''
            text = f'{ICON[status]} {note}'.rstrip()
            lines.append(f'| {head} | {name} | {text} |')
    lines += ['', '</details>', '',
              '<sub>Percentages are a progress estimate from the table above, not a benchmark. Measured figures come from single test boots of one phone, and their notes say which were short tests or estimates. '
              'Rebuild with `python3 -I tools/readme_status.py` after editing `docs/status.json`.</sub>', '',
              '> **What this is.** An experimental research bring-up on the owner\'s own phone, not a usable phone OS and not a product. '
              'Nothing here is for sale. It isn\'t affiliated with or endorsed by Apple or Google. No Apple software or firmware is distributed here. '
              'Apple\'s security model is largely switched off, so the phone isn\'t safe for real data.', '', END]
    return '\n'.join(lines)


def main():
    data = json.loads((ROOT / 'docs/status.json').read_text())
    scores = data['scores']
    feats = [f for b in data['blocks'] for f in b['features']]
    pct = percent(feats, scores)
    rows = [(b['name'], percent(b['features'], scores), len(b['features'])) for b in data['blocks']]
    files = {'docs/assets/hero.svg': hero(pct, data), 'docs/assets/blocks.svg': blocks_svg(rows), 'docs/assets/stats.svg': stats_svg(data['stats'])}
    readme = (ROOT / 'README.md').read_text()
    block = markdown(data, pct, rows, feats)
    if BEGIN in readme:
        head, rest = readme.split(BEGIN, 1)
        new = head + block + rest.split(END, 1)[1]
    else:
        new = block + '\n\n---\n\n' + readme
    files['README.md'] = new
    if '--check' in sys.argv:
        stale = [p for p, text in files.items() if not (ROOT / p).exists() or (ROOT / p).read_text() != text]
        print('stale: ' + ' '.join(stale) if stale else 'up to date')
        return 1 if stale else 0
    (ROOT / 'docs/assets').mkdir(exist_ok=True)
    for p, text in files.items():
        (ROOT / p).write_text(text)
    print(f'{pct}% of {sum(1 for f in feats if f[1] != "out")} reachable features; ' + ', '.join(f'{n} {p if p is not None else "out"}' for n, p, _ in rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
