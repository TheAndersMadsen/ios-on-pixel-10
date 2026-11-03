#!/usr/bin/env python3
"""Mac, from the repository root. build_int1.py with the branch and outputs renamed: build XNU branch hk-fb120 (hk-int1 + 0001-hk-fb120.patch,
made in a throwaway worktree), keep its objects, then restore the tree to p1 and rebuild that. Same lock, busy-wait and refusals.
Outputs: research/ios26-phaseb-r1/display/fb120/build/kernel.fb120{,.unstripped}, build/obj/.
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-phaseb-r1/display/fb120/build"
BR, WANT = "hk-fb120", sys.argv[1]


def g(*a, check=True):
    r = subprocess.run(["git", "-C", X, *a], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {a} failed: {r.stderr}")
    return r.stdout.strip()


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def busy():
    r = subprocess.run("ps ax -o pid=,command= | grep -E 'make|mk.sh' | grep -v grep", shell=True, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if str(os.getpid()) not in l]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def build(name):
    with open(f"{LOGS}/{name}.log", "w") as f:
        rc = subprocess.run([MK, "-j8"], stdout=f, stderr=subprocess.STDOUT).returncode
    log(f"build {name} rc {rc}")
    return rc


lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock")
fcntl.flock(lk, fcntl.LOCK_EX)
log("lock held")
while busy():
    log(f"build running, waiting: {busy()}")
    time.sleep(30)
orig = g("branch", "--show-current")
log(f"tree branch {orig} HEAD {g('rev-parse', '--short', 'HEAD')}")
if g("status", "--porcelain"):
    raise SystemExit("tree dirty, refusing")
if orig != "p1":
    raise SystemExit(f"tree is on {orig}, not p1: refusing")
if g("rev-parse", BR) != WANT:
    raise SystemExit(f"{BR} is not {WANT}, refusing")
rc = 1
try:
    g("checkout", "-q", BR)
    log(f"checked out {BR} {g('rev-parse', 'HEAD')}")
    rc = build("fb120-build")
    if rc == 0:
        os.makedirs(OUT, exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.fb120"), ("kernel.development.blazer.unstripped", "kernel.fb120.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for o in ("SweetFramebuffer.cpo", "sweet_scanout.cpo", "tensor_dpu.o",
                  ):
            for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
                shutil.copy2(h, f"{OUT}/obj/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("fb120-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    log("restored p1 kernel has the fb120 string: " + str(b"refresh 120 by copy" in open(f"{OBJ}/kernel.development.blazer", "rb").read()))
sys.exit(rc)
