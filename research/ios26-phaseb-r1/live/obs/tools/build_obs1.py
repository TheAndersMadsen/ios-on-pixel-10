#!/usr/bin/env python3
"""Mac, from the repository root. HOST ONLY. XNU branch hk-obs1 = hk-int1 (484717f) + obs/xnu-src/0001-hk-obs1.patch, made
in a throwaway worktree so the shared tree is never left on it; then build it in the shared tree under the fleet lock and
restore p1 (rebuilt), as int/tools/build_int1.py. Refuses: a dirty tree, a tree not on p1, hk-int1 not 484717f, a patch
whose sha256 is not the given one, an existing hk-obs1 at another commit.

    python3 -I research/ios26-phaseb-r1/live/obs/tools/build_obs1.py PATCH_SHA256
Outputs: research/ios26-phaseb-r1/live/obs/build/kernel.obs1{,.unstripped}, obj/ copies of the changed objects.
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
O = f"{R}/research/ios26-phaseb-r1/live/obs"
OUT = f"{O}/build"
PATCH = f"{O}/xnu-src/0001-hk-obs1.patch"
BASE_BR, BASE = "hk-int1", "484717fc194d599cfd28985012b19e7bf0be9748"
BR = "hk-obs1"
WT = "/tmp/hk-obs1-wt"


def g(*a, check=True, cwd=X):
    r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True)
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


def make_branch():
    if sha(PATCH) != sys.argv[1]:
        raise SystemExit(f"patch is {sha(PATCH)}, not {sys.argv[1]}")
    if g("rev-parse", BASE_BR) != BASE:
        raise SystemExit(f"{BASE_BR} is not {BASE}, refusing")
    have = g("rev-parse", "--verify", "-q", BR, check=False)
    if have:
        if g("rev-parse", f"{BR}~1") != BASE:
            raise SystemExit(f"{BR} is not one commit on {BASE}: not ours, refusing")
        if f"patch-sha256: {sys.argv[1]}" in g("log", "-1", "--format=%B", BR):
            log(f"{BR} exists at {have}, made from this patch")
            return have
        log(f"{BR} at {have} was made from an earlier patch: replaced")
        g("branch", "-D", BR)
    if os.path.exists(WT):
        raise SystemExit(f"{WT} exists")
    g("worktree", "add", "-q", "--detach", WT, BASE)
    try:
        g("-c", "user.name=Anders Madsen", "-c", "user.email=madsenanders97@gmail.com", "am", "-q", "--committer-date-is-author-date",
          PATCH, cwd=WT)
        msg = g("log", "-1", "--format=%B", cwd=WT)
        g("-c", "user.name=Anders Madsen", "-c", "user.email=madsenanders97@gmail.com", "commit", "-q", "--amend", "-m",
          f"{msg}\n\npatch-sha256: {sys.argv[1]}", cwd=WT)
        head = g("rev-parse", "HEAD", cwd=WT)
        g("branch", BR, head)
        log(f"{BR} = {head} (on {BASE[:7]})")
    finally:
        g("worktree", "remove", "--force", WT, check=False)
    return head


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
head = make_branch()
rc = 1
try:
    g("checkout", "-q", BR)
    log(f"checked out {BR} {g('rev-parse', 'HEAD')}")
    rc = build("obs1-build")
    if rc == 0:
        os.makedirs(OUT, exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.obs1"), ("kernel.development.blazer.unstripped", "kernel.obs1.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for o in ("hk_obs.o", "kern_exec.o", "kern_exit.o", "cons.o", "debug.o", "blazer_wifi.o", "blazer_bcm4390.o",
                  "blazer_bcm4390_scan.o", "blazer_bt_bridge.o", "blazer_btuart.o", "blazer_usbcon.o", "hakios.blazer_ufs.o"):
            for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
                shutil.copy2(h, f"{OUT}/obj/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("obs1-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    log("restored p1 kernel has the HKOBS string: " + str(b"HKOBS %u" in open(f"{OBJ}/kernel.development.blazer", "rb").read()))
sys.exit(rc)
