#!/usr/bin/env python3
"""Mac, repo root. Single-file ARM64 compile of WORKTREE/bsd/kern/sweet_amfi.c with the kernel build's own command line
(compile_commands.json entry for sweet_amfi.c, BLAZER config), out of tree; then llvm-nm and a disassembly grep.
    python3 -I cc_amfi.py WORKTREE"""
import json, os, shlex, subprocess, sys, tempfile
R = os.getcwd(); W = sys.argv[1]
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
OUT = tempfile.mkdtemp(prefix="hk_amfi_cc.")
cc = {os.path.basename(e["file"]): e for e in json.load(open(f"{OBJ}/compile_commands.json"))}
e = cc["sweet_amfi.c"]
argv = shlex.split(e["command"]) if "command" in e else list(e["arguments"])
src = f"{W}/bsd/kern/sweet_amfi.c"
argv[argv.index(e["file"])] = src
obj = f"{OUT}/sweet_amfi.o"; argv[argv.index("-o") + 1] = obj
argv = [a for a in argv if a != "-w"]
argv += ["-Werror=implicit-function-declaration", "-Werror=int-conversion", "-Werror=incompatible-pointer-types",
         "-Werror=return-type", "-Wformat", "-Werror=format-security"]
r = subprocess.run(argv, cwd=e["directory"], capture_output=True, text=True)
print(f"== sweet_amfi.c rc {r.returncode}")
print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if "warning:" in l or "error:" in l)[:4000])
if r.returncode:
    sys.exit(1)
NM = subprocess.run(["xcrun", "-f", "llvm-nm"], capture_output=True, text=True).stdout.strip()
OD = subprocess.run(["xcrun", "-f", "llvm-objdump"], capture_output=True, text=True).stdout.strip()
nm = subprocess.run([NM, obj], capture_output=True, text=True).stdout
print("\n".join(l for l in nm.splitlines() if any(k in l for k in ("sweet_sandbox", "IOCurrentTaskGetEntitlement", "kfree_data", "copyout", "copyin"))))
d = subprocess.run([OD, "-d", "-r", "--no-show-raw-insn", obj], capture_output=True, text=True).stdout
blk = d.split("<_sweet_sandbox_syscall>:")[1].split("\n\n")[0] if "<_sweet_sandbox_syscall>:" in d else ""
print("sweet_sandbox_syscall insns", blk.count("\n"), "| cmp #0x2:", "#0x2" in blk)
blk2 = d.split("<_sweet_sandbox_check_self>:")[1].split("\n\n")[0] if "<_sweet_sandbox_check_self>:" in d else "(inlined)"
print("check_self relocs:", sorted(set(l.split()[-1] for l in blk2.splitlines() if "R_AARCH64" in l or "ARM64_RELOC" in l))[:20])
s = subprocess.run(["strings", obj], capture_output=True, text=True).stdout
print("strings:", [l for l in s.splitlines() if "self-check" in l or "profile:embedded" in l or l == "blastdoor"])
print(subprocess.run(["file", obj], capture_output=True, text=True).stdout.strip())
print(subprocess.run(["shasum", "-a", "256", src, f"{W}/bsd/kern/sweet_sandbox_check.h"], capture_output=True, text=True).stdout.strip())
subprocess.run(["rm", "-rf", OUT])
