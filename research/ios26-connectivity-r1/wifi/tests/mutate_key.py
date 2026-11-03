#!/usr/bin/env python3
"""HOST ONLY. Mutants of the r2 key path (r2/src/blazer_bcm4390_join.c): key_oracle must fail on each."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
SRC = HERE.parent / 'r2/src'
X = Path(os.environ.get('XNU', HERE.parents[3] / 'research/ios26-release-r1/work/xnu'))
L = Path(os.environ.get('LLVM', Path.home() / '.local/share/hackios-host/llvm/bin'))
M = [
 ('passphrase sent as a PMK', 'rc = give_key(p, net->pass, net->pass_len, WSEC_PASSPHRASE, &st);', 'rc = give_key(p, net->pass, net->pass_len, 0, &st);'),
 ('passphrase never sent', 'if (net != NULL && net->pass_len != 0) {\n\t\trc = give_key', 'if (false) {\n\t\trc = give_key'),
 ('PMK before passphrase', '\tif (net != NULL && net->pass_len != 0) {\n\t\trc = give_key(p, net->pass', '\tif (0) {\n\t\trc = give_key(p, net->pass'),
 ('passphrase not wiped', 'jn_wipe(net->pass, sizeof(net->pass));\n\t\tnet->pass_len = 0;', 'net->pass_len = 0;'),
 ('ioctl buffers not wiped', '\t*status = p->ioc_status;\n\tjn_wipe(b, sizeof(b));\n\tb4_wipe_ioctl(p);', '\t*status = p->ioc_status;\n\tjn_wipe(b, sizeof(b));'),
 ('passphrase refusal ignored', 'if (st != 0 && p->cfg.join_armed) {\n\t\t\tjn_wipe(net->pmk', 'if (0) {\n\t\t\tjn_wipe(net->pmk'),
 ('length logged', '"join: passphrase given to the firmware: status %d\\n", st);', '"join: passphrase given to the firmware, %u: status %d\\n", net->pass_len, st);'),
 ('short passphrase taken', 'pass_len < PASS_MIN ||', 'pass_len < 1 ||'),
 ('long passphrase taken', '#define PASS_MAX        63u', '#define PASS_MAX        64u'),
 ('control chars taken', 'c < 0x20u ||', 'c < 0x01u ||'),
 ('tail not checked', ': c != 0) {', ': false) {'),
 ('open with passphrase taken', '(flags & NB_F_OPEN) ? pass_len != 0 :', '(flags & NB_F_OPEN) ? false :'),
 ('passphrase not kept', 'memcpy(net->pass, blob + NB2_PASS, pass_len);', ''),
 ('wrong struct size', '#define PMK_IOCTL_BYTES 263u', '#define PMK_IOCTL_BYTES 262u'),
 ('key at the wrong place', '#define PMK_KEY_AT      4u', '#define PMK_KEY_AT      6u'),
]
def run(src_dir):
    out = Path(src_dir) / 'ko'
    r = subprocess.run([str(L / 'clang'), '-std=c11', '-O1', '-DBLAZER', '-w', '-iquote', str(src_dir), '-iquote', str(X / 'bsd/dev'),
                        str(HERE / 'key_oracle.c'), '-o', str(out)], capture_output=True, text=True)
    if r.returncode:
        return 'no-build'
    return 'pass' if subprocess.run([str(out)], capture_output=True).returncode == 0 else 'fail'
base = (SRC / 'blazer_bcm4390_join.c').read_text()
missed = 0
with tempfile.TemporaryDirectory() as t:
    shutil.copy(SRC / 'blazer_pcie1.h', t)
    (Path(t) / 'blazer_bcm4390_join.c').write_text(base)
    assert run(t) == 'pass', 'unmutated source must pass'
    for name, a, b in M:
        if base.count(a) != 1:
            print(f'MUTANT DOES NOT APPLY: {name}'); missed += 1; continue
        (Path(t) / 'blazer_bcm4390_join.c').write_text(base.replace(a, b))
        r = run(t)
        ok = r != 'pass'
        missed += not ok
        print(f"{'caught' if ok else 'MISSED'} ({r}): {name}")
print(f'key mutants {len(M) - missed}/{len(M)} caught')
sys.exit(1 if missed else 0)
