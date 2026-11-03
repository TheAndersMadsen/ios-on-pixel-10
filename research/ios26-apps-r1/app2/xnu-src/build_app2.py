#!/usr/bin/env python3
"""Mac only (repo root). New XNU branch hk-sandbox-token from hk-aks-usersession (cc42295, has the varfs RENAME_SWAP fix):
sandbox op 5 (extension issue) answers with libsandbox's no-op token "invalid" in argument word 4 and returns 0. Build
kernel.rootview-bl-app2, check the object/kernel, then restore the tree to its original branch (p1) and rebuild it.
Lock /tmp/fleet/kernel-build-slot.lock (same convention as usersession/xnu-src/build_us2.py); refuses a dirty tree."""
import fcntl, os, shutil, subprocess, sys, time, hashlib
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
MK = f"{R}/research/ios26-release-r1/tools/mk.sh"
LOGS = f"{R}/research/ios26-release-r1/logs"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = f"{R}/research/ios26-apps-r1/app2/build"
SRC = f"{R}/research/ios26-apps-r1/app2/xnu-src"
BASE, BASESHA, BR = "hk-aks-usersession", "cc422959eae4b482e3dbcbac4af6065d3a178aeb", "hk-sandbox-token"
OLD_CASE = """\tcase 5:         /* extension issue */
\tcase 6:         /* extension consume */
\t\treturn ENOENT;
"""
NEW_CASE = """\tcase SSI_OP_ISSUE: /* extension issue: libsandbox's own no-op token */
\t{
\t\tunsigned long long a[SSI_ARG_WORDS], dst = 0;
\t\tint error = copyin(arg, a, sizeof(a));
\t\tif (error == 0) {
\t\t\terror = ssi_issue_target(a, &dst) != 0 ? EINVAL :
\t\t\t    copyout(ssi_token, (user_addr_t)dst, sizeof(ssi_token));
\t\t}
\t\treturn error;
\t}
\tcase 6:         /* extension consume: "invalid" never gets here */
\t\treturn ENOENT;
"""
OLD_DOC = """ * data (container paths, extension tokens) fail with ENOENT. The first
 * use of each operation number is logged.
"""
NEW_DOC = """ * data fail with ENOENT, except extension issue (op 5), which hands out
 * libsandbox's no-op token "invalid" (sweet_sandbox_issue.h; consume
 * accepts it without a syscall). The first use of each operation number
 * is logged.
"""
OLD_INC = "#include <sys/sysctl.h>\n"
NEW_INC = "#include <sys/sysctl.h>\n#include \"sweet_sandbox_issue.h\"\n"
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
def once(text, old, new):
    if text.count(old) != 1: sys.exit(f"anchor not found exactly once: {old[:40]!r}")
    return text.replace(old, new)
os.makedirs(OUT, exist_ok=True)
lk = open("/tmp/fleet/kernel-build-slot.lock", "a")
log("waiting for build slot lock"); fcntl.flock(lk, fcntl.LOCK_EX); log("lock held")
while busy(): log(f"build running, waiting: {busy()}"); time.sleep(30)
orig = g("branch", "--show-current"); st = g("status", "--porcelain")
log(f"tree branch {orig} HEAD {g('rev-parse','--short','HEAD')} dirty={bool(st)}")
if st: sys.exit("tree dirty, refusing")
if g("rev-parse", BASE) != BASESHA: sys.exit(f"{BASE} is not at {BASESHA}, refusing")
if g("branch", "--list", BR): sys.exit(f"branch {BR} exists, refusing")
rc = 1
try:
    g("checkout", "-b", BR, BASE)
    shutil.copy2(f"{SRC}/sweet_sandbox_issue.h", f"{X}/bsd/kern/sweet_sandbox_issue.h")
    p = f"{X}/bsd/kern/sweet_amfi.c"; t = open(p).read()
    t = once(once(once(t, OLD_CASE, NEW_CASE), OLD_DOC, NEW_DOC), OLD_INC, NEW_INC)
    open(p, "w").write(t)
    g("add", "-A"); log("staged:\n" + g("diff", "--cached", "--stat"))
    g("commit", "-q", "-m", "sweet sandbox: extension issue (op 5) answers libsandbox's no-op token\n\n"
      "libsystem_sandbox's issue helper passes 7 u64 words with the caller's 0x3ff0-byte buffer in word 4; on failure it\n"
      "frees the buffer and returns NULL. Op 5 returned ENOENT, so containermanagerd handed out containers with a NULL\n"
      "sandbox token and SafariCore's WBSSetUpAccessToAppDataContainerWithIdentifier faulted in sandbox_extension_consume\n"
      "(Preferences SIGSEGV, wifi-join-r2). Write \"invalid\", which libsandbox itself issues for flag bit 0 and which\n"
      "consume accepts without a syscall. Nothing is enforced here, so nothing is extended. Consume (op 6) stays ENOENT.\n\n"
      "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    log(f"commit {g('rev-parse','HEAD')}")
    rc = build("app2-build")
    if rc == 0:
        for s, d in (("kernel.development.blazer", "kernel.rootview-bl-app2"), ("kernel.development.blazer.unstripped", "kernel.rootview-bl-app2.unstripped")):
            shutil.copy2(f"{OBJ}/{s}", f"{OUT}/{d}"); log(f"{sha(OUT+'/'+d)}  {d}")
        o = f"{OBJ}/bsd/DEVELOPMENT/sweet_amfi.o"
        nm = subprocess.run(["xcrun", "nm", "-m", o], capture_output=True, text=True).stdout
        log("sweet_amfi.o: " + "; ".join(l.strip() for l in nm.splitlines() if "sweet_sandbox_syscall" in l or "copyout" in l or "copyin" in l))
        log("sweet_amfi.o file: " + subprocess.run(["file", o], capture_output=True, text=True).stdout.strip())
        dis = subprocess.run(["xcrun", "otool", "-tV", o], capture_output=True, text=True).stdout
        open(f"{OUT}/sweet_amfi.o.otool.txt", "w").write(dis)
        log(f"sweet_amfi.o otool lines {len(dis.splitlines())}")
finally:
    if g("status", "--porcelain"): log("WARNING tree dirty after build:\n" + g("status", "--porcelain"))
    g("checkout", orig); log(f"restored branch {g('branch','--show-current')} HEAD {g('rev-parse','--short','HEAD')}")
    build("app2-restore-p1-build")
    log("obj kernel after restore " + sha(f"{OBJ}/kernel.development.blazer"))
sys.exit(rc)
