#!/usr/bin/env python3
"""Build kernel.rootview-bl-aks-us on the Mac: hk-aks-usersession = hk-aks-wrap (44689e0) + SweetKeyStore user-session
selectors (blazer_aks_usersession=1) + persona alloc log (blazer_persona_log=1) + -DBLAZER_AKS_USERSESSION=1; then
restore the tree to its original branch (p1) and rebuild it. Same lock and build as aks-build/build_aks.py."""
import fcntl, os, shutil, subprocess, sys, time, hashlib
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-apps-r1/usersession/build"
SRC = f"{R}/research/ios26-apps-r1/usersession/xnu-src"
BR, BASE = "hk-aks-usersession", "44689e02f105f2daea3dae5762912d6847f81902"
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
os.makedirs(OUT, exist_ok=True)
lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock"); fcntl.flock(lk, fcntl.LOCK_EX); log("lock held")
while busy(): log(f"build running, waiting: {busy()}"); time.sleep(30)
orig = g("branch", "--show-current"); st = g("status", "--porcelain")
log(f"tree branch {orig} HEAD {g('rev-parse','--short','HEAD')} dirty={bool(st)}")
if st: sys.exit("tree dirty, refusing")
if g("rev-parse", "--verify", "-q", BR, check=False): sys.exit(f"{BR} exists, refusing")
rc = 1
try:
    g("checkout", "-b", BR, BASE)
    shutil.copy2(f"{SRC}/SweetKeyStore.cpp", f"{X}/iokit/Kernel/arm/SweetKeyStore.cpp")
    shutil.copy2(f"{SRC}/blazer_aks_usersession.inc", f"{X}/iokit/Kernel/arm/blazer_aks_usersession.inc")
    shutil.copy2(f"{SRC}/sys_persona.c", f"{X}/bsd/kern/sys_persona.c")
    mk = f"{X}/makedefs/MakeInc.def"; t = open(mk).read(); a = "-DBLAZER_AKS_WRAP=1"
    assert t.count(a) == 1; open(mk, "w").write(t.replace(a, a + " -DBLAZER_AKS_USERSESSION=1"))
    g("add", "-A"); log("staged:\n" + g("diff", "--cached", "--stat"))
    g("commit", "-q", "-m", "SweetKeyStore: gated AKS user-session selectors (blazer_aks_usersession=1); persona alloc log (blazer_persona_log=1)\n\n"
      "Software answers for aks_create_bag/save_bag/load_bag (an opaque 16-byte user record, no keys), keybag persona\n"
      "create/list/delete and set_keybag_for_volume_with_cookie_persona, so usermanagerd can set up the local user's\n"
      "personas. Off unless both BLAZER_AKS_USERSESSION and the boot-arg are set. No identity or attestation selectors.\n"
      "Host test: research/ios26-apps-r1/usersession/tests. Plan: research/ios26-apps-r1/usersession/PLAN.md.\n\n"
      "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    log(f"commit {g('rev-parse','HEAD')}")
    rc = build("aks-us-build")
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.rootview-bl-aks-us"), ("kernel.development.blazer.unstripped", "kernel.rootview-bl-aks-us.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}"); log(f"{sha(OUT+'/'+d)}  {d}")
finally:
    if g("status", "--porcelain"): log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig); log(f"restored branch {g('branch','--show-current')} HEAD {g('rev-parse','--short','HEAD')}")
    build("aks-us-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
