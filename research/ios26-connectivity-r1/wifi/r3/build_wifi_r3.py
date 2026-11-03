#!/usr/bin/env python3
"""Mac only, from the repo root. Build kernel.rootview-wifi-r3 = hk-wifi-join2: hk-wifi-pass eef94c6 (r2) + the two-method join (r3), then restore the tree.
Usage: python3 -I research/ios26-connectivity-r1/wifi/r3/build_wifi_r3.py <full hk-wifi-join2 commit>. Refuses unless that is the branch head and its parent is eef94c6.

Same lock, flags and restore as rootview/aks-build/build_aks.py: fcntl lock of /tmp/fleet/kernel-build-slot.lock, wait while any make or
mk.sh runs, refuse a dirty tree, build with research/ios26-release-r1/tools/mk.sh -j8, copy the stripped and unstripped kernel to
research/ios26-dualboot-r8/rootview/, check out the original branch (p1) again and rebuild it, so the next user finds what they left."""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-dualboot-r8/rootview"
WT = f"{R}/research/ios26-connectivity-r1/wifi/r3/xnu-wt"
BRANCH, BASE = "hk-wifi-join2", "eef94c6fbb3cb4a40933d470387627ae186b56bf"


def g(*a, check=True):
    r = subprocess.run(["git", "-C", X, *a], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {a} failed: {r.stderr}")
    return r.stdout.strip()


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def busy():
    r = subprocess.run("ps ax -o pid=,command= | grep -E 'make|mk.sh' | grep -v grep", shell=True, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if str(os.getpid()) not in l]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def build(name):
    t = time.time()
    with open(f"{LOGS}/{name}.log", "w") as f:
        rc = subprocess.run([MK, "-j8"], stdout=f, stderr=subprocess.STDOUT).returncode
    log(f"build {name} rc {rc}, {time.time() - t:.0f} s, log research/ios26-release-r1/logs/{name}.log")
    return rc


lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock")
fcntl.flock(lk, fcntl.LOCK_EX)
log("lock held")
while busy():
    log(f"build running, waiting: {busy()}")
    time.sleep(30)
orig = g("branch", "--show-current")
st = g("status", "--porcelain")
log(f"tree branch {orig} HEAD {g('rev-parse', '--short', 'HEAD')} dirty={bool(st)}")
if st:
    sys.exit("tree dirty, refusing")
COMMIT = sys.argv[1] if len(sys.argv) > 1 else ""
if not COMMIT or g("rev-parse", BRANCH) != COMMIT or g("rev-parse", f"{BRANCH}~1") != BASE:
    sys.exit(f"{BRANCH} is not {COMMIT} on {BASE}, refusing")
if os.path.isdir(WT):
    wst = subprocess.run(["git", "-C", WT, "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    if wst:
        sys.exit("the edit worktree is dirty, refusing")
    g("worktree", "remove", WT)
    log("edit worktree removed (clean; its commit is the branch)")
rc = 1
try:
    g("checkout", BRANCH)
    log(f"on {g('branch', '--show-current')} {g('rev-parse', 'HEAD')}; vs {BASE}:\n" + g("diff", "--stat", BASE, "HEAD"))
    rc = build("wifi-r3-build")
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.rootview-wifi-r3"), ("kernel.development.blazer.unstripped", "kernel.rootview-wifi-r3.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("wifi-r3-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
