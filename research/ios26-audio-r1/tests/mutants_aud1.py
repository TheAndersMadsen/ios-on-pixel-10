#!/usr/bin/env python3
"""HOST ONLY. Mutants of tools/aud1_overlay.py: each must make test_aud1_overlay.py fail (or the merge raise).

    python3 -I research/ios26-audio-r1/tests/mutants_aud1.py
Each mutant is a text replacement in a temporary copy of the tool; the test runs against the copy through AUD1_TOOL.
"""
import os, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / 'research/ios26-audio-r1/tools/aud1_overlay.py'
TEST = REPO / 'research/ios26-audio-r1/tests/test_aud1_overlay.py'
MUTANTS = [
    ('tone stays in group 26', 'TONE_GROUP = 29', 'TONE_GROUP = 26'),
    ('no [39] edit', "new39_text = r39[6].replace(SB_OLD, SB_NEW)", "new39_text = r39[6]"),
    ('tone first in the DYLD list', "SB_NEW = SB_OLD[:-1] + b':' + TONE_PATH.encode() + b';'",
     "SB_NEW = SB_OLD.replace(b'=/private/var/hk/hkbattery', b'=' + TONE_PATH.encode() + b':/private/var/hk/hkbattery')"),
    ('tunings dropped', "[r[7] for r in tun] + [tone_rec]", "[tone_rec]"),
    ('HAL after tunings', "[r[7] for r in hal] + [r[7] for r in tun]", "[r[7] for r in tun] + [r[7] for r in hal]"),
    ('tone mode 0644', "tone_rec = MK.pack('f', TONE_GROUP, t[2],", "tone_rec = MK.pack('f', TONE_GROUP, 0o644,"),
    ('int1 record dropped', "for i, r in enumerate(base)]", "for i, r in enumerate(base) if i != 51]"),
]


def main():
    src = TOOL.read_text()
    caught = 0
    m = TOOL.with_name('.mutant_aud1_overlay.py')      # same directory: the tool finds the repo from its own path
    try:
        for name, old, new in MUTANTS:
            if src.count(old) != 1:
                print(f'BAD MUTANT {name}: pattern not found once')
                return 1
            m.write_text(src.replace(old, new))
            env = dict(os.environ, AUD1_TOOL=str(m))
            r = subprocess.run([sys.executable, '-I', str(TEST)], env=env, capture_output=True, text=True)
            hit = r.returncode != 0
            caught += hit
            print(f"{'caught' if hit else 'MISSED'}: {name}")
    finally:
        m.unlink(missing_ok=True)
    print(f'aud1 overlay mutants {caught}/{len(MUTANTS)} caught')
    return 0 if caught == len(MUTANTS) else 1


if __name__ == '__main__':
    sys.exit(main())
