#!/usr/bin/env python3
"""Host tests for the ADT, payload and image tool. No Apple data needed except the pinned donor."""
import json, os, struct, subprocess, sys, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; sys.path[:0] = [str(X)]
import adt, mkadt, mkpayload, image_tool as T

def macho(extra_exec=b'', text=0xfffffff007004000, prelink=0):
    """Minimal PIE-less Mach-O: __TEXT, __TEXT_EXEC with the entry, no fixups."""
    segs = [('__TEXT', text, 0x4000, 0, 0x4000), ('__TEXT_EXEC', text + 0x4000, 0x4000, 0x4000, 0x4000)]
    if prelink: segs.append(('__PRELINK_TEXT', prelink, 0x4000, 0x8000, 0x4000))
    cmds = b''
    for n, va, vs, fo, fs in segs: cmds += struct.pack('<II16s4Q4I', 0x19, 72, n.encode(), va, vs, fo, fs, 7, 5, 0, 0)
    th = struct.pack('<IIII', 5, 16 + 34 * 8, 6, 68) + b'\0' * (32 * 8) + struct.pack('<Q', text + 0x4000) + b'\0' * 8
    cmds += th
    h = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, len(segs) + 1, len(cmds), 0, 0)
    b = bytearray(0xc000); b[:len(h + cmds)] = h + cmds; b[0x4000:0x4000 + len(extra_exec)] = extra_exec; b[0x100:0x109] = b'xnu-12377'
    return bytes(b)

class ADTTests(unittest.TestCase):
    def tree(self, **k):
        return adt.parse(adt.serialize(mkadt.build(**k)))[0]
    def test_identity(self):
        f = T.adt_facts(adt.serialize(mkadt.build()))
        self.assertEqual(f['model'], 'iPhone12,3'); self.assertEqual(f['chip_id'], '0x8030'); self.assertEqual(f['tuple'], [0, 0, 1, 1]); self.assertEqual(f['home_button_type'], 2)
        self.assertEqual(f['dram'], ['0xa00000000', '0x100000000']); self.assertEqual(f['fb'], ['0xf0000000', 1280, 2856]); self.assertEqual(f['canvas'], [1125, 2436]); self.assertEqual(f['ctrr'], 0)
        for n in ('D421AP', 'iPhone12,3', 'google,tegu', 'google,lga-blazer'): self.assertIn(n, f['compatible'])
    def test_product_is_d421ap_without_placeholders(self):
        r = self.tree(); p = next(c for c in r.children if c.name == 'product')
        self.assertEqual(p.prop('product-name'), b'iPhone 11 Pro\0'); self.assertEqual([c.name for c in p.children], ['haptics'])
        self.assertTrue(all(not f for k, f, v in p.props))
    def test_no_product_fails(self):
        with self.assertRaises(SystemExit): mkadt.build(donor='/nonexistent')
    def test_ramoops_guard(self):
        with self.assertRaises(SystemExit): mkadt.build(phys_base=0x80000000, mem_size=0x80000000)
    def test_seed(self):
        with self.assertRaises(SystemExit): mkadt.build(seed=b'R' * 64)
        with self.assertRaises(SystemExit): mkadt.build(seed=b'\0' * 256)
        a, b = self.tree(), self.tree(); s = lambda t: next(c for c in t.children if c.name == 'chosen').prop('random-seed')
        self.assertNotEqual(s(a), s(b))
    def test_cpu_prefix_and_no_options(self):
        r = self.tree(cpus=2); self.assertEqual(len(next(c for c in r.children if c.name == 'cpus').children), 2)
        self.assertNotIn('options', [c.name for c in r.children]); self.assertIn('options', [c.name for c in self.tree(nvram=True).children])
    def test_boot_mpidr_changes_reg_alone(self):
        seed = b'S' * 256; base = adt.serialize(mkadt.build(seed=seed))
        for m in (0x200, 0x300, 0x500):
            two = adt.serialize(mkadt.build(seed=seed, boot_mpidr=m))
            self.assertEqual(len(base), len(two))
            self.assertEqual(sum(x != y for x, y in zip(base, two)), 1)  # one byte of one u32
            c = next(x for x in adt.parse(two)[0].children if x.name == 'cpus').children
            self.assertEqual([(n.name, n.prop('reg'), n.prop('state'), n.prop('cpu-id')) for n in c], [('cpu0', struct.pack('<I', m), b'running\0', struct.pack('<I', 0))])
            self.assertEqual(T.adt_facts(two)['boot_reg'], m)
        self.assertEqual(T.adt_facts(base)['boot_reg'], 0)
    def test_boot_mpidr_with_cpus(self):
        for boot, want in ((0x200, [0x200, 0x300, 0x400, 0x500, 0x600]), (0x500, [0x500, 0x200, 0x300, 0x400, 0x600])):
            for n in range(1, 6):
                c = next(x for x in adt.parse(adt.serialize(mkadt.build(cpus=n, boot_mpidr=boot)))[0].children if x.name == 'cpus').children
                self.assertEqual([struct.unpack('<I', x.prop('reg'))[0] for x in c], want[:n])
                self.assertEqual([x.prop('state') for x in c], [b'running\0'] + [b'stopped\0'] * (n - 1))
                self.assertEqual([struct.unpack('<I', x.prop('cpu-id'))[0] for x in c], list(range(n)))
                self.assertTrue(all(x.prop('cluster-type') == struct.pack('<I', 0) for x in c))
    def test_boot_mpidr_refused(self):
        for k in (dict(boot_mpidr=0x100), dict(boot_mpidr=0x400), dict(boot_mpidr=0x600), dict(boot_mpidr=0x700), dict(boot_mpidr=0x500, cpus=6), dict(boot_mpidr=0x200, cpus=8), dict(boot_mpidr=0x500, qemu=True, phys_base=0x80000000, mem_size=0x80000000)):
            with self.assertRaises(SystemExit): mkadt.build(**k)
    def test_qemu(self):
        n = [c.name for c in self.tree(qemu=True, phys_base=0x80000000, mem_size=0x80000000).children]
        self.assertNotIn('laguna-dpu', n); self.assertNotIn('pram', n)

class CpuOrder(unittest.TestCase):
    # ios26-smp-r1. Node order is logical order, reg is the core, cluster-type stays 0, the boot core is cpu0 wherever listed.
    def nodes(self, **k):
        blob = adt.serialize(mkadt.build(seed=b'S' * 256, **k)); blob += b'\0' * (-len(blob) % 8)
        return blob, next(c for c in adt.parse(blob)[0].children if c.name == 'cpus').children
    def test_fast_first(self):
        _, c = self.nodes(cpu_order=[5, 6, 2, 3, 4, 1, 0])
        u = lambda n, k: struct.unpack('<I', n.prop(k))[0]
        self.assertEqual([n.name for n in c], [f'cpu{i}' for i in range(7)])
        self.assertEqual([u(n, 'reg') for n in c], [0x500, 0x600, 0x200, 0x300, 0x400, 0x100, 0])
        self.assertEqual([n.prop('state') for n in c], [b'stopped\0'] * 6 + [b'running\0'])
        self.assertEqual([u(n, 'cluster-type') for n in c], [0] * 7)
        self.assertEqual([u(n, 'cpu-id') for n in c], list(range(7)))
        self.assertEqual([u(n, 'l2-cache-id') for n in c], [5, 6, 2, 3, 4, 1, 0])
    def test_boot_reg_is_the_running_node(self):
        blob, _ = self.nodes(cpu_order=[5, 6, 2, 3, 4, 1, 0])
        self.assertEqual(T.adt_facts(blob)['boot_reg'], 0)
    def test_physical_order_is_the_plain_prefix(self):
        self.assertEqual(self.nodes(cpu_order=[0, 1])[0], self.nodes(cpus=2)[0])
    def test_qemu_reg_is_aff0(self):
        _, c = self.nodes(qemu=True, phys_base=0x80000000, mem_size=0x80000000, cpu_order=[3, 1, 2, 0])
        self.assertEqual([struct.unpack('<I', n.prop('reg'))[0] for n in c], [3, 1, 2, 0])
    def test_mkadt_refuses(self):
        for k in (dict(cpu_order=[1, 2]), dict(cpu_order=[0, 0]), dict(cpu_order=[0]), dict(cpu_order=[0, 8]), dict(cpu_order=[0, 1], cpus=2), dict(cpu_order=[0, 2], boot_mpidr=0x200)):
            with self.assertRaises(SystemExit): mkadt.build(seed=b'S' * 256, **k)
    def test_tool_refuses_x4_and_bad_lists(self):
        for t in ('7,0', '5,6,7,0', '1,2', '0', '0,0', '0,x', ''):
            with self.assertRaises(SystemExit): T.cpu_order(t)
        self.assertEqual(T.cpu_order('5,6,2,3,4,1,0'), [5, 6, 2, 3, 4, 1, 0])
    def test_tokens_on_the_list(self):
        self.assertEqual(T.phone_extra('blazer_fast_first=1 blazer_smp_report=1 blazer_smp_test=1'), ['blazer_fast_first=1', 'blazer_smp_report=1', 'blazer_smp_test=1'])

class TwoShapes(unittest.TestCase):
    # mcimg: --cpu-order and --bootcpu --cpus in one tool. Each author's own tests are CpuOrder and ADTTests.test_boot_mpidr_*.
    def ns(self, **k):
        d = dict(bootcpu=None, cpu_order=None, phone_deadline=None, phone_args=None, var_overlay=None, var_overlay_sha=None, touch=False, preflight=True, name='phone-preflight-t2', phone_route='md0-mountroot', phone_root=True, qemu_run=None, soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False, legacy_base=False, kernel=str(X/'image_tool.py'), kernel_sha='0' * 64)
        d.update(k); return T.argparse.Namespace(**d)
    def refused(self, why, **k):
        with self.assertRaises(SystemExit, msg=why) as e: T.build(self.ns(**k))
        self.assertIn(why, str(e.exception)); self.assertFalse((T.RUN/'phone-preflight-t2').exists())
    def k(self, *s):
        d = tempfile.mkdtemp(); p = Path(d)/'k'; p.write_bytes(macho() + b'\0'.join((b'ramfs', b'hk_fb_scanout', b'var.skel', b'rooting on ufsroot0') + s)); return dict(kernel=str(p), kernel_sha=T.sha(p))
    def test_mutually_exclusive(self):
        self.refused('--cpu-order and --bootcpu', cpu_order='5,6,2,3,4,1,0', bootcpu='0x200'); self.refused('--cpu-order and --bootcpu', cpu_order='5,6,2,3,4,1,0', bootcpu='0x200', cpus=5)
        self.refused('no --cpus', cpu_order='5,6,2,3,4,1,0', cpus=7)
        with self.assertRaises(SystemExit): mkadt.build(seed=b'S' * 256, cpus=5, boot_mpidr=0x200, cpu_order=[5, 6, 0])
    def test_empty_order_is_not_no_flag(self): self.refused('--cpu-order', cpu_order='')
    def test_x4_refused_both_ways(self):
        for k in (dict(cpu_order=[7, 0]), dict(cpu_order=[5, 7, 0]), dict(boot_mpidr=0x700), dict(boot_mpidr=0x200, cpus=6)):
            with self.assertRaises(SystemExit, msg=str(k)): mkadt.build(seed=b'S' * 256, **k)
        for n in range(1, 6):
            c = next(x for x in adt.parse(adt.serialize(mkadt.build(seed=b'S' * 256, boot_mpidr=0x500, cpus=n)))[0].children if x.name == 'cpus').children
            self.assertNotIn(struct.pack('<I', 0x700), [x.prop('reg') for x in c]); self.assertNotIn(struct.pack('<I', 0), [x.prop('reg') for x in c])
        self.refused('--cpu-order', cpu_order='7,0'); self.refused('at cpus 1 to 5', bootcpu='0x200', cpus=6, **self.k(b'blazer_bootcpu'))
    def test_qemu_can_still_list_core_7(self):
        c = next(x for x in adt.parse(adt.serialize(mkadt.build(seed=b'S' * 256, qemu=True, phys_base=0x80000000, mem_size=0x80000000, cpu_order=[7, 0])))[0].children if x.name == 'cpus').children
        self.assertEqual([struct.unpack('<I', x.prop('reg'))[0] for x in c], [7, 0])
    def test_cpus_alone_stays_refused(self):
        self.refused('recipe as written', cpus=5); self.refused('needs --phone-route', phone_route=None, cpu_order='5,0')
    def test_fast_first_only_with_order(self):
        self.refused('goes with --cpu-order', phone_args='blazer_fast_first=1'); self.refused('goes with --cpu-order', phone_args='blazer_fast_first=1', bootcpu='0x200', cpus=5)
        with self.assertRaises(SystemExit) as e: T.build(self.ns(phone_args='blazer_fast_first=1', cpu_order='5,0', **self.k()))
        self.assertIn('kernel does not read blazer_fast_first', str(e.exception))  # past the shape gate
    def test_kernel_gates(self):
        self.refused('0722 or 0724', cpu_order='5,0', **self.k(b'blazer_fast_first')); self.refused('0722 or 0724', cpu_order='5,0', **self.k(b'blazer_smp_test'))
        self.refused('0703 or smp 0722', bootcpu='0x200', cpus=5, **self.k(b'blazer_bootcpu')); self.refused('0703 or smp 0722', bootcpu='0x200', cpus=5, **self.k(b'blazer_bootcpu', b'blazer_smp_test'))
        self.refused('0703 or smp 0722', bootcpu='0x200', cpus=5, **self.k(b'blazer_bootcpu', b'CPUs, cpu0 parked in the shim'))
    def test_new_tokens(self):
        for t in ('blazer_aoc=1', 'blazer_battery_chg=1', 'blazer_mem=5', 'blazer_mem=13', 'blazer_mem_test=64', 'blazer_mem_test=4096', 'blazer_mem_report=1', 'blazer_persist=1', 'blazer_persist=3', 'blazer_persist_period=60', 'blazer_rtc=1', 'blazer_keys=1', 'blazer_battery=1', 'blazer_wifi=1', 'blazer_thermal=1', 'hk_overlay=1'): self.assertEqual(T.phone_extra(t), [t])
        for t in ('blazer_mem=4', 'blazer_mem=14', 'blazer_mem_test=65', 'blazer_persist=2', 'blazer_rtc_fake=1'):
            with self.assertRaises(SystemExit, msg=t): T.phone_extra(t)
    def test_window_base(self):
        d = T.adt_facts(adt.serialize(mkadt.build(seed=b'S' * 256, headless=True, disp0=True, phys_base=0x882000000)))['dram']; self.assertEqual(d[0], '0x882000000')
        self.assertEqual(adt.serialize(mkadt.build(seed=b'S' * 256, phys_base=T.PHYS)), adt.serialize(mkadt.build(seed=b'S' * 256)))
    def test_fast_core_1800_needs_thermal_1(self):
        K = self.k(b'blazer_bootcpu', b'blazer_thermal', b'blazer_fast_first', b'blazer_smp_test', b'CPUs, cpu0 parked in the shim')
        w = 'limits.md P1b'
        self.refused(w, phone_deadline=1800, bootcpu='0x200', **K); self.refused(w, phone_deadline=1800, bootcpu='0x200', phone_args='blazer_thermal=2', **K)
        self.refused(w, phone_deadline=1800, bootcpu='0x200', cpus=5, phone_args='blazer_thermal=1', **K); self.refused(w, phone_deadline=1800, cpu_order='5,0', phone_args='blazer_thermal=1', **K)
    def made(self, **k):
        # The line the tool makes, caught at its mkdir; nothing is written.
        K = self.k(b'blazer_bootcpu', b'blazer_thermal', b'blazer_fast_first', b'blazer_smp_test', b'CPUs, cpu0 parked in the shim')
        real_mk = T.Path.mkdir; got = {}
        class Stop(Exception): pass
        def stop(p, *x, **y):
            import inspect
            got['c'] = inspect.currentframe().f_back.f_locals.get('c'); raise Stop()
        T.Path.mkdir = stop
        try:
            with self.assertRaises(Stop): T.build(self.ns(**{**K, **k}))
        finally: T.Path.mkdir = real_mk
        return got['c'].split()
    def test_deadlines(self):
        d = lambda **k: [t for t in self.made(**k) if t.startswith('blazer_deadline=')]
        self.assertEqual(d(), ['blazer_deadline=1800']); self.assertEqual(d(phone_deadline=1800), ['blazer_deadline=1800']); self.assertEqual(d(phone_deadline=300), ['blazer_deadline=300'])
        self.assertEqual(d(bootcpu='0x200'), ['blazer_deadline=900']); self.assertEqual(d(bootcpu='0x200', cpus=5), ['blazer_deadline=900']); self.assertEqual(d(cpu_order='5,6,0'), ['blazer_deadline=900'])
        self.assertEqual(d(bootcpu='0x200', phone_deadline=1800, phone_args='blazer_thermal=1'), ['blazer_deadline=1800']); self.assertEqual(d(bootcpu='0x200', phone_deadline=300), ['blazer_deadline=300']); self.assertEqual(d(cpu_order='5,0', phone_deadline=300), ['blazer_deadline=300'])
    def test_shape_lines(self):
        c = self.made(bootcpu='0x200', cpus=5); self.assertIn('cpus=5', c); self.assertIn('blazer_bootcpu=0x200', c); self.assertNotIn('blazer_fast_first=1', c); self.assertNotIn('cpus=1', c)
        c = self.made(cpu_order='5,6,2,3,4,1,0', phone_args='blazer_fast_first=1'); self.assertIn('cpus=7', c); self.assertIn('blazer_fast_first=1', c); self.assertFalse([t for t in c if t.startswith('blazer_bootcpu')])
        self.assertIn('cpus=1', self.made())
    def test_order_needs_a_recipe(self):
        self.refused('goes with --phone-root or --first-boot', phone_root=False, preflight=False, phone_route=None, cpu_order='5,0', **self.k(b'blazer_fast_first', b'blazer_smp_test'))
    def test_order_numbers_nodes(self):
        c = next(x for x in adt.parse(adt.serialize(mkadt.build(seed=b'S' * 256, cpu_order=[5, 6, 0])))[0].children if x.name == 'cpus').children
        self.assertEqual([struct.unpack('<I', x.prop('cluster-core-id'))[0] for x in c], [0, 1, 2])
    def test_deadline_3600_refused_with_each(self):
        self.refused('--phone-deadline 3600', phone_deadline=3600, cpu_order='5,0', phone_args='blazer_thermal=2', **self.k(b'blazer_fast_first', b'blazer_smp_test', b'blazer_thermal'))
        self.refused('--phone-deadline 3600', phone_deadline=3600, bootcpu='0x200', cpus=5, phone_args='blazer_thermal=2', **self.k(b'blazer_thermal'))
    def test_set_cpus(self):
        self.assertEqual(T.set_cpus('a=1 cpus=1 b=2', 5), 'a=1 cpus=5 b=2')
        for bad in ('a=1 cpus=1 cpus=1', 'a=1', 'cpus=2', 'x_cpus=1', 'a-cpus=1', 'cpus=10'):
            with self.assertRaises(SystemExit, msg=bad): T.set_cpus(bad, 5)
    def test_line_and_adt_must_agree(self):
        a = adt.serialize(mkadt.build(seed=b'S' * 256, cpu_order=[5, 6, 0])); b = adt.serialize(mkadt.build(seed=b'S' * 256, boot_mpidr=0x200, cpus=5))
        T.check_cpu_line(a, 'x cpus=3 y'); T.check_cpu_line(b, 'cpus=5')
        for blob, line in ((a, 'cpus=2'), (a, 'x=1'), (a, 'cpus=3 cpus=3'), (b, 'cpus=1'), (b, 'cpus=3')):
            with self.assertRaises(SystemExit, msg=line): T.check_cpu_line(blob, line)
        for prop, v in (('cluster-type', struct.pack('<I', ord('P'))), ('reg', struct.pack('<I', 0x700))):
            t = mkadt.build(seed=b'S' * 256, cpu_order=[5, 6, 0]); x = next(c for c in t.children if c.name == 'cpus').children[1]; x.props = [(n, f, v if n == prop else o) for n, f, o in x.props]
            with self.assertRaises(SystemExit, msg=prop): T.check_cpu_line(adt.serialize(t), 'cpus=3')
    def test_no_shape_adt_is_cpus_prefix(self):
        for k in (dict(), dict(headless=True, disp0=True), dict(cpus=8), dict(boot_mpidr=0x300)):
            self.assertEqual(adt.serialize(mkadt.build(seed=b'S' * 256, **k)), adt.serialize(mkadt.build(seed=b'S' * 256, cpu_order=None, **k)))

class FirstBootContract(unittest.TestCase):
    def test_headless_adt(self):
        r = adt.parse(adt.serialize(mkadt.build(headless=True)))[0]; names = [c.name for c in r.children]
        for n in ('sweet-fbcon', 'laguna-fbcon', 'laguna-dpu'): self.assertNotIn(n, names)
        io = next(c for c in r.children if c.name == 'arm-io'); self.assertNotIn('disp0', [c.name for c in io.children])
        g = next(c for c in io.children if c.name == 'gic'); self.assertEqual(struct.unpack('<4Q', g.prop('reg')), (0, 0x10000, 0x80000, 0x200000)); self.assertEqual(struct.unpack('<I', g.prop('virtual-timer-intid'))[0], 27)
        self.assertEqual(next(c for c in r.children if c.name == 'chosen').prop('laguna-display-handoff'), b'\0' * 16)
        cpu = next(c for c in r.children if c.name == 'cpus').children; self.assertEqual(len(cpu), 1); self.assertIn(b'tegu,cpu\0', cpu[0].prop('compatible'))
        self.assertIn(b'D421AP\0', r.prop('compatible'))
    def test_manifest_properties_empty(self):
        for k in (dict(), dict(headless=True)):
            c = next(c for c in adt.parse(adt.serialize(mkadt.build(**k)))[0].children if c.name == 'chosen')
            m = next(x for x in c.children if x.name == 'manifest-properties'); self.assertEqual({n for n, f, v in m.props}, {'name', 'AAPL,phandle'})
    def test_cmdline_is_admitted_shape(self):
        class A: phone_root = False; first_boot = True; second_boot = False
        c = T.cmdline(A, 1); self.assertNotIn('mountroot', c); self.assertIn('unentitled_ios_sim_launch=1', c); self.assertIn(' rd=md0 ', c); self.assertIn('blazer_ufs_test=1', c); self.assertLess(len(c), 1024)

class DisplayContract(unittest.TestCase):
    def test_canvas_and_flags(self):
        self.assertEqual(T.adt_facts(adt.serialize(mkadt.build()))['canvas'], [1125, 2436]); self.assertIn('-DTGL_DCS_HANDOFF=1', T.DPU_FLAGS)
    def test_clear_runs_first_and_record_is_off_ufs(self):
        s = (T.SHIM/'shim.c').read_text(); m = s.index('void shim_main'); self.assertLess(s.index('tgl_scanout_takeover_clear();', m), s.index('tgl_stamp(', m))
        self.assertIn('0x95438000', (T.SHIM/'tgl_dcs.h').read_text())

class SecondBoot(unittest.TestCase):
    def test_adt_and_args(self):
        r = adt.parse(adt.serialize(mkadt.build(headless=True, disp0=True)))[0]; io = next(c for c in r.children if c.name == 'arm-io')
        d = next(c for c in io.children if c.name == 'disp0'); self.assertEqual(struct.unpack('<I', d.prop('canvas-width'))[0], 1125); self.assertIn(b'sweet,display', d.prop('compatible'))
        self.assertNotIn('sweet-fbcon', [c.name for c in r.children])
        class A: phone_root = False; first_boot = True; second_boot = True
        c = T.cmdline(A, 1); self.assertTrue(c.endswith('hk_fb_scanout=1 sweetfb_noconsole=1 hk_fb_probe=1')); self.assertLess(len(c), 1024)

class Stability(unittest.TestCase):
    def test_debug_never_0xc(self):
        class A: first_boot = False; second_boot = False; phone_root = False; route = 'ufs'; cpus = 1; args = None
        self.assertIn('debug=0x8 ', T.cmdline(A, 1))
        for x in (True,):
            A.phone_root = x; A.phone_route = 'ufsroot'; self.assertIn('debug=0x8 ', T.cmdline(A, 1))
        self.assertNotIn('debug=0xc', (X/'image_tool.py').read_text())
    def test_no_trustcache(self):
        for k in (dict(), dict(headless=True), dict(headless=True, disp0=True), dict(qemu=True, phys_base=0x80000000, mem_size=0x80000000)):
            self.assertNotIn(b'TrustCache', adt.serialize(mkadt.build(**k)))
        with self.assertRaises(SystemExit): T.adt_facts(adt.serialize(mkadt.build()) + b'TrustCache')
class PhoneRoot(unittest.TestCase):
    def test_cmdline(self):
        class A: phone_root = True; phone_route = 'ufsroot'
        c = T.cmdline(A, 1); self.assertLess(len(c), 1024)
        A.phone_route = 'md0-mountroot'; m = T.cmdline(A, 1); self.assertIn(' rd=md0 blazer_ufs_mountroot=1 ', m); self.assertNotIn('ufsroot0', m); self.assertLess(len(m), 1024); A.phone_route = 'ufsroot'
        for t in ('rd=ufsroot0', 'varfs=1', 'hk_fb_scanout=1', 'sweetfb_noconsole=1', 'hk_fb_probe=1', 'interrupt-masked-debug-mode=0', 'unentitled_ios_sim_launch=1', 'sweetarm64e=1', 'blazer_deadline=1800'): self.assertIn(t, c)
        for t in ('rootrw', 'blazer_ufs_test', 'mountroot', 'rd=md0', 'sched_preemption', 'wdt=', '-v', 'epoch=', 'blazer_ufs_fake'): self.assertNotIn(t, c)
    def test_touch_adds_only_that(self):
        class A: phone_root = True; phone_route = 'md0-mountroot'; touch = False
        base = T.cmdline(A, 1); A.touch = True; c = T.cmdline(A, 1)
        self.assertEqual(c, base + ' blazer_touch=1'); self.assertLess(len(c), 1024)
    def test_touch_needs_phone_root_and_args_still_refused(self):
        b = T.argparse.Namespace(var_overlay=None, var_overlay_sha=None, phone_args=None, preflight=False, name='t-gate', phone_route='md0-mountroot', phone_root=True, qemu_run='go-5', soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args='blazer_touch=1', canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False, touch=False)
        with self.assertRaises(SystemExit): T.build(b)
        self.assertFalse((T.RUN/'t-gate').exists())
    def test_allow_list(self):
        good = 'blazer_touch=1 blazer_touch_bars=1 touch_flip=3 hk_top=30 hk_ui=300:t169.280,w120,h,w60'
        self.assertEqual(T.phone_extra(good), good.split()); self.assertEqual(T.phone_extra(None), [])
        for bad in ('rootrw=1', 'wdt=-1', 'blazer_touch=2', 'touch_flip=4', 'hk_top=4', 'hk_top=601', 'hk_ui=abc', 'hk_ui=1:X Y', 'blazer_touch=1 blazer_touch=1', 'blazer_touch_bars=1x', 'varfs=0', 'debug=0xc'):
            with self.assertRaises(SystemExit, msg=bad): T.phone_extra(bad)
    def test_exact_token(self):
        self.assertEqual(T.phone_extra('validation_disables=0x39d64'), ['validation_disables=0x39d64'])
        for bad in ('validation_disables=0x1', 'validation_disables=0x39d640', 'validation_disables'):
            with self.assertRaises(SystemExit, msg=bad): T.phone_extra(bad)
    def test_overlay_tokens(self):
        for good in ('hk_fb_te=1', 'hk_fb_te=2', 'hk_panel_hz=120', 'hk_panel_hz=60', 'hk_panel_hz=30', 'hk_panel_hz=10', 'hk_panel_off=1', 'hk_fb_period=1', 'blazer_ufs_hold=1', 'blazer_battery=1', 'blazer_battery=2', 'blazer_sensors=1', 'blazer_sensors=2', 'blazer_sensors=3', 'blazer_sensors_flip=0', 'blazer_sensors_flip=7', 'blazer_ufs_spin_us=300', 'blazer_ufs_cost=1', 'hk_clk=6', 'hk_clk=9', 'hk_clk=10', 'hk_clk=599', 'hk_clk=600', 'hk_bench=1', 'hk_amu=1', 'hk_pmu=1', 'hk_pmu=2', 'hk_fb_fast=1', 'blazer_ic_va=1', 'hk_fb_bench=2', 'blazer_wifi=1', 'blazer_wifi_end=60', 'blazer_haptic=1', 'blazer_haptic=3', 'blazer_thermal=1', 'blazer_thermal=2', 'blazer_thermal_panic_c=30', 'blazer_thermal_panic_c=102', 'blazer_rtc=1', 'blazer_keys=1', 'blazer_usbcon=1', 'blazer_usbcon=2', 'blazer_ufs_multi=1', 'blazer_cs_nohash=1', 'atm_diagnostic_config=0x400', 'hk_fb_scale=1', 'hk_fb_scale=2', 'hk_fb_filter=1', 'hk_overlay=1', 'hk_overlay=0x3', 'hk_deny=PerfPowerServices', 'hk_deny=a.b,c-d', 'hk_env=backboardd:A=1', 'hk_env=SpringBoard+backboardd:CA_X=1;B=two~words,lsd:C=', ):
            self.assertEqual(T.phone_extra(good), [good], good)
        for bad in ('hk_fb_te=0', 'hk_fb_te=3', 'hk_panel_hz=90', 'hk_panel_hz=0', 'hk_panel_off=0', 'hk_panel_hz=60 hk_panel_hz=30', 'hk_fb_period=0', 'hk_fb_period=2', 'blazer_ufs_hold=0', 'blazer_battery=0', 'blazer_battery=3', 'blazer_battery_chg=2', 'blazer_aoc=0', 'blazer_aoc=2', 'blazer_sensors=0', 'blazer_sensors=4', 'blazer_sensors=12', 'blazer_sensors_flip=8', 'blazer_sensors_flip=', 'blazer_ufs_spin_us=299', 'blazer_ufs_spin_us=0', 'blazer_ufs_cost=0', 'blazer_ufs_cost=2', 'hk_clk=5', 'hk_clk=0', 'hk_clk=601', 'hk_clk=06', 'hk_clk=', 'hk_bench=2', 'hk_amu=0', 'hk_pmu=3', 'hk_fb_fast=2', 'blazer_ic_va=0', 'hk_fb_bench=1', 'blazer_wifi=2', 'blazer_haptic=0', 'blazer_haptic=2', 'blazer_haptic=4', 'blazer_thermal=0', 'blazer_thermal=3', 'blazer_thermal_panic_c=29', 'blazer_thermal_panic_c=103', 'blazer_rtc=0', 'blazer_rtc=2', 'blazer_keys=0', 'blazer_keys=2', 'blazer_usbcon=0', 'blazer_usbcon=3', 'blazer_ufs_multi=0', 'blazer_cs_nohash=2', 'atm_diagnostic_config=0x401', 'up_style_idle_exit=1', 'hk_fb_scale=0', 'hk_fb_scale=3', 'hk_fb_filter=0', 'hk_fb_filter=2', 'hk_fb_scale=1 hk_fb_scale=2', 'hk_overlay=0', 'hk_overlay=x', 'hk_overlay=', 'hk_deny=', 'hk_deny=a,,b', 'hk_deny=a/b', 'hk_env=', 'hk_env=prog', 'hk_env=prog:', 'hk_env=:A=1', 'hk_env=p:1A=2', 'hk_env=p/q:A=1'):
            with self.assertRaises(SystemExit, msg=bad): T.phone_extra(bad)
    OV = T.R/'ios26-overlay-r1/overlays/p5-first.ovl'; OVS = 'f649fc383cf00e3537697aa6925b2bf2a21f7a9843e55592cc0939624203cf08'
    def ns(self, **k):
        d = dict(phone_args=None, var_overlay=None, var_overlay_sha=None, touch=False, preflight=True, name='phone-preflight-tov', phone_route='md0-mountroot', phone_root=True, qemu_run=None, soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False)
        d.update(k); return T.argparse.Namespace(**d)
    def test_overlay_pairing(self):
        with self.assertRaises(SystemExit): T.check_overlay(self.ns(phone_args='hk_overlay=3'))
        with self.assertRaises(SystemExit): T.check_overlay(self.ns(var_overlay=str(self.OV), var_overlay_sha=self.OVS))
        with self.assertRaises(SystemExit): T.check_overlay(self.ns(phone_args='hk_overlay=3', var_overlay=str(self.OV), var_overlay_sha='0' * 64))
        with self.assertRaises(SystemExit): T.check_overlay(self.ns(phone_root=False, phone_args='hk_overlay=3', var_overlay=str(self.OV), var_overlay_sha=self.OVS))
        self.assertIsNone(T.check_overlay(self.ns()))
    def test_overlay_masks_against_real_file(self):
        if not self.OV.exists(): self.skipTest('overlay absent')
        ok = T.check_overlay(self.ns(phone_args='hk_overlay=3', var_overlay=str(self.OV), var_overlay_sha=self.OVS))
        self.assertEqual((ok['mask'], ok['sha256'], ok['groups']), (3, self.OVS, [0, 1, 2, 3, 4, 5, 6]))
        for mask in ('0x7f', '33', '11'): T.check_overlay(self.ns(phone_args='hk_overlay=' + mask, var_overlay=str(self.OV), var_overlay_sha=self.OVS))
        with self.assertRaises(SystemExit): T.check_overlay(self.ns(phone_args='hk_overlay=0x80', var_overlay=str(self.OV), var_overlay_sha=self.OVS))
    def test_overlay_corrupt_refused(self):
        if not self.OV.exists(): self.skipTest('overlay absent')
        d = bytearray(self.OV.read_bytes()); d[100] ^= 1
        with self.assertRaises(SystemExit): T.overlay_groups(bytes(d))
        with self.assertRaises(SystemExit): T.overlay_groups(bytes(self.OV.read_bytes()) + b'x')
    def test_overlay_placed_in_payload_and_shim_accepts(self):
        if not self.OV.exists(): self.skipTest('overlay absent')
        d = tempfile.mkdtemp(); k, ap, p = Path(d)/'k', Path(d)/'a', Path(d)/'p'; k.write_bytes(macho(text=0xfffffe0007004000)); ap.write_bytes(adt.serialize(mkadt.build(headless=True, disp0=True)))
        raw, i = mkpayload.build(k, ap, 'a=1', var_overlay_path=self.OV); p.write_bytes(raw); plan = T.contract_check(p)
        pa, size = int(i['var_overlay'][0], 16), int(i['var_overlay'][1], 16)
        self.assertGreater(pa, 0xa01004000); self.assertLessEqual(pa + size, int(plan['adt_pa'], 16)); self.assertGreaterEqual(raw.find(self.OV.read_bytes()), 0)
        hdr = raw[0x48:0x48]
        n = struct.unpack_from('<II', raw, 8)[1]; ao, az = struct.unpack_from('<QQ', raw, 0x20)
        root = adt.parse(raw[ao:ao + az])[0]; c = next(x for x in root.children if x.name == 'chosen'); m = next(x for x in c.children if x.name == 'memory-map')
        self.assertEqual(struct.unpack('<2Q', m.prop('HKVarOverlay')), (pa, size)); self.assertIsNone(m.prop('RAMDisk'))
    def test_line_limit_applies_with_extras(self):
        class A: phone_root = True; phone_route = 'md0-mountroot'; touch = False; phone_args = 'hk_ui=1:' + 'a' * 700
        self.assertGreaterEqual(len(T.cmdline(A, 1)), T.mkpayload.BOOT_LINE_LENGTH)  # build() refuses this length
        b = T.argparse.Namespace(bootcpu=None, var_overlay=None, var_overlay_sha=None, phone_args=A.phone_args, touch=False, preflight=True, name='phone-preflight-tmax', phone_route='md0-mountroot', phone_root=True, qemu_run=None, soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False, kernel=str(T.R/'ios26-release-r1/artifacts/kernel.ios26-p4'), kernel_sha='22022cdadbaef0980b2c1378cb5c81025a6993c0c7e60fd4797ccac1f5157a91', legacy_base=False)
        with self.assertRaises(SystemExit): T.build(b)
        self.assertFalse((T.RUN/'phone-preflight-tmax').exists())
    def test_extras_need_phone_root(self):
        b = T.argparse.Namespace(var_overlay=None, var_overlay_sha=None, phone_args='hk_top=30', touch=False, preflight=False, name='t-gate', phone_route=None, phone_root=False, qemu_run=None, soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False, kernel=str(X/'image_tool.py'), kernel_sha='0'*64)
        with self.assertRaises(SystemExit): T.build(b)
        self.assertFalse((T.RUN/'t-gate').exists())
    def test_canvas_only_the_one(self):
        base = dict(var_overlay=None, var_overlay_sha=None, phone_args=None, touch=False, preflight=False, name='t-gate', phone_route='md0-mountroot', phone_root=True, qemu_run=None, soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, gamut=None, route='ufs', cpus=1, test_kernel=False)
        for bad in ('1125x2436', '1280x2856', '1125x2511 ', '1125X2511'):
            with self.assertRaises(SystemExit) as e: T.build(T.argparse.Namespace(canvas=bad, **base))
            self.assertIn('only --canvas', str(e.exception))
        with self.assertRaises(SystemExit) as e: T.build(T.argparse.Namespace(canvas='1125x2511', **base))
        self.assertIn('--qemu-run', str(e.exception))  # past the canvas check, the gate still stands
        self.assertFalse((T.RUN/'t-gate').exists())
        d = adt.parse(adt.serialize(mkadt.build(headless=True, disp0=True, canvas=(1125, 2511))))[0]
        self.assertEqual(T.adt_facts(adt.serialize(d))['canvas'], [1125, 2511])
    def test_qemu_run_folders(self):
        self.assertEqual(T.QEMU_RUN_DIRS, ('ios26-qemu-r1', 'ios26-blazer-r1', 'ios26-native-r1', 'ios26-overlay-r1'))
        b = T.argparse.Namespace(bootcpu=None, var_overlay=None, var_overlay_sha=None, phone_args=None, touch=False, preflight=False, name='t-gate', phone_route='md0-mountroot', phone_root=True, qemu_run='no-such-run-anywhere', soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False)
        with self.assertRaises(SystemExit) as e: T.build(b)
        self.assertIn('--qemu-run', str(e.exception)); self.assertFalse((T.RUN/'t-gate').exists())
    def test_phone_deadline_gates(self):
        K = T.R/'ios26-release-r1/artifacts/kernel.ios26-p4'
        if not K.exists(): self.skipTest('kernel absent')
        base = dict(bootcpu=None, var_overlay=None, var_overlay_sha=None, touch=False, preflight=True, name='phone-preflight-tdl', phone_route='md0-mountroot', phone_root=True, qemu_run=None, soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False, kernel=str(K), kernel_sha=T.sha(K), legacy_base=False)
        for args, dl, why in ((None, 3600, 'armed guard'), (None, 2400, '1800 or 3600')):
            with self.assertRaises(SystemExit) as e: T.build(T.argparse.Namespace(phone_args=args, phone_deadline=dl, **base))
            self.assertIn(why, str(e.exception))
        self.assertFalse((T.RUN/'phone-preflight-tdl').exists())
    def test_soak_lines(self):
        class A: soak = 9
        c = T.cmdline(A, 1); self.assertIn('blazer_ufs_fullcheck=9', c); self.assertIn('rd=md0 blazer_ufs_mountroot=1', c); self.assertNotIn('rootrw', c); self.assertNotIn('blazer_touch', c); self.assertNotIn('hk_fb', c)
        A.soak = 0; c = T.cmdline(A, 1); self.assertIn('rd=md0', c); self.assertNotIn('blazer_ufs', c)
    def test_fullcheck_line(self):
        class A: soak = None; phone_root = False; first_boot = True; second_boot = False; fullcheck = 'x'
        c = T.cmdline(A, 1); self.assertIn(' blazer_ufs_fullcheck=1', c); self.assertIn('blazer_ufs_deadline=1200', c); self.assertNotIn('deadline=300', c)
        A.fullcheck = None; self.assertNotIn('fullcheck', T.cmdline(A, 1))
    def test_gates(self):
        b = T.argparse.Namespace(var_overlay=None, var_overlay_sha=None, phone_args=None, preflight=False, name='t-gate', phone_route='ufsroot', phone_root=True, qemu_run=None, touch=False, soak=None, fullcheck=None, readback=None, first_boot=False, second_boot=False, dpu=False, md0=None, md1=None, args=None, canvas=None, gamut=None, route='ufs', cpus=1, test_kernel=False)
        with self.assertRaises(SystemExit): T.build(b)
        self.assertFalse((T.RUN/'t-gate').exists())
        b.preflight = True
        with self.assertRaises(SystemExit): T.build(b)  # wrong name
        self.assertFalse((T.RUN/'t-gate').exists())

class PayloadTests(unittest.TestCase):
    def build(self, m, cmd='a=1', **k):
        d = tempfile.mkdtemp(); kp, ap = Path(d)/'k', Path(d)/'a'; kp.write_bytes(m); ap.write_bytes(adt.serialize(mkadt.build()))
        return mkpayload.build(kp, ap, cmd, **k), d
    def test_virt_base_is_block_of_lowest_segment(self):
        (raw, i), _ = self.build(macho()); self.assertEqual(i['virt_base'], hex(0xfffffff006000000))
        (raw, i), _ = self.build(macho(prelink=0xfffffff004004000)); self.assertEqual(i['virt_base'], hex(0xfffffff004000000))
        (raw, i), _ = self.build(macho(), legacy_base=True); self.assertEqual(i['virt_base'], hex(0xfffffff004000000))
    def test_real_12377_layout(self):
        t = 0xfffffe0007004000
        (raw, i), d = self.build(macho(text=t)); self.assertEqual(i['virt_base'], hex(0xfffffe0006000000))
        p = Path(d)/'p'; p.write_bytes(raw); self.assertEqual(T.contract_check(p)['entry_pa'], hex(0xa00000000 + 0x1008000))
    def test_shim_refuses_below_kernel_range(self):
        (raw, i), d = self.build(macho(text=0xfffffe0007004000)); b = bytearray(raw); struct.pack_into('<Q', b, 0x10, 0xfffffc0006000000); p = Path(d)/'p'; p.write_bytes(b)
        with self.assertRaises(SystemExit): T.contract_check(p)
    def test_shim_accepts_it_and_entry_lands_right(self):
        (raw, i), d = self.build(macho()); p = Path(d)/'p'; p.write_bytes(raw); plan = T.contract_check(p)
        self.assertEqual(plan['entry_pa'], hex(0xa00000000 + 0x1008000))
    def test_shim_refuses_bad_base(self):
        (raw, i), d = self.build(macho()); b = bytearray(raw); struct.pack_into('<Q', b, 0x10, 0xfffffff006001000); p = Path(d)/'p'; p.write_bytes(b)
        with self.assertRaises(SystemExit): T.contract_check(p)
    def test_cmdline_not_truncated(self):
        with self.assertRaises(ValueError): self.build(macho(), cmd='x' * 1024)
    def test_ramdisks_published(self):
        d = tempfile.mkdtemp(); r = Path(d)/'r'; r.write_bytes(b'R' * 0x5000)
        (raw, i), _ = self.build(macho(), ramdisk_path=r, ramdisk1_path=r); self.assertIn('ramdisk1', i)

class LineLength(unittest.TestCase):
    def test_limit_is_xnus(self):
        self.assertEqual((mkpayload.BOOT_LINE_LENGTH, mkpayload.SEG_TABLE), (1024, 0x448))
        h = (T.SHIM/'payload.h').read_text(); self.assertIn('TGL_BOOT_LINE_LENGTH 1024', h)
        self.assertIn('TGL_UFS_CMDLINE_BYTES 1024', (T.SHIM/'tgl_ufs.h').read_text())
    def payload(self, cmd):
        d = tempfile.mkdtemp(); k, ap, p = Path(d)/'k', Path(d)/'a', Path(d)/'p'
        k.write_bytes(macho(text=0xfffffe0007004000)); ap.write_bytes(adt.serialize(mkadt.build()))
        raw, i = mkpayload.build(k, ap, cmd); p.write_bytes(raw); return raw, p
    def test_longest_line_passes_the_shim_validator(self):
        raw, p = self.payload('x' * 1023); T.contract_check(p)
        self.assertEqual(raw[0x48:0x48 + 1024], b'x' * 1023 + b'\0'); self.assertEqual(struct.unpack_from('<I', raw, 8)[0], 2)
    def test_shim_refuses_version_1_and_unterminated(self):
        raw, p = self.payload('a=1')
        v1 = bytearray(raw); struct.pack_into('<I', v1, 8, 1); p.write_bytes(v1)
        with self.assertRaises(SystemExit): T.contract_check(p)
        full = bytearray(raw); full[0x48:0x48 + 1024] = b'x' * 1024; p.write_bytes(full)
        with self.assertRaises(SystemExit): T.contract_check(p)
    def admit(self, line, live):
        """The shim's own function text on the host, with its neighbours stubbed."""
        src = (T.SHIM/'tgl_ufs.c').read_text(); a = src.index('static int u_prefix'); b = src.index('\n}\n', src.index('int tgl_ufs_cmdline_admit')) + 3
        d = Path(tempfile.mkdtemp()); (d/'t.c').write_text('''#include <stdio.h>
#include <stdint.h>
#include <string.h>
#define TGL_UFS_CMDLINE_BYTES 1024u
#define TGL_UFS_HANDOFF 1
#define TGL_STAGE_UFS_LIVE 1
#define TGL_STAMP_F_REFUSED 1
struct tgl_ufs_result { int live; unsigned proven_lun; };
static void u_copy(char *d, const char *s, unsigned n) { memcpy(d, s, n); }
static void tgl_stamp(int a, int b, uint64_t c) { }
static void laguna_usb_log(const char *s) { printf("LOG %zu\\n", strlen(s)); }
static int ufsh_cmdline_ok(const char *c, unsigned l) { return strstr(c, "blazer_ufs=2") != 0; }
''' + src[a:b] + '''
int main(int c, char **v) { static char buf[2048]; size_t n = fread(buf, 1, 1024, stdin); struct tgl_ufs_result r = { v[1][0] == '1', 0 };
 int rc = tgl_ufs_cmdline_admit(buf, &r); printf("%d %zu\\n", rc, strnlen(buf, 2048)); fwrite(buf, 1, strnlen(buf, 2048), stdout); return 0; }
''')
        subprocess.run(['/usr/bin/cc', '-w', '-o', str(d/'t'), str(d/'t.c')], check=True)
        return subprocess.run([str(d/'t'), '1' if live else '0'], input=line, capture_output=True, check=True).stdout
    def test_admit_long_live_line_unchanged(self):
        line = (b'rd=md0 blazer_ufs=2 ' + b'y' * 1100)[:1023] + b'\0'
        self.assertIn(b'0 1023\n', self.admit(line, True))
    def test_admit_rewrite_keeps_tail_past_608(self):
        tail = b'keep=' + b'z' * 800; line = b'rd=ufsroot0 blazer_ufs=2 blazer_ufs_lun=0 ' + tail + b'\0'
        o = self.admit(line, False); self.assertIn(b'rd=md0 ' + tail, o); self.assertNotIn(b'blazer_ufs', o.split(b'\n')[-1])
    def test_admit_unterminated_refused(self):
        self.assertIn(b'-1 ', self.admit(b'x' * 1024, False))

class KernelGuardTests(unittest.TestCase):
    def k(self, m):
        d = tempfile.mkdtemp(); p = Path(d)/'k'; p.write_bytes(m); return p, T.sha(p)
    def test_refuses_g4_console_write(self):
        code = struct.pack('<II', 0xd29e0000, 0xf2bfa7e0)  # movz x0,#0xf000; movk x0,#0xfd3f,lsl#16
        p, s = self.k(macho(code))
        with self.assertRaises(SystemExit): T.check_kernel(p, s, False)
        self.assertEqual(list(T.check_kernel(p, s, True)['g4_writes']), ['0xfd3ff000'])
    def test_other_register_or_far_apart_ok(self):
        p, s = self.k(macho(struct.pack('<II', 0xd29e0000, 0xf2bfa7e1))); self.assertEqual(T.check_kernel(p, s, False)['g4_writes'], {})
    def test_refuses_other_xnu_and_wrong_hash(self):
        p, s = self.k(macho().replace(b'xnu-12377', b'xnu-08796'))
        with self.assertRaises(SystemExit): T.check_kernel(p, s, False)
        p, s = self.k(macho())
        with self.assertRaises(SystemExit): T.check_kernel(p, '0' * 64, False)

class BootArgsLayout(unittest.TestCase):
    def test_shim_matches_12377_boot_h(self):
        s = (T.SHIM/'loader.c').read_text(); self.assertIn('#define BOOT_LINE_LENGTH\t1024', s); self.assertIn('== 1144', s)
        h = T.R/'ios26-kernel-r1/work/xnu/pexpert/pexpert/arm64/boot.h'
        if h.exists(): self.assertIn('#define BOOT_LINE_LENGTH 1024', h.read_text())

class CpuHealthProfile(unittest.TestCase):
    def ns(self, **kw):
        a = TwoShapes().ns(cpu_health=True, name='cpu-health-unit', phone_root=True,
            preflight=False, bootcpu='0x200', cpus=5, window_base='0x882000000',
            phone_deadline=300, kernel_sha=T.CPU_HEALTH_KERNEL_SHA, qemu_run='overlay-1',
            canvas=T.PHONE_CANVAS, var_overlay='overlay.ovl', var_overlay_sha=T.CPU_HEALTH_OVERLAY_SHA)
        for k, v in kw.items(): setattr(a, k, v)
        return a

    def test_exact_common_configuration_and_default_refusal(self):
        a = self.ns(); self.assertTrue(T.cpu_health_profile(a))
        self.assertEqual(a.phone_args, T.CPU_HEALTH_ARGS)
        self.assertEqual(len(T.cpu_health_line().encode()), 1000)
        with self.assertRaises(SystemExit): T.phone_extra(T.CPU_HEALTH_ARGS)
        for t in ('blazer_gov_verify=1', 'blazer_gov_health=1', 'blazer_gov_probe=1', 'blazer_gov_hi=0'):
            with self.assertRaises(SystemExit): T.phone_extra(t)
        a = self.ns(phone_args=' '.join(reversed(T.CPU_HEALTH_ARGS.split())))
        self.assertTrue(T.cpu_health_profile(a)); self.assertEqual(a.phone_args, T.CPU_HEALTH_ARGS)
        self.assertFalse(T.cpu_health_profile(self.ns(cpu_health=False)))

    def test_refuses_changed_context_before_outputs(self):
        for k, v in [('kernel_sha', '0'*64), ('bootcpu', '0x300'), ('bootcpu', None), ('cpus', 1),
                ('cpus', 6), ('window_base', '0xa00000000'), ('phone_deadline', 900),
                ('var_overlay_sha', '0'*64), ('var_overlay', None), ('canvas', None),
                ('qemu_run', 'other'), ('phone_root', False), ('phone_route', 'ufsroot'),
                ('cpu_order', ''), ('cpu_order', '0,1')]:
            with self.subTest(k=k, v=v), self.assertRaises(SystemExit): T.cpu_health_profile(self.ns(**{k:v}))
        for k in ('cpu_audit', 'test_kernel', 'preflight', 'touch', 'dpu', 'legacy_base',
                'first_boot', 'second_boot', 'fullcheck', 'readback', 'persist', 'soak'):
            with self.subTest(k=k), self.assertRaises(SystemExit): T.cpu_health_profile(self.ns(**{k:True}))

    def test_refuses_removed_added_duplicate_or_high_tokens(self):
        toks = T.CPU_HEALTH_ARGS.split()
        for i in range(len(toks)):
            with self.subTest(removed=toks[i]), self.assertRaises(SystemExit):
                T.cpu_health_profile(self.ns(phone_args=' '.join(toks[:i]+toks[i+1:])))
        for t in ('blazer_gov_cap=13', 'blazer_gov_hi=0', 'blazer_gov_probe=1', 'blazer_cpu0_cas_probe=1',
                'blazer_aoc=1', 'blazer_gpu_tipc=5', 'blazer_persist=1', 'blazer_thermal=1'):
            with self.subTest(added=t), self.assertRaises(SystemExit):
                T.cpu_health_profile(self.ns(phone_args=T.CPU_HEALTH_ARGS+' '+t))
        with self.assertRaises(SystemExit): T.phone_extra(T.CPU_HEALTH_ARGS+' blazer_gov_health=1', cpu_health=True)

    def fixture(self, tmp):
        # Exercise the real payload producer/checker with owned Mach-O bytes.
        k = Path(tmp)/'kernel'; k.write_bytes(macho(text=0xfffffe0007004000))
        ov = Path(tmp)/'overlay'; ov.write_bytes(b'owned-overlay-fixture')
        blob = adt.serialize(mkadt.build(headless=True, disp0=True, cpus=5,
            boot_mpidr=0x200, canvas=(1125,2511), phys_base=0x882000000))
        blob += b'\0'*(-len(blob)%8); p = Path(tmp)/'adt'; p.write_bytes(blob)
        raw, _ = mkpayload.build(k, p, T.cpu_health_line(), None, None, False, ov)
        m = dict(mach=T.sha(k), bootcpu='0x200', cpus=5, phone_root=True, route='ufs',
            cmdline=T.cpu_health_line(), cmdline_bytes=1000, adt_facts=T.adt_facts(blob),
            window_base='0x882000000', var_overlay=dict(path=str(ov),sha256=T.sha(ov)),
            cpu_health=dict(version=1,cap=16,required_mask=262,high_clock=False,
                stepdown_probe=False,physical_acceptance=False,kernel_path=str(k)))
        return m, blob, raw

    def test_embedded_bytes_and_context_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            m, blob, raw = self.fixture(tmp)
            with patch.object(T,'CPU_HEALTH_KERNEL_SHA',m['mach']), patch.object(T,'CPU_HEALTH_OVERLAY_SHA',m['var_overlay']['sha256']):
                T.check_cpu_health(m,blob,raw)
                for key, value in [('mach','0'*64),('bootcpu','0x300'),('cpus',1),('cmdline',m['cmdline'].replace('cap=16','cap=13')),('window_base','0xa00000000')]:
                    n = {**m,key:value}
                    with self.subTest(key=key), self.assertRaises(SystemExit): T.check_cpu_health(n,blob,raw)
                # Stripping the receipt and lying about the manifest line still
                # exposes the real health tokens in the embedded payload header.
                n = {**m, 'cpu_health':None, 'cmdline':'debug=0x8 cpus=5'}
                with self.assertRaises(SystemExit): T.check_cpu_health(n,blob,raw)
                changed = bytearray(raw); changed[-1] ^= 1
                with self.assertRaises(SystemExit): T.check_cpu_health(m,blob,changed)
                # A different, structurally valid ADT cannot be relabelled.
                other = adt.serialize(mkadt.build(headless=True,disp0=True,cpus=5,
                    boot_mpidr=0x300,canvas=(1125,2511),phys_base=0x882000000))
                with self.assertRaises(SystemExit): T.check_cpu_health(m,other,raw)
                for key in ('kernel_path','physical_acceptance','stepdown_probe','high_clock','required_mask'):
                    n = {**m,'cpu_health':{**m['cpu_health'],key:True}}
                    with self.subTest(key=key), self.assertRaises(SystemExit): T.check_cpu_health(n,blob,raw)
                Path(m['cpu_health']['kernel_path']).write_bytes(b'changed source')
                with self.assertRaises(SystemExit): T.check_cpu_health(m,blob,raw)

if __name__ == '__main__': unittest.main()
