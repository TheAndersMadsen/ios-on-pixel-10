#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare an immutable QEMU-only status diagnostic. Never starts it."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P29 = '5aad89780e798d730aa00372dd17568917cc81d97fc231df0fcf1a9fda80fca8'
ROOT_R3 = '205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7'
BASE_OVERLAY = '61c38161efd809bdac15f9f167e5431a4f116b54bf42c7280411480fa37bea2a'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dylib-receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    out = a.output.resolve()
    namespace = (ROOT / 'research/ios26-connectivity-r1').resolve()
    if out == namespace or not out.is_relative_to(namespace) or out.exists():
        raise ValueError('use a new ignored connectivity directory')
    receipt = json.loads(a.dylib_receipt.read_text())
    dylib = a.dylib_receipt.resolve().parent / 'hkbtkeychain.dylib'
    assert sha(dylib) == receipt['dylib_sha256'] and receipt['signature_verified']
    kernel = ROOT / 'research/ios26-release-r1/artifacts/kernel.ios26-p29'
    root = ROOT / 'research/ios26-overlay-r1/work/root-r3.img'
    base = ROOT / 'research/ios26-gpugl-r1/phone/p5-merged-r2-gltrack.ovl'
    assert sha(kernel) == P29 and sha(root) == ROOT_R3 and sha(base) == BASE_OVERLAY
    decoder = load('bt_overlay_decoder', ROOT / 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
    writer = load('bt_overlay_writer', ROOT / 'research/ios26-overlay-r1/tools/mkoverlay.py')
    rows = decoder.decode(base.read_bytes())
    selected = [i for i,r in enumerate(rows) if r[0] == ord('c') and r[1] == 29 and r[5] == 'hk_env']
    assert len(selected) == 1
    index = selected[0]
    assert [r[6] for r in rows if r[1] == 31 and r[5] == 'hk_deny'] == [b'bluetoothd']
    env = rows[index][6].decode()
    assert 'bluetoothd:' not in env
    env += ',bluetoothd:BT_HCI_TRANSPORT=H4:POSIX;BT_CHIP=ACI~BT;HK_BT_KEYCHAIN_TRACE=1;DYLD_INSERT_LIBRARIES=/private/var/hk/hkbtkeychain.dylib'
    writer.env_ok(env)
    assert len(env) < 1024
    replacement = writer.pack('c', 29, 0, 0, 0, 'hk_env', env.encode())
    body = b''.join(replacement if i == index else r[7] for i,r in enumerate(rows))
    body += writer.pack('f', 29, 0o755, 0, 0, '/private/var/hk/hkbtkeychain.dylib', dylib.read_bytes())
    blob = b'HKVAROV1' + struct.pack('<IIQ', len(body) + 24, len(rows) + 1, writer.fnv1a(body)) + body
    parsed = decoder.decode(blob)
    assert all(before[7] == after[7] for i,(before, after) in enumerate(zip(rows, parsed)) if i != index)
    assert parsed[-1][6] == dylib.read_bytes()
    out.mkdir(parents=True)
    overlay = out / 'bt-keychain.ovl'
    overlay.write_bytes(blob)

    # Freeze the already used guest harness; add only the known synthetic BT
    # discovery nub from bt-2. No MMIO/controller or fake-HCI implementation.
    template = ROOT / 'research/ios26-apps-r1/tools/qemu-ufsroot.py'
    text = template.read_text()
    anchor = '    blob = adt.serialize(tree)\n'
    assert text.count(anchor) == 1
    addition = '''    bn = adt.Node()
    bn.props = [('name', 0, b'bluetooth\\0'), ('device_type', 0, b'bluetooth\\0'),
                ('compatible', 0, b'bluetooth,n88\\0'), ('transport-encoding', 0, struct.pack('<I', 7)),
                ('local-mac-address', 0, bytes.fromhex('020000000001'))]
    next(c for c in tree.children if c.name == 'arm-io').children.append(bn)
'''
    # D is the harness's parent directory. Keep its layout entirely private.
    (out / 'tools').mkdir()
    harness = out / 'tools/qemu-ufsroot.py'
    path_anchor = "R = D.parent; BC = R/'ios26-bootchain-r1/tools'"
    assert text.count(path_anchor) == 1
    text = text.replace(path_anchor, "R = Path(" + repr(str(ROOT / 'research')) + "); BC = R/'ios26-bootchain-r1/tools'", 1)
    harness.write_text(text.replace(anchor, addition + anchor, 1))
    compile(harness.read_text(), str(harness), 'exec')
    test = out / 'test-overlay'
    release = ROOT / 'research/ios26-release-r1/work/xnu'
    command = ['clang', '-std=c11', '-DBLAZER=1', '-g', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
               '-idirafter', str(release / 'bsd'), HERE / 'tests/test_overlay.c', '-o', test]
    for label, argv in [('consumer-build', command), ('consumer-test', [test, overlay])]:
        p = subprocess.run(list(map(str, argv)), capture_output=True, text=True)
        (out / (label + '.log')).write_text(p.stdout + p.stderr)
        assert p.returncode == 0, (label, p.stderr[-1000:])
    args = 'launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 sweetarm64e=1 autounlock=0 blazer_panic=1 hk_usertrace=1 hk_fb_scanout=1 sweetfb_noconsole=1 sweetfb_hz=60 varfs=1 blazer_deadline=600 interrupt-masked-debug-mode=0 sched_preemption_disable_debug_mode=0 wdt=-1 atm_diagnostic_config=0x400 hk_top=30 hk_overlay=0x20080081'
    argv = [sys.executable, '-I', str(harness), 'bt-keychain-r1', '--route-md', '--kernel', str(kernel),
            '--root', str(root), '--window-gib', '12', '--runtime', '420', '--idle', '0', '--wait', '0',
            '--var-overlay', str(overlay), '--args', args]
    report = dict(kernel=str(kernel), kernel_sha256=P29, root=str(root), root_sha256=ROOT_R3,
                  base_overlay_sha256=BASE_OVERLAY, overlay=str(overlay), overlay_sha256=sha(overlay),
                  dylib_sha256=sha(dylib), source_receipt_sha256=sha(a.dylib_receipt),
                  harness=str(harness), harness_sha256=sha(harness), template_sha256=sha(template),
                  baseline_records_preserved=len(rows)-1, replaced_env_index=index, selected_env=env,
                  mask='0x20080081', bluetooth_deny_bit_unselected=31, synthetic_bt_node_guest_only=True,
                  no_fake_hci=True, no_radio_hardware=True, no_old_exittrace=True,
                  argv=argv, status='PREPARED, NOT RUN; awaiting shared guest release event')
    (out / 'plan.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
