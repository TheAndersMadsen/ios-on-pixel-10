#!/usr/bin/env python3
"""HOST ONLY. The overlay for a7-ios-system-aud1: int1-r1 (c440b6ea) + audio-s1b's HAL, tunings and tone client (9c4a7dde).

int1-r1's 52 records stay byte-identical and in place, except one in-place edit of record [39] (group 29's hk_env):
SpringBoard's DYLD_INSERT_LIBRARIES gains ':/private/var/hk/hkaudiotest.dylib' after hkbattery.dylib. A second
SpringBoard DYLD_INSERT_LIBRARIES rule would only add a second variable of the same name to the environment (kern_exec.c
hk_exec_env_add appends every matching KEY=VAL), so the existing variable is extended instead.
Appended, in this order:
  - audio-s1b's group 24 (5 records: /private/var/hkcover/hal/BlazerAudio.driver) and group 25 (259 records: the stock
    D421 tunings), byte-identical. hkcover_boot (blazer_audio bits 0 and 1) copies them over /Library/Audio/Plug-Ins/HAL
    and /Library/Audio/Tunings/D421. Their bits must stay out of hk_overlay.
  - audio-s1b's /private/var/hk/hkaudiotest.dylib (its record 265), same mode, uid, gid, path and bytes, moved from
    group 26 to group 29: int1's mask 0xA0080081 already applies group 29 and /private/var/hk (int1 [35]) is its parent.
Not taken: s1b's group 26 'd /private/var/hk' and its SpringBoard hk_env (replaced by the [39] edit) and group 27
(hkaudiolog, guest-only audiomxd os_log mirror; int1 already uses group 27 for a disabled.plist).

    aud1_overlay.py INT1 S1B OUT          (refuses to overwrite OUT; prints a JSON report)
    aud1_overlay.py --diff A B            (decode-diff, int_overlay.py's)
Codec: ios26-overlay-r1/tools/mkoverlay.py (pack/fnv1a/MAGIC); second walker ios26-overlay2-r1/tools/restore_cloudd.py.
"""
import argparse, hashlib, importlib.util, json, struct, sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[3]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MK = load('mkoverlay', 'research/ios26-overlay-r1/tools/mkoverlay.py')
RC = load('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
INT = load('int_overlay', 'research/ios26-phaseb-r1/int/tools/int_overlay.py')
sha = lambda b: hashlib.sha256(b).hexdigest()
PIN = {'int1': 'c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e',
       's1b': '9c4a7ddee3ba543ccae9334dbb0d67065a2c5766671533b071cd4e83ac3bcbd5'}
MASK = 0xA0080081                      # int1's hk_overlay, unchanged
HAL_GROUP, TUN_GROUP = 24, 25          # varfs_seed.c HKCOVER_HAL_GROUP / HKCOVER_TUN_GROUP
TONE_PATH = '/private/var/hk/hkaudiotest.dylib'
TONE_GROUP = 29
SB_OLD = b'SpringBoard:FEATUREFLAGS_DISABLED=SpringBoard/Autobahn:SpringBoard/AutobahnLegacyMigration:' \
         b'SpringBoard/AutobahnLegacyMigrationSupportingDistinctHome;DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib;'
SB_NEW = SB_OLD[:-1] + b':' + TONE_PATH.encode() + b';'
RULES_MAX, VAR_MAX = 1024, 384         # hk_exec_rules.h HK_RULES_MAX / HK_VAR_MAX, each with its NUL


def env_vars(text):
    """KEY=VAL strings of an hk_env text (PROG[+PROG]:K=V[;K=V][,PROG...])."""
    out = []
    for rule in text.split(b','):
        _, _, rest = rule.partition(b':')
        out += [v for v in rest.split(b';') if v]
    return out


def merge(ib, sb):
    for k, blob in (('int1', ib), ('s1b', sb)):
        if sha(blob) != PIN[k]:
            raise ValueError(f'{k} is not {PIN[k][:8]}')
    base, s1b = RC.decode(ib), RC.decode(sb)
    if len(base) != 52 or base[39][:2] != (ord('c'), 29) or base[39][5] != 'hk_env' or base[35][:2] + base[35][5:6] != (ord('d'), 29, '/private/var/hk'):
        raise ValueError('int1 records [35]/[39] are not what this merge edits')
    if base[39][6].count(SB_OLD) != 1:
        raise ValueError("int1 [39] has no single SpringBoard rule ending in hkbattery.dylib's DYLD_INSERT_LIBRARIES")
    if {r[1] for r in base} & {HAL_GROUP, TUN_GROUP}:
        raise ValueError('int1 already uses group 24 or 25')
    if MASK & (1 << HAL_GROUP | 1 << TUN_GROUP) or not MASK >> TONE_GROUP & 1:
        raise ValueError('mask must apply group 29 and never 24/25')
    hal = [r for r in s1b if r[1] == HAL_GROUP]
    tun = [r for r in s1b if r[1] == TUN_GROUP]
    tone = [r for r in s1b if r[1] == 26 and r[0] == ord('f') and r[5] == TONE_PATH]
    if len(hal) != 5 or len(tun) != 259 or len(tone) != 1:
        raise ValueError(f's1b groups: hal {len(hal)} tun {len(tun)} tone {len(tone)}, expected 5/259/1')
    t = tone[0]
    tone_rec = MK.pack('f', TONE_GROUP, t[2], t[3], t[4], t[5], t[6])
    r39 = base[39]
    new39_text = r39[6].replace(SB_OLD, SB_NEW)
    new39 = MK.pack('c', r39[1], r39[2], r39[3], r39[4], r39[5], new39_text)
    if len(new39_text) + 1 > RULES_MAX:
        raise ValueError('hk_env text too long')
    if any(len(v) + 1 > VAR_MAX for v in env_vars(new39_text)):
        raise ValueError('an hk_env variable is too long')
    recs = [new39 if i == 39 else r[7] for i, r in enumerate(base)] + [r[7] for r in hal] + [r[7] for r in tun] + [tone_rec]
    body = b''.join(recs)
    out = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(recs), MK.fnv1a(body)) + body
    if len(out) > MK.TOTAL_MAX:
        raise ValueError('too large')
    # independent postconditions with the second walker
    new = RC.decode(out)
    assert len(new) == 52 + 5 + 259 + 1
    assert all(new[i][7] == base[i][7] for i in range(52) if i != 39)
    assert new[39][:6] == base[39][:6] and new[39][6] == new39_text
    assert [r[7] for r in new[52:52 + 264]] == [r[7] for r in hal + tun]
    assert new[-1][:1] == (ord('f'),) and new[-1][1] == TONE_GROUP and new[-1][2:7] == t[2:7]
    sb_env = [v for rule in new39_text.split(b',') if rule.startswith(b'SpringBoard:') for v in env_vars(rule)]
    assert [v for v in sb_env if v.startswith(b'DYLD_INSERT_LIBRARIES=')] == [b'DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib:' + TONE_PATH.encode()]
    applied = sorted({r[1] for r in new if MASK >> r[1] & 1})
    return out, {'int1': PIN['int1'], 's1b': PIN['s1b'], 'output_sha256': sha(out), 'bytes': len(out), 'records': len(new),
                 'mask': hex(MASK), 'groups': sorted({r[1] for r in new}), 'applied_groups': applied,
                 'edited': {'[39]': {'before_sha256': sha(r39[6]), 'after_sha256': sha(new39_text),
                                     'springboard_env': [v.decode() for v in sb_env]}},
                 'appended': {'hal_g24': len(hal), 'tunings_g25': len(tun), 'tone_g29': f'[{len(new) - 1}] f g29 {TONE_PATH} sha256 {sha(t[6])}'},
                 'hk_env_text_bytes': len(new39_text)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--diff', action='store_true')
    p.add_argument('paths', nargs='+', type=Path)
    a = p.parse_args()
    if a.diff:
        print(INT.diff(a.paths[0].read_bytes(), a.paths[1].read_bytes()))
        return
    i1, s1b, outp = a.paths
    out, rep = merge(i1.read_bytes(), s1b.read_bytes())
    with outp.open('xb') as f:
        f.write(out)
    print(json.dumps(rep, indent=2))


if __name__ == '__main__':
    main()
