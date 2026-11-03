#!/usr/bin/env python3
"""Mac, from the repository root. Build kernel.pwr1 on a new XNU branch hk-pwr1 from hk-touch-direct (e731e68), then restore
the tree to the branch it was on (p1) and rebuild that. Same lock and checks as ios26-apps-r1/usersession/xnu-src/build_us2.py.

hk-pwr1 = e731e68
  + cherry-pick 44689e0 eb2d19b cc42295 (hk-aks-usersession: AKS wrap, user-session selectors, ramfs RENAME_SWAP; the r10 kernel
    has them and its line uses blazer_aks_wrap=1)
  + 0001-native-buttons-delivery.patch (ios26-opt-20261102/buttons_integration, 00ce0bf8...)
  + 0832-blazer-haptic-native-rom.patch (ios26-feature-haptics-r1, 97353f86...)
  + 0003-blazer-haptic-tap.patch (this lane)
  + makedefs/MakeInc.def: -DBLAZER_KEY_DELIVERY=1 -DBLAZER_HAPTIC_SERVICE=1 on the BLAZER line
Each step is its own commit on hk-pwr1. Outputs: research/ios26-phaseb-r1/pwr/build/kernel.pwr1{,.unstripped} and object copies.
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
L = f"{R}/research/ios26-phaseb-r1/pwr"
OUT = f"{L}/build"
BR, BASE = "hk-pwr1", "e731e68"
PICKS = ("44689e0", "eb2d19b", "cc42295")
PATCHES = (("0001-native-buttons-delivery.patch", "00ce0bf89742809d0e2ff3197b15f16312ee0f031e992cdddf088ecc102e9830",
            "SweetHID/blazer keys: checked physical key delivery and the reviewed power-key lifecycle (buttons_integration 0001)"),
           ("0832-blazer-haptic-native-rom.patch", "97353f863885438f6a958d1e5d071a96547193b793438498914d807e1c9e1799",
            "blazer haptic: bounded native ROM-effect service (blazer_haptic_service=1, ID-only stage) (feature-haptics 0832)"),
           ("0003-blazer-haptic-tap.patch", None,
            "blazer haptic: blazer_haptic_tap=1, one ROM effect per new touch contact from a worker thread"))
FLAGS = "-DBLAZER_KEY_DELIVERY=1 -DBLAZER_HAPTIC_SERVICE=1"
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


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


def commit(msg):
    g("add", "-A")
    log("staged:\n" + g("diff", "--cached", "--stat"))
    g("commit", "-q", "-m", msg + TRAILER)
    log(f"commit {g('rev-parse', '--short', 'HEAD')} {msg[:70]}")


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
if g("rev-parse", "--verify", "-q", BR, check=False):
    raise SystemExit(f"{BR} exists, refusing")
for name, want, _ in PATCHES:
    if want and sha(f"{L}/patches/{name}") != want:
        raise SystemExit(f"{name} hash changed, refusing")
rc = 1
try:
    g("checkout", "-q", "-b", BR, BASE)
    for c in PICKS:
        g("cherry-pick", c)
        log(f"picked {c} -> {g('rev-parse', '--short', 'HEAD')}")
    for name, _, msg in PATCHES:
        g("apply", "--index", f"{L}/patches/{name}")
        commit(msg)
    mk = f"{X}/makedefs/MakeInc.def"
    text = open(mk).read()
    lines = [l for l in text.splitlines() if l.startswith("MACHINE_FLAGS_ARM64_BLAZER = ")]
    if len(lines) != 1 or "BLAZER_KEY_DELIVERY" in lines[0] or "BLAZER_HAPTIC_SERVICE" in lines[0]:
        raise SystemExit("unexpected MACHINE_FLAGS_ARM64_BLAZER")
    open(mk, "w").write(text.replace(lines[0], lines[0] + " " + FLAGS))
    commit("BLAZER build: BLAZER_KEY_DELIVERY=1 BLAZER_HAPTIC_SERVICE=1 (both still default off at boot)")
    log(f"{BR} at {g('rev-parse', 'HEAD')}")
    rc = build("pwr1-build")
    if rc == 0:
        os.makedirs(OUT, exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.pwr1"), ("kernel.development.blazer.unstripped", "kernel.pwr1.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        for o in ("hakios.blazer_keys.o", "blazer_haptic.o", "SweetHID.cpo"):
            hits = subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split()
            for h in hits:
                shutil.copy2(h, f"{OUT}/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("cherry-pick", "--abort", check=False)
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("pwr1-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
