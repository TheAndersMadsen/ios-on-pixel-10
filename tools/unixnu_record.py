#!/usr/bin/env python3
"""Emit a UniXNU catalog identity (board.toml) and porting record (porting.toml) for blazer.

Usage: python3 -I tools/unixnu_record.py OUTDIR [--evidence FILE.toml] [--check]
       python3 -I tools/unixnu_record.py devices/blazer        (reads devices/blazer/receipts.toml)

The record follows UniXNU's published format (board.toml schema_version 2, porting.toml
schema_version 1; https://unixnu.com/porting/records, read at UniXNU 6b24c06c). It is
generated from docs/status.json, the README checklist's source, so the two cannot drift.
hackios is not built on the UniXNU tree: the board selects no UniXNU component, like
Scion-Project/scion-starlte's record (5cd68c99). Nothing here publishes anything.

Status mapping (docs/UNIXNU.md):
  area with a bound device receipt and a 'works' feature   -> device-verified
  area with a bound host receipt and works/partial/built   -> host-verified
  area with any works/partial/built feature                -> implemented
  otherwise                                                -> planned
Physical receipts live under research/, outside git, so device-verified needs an
--evidence file binding a receipt with its command and full 40-character revision.
--check exits 1 if OUTDIR's files differ from what would be written.

The evidence file (default OUTDIR/receipts.toml when present) holds [[evidence]] receipts and
[[claim]] entries (area, status, optional findings/limits/next_action/completion lists). A claim sets
the area's level; device-verified and host-verified claims need a bound receipt of that kind.
Evidence references resolve against OUTDIR first, then the repository root. UniXNU's checker
resolves them against OUTDIR only, so check a copy with the repository's top-level paths linked
beside it (docs/UNIXNU.md).
"""
import argparse
import json
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATUS = ROOT / 'docs' / 'status.json'

BOARD = {'name': 'blazer', 'soc': 'laguna', 'os_profile': 'ios-26.6.2-23G90',
         'description': 'Google Pixel 10 Pro (blazer, Tensor G5): hackios, iOS 26.6.2 on XNU 12377; '
                        'not built on the UniXNU tree'}
STATES = ('planned', 'implemented', 'host-verified', 'device-verified', 'not-applicable')
REQUIRED = ('configuration', 'firmware', 'cpu', 'memory', 'storage', 'display', 'input', 'gpu',
            'network', 'audio', 'power', 'packaging', 'diagnostics')
FIELDS = ('inputs', 'configuration', 'procedure', 'findings', 'completion', 'limits', 'next_action')
WORD = {'works': 'works on the phone', 'partial': 'partly working', 'built': 'built, not run',
        'active': 'in progress', 'open': 'not started', 'out': 'likely out of reach'}
PRIVATE = ('Physical receipts are kept under research/, outside git; device-verified needs a published '
           'receipt bound with --evidence.')

# Block -> area; (block, feature substring) overrides first.
BLOCK_AREA = {'CPU': 'cpu', 'Memory': 'memory', 'Display': 'display', 'Graphics': 'gpu', 'Storage': 'storage',
              'Input': 'input', 'Connectivity': 'network', 'USB': 'usb', 'Audio': 'audio', 'Sensors': 'sensors',
              'Power': 'power', 'Cameras': 'camera', 'Security': 'security', 'Apple services': 'identity'}
FEATURE_AREA = (('Storage', 'chooser', 'firmware'), ('Connectivity', 'Cellular', 'cellular'),
                ('Connectivity', 'Bluetooth', 'bluetooth'), ('Audio', 'Haptics', 'input'),
                ('Connectivity', 'SIM', 'cellular'), ('Connectivity', 'GPS', 'radios'),
                ('Connectivity', 'NFC', 'radios'), ('Connectivity', 'UWB', 'radios'),
                ('USB', 'Fastboot', 'diagnostics'), ('USB', 'Live console', 'diagnostics'))

# Static per-area text: (paths, inputs, configuration, procedure, completion, next_action, source refs).
# Hardware facts are those already in committed files (README.md, tools/mkadt.py, shim/*.h, docs/*.md).
A = {
    'configuration': (['docs/status.json', 'tools/unixnu_record.py', 'tools/image_tool.py', '.github/**'],
                      ['XNU 12377 (local series based on ios-tegu), iOS 26.6.2 (23G90) userland, Tensor G5 board blazer.'],
                      ['Image inputs are pinned by sha256 in tools/image_tool.py and docs/BUILD.md; boot-args only from the tool list.'],
                      ['python3 -I tools/image_tool.py image NAME --kernel K --kernel-sha SHA ... (docs/BUILD.md).'],
                      ['Every input of an image resolves to a pinned hash; the manifest names kernel, ADT, payload and argv.'],
                      ['Keep docs/status.json current; regenerate this record with tools/unixnu_record.py.'],
                      ['docs/BUILD.md']),
    'firmware': (['shim/**'],
                 ['Stock ABL (unlocked) loads a temporary fastboot boot image; no UEFI. The shim enters at EL2.'],
                 ['shim/ chooser: menu, volume keys, 5 s default to Android; Android entry chain-loads the stock kernel.'],
                 ['fastboot boot of the image built by tools/image_tool.py or tools/chooser_image.py; return check after every boot.'],
                 ['The shim reaches XNU entry at EL1 with ADT and boot-args; the chooser boots Android unchanged.'],
                 ['Physical chooser volume keys and the iOS entry from the chooser (HANDOFF.md).'],
                 ['shim/chooser.c', 'docs/DUALBOOT.md']),
    'cpu': (['shim/el2_mmu*', 'tools/cpu_*'],
            ['GICv3 distributor 0x05880000, redistributors 0x05900000 (tools/mkadt.py); A520, A725 and X4 cores.'],
            ['--cpus, --bootcpu and --cpu-order of tools/image_tool.py.'],
            ['tools/cpu_audit.py and tools/cpu_dvfs_check.py on captures; 15-minute physical runs.'],
            ['Each admitted core runs iOS for 15 minutes with timer and IPI delivery; governor clocks match reads.'],
            ['Higher-clock acceptance, then A520 admission after the CAS workaround audit.'],
            ['docs/CPU.md']),
    'memory': (['tools/mkadt.py'],
               ['16 GiB LPDDR; low bank holds firmware carve-outs; kernel window in an upper bank (tools/mkadt.py).'],
               ['PHYS_BASE and MEM_SIZE in tools/mkadt.py; --window-base of tools/image_tool.py.'],
               ['Memory test and 15-minute runs under iOS.'],
               ['All RAM is owned or explicitly reserved; DMA engines use their documented ranges.'],
               ['Assign RAM beyond the working 12.92 GiB.'],
               ['NOTES.md']),
    'storage': (['shim/tgl_ufs*', 'tools/gpt_plan.py', 'tools/persist_check.py', 'tools/ios_partition_flash.py'],
                ['UFS host 0x3c400000, Samsung KLUDG4UHGC, 4096-byte LBA; GPT partitions ios_system and ios_data.'],
                ['Root on ios_system; /var writes only to the GPT-resolved ios_data.'],
                ['tools/gpt_plan.py plan; tools/persist_check.py before and after a boot.'],
                ['Root mounts from ios_system; writes stay in ios_data and survive a reboot; Android partitions unchanged.'],
                ['Physical ios_data persist test after a visible boot from ios_system.'],
                ['docs/DUALBOOT.md']),
    'display': (['shim/dcs_tables.h', 'shim/frame_tables.h', 'shim/dpu_quiesce.h'],
                ['DC9x00 display controller at 0x0ee00000 (vs_drm), panel 1280x2856.'],
                ['Framebuffer and canvas from tools/mkadt.py; --canvas of tools/image_tool.py.'],
                ['Panel frame and DCS brightness tests; owner observation of the panel.'],
                ['A known frame with correct geometry, then iOS presentation at a measured rate and brightness control.'],
                ['Measure completed-frame cadence; keep the compositor stable.'],
                ['NOTES.md']),
    'input': (['shim/keys_laguna*', 'tools/usb_keyboard.py'],
              ['Synaptics touch; volume and power keys on cpm pinctrl@5280000 (shim/keys_laguna.h).'],
              ['blazer_touch boot-args of tools/image_tool.py.'],
              ['Owner touch test in SpringBoard and Settings; key probe captures.'],
              ['Touches map to the panel with stable IDs; keys produce HID events.'],
              ['Power key test with the owner present.'],
              ['shim/keys_laguna.h']),
    'gpu': (['native/metal/**'],
            ['Imagination PowerVR DXT GPU; firmware started through Trusty.'],
            ['Native Metal sources under native/metal/.'],
            ['Host tests of native/metal; physical GPU ladder boots (rung N PASS lines); Metal plugin probe in userland.'],
            ['Firmware health passes, submissions complete with fences, a known image renders through Metal.'],
            ['Analyze the captured firmware DEBUG_DUMP and complete strict health.'],
            ['docs/NATIVE-METAL.md']),
    'network': (['tools/laguna_usb*'],
                ['BCM4390 Wi-Fi on PCIe (gen 1 x1), firmware from the vendor image.'],
                ['ADT /arm-io/wlan node, IO80211Controller/Interface user client and Apple80211 socket ioctls (docs/CONNECTIVITY.md).'],
                ['Physical boot with the image network; scripted Settings>Wi-Fi walk; HKWIFI round (IPMonitor, DNS, HTTP).'],
                ['Scan, association, DHCP and sustained traffic from iOS Settings and apps.'],
                ['Finish native Wi-Fi scan delivery and the Bluetooth keychain prerequisite.'],
                ['docs/CONNECTIVITY.md']),
    'bluetooth': (['docs/CONNECTIVITY.md'],
                  ['BCM4390 Bluetooth over the shared PCIe/UART path; firmware from the vendor image.'],
                  ['ADT bluetooth nub with transport-encoding 1 (H4); kernel-control com.apple.uart.sk.bluetooth bridge.'],
                  ['Physical boot with the bridge at transmit gate level 0; count bluetoothd packets and answers.'],
                  ['bluetoothd powers the controller, discovers devices and pairs one peripheral.'],
                  ['Keep bluetoothd alive past its fourth run, then controller power-on in bluetoothd.'],
                  ['docs/CONNECTIVITY.md']),
    'cellular': (['docs/CONNECTIVITY.md'],
                 ['Samsung S5400 modem.'],
                 ['None selected.'],
                 ['Pad probe only.'],
                 ['Modem boot, SIM access, registration and a data session.'],
                 ['PCIe0 bring-up and modem boot.'],
                 ['docs/CONNECTIVITY.md']),
    'radios': (['docs/CONNECTIVITY.md'], ['GPS, NFC and UWB hardware.'], ['None selected.'], ['None yet.'],
               ['Each radio reports to its iOS service.'], ['Not assigned.'], ['docs/CONNECTIVITY.md']),
    'usb': (['shim/laguna_usb*', 'tools/usbnet_mac.py', 'tools/usbcon.py'],
            ['DWC3 at 0x0c400000, wrapper 0x0c450000.'],
            ['blazer_usbcon boot-args; USB ECM source.'],
            ['tools/usbcon.py live console; host tests of the ECM path.'],
            ['Native mux pairing and ECM traffic with the Mac.'],
            ['Physical ECM binding and traffic.'],
            ['README.md']),
    'audio': (['docs/CONNECTIVITY.md'], ['Always-on chip (AoC) audio path, CS35L43 amplifiers.'], ['None default.'],
              ['AoC ladder boots (aoc5, aoc6) with the carve attribute check.'], ['Playback and capture on declared routes.'],
              ['Run the queued QEMU audio test.'], ['NOTES.md']),
    'sensors': (['docs/CONNECTIVITY.md'], ['IMU and other sensors behind the always-on chip.'], ['None default.'],
                ['Physical accelerometer and gyro samples.'], ['Sensors reach their iOS services.'],
                ['Proximity, light and barometer; app integration.'], ['NOTES.md']),
    'power': (['shim/guard*', 'tools/panic_region.py'],
              ['PMIC RTC, fuel gauge, thermal zones.'],
              ['Thermal guard and battery boot-args of tools/image_tool.py.'],
              ['Physical battery samples and RTC GET_TIME.'],
              ['Battery percentage and charge state visible in iOS; supported transitions restore peripherals.'],
              ['Verify the visible battery percentage and date/time.'],
              ['NOTES.md']),
    'camera': (['docs/REUSE.md'], ['Camera sensors and ISP.'], ['None.'], ['None.'], ['A frame from a camera in iOS.'],
               ['None scheduled: sensor details are not public.'], ['README.md']),
    'security': (['docs/IOS-APPS-IDENTITY.md'], ['No Apple SEP; Android secure world.'], ['Key-store provider only.'],
                 ['None.'], ['Data protection with wrapped keys.'], ['Owner decision on the AKS user-session keybag.'],
                 ['docs/IOS-APPS-IDENTITY.md']),
    'identity': (['adt/identity.yaml', 'tools/adt_patch.py'], ['ADT identity iPhone12,3 (D421AP), synthetic ECID.'],
                 ['adt/identity.yaml'], ['None.'], ['Apple services accept the device.'],
                 ['None scheduled: needs a real iPhone identity.'], ['docs/IOS-APPS-IDENTITY.md']),
    'packaging': (['tools/image_tool.py', 'tools/mkadt.py', 'tools/mkpayload.py', 'tools/mkbootimg.py', 'adt/**'],
                  ['Android boot image (fastboot boot) carrying shim, XNU Mach-O, ADT and payload.'],
                  ['ADT from tools/mkadt.py (google,lga-blazer root); payload version 2 with a 1023-byte line.'],
                  ['python3 -I tools/image_tool.py image NAME ...; python3 -I tools/image_tool.py check research/images/NAME.'],
                  ['The image matches its manifest and SHA256SUMS and the bootloader accepts it.'],
                  ['Keep images immutable: a change gets a new name.'],
                  ['docs/BUILD.md']),
    'diagnostics': (['tools/boot-summary.py', 'tools/all_decode.py', 'tools/read-ramdump.py', 'tools/hklog.py',
                     'tools/decode-shim-stamps.py'],
                    ['ramoops at 0x95200000, pmsg at 0x95400000; USB live console.'],
                    ['blazer_usbcon boot-args; shim stamps.'],
                    ['tools/bootios ... then tools/boot-summary.py ATTEMPT (docs/BUILD.md).'],
                    ['Each claimed milestone has a capture bound to its image and argv.'],
                    ['Keep live console and final RAM tail retained separately.'],
                    ['docs/BUILD.md']),
    'userland': (['adt/**', 'tools/image_tool.py'],
                 ['iOS 26.6.2 (23G90) system volume on ios_system; overlay and launchd environment from the image.'],
                 ['Boot overlay, hk_env injection and launchd job state from tools/image_tool.py.'],
                 ['Physical boot to Home, then a scripted walk (ui scripts) that opens stock apps.'],
                 ['Home with stock icons; stock apps launch and draw; no respawn loop.'],
                 ['Register stock apps with lsd and stop the Photos/Health/Maps crashes.'],
                 ['NOTES.md']),
    'upstream': (['docs/UNIXNU.md'],
                 ['hackios: XNU 12377 with a local kernel series, its own shim, ADT generator and drivers.'],
                 ['No UniXNU source pin, component, OS profile or package script is used; board.toml lists no components.'],
                 ['Build and boot with docs/BUILD.md.'],
                 ['The record states that the port is not built on the UniXNU tree.'],
                 ['Keep this record generated from docs/status.json.'],
                 ['docs/UNIXNU.md']),
}
STATIC_FINDINGS = {
    'configuration': 'Inputs are bound by hash; an image is never rebuilt under the same name (docs/BUILD.md).',
    'packaging': 'Images from tools/image_tool.py booted XNU 12377 to Home and Settings on the phone (NOTES.md).',
    'upstream': 'This record follows the UniXNU porting-record format so the board can be described; it shares no code.',
}


def clean(text):
    return text.replace('–', '-').replace('—', '-').strip()


def area_of(block, feature):
    for b, sub, area in FEATURE_AREA:
        if b == block and sub in feature:
            return area
    if block not in BLOCK_AREA:
        raise SystemExit(f'unixnu_record: no area for status block {block!r}')
    return BLOCK_AREA[block]


def load_evidence(path):
    if path is None:
        return {}, {}
    data = tomllib.loads(pathlib.Path(path).read_text())
    bound = {}
    claims = {}
    for item in data.get('claim', []):
        if item.get('status') not in STATES or not isinstance(item.get('area'), str):
            raise SystemExit(f'unixnu_record: claim needs area and a status of {STATES}: {item}')
        for key in ('findings', 'limits', 'next_action', 'completion'):
            if key in item and not (isinstance(item[key], list) and item[key] and all(
                    isinstance(v, str) and v.strip() for v in item[key])):
                raise SystemExit(f'unixnu_record: claim {item["area"]}: {key} must be a list of strings')
        claims[item['area']] = item
    for item in data.get('evidence', []):
        for key in ('area', 'kind', 'reference', 'result', 'command', 'revision'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise SystemExit(f'unixnu_record: evidence entry needs {key}: {item}')
        if item['kind'] not in ('host', 'device') or not re.fullmatch(r'[0-9a-f]{40}', item['revision']):
            raise SystemExit(f'unixnu_record: evidence kind host/device and a 40-character revision: {item}')
        area = item.pop('area')
        bound.setdefault(area, []).append(item)
    return bound, claims


def build(status, bound, claims=None):
    claims = claims or {}
    features = {}
    for block in status['blocks']:
        for name, state, note in block['features']:
            features.setdefault(area_of(block['name'], name), []).append((name, state, clean(note)))
    order = list(REQUIRED) + [a for a in ('bluetooth', 'cellular', 'radios', 'usb', 'sensors', 'camera', 'security',
                                           'identity', 'userland', 'upstream') if a in A]
    unknown = set(features) | set(bound) | set(claims)
    unknown -= set(A)
    if unknown:
        raise SystemExit(f'unixnu_record: unknown areas {sorted(unknown)}')
    areas = []
    for aid in order:
        paths, inputs, config, proc, completion, nxt, refs = A[aid]
        feats = features.get(aid, [])
        states = {s for _, s, _ in feats}
        extra = bound.get(aid, [])
        kinds = {e['kind'] for e in extra}
        if aid == 'upstream':
            status_word = 'not-applicable'
        elif 'device' in kinds and 'works' in states:
            status_word = 'device-verified'
        elif 'host' in kinds and states & {'works', 'partial', 'built'}:
            status_word = 'host-verified'
        elif states & {'works', 'partial', 'built'} or aid in ('configuration', 'packaging'):
            status_word = 'implemented'
        else:
            status_word = 'planned'
        good = [f'{n}: {WORD[s]}. {note}'.rstrip() for n, s, note in feats if s in ('works', 'partial')]
        rest = [f'{n}: {WORD[s]}. {note}'.rstrip() for n, s, note in feats if s not in ('works', 'partial')]
        rest = [f'{n}: partly working; acceptance pending (findings).' for n, s, _ in feats if s == 'partial'] + rest
        findings = good or [STATIC_FINDINGS.get(aid, 'No physical result in this area yet.')]
        limits = rest + ([PRIVATE] if 'works' in states and status_word != 'device-verified' else [])
        if aid == 'upstream':
            limits = ["UniXNU's build, package and checker scripts do not build this board; its component IDs do not apply."]
        evidence = [{'kind': 'source', 'reference': r, 'result': f'{aid}: current statements and routes.'} for r in refs]
        if feats:
            evidence.append({'kind': 'source', 'reference': 'docs/status.json',
                             'result': f'{aid}: per-feature state of the README checklist.'})
        evidence += extra
        claim = claims.get(aid)
        if claim:
            status_word = claim['status']
            listed = '; '.join(f'{n}: {WORD[s]}' for n, s, _ in feats)
            if 'findings' in claim:
                findings = claim['findings'] + ([f'README checklist (docs/status.json {status["updated"]}): {listed}.']
                                                if feats else [])
            if 'limits' in claim:
                limits = claim['limits']
            nxt = claim.get('next_action', nxt)
            completion = claim.get('completion', completion)
        areas.append({'id': aid, 'status': status_word, 'components': [], 'paths': paths, 'inputs': inputs,
                      'configuration': config, 'procedure': proc, 'findings': findings, 'completion': completion,
                      'limits': limits or ['None recorded.'], 'next_action': nxt, 'evidence': evidence})
    summary = (f"Google Pixel 10 Pro (blazer, Tensor G5) running XNU 12377 and the iOS 26.6.2 userland through hackios "
               f"(own shim, ADT and drivers; not built on the UniXNU tree; no UniXNU components). Generated from "
               f"docs/status.json of {status['updated']}.")
    return {'schema_version': 1, 'device': {k: BOARD[k] for k in ('name', 'soc', 'os_profile')} | {'summary': summary},
            'area': areas}


def validate(record, board, roots=(ROOT,)):
    """The documented UniXNU record rules (https://unixnu.com/porting/records); raises ValueError."""
    def need(ok, msg):
        if not ok:
            raise ValueError(msg)
    need(board.get('schema_version') == 2 and record.get('schema_version') == 1, 'schema versions 2 and 1')
    for key in ('name', 'soc', 'os_profile'):
        need(record['device'][key] == board['board'][key], f'device.{key} differs from board.toml')
    ids = [a['id'] for a in record['area']]
    need(len(ids) == len(set(ids)) and set(REQUIRED) <= set(ids), 'required areas, no duplicates')
    for a in record['area']:
        need(re.fullmatch(r'[a-z][a-z0-9-]*', a['id']) and a['status'] in STATES, f'{a["id"]}: id/status')
        for key in FIELDS + ('paths',):
            need(a[key] and all(isinstance(v, str) and v.strip() for v in a[key]), f'{a["id"]}: {key} empty')
        need(all(not p.startswith('/') and '..' not in p for p in a['paths']), f'{a["id"]}: absolute path')
        kinds = set()
        for e in a['evidence']:
            kinds.add(e['kind'])
            need(e['kind'] in ('source', 'host', 'device') and e['reference'] and e['result'], f'{a["id"]}: evidence')
            if not e['reference'].startswith('https://'):
                need(any((r / e['reference']).is_file() for r in roots),
                     f'{a["id"]}: missing evidence file {e["reference"]}')
            if e['kind'] != 'source':
                need(e.get('command') and re.fullmatch(r'[0-9a-f]{40}', e.get('revision', '')), f'{a["id"]}: binding')
        if a['status'] == 'implemented':
            need(a['evidence'], f'{a["id"]}: implemented needs evidence')
        if a['status'] in ('host-verified', 'device-verified'):
            need(a['status'].split('-')[0] in kinds, f'{a["id"]}: {a["status"]} needs that evidence kind')
        if a['status'] == 'not-applicable':
            need(not a['components'], f'{a["id"]}: not-applicable with components')


def q(value):
    return json.dumps(value, ensure_ascii=False)


def dump(record):
    out = [f'schema_version = {record["schema_version"]}', '', '[device]']
    out += [f'{k} = {q(v)}' for k, v in record['device'].items()]
    for a in record['area']:
        out += ['', '[[area]]', f'id = {q(a["id"])}', f'status = {q(a["status"])}']
        for key in ('components', 'paths') + FIELDS:
            out.append(f'{key} = [' + ', '.join(q(v) for v in a[key]) + ']')
        if not a['evidence']:
            out.append('evidence = []')
        for e in a['evidence']:
            out += ['', '[[area.evidence]]'] + [f'{k} = {q(v)}' for k, v in e.items()]
    return '\n'.join(out) + '\n'


def board_toml():
    head = ('# hackios catalog identity in UniXNU board format 2. Generated by tools/unixnu_record.py;\n'
            '# not built on the UniXNU tree, so no UniXNU component is selected.\n')
    return head + 'schema_version = 2\n\n[board]\n' + ''.join(f'{k} = {q(v)}\n' for k, v in BOARD.items()) + \
        '\n[components]\ninclude = []\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('outdir', type=pathlib.Path)
    ap.add_argument('--evidence', help='TOML of [[evidence]] receipts: area, kind, reference, result, command, revision')
    ap.add_argument('--status', type=pathlib.Path, default=STATUS)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    if args.evidence is None and (args.outdir / 'receipts.toml').is_file():
        args.evidence = args.outdir / 'receipts.toml'
    record = build(json.loads(args.status.read_text()), *load_evidence(args.evidence))
    files = {'board.toml': board_toml(), 'porting.toml': dump(record)}
    try:
        validate(tomllib.loads(files['porting.toml']), tomllib.loads(files['board.toml']), (args.outdir, ROOT))
    except ValueError as error:
        print(f'unixnu_record: invalid record: {error}', file=sys.stderr)
        return 1
    if args.check:
        stale = [n for n, text in files.items() if not (args.outdir / n).is_file() or (args.outdir / n).read_text() != text]
        print('unixnu_record: ' + (f'stale {stale}' if stale else 'up to date'))
        return 1 if stale else 0
    args.outdir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (args.outdir / name).write_text(text)
    print(f'unixnu_record: {len(record["area"])} areas -> {args.outdir}: ' +
          ', '.join(f'{a["id"]}={a["status"]}' for a in record['area']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
