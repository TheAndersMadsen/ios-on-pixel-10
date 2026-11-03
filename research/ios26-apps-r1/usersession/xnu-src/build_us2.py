#!/usr/bin/env python3
"""Second commit on hk-aks-usersession: ramfs (varfs) RENAME_SWAP/RENAME_EXCL (vnop_renamex). Build
kernel.rootview-bl-aks-us2, then restore the tree to its original branch (p1) and rebuild it. Same lock as build_us.py."""
import fcntl, os, shutil, subprocess, sys, time, hashlib
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-apps-r1/usersession/build"
SRC = f"{R}/research/ios26-apps-r1/usersession/xnu-src"
BR, PARENT = "hk-aks-usersession", "eb2d19ba821b77c2d4153d9216cf4491cf83fd27"
def g(*a, check=True):
    r = subprocess.run(["git", "-C", X, *a], capture_output=True, text=True)
    if check and r.returncode: sys.exit(f"git {a} failed: {r.stderr}")
    return r.stdout.strip()
def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)
def busy():
    r = subprocess.run("ps ax -o pid=,command= | grep -E 'make|mk.sh' | grep -v grep", shell=True, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if str(os.getpid()) not in l]
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def build(name):
    with open(f"{LOGS}/{name}.log", "w") as f:
        rc = subprocess.run([MK, "-j8"], stdout=f, stderr=subprocess.STDOUT).returncode
    log(f"build {name} rc {rc}"); return rc
lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock"); fcntl.flock(lk, fcntl.LOCK_EX); log("lock held")
while busy(): log(f"build running, waiting: {busy()}"); time.sleep(30)
orig = g("branch", "--show-current"); st = g("status", "--porcelain")
log(f"tree branch {orig} HEAD {g('rev-parse','--short','HEAD')} dirty={bool(st)}")
if st: sys.exit("tree dirty, refusing")
if g("rev-parse", BR) != PARENT: sys.exit(f"{BR} is not at {PARENT}, refusing")
rc = 1
try:
    g("checkout", BR)
    shutil.copy2(f"{SRC}/ramfs.c", f"{X}/bsd/miscfs/ramfs/ramfs.c")
    g("add", "-A"); log("staged:\n" + g("diff", "--cached", "--stat"))
    g("commit", "-q", "-m", "ramfs (varfs): RENAME_SWAP of two files and RENAME_EXCL (vnop_renamex)\n\n"
      "Foundation's atomic writes replace an existing file with renamex_np(RENAME_SWAP). varfs had no vnop_renamex and no\n"
      "vnop_exchange, so the SWEET HFS fallback (0052) could not help and every such save on /private/var failed with\n"
      "ENOTSUP (usermanagerd's usersession.kb/persona.kb). Directory swaps and other flags stay ENOTSUP.\n\n"
      "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    log(f"commit {g('rev-parse','HEAD')}")
    rc = build("aks-us2-build")
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.rootview-bl-aks-us2"), ("kernel.development.blazer.unstripped", "kernel.rootview-bl-aks-us2.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}"); log(f"{sha(OUT+'/'+d)}  {d}")
finally:
    if g("status", "--porcelain"): log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig); log(f"restored branch {g('branch','--show-current')} HEAD {g('rev-parse','--short','HEAD')}")
    build("aks-us2-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
