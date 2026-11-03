#!/usr/bin/env python3
"""Mac only, from the repo root. Build kernel.rootview-wifi-r5 = hk-wifi-join4: hk-wifi-join3 885589f (r4) + r5 (1024 host RX buffers in 2.5 MiB,
capped by max_host_rxbufs; the firmware's EL 30 b8c8 drops counted), then restore the tree. r4's build_wifi_r4.py otherwise (same lock, pins, restore).
Usage: python3 -I research/ios26-connectivity-r1/wifi/r5/build_wifi_r5.py <full hk-wifi-join4 commit>."""
import fcntl, hashlib, os, shutil, subprocess, sys, time
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-dualboot-r8/rootview"
WT = f"{R}/research/ios26-connectivity-r1/wifi/r5/xnu-wt"
BRANCH, BASE = "hk-wifi-join4", "76bcd0325042ddd11ec52a7bcd2a6906c3a2da73"   # r5 b: the M1 and MAC-fill lines on r5 a (76bcd03, on r4 885589f)
FW = f"{R}/research/ios26-wifi-r1/fw-57.31"
FW_PIN = {
    "fw_bcmdhd.bin_4390_b1": "db46afd65f4e3d9ec4f825bc52f2487195f9bb0d43062baade35c68b26c92864",
    "bcmdhd.cal_USI_G7BB_7311_V11": "fe7cf29218f8cea8a5cf43a8e46c735f84f336004b9236e3d46e7a4990da1bc5",
    "bcmdhd_clm.blob_4390_b1": "9ad4c6ceff1ff29eb1cd30f585103a69425cc15d3bfc66786d941d0b8661596e",
    "bcmdhd_txcap.blob_ROW": "75c0515da4e74de05d67f53f0ffa1145d5ce5a2c3261303b15fd78531b6f697a",
    "bcmdhd.cal_USI_G7BB_7321_V21": "b08be0e8ff5b98c28aa7e0d1481c989834c0ea46d7a2f49782c1ad075abc295d",
    "bcmdhd.cal_USI_G6BB_6327_V27": "44dec2d4052152bcbe6e4cdb9e8bb672b9be706d9c8a7856dd004db9b2796305",
    "bcmdhd.cal_4390_b1": "226c3f62fca1071c6808a7eb3a90a864ed7d1872ecc63fa974255c228b57a637",
}


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


for n, h in FW_PIN.items():
    if sha(f"{FW}/{n}") != h:
        sys.exit(f"fw-57.31/{n} is not the pinned {h[:8]}, refusing")
log("fw-57.31: all 7 files as pinned")
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
    rc = build("wifi-r5-build")
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.rootview-wifi-r5"), ("kernel.development.blazer.unstripped", "kernel.rootview-wifi-r5.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}")
            log(f"{sha(OUT + '/' + d)}  {d}")
        k = open(f"{OUT}/kernel.rootview-wifi-r5", "rb").read()
        fw = open(f"{FW}/fw_bcmdhd.bin_4390_b1", "rb").read()
        log(f"kernel holds the .57.31 firmware bytes: {fw in k}; a .57.30 version string: {b'27.10.1121.57.30 (ge2638ec' in k}")
        if fw not in k or b"27.10.1121.57.30 (ge2638ec" in k:
            rc = 2
        for t in (b"Firmware drops for want of a host buffer (EL 30 b8c8)", b"no host RX buffer was queued (EL 30 b8c8)", b"r1-r4 posted 64", b"join: M1 received: %s (supplicant %s)", b"above the %u the MAC fill holds"):
            log(f"kernel string {t.decode()!r}: {t in k}")
            if t not in k:
                rc = 3
finally:
    if g("status", "--porcelain"):
        log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig)
    log(f"restored branch {g('branch', '--show-current')} HEAD {g('rev-parse', '--short', 'HEAD')}")
    build("wifi-r5-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
