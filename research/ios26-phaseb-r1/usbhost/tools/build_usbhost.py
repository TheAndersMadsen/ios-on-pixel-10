#!/usr/bin/env python3
"""Mac, from the repository root. HOST ONLY. XNU branch hk-usbhost1 = hk-obs1 (284121116f) + usbhost/patches/0001-*.patch
(two new files in osfmk/arm64, one line in osfmk/conf/files.arm64, two in osfmk/kern/startup.c), made in a throwaway
worktree; built in the shared tree under the fleet lock; p1 restored and rebuilt. As live/obs/tools/build_obs1.py.
Refuses: a dirty tree, a tree not on p1, hk-obs1 not 284121116f, a patch whose sha256 is not the given one, an
existing hk-usbhost1 made from another patch, a built kernel without the blazer-usbhost strings.

    python3 -I research/ios26-phaseb-r1/usbhost/tools/build_usbhost.py PATCH_SHA256
Outputs: research/ios26-phaseb-r1/usbhost/build/kernel.usbhost1{,.unstripped}, build/obj/blazer_usbhost.o (+ .nm.txt).
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
U = f"{R}/research/ios26-phaseb-r1/usbhost"
OUT = f"{U}/build"
PATCH = f"{U}/patches/0001-blazer_usbhost-DWC3-host-mode-enumerate-one-device.patch"
BASE_BR, BASE = "hk-obs1", "284121116f90c6549c8a3bc35250579c9cd9f155"
BR = "hk-usbhost1"
WT = "/tmp/hk-usbhost1-wt"
NEED = (b"blazer-usbhost: ENUM port %u speed %s dev %04x:%04x", b"blazer_usbhost_window", b"HKOBS %u")
ID = ["-c", "user.name=Anders Madsen", "-c", "user.email=madsenanders97@gmail.com"]
MSG = """blazer_usbhost: DWC3 host mode on the USB2 root ports, enumerate one device (boot-arg gated)

blazer_usbhost=1, refused with blazer_usbcon (one controller, one owner; results come back in the ramdump).
After blazer_usbhost_wait s (90): stop the shim's gadget, retire its event buffer, core soft reset into
PRTCAP host, start the xHCI polled (arena 0xbee00000, 64 KiB in abl@be000000), power the USB2 root ports
only, wait blazer_usbhost_window s (150) for a connect, reset it, Enable Slot, Address Device, read the
device/configuration/product descriptors, one ENUM line each. Read-only survey of the TCA and dp_top_csr
first (DP alt-mode map). Never sources VBUS or writes the PHY, TCA, repeater, TCPC, charger, clocks or CPM.
Core blazer_usbhost_core.inc has no XNU types and is host-tested against an xHCI model
(research/ios26-phaseb-r1/usbhost/tests).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"""


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
    if len(sys.argv) != 2 or sha(PATCH) != sys.argv[1]:
        raise SystemExit(f"patch is {sha(PATCH)}; pass that sha256 after reviewing it")
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
        g("apply", "-p1", "--whitespace=nowarn", PATCH, cwd=WT)
        for f in ("osfmk/arm64/blazer_usbhost.c", "osfmk/arm64/blazer_usbhost_core.inc"):
            if sha(f"{WT}/{f}") != sha(f"{U}/xnu-src/{os.path.basename(f)}"):
                raise SystemExit(f"{f} in the patch differs from xnu-src/: regenerate the patch")
        g("add", "-A", cwd=WT)
        g(*ID, "commit", "-q", "-m", f"{MSG}\n\npatch-sha256: {sys.argv[1]}", cwd=WT)
        head = g("rev-parse", "HEAD", cwd=WT)
        g("branch", BR, head)
        log(f"{BR} = {head} (on {BASE[:7]})\n" + g("show", "--stat", "--format=", head))
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
    for f in ("osfmk/arm64/blazer_usbhost.c", "osfmk/arm64/blazer_usbhost_core.inc", "osfmk/kern/startup.c", "osfmk/conf/files.arm64"):
        os.utime(f"{X}/{f}")    # newer than any object another branch's build left (NET.md build pitfall)
    log(f"checked out {BR} {g('rev-parse', 'HEAD')}")
    rc = build("usbhost1-build")
    if rc == 0:
        k = open(f"{OBJ}/kernel.development.blazer", "rb").read()
        lacking = [n.decode() for n in NEED if n not in k]
        if lacking:
            log(f"built kernel lacks {lacking}: stale objects, refusing")
            rc = 1
    if rc == 0:
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.usbhost1"), ("kernel.development.blazer.unstripped", "kernel.usbhost1.unstripped")):
            shutil.copyfile(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        for o in ("blazer_usbhost.o", "blazer_usbcon.o", "startup.o"):
            for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
                shutil.copyfile(h, f"{OUT}/obj/{o}")
                log(f"{sha(h)}  {o} ({h[len(OBJ):]})")
        nm = subprocess.run(["nm", "-m", f"{OUT}/kernel.usbhost1.unstripped"], capture_output=True, text=True).stdout
        for s in ("_blazer_usbhost_start", "_usbhost_thread", "_blazer_usbcon_start"):
            log(next((l for l in nm.splitlines() if l.endswith(" " + s)), f"MISSING {s}"))
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("usbhost1-restore-p1-build")
    k = open(f"{OBJ}/kernel.development.blazer", "rb").read()
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer") + ", blazer-usbhost absent: " +
        str(b"blazer_usbhost_window" not in k))
sys.exit(rc)
