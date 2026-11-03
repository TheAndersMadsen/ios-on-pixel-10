#!/usr/bin/env python3
"""Mac only, repo root. B2 kernel: new branch hk-bt-b2 from hk-aks-usersession's cc42295 (the kernel of a7-ios-system-r10-perf,
kernel.rootview-bl-aks-us2 d7f47431), one commit with the candidate BT files (gate vendor list, deferred bridge start, QEMU fake
controller, bounded flow log). Builds kernel.bt2, then restores the tree to its original branch (p1) and rebuilds it.
Same lock and checks as research/ios26-apps-r1/usersession/xnu-src/build_us2.py."""
import fcntl, os, shutil, subprocess, sys, time, hashlib
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
B2 = f"{R}/research/ios26-connectivity-r1/bluetooth/b2"
OUT, SRC = f"{B2}/build", f"{B2}/xnu-src/candidate"
BR, PARENT = "hk-bt-b2", "cc42295"
FILES = ("blazer_bt_gate.c", "blazer_bt_gate.h", "blazer_bt_bridge.c", "blazer_btuart.c", "blazer_btuart_hw.c", "blazer_btuart_hw.h")
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
for f in FILES:
    base = g("show", f"{PARENT}:bsd/dev/{f}")
    if hashlib.sha256((base + "\n").encode()).hexdigest() != sha(f"{B2}/xnu-src/baseline/{f}"):
        sys.exit(f"baseline {f} differs from {PARENT}")
rc = 1
try:
    g("checkout", "-b", BR, PARENT)
    for f in FILES:
        shutil.copy2(f"{SRC}/{f}", f"{X}/bsd/dev/{f}")
    g("add", "-A"); log("staged:\n" + g("diff", "--cached", "--stat"))
    g("commit", "-q", "-m", "blazer bt (B2): Broadcom vendor list in the gate, bridge starts when the chip serves, QEMU fake controller\n\n"
      "Gate: 0xfc01 (6 bytes), 0xfc18 (only 4,000,000), 0xfc27 (only sleep mode 0), 0xfc6e and 0xfc79 (no parameters) reach the chip at\n"
      "level 0; every other vendor opcode stays local (Unknown HCI Command), a listed one with other parameters gets Command\n"
      "Disallowed. The kernel control and the nexus are registered from the link's ready hook when serving starts, so bluetoothd\n"
      "cannot spend the one session before the firmware is in. blazer_bt_qfake=N: QEMU only, no hardware, a fake controller\n"
      "behind the same bridge and gate after N s. The bridge logs the first 64 opcodes sent and Command Complete/Status opcodes\n"
      "and statuses received (no parameters, no addresses). Transmit levels unchanged (blazer_bt_tx default 0).\n\n"
      "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    log(f"commit {g('rev-parse','HEAD')}")
    rc = build("bt2-build")
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.bt2"), ("kernel.development.blazer.unstripped", "kernel.bt2.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}"); log(f"{sha(OUT+'/'+d)}  {d}")
finally:
    if g("status", "--porcelain"): log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig); log(f"restored branch {g('branch','--show-current')} HEAD {g('rev-parse','--short','HEAD')}")
    build("bt2-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
