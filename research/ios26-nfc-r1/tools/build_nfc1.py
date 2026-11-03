#!/usr/bin/env python3
"""Mac, from the repository root. HOST ONLY. XNU branch hk-nfc1 = hk-obs1 (2841211) + the files in research/ios26-nfc-r1/xnu-src,
committed in a throwaway worktree so the shared tree is never left on it; then built in the shared tree under the fleet lock and p1
restored (rebuilt), as live/obs/tools/build_obs1.py. Refuses: a dirty tree, a tree not on p1, hk-obs1 not 2841211, a base file at
hk-obs1 that is not the one the change was written against, an existing hk-nfc1 not made by this script.

    python3 -I research/ios26-nfc-r1/tools/build_nfc1.py
Outputs: research/ios26-nfc-r1/build/kernel.nfc1{,.unstripped}, obj/ copies, receipts/0001-hk-nfc1.patch.
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
N = f"{R}/research/ios26-nfc-r1"
SRC = f"{N}/xnu-src"
OUT = f"{N}/build"
BASE_BR, BASE = "hk-obs1", "284121116f90c6549c8a3bc35250579c9cd9f155"
BR = "hk-nfc1"
WT = "/tmp/hk-nfc1-wt"
NEW = ["bsd/dev/blazer_nfc_hw.h", "bsd/dev/blazer_nfc_hw.c", "bsd/dev/blazer_nfc.c", "bsd/dev/blazer_cli10_bus.h"]
CHANGED = {  # path: sha256 of the hk-obs1 version the change was written against
    "bsd/dev/blazer_haptic.c": "0de643cc77cc32cfafe2a98fd88759582b33eed68e0d987543d8b413bbb0ffbd",
    "bsd/conf/files": "ccdaf62a603ba1e12c293a24335143523848cf055b3ac0f53981e19df7445e93",
    "bsd/kern/bsd_init.c": "0c3fc37115dbe1a3d18921d66d78b0b2e59ea82c7f3d10a2fcd48412f6323ae3",
}
MSG = """blazer nfc (hk-nfc1): ST21NFC on the haptics bus, blazer_nfc=1..4 (pads, probe + power-up CORE_RESET_NTF versions, NCI init, RF discovery)

cli10 bus lock shared with blazer_haptic (ID stage and each ROM effect; a tap while NFC holds the bus is EBUSY, skipped).
research/ios26-nfc-r1/DESIGN.md"""


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


def src_digest():
    h = hashlib.sha256()
    for p in sorted(NEW + list(CHANGED)):
        h.update(p.encode() + b"\0" + open(f"{SRC}/{p}", "rb").read())
    return h.hexdigest()


def build(name):
    with open(f"{LOGS}/{name}.log", "w") as f:
        rc = subprocess.run([MK, "-j8"], stdout=f, stderr=subprocess.STDOUT).returncode
    log(f"build {name} rc {rc}")
    return rc


def make_branch():
    dig = src_digest()
    if g("rev-parse", BASE_BR) != BASE:
        raise SystemExit(f"{BASE_BR} is not {BASE}, refusing")
    for p, want in CHANGED.items():
        have = hashlib.sha256(subprocess.run(["git", "-C", X, "show", f"{BASE}:{p}"], capture_output=True).stdout).hexdigest()
        if have != want:
            raise SystemExit(f"{p} at {BASE[:7]} is {have}, the change was written against {want}: refusing")
    have = g("rev-parse", "--verify", "-q", BR, check=False)
    if have:
        if g("rev-parse", f"{BR}~1") != BASE:
            raise SystemExit(f"{BR} is not one commit on {BASE}: not ours, refusing")
        if f"src-sha256: {dig}" in g("log", "-1", "--format=%B", BR):
            log(f"{BR} exists at {have}, made from these sources")
            return have
        log(f"{BR} at {have} was made from other sources: replaced")
        g("branch", "-D", BR)
    if os.path.exists(WT):
        raise SystemExit(f"{WT} exists")
    g("worktree", "add", "-q", "--detach", WT, BASE)
    try:
        for p in NEW + list(CHANGED):
            shutil.copyfile(f"{SRC}/{p}", f"{WT}/{p}")
        g("add", *NEW, *CHANGED, cwd=WT)
        g("-c", "user.name=Anders Madsen", "-c", "user.email=madsenanders97@gmail.com", "commit", "-q", "-m", f"{MSG}\n\nsrc-sha256: {dig}", cwd=WT)
        head = g("rev-parse", "HEAD", cwd=WT)
        g("branch", BR, head)
        os.makedirs(f"{N}/receipts", exist_ok=True)
        with open(f"{N}/receipts/0001-hk-nfc1.patch", "w") as f:
            f.write(g("format-patch", "--stdout", "-1", head, cwd=WT) + "\n")
        log(f"{BR} = {head} (on {BASE[:7]}), src {dig}")
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
    rc = build("nfc1-build")
    if rc == 0:
        os.makedirs(OUT, exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.nfc1"), ("kernel.development.blazer.unstripped", "kernel.nfc1.unstripped")):
            shutil.copyfile(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for o in ("blazer_nfc_hw.o", "blazer_nfc.o", "blazer_haptic.o", "bsd_init.o"):
            for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
                shutil.copyfile(h, f"{OUT}/obj/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("nfc1-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    log("restored p1 kernel has the blazer-nfc string: " + str(b"blazer-nfc: " in open(f"{OBJ}/kernel.development.blazer", "rb").read()))
sys.exit(rc)
