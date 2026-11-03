#!/usr/bin/env python3
"""Build the README's status block and animated SVGs from docs/status.json.

Usage: python3 -I tools/readme_status.py        rewrite docs/assets/*.svg and README.md's blocks
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
ROADMAP_BEGIN, ROADMAP_END = '<!-- roadmap:begin -->', '<!-- roadmap:end -->'
NAV = (('Progress', 'progress'), ('Quick start', 'quick-start'), ('Roadmap', 'roadmap'), ('How it boots', 'how-it-boots'),
       ('Docs', 'documentation'), ('Contributing', 'contributing'), ('Licensing', 'licensing'), ('Credits', 'credits'))
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


# Block glyphs: original single-path pictograms drawn on a 100x100 grid (no Apple or Google artwork).
GLYPH = {
    'CPU': 'M30 30h40v40H30z M38 38h24v24H38z M22 38h8M22 50h8M22 62h8M70 38h8M70 50h8M70 62h8M38 22v8M50 22v8M62 22v8M38 70v8M50 70v8M62 70v8',
    'Memory': 'M18 36h64v28H18z M28 44h8v12h-8z M46 44h8v12h-8z M64 44h8v12h-8z M24 64v8M40 64v8M60 64v8M76 64v8',
    'Display': 'M34 18h32a6 6 0 0 1 6 6v52a6 6 0 0 1-6 6H34a6 6 0 0 1-6-6V24a6 6 0 0 1 6-6z M44 76h12',
    'Graphics': 'M50 18l30 17v30L50 82 20 65V35z M50 18v64 M20 35l30 17 30-17',
    'Storage': 'M24 30a26 9 0 1 0 52 0a26 9 0 1 0-52 0z M24 30v40a26 9 0 0 0 52 0V30 M24 50a26 9 0 0 0 52 0',
    'Input': 'M50 22v18 M38 50a12 12 0 1 0 24 0a12 12 0 1 0-24 0z M30 72c6-8 34-8 40 0',
    'Connectivity': 'M22 44a40 40 0 0 1 56 0 M31 54a27 27 0 0 1 38 0 M40 64a14 14 0 0 1 20 0 M50 74h.1',
    'USB': 'M50 16v56 M50 16l-8 10h16z M50 46l-16-10v-8 M50 56l16-10v-8 M42 72h16v10H42z',
    'Audio': 'M24 42h14l18-14v44L38 58H24z M66 38a16 16 0 0 1 0 24 M74 30a28 28 0 0 1 0 40',
    'Sensors': 'M50 18a32 32 0 1 0 .1 0z M50 50L64 30 M50 50h.1',
    'Power': 'M24 34h48v32H24z M72 44h6v12h-6 M30 40h20v20H30z',
    'Cameras': 'M22 34h14l6-8h16l6 8h14v40H22z M50 54a12 12 0 1 0 .1 0z',
    'Security': 'M50 16l28 10v20c0 20-12 32-28 38-16-6-28-18-28-38V26z',
    'Apple services': 'M50 22a28 28 0 1 0 .1 0z M50 22v56 M22 50h56 M30 32c12 8 28 8 40 0 M30 68c12-8 28-8 40 0',
}
SHORT = {'Connectivity': 'Radios', 'Apple services': 'Services'}
TINT = ['#0a84ff', '#5e5ce6', '#bf5af2', '#ff375f', '#ff9f0a', '#30d158', '#64d2ff', '#ffd60a', '#ff6482', '#66d4cf', '#32d74b', '#8e8e93', '#8e8e93', '#8e8e93']


def pop(cx, cy, delay, dur=.7):
    """Scale-in about (cx, cy) with a small overshoot; final state is the base attribute."""
    total = delay + dur
    k = f'0;{delay / total:.3f};{(delay + dur * .7) / total:.3f};1'
    return (f'<animateTransform attributeName="transform" type="scale" values="0;0;1.08;1" keyTimes="{k}" dur="{total:.2f}s" fill="freeze" additive="sum"/>'
            f'<animate attributeName="opacity" values="0;0;1;1" keyTimes="{k}" dur="{total:.2f}s" fill="freeze"/>')


def ring(cx, cy, r, w, pct, colour, delay, track='#2c2c2e', dur=1.6):
    c = 2 * 3.14159265 * r
    target = c * (1 - (pct or 0) / 100)
    total = delay + dur
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{track}" stroke-width="{w}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{colour}" stroke-width="{w}" stroke-linecap="round" '
            f'stroke-dasharray="{c:.1f}" stroke-dashoffset="{target:.1f}" transform="rotate(-90 {cx} {cy})">'
            f'<animate attributeName="stroke-dashoffset" values="{c:.1f};{c:.1f};{target:.1f}" keyTimes="0;{delay / total:.3f};1" '
            f'calcMode="spline" keySplines="0 0 1 1;.3 .7 .2 1" dur="{total:.2f}s" fill="freeze"/></circle>')


def phone(x, y, pct, rows):
    """Pixel 10 Pro, front view, 300x640: the chooser picks iOS, then a home screen builds itself."""
    w, h = 300, 640
    sx, sy, sw, sh = x + 14, y + 14, w - 28, h - 28
    o = [f'<g>',
         f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="52" fill="#1d1d1f" stroke="#3a3a3c" stroke-width="2"/>',
         f'<rect x="{x - 3}" y="{y + 150}" width="3" height="70" rx="1.5" fill="#3a3a3c"/><rect x="{x - 3}" y="{y + 240}" width="3" height="110" rx="1.5" fill="#3a3a3c"/>',
         f'<clipPath id="scr"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="40"/></clipPath>',
         f'<g clip-path="url(#scr)">',
         f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="url(#wall)"/>',
         f'<circle cx="{sx + 60}" cy="{sy + 160}" r="170" fill="url(#orb1)"><animate attributeName="cy" values="{sy + 160};{sy + 220};{sy + 160}" dur="11s" repeatCount="indefinite"/></circle>',
         f'<circle cx="{sx + sw - 40}" cy="{sy + sh - 160}" r="190" fill="url(#orb2)"><animate attributeName="cx" values="{sx + sw - 40};{sx + sw - 100};{sx + sw - 40}" dur="13s" repeatCount="indefinite"/></circle>']
    # status bar
    o.append(f'<text font-family="{FONT}" x="{sx + 38}" y="{sy + 36}" font-size="15" font-weight="600" fill="#fff">9:41</text>')
    o.append(f'<g fill="#fff"><rect x="{sx + sw - 72}" y="{sy + 25}" width="24" height="11" rx="3" fill="none" stroke="#fff" stroke-width="1.5"/>'
             f'<rect x="{sx + sw - 70}" y="{sy + 27}" width="{int(20 * pct / 100)}" height="7" rx="1.5"/></g>')
    # widget: progress ring
    wx, wy = sx + 18, sy + 64
    o.append(f'<g transform="translate({wx + 117} {wy + 70})"><g>{pop(0, 0, 2.6)}<g transform="translate({-wx - 117} {-wy - 70})">'
             f'<rect x="{wx}" y="{wy}" width="{sw - 36}" height="140" rx="26" fill="#000" fill-opacity=".35" stroke="#fff" stroke-opacity=".12"/>'
             f'{ring(wx + 70, wy + 70, 42, 11, pct, "url(#g)", 3.0)}'
             f'<text font-family="{FONT}" x="{wx + 70}" y="{wy + 78}" text-anchor="middle" font-size="22" font-weight="700" fill="#fff">{pct}%</text>'
             f'<text font-family="{FONT}" x="{wx + 132}" y="{wy + 58}" font-size="13" font-weight="600" fill="#fff" fill-opacity=".7">BRING-UP</text>'
             f'<text font-family="{FONT}" x="{wx + 132}" y="{wy + 82}" font-size="17" font-weight="700" fill="#fff">iOS 26</text>'
             f'<text font-family="{FONT}" x="{wx + 132}" y="{wy + 102}" font-size="13" fill="#fff" fill-opacity=".7">on Tensor G5</text></g></g></g>')
    # icon grid: one icon per hardware block
    cols, isz, gap = 4, 50, 14
    gx = sx + (sw - (cols * isz + (cols - 1) * gap)) // 2
    gy = wy + 166
    for i, (name, bp, _) in enumerate(rows[:12]):
        cx = gx + (i % cols) * (isz + gap)
        cy = gy + (i // cols) * (isz + 30)
        tint = TINT[i % len(TINT)] if bp is not None else '#48484a'
        d = 3.3 + i * .07
        g = GLYPH.get(name, '')
        o.append(f'<g transform="translate({cx + isz / 2} {cy + isz / 2})"><g>{pop(0, 0, d)}<g transform="translate({-isz / 2} {-isz / 2})">'
                 f'<rect width="{isz}" height="{isz}" rx="13" fill="{tint}"/>'
                 f'<rect width="{isz}" height="{isz / 2}" rx="13" fill="#fff" fill-opacity=".14"/>'
                 f'<path d="{g}" transform="translate(9 9) scale(.32)" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
                 f'</g></g></g>')
        o.append(f'<text font-family="{FONT}" x="{cx + isz / 2}" y="{cy + isz + 15}" text-anchor="middle" font-size="9.5" fill="#fff" fill-opacity=".9">{escape(SHORT.get(name, name))}<animate attributeName="opacity" values="0;0;1" keyTimes="0;.85;1" dur="{d + .7:.2f}s" fill="freeze"/></text>')
    # dock
    dy = sy + sh - 104
    o.append(f'<rect x="{sx + 12}" y="{dy}" width="{sw - 24}" height="78" rx="28" fill="#fff" fill-opacity=".16"><animate attributeName="opacity" values="0;0;1" keyTimes="0;.8;1" dur="3.6s" fill="freeze"/></rect>')
    for j, t in enumerate(('#30d158', '#0a84ff', '#ffffff', '#ff9f0a')):
        cx = sx + 34 + j * 58
        o.append(f'<g transform="translate({cx + 25} {dy + 39})"><g>{pop(0, 0, 3.4 + j * .08)}<rect x="-25" y="-25" width="50" height="50" rx="13" fill="{t}" fill-opacity="{.95 if t != "#ffffff" else .9}"/></g></g>')
    o.append(f'<rect x="{sx + sw / 2 - 60}" y="{sy + sh - 14}" width="120" height="5" rx="2.5" fill="#fff"/>')
    # boot sequence overlay: black -> chooser (Android / iOS, iOS picked) -> fades out at 2.3 s
    ox, oy = sx, sy
    o.append(f'<g opacity="0"><animate attributeName="opacity" values="1;1;0" keyTimes="0;.82;1" dur="2.6s" fill="freeze"/>'
             f'<rect x="{ox}" y="{oy}" width="{sw}" height="{sh}" fill="#08090c"/>'
             f'<text font-family="{FONT}" x="{ox + sw / 2}" y="{oy + 200}" text-anchor="middle" font-size="13" fill="#fff" fill-opacity=".55">Choose a startup system</text>')
    for k, (lab, xx) in enumerate((('Android', ox + 40), ('iOS', ox + sw - 130))):
        o.append(f'<rect x="{xx}" y="{oy + 230}" width="90" height="90" rx="22" fill="#fff" fill-opacity=".1"/>'
                 f'<text font-family="{FONT}" x="{xx + 45}" y="{oy + 345}" text-anchor="middle" font-size="14" font-weight="600" fill="#fff">{lab}</text>')
    o.append(f'<rect x="{ox + 33}" y="{oy + 223}" width="104" height="104" rx="28" fill="none" stroke="#fff" stroke-width="3">'
             f'<animate attributeName="x" values="{ox + 33};{ox + 33};{ox + sw - 137};{ox + sw - 137}" keyTimes="0;.35;.5;1" dur="2.2s" fill="freeze"/></rect>'
             f'<rect x="{ox + sw / 2 - 66}" y="{oy + 390}" width="132" height="30" rx="15" fill="#fff" fill-opacity=".12"/>'
             f'<text font-family="{FONT}" x="{ox + sw / 2}" y="{oy + 410}" text-anchor="middle" font-size="12" fill="#fff">Starting iOS</text></g>')
    o.append('</g>')
    # punch-hole camera above everything
    o.append(f'<circle cx="{x + w / 2}" cy="{y + 34}" r="9" fill="#000"/><circle cx="{x + w / 2}" cy="{y + 34}" r="3.5" fill="#1c2a3a"/>')
    o.append('</g>')
    return '\n'.join(o)


def hero(pct, data):
    rows = data['_rows']
    stats = data.get('hero') or data['stats'][:3]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 720" role="img" aria-label="iOS 26 on Pixel 10 Pro: {pct} percent of reachable hardware">',
           f'<defs>{GRADIENT}',
           '<linearGradient id="wall" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b1f4b"/><stop offset=".55" stop-color="#3a1458"/><stop offset="1" stop-color="#5b0f2e"/></linearGradient>',
           '<radialGradient id="orb1"><stop offset="0" stop-color="#5e5ce6" stop-opacity=".85"/><stop offset="1" stop-color="#5e5ce6" stop-opacity="0"/></radialGradient>',
           '<radialGradient id="orb2"><stop offset="0" stop-color="#ff375f" stop-opacity=".7"/><stop offset="1" stop-color="#ff375f" stop-opacity="0"/></radialGradient>',
           '<radialGradient id="halo" cx=".27" cy=".5" r=".45"><stop offset="0" stop-color="#5e5ce6" stop-opacity=".35"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>',
           '<linearGradient id="t" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#a1a1a6"/></linearGradient></defs>',
           '<rect width="1200" height="720" rx="32" fill="#000"/>',
           '<rect width="1200" height="720" rx="32" fill="url(#halo)"><animate attributeName="opacity" values=".7;1;.7" dur="7s" repeatCount="indefinite"/></rect>',
           phone(170, 40, pct, rows)]
    L = 548
    def left(x, y, size, fill, body, delay, weight=400, spacing=0):
        extra = f' letter-spacing="{spacing}"' if spacing else ''
        return f'<text font-family="{FONT}" x="{x}" y="{y}" font-size="{size}" font-weight="{weight}"{extra} fill="{fill}">{body}{rise(delay)}</text>'
    out += [left(L, 180, 21, '#bf5af2', 'Pixel 10 Pro · Tensor G5', .2, 600),
            left(L, 252, 64, 'url(#t)', 'iOS 26.', .35, 700, -1.5),
            left(L, 322, 64, 'url(#t)', 'On a Pixel.', .5, 700, -1.5),
            left(L, 376, 20, '#86868b', 'Apple’s open-source XNU and iOS 26’s own', .7),
            left(L, 404, 20, '#86868b', 'userland, booting natively on Tensor G5,', .75),
            left(L, 432, 20, '#86868b', 'driver by driver — right next to Android.', .8)]
    for i, s in enumerate(stats):
        cx = L + i * 196
        unit = f'<tspan font-size="20" font-weight="600" dx="4">{escape(s["unit"])}</tspan>' if s.get('unit') else ''
        out.append(f'<g>{rise(1.0 + i * .12)}<rect x="{cx}" y="470" width="172" height="118" rx="22" fill="#1c1c1e"/>'
                   f'<text font-family="{FONT}" x="{cx + 20}" y="528" font-size="{40 if len(s["value"]) <= 3 else 34}" font-weight="700" fill="url(#g)">{escape(s["value"])}{unit}</text>'
                   f'<text font-family="{FONT}" x="{cx + 20}" y="562" font-size="13" fill="#f5f5f7">{escape(s["label"][:24])}</text></g>')
    out.append(left(L, 640, 15, '#636366', f'Research bring-up · {pct}% of reachable hardware · {escape(data["updated"])}', 1.5))
    out.append('</svg>\n')
    return '\n'.join(out)


def blocks_svg(rows):
    """Every hardware block as an app-style icon with a progress ring, on a dark home screen."""
    cols, cw, chh = 7, 160, 196
    n = len(rows)
    h = 70 + chh * ((n + cols - 1) // cols)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {h}" role="img" aria-label="Progress by hardware block"><defs>{GRADIENT}</defs>',
           f'<rect width="1200" height="{h}" rx="32" fill="#000"/>']
    x0 = (1200 - cols * cw) / 2
    for i, (name, pct, _) in enumerate(rows):
        cx = x0 + (i % cols) * cw + cw / 2
        cy = 110 + (i // cols) * chh
        out_of_reach = pct is None
        tint = '#3a3a3c' if out_of_reach else TINT[i % len(TINT)]
        d = .15 + i * .07
        g = GLYPH.get(name, '')
        out.append(f'<g transform="translate({cx} {cy})"><g>{pop(0, 0, d)}'
                   f'{ring(0, 0, 54, 6, 0 if out_of_reach else pct, tint, d + .3, "#1c1c1e")}'
                   f'<rect x="-36" y="-36" width="72" height="72" rx="18" fill="{tint}" fill-opacity="{.35 if out_of_reach else 1}"/>'
                   f'<rect x="-36" y="-36" width="72" height="36" rx="18" fill="#fff" fill-opacity=".13"/>'
                   f'<path d="{g}" transform="translate(-24 -24) scale(.48)" fill="none" stroke="#fff" stroke-opacity="{.5 if out_of_reach else 1}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
                   f'</g></g>')
        label = 'out of reach' if out_of_reach else f'{pct}%'
        out.append(f'<text font-family="{FONT}" x="{cx}" y="{cy + 84}" text-anchor="middle" font-size="16" font-weight="600" fill="{"#636366" if out_of_reach else "#f5f5f7"}">{escape(name)}{rise(d + .2, .8)}</text>')
        out.append(f'<text font-family="{FONT}" x="{cx}" y="{cy + 106}" text-anchor="middle" font-size="14" fill="{"#48484a" if out_of_reach else "#86868b"}">{label}{rise(d + .3, .8)}</text>')
    out.append('</svg>\n')
    return '\n'.join(out)


def stats_svg(stats):
    """Measured figures as iOS-style widgets."""
    cols, cw, ch = 3, 376, 176
    rows_n = (len(stats) + cols - 1) // cols
    h = 24 + ch * rows_n
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {h}" role="img" aria-label="Measured on the phone"><defs>{GRADIENT}</defs>']
    x0 = (1200 - cols * cw) / 2
    for i, s in enumerate(stats):
        x, y = x0 + cw * (i % cols) + 8, 12 + ch * (i // cols)
        unit = f'<tspan font-size="26" font-weight="600" dx="6">{escape(s["unit"])}</tspan>' if s.get('unit') else ''
        d = .1 + i * .1
        out.append(f'<g>{rise(d, .9)}<rect x="{x}" y="{y}" width="{cw - 16}" height="{ch - 16}" rx="28" fill="#1c1c1e"/>'
                   f'<text font-family="{FONT}" x="{x + 28}" y="{y + 40}" font-size="13" font-weight="600" letter-spacing="1" fill="#86868b">{escape(s["label"].upper()[:30])}</text>'
                   f'<text font-family="{FONT}" x="{x + 28}" y="{y + 100}" font-size="56" font-weight="700" letter-spacing="-1.5" fill="url(#g)">{escape(s["value"])}{unit}</text>'
                   f'<text font-family="{FONT}" x="{x + 28}" y="{y + 134}" font-size="14" fill="#636366">{escape(s["note"][:44])}</text></g>')
    out.append('</svg>\n')
    return '\n'.join(out)


def badge(label, value, colour):
    """A flat static badge. Local files, so a private repo's README asks no outside service for an image."""
    lw, vw = 6 * len(label) + 12, 6 * len(value) + 12
    w = lw + vw
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{escape(label)}: {escape(value)}">'
            f'<clipPath id="r"><rect width="{w}" height="20" rx="4"/></clipPath><g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#1c1c1e"/>'
            f'<rect x="{lw}" width="{vw}" height="20" fill="{colour}"/></g>'
            f'<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="10" text-anchor="middle">'
            f'<text x="{lw / 2}" y="14">{escape(label)}</text><text x="{lw + vw / 2}" y="14">{escape(value)}</text></g></svg>\n')


def badges(pct):
    """Name, label, value, colour. Progress comes from status.json; the rest are plain facts about the repo."""
    return (('progress', 'progress', f'{pct}%', '#5e5ce6'), ('target', 'device', 'Pixel 10 Pro', '#1c1c1e'),
            ('software', 'running', 'XNU 12377 · iOS 26', '#1c1c1e'))


def roadmap(data):
    lines = [ROADMAP_BEGIN, '']
    for stage in data['roadmap']:
        lines += [f'**{stage["stage"]}**', ''] + [f'- {item}' for item in stage['items']] + ['']
    out = [f[0] for b in data['blocks'] for f in b['features'] if f[1] == 'out']
    lines += ['**Likely out of reach**', '', '- ' + ', '.join(out), '', ROADMAP_END]
    return '\n'.join(lines)


def splice(readme, begin, end, block):
    head, rest = readme.split(begin, 1)
    return head + block + rest.split(end, 1)[1]


def markdown(data, pct, rows, feats):
    legend = ' · '.join(f'{ICON[k]} {WORD[k]} {sum(1 for f in feats if f[1] == k)}' for k in ICON)
    lines = [BEGIN, '', '<p align="center"><img src="docs/assets/hero.svg" alt="iOS 26 on Pixel 10 Pro: ' + f'{pct}% of reachable hardware" width="100%"></p>', '',
             '<p align="center">' + ' '.join(f'<img src="docs/assets/badge-{n}.svg" alt="{l}: {v}">' for n, l, v, _ in badges(pct)) + '</p>',
             '<p align="center">' + ' · '.join(f'<a href="#{a}">{t}</a>' for t, a in NAV) + '</p>', '',
             '<p align="center"><img src="docs/assets/stats.svg" alt="Measured on the phone" width="100%"></p>', '',
             '<a id="progress"></a>', '<h2 align="center">Every block. Tracked.</h2>',
             f'<p align="center"><b>{pct}%</b> of {sum(1 for f in feats if f[1] != "out")} reachable features · updated {data["updated"]}</p>', '',
             '<p align="center"><img src="docs/assets/blocks.svg" alt="Progress by hardware block" width="100%"></p>', '',
             f'<p align="center"><sub>{legend}</sub></p>', '',
             '<details><summary><b>Every feature</b></summary>', '', '| Block | Feature | Status |', '| --- | --- | --- |']
    for block in data['blocks']:
        for i, (name, status, note) in enumerate(block['features']):
            head = f'**{block["name"]}**' if i == 0 else ''
            text = f'{ICON[status]} {note}'.rstrip()
            lines.append(f'| {head} | {name} | {text} |')
    lines += ['', '<sub>Scores: ' + ', '.join(f'{WORD[k].lower()} {data["scores"][k]}%' for k in ICON if data["scores"][k] is not None) +
              '. A planning estimate, not a benchmark. Rebuild with `python3 -I tools/readme_status.py` after editing `docs/status.json`.</sub>', '',
              '</details>', '',
              '> **What this is.** An experimental research bring-up on the owner\'s own phone, not a product. Not affiliated with or endorsed by Apple or Google. '
              'No Apple software or firmware is distributed here. Apple\'s security model is largely switched off, so the phone isn\'t safe for real data.', '', END]
    return '\n'.join(lines)


def main():
    data = json.loads((ROOT / 'docs/status.json').read_text())
    scores = data['scores']
    feats = [f for b in data['blocks'] for f in b['features']]
    pct = percent(feats, scores)
    rows = [(b['name'], percent(b['features'], scores), len(b['features'])) for b in data['blocks']]
    data['_rows'] = rows
    files = {'docs/assets/hero.svg': hero(pct, data), 'docs/assets/blocks.svg': blocks_svg(rows), 'docs/assets/stats.svg': stats_svg(data['stats'])}
    files.update({f'docs/assets/badge-{n}.svg': badge(l, v, c) for n, l, v, c in badges(pct)})
    readme = (ROOT / 'README.md').read_text()
    block = markdown(data, pct, rows, feats)
    new = splice(readme, BEGIN, END, block) if BEGIN in readme else block + '\n\n---\n\n' + readme
    if ROADMAP_BEGIN in new:
        new = splice(new, ROADMAP_BEGIN, ROADMAP_END, roadmap(data))
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
