#!/usr/bin/env python3
"""Mac, from the repository root. HOST ONLY: boots nothing. XNU branch hk-cam1 = 7227fe7 (the A7-r3 kernel's source, kernel.rootview
ddf874fb) + research/ios26-camera-r1/xnu-src/0001-hk-cam1.patch, made in a throwaway worktree; built in the shared tree under the fleet
build lock; the shared tree is then put back on its branch (p1) and rebuilt, as live/obs/tools/build_obs1.py.
Refuses: a dirty tree, a tree not on p1, a patch whose sha256 is not the given one, an existing hk-cam1 not made from this patch on 7227fe7.

    python3 -I research/ios26-camera-r1/tools/build_cam1.py PATCH_SHA256
Outputs: research/ios26-camera-r1/build/kernel.cam1{,.unstripped}, build/obj/blazer_torch*.o (not for git).
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
C = f"{R}/research/ios26-camera-r1"
OUT = f"{C}/build"
PATCH = f"{C}/xnu-src/0001-hk-cam1.patch"
BASE = "7227fe7c7563727f63405b12f3c58409a4975ef0"
BR = "hk-cam1"
WT = "/tmp/hk-cam1-wt"
WANT = (b"cli select uart -> i2c", b"led%u on: torch code 0x%x, enable 0x%x, for %u ms", b"blazer-torch: summary stage %u", b"refused-write")


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
        g("-c", "user.name=Anders Madsen", "-c", "user.email=madsenanders97@gmail.com", "am", "-q", "--committer-date-is-author-date", PATCH, cwd=WT)
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
    rc = build("cam1-build")
    if rc == 0:
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.cam1"), ("kernel.development.blazer.unstripped", "kernel.cam1.unstripped")):
            shutil.copyfile(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        blob = open(f"{OUT}/kernel.cam1", "rb").read()
        for w in WANT:
            log(f"kernel.cam1 has {w.decode()!r}: {w in blob}")
            if w not in blob:
                rc = 3
        for o in ("blazer_torch.o", "blazer_torch_hw.o"):
            for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
                shutil.copyfile(h, f"{OUT}/obj/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("cam1-restore-p1-build")
    k = open(f"{OBJ}/kernel.development.blazer", "rb").read()
    log("obj kernel after restore " + hashlib.sha256(k).hexdigest())
    log("restored p1 kernel has the hk-cam1 string: " + str(WANT[0] in k))
sys.exit(rc)
