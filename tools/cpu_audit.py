#!/usr/bin/env python3
"""Verify nonce-bound cpu0 audit stamps. A PASS is a prerequisite, never A520 support.

Usage: python3 -I tools/cpu_audit.py <attempt>/ramdump/kernel.log <image>/manifest.json

Mode 2 (blazer_cpu0_audit=2) adds the read-only Arm Errata Management ABI answers for
cpu0 (EM_VERSION, EM_FEATURES, EM_CPU_ERRATUM_FEATURES per A520 erratum). They are
reported under "errata_abi"; they never set a520_support_accepted either.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location('cpu_audit_stamps', Path(__file__).with_name('decode-shim-stamps.py'))
stamps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamps)


EM_ANSWERS = {3: 'higher-el-mitigation', 2: 'not-affected', 1: 'affected', 0: 'success',
              -1: 'not-supported', -2: 'invalid-parameters', -3: 'unknown-erratum'}
EM_ERRATA = (3685825, 4615642, 3631357, 2938996, 2900952, 2858100, 2630792)  # shim/tgl_cpu_audit.h order


def _s32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def errata_abi(records):
    """Decode mode 2's EM records (ENTER/DONE pairs) into firmware answers for cpu0."""
    pairs = [(int(s['stage_id'], 16), s['flags'], int(s['arg'], 16)) for s in records]
    out = dict(version=None, features=None, errata={})
    if len(pairs) < 2 or pairs[0][:2] != (0xed, 'ENTER') or pairs[1][:2] != (0xed, 'DONE'):
        return dict(out, error='missing EM_VERSION ENTER/DONE (a hang after ENTER means the SMC never returned)')
    version = _s32(pairs[1][2])
    out['version'] = version
    out['version_text'] = ('%d.%d' % (version >> 16, version & 0xffff)) if version >= 0 else EM_ANSWERS.get(version, str(version))
    rest = pairs[2:]
    if version < 0 or version >> 16 != 1:
        return dict(out, error='unexpected records after a non-1.x EM_VERSION') if rest else out
    if len(rest) < 2 or rest[0] != (0xef, 'ENTER', 0x840000F2) or rest[1][:2] != (0xef, 'DONE'):
        return dict(out, error='missing EM_FEATURES ENTER/DONE')
    out['features'] = _s32(rest[1][2])
    rest = rest[2:]
    if out['features'] != 0:
        return dict(out, error='erratum records without EM_CPU_ERRATUM_FEATURES') if rest else out
    if len(rest) != 2 * len(EM_ERRATA):
        return dict(out, error='erratum queries missing or repeated (%d records)' % len(rest))
    for i, erratum in enumerate(EM_ERRATA):
        enter, done = rest[2 * i], rest[2 * i + 1]
        if enter != (0xee, 'ENTER', erratum) or done[:2] != (0xee, 'DONE') or done[2] >> 32 != erratum:
            return dict(out, error='erratum %d record out of order' % erratum)
        answer = _s32(done[2])
        out['errata'][str(erratum)] = EM_ANSWERS.get(answer, str(answer))
    return out


def verify(raw, manifest):
    errors = []
    result = dict(ok=False, audit_complete=False, a520_support_accepted=False,
                  capture_sha256=hashlib.sha256(raw).hexdigest(), errors=errors)
    mode = (manifest.get('cpu_audit') or {}).get('mode')
    mode = mode if mode in (1, 2) else 1
    expected = dict(mode=mode, core=0, read_only=True, a520_support_accepted=False)
    if manifest.get('cpu_audit') != expected:
        errors.append('manifest does not identify the read-only cpu0 audit')
    tokens = manifest.get('cmdline', '').split()
    for token in ('blazer_cpu0_audit=%d' % mode, 'blazer_bootcpu=0x200', 'cpus=5', 'blazer_deadline=300'):
        key = token.split('=')[0]
        if [t for t in tokens if t.split('=')[0] == key] != [token]:
            errors.append('missing or conflicting ' + key)
    if '-DTGL_CPU_AUDIT=1' not in manifest.get('cflags', '').split():
        errors.append('manifest does not enable the compiled audit')
    if 'tgl_cpu_audit.c' not in manifest.get('extra_src', '').split():
        errors.append('manifest does not include the audit source')
    try:
        decoded = stamps.decode(raw)
        nonce = int(manifest['ids']['stamp_nonce'], 16)
        if int(decoded['nonce'], 16) != nonce: errors.append('stamp nonce differs from image')
    except (stamps.StampError, KeyError, ValueError, TypeError) as exc:
        errors.append('invalid stamps/manifest: ' + str(exc))
        return result
    if decoded['abi'] != 2 or decoded['boots'] != 1 or decoded['dropped']:
        errors.append('requires one complete, undropped v2 stamp trail')
    if decoded['freq'] != 38400000 or decoded['reason'] != 'handed-off-to-xnu':
        errors.append('requires the expected counter frequency and terminal XNU handoff reason')
    if decoded['count'] != len(decoded['slots']) or decoded['count'] > stamps.MAX_SLOTS:
        errors.append('stamp trail is truncated')
    slots = decoded['slots']
    if [s['seq'] for s in slots] != list(range(1, len(slots) + 1)):
        errors.append('stamp sequence is incomplete')
    if slots and (decoded['seq'] != slots[-1]['seq'] or decoded['last_stage'] != slots[-1]['stage'] or
                  decoded['last_flags'] != slots[-1]['flags']):
        errors.append('stamp header and final slot disagree')
    if any(s['ms_since_entry'] is None or s['ms_since_entry'] < 0 for s in slots):
        errors.append('invalid stamp timestamps')
    audit = [s for s in slots if 0xe7 <= int(s['stage_id'], 16) <= 0xef]
    order = [(0xe7, 'ENTER'), (0xe8, 'DONE'), (0xe9, 'DONE'), (0xea, 'DONE'),
             (0xeb, 'DONE'), (0xec, 'ENTER'), (0xec, 'DONE'), (0xe7, 'DONE')]
    em = audit[7:-1] if mode == 2 else []
    seen = [(int(s['stage_id'], 16), s['flags']) for s in audit[:7] + audit[-1:]]
    if seen != order or (mode == 1 and len(audit) != 8):
        errors.append('audit incomplete, repeated, reordered or refused')
        return result
    if mode == 2:
        abi = errata_abi(em)
        result['errata_abi'] = abi
        if abi.get('error'):
            errors.append('Errata ABI records: ' + abi['error'])
            return result
    audit = audit[:7] + audit[-1:]
    values = [int(s['arg'], 16) for s in audit]
    mpidr, midr, el, sctlr, revidr, actlr_enter, actlr, done = values
    if mpidr & 0xff00ffffff or midr != 0x410fd801 or el != 8 or sctlr & 0x1005:
        errors.append('unexpected cpu0 identity, EL or cache state')
    if actlr_enter or done: errors.append('invalid audit completion argument')
    result.update(audit_complete=not errors, midr=hex(midr), revidr=hex(revidr), cpuactlr=hex(actlr),
                  cas_workaround_bit9=bool(actlr & (1 << 9)),
                  powerdown_workaround_bit38=bool(actlr & (1 << 38)))
    if not result['cas_workaround_bit9']: errors.append('CPUACTLR[9] is clear; A520 CAS prerequisite fails')
    if not result['powerdown_workaround_bit38']: errors.append('CPUACTLR[38] is clear; A520 powerdown prerequisite fails')
    # Real fastcore records arrival time, MIDR, raw MPIDR (including non-affinity
    # bits), REVIDR, and EL/ISR. start.S then emits EL_DROP DONE and changes only
    # header.reason. The older decoder's synthetic HANDOFF DONE is not emitted.
    start = slots.index(audit[0])
    if not start or (slots[start - 1]['stage_id'], slots[start - 1]['flags'],
                     int(slots[start - 1]['arg'], 16)) != ('0x00e6', 'ENTER', 0x200):
        errors.append('audit is not inside the admitted fastcore handoff')
    tail = slots[slots.index(audit[-1]) + 1:]
    if [(s['stage_id'], s['flags']) for s in tail] != [('0x00e6', 'DONE')] * 5 + [('0x0028', 'DONE')]:
        errors.append('missing, reordered or failed fastcore/EL-drop handoff')
    else:
        elapsed, target_midr, target_mpidr, target_revidr, el_isr, final_el = [int(s['arg'], 16) for s in tail]
        if (elapsed <= 0 or target_midr != 0x410fd871 or target_mpidr & 0xff00ffffff != 0x200 or
            not target_revidr & 1 or el_isr >> 32 != 8 or el_isr & 0x100 or final_el != 0x40000000):
            errors.append('unexpected A725 identity, errata state or EL-drop result')
    result['ok'] = not errors
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    result = verify(args.capture.read_bytes(), json.loads(args.manifest.read_text()))
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
