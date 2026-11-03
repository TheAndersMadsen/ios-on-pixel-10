#!/usr/bin/env python3
"""Mac, repo root. Build hk-jailbreak-r1 under the kernel lock, then restore and rebuild p1.

Usage: python3 -I research/ios26-jailbreak-r1/tools/build_jb1.py FULL_COMMIT
No reset/clean is used: a dirty source tree refuses the build and also refuses branch restoration.
Outputs derived kernels/objects under research/ios26-jailbreak-r1/build/ (not for git).
"""
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import time

R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-jailbreak-r1/build"
BR, WANT = "hk-jailbreak-r1", sys.argv[1]


def g(*a):
    r = subprocess.run(["git", "-C", X, *a], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {a} failed: {r.stderr}")
    return r.stdout.strip()


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def busy():
    r = subprocess.run("ps ax -o pid=,command= | grep -E 'make|mk.sh' | grep -v grep", shell=True,
                       capture_output=True, text=True)
    return [line for line in r.stdout.splitlines() if str(os.getpid()) not in line]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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
log(f"tree branch {orig} HEAD {g('rev-parse', 'HEAD')}")
if g("status", "--porcelain"):
    raise SystemExit("tree dirty, refusing")
if orig != "p1":
    raise SystemExit(f"tree is on {orig}, not p1: refusing")
if g("rev-parse", BR) != WANT:
    raise SystemExit(f"{BR} is not {WANT}, refusing")
rc = 1
restore_rc = 1
try:
    g("checkout", "-q", BR)
    log(f"checked out {BR} {g('rev-parse', 'HEAD')}")
    rc = build("jb1-build")
    if rc == 0:
        os.makedirs(OUT, exist_ok=True)
        for source, dest in (("kernel.development.blazer", "kernel.jb1"),
                             ("kernel.development.blazer.unstripped", "kernel.jb1.unstripped")):
            shutil.copy2(f"{OBJ}/{source}", f"{OUT}/{dest}")
            log(f"{sha(OUT + '/' + dest)}  {dest}")
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for name in ("sweet_amfi.o", "kern_cs.o", "kern_codesigning.o", "hk_ustack.o", "ramfs.o"):
            for path in subprocess.run(["find", OBJ, "-name", name], capture_output=True,
                                       text=True).stdout.split():
                shutil.copy2(path, f"{OUT}/obj/{name}")
                log(f"{sha(path)}  {name} ({path[len(OBJ):]})")
finally:
    dirty = g("status", "--porcelain")
    if dirty:
        log("ERROR source tree dirty after build; refusing reset/clean and leaving branch unchanged:\n" + dirty)
        sys.exit(3)
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', 'HEAD')}")
    restore_rc = build("jb1-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    log("restored p1 kernel has generalized sandbox string: " +
        str(b"self-check: sandboxed (profile %s)" in open(f"{OBJ}/kernel.development.blazer", "rb").read()))
sys.exit(rc or restore_rc)
