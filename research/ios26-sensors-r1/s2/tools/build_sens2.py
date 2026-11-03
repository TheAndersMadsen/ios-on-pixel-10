#!/usr/bin/env python3
"""Mac, from the repository root. Build the int1 + compass kernel from XNU branch hk-int1-sens2 (hk-int1 484717f + patch 0930,
made beforehand in a separate worktree, S2.md section 2), then restore the tree to p1 and rebuild that. Copy of
research/ios26-phaseb-r1/int/tools/build_int1.py: exclusive /tmp/fleet/kernel-build-slot.lock, wait for any make, refuse a dirty
tree or one not on p1, refuse hk-int1-sens2 at any commit but the expected one. Outputs: research/ios26-sensors-r1/s2/build/kernel.sens2{,.unstripped}.
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-sensors-r1/s2/build"
BR, WANT = "hk-int1-sens2", sys.argv[1]


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
    rc = build("sens2-build")
    if rc == 0:
        os.makedirs(OUT, exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.sens2"), ("kernel.development.blazer.unstripped", "kernel.sens2.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for o in ("blazer_sensors.o", "blazer_sensor_hw.o", "blazer_mag_hw.o", "blazer_cpmq.o", "SweetHID.cpo", "KernelConfigTables.cpo"):
            for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
                shutil.copy2(h, f"{OUT}/obj/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("sens2-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    log("restored p1 kernel has compass strings: " + str(b"blazer-sensors: compass on" in open(f"{OBJ}/kernel.development.blazer", "rb").read()))
sys.exit(rc)
