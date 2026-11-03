#!/usr/bin/env python3
"""Build kernel.rootview-bl-aks on the Mac: hk-aks-wrap = f24a98d + aks-wrap 0001/0002, then restore the tree."""
import fcntl, os, shutil, subprocess, sys, time, hashlib
R = os.getcwd()  # repo root
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-dualboot-r8/rootview"
P = f"{R}/research/ios26-connectivity-r1/bluetooth/aks-wrap"
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
if g("rev-parse", "--verify", "-q", "hk-aks-wrap", check=False): sys.exit("hk-aks-wrap exists, refusing")
rc = 1
try:
    g("checkout", "-b", "hk-aks-wrap", "f24a98d")
    pa = [f"{P}/0001-sweet-aks-wrap-unwrap.patch", f"{P}/0002-blazer-aks-wrap-build-on.patch"]
    g("apply", "--check", *pa); g("apply", *pa); g("add", "-A")
    log("staged:\n" + g("diff", "--cached", "--stat"))
    g("commit", "-q", "-m", "SweetKeyStore: gated AKS wrap/unwrap (blazer_aks_wrap=1), BLAZER_AKS_WRAP=1 in the BLAZER build\n\n"
      "Applies research/ios26-connectivity-r1/bluetooth/aks-wrap/0001-sweet-aks-wrap-unwrap.patch and\n"
      "0002-blazer-aks-wrap-build-on.patch unchanged on hk-bright-calib-bl (f24a98d).\n\n"
      "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    log(f"commit {g('rev-parse','HEAD')}")
    # MakeInc.def is not a make prerequisite: SweetKeyStore.cpp is the only TU testing BLAZER_AKS_WRAP and it is modified, so it recompiles.
    rc = build("aks-wrap-build")
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.rootview-bl-aks"), ("kernel.development.blazer.unstripped", "kernel.rootview-bl-aks.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}"); log(f"{sha(OUT+'/'+d)}  {d}")
finally:
    if g("status", "--porcelain"): log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig); log(f"restored branch {g('branch','--show-current')} HEAD {g('rev-parse','--short','HEAD')}")
    build("aks-wrap-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
