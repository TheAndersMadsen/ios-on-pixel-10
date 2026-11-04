#!/usr/bin/env python3
"""A strict, stdlib-only reader for the YAML subset the repo's declarative files use (adt/*.yaml).

Supported: block mappings, block sequences (`- ` items, including `- key: value` mapping items), flow
sequences of scalars (`[a, 0x10, "b c"]`), `#` comments, plain/single/double-quoted scalars, ints
(decimal, 0x hex), true/false/null. Everything else (tabs, anchors, aliases, tags, multi-line
scalars, flow mappings, multiple documents) is refused with the line number, so a file never means
something other than what it looks like.

  miniyaml.py FILE      print the parsed value as JSON
"""
import json, re, sys


class YAMLError(ValueError):
    pass


_INT = re.compile(r'[-+]?(0x[0-9a-fA-F_]+|[0-9][0-9_]*)$')
_KEY = re.compile(r'''((?:"(?:[^"\\]|\\.)*")|(?:'(?:[^']|'')*')|[^\s"'#:\[\]{},&*!|>][^:#]*?)\s*:(?:\s+|$)''')


def _strip_comment(s):
    out, q, esc = [], None, False
    for i, ch in enumerate(s):
        if q:
            if esc:
                esc = False
            elif q == '"' and ch == '\\':
                esc = True
            elif ch == q:
                q = None
        elif ch in '"\'':
            q = ch
        elif ch == '#' and (i == 0 or s[i - 1] in ' \t'):
            break
        out.append(ch)
    if q:
        raise YAMLError('unterminated quote')
    return ''.join(out).rstrip()


def scalar(tok, ln=0):
    t = tok.strip()
    if not t:
        return None
    if t[0] == '"':
        if len(t) < 2 or t[-1] != '"':
            raise YAMLError(f'line {ln}: bad double-quoted scalar {t!r}')
        return json.loads(t)
    if t[0] == "'":
        if len(t) < 2 or t[-1] != "'":
            raise YAMLError(f'line {ln}: bad single-quoted scalar {t!r}')
        return t[1:-1].replace("''", "'")
    if t[0] == '[':
        if t[-1] != ']':
            raise YAMLError(f'line {ln}: flow sequence must close on its line')
        body = t[1:-1].strip()
        if not body:
            return []
        items, cur, q = [], '', None
        for ch in body:
            if q:
                cur += ch
                if ch == q:
                    q = None
            elif ch in '"\'':
                q = ch
                cur += ch
            elif ch in '[]{}':
                raise YAMLError(f'line {ln}: nested flow collections are not supported')
            elif ch == ',':
                items.append(cur)
                cur = ''
            else:
                cur += ch
        items.append(cur)
        return [scalar(i, ln) for i in items]
    if t[0] in '{&*!|>%@`':
        raise YAMLError(f'line {ln}: unsupported YAML construct {t[:20]!r}')
    if t in ('true', 'True'):
        return True
    if t in ('false', 'False'):
        return False
    if t in ('null', '~', 'Null'):
        return None
    if _INT.match(t):
        return int(t.replace('_', ''), 0)
    if ': ' in t or t.endswith(':'):
        raise YAMLError(f'line {ln}: ambiguous plain scalar {t!r}: quote it')
    return t


def _lines(text):
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        if '\t' in raw[:len(raw) - len(raw.lstrip())]:
            raise YAMLError(f'line {n}: tab indentation')
        try:
            s = _strip_comment(raw)
        except YAMLError as e:
            raise YAMLError(f'line {n}: {e}')
        if not s.strip():
            continue
        if s.strip() in ('---', '...'):
            if out:
                raise YAMLError(f'line {n}: one document per file')
            continue
        out.append((n, len(s) - len(s.lstrip(' ')), s.strip()))
    return out


def loads(text):
    lines = _lines(text)
    if not lines:
        return None
    val, i = _block(lines, 0, lines[0][1])
    if i != len(lines):
        n, ind, _ = lines[i]
        raise YAMLError(f'line {n}: unexpected indentation {ind}')
    return val


def _split_key(s, ln):
    m = _KEY.match(s)
    if not m:
        return None
    k = m.group(1).strip()
    key = scalar(k, ln) if k[0] in '"\'' else k
    return key, s[m.end():]


def _block(lines, i, ind):
    n, cur, s = lines[i]
    if s.startswith('- ') or s == '-':
        return _seq(lines, i, ind)
    if _split_key(s, n) is not None:
        return _map(lines, i, ind)
    if i + 1 < len(lines) and lines[i + 1][1] > ind:
        raise YAMLError(f'line {n}: multi-line scalars are not supported')
    return scalar(s, n), i + 1


def _value(lines, i, ind, rest, n):
    """Value after 'key:' or '- ': inline scalar, or a nested block on the following lines."""
    if rest.strip():
        return scalar(rest, n), i + 1
    if i + 1 < len(lines) and lines[i + 1][1] > ind:
        return _block(lines, i + 1, lines[i + 1][1])
    # a block sequence may sit at the parent key's indentation (common YAML style)
    if i + 1 < len(lines) and lines[i + 1][1] == ind and lines[i + 1][2].startswith('-'):
        return _seq(lines, i + 1, ind)
    return None, i + 1


def _map(lines, i, ind):
    out = {}
    while i < len(lines):
        n, cur, s = lines[i]
        if cur < ind:
            break
        if cur > ind:
            raise YAMLError(f'line {n}: unexpected indentation {cur} (expected {ind})')
        kv = _split_key(s, n)
        if kv is None:
            if s.startswith('-'):
                break
            raise YAMLError(f'line {n}: expected "key: value", got {s[:40]!r}')
        key, rest = kv
        if key in out:
            raise YAMLError(f'line {n}: duplicate key {key!r}')
        out[key], i = _value(lines, i, ind, rest, n)
    return out, i


def _seq(lines, i, ind):
    out = []
    while i < len(lines):
        n, cur, s = lines[i]
        if cur != ind or not (s.startswith('- ') or s == '-'):
            if cur > ind:
                raise YAMLError(f'line {n}: unexpected indentation {cur}')
            break
        body = s[1:].lstrip(' ')
        if not body:
            v, i = _value(lines, i, ind, '', n)
            out.append(v)
            continue
        sub = ind + (len(s) - len(body))
        if _split_key(body, n) is not None:
            # "- key: v" starts a mapping whose keys are indented to `sub`
            lines[i] = (n, sub, body)
            v, i = _map(lines, i, sub)
            out.append(v)
        else:
            out.append(scalar(body, n))
            i += 1
    return out, i


def load(path):
    with open(path, encoding='utf-8') as f:
        try:
            return loads(f.read())
        except YAMLError as e:
            raise YAMLError(f'{path}: {e}') from None


if __name__ == '__main__':
    print(json.dumps(load(sys.argv[1]), indent=1))
