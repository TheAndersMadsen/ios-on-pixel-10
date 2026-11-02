#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage the original readback adapter in a PRIVATE partial XNU fixture.

Never edits --base. Existing XNU context and the generated patch stay in ignored
research/. No whole-tree copy, kernel link, device access or boot is performed.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = ('bsd/dev/hakios.blazer_ufs.c', 'osfmk/arm64/blazer_usbcon.c',
         'osfmk/arm64/blazer_usbcon_core.inc', 'bsd/sys/Makefile')


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'expected one source anchor: {old[:80]!r}; reconcile changed base')
    return text.replace(old, new, 1)


def stage(base, out):
    base, out = Path(base).resolve(), Path(out).resolve()
    research = (ROOT/'research').resolve()
    if not out.is_relative_to(research/'ios26-dualboot-r2') or out == base or out.is_relative_to(base):
        raise ValueError('output must be a new private research/ios26-dualboot-r2/ directory outside --base')
    if out.exists():
        raise ValueError('output already exists; use a new fixture name')
    originals = {f: (base/f).read_text() for f in FILES}
    changed = dict(originals)
    rel = FILES[0]
    helper = '''/* Native readback identity only: no LUN switch, bind, or quarantine reset. */
int
n882_blazer_readback_lun(uint32_t *lun)
{
    int rc = -1;
    if (lun == NULL) return -1;
    lck_mtx_lock(&blazer_ufs_lock);
    if (ufs.ready && ufs_fake == NULL && ufs.exact.bound && !ufs.exact.quarantined) {
        *lun = ufs.lun;
        rc = 0;
    }
    lck_mtx_unlock(&blazer_ufs_lock);
    return rc;
}

'''
    changed[rel] = once(changed[rel], 'uint64_t\nn882_blazer_now_us(void)', helper+'uint64_t\nn882_blazer_now_us(void)')
    rel = FILES[1]
    changed[rel] = once(changed[rel], '#include "blazer_usbcon_core.inc"',
                        '#define UC_READBACK 1\n#include "xnu_usb_readback.inc"\n#include "blazer_usbcon_core.inc"')
    changed[rel] = once(changed[rel], '\tuc.ch9 = blazer_usbcon_ch9 == 1;',
                        '\tuc.ch9 = blazer_usbcon_ch9 == 1;\n\thk_rb_start();')
    rel = FILES[2]
    anchor = '\t\tok = false;                     /* no OUT data stage in this gadget */\n'
    changed[rel] = once(changed[rel], anchor, anchor+'#ifdef UC_READBACK\n'+
        '\t} else if (hk_rb_usb_setup(type, request, value, index, length, cap, &ok, &n)) {\n'
        '\t\t/* Readback worker owns storage; EP0 sees cached RAM only. */\n#endif\n')
    # The USB owner is in osfmk, so the real build must export the BSD contract
    # privately to XNU. Do not hide a missing export using broad -I bsd flags.
    rel = 'bsd/sys/Makefile'
    changed[rel] = once(changed[rel], 'XNU_ONLY_EXPORTS = \\\n',
                        'XNU_ONLY_EXPORTS = \\\n\thakios.blazer_ufs_exact.h \\\n')
    new_files = {f'osfmk/arm64/{n}': (ROOT/'dualboot'/n).read_text()
                 for n in ('readback.h', 'readback.c', 'xnu_usb_readback.inc')}
    patch = ''.join(''.join(difflib.unified_diff(originals[f].splitlines(True), changed[f].splitlines(True),
                    fromfile=f'a/{f}', tofile=f'b/{f}')) for f in FILES)
    for f, data in new_files.items():
        patch += ''.join(difflib.unified_diff([], data.splitlines(True), fromfile='/dev/null', tofile=f'b/{f}'))
    out.mkdir(parents=True)
    for f, data in (changed | new_files).items():
        p = out/'xnu'/f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(data)
    exported = out/'export/bsd/sys/hakios.blazer_ufs_exact.h'
    exported.parent.mkdir(parents=True)
    exported.write_bytes((base/'bsd/sys/hakios.blazer_ufs_exact.h').read_bytes())
    (out/'readback.patch').write_text(patch)
    hashes = lambda files: {f: hashlib.sha256(s.encode()).hexdigest() for f, s in files.items()}
    report = dict(base=str(base), base_sha256=hashes(originals), staged_sha256=hashes(changed | new_files),
                  patch_sha256=hashlib.sha256(patch.encode()).hexdigest(), compiled=False, linked=False, booted=False)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=base, capture_output=True, text=True)
    report['base_commit'] = revision.stdout.strip() if revision.returncode == 0 else None
    report['exported_header_sha256'] = hashlib.sha256(exported.read_bytes()).hexdigest()
    # Check the exact patch against the base; this does not modify the base/index.
    check = subprocess.run(['git', 'apply', '--check', str(out/'readback.patch')], cwd=base,
                           capture_output=True, text=True)
    report['apply_check'] = check.returncode == 0
    (out/'apply.txt').write_text(check.stdout+check.stderr)
    (out/'stage.json').write_text(json.dumps(report, indent=2)+'\n')
    if check.returncode:
        raise ValueError('patch apply check failed; see apply.txt')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(stage(a.base, a.output), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        sys.exit(f'stage-readback: {exc}')
