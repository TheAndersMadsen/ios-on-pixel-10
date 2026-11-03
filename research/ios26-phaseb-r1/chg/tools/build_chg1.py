#!/usr/bin/env python3
"""Mac, from the repository root. HOST ONLY. XNU branch hk-chg1 = hk-obs1 (2841211) + chg/xnu-src/0001-hk-chg1.patch, made
in a throwaway worktree so the shared tree is never left on it; then build it in the shared tree under the fleet lock and
restore p1 (rebuilt). Copy of live/obs/tools/build_obs1.py with the names changed. Refuses: a dirty tree, a tree not on p1,
hk-obs1 not 2841211, a patch whose sha256 is not the given one, an existing hk-chg1 at another commit.

    python3 -I research/ios26-phaseb-r1/chg/tools/build_chg1.py PATCH_SHA256
Outputs: research/ios26-phaseb-r1/chg/build/kernel.chg1{,.unstripped}, obj/blazer_gauge.o.
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
O = f"{R}/research/ios26-phaseb-r1/chg"
OUT = f"{O}/build"
PATCH = f"{O}/xnu-src/0001-hk-chg1.patch"
BASE_BR, BASE = "hk-obs1", "284121116f90c6549c8a3bc35250579c9cd9f155"
BR = "hk-chg1"
WT = "/tmp/hk-chg1-wt"


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
    rc = build("chg1-build")
    if rc == 0:
        os.makedirs(OUT, exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.chg1"), ("kernel.development.blazer.unstripped", "kernel.chg1.unstripped")):
            shutil.copyfile(f"{OBJ}/{s}", f"{OUT}/{d}")  # plain copy: fresh mtime (playbook lesson)
            log(f"{sha(OUT + '/' + d)}  {d}")
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for o in ("blazer_gauge.o", "SweetBattery.cpo"):
            for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
                shutil.copyfile(h, f"{OUT}/obj/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("chg1-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    log("restored p1 kernel has the chg1 line (must be False): " + str(b"blazer-battery: charger %u in=" in open(f"{OBJ}/kernel.development.blazer", "rb").read()))
sys.exit(rc)
