#!/usr/bin/env python3
"""m1box (Linux) port of ios26-apps-r1/tools/qemu-ufsroot.py. Same guest: addresses, ADT, boot-args, stub, framebuffer and
ramoops capture, backing-file layout. Host differences only: QEMU 11.1.2 from a user prefix, /proc/meminfo headroom, disk
check on the run directory, N admission slots, and --accel kvm (the stub already enters at EL1 when CurrentEL==1;
-cpu host,pauth=off; the ADT timebase becomes the host CNTFRQ). QEMU only; says nothing about Tensor.
research/ios26-ram-r1 variant: --loader-gib L hands the kernel memSize = memSizeActual = ADT dram-size = L GiB of the
SIZE GiB backed window, as the phone loader hands 4 GiB of its bank, so blazer_mem=GIB can grow it. Lives in the repo; the
rig directory comes from HACKIOS_QEMU_RIG.
usage: qemu-ufsroot.py NAME --kernel K --root R [--accel tcg|kvm] [--slots N] [--dry] [--window-gib N] [--args "..."] ..."""
import argparse, fcntl, hashlib, json, os, platform, re, shutil, socket, struct, subprocess, sys, time, zlib
from pathlib import Path
sys.dont_write_bytecode = True
D = Path(os.environ.get('HACKIOS_QEMU_RIG', '/data/hackios-qemu'))/'research/ios26-apps-r1'; R = D.parent; BC = R/'ios26-bootchain-r1/tools'
sys.path.insert(0, str(BC)); import mkpayload, adt
PREFIX = Path(os.environ.get('HACKIOS_QEMU_PREFIX', '/data/hackios-qemu/prefix'))
QEMU = str(PREFIX/'usr/bin/qemu-system-aarch64')
QENV = dict(os.environ, LD_LIBRARY_PATH=str(PREFIX/'usr/lib'), QEMU_MODULE_DIR=str(PREFIX/'usr/lib/qemu'))
LOCK = Path(os.environ.get('HACKIOS_QEMU_LOCK', '/data/hackios-qemu/slot.lock')); PAGE = 0x4000
BASE, FB_PA, FBW, FBH, FBS = 0xa00000000, 0xf0000000, 1280, 2856, 5120
HEADROOM = 7 << 29
DISK_FLOOR = int(float(os.environ.get('HACKIOS_QEMU_DISK_FLOOR_GIB', '20')) * (1 << 30))
TCG_TIMEBASE = 62500000   # mkadt --qemu; what the Mac runs boot with
PANIC = re.compile(r'panic\(cpu|Debugger message|Please go to|Synchronous exception|kernel trap|halt_all_cpus|Waiting for root')
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''): h.update(b)
    return h.hexdigest()
def headroom():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) * 1024
    return 0
def host_cntfrq():
    """KVM passes the host counter frequency through to the guest; the kernel logs it at boot."""
    if os.environ.get('HACKIOS_CNTFRQ'): return int(os.environ['HACKIOS_CNTFRQ'])
    t = subprocess.run(['journalctl', '-k', '-b', '0', '--no-pager', '-o', 'cat'], capture_output=True, text=True).stdout
    m = re.search(r'arch_timer: cp15 timer(?:\(s\))? running at (\d+)\.(\d+)MHz', t)
    if not m: sys.exit('host CNTFRQ unknown: no arch_timer line in journalctl -k; set HACKIOS_CNTFRQ')
    return int(m[1])*1000000 + int(m[2].ljust(6, '0')[:6])
def nqemu():
    # Linux truncates comm to 15 chars, so `pgrep -x qemu-system-aarch64` never matches; match the full command line.
    return len(subprocess.run(['pgrep', '-f', r'(^|/)qemu-system-aarch64( |$)'], capture_output=True).stdout.split())
class QMP:
    def __init__(s, sock):
        s.s = socket.socket(socket.AF_UNIX); s.s.settimeout(120); s.s.connect(str(sock)); s.f = s.s.makefile('rw'); json.loads(s.f.readline()); s.n = 0; s.call('qmp_capabilities')
    def call(s, cmd, **a):
        s.n += 1; s.f.write(json.dumps(dict(execute=cmd, arguments=a, id=s.n))+'\n'); s.f.flush()
        while True:
            r = json.loads(s.f.readline())
            if r.get('id') == s.n:
                if 'error' in r: raise RuntimeError(r)
                return r['return']
    def hmp(s, x): return s.call('human-monitor-command', **{'command-line': x})
def png(raw, path, s):
    w = len(range(0, FBW, s)); rows = bytearray()
    for y in range(0, FBH, s):
        r = raw[y*FBS:y*FBS+FBW*4]; o = bytearray(w*3); o[0::3] = r[2::4*s]; o[1::3] = r[1::4*s]; o[2::3] = r[0::4*s]; rows += b'\0'+o
    ch = lambda k, d: struct.pack('>I', len(d))+k+d+struct.pack('>I', zlib.crc32(k+d))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+ch(b'IHDR', struct.pack('>IIBBBBB', w, len(range(0, FBH, s)), 8, 2, 0, 0, 0))+ch(b'IDAT', zlib.compress(bytes(rows), 1))+ch(b'IEND', b''))
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('--kernel', type=Path, required=True); ap.add_argument('--root', type=Path, required=True); ap.add_argument('--window-gib', type=int, default=6); ap.add_argument('--loader-gib', type=int, default=None)
    ap.add_argument('--args', default=''); ap.add_argument('--runtime', type=int, default=300); ap.add_argument('--idle', type=int, default=90); ap.add_argument('--cpu', default=None); ap.add_argument('--scale', type=int, default=2); ap.add_argument('--ram-gib', type=int, default=3); ap.add_argument('--adt-opts', default=''); ap.add_argument('--wait', type=int, default=120)
    ap.add_argument('--ramdisk-root',action='store_true'); ap.add_argument('--route-md',action='store_true'); ap.add_argument('--var-overlay', type=Path)
    ap.add_argument('--accel', choices=['tcg', 'kvm'], default='tcg'); ap.add_argument('--slots', type=int, default=int(os.environ.get('HACKIOS_QEMU_SLOTS', '1'))); ap.add_argument('--timebase', type=int, default=None); ap.add_argument('--dry', action='store_true')
    # Mac qemu-ufsroot.py names userdata_exp.ai (fake device only); qemu-ufsroot-iossys.py names ios_system. One flag here.
    ap.add_argument('--ufs-root', default='ios_system'); ap.add_argument('--root-rw', action='store_true', help='map --root shared and writable (guest stores land in the file); pass a disposable copy')
    ap.add_argument('--dump-window', action='store_true', help='at the end, save the kernel image window (BASE..root) to kernel-window.bin for offline reads of kernel VAs')
    a = ap.parse_args(); out = D/'runs'/a.name; out.mkdir(parents=True)
    SIZE = a.window_gib << 30; LSIZE = (a.loader_gib or a.window_gib) << 30; assert LSIZE <= SIZE; epoch = int(time.time())
    route = 'rd=md0' if a.ramdisk_root else ((a.route_md and 'rd=md0 blazer_ufs_mountroot=1' or 'rd=ufsroot0')+f' blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root={a.ufs_root} blazer_ufs_lun=0')
    ARGS = f'debug=0x8 serial=3 cpus=1 {route} rootfstype=hfs msgbuf=1048576 launchd_disable_all_timeouts=1 epoch={epoch}' + (' '+a.args if a.args else '')
    assert len(ARGS) < 1024
    # kernel
    buf = bytearray(a.kernel.read_bytes()); m = mkpayload.parse_macho(buf); nfix = mkpayload.apply_chained_fixups(buf, m)
    segs = [s for s in m['segs'] if s['vmsize']]; vb = min(s['vmaddr'] for s in segs) & ~(mkpayload.L2_BLOCK-1)
    kend = (max(s['vmaddr']+s['vmsize'] for s in segs)+PAGE-1) & ~(PAGE-1); pa = lambda va: va-vb+BASE
    rsize = a.root.stat().st_size; assert rsize % (1 << 21) == 0, 'root must be a 2 MiB multiple'; root_pa = (pa(kend)+(1 << 21)-1) & ~((1 << 21)-1); ASZ = root_pa-BASE; CSZ = SIZE-ASZ-rsize
    if not a.ramdisk_root: ARGS += f' blazer_ufs_fake={root_pa:#x} blazer_ufs_fake_size={a.root.stat().st_size}'
    # ADT
    adtf = out/'adt.bin'; r = subprocess.run([sys.executable, '-I', str(BC/'mkadt.py'), str(adtf), '--qemu', f'--phys-base={BASE:#x}', f'--mem-size={min(SIZE, 6 << 30):#x}', *a.adt_opts.split()], capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    (out/'mkadt.log').write_text(r.stdout+r.stderr)
    if r.returncode: sys.exit('mkadt failed: '+r.stderr[-800:])
    tree, _ = adt.parse(adtf.read_bytes()); ch = next(c for c in tree.children if c.name == 'chosen')
    ch.props = [(k, f, struct.pack('<Q', LSIZE) if k == 'dram-size' else v) for k, f, v in ch.props]
    # accelerator: KVM on Apple silicon has no EL2 for guests and runs the counter at the host rate; the stub enters at EL1.
    tb = a.timebase or (host_cntfrq() if a.accel == 'kvm' else TCG_TIMEBASE)
    if tb != TCG_TIMEBASE:
        cpus = next(c for c in tree.children if c.name == 'cpus')
        for cn in cpus.children:
            cn.props = [(k, f, struct.pack('<I', tb) if k in ('timebase-frequency', 'peripheral-frequency', 'fixed-frequency') else v) for k, f, v in cn.props]
    cpu = a.cpu or ('host,pauth=off' if a.accel == 'kvm' else 'cortex-a76')
    if a.accel == 'kvm': mach = 'virt-11.1,gic-version=3,virtualization=off,nvdimm=on,dtb-randomness=off'; accel = ['-accel', 'kvm']
    else: mach = 'virt-11.1,gic-version=3,virtualization=on,nvdimm=on,dtb-randomness=off'; accel = ['-accel', 'tcg,tb-size=384']
    ov = a.var_overlay.read_bytes() if a.var_overlay else b''; ovsize = (len(ov)+PAGE-1) & ~(PAGE-1); ov_pa = root_pa+rsize
    if ov:
        next(c for c in ch.children if c.name == 'memory-map').props.append(('HKVarOverlay', 0, struct.pack('<2Q', ov_pa, ovsize)))
    blob = adt.serialize(tree)
    if a.ramdisk_root: blob = mkpayload.add_ramdisk_to_adt(blob, root_pa, rsize)
    adtf.write_bytes(blob)
    adt_pa = root_pa+rsize+ovsize; ba_pa = (adt_pa+len(blob)+PAGE-1) & ~(PAGE-1); top = ba_pa+PAGE
    assert top-BASE < SIZE-(1 << 30), 'window too small for root'
    assert top-BASE < LSIZE-(1 << 29), 'loader window too small for root'
    ba = bytearray(PAGE); struct.pack_into('<HH', ba, 0, 2, 2); struct.pack_into('<4Q', ba, 8, vb, BASE, LSIZE, top)
    struct.pack_into('<6Q', ba, 40, FB_PA, 1, FBS, FBW, FBH, 32); struct.pack_into('<Q', ba, 96, adt_pa-BASE+vb); struct.pack_into('<I', ba, 104, len(blob))
    cl = ARGS.encode(); ba[108:108+len(cl)] = cl; struct.pack_into('<Q', ba, 1144, LSIZE)
    stub = bytearray((R/'ios26-qemu-r1/tools/stub.bin').read_bytes()); n = stub.find(struct.pack('<Q', 0x1122334455667788)); assert n > 0
    struct.pack_into('<2Q', stub, n, ba_pa, pa(m['entry'])); (out/'stub.bin').write_bytes(stub)
    back = out/'managed.backing'; backc = out/'managed-c.backing'; sock = Path(f'/tmp/i26q-{os.getpid()}.sock')
    cmd = [QEMU, '-machine', mach, '-cpu', cpu, '-smp', '1', '-m', f'{a.ram_gib}G,slots=3,maxmem=80G', *accel,
           '-object', f'memory-backend-file,id=ma,size={ASZ},mem-path={back},share=on,prealloc=off', '-device', f'nvdimm,id=da,memdev=ma,addr={BASE:#x}',
           '-object', (f'memory-backend-file,id=mr,size={rsize},mem-path={a.root.resolve()},share=on,prealloc=off' if a.root_rw else f'memory-backend-file,id=mr,size={rsize},mem-path={a.root.resolve()},share=off,prealloc=off,readonly=on,rom=off'), '-device', f'nvdimm,id=dr,memdev=mr,addr={root_pa:#x}',
           '-object', f'memory-backend-file,id=mc,size={CSZ},mem-path={backc},share=on,prealloc=off', '-device', f'nvdimm,id=dc,memdev=mc,addr={root_pa+rsize:#x}',
           '-global', 'virtio-mmio.force-legacy=false', '-device', 'virtio-tablet-device', '-device', 'virtio-keyboard-device',
           '-kernel', str(out/'stub.bin'), '-no-reboot', '-no-shutdown', '-display', 'none', '-monitor', 'none', '-serial', f'file:{out}/uart.log', '-S', '-qmp', f'unix:{sock},server=on,wait=off']
    qv = subprocess.run([QEMU, '--version'], capture_output=True, text=True, env=QENV).stdout.split('\n')[0]
    rec = dict(host=platform.node(), qemu=qv, accel=a.accel, timebase=tb, kernel=str(a.kernel), kernel_sha=sha(a.kernel), root=str(a.root), root_sha=sha(a.root), overlay=str(a.var_overlay) if a.var_overlay else None, overlay_sha=hashlib.sha256(ov).hexdigest() if ov else None,
               args=ARGS, root_rw=bool(a.root_rw), fixups=nfix, virt_base=hex(vb), entry=hex(m['entry']), root_pa=hex(root_pa), root_size=hex(rsize), adt_pa=hex(adt_pa), ba_pa=hex(ba_pa), top=hex(top), window=SIZE, loader=LSIZE, cpu=cpu, argv=cmd)
    (out/'intent.json').write_text(json.dumps(rec, indent=1)+'\n')
    if a.dry: print(json.dumps(dict(dry=True, out=str(out), adt_bytes=len(blob), timebase=tb, cpu=cpu, accel=a.accel))); return
    # slot: the lock is held for admission and start only, so --slots N guests can run side by side
    LOCK.parent.mkdir(exist_ok=True); lock = LOCK.open('a'); t0 = time.monotonic()
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if nqemu() < a.slots and shutil.disk_usage(out).free >= DISK_FLOOR+CSZ and headroom() >= HEADROOM: break
            fcntl.flock(lock, fcntl.LOCK_UN)
        except BlockingIOError: pass
        if time.monotonic()-t0 > a.wait: sys.exit('slot not free within wait')
        time.sleep(10)
    rec['headroom'] = room = headroom()
    if room < HEADROOM: sys.exit(f'host headroom {room}')
    fd = os.open(back, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600); os.ftruncate(fd, ASZ)
    fdc = os.open(backc, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600); os.ftruncate(fdc, CSZ)
    def put(p, data):
        h, o = (fd, p-BASE) if p < root_pa else (fdc, p-root_pa-rsize); assert p < root_pa or p >= root_pa+rsize
        v = memoryview(data); os.lseek(h, o, os.SEEK_SET)
        while v: v = v[os.write(h, v):]
    for s in segs: put(pa(s['vmaddr']), bytes(buf[s['fileoff']:s['fileoff']+s['filesize']]))
    if ov: put(ov_pa, ov)
    put(adt_pa, blob); put(ba_pa, ba); os.close(fd); os.close(fdc)
    (out/'intent.json').write_text(json.dumps(rec, indent=1)+'\n')
    p = None; res = {}
    try:
        with (out/'qemu.stdout').open('wb') as l: p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=l, stderr=subprocess.STDOUT, env=QENV)
        t = time.monotonic()
        while not sock.exists():
            if p.poll() is not None or time.monotonic()-t > 30: raise RuntimeError('QEMU did not start')
            time.sleep(.05)
        fcntl.flock(lock, fcntl.LOCK_UN)
        q = QMP(sock); q.call('cont'); t0 = time.monotonic(); nf = 0; last = None; ul = 0; ut = t0; x = out/'fb.bin'; seen = 0
        while (el := time.monotonic()-t0) < a.runtime and p.poll() is None and not (out/'stop').exists():
            u = (out/'uart.log').stat().st_size
            if u != ul: ul = u; ut = time.monotonic()
            if shutil.disk_usage(out).free < DISK_FLOOR: res['ended'] = f'disk floor {DISK_FLOOR >> 30} GiB'; break
            if a.idle and time.monotonic()-ut > a.idle: res['ended'] = f'uart idle {a.idle}s'; break
            if el >= nf:
                q.hmp(f'pmemsave {FB_PA:#x} {FBS*FBH:#x} '+json.dumps(str(x))); raw = x.read_bytes(); h = hashlib.sha1(raw).hexdigest(); nf = el+15
                if h != last: png(raw, out/f'fb-{int(el):05d}.png', a.scale); last = h
            q.hmp(f'pmemsave 0x95200000 0x400000 '+json.dumps(str(out/'ramoops.bin')))
            # The mirror is a 1 MiB ring and overwrites the boot's lines. Keep every byte as it appears.
            d = (out/'ramoops.bin').read_bytes(); tot = struct.unpack_from('<Q', d, 0x23f800+48)[0]
            if tot > seen and tot < 1 << 40:
                n = tot-seen; w = tot % 0x100000; r = d[0x240000:0x340000]
                if n >= 0x100000: res['log_bytes_lost'] = res.get('log_bytes_lost', 0)+n-0x100000; chunk = r[w:]+r[:w]
                else: chunk = r[w-n:w] if w >= n else r[w-n:]+r[:w]
                with (out/'console.log').open('ab') as cf: cf.write(chunk)
                seen = tot
            # host wall clock against console and uart bytes, so milestones can be timed on the host side afterwards
            with (out/'progress.txt').open('a') as pf: pf.write(f'{el:.0f} {min(seen, 1 << 40)} {ul}\n')
            if not q.call('query-status')['running']: res['ended'] = 'guest stopped'; break
            try:
                r = q.hmp('info registers'); m = re.search(r'PC=([0-9a-f]+)', r); l = re.search(r'X30=([0-9a-f]+)', r); sp = re.search(r' SP=([0-9a-f]+)', r); st = re.search(r'PSTATE=\S+ \S+ (EL\d)', r)
                if m:
                    with (out/'pcs.txt').open('a') as pf: pf.write(f"{int(el)} {st[1] if st else '?'} {m[1]} {l[1] if l else '?'} {sp[1] if sp else '?'}\n")
            except Exception: pass
            time.sleep(1)
        res['elapsed'] = time.monotonic()-t0
        if p.poll() is None:
            if q.call('query-status')['running']: q.call('stop')
            q.hmp(f'pmemsave 0x95200000 0x400000 '+json.dumps(str(out/'ramoops.bin')))
            (out/'registers.txt').write_text(q.hmp('info registers')); q.hmp(f'pmemsave {FB_PA:#x} {FBS*FBH:#x} '+json.dumps(str(x))); png(x.read_bytes(), out/'fb-final.png', a.scale)
            if a.dump_window: q.hmp(f'pmemsave {BASE:#x} {ASZ:#x} '+json.dumps(str(out/'kernel-window.bin')))
            q.call('quit'); p.wait(timeout=5)
    except BaseException as e:
        res['error'] = repr(e); raise
    finally:
        if p and p.poll() is None:
            p.terminate()
            try: p.wait(timeout=3)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
        res['exit'] = p.returncode if p else None
        sock.unlink(missing_ok=True); back.unlink(missing_ok=True); backc.unlink(missing_ok=True); (out/'fb.bin').unlink(missing_ok=True); res['root_unchanged'] = sha(a.root) == rec['root_sha']
        (out/'exit.json').write_text(json.dumps(res, indent=1)+'\n'); lock.close(); print(json.dumps(res))
if __name__ == '__main__': main()
