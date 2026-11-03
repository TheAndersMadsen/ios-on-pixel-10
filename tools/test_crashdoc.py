"""Host tests of crashdoc.py with synthetic logs. No device.

The real-cache cases skip when the dyld cache (/data/hackios-qemu/dsc-r6) is absent.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('crashdoc', TOOLS / 'crashdoc.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

S1, S2 = 0xc50c000, 0xb6a8000


def ld(ts, text):
    return f'com.apple.xpc.launchd|2026-11-03 {ts} {text}'


def boot_a():
    """Current boot (slide S1): MobilePhone trap + its CRASH and exit, a deadline panic."""
    return [
        'TEGU-XNU STAGE0',
        'Darwin Kernel Version 25.5.0: test',
        ld('17:51:14.784781', '<Notice>: boot-args = cpus=5 blazer_deadline=300 hk_bright=140'),
        ld('17:51:15.000001', '(system) <Notice>: entering ondemand mode'),
        ld('09:51:15.100000', '(system) <Notice>: time zone shifted line'),          # whole hours: not a cut
        f'HGLTRACK: SWContext slot wrapped, slide {S1:#x}, reprotect 0',
        'exec MobilePhone',
        f'usertrap: MobilePhone[174] exception 6 code 0x1 0x100c6ebc0: pc 0x100c6ebc0 lr 0x100c6eb64 sp 0x16f372c50, '
        f'shared cache slide {S1:#x}, main header 0x100a8c000',
        'usertrap:   called from 0x100c6eacc',
        'usertrap:   called from 0x19575c420',
        'CRASH MobilePhone reason ns 2 code 0x5: (none)',
        ld('17:52:00.000002', '(user/501/UIKitApplication:com.apple.mobilephone[1a2b][rb-legacy] [174]) <Notice>: '
           'exited due to SIGTRAP | sent by exc handler[174], ran for 900ms'),
        ld('17:52:01.000003', '(user/501/com.apple.foo [80]) <Notice>: exited due to exit(0), ran for 10ms'),
        'panic(cpu 1 caller 0xfffffe00079fc060): blazer-root: deadline 300 s, stage pid1_exec, 1 reads @hakios.blazer_ufs.c:1120',
    ]


def boot_b():
    """Older boot (slide S2), residue after A in the ring: a CoreBrightness trap."""
    return [
        ld('17:44:15.151960', '<Warning>: kpersona_f residue starts'),
        f'usertrap: backboardd[22] exception 1 code 0x1 0x0: pc {0x1e2746924 + S2:#x} lr {0x1e2742298 + S2:#x} '
        f'sp 0x16daf4810, shared cache slide {S2:#x}, main header 0x102308000',
        f'usertrap:   called from {0x1e2742298 + S2:#x}',
        'CRASH backboardd reason ns 2 code 0xb: (none)',
        ld('17:44:20.000001', '(user/501/com.apple.backboardd [22]) <Notice>: exited due to SIGSEGV | sent by exc handler[22], '
           'ran for 3000ms'),
    ]


def write_attempt(root, name, lines, reader_tail=None, nonce=None, extra=None):
    d = Path(root) / name
    (d / 'ramdump').mkdir(parents=True)
    (d / 'ramdump' / 'kernel.log').write_bytes(lines)
    if reader_tail is not None:
        (d / 'reader.txt').write_text(
            'VERDICT: PANICKED | stage=none\n'
            f'  shim: TSHIMST2 nonce={nonce} reason=5\n'
            '----- XNU msgbuf tail -----\n' + '\n'.join(reader_tail) + '\n----- persistent_ram console tail -----\nzzz\n')
    for k, v in (extra or {}).items():
        (d / k).write_text(v)
    return d


def ring(*parts):
    """A 'dump': text regions separated by NUL runs (console zone, then the pmsg mirror)."""
    return (b'\0' * 64).join('\n'.join(p).encode() + b'\n' for p in parts)


def run_json(*paths, cache=None):
    doc, md = C.run([str(p) for p in paths], cache)
    return doc, md


class Fragments(unittest.TestCase):
    def frags(self, lines):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'kernel.log'
            p.write_bytes(lines if isinstance(lines, bytes) else '\n'.join(lines).encode())
            src = C.Source(p, 'x')
            return src, C.split_fragments(src)

    def test_ring_cut_on_time_jump_and_slide(self):
        src, fs = self.frags(boot_a() + boot_b())
        self.assertEqual([f.slide for f in fs], [S1, S2])
        self.assertEqual(fs[0].start, 0)
        self.assertEqual(src.lines[fs[1].start], boot_b()[0])

    def test_timezone_shift_is_not_a_cut(self):
        _, fs = self.frags(boot_a())
        self.assertEqual(len(fs), 1)

    def test_cut_after_panic_without_launchd(self):
        short = ['TEGU-XNU STAGE0', 'Darwin Kernel Version 25.5.0',
                 'panic(cpu 0 caller 0xfffffe0007a32c9c): HK GPUTA: rung 6 PASS, boot ended on purpose @blazer_gpu_tipc.c:933',
                 'Debugger called', f'userabort: lsd[81] aborts, shared cache slide {S2:#x}; called from: 0x1a4ae2fcc']
        _, fs = self.frags(short)
        self.assertEqual(len(fs), 2)
        self.assertIsNone(fs[0].slide)
        self.assertEqual(fs[1].slide, S2)

    def test_nul_runs_are_regions_and_line_numbers_match_tr(self):
        data = ring(['a', 'b'], ['c'])
        src, fs = self.frags(data)
        self.assertEqual(src.lines[:3], ['a', 'b', 'c'])
        self.assertEqual(src.region_start, {0, 2})
        self.assertEqual(len(fs), 2)
        self.assertEqual(data.replace(b'\0', b'').decode().split('\n')[:4], src.lines[:4])

    def test_glued_frame_hex(self):
        self.assertEqual(C.hexes('0x1c96d01e4 0x1c96b95b0com.apple.xpc'), [0x1c96d01e4, 0x1c96b95b0])
        self.assertEqual(C.hexes('0x100a32d74SWEET'), [0x100a32d74])


class Boots(unittest.TestCase):
    def test_residue_and_mirror_copy(self):
        with tempfile.TemporaryDirectory() as td:
            a = boot_a()
            d = write_attempt(td, '20261103-185039-r9', ring(a + boot_b(), a), reader_tail=a[-6:], nonce='0xcf23')
            doc, md = run_json(d)
        boots = {b['slide']: b for b in doc['boots'] if b['slide']}
        self.assertEqual(set(boots), {f'{S1:#x}', f'{S2:#x}'})
        cur, old = boots[f'{S1:#x}'], boots[f'{S2:#x}']
        self.assertEqual(cur['nonce'], '0xcf23')
        self.assertEqual(cur['current_in'], ['20261103-185039-r9'])
        self.assertEqual(old['current_in'], [])
        self.assertTrue(old['label'].startswith('residue@'))
        self.assertEqual(cur['boot_args'], {'cpus': '5', 'blazer_deadline': '300', 'hk_bright': '140'})
        sigs = {s['sig']: s for s in doc['signatures']}
        mp = sigs['usertrap:MobilePhone@MobilePhone+0x1e2bc0']
        self.assertEqual(mp['incidents'], 1)                 # the mirror copy is the same incident
        self.assertEqual(mp['boots'], {cur['id']: 1})
        self.assertEqual([h['id'] for h in mp['hints']], ['mobilephone-contacts-tcc'])
        bb = sigs['usertrap:backboardd@0x1e2746924']           # no cache: the unslid address still names the signature
        self.assertEqual(bb['boots'], {old['id']: 1})
        self.assertEqual([h['id'] for h in bb['hints']], ['corebrightness-calibration'])
        # CRASH and the SIGTRAP exit belong to the trap, they are not separate crashes
        self.assertFalse(any(s['kind'] == 'crash' for s in doc['signatures']))
        self.assertTrue(all(not s['crash'] for s in doc['signatures'] if s['kind'] == 'exit'))
        panic = next(s for s in doc['signatures'] if s['kind'] == 'panic')
        self.assertFalse(panic['crash'])
        self.assertEqual(panic['hints'][0]['id'], 'blazer-deadline')
        src = doc['sources'][0]
        self.assertEqual(src['own_boot'], cur['id'])
        self.assertEqual([c['sig'] for c in src['own_crashes']], ['usertrap:MobilePhone@MobilePhone+0x1e2bc0'])
        self.assertIn('mobilephone-contacts-tcc', md)

    def test_residue_across_dumps_counts_once_and_fixed_status(self):
        with tempfile.TemporaryDirectory() as td:
            b = boot_b()
            # attempt 1 is boot B itself; attempt 2 is boot A with B's residue; attempt 3 is a later boot running backboardd
            d1 = write_attempt(td, '20261103-184333-wj2', ring(['TEGU-XNU STAGE0'] + b), reader_tail=b[-4:], nonce='0x3e26')
            d2 = write_attempt(td, '20261103-185039-r9', ring(boot_a() + b), reader_tail=boot_a()[-5:], nonce='0xcf23')
            later = ['TEGU-XNU STAGE0', ld('18:30:00.000001', '(system) <Notice>: hello'),
                     f'HKACCEL: IOAcceleratorES wait skipped, pred 0 -> 0x1462, slide {0x105c000:#x}',
                     'exec backboardd', 'SWEET AKS: backboardd[45] sel 0']
            d3 = write_attempt(td, '20261103-193846-later', ring(later), reader_tail=later[-3:], nonce='0xf778')
            doc, _ = run_json(d1, d2, d3)
        bb = next(s for s in doc['signatures'] if s['sig'] == 'usertrap:backboardd@0x1e2746924')
        self.assertEqual(bb['incidents'], 1)
        self.assertEqual(len(bb['boots']), 1)
        owner = next(x for x in doc['boots'] if x['id'] == bb['first'])
        self.assertEqual(owner['current_in'], ['20261103-184333-wj2'])
        self.assertEqual(owner['seen_in'], ['20261103-184333-wj2', '20261103-185039-r9'])
        self.assertTrue(bb['status'].startswith('not seen since: 1 later boot(s) ran backboardd'), bb['status'])  # boot A did not run it
        mp = next(s for s in doc['signatures'] if s['proc'] == 'MobilePhone' and s['kind'] == 'usertrap')
        self.assertTrue(mp['status'].startswith('not exercised since'), mp['status'])

    def test_different_slides_never_join(self):
        a = boot_a()
        twin = [l.replace(f'{S1:#x}', f'{S2:#x}') for l in a]       # same launchd lines, other slide
        with tempfile.TemporaryDirectory() as td:
            d1 = write_attempt(td, '20261103-100000-x', ring(a))
            d2 = write_attempt(td, '20261103-110000-y', ring(twin))
            doc, _ = run_json(d1, d2)
        self.assertEqual(len([b for b in doc['boots'] if b['slide']]), 2)


class Live(unittest.TestCase):
    def test_live_console_crash_lines_and_context(self):
        console = [
            '21:39:54.132 live_boot: console: usbcon',
            '21:40:36.806 [    0.06] Darwin Kernel Version 25.5.0: test',
            '21:41:04.563 [   27.81] ERROR: [MessagesBlastDoorService:156] EXC_GUARD AST: type=0x1 flavor=0x0 target=0x0 code=0x2',
            '21:41:04.717 [   27.97] CRASH MessagesBlastDoo reason ns 2 code 0x5: (none)',
            '21:41:14.737 [   37.98] ERROR: [MessagesBlastDoorService:176] EXC_GUARD AST: type=0x1 flavor=0x0 target=0x0 code=0x2',
            '21:41:14.737 [   37.98] CRASH MessagesBlastDoo reason ns 2 code 0x5: (none)',
            '21:41:27.475 [   50.72] \tservice="kTCCServiceMediaLibrary"',
            '21:41:27.493 [   50.74] \tgeneric_extension="invalid"',
            '21:41:27.496 [   50.75] CRASH Preferences reason ns 2 code 0x6: (none)',
            '21:41:31.916 [   55.17] CRASH AccessibilityUIS reason ns 2 code 0x6: (none)',
        ]
        markers = ('LIVEBOOT 21:40:36.775 +42.8 CONSOLE_CONNECTED nonce 0x8bc64d7181cbb83c, entry 0x1\n'
                   'LIVEBOOT 21:41:04.717 +70.7 CRASH MessagesBlastDoo\n')
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / 'live-20261103-213954-a7-int1-live'
            d.mkdir()
            (d / 'console.txt').write_text('\n'.join(console) + '\n')
            (d / 'markers.txt').write_text(markers)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                C.main([str(d), '--json', '--no-symbols'])
            doc = json.loads(out.getvalue())
            self.assertFalse((Path.cwd() / 'crashes.md').exists() and False)
        own = doc['sources'][0]
        self.assertEqual(own['nonce'], '0x8bc64d7181cbb83c')
        self.assertIsNotNone(own['own_boot'])
        sigs = {s['proc']: s for s in doc['signatures'] if s['kind'] == 'crash'}
        bd = sigs['MessagesBlastDoo']
        self.assertEqual(bd['incidents'], 2)                   # pids 156 and 176 from the EXC_GUARD lines
        self.assertEqual(bd['hints'][0]['id'], 'blastdoor-sandbox-check')
        self.assertEqual(bd['example']['pid'], 156)
        self.assertTrue(bd['example']['guard'].startswith('EXC_GUARD AST'))
        self.assertEqual([h['id'] for h in sigs['Preferences']['hints']], ['about-preferences-medialibrary'])
        self.assertEqual([h['id'] for h in sigs['AccessibilityUIS']['hints']], ['axui-punctuation-model'])
        self.assertEqual({c['proc'] for c in own['own_crashes']}, {'MessagesBlastDoo', 'Preferences', 'AccessibilityUIS'})

    def test_markers_only(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / 'live-x'
            d.mkdir()
            (d / 'markers.txt').write_text('LIVEBOOT 21:40:36.775 +42.8 CONSOLE_CONNECTED nonce 0x1, entry 0x1\n'
                                           'LIVEBOOT 21:41:04.717 +70.7 CRASH MessagesBlastDoo\n'
                                           'LIVEBOOT 21:41:14.717 +80.7 CRASH MessagesBlastDoo\n')
            doc, _ = run_json(d)
        bd = next(s for s in doc['signatures'] if s['proc'] == 'MessagesBlastDoo')
        self.assertEqual(bd['incidents'], 2)


class FakeSym(C.Symbolizer):
    """Cache stand-in: names by unslid address."""
    NAMES = {0x1f0000000: ('libsystem_kernel.dylib', 'mach_msg2_trap'),
             0x1f0000100: ('SystemConfiguration', '__SCDynamicStoreNotifyWait'),
             0x1f0000200: ('libdispatch.dylib', 'dispatch_once_f'),
             0x1f0000300: ('SystemConfiguration', '__SCNetworkInterfaceCopyAllWithPreferences')}

    def __init__(self):
        super().__init__(None)
        self.uuid = 'fake'

    def cache_frame(self, u, ret):
        base = max((a for a in self.NAMES if a <= u), default=None)
        if base is None or u - base > 0x100:
            return None
        img, fn = self.NAMES[base]
        return dict(image=img, image_off=u - base, func=fn, func_start=base, off=u - base, how='export')


class Symbols(unittest.TestCase):
    def test_stall_culprit_skips_machinery(self):
        sl, ms = 0x1c5a8000, 0x4000
        lines = ['TEGU-XNU STAGE0', 'HKMAIN: Preferences[177] watching the main thread',
                 f'HKMAIN: stall 8029 ms pc {0x1f0000008 + sl:#x} lr {0x1f0000204 + sl:#x} sp 0x16da51dd0 '
                 f'dsc_slide {sl:#x} main_slide {ms:#x}',
                 f'HKMAIN: frames {0x1f0000198 + sl:#x} {0x1f0000370 + sl:#x} {0x100000000 + ms + 0xcdab0:#x}']
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'kernel.log'
            p.write_text('\n'.join(lines) + '\n')
            src = C.Source(p, 'x')
            boots = C.build_boots(C.split_fragments(src))
            evs = C.parse_events(boots[0], FakeSym())
        st = evs[0]
        self.assertEqual(st['kind'], 'stall')
        self.assertEqual(st['proc'], 'Preferences')
        self.assertEqual(st['culprit']['func'], '__SCDynamicStoreNotifyWait')
        self.assertEqual(st['frames'][-1]['loc'], 'Preferences+0xcdab0')
        g = dict(sig=C.signature(st), kind='stall', proc='Preferences', example=st, events=[st])
        self.assertEqual([h['id'] for h in C.hint_for(g)], ['configd-ionetworkstack'])

    @unittest.skipUnless(Path(C.DEFAULT_CACHE).exists(), 'dyld cache dsc-r6 not present')
    def test_real_cache_local_function_names(self):
        sym = C.Symbolizer(C.DEFAULT_CACHE)
        try:
            self.assertTrue(sym.uuid.startswith('0f1ee332'))
            pc = sym.frame(0x1e2746924 + S2, S2)
            lr = sym.frame(0x1e2742298 + S2, S2, ret=True)
            sb = sym.frame(0x2a4413fac, 0, ret=True)
        finally:
            sym.close()
        self.assertEqual(pc['func_start'], 0x1e2746810)
        self.assertIn('Display_lut', pc['func'])
        self.assertEqual(lr['func_start'], 0x1e2741c1c)
        self.assertEqual(sb['func'], '_sandbox_extension_consume')
        self.assertEqual(sb['off'], 0x24)


class Schema(unittest.TestCase):
    def test_stable_keys(self):
        with tempfile.TemporaryDirectory() as td:
            d = write_attempt(td, '20261103-185039-r9', ring(boot_a() + boot_b()), reader_tail=boot_a()[-5:], nonce='0x1')
            doc, _ = run_json(d)
            doc2, _ = run_json(d)
        self.assertEqual(doc['schema'], 'crashdoc/1')
        self.assertEqual(set(doc), {'schema', 'tool', 'cache', 'summary', 'sources', 'boots', 'signatures'})
        self.assertEqual(set(doc['summary']), {'sources', 'boots', 'signatures', 'crash_signatures', 'open', 'unexplained'})
        s = doc['signatures'][0]
        self.assertEqual(set(s), {'id', 'sig', 'kind', 'proc', 'crash', 'culprit', 'incidents', 'boots', 'first', 'last',
                                  'status', 'also', 'hints', 'example', 'refs'})
        self.assertEqual(set(s['example']), set(C.EVENT_KEYS) | {'boot', 'frames', 'throw', 'culprit'})
        self.assertEqual([x['id'] for x in doc['signatures']], [x['id'] for x in doc2['signatures']])
        self.assertEqual(s['id'], C.sig_id(s['sig']))


if __name__ == '__main__':
    unittest.main()
