#!/usr/bin/env python3
"""Mac, from the repo root: XNU branch hk-ustack-dbg4 = hk-touch-direct e731e68 + one commit (hk_ustack: user stacks of named
processes on the console, boot-arg hk_ustack=, EP0 0x70). Build kernel.dbg4-ustack, then restore the tree's original branch
(p1) and rebuild it. Lock /tmp/fleet/kernel-build-slot.lock (fcntl), waits for any running make, refuses a dirty tree.
Same steps as live/net/xnu-src/build_net.py (dbg1)."""
import fcntl, os, shutil, subprocess, sys, time, hashlib
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
SRC = f"{R}/research/ios26-phaseb-r1/live/ustack/xnu-src"
OUT = f"{R}/research/ios26-phaseb-r1/live/ustack/build"
BR, BASE = "hk-ustack-dbg4", "e731e68"
FILES = tuple((p, p) for p in ("osfmk/kern/hk_ustack.c", "osfmk/kern/hk_ustack_pure.inc", "osfmk/kern/hk_ustack_wire.h",
    "osfmk/kern/hk_top.c", "osfmk/arm64/blazer_usbcon.c", "osfmk/arm64/blazer_usbcon_core.inc", "osfmk/conf/files"))
# The edited files must start from e731e68's bytes (xnu-src/base holds those copies).
BASE_FILES = ("osfmk/kern/hk_top.c", "osfmk/arm64/blazer_usbcon.c", "osfmk/arm64/blazer_usbcon_core.inc", "osfmk/conf/files")
def g(*a, check=True):
    r = subprocess.run(["git", "-C", X, *a], capture_output=True, text=True)
    if check and r.returncode: sys.exit(f"git {a} failed: {r.stderr}")
    return r.stdout.strip()
def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)
def busy():
    r = subprocess.run("ps ax -o pid=,command= | grep -E 'make|mk.sh' | grep -v grep", shell=True, capture_output=True, text=True)
    return [l[:120] for l in r.stdout.splitlines() if str(os.getpid()) not in l]
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def build(name):
    with open(f"{LOGS}/{name}.log", "w") as f:
        rc = subprocess.run([MK, "-j8"], stdout=f, stderr=subprocess.STDOUT).returncode
    log(f"build {name} rc {rc}"); return rc
os.makedirs(OUT, exist_ok=True)
base = g("rev-parse", BASE)
if not g("rev-parse", "hk-touch-direct").startswith(base[:7]): sys.exit("hk-touch-direct moved off e731e68, refusing")
lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock"); fcntl.flock(lk, fcntl.LOCK_EX); log("lock held")
while busy(): log(f"build running, waiting: {busy()[:2]}"); time.sleep(30)
orig = g("branch", "--show-current"); st = g("status", "--porcelain")
log(f"tree branch {orig} HEAD {g('rev-parse','--short','HEAD')} dirty={bool(st)}")
if st: sys.exit("tree dirty, refusing")
if not orig: sys.exit("detached HEAD, refusing")
have = g("rev-parse", "--verify", "-q", BR, check=False)
rc = 1
try:
    if have:
        # First build: cac047f (EP0 request 0x64). 0x64..0x68 are being taken by HLI1 KEY/SWIPE/SNAP, so a second commit moves
        # the request to 0x70; nothing else changes.
        if g("rev-parse", f"{BR}^") == base and have.startswith("cac047f"):
            g("checkout", BR)
            for s, d in FILES: shutil.copy(f"{SRC}/{s}", f"{X}/{d}")
            g("add", "-A"); log("staged:\n" + g("diff", "--cached", "--stat"))
            g("commit", "-q", "-m", "hk_ustack: EP0 request 0x70, clear of HLI1 0x60..0x68 (KEY, SWIPE, SNAP)\n\n"
              "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
        elif g("rev-parse", f"{BR}~2") == base and g("rev-parse", f"{BR}^").startswith("cac047f"):
            g("checkout", BR); log(f"reusing {BR} {have}")
        else:
            sys.exit(f"{BR} exists and is not cac047f on e731e68, refusing")
        for s, d in FILES:
            if sha(f"{SRC}/{s}") != sha(f"{X}/{d}"): sys.exit(f"{BR} has a different {d}, refusing")
    else:
        g("checkout", "-b", BR, base)
        for b in BASE_FILES:
            if sha(f"{SRC}/base/{b}") != sha(f"{X}/{b}"): sys.exit(f"e731e68 {b} differs from xnu-src/base, refusing")
        for s, d in FILES: shutil.copy(f"{SRC}/{s}", f"{X}/{d}")  # not copy2: an old mtime hides the change from make
        g("add", "-A"); log("staged:\n" + g("diff", "--cached", "--stat"))
        g("commit", "-q", "-m", "hk_ustack: user stacks of named processes on the console (hk_ustack=NAME,...; EP0 0x70)\n\n"
          "Every hk_ustack_s seconds (default 5) a kernel thread prints, for each task whose p_comm is in hk_ustack=, a\n"
          "header (shared cache slide, main image, suspend count, CPU) and one line per thread: state, block_hint, x16/x0,\n"
          "CPU and switches since the last round, time off CPU, user pc/lr/sp and the frame-pointer chain (hk_hog_walk).\n"
          "Unchanged threads fold into one same: line; images outside the shared cache are listed from dyld's\n"
          "all_image_infos. Bounded by hk_ustack_n rounds per pid and hk_ustack_max lines. With blazer_usbcon_input=1,\n"
          "vendor request 0x70 (hk_ustack_wire.h) samples one pid for 1..120 rounds. Read-only (copyinmap, as hk_hog).\n"
          "Pure part and EP0 dispatch host-tested (research/ios26-phaseb-r1/live/ustack/test). BLAZER only; off without\n"
          "hk_ustack= and blazer_usbcon_input=1.\n\n"
          "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    log(f"commit {g('rev-parse','HEAD')}")
    for s, d in FILES: os.utime(f"{X}/{d}")  # newer than any object another branch's build left
    rc = build("ustack-dbg4-build")
    if rc == 0 and b"HK USTACK: every %u s" not in open(f"{OBJ}/kernel.development.blazer", "rb").read():
        log("built kernel lacks hk_ustack: stale object or config, refusing"); rc = 1
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.dbg4-ustack"), ("kernel.development.blazer.unstripped", "kernel.dbg4-ustack.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}"); log(f"{sha(OUT+'/'+d)}  {d}")
        for o in ("osfmk/DEVELOPMENT/hk_ustack.o", "osfmk/DEVELOPMENT/blazer_usbcon.o", "osfmk/DEVELOPMENT/hk_top.o"):
            p = f"{OBJ}/{o}"
            if os.path.exists(p): shutil.copy2(p, f"{OUT}/{os.path.basename(o)}"); log(f"{sha(p)}  {o}")
finally:
    if g("status", "--porcelain"): log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig); log(f"restored branch {g('branch','--show-current')} HEAD {g('rev-parse','--short','HEAD')}")
    build("ustack-dbg4-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    if b"HK USTACK: every %u s" in open(f"{OBJ}/kernel.development.blazer", "rb").read():
        log("WARNING restored p1 kernel still has hk_ustack (stale config)")
sys.exit(rc)
