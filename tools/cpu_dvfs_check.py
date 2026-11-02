#!/usr/bin/env python3
"""Offline A725 table check using the existing clk-probe decoder. No device access.

The saved probe enumerates firmware IDs34/35; CPU vote domains1/2 are a different
namespace. Explicit OPP levels survive sorting into Linux frequency-table order.
Source references/pin/licences and limitations: docs/CPU.md.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DECODER_SHA256 = 'a3baf95360949af7e3e54b3db08e553922505d4fca68051e9b17e15cff252bcf'
VENDOR_PIN = '5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c'
CPU_DOMAINS = {1: (34, 'cpu1g0'), 2: (35, 'cpu1g1')}


def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid ' + label)
    return value


def source_rungs(source):
    match = re.search(r'\}\s*gov_ladder\[\]\s*=\s*\{(.*?)\n\};', source, re.S)
    if not match:
        raise ValueError('governor ladder missing')
    # Accept only complete rows of the current declaration; unknown syntax fails.
    body = re.sub(r'/\*.*?\*/', '', match[1], flags=re.S)
    pattern = r'\{\s*(\d+),\s*(\d+),\s*\{\s*\d+,\s*\d+\s*\},\s*\d+,\s*\d+,\s*\d+\s*\},'
    rows = [(int(a), int(b)) for a, b in re.findall(pattern, body)]
    if re.sub(pattern, '', body).strip() or not rows or len(rows) > 32:
        raise ValueError('incomplete or unsupported governor ladder')
    if len({level for level, _ in rows}) != len(rows):
        raise ValueError('duplicate governor level')
    for level, mhz in rows:
        integer(level, 0, 31, 'governor level')
        integer(mhz, 1, 16383, 'governor MHz')
    tops = re.search(r'gov_dom_top\[GOV_DOMAINS\]\s*=\s*\{\s*0,\s*(\d+),\s*(\d+)\s*\}', source)
    if not tops:
        raise ValueError('governor domain ceilings missing')
    top = dict(zip((1, 2), map(int, tops.groups())))
    for domain, index in top.items():
        integer(index, 0, len(rows) - 1, 'domain ceiling index')
    # This checker never expands the existing physical clock admission ceilings.
    if rows[top[1]][0] != 0 or rows[top[2]][0] != 13:
        raise ValueError('existing measured domain ceilings changed')
    return rows, top


def topology(dts):
    match = re.search(r'cpufreq-clk-domain\s*=\s*<([^>]+)>', dts)
    if not match:
        raise ValueError('decompiled cpufreq-clk-domain missing')
    words = [integer(int(t, 0), 0, 0xffffffff, 'DT cell') for t in match[1].split()]
    mapping = b''.join(word.to_bytes(4, 'big') for word in words)
    if mapping != bytes((0, 0, 1, 1, 1, 2, 2, 3)):
        raise ValueError('unexpected physical CPU vote-domain map')
    for core in range(2, 7):
        node = re.search(r'\bcpu@' + format(core << 8, 'x') + r'\s*\{(.*?)\n\s*\};', dts, re.S)
        domain = mapping[core]
        expected = CPU_DOMAINS[domain][1]
        if not node or not re.search(r'dvfs-helper-domain-name\s*=\s*"' + expected + '"', node[1]):
            raise ValueError('CPU' + str(core) + ' firmware domain name disagrees with DT vote domain')
    return mapping


def validate(report, source, dts):
    result = dict(ok=False, physical_acceptance=False, clock_cap_change_authorized=False,
                  vendor_reference_pin=VENDOR_PIN, errors=[], checked=[])
    try:
        if (report.get('finished') is not True or report.get('table_complete') is not True or
            report.get('verdict') != 'LEVELS_AND_TABLE' or report.get('torn_at') is not None or
            report.get('faults') or report.get('stop') or report.get('rule_broken')):
            raise ValueError('requires a complete, clean existing clk-probe record')
        domains = report['domains']
        count = integer(report['domain_count'], 1, 48, 'firmware domain count')
        if not isinstance(domains, list) or len(domains) != count:
            raise ValueError('firmware domain list truncated')
        indexed = {}
        for domain in domains:
            key = integer(domain['id'], 0, count - 1, 'firmware domain id')
            if key in indexed: raise ValueError('duplicate firmware domain id')
            indexed[key] = domain
        rows, tops = source_rungs(source)
        topology(dts)
        for vote_domain, (firmware_id, name) in CPU_DOMAINS.items():
            domain = indexed.get(firmware_id)
            if (not domain or domain.get('name') != name or
                sum(d.get('name') == name for d in domains) != 1):
                raise ValueError('wrong or ambiguous firmware identity for vote domain ' + str(vote_domain))
            levels = integer(domain['level_count'], 1, 32, 'OPP count')
            if len(domain['levels']) != levels: raise ValueError('CPU OPP list truncated')
            table = {}
            for opp in domain['levels']:
                level = integer(opp['level'], 0, levels - 1, 'explicit OPP level')
                if level in table: raise ValueError('duplicate explicit OPP level')
                mhz = integer(opp['mhz'], 0, 16383, 'wire MHz')
                supported = integer(opp['supported'], 0, 1, 'OPP supported flag')
                integer(opp['sw_override'], 0, 1, 'OPP override flag')
                integer(opp['mv'], 0, 16383, 'wire voltage')
                if supported and not mhz: raise ValueError('supported zero-frequency OPP')
                # Check before unit conversion; arbitrary input never reaches unbounded C arithmetic.
                table[level] = dict(mhz=mhz, supported=supported)
            for rung, (level, mhz) in enumerate(rows):
                opp = table.get(level)
                if not opp or not opp['supported'] or opp['mhz'] != mhz:
                    raise ValueError('vote domain ' + str(vote_domain) + ' L' + str(level) + ' is unsupported or frequency disagrees')
                hz, khz = opp['mhz'] * 1000000, opp['mhz'] * 1000
                result['checked'].append(dict(vote_domain=vote_domain, firmware_id=firmware_id,
                                             name=name, explicit_level=level, wire_mhz=mhz,
                                             hz=hz, khz=khz, inside_existing_domain_ceiling=rung <= tops[vote_domain]))
        result['ok'] = True
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        result['errors'].append(str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--ids', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--dts', required=True, type=Path)
    parser.add_argument('--decoder', type=Path, default=ROOT / 'research/ios26-dramclk-r1/tools/decode_clk.py')
    args = parser.parse_args()
    result = dict(ok=False, physical_acceptance=False, clock_cap_change_authorized=False, errors=[])
    try:
        if hashlib.sha256(args.decoder.read_bytes()).hexdigest() != DECODER_SHA256:
            raise ValueError('existing decoder source identity changed; review before reuse')
        spec = importlib.util.spec_from_file_location('cpu_existing_clock_decoder', args.decoder)
        decoder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(decoder)
        raw = args.capture.read_bytes()
        ids = json.loads(args.ids.read_text())
        source, dts = args.source.read_text(), args.dts.read_text()
        report = decoder.decode(raw, ids)  # Reuse nonce/epoch/seal and framing checks.
        result = validate(report, source, dts)
        result['inputs'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (args.capture, args.ids, args.source, args.dts, args.decoder)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['errors'].append(str(exc))
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
