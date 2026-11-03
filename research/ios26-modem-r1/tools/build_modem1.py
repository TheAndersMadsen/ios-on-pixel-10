#!/usr/bin/env python3
"""Mac, from the repository root. HOST ONLY. XNU branch hk-modem1 = hk-int3 (3dc7fec) + research/ios26-modem-r1/src (blazer_modem.c
replaced, blazer_modem_core.{c,h} added, one bsd/conf/files line), made in a throwaway worktree so the shared tree is never left on it;
then built in the shared tree under the fleet build lock and p1 restored (rebuilt), as live/obs/tools/build_obs1.py does.
Refuses: a dirty tree, a tree not on p1, hk-int3 not 3dc7fec, an existing hk-modem1 not one commit on hk-int3.

    python3 -I research/ios26-modem-r1/tools/build_modem1.py
Outputs: research/ios26-modem-r1/build/kernel.modem1{,.unstripped}, obj/ copies, xnu-src/0001-hk-modem1.patch, symbol receipts.
"""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
M = f"{R}/research/ios26-modem-r1"
SRC = f"{M}/src/bsd/dev"
OUT = f"{M}/build"
BASE_BR, BASE = "hk-int3", "3dc7fec3663746ed0390f360c3fa63031b970861"
BR = "hk-modem1"
WT = "/tmp/hk-modem1-wt"
FILES = ("blazer_modem.c", "blazer_modem_core.c", "blazer_modem_core.h")


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


def bundle_sha():
    h = hashlib.sha256()
    for n in FILES:
        h.update(n.encode() + b"\0" + open(f"{SRC}/{n}", "rb").read())
    return h.hexdigest()


def make_branch():
    want = bundle_sha()
    base = g("rev-parse", BASE_BR)
    if not base.startswith(BASE):
        raise SystemExit(f"{BASE_BR} is {base}, not {BASE}: refusing")
    have = g("rev-parse", "--verify", "-q", BR, check=False)
    if have:
        if g("rev-parse", f"{BR}~1") != base:
            raise SystemExit(f"{BR} is not one commit on {base}: not ours, refusing")
        if f"src-sha256: {want}" in g("log", "-1", "--format=%B", BR):
            log(f"{BR} exists at {have}, made from this source")
            return have
        log(f"{BR} at {have} was made from earlier source: replaced")
        g("branch", "-D", BR)
    if os.path.exists(WT):
        raise SystemExit(f"{WT} exists")
    g("worktree", "add", "-q", "--detach", WT, base)
    try:
        for n in FILES:
            shutil.copyfile(f"{SRC}/{n}", f"{WT}/bsd/dev/{n}")
        files = f"{WT}/bsd/conf/files"
        text = open(files).read()
        anchor = "bsd/dev/blazer_modem.c\t\t\tstandard\n"
        if anchor not in text or "blazer_modem_core.c" in text:
            raise SystemExit("bsd/conf/files: anchor missing or core already listed")
        open(files, "w").write(text.replace(anchor, anchor + "bsd/dev/blazer_modem_core.c\t\tstandard\n", 1))
        g("add", "bsd/dev/blazer_modem.c", "bsd/dev/blazer_modem_core.c", "bsd/dev/blazer_modem_core.h", "bsd/conf/files", cwd=WT)
        msg = ("blazer modem: S5400 rungs 1..4 (read, PCIe0 ctrl, PHY, CP power-on + boot ROM link + config ID), off unless blazer_modem=N "
               "or hk_dbg bits 24..27\n\nresearch/ios26-modem-r1/MODEM.md. No firmware, no CP memory, no endpoint config write.\n\n"
               f"src-sha256: {want}\n")
        g("-c", "user.name=Anders Madsen", "-c", "user.email=madsenanders97@gmail.com", "commit", "-q", "-m", msg, cwd=WT)
        head = g("rev-parse", "HEAD", cwd=WT)
        g("branch", BR, head)
        os.makedirs(f"{M}/xnu-src", exist_ok=True)
        with open(f"{M}/xnu-src/0001-hk-modem1.patch", "w") as f:
            f.write(g("format-patch", "-1", "--stdout", head, cwd=WT) + "\n")
        log(f"{BR} = {head} (on {base[:7]}); patch sha256 {sha(M + '/xnu-src/0001-hk-modem1.patch')}")
    finally:
        g("worktree", "remove", "--force", WT, check=False)
    return head


def receipts():
    """ARM64 objects and their symbols; the kernel's strings and the call from bsd_init."""
    lines = []
    for o in ("blazer_modem.o", "blazer_modem_core.o", "bsd_init.o"):
        for h in subprocess.run(["find", OBJ, "-name", o], capture_output=True, text=True).stdout.split():
            shutil.copy2(h, f"{OUT}/obj/{o}")
            ft = subprocess.run(["file", "-b", h], capture_output=True, text=True).stdout.strip()
            nm = subprocess.run(["nm", "-m", h], capture_output=True, text=True).stdout
            syms = [l.split()[-1] for l in nm.splitlines() if "external" in l and ("_m0_" in l or "blazer_modem" in l or "hk_dbg" in l or "cpmq" in l)]
            lines.append(f"{sha(h)}  {o}  {ft}\n  symbols: {' '.join(sorted(set(syms)))}")
    k = f"{OUT}/kernel.modem1.unstripped"
    data = open(k, "rb").read()
    for s in (b"blazer-modem: verdict: PASS stage %u", b"PCIe0 power vote", b"S5400 CP boot ROM", b"CP not off as found", b"hk_dbg"):
        lines.append(f"kernel string {s.decode()!r}: {s in data}")
    nm = subprocess.run(["nm", k], capture_output=True, text=True).stdout
    for s in ("_blazer_modem_init", "_m0_run", "_blazer_modem_obs", "_modem_thread", "_hk_dbg_bits"):
        lines.append(f"kernel symbol {s}: {any(l.endswith(' ' + s) for l in nm.splitlines())}")
    od = subprocess.run(["xcrun", "-f", "llvm-objdump"], capture_output=True, text=True).stdout.strip() or "llvm-objdump"
    dis = subprocess.run([od, "-d", "--disassemble-symbols=_bsd_init", k], capture_output=True, text=True).stdout
    lines.append("bsd_init calls _blazer_modem_init: " + str("<_blazer_modem_init>" in dis))  # otool -p misses it on the fileset kernel
    open(f"{OUT}/receipts.txt", "w").write("\n".join(lines) + "\n")
    log("receipts:\n" + "\n".join(lines))


lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock")
fcntl.flock(lk, fcntl.LOCK_EX)
log("lock held")
while busy():
    log(f"build running, waiting: {busy()}")
    time.sleep(30)
orig = g("branch", "--show-current")
log(f"tree branch {orig} HEAD {g('rev-parse', '--short', 'HEAD')}")
if g("status", "--porcelain", "--untracked-files=no"):
    raise SystemExit("tree dirty, refusing")
if orig != "p1":
    raise SystemExit(f"tree is on {orig}, not p1: refusing")
head = make_branch()
rc = 1
try:
    g("checkout", "-q", BR)
    log(f"checked out {BR} {g('rev-parse', 'HEAD')}")
    for n in FILES:     # make skips files whose mtime is old (playbook: build mtimes)
        os.utime(f"{X}/bsd/dev/{n}")
    os.utime(f"{X}/bsd/conf/files")
    rc = build("modem1-build")
    if rc == 0:
        os.makedirs(f"{OUT}/obj", exist_ok=True)
        for s, d in (("kernel.development.blazer", "kernel.modem1"), ("kernel.development.blazer.unstripped", "kernel.modem1.unstripped")):
            shutil.copyfile(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        receipts()
finally:
    if g("status", "--porcelain", "--untracked-files=no"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
        g("reset", "-q", "--hard")
    g("checkout", "-q", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("modem1-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
    log("restored p1 kernel has the modem1 core: " + str(b"PCIe0 power vote" in open(f"{OBJ}/kernel.development.blazer", "rb").read()))
sys.exit(rc)
