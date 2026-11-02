#!/usr/bin/env python3
"""Decode hackios live console captures without reordering or guessing timestamps.

    python3 -I tools/live_profile.py --raw X.raw --manifest IMAGE/manifest.json --json report.json
    python3 -I tools/live_profile.py --raw X.raw --follow --events --json report.json
    python3 -I tools/live_profile.py --dump ATTEMPT/ramdump/kernel.log --json report.json

--raw uses usbcon.py's .times as a committed byte-range journal (including holes).
--follow tails that journal; it never opens USB. --dump reconstructs only the
current header's stream from the first-MiB console and last-MiB ring. No text
deduplication, launchd wall-clock interpolation, weighted phase CPU, or FPS claims.
All output files and cache/disassembly sources stay local; don't commit dumps or
Apple disassembly. Standard library only. See tools/live_profile.md.
"""
import argparse
import bisect
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import time


HDR_OFF, RING_OFF = 0x23f800, 0x240000
MIRROR = struct.Struct('<16sIIQQIIQII')
ENTRY = struct.Struct('<8sQQQQIIQQ')
CONSOLE = struct.Struct('<III')
STAGE0 = b'TEGU-XNU STAGE0\n'
TOP = re.compile(r'HK TOP: t=(\d+) frames\+(\d+) cpu_ms=(\d+):((?: [^\s\[\]=]+\[\d+\]=\d+)*)')
TASK = re.compile(r' ([^\s\[\]=]+)\[(\d+)\]=(\d+)')
TRACE = re.compile(r'HK UITRACE token seq=(\d+) event=(\d+) tok=(\d+) op=([a-z]) callback_us=(\d+) begin_us=(\d+) end_us=(\d+) late_us=(\d+)$')
DONE = re.compile(r'HK UITRACE done us=(\d+) events=(\d+) tokens=(\d+) max_late_us=(\d+) max_call_us=(\d+) drift_us=(\d+)$')
PRESENT_EVENT = re.compile(r'HK PRESENT event v=1 seq=(\d+) us=(\d+) stage=(layer_copy|copy_refused|copy_aggregate|submitted|submit_not_ok|unavailable|fetch_layer0|fetch_unproved|stop_unproved) id=(\d+) swap=(\d+) gen=(\d+) queue_us=(\d+) begin_us=(\d+) bytes=(\d+) layer=(\d+) plane=(\d+) rc=(-?\d+) status=(\d+) fe=(\d+) observed=(\d+)$')
PRESENT_COUNTER_KEYS = ('seq us queued selected copy_ops copy_bytes copy_refused copy_aggregates submitted fetch_done uncertain unavailable submit_not_ok event_drops events reports pending').split()
PRESENT_COUNTERS = re.compile(r'HK PRESENT counters v=1 ' + ' '.join(k + r'=(\d+)' for k in PRESENT_COUNTER_KEYS) + '$')
PRESENT_CONFIG = re.compile(r'HK PRESENT config v=1 us=(\d+) every=(\d+) events_max=(\d+) reports_max=(\d+) clock=mach_absolute_us glass=unavailable$')
HOG = re.compile(r'HK HOG: (\S+)\[(\d+)\] s=(\d+) tid=(\d+) x16=(-?\d+) pc=(0x[0-9a-f]+) lr=(0x[0-9a-f]+) slide=(0x[0-9a-f]+) main=(0x[0-9a-f]+):((?: 0x[0-9a-f]+)*)$')
CRASH = re.compile(r'(userabort|usercrash|usertrap): ([^\s\[]+)\[(\d+)\]')
EXEC = re.compile(r'(?:^|\s)exec ([^\s/]+)$')
SPAWN = re.compile(r'Successfully spawned ([^\s\[]+)\[(\d+)\]')
EXIT = re.compile(r'\((?:[^\s()]*/)?([^/\s()]+) \[(\d+)\]\).*exited due to (.+)$')
UI_START = re.compile(r'HK UI: (\d+) tokens, start in (\d+) s$')
PERF = re.compile(r'(?:blazer-perf|HK VM): t=(\d+)\b')


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def repo_path():
    for p in (Path.cwd(), *Path(__file__).resolve().parents):
        if (p / 'AGENTS.md').is_file() and (p / 'tools/usbcon.py').is_file():
            return p
    return Path.cwd()


def decode_dump(path, expected=None):
    """Canonical disjoint stream ranges and the epoch from tegu_early.c's v2 header."""
    raw = Path(path).read_bytes()
    if len(raw) < RING_OFF:
        raise ValueError('dump truncated before mirror header/ring')
    magic, seq, flags, _, _, size, write, total, off, length = MIRROR.unpack_from(raw, HDR_OFF)
    if magic.rstrip(b'\0') != b'XNU-MSGBUF v2':
        raise ValueError('no current XNU-MSGBUF v2 header')
    if not (0 < size <= 0x100000 and length == min(size, total) and off < size
            and off == (total - length) % size and write == total % size):
        raise ValueError('inconsistent mirror size/write/total/tail')
    if len(raw) < RING_OFF + size:
        raise ValueError('dump truncated inside physical ring')
    emagic, nonce, entry, _, hz, eflags, _, _, _ = ENTRY.unpack_from(raw, HDR_OFF + 0x40)
    if emagic.rstrip(b'\0') != b'XNUENT1' or eflags & 7 != 7 or not hz:
        raise ValueError('current XNUENT1 epoch is unavailable')
    epoch = dict(nonce=nonce, entry_t=entry, hz=hz)
    if expected and any(expected[k] != epoch[k] for k in epoch):
        raise ValueError('raw/dump boot epoch mismatch')
    ring = raw[RING_OFF:RING_OFF + size]
    tail = (ring[off:] + ring[:off])[:length]
    first = total - length
    segments = [(first, tail)] if tail else []
    sig, start, used = CONSOLE.unpack_from(raw)
    head = b''
    if sig == 0x43474244:
        if start != used or used > 0x100000 - CONSOLE.size or CONSOLE.size + used > len(raw):
            raise ValueError('invalid nonwrapping RAM console length')
        console = raw[CONSOLE.size:CONSOLE.size + used]
        if console.startswith(STAGE0):
            head = console[len(STAGE0):]
    overlap = max(0, min(len(head), total) - first)
    if head and overlap:
        if head[first:first + overlap] != tail[:overlap]:
            raise ValueError('head/ring overlap mismatch: stale or inconsistent dump')
        # Drop overlap by position, never by line text.
        segments = [(0, head[:first]), (first, tail)] if first else [(0, tail)]
    elif head and first == 0:
        raise ValueError('head/ring cannot be reconciled')
    # Without overlap, the RAM console has no independently proved epoch. Keep
    # only the epoch-framed tail; never join a possibly stale head to it.
    segments = [(off, data) for off, data in segments if data]
    return segments, dict(epoch=epoch, total=total, ring_from=first, ring_size=size,
                          overlap_verified=overlap, unproved_head_omitted=bool(head and not overlap),
                          header_seq=seq, header_flags=flags)


class Journal:
    """Incremental reader for the write-raw/flush/write-times/flush protocol."""
    def __init__(self, raw, times=None):
        self.raw, self.path = Path(raw), Path(times or str(raw) + '.times')
        self.pos, self.end, self.host, self.reads, self.bytes = 0, 0, -1.0, 0, 0
        self.identity = None
        self.prefix = b''
        self.ranges = []

    def poll(self, final=False):
        if not self.raw.exists() or not self.path.exists():
            if final:
                raise ValueError('raw and .times journal are both required')
            return []
        stat, ts = self.raw.stat(), self.path.stat()
        identity = (stat.st_dev, stat.st_ino, ts.st_dev, ts.st_ino)
        if self.identity is not None and (identity != self.identity or ts.st_size < self.pos or stat.st_size < self.end):
            raise ValueError('capture replaced/truncated while following; start a new reader for a new epoch')
        self.identity = identity
        out = []
        with self.raw.open('rb') as data, self.path.open('rb') as journal:
            if self.prefix:
                data.seek(self.prefix_off)
                if data.read(len(self.prefix)) != self.prefix:
                    raise ValueError('capture prefix changed while following; epoch replacement')
            journal.seek(self.pos)
            while True:
                line = journal.readline()
                if not line:
                    break
                if not line.endswith(b'\n'):
                    if final:
                        raise ValueError('truncated .times record (missing newline)')
                    break
                try:
                    t, off, length = line.split()
                    t, off, length = float(t), int(off), int(length)
                except (ValueError, OverflowError):
                    raise ValueError('malformed .times record') from None
                if not math.isfinite(t) or t < 0 or t < self.host or off < self.end or not 0 < length <= 1048576:
                    raise ValueError('nonmonotonic/overlapping/invalid .times record; refusing epoch merge')
                if off + length > stat.st_size:
                    if final:
                        raise ValueError('raw file truncated relative to committed .times bytes')
                    break
                data.seek(off)
                payload = data.read(length)
                if len(payload) != length:
                    raise ValueError('raw file changed during read')
                if not self.prefix:
                    self.prefix, self.prefix_off = payload[:64], off
                out.append((off, payload, t))
                self.pos += len(line)
                self.end, self.host = off + length, t
                self.reads += 1
                self.bytes += length
                self.ranges.append((off, length))
        return out


def script_schedule(value):
    """Expectations only; tested against actual hk_ui_replay.h, not UX evidence."""
    value = value.removeprefix('hk_ui=')
    match = re.fullmatch(r'([0-9]+):(.+)', value)
    if not match or not 1 <= int(match[1]) <= 3600:
        raise ValueError('invalid hk_ui delay')
    raw = match[2].split(',')
    if len(raw) > 32:
        raise ValueError('too many hk_ui tokens')
    expanded, forms = [], []
    for i, token in enumerate(raw):
        op, duration, events = token[:1], 0, 0
        if token in ('h', 'p'):
            duration, events = 1100, 2
        elif token in ('u', 'd', 'l', 'r', 's', 'v'):
            duration, events = 1400, 26
        elif re.fullmatch(r'w[0-9]+', token) and 1 <= int(token[1:]) <= 600:
            duration, events = int(token[1:]) * 1000, 1
        elif re.fullmatch(r't[0-9]+\.[0-9]+', token):
            x, y = map(int, token[1:].split('.'))
            if not (x < 1125 and y < 2511):
                raise ValueError('hk_ui tap outside current canvas')
            duration, events = 1060, 2
        elif re.fullmatch(r'x[0-9]+\.[0-9]+', token):
            group, repeat = map(int, token[1:].split('.'))
            if not (1 <= group <= min(8, i) and 1 <= repeat <= 200) or any(f[1] == 'x' for f in forms[-group:]):
                raise ValueError('invalid hk_ui repeat')
            expanded.extend(forms[-group:] * repeat)
            forms.append((i, op, 0, 0))
            continue
        else:
            raise ValueError('invalid hk_ui token: ' + token)
        form = (i, op, duration, events)
        forms.append(form)
        expanded.append(form)
    result, ms, event = [], 0, 0
    for tok, op, duration, count in expanded:
        result.append(dict(seq=len(result), tok=tok, op=op, event=event, nominal_ms=ms))
        ms, event = ms + duration, event + count
    return dict(value='hk_ui=' + value, delay_s=int(match[1]), parsed_tokens=len(raw),
                executions=result, events=event, duration_ms=ms)


class CacheImages:
    """Read just headers/load commands. No extraction, .symbols dependency or mmap."""
    def __init__(self, path):
        self.path = Path(path)
        head = self.path.read_bytes()
        if not head.startswith(b'dyld_v1') or len(head) < 0x1c8:
            raise ValueError('unsupported dyld cache header')
        self.uuid = head[0x58:0x68].hex()
        self.maps, self.handles = [], []
        suboff, count = struct.unpack_from('<II', head, 0x188)
        if count > 256 or suboff + count * 56 > len(head):
            raise ValueError('invalid v2 subcache table')
        paths = [self.path]
        for i in range(count):
            suffix = head[suboff + i * 56 + 24:suboff + i * 56 + 56].split(b'\0')[0].decode('ascii')
            if not re.fullmatch(r'\.[0-9]+(?:\.(?:data|dylddata|dyldreadonly|dyldlinkedit))?', suffix):
                raise ValueError('unsupported subcache suffix')
            paths.append(Path(str(self.path) + suffix))
        try:
            for path in paths:
                source = path.open('rb')
                self.handles.append(source)
                header = source.read(0x4000)
                mo, mc = struct.unpack_from('<II', header, 0x10)
                if not header.startswith(b'dyld_v1') or mc > 64 or mo + mc * 32 > len(header):
                    raise ValueError('invalid subcache mappings')
                for j in range(mc):
                    addr, size, fileoff = struct.unpack_from('<QQQ', header, mo + j * 32)
                    if fileoff + size > os.fstat(source.fileno()).st_size:
                        raise ValueError('subcache mapping exceeds file')
                    self.maps.append((addr, addr + size, fileoff, source))
            self.maps.sort(key=lambda row: row[0])
            self.starts = [row[0] for row in self.maps]
            io, ic = struct.unpack_from('<II', head, 0x1c0)
            if ic > 20000 or io + ic * 32 > len(head):
                raise ValueError('invalid cache image table')
            self.images = []
            for i in range(ic):
                addr, _, _, po, _ = struct.unpack_from('<QQQII', head, io + 32 * i)
                end = head.find(b'\0', po)
                if po >= len(head) or end < po:
                    raise ValueError('invalid cache image path')
                self.images.append((addr, head[po:end].decode('utf-8')))
            self.images.sort()
            self.image_starts = [row[0] for row in self.images]
            self.segments = {}
        except BaseException:
            self.close()
            raise

    def close(self):
        for source in self.handles:
            source.close()

    def read(self, addr, length):
        i = bisect.bisect_right(self.starts, addr) - 1
        if i < 0 or addr + length > self.maps[i][1]:
            raise ValueError('address outside cache mapping')
        base, _, offset, source = self.maps[i]
        source.seek(offset + addr - base)
        data = source.read(length)
        if len(data) != length:
            raise ValueError('truncated mapped cache bytes')
        return data

    def who(self, addr):
        i = bisect.bisect_right(self.image_starts, addr) - 1
        if i < 0:
            return None
        base, path = self.images[i]
        if base not in self.segments:
            header = self.read(base, 32)
            magic, _, _, _, nc, size, _, _ = struct.unpack('<IiiIIIII', header)
            if magic != 0xfeedfacf or nc > 1000 or size > 1024 * 1024:
                raise ValueError('invalid cached Mach-O header')
            commands, off, segments = self.read(base + 32, size), 0, []
            for _ in range(nc):
                if off + 8 > len(commands):
                    raise ValueError('truncated Mach-O command')
                cmd, cs = struct.unpack_from('<II', commands, off)
                if cs < 8 or off + cs > len(commands):
                    raise ValueError('invalid Mach-O command')
                if cmd == 0x19 and cs >= 72:
                    name = commands[off + 8:off + 24].split(b'\0')[0].decode('ascii')
                    vm, length, _, _, _, prot = struct.unpack_from('<QQQQii', commands, off + 24)
                    if prot & 4:
                        segments.append((vm, vm + length, name))
                off += cs
            self.segments[base] = segments
        for begin, end, segment in self.segments[base]:
            if begin <= addr < end:
                return dict(image=path, segment=segment, image_offset=addr - base)
        return None


class Labels:
    def __init__(self, path):
        self.path, self.rows = Path(path), []
        label, start, end, position = None, None, None, None
        with self.path.open() as source:
            while True:
                line_pos = source.tell()
                line = source.readline()
                if not line:
                    break
                match = re.match(r'^0x([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{2} ){3}[0-9a-fA-F]{2}\s', line)
                if match:
                    addr = int(match[1], 16)
                    if label is not None:
                        position = line_pos if start is None else position
                        start = addr if start is None else start
                        end = addr + 4
                elif line.strip() and line.rstrip().endswith(':') and not line.startswith('0x'):
                    if start is not None:
                        self.rows.append((start, end, label, position))
                    label, start, end = line.rstrip()[:-1], None, None
        if start is not None:
            self.rows.append((start, end, label, position))
        self.rows.sort()
        self.starts = [row[0] for row in self.rows]

    def lookup(self, addr):
        i = bisect.bisect_right(self.starts, addr) - 1
        if i >= 0 and addr < self.rows[i][1]:
            start, end, name, position = self.rows[i]
            with self.path.open() as source:
                source.seek(position)
                for line in source:
                    match = re.match(r'^0x([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2} ){3}[0-9a-fA-F]{2})\s', line)
                    if match and int(match[1], 16) == addr:
                        return dict(symbol=name, symbol_start=hex(start), symbol_end=hex(end),
                                    symbol_offset=addr - start, instruction_hex=bytes.fromhex(match[2]).hex())
                    if match and int(match[1], 16) > addr:
                        break
        return None


class Symbols:
    def __init__(self, cache=None, disassembly=None):
        self.cache = CacheImages(cache) if cache else None
        try:
            self.labels = Labels(disassembly) if disassembly else None
        except BaseException:
            self.close()
            raise
        self.memo = {}

    def close(self):
        if self.cache:
            self.cache.close()

    def resolve(self, addr, slide, main):
        key = addr, slide, main
        if key in self.memo:
            return self.memo[key]
        result = dict(address=hex(addr), status='unresolved')
        if addr:
            unslid = addr - slide
            info = self.cache.who(unslid) if self.cache and unslid >= 0 else None
            if info:
                result.update(info, unslid=hex(unslid), status='cache_image_only')
                if self.labels and info['image'].endswith('/QuartzCore'):
                    label = self.labels.lookup(unslid)
                    if label and self.cache.read(unslid, 4).hex() == label['instruction_hex']:
                        result.update(label, status='disassembly_label', label_source=str(self.labels.path),
                                      label_validation='instruction bytes at this address match current cache')
                    elif label:
                        result['label_rejected'] = 'instruction bytes differ from current cache'
            elif main and main <= addr < 0x180000000:
                result.update(status='main_relative_unresolved', main_offset=hex(addr - main))
        self.memo[key] = result
        return result


class Analyzer:
    def __init__(self, symbols=None, schedule=None, emit=None):
        self.symbols, self.schedule, self.emit = symbols, schedule, emit
        self.records, self.gaps, self.warnings = [], [], []
        self.pending, self.pending_off, self.end, self.discard = b'', 0, 0, False
        self.period, self.tops, self.tokens, self.done = None, [], [], None
        self.ui_start, self.last_anchor_low, self.epoch_starts = None, None, 0
        self.present_seqs, self.present_config = set(), None

    def feed(self, off, data, host=None):
        if off < self.end:
            raise ValueError('overlapping input bytes')
        if off != self.end:
            self.gaps.append(dict(start=self.end, end=off, bytes=off - self.end))
            self.pending, self.discard = b'', True
        self.end = off + len(data)
        if not self.pending:
            self.pending_off = off
        buffer = self.pending + data
        at = self.pending_off
        while b'\n' in buffer:
            line, buffer = buffer.split(b'\n', 1)
            length = len(line) + 1
            if self.discard:
                self.discard = False
            else:
                self.line(line.replace(b'\r', b'').decode('utf-8', 'replace'), at, at + length, host)
            at += length
        if len(buffer) > 65536:
            raise ValueError('unterminated console line exceeds 64 KiB')
        self.pending, self.pending_off = buffer, at

    def line(self, text, off, end, host):
        r = dict(offset=off, end_offset=end, host_received_s=host)
        match = TOP.search(text)
        if match:
            t, frames, cpu = map(int, match.group(1, 2, 3))
            if self.tops and t <= self.tops[-1]['kernel_s'][0]:
                raise ValueError('TOP clock moved backwards/repeated: refusing duplicated or foreign-epoch bytes')
            r.update(kind='top', kernel_s=[t, t + 1], frames_delta=frames, cpu_ms=cpu,
                     task_list_complete=not bool(text[match.end():].strip()),
                     tasks=[dict(name=n, pid=int(pid), cpu_ms=int(ms)) for n, pid, ms in TASK.findall(match[4])])
            if not r['task_list_complete']:
                self.warnings.append(dict(offset=off, reason='interleaved TOP: only the intact task prefix is retained'))
            self.tops.append(r)
        elif (match := TRACE.search(text)):
            seq, event, tok, op, cb, begin, finish, late = match.groups()
            r.update(kind='token', seq=int(seq), event=int(event), tok=int(tok), op=op,
                     callback_us=int(cb), begin_us=int(begin), end_us=int(finish), late_us=int(late))
            if not r['callback_us'] <= r['begin_us'] <= r['end_us']:
                raise ValueError('trace callback/begin/end ordering is invalid')
            if self.tokens and (r['seq'] <= self.tokens[-1]['seq'] or r['event'] <= self.tokens[-1]['event']):
                raise ValueError('trace sequence reset/repeated: refusing another epoch or duplicated dump')
            if self.tokens and r['callback_us'] < self.tokens[-1]['end_us']:
                raise ValueError('trace clock moved backwards within the replay thread')
            r['kernel_s'] = [int(cb) / 1e6, int(finish) / 1e6]
            self.tokens.append(r)
        elif (match := DONE.search(text)):
            if self.done:
                raise ValueError('more than one trace completion in this epoch')
            us, events, tokens, late, call, drift = map(int, match.groups())
            r.update(kind='done', kernel_s=[us / 1e6, us / 1e6], us=us, events=events,
                     tokens=tokens, max_late_us=late, max_call_us=call, drift_us=drift)
            if self.tokens and us < self.tokens[-1]['end_us']:
                raise ValueError('trace done clock moved backwards within the replay thread')
            self.done = r
        elif (match := PRESENT_CONFIG.search(text)):
            if self.present_config is not None:
                raise ValueError('second presentation config: refusing duplicated/foreign epoch')
            us, every, events_max, reports_max = map(int, match.groups())
            if (every, events_max, reports_max) != (32, 448, 64):
                raise ValueError('unknown presentation sampling/bounds')
            r.update(kind='present_config', us=us, every=every, events_max=events_max,
                     reports_max=reports_max, clock='mach_absolute_us', glass='unavailable',
                     kernel_s=[us / 1e6, us / 1e6])
            self.present_config = r
        elif (match := PRESENT_EVENT.search(text)):
            names = 'seq us stage id swap gen queue_us begin_us bytes layer plane rc status fe observed'.split()
            fields = dict(zip(names, match.groups()))
            fields = {k: v if k == 'stage' else int(v) for k, v in fields.items()}
            if not fields['id'] or not fields['seq'] or not fields['queue_us'] <= fields['begin_us'] <= fields['us']:
                raise ValueError('invalid presentation identity/observation timestamps')
            if fields['layer'] >= 4 or fields['plane'] > 1 or fields['observed'] not in (0, 1, 3):
                raise ValueError('invalid presentation layer/plane')
            if fields['stage'] in ('submitted', 'fetch_layer0') and (fields['rc'] or not fields['gen']):
                raise ValueError('invalid successful presentation observation')
            if fields['stage'] == 'fetch_layer0' and (fields['observed'] != 3 or not fields['status'] & 2 or not fields['fe'] & 0x40 or fields['fe'] & 0x1f000):
                raise ValueError('presentation fetch lacks existing Layer0 completion evidence')
            if fields['stage'] == 'layer_copy' and (fields['rc'] != 1 or fields['bytes'] == 0):
                raise ValueError('presentation copy lacks successful row-helper evidence')
            r.update(kind='present_event', **fields, kernel_s=[fields['us'] / 1e6] * 2)
        elif (match := PRESENT_COUNTERS.search(text)):
            fields = dict(zip(PRESENT_COUNTER_KEYS, map(int, match.groups())))
            if not fields['seq'] or fields['events'] > 448 or not 1 <= fields['reports'] <= 64:
                raise ValueError('presentation counter bounds violated')
            r.update(kind='present_counters', **fields, kernel_s=[fields['us'] / 1e6] * 2)
        elif (match := HOG.search(text)):
            name, pid, sample, tid, x16, pc, lr, slide, main, frames = match.groups()
            r.update(kind='hog', name=name, pid=int(pid), sample=int(sample), tid=int(tid), x16=int(x16),
                     pc=pc, lr=lr, slide=slide, main=main,
                     following_top_offset=self.tops[-1]['offset'] if self.tops else None)
            addresses = [int(pc, 16), int(lr, 16), *[int(f, 16) for f in frames.split()]]
            r['stack'] = [self.symbols.resolve(a, int(slide, 16), int(main, 16)) if self.symbols
                          else dict(address=hex(a), status='unresolved') for a in addresses]
        elif (match := re.search(r'HK TOP: every (\d+) s$', text)):
            self.epoch_starts += 1
            if self.epoch_starts > 1:
                raise ValueError('second HK TOP start: new boot or duplicated dump')
            self.period = int(match[1])
            r.update(kind='top_start', period_s=self.period)
        elif (match := UI_START.search(text)):
            if self.ui_start:
                raise ValueError('second HK UI start: new boot or duplicated dump')
            r.update(kind='ui_start', parsed_tokens=int(match[1]), delay_s=int(match[2]))
            self.ui_start = r
        elif (match := CRASH.search(text)):
            r.update(kind='crash', reason=match[1], name=match[2], pid=int(match[3]), detail=text)
        elif (match := EXEC.search(text)):
            r.update(kind='exec', name=match[1])
        elif (match := SPAWN.search(text)):
            r.update(kind='spawn', name=match[1], pid=int(match[2]))
        elif (match := EXIT.search(text)):
            r.update(kind='exit', name=match[1], pid=int(match[2]), reason=match[3])
        elif (match := PERF.search(text)):
            t = int(match[1])
            r.update(kind='anchor', kernel_s=[t, t + 1])
        elif 'SWEET FB: display on' in text:
            r.update(kind='display_on')
        elif 'HGLTRACK:' in text:
            r.update(kind='hgltrack', detail=text)
        elif 'panic(cpu' in text:
            r.update(kind='end_marker', termination='deadline_panic' if re.search(r'blazer-root: deadline \d+ s', text) else 'panic', detail=text)
        elif text.startswith('HK UI: refused'):
            r.update(kind='ui_refused')
        elif text.startswith(('HK UITRACE', 'HK HOG:', 'HK TOP:', 'HK PRESENT ')):
            self.warnings.append(dict(offset=off, reason='malformed/interleaved diagnostic line', detail=text))
            return
        else:
            return
        if r['kind'] in ('present_event', 'present_counters'):
            # The trace lock orders observations; it is dropped BEFORE printing.
            # Out-of-order seq is legal, duplicate seq is not. Source byte/epoch
            # validation remains in Journal/dump_ranges, never inferred from IDs.
            if r['seq'] in self.present_seqs:
                raise ValueError('duplicate presentation sequence in this epoch')
            self.present_seqs.add(r['seq'])
        if 'kernel_s' in r:
            low, high = r['kernel_s']
            if self.last_anchor_low is not None and high < self.last_anchor_low:
                self.warnings.append(dict(offset=off, reason='concurrent writers printed kernel timestamps out of order; explicit stamps retained'))
            self.last_anchor_low = max(low, self.last_anchor_low or low)
        self.records.append(r)
        if self.emit:
            self.emit(r)

    def report(self):
        # Record log neighbors only, not guaranteed event-time bounds: another
        # thread can stamp before it prints. Holes break neighbor association.
        records = [dict(r) for r in self.records]
        lower, upper = None, None
        for r in records:
            if lower is not None and any(lower_off <= g['start'] < r['offset'] for g in self.gaps):
                lower = None
            if 'kernel_s' in r:
                lower, lower_off = r['kernel_s'][0], r['end_offset']
            elif lower is not None:
                r['adjacent_kernel_stamps_s'] = [lower, None]
        for r in reversed(records):
            if upper is not None and any(r['end_offset'] <= g['start'] < upper_off for g in self.gaps):
                upper = None
            if 'kernel_s' in r:
                upper, upper_off = r['kernel_s'][1], r['offset']
            elif upper is not None:
                r.setdefault('adjacent_kernel_stamps_s', [None, None])[1] = upper
        errors = []
        if self.schedule:
            expected = self.schedule['executions']
            for token in self.tokens:
                seq = token['seq']
                if seq >= len(expected) or any(token[k] != expected[seq][k] for k in ('tok', 'op', 'event')):
                    errors.append('trace disagrees with manifest at seq=' + str(seq))
            if self.ui_start and (self.ui_start['parsed_tokens'] != self.schedule['parsed_tokens'] or self.ui_start['delay_s'] != self.schedule['delay_s']):
                errors.append('runtime start disagrees with manifest')
            if self.done and (self.done['tokens'] != len(expected) or self.done['events'] != self.schedule['events']):
                errors.append('trace completion disagrees with manifest')
        contiguous = [r['seq'] for r in self.tokens] == list(range(len(self.tokens)))
        if self.done and self.done['tokens'] != len(self.tokens):
            errors.append('trace completion includes unobserved token executions')
        if not contiguous:
            errors.append('missing trace sequences')
        if self.done and self.tokens:
            if self.done['max_late_us'] < max(r['late_us'] for r in self.tokens):
                errors.append('completion lateness is below observed token lateness')
            if self.done['max_call_us'] < max(r['end_us'] - r['begin_us'] for r in self.tokens):
                errors.append('completion call maximum is below observed token call duration')
        phases = []
        if self.schedule:
            family = dict(h='home-key', p='power-key', w='wait', t='tap', l='horizontal-swipes', r='horizontal-swipes',
                          s='vertical-scrolls', v='vertical-scrolls', u='edge-swipe-up', d='edge-swipe-down')
            groups = []
            for execution in self.schedule['executions']:
                name = family[execution['op']]
                if not groups or groups[-1][0] != name:
                    groups.append((name, []))
                groups[-1][1].append(execution['seq'])
            observed = {r['seq']: r for r in self.tokens}
            for i, (name, seqs) in enumerate(groups):
                first = observed.get(seqs[0])
                following = observed.get(seqs[-1] + 1)
                end = following['callback_us'] / 1e6 if following else self.done['us'] / 1e6 if self.done and seqs[-1] + 1 == len(self.schedule['executions']) else None
                phases.append(dict(name=f'{i}:{name}', sequences=[seqs[0], seqs[-1]],
                                   issue_span_s=[first['callback_us'] / 1e6 if first else None, end],
                                   tokens_observed=sum(s in observed for s in seqs), tokens_expected=len(seqs),
                                   state='observed_complete' if first and end is not None and all(s in observed for s in seqs) else 'incomplete'))
        windows, prev = [], None
        for top in self.tops:
            t = top['kernel_s'][0]
            window = dict(top, start_s=prev['kernel_s'] if prev else None,
                          first_sample_includes_task_lifetime=prev is None)
            if prev:
                gap = any(prev['end_offset'] <= g['start'] < top['offset'] for g in self.gaps)
                window['coverage'] = 'gap' if gap else 'complete'
                window['duration_bounds_s'] = [t - prev['kernel_s'][1], t + 1 - prev['kernel_s'][0]]
                window['issued_tokens'] = [r['seq'] for r in self.tokens if prev['kernel_s'][0] <= r['callback_us'] / 1e6 < t + 1]
                window['script_may_overlap'] = bool(self.tokens and t + 1 >= self.tokens[0]['callback_us'] / 1e6
                    and (not self.done or prev['kernel_s'][0] <= self.done['us'] / 1e6))
                window['cpu_ms_per_counter_increment'] = {f"{task['name']}[{task['pid']}]": round(task['cpu_ms'] / top['frames_delta'], 3)
                    for task in top['tasks'] if task['name'] == 'backboardd'} if top['frames_delta'] else {}
                window['intersects_issue_phases'] = [p['name'] for p in phases if p['issue_span_s'][0] is not None
                    and p['issue_span_s'][0] < t + 1 and (p['issue_span_s'][1] is None or p['issue_span_s'][1] > prev['kernel_s'][0])]
            else:
                window['coverage'] = 'initial_cumulative_sample'
            windows.append(window)
            prev = top
        crash_lines = collections.Counter(r['name'] for r in records if r['kind'] == 'crash')
        crash_pids = collections.defaultdict(set)
        for r in records:
            if r['kind'] == 'crash':
                crash_pids[r['name']].add(r['pid'])
        pids = collections.defaultdict(set)
        for r in self.tops:
            for task in r['tasks']:
                pids[task['name']].add(task['pid'])
        for r in records:
            if r['kind'] in ('spawn', 'exit', 'crash'):
                pids[r['name']].add(r['pid'])
        hogs = [r for r in records if r['kind'] == 'hog']
        summary = dict(tokens_observed=len(self.tokens), done=self.done,
                       state='observed_complete' if self.done and contiguous and not errors and not self.gaps else 'incomplete',
                       errors=errors, max_token_late_us=max((r['late_us'] for r in self.tokens), default=None),
                       max_token_call_us=max((r['end_us'] - r['begin_us'] for r in self.tokens), default=None),
                       callback_times_s=[self.tokens[0]['callback_us'] / 1e6, self.tokens[-1]['callback_us'] / 1e6] if self.tokens else None)
        if self.schedule:
            summary['expected'] = {k: v for k, v in self.schedule.items() if k != 'executions'}
        return dict(schema=1, script=summary, gaps=self.gaps, trailing_partial_bytes=len(self.pending),
                    warnings=self.warnings, top_period_s=self.period, windows=windows, records=records,
                    phases=phases, crash_report_lines=dict(crash_lines),
                    crash_affected_pids={n: sorted(p) for n, p in crash_pids.items()}, task_pids={n: sorted(p) for n, p in pids.items()},
                    termination=[r for r in records if r['kind'] == 'end_marker'],
                    hogs=hogs, presentation=dict(config=self.present_config,
                        counters=[r for r in records if r['kind'] == 'present_counters'],
                        observations=[r for r in records if r['kind'] == 'present_event'],
                        glass_timing='unavailable', input_causality='unavailable'), limitations=[
                        'HK PRESENT counts row-helper returns, submitted aggregates and existing DPU poll Layer0 evidence separately; none is glass/FPS.',
                        'Presentation stamps are CPU observation times; fetch status freshness and independent Layer1 completion are not established.',
                        'Sampled presentation records can be capped/reordered; counter snapshots are cumulative and bounded, not final boot totals.',
                        'UITRACE and presentation share a kernel clock, but temporal proximity does not prove input caused a particular aggregate.',
                        'Trace times cover callback/injection-call work, not delivery, response, scanout or glass.',
                        'HK HOG is selected TH_RUN threads at their last kernel entry, not a statistical CPU profile.',
                        'HK HOG sampling occurs after the preceding TOP window; stacks do not apportion that window CPU.',
                        'TOP frames+ counts eligible copy-path layers before validation, or admitted flips; it is not completed frames/FPS.',
                        'CPU per counter increment is a mixed-window ratio, not frame rendering or completion latency.',
                        'TOP excludes unobserved exited-task CPU; the initial sample includes extant tasks lifetime CPU.',
                        'Host receipt times are transport arrival times in a separate clock; no wall-clock alignment is inferred.',
                        'Untimed records have adjacent log stamps, not guaranteed event-time bounds; writers can stamp before printing.',
                        'No-issue/wait/post-script windows do not prove device idle or physical input absence.'])


def load_schedule(manifest, script):
    if script:
        return script_schedule(script), 'explicit --script'
    if manifest:
        cmdline = json.loads(Path(manifest).read_text())['cmdline']
        values = re.findall(r'(?:^|\s)hk_ui=(\S+)', cmdline)
        if len(values) != 1:
            raise ValueError('manifest must have exactly one complete hk_ui argument')
        return script_schedule(values[0]), str(manifest)
    return None, None


def verify_capture(journal, dump, expected):
    segments, metadata = decode_dump(dump, expected)
    compared = 0
    with journal.raw.open('rb') as source:
        for off, length in journal.ranges:
            for start, payload in segments:
                a, b = max(off, start), min(off + length, start + len(payload))
                if a < b:
                    source.seek(a)
                    got, want = source.read(b - a), payload[a - start:b - start]
                    if got != want:
                        raise ValueError(f'raw/dump byte mismatch at or after stream offset {a}')
                    compared += b - a
    if not compared:
        raise ValueError('raw/dump have no independently comparable bytes')
    endings = []
    for off, data in segments:
        for match in re.finditer(rb'(?:^|\n)(panic\(cpu[^\n]*)\n', data):
            detail = match[1].decode('utf-8', 'replace').rstrip('\r')
            endings.append(dict(offset=off + match.start(1), detail=detail,
                                termination='deadline_panic' if re.search(r'blazer-root: deadline \d+ s', detail) else 'panic'))
    return dict(path=str(dump), sha256=digest(dump), epoch=metadata['epoch'], compared_bytes=compared,
                uncomparable_live_bytes=journal.bytes - compared, stream_total=metadata['total'],
                not_read_before_reset=max(0, metadata['total'] - journal.end), termination=endings)


def text_report(report):
    source, script = report['source'], report['script']
    lines = [f"source {source['path']} ({source['mode']})", f"sha256 {source['raw_sha256']}",
             f"boot epoch {source.get('epoch', 'unknown; no status/header available')}"]
    if 'verified_dump' in source:
        verified = source['verified_dump']
        lines.append(f"same-epoch dump verification: {verified['compared_bytes']} live bytes equal; {verified['not_read_before_reset']} trailing dump bytes not read live")
        for end in verified['termination']:
            lines.append('verified dump ending: ' + end['termination'])
    lines.append(f"trace {script['state']}: {script['tokens_observed']} token executions observed")
    if script['done']:
        done = script['done']
        lines.append(f"done events={done['events']} tokens={done['tokens']} max_late_us={done['max_late_us']} max_call_us={done['max_call_us']} drift_us={done['drift_us']}")
    lines.append(f"gaps={report['gaps']} trailing_partial_bytes={report['trailing_partial_bytes']}")
    if report['termination']:
        lines.append('stream ending: ' + ','.join(e['termination'] for e in report['termination']))
    presentation = report['presentation']
    if presentation['counters']:
        c = max(presentation['counters'], key=lambda item: item['seq'])
        lines.append(f"PRESENT cumulative snapshot seq={c['seq']} us={c['us']}: copy_ops={c['copy_ops']} copy_bytes={c['copy_bytes']} submitted={c['submitted']} fetch_layer0={c['fetch_done']} unproved={c['uncertain']} event_drops={c['event_drops']}; glass/input causality unavailable")
    elif presentation['observations']:
        lines.append('PRESENT sampled observations only; no counter snapshot; glass/input causality unavailable')
    lines.append('TOP windows: kernel absolute seconds; frames+ counts attempted layers/admitted flips, not completed frames or FPS')
    for w in report['windows']:
        start, end = w['start_s'], w['kernel_s']
        bb = ','.join(f"{t['pid']}:{t['cpu_ms']}" for t in w['tasks'] if t['name'] == 'backboardd') or '-'
        lines.append(f"  {start} -> {end} frames={w['frames_delta']} cpu_ms={w['cpu_ms']} backboardd_pid:ms={bb} coverage={w['coverage']} tasks_complete={w['task_list_complete']}")
    lines.append('Issue phases (callback times; no proportional CPU allocation)')
    for p in report['phases']:
        lines.append(f"  {p['name']} {p['issue_span_s']} {p['tokens_observed']}/{p['tokens_expected']} {p['state']}")
    pcs = collections.Counter((h['name'], h['stack'][0].get('unslid', h['pc']), h['stack'][0].get('symbol', h['stack'][0].get('image', 'unresolved'))) for h in report['hogs'])
    lines.append('Saved user PCs at last kernel entry (counts are records, not time percentages)')
    for (name, addr, label), count in pcs.most_common():
        lines.append(f'  {name} {addr} records={count} {label}')
    lines.append('Crash-affected PIDs (multiple diagnostics can describe one termination): ' + str(report['crash_affected_pids']))
    for warning in report['warnings']:
        lines.append('warning: ' + str(warning))
    lines.extend('limit: ' + item for item in report['limitations'])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--raw', help='usbcon raw file, including .times journal')
    group.add_argument('--dump', help='4 MiB kernel.log capture, header required')
    parser.add_argument('--times', help='alternate .times journal for --raw')
    parser.add_argument('--verify-dump', help='verify raw ranges AND epoch against captured kernel.log (requires final .json)')
    parser.add_argument('--manifest', help='complete image manifest, preferred to truncated boot log')
    parser.add_argument('--script', help='explicit complete hk_ui=... for expected execution checks')
    parser.add_argument('--cache', help='explicit current dyld_shared_cache_arm64e')
    parser.add_argument('--quartzcore', help='local QuartzCore.s with demangled function labels')
    parser.add_argument('--no-symbols', action='store_true')
    parser.add_argument('--follow', action='store_true', help='tail committed .times records, stop at capture .json or Ctrl-C')
    parser.add_argument('--events', action='store_true', help='flush NDJSON records to stdout as decoded')
    parser.add_argument('--summary', action='store_true', help='compact human-readable report on stdout')
    parser.add_argument('--json', help='write complete report (atomic replacement)')
    args = parser.parse_args(argv)
    if (args.follow or args.times or args.verify_dump) and not args.raw:
        parser.error('--follow/--times/--verify-dump require --raw')
    if args.events and args.summary:
        parser.error('--events and --summary are separate output formats')
    symbols = None
    try:
        schedule, schedule_source = load_schedule(args.manifest, args.script)
        repo = repo_path()
        cache = Path(args.cache) if args.cache else repo / 'research/ios26-debug-r1/mnt/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64e'
        dis = Path(args.quartzcore) if args.quartzcore else repo / 'research/ios26-root-r1/apple/dis/QuartzCore.s'
        if args.json:
            protected = [args.raw, args.dump, args.times, args.verify_dump, args.manifest, cache, dis]
            if args.raw:
                protected += [args.raw + '.times', args.raw + '.json']
            if Path(args.json).resolve() in {Path(p).resolve() for p in protected if p}:
                raise ValueError('--json output must not overwrite an input/capture sidecar')
        if not args.no_symbols and (cache.is_file() or args.cache):
            symbols = Symbols(cache, dis if dis.is_file() or args.quartzcore else None)
        analyzer = Analyzer(symbols, schedule, lambda r: print(json.dumps(r), flush=True) if args.events else None)
        source = dict(path=args.raw or args.dump, mode='raw_journal' if args.raw else 'canonical_dump', schedule_source=schedule_source)
        if args.raw:
            journal = Journal(args.raw, args.times)
            summary_path = Path(args.raw + '.json')
            interrupted = False
            try:
                while True:
                    for off, payload, host in journal.poll(final=not args.follow):
                        analyzer.feed(off, payload, host)
                    if not args.follow or summary_path.exists():
                        for off, payload, host in journal.poll(final=True):
                            analyzer.feed(off, payload, host)
                        break
                    time.sleep(0.1)
            except KeyboardInterrupt:
                interrupted = True
            source.update(reads=journal.reads, bytes=journal.bytes, final_offset=journal.end,
                          times_sha256=digest(journal.path), raw_sha256=digest(journal.raw), interrupted=interrupted,
                          unjournaled_file_tail_bytes=max(0, journal.raw.stat().st_size - journal.end))
            if summary_path.exists():
                capture = json.loads(summary_path.read_text())
                if (capture['bytes'] != journal.bytes or capture['final_offset'] != journal.end or capture['reads'] != journal.reads
                        or journal.raw.stat().st_size != journal.end
                        or capture.get('lost_bytes', 0) != sum(g['bytes'] for g in analyzer.gaps)):
                    raise ValueError('capture summary/journal disagree: truncated or replaced capture')
                source['capture'] = capture
                status = capture.get('last_status', {})
                if all(k in status for k in ('nonce', 'entry_t', 'hz')):
                    source['epoch'] = {k: status[k] for k in ('nonce', 'entry_t', 'hz')}
                if args.verify_dump:
                    if 'epoch' not in source:
                        raise ValueError('raw final status has no boot epoch for --verify-dump')
                    source['verified_dump'] = verify_capture(journal, args.verify_dump, source['epoch'])
            elif args.verify_dump:
                raise ValueError('--verify-dump requires the finished capture summary .json')
        else:
            segments, info = decode_dump(args.dump)
            source.update(info, raw_sha256=digest(args.dump))
            for off, payload in segments:
                analyzer.feed(off, payload)
        report = analyzer.report()
        report['source'] = source
        report['symbols'] = dict(cache=str(cache) if symbols else None,
                                 cache_uuid=symbols.cache.uuid if symbols else None,
                                 local_symbols_present=Path(str(cache) + '.symbols').is_file(),
                                 disassembly=str(dis) if symbols and symbols.labels else None,
                                 disassembly_sha256=digest(dis) if symbols and symbols.labels else None,
                                 method='cache image executable-segment bounds + local disassembly labels; unresolved otherwise')
        if args.json:
            output = Path(args.json)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=output.parent, prefix=output.name + '.', delete=False) as target:
                    temporary = Path(target.name)
                    target.write(json.dumps(report, indent=2) + '\n')
                temporary.replace(output)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
        if not args.events:
            print(text_report(report) if args.summary else json.dumps(report, indent=2))
        return 1 if report['script']['errors'] else 0
    except (ValueError, OSError, KeyError, struct.error) as exc:
        print('live_profile: ' + str(exc), file=sys.stderr)
        return 2
    finally:
        if symbols:
            symbols.close()


if __name__ == '__main__':
    sys.exit(main())
