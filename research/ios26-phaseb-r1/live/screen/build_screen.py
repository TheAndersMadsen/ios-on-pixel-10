#!/usr/bin/env python3
"""Mac, from the repo root. XNU branch hk-screen-dbg5 = hk-touch-direct e731e68
  + DBG3's 0001-hk-live-key-swipe-snapshot.patch (live KEY/SWIPE, framebuffer snapshot 0x67/0x68; ../input), one commit
  + 0002-hk-screen.patch (hk_screen: the glass into the dumped ramoops zone at deadline/panic/every N s), one commit.
Builds kernel.dbg5-screen, checks it, then restores the tree's original branch (p1) and rebuilds it.
Same convention as live/ustack/xnu-src/build_ustack.py: exclusive /tmp/fleet/kernel-build-slot.lock (fcntl), waits for any
running make, refuses a dirty tree, a detached HEAD, or a moved hk-touch-direct. HOST ONLY: boots nothing."""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
L = f"{R}/research/ios26-phaseb-r1/live"
P1, P2 = f"{L}/input/0001-hk-live-key-swipe-snapshot.patch", f"{L}/screen/0002-hk-screen.patch"
OUT = f"{L}/screen/build"
BR, BASE = "hk-screen-dbg5", "e731e68"
MUST = (b"HK SCREEN: on, record %#llx", b"HK SCREEN: capture %u deadline", b"blazer_usbcon_snap", b"hk_screen_box")
CO = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def g(*a, check=True):
    r = subprocess.run(["git", "-C", X, *a], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {a} failed: {r.stderr}")
    return r.stdout.strip()


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def busy():
    r = subprocess.run("ps ax -o pid=,command= | grep -E 'make|mk.sh' | grep -v grep", shell=True, capture_output=True, text=True)
    return [l[:120] for l in r.stdout.splitlines() if str(os.getpid()) not in l]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def build(name):
    with open(f"{LOGS}/{name}.log", "w") as f:
        rc = subprocess.run([MK, "-j8"], stdout=f, stderr=subprocess.STDOUT).returncode
    log(f"build {name} rc {rc}")
    return rc


def apply(patch, msg):
    g("apply", "--index", "--whitespace=nowarn", patch)
    files = g("diff", "--cached", "--name-only").split()
    log(f"applied {os.path.basename(patch)} sha256 {sha(patch)}:\n" + g("diff", "--cached", "--stat"))
    g("commit", "-q", "-m", msg + CO)
    for f in files:                     # newer than any object another branch's build left
        if os.path.exists(f"{X}/{f}"):
            os.utime(f"{X}/{f}")
    return g("rev-parse", "HEAD")


os.makedirs(OUT, exist_ok=True)
base = g("rev-parse", BASE)
if not g("rev-parse", "hk-touch-direct").startswith(base[:7]):
    sys.exit("hk-touch-direct moved off e731e68, refusing")
lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock")
fcntl.flock(lk, fcntl.LOCK_EX)
log("lock held")
while busy():
    log(f"build running, waiting: {busy()[:2]}")
    time.sleep(30)
orig = g("branch", "--show-current")
st = g("status", "--porcelain")
log(f"tree branch {orig} HEAD {g('rev-parse', '--short', 'HEAD')} dirty={bool(st)}")
if st:
    sys.exit("tree dirty, refusing")
if not orig:
    sys.exit("detached HEAD, refusing")
rc = 1
try:
    have = g("rev-parse", "--verify", "-q", BR, check=False)
    if have:
        if g("rev-parse", f"{BR}~2") != base:
            sys.exit(f"{BR} exists and is not two commits on e731e68, refusing")
        g("checkout", BR)
        log(f"reusing {BR} {have}")
        if subprocess.run(["git", "-C", X, "apply", "--check", "-R", P2], capture_output=True).returncode:
            sys.exit(f"{BR} does not carry this 0002-hk-screen.patch, refusing (delete the branch to rebuild)")
        for f in g("diff", "--name-only", f"{BR}~1", BR).split():
            os.utime(f"{X}/{f}")
    else:
        g("checkout", "-b", BR, base)
        c1 = apply(P1, "hk live input: KEY, SWIPE and framebuffer snapshot over usbcon (DBG3 0001)\n\n"
                   "research/ios26-phaseb-r1/live/input/0001-hk-live-key-swipe-snapshot.patch, unchanged: requests 0x69 KEY,\n"
                   "0x6a/0x6b SWIPE (HLI1 capability bits), 0x67/0x68 snapshot (blazer_usbcon_snap=1, RGB565 every step-th\n"
                   "pixel of the panel buffer's picture). See research/ios26-phaseb-r1/live/UNATTENDED.md.")
        log(f"commit {c1}")
        c2 = apply(P2, "hk_screen: the glass into the dumped ramoops zone (deadline, panic, every N s)\n\n"
                   "hk_screen=1 copies the picture the copy path put in the panel buffer, downscaled to 360 px wide RGB565\n"
                   "(2x2 box; hk_screen_box=0 point), into an HKSCR1 record at PA 0x95550000 (pmsg+0x150000, below TGL_ALL),\n"
                   "which every fastboot park already dumps as kernel.log. At the blazer deadline (thread context, logged)\n"
                   "and once in debugger_collect_diagnostics before PEHaltRestart(kPEPanicBegin); hk_screen=N >= 10 also\n"
                   "every N s from the blazer-root watch. The record carries this boot's XNUENT1 identity and a crc32 of\n"
                   "the rows; tools/fb_png.py decodes it. sweet_scanout_picture_buffer exposes the snapshot's picture.\n"
                   "Sampler and record writer host-tested (research/ios26-phaseb-r1/live/screen/test). BLAZER only, off by\n"
                   "default.")
        log(f"commit {c2}")
    log(f"branch {BR} HEAD {g('rev-parse', 'HEAD')}")
    rc = build("screen-dbg5-build")
    if rc == 0:
        k = open(f"{OBJ}/kernel.development.blazer.unstripped", "rb").read()
        missing = [m.decode() for m in MUST if m not in k]
        if missing:
            log(f"built kernel lacks {missing}: stale object or config, refusing")
            rc = 1
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.dbg5-screen"),
                     ("kernel.development.blazer.unstripped", "kernel.dbg5-screen.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        for o in ("osfmk/DEVELOPMENT/hk_screen.o", "osfmk/DEVELOPMENT/blazer_usbcon.o", "osfmk/DEVELOPMENT/debug.o",
                  "bsd/DEVELOPMENT/hakios.blazer_ufs.o", "iokit/DEVELOPMENT/sweet_scanout.cpo"):
            p = f"{OBJ}/{o}"
            if os.path.exists(p):
                shutil.copy2(p, f"{OUT}/{os.path.basename(o)}")
                log(f"{sha(p)}  {o}")
            else:
                log(f"(no {o})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("screen-dbg5-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    if b"HK SCREEN: on" in open(f"{OBJ}/kernel.development.blazer", "rb").read():
        log("WARNING restored p1 kernel still has hk_screen (stale config)")
sys.exit(rc)
