#!/usr/bin/env python3
"""Mac, repo root. Single-file ARM64 compile of the hk_ustack sources with the kernel build's own command line (hk_top.c's and
blazer_usbcon.c's entries in compile_commands.json, BLAZER=1 as built), out of tree: the release tree is not touched.
Then llvm-nm the objects. Gate BLAZER is on in those commands; a guarded empty object would have no hk_ustack_* symbols."""
import json, os, shlex, subprocess, sys, tempfile
R = os.getcwd()
X = f"{R}/research/ios26-release-r1/work/xnu"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER"
U = f"{R}/research/ios26-phaseb-r1/live/ustack/xnu-src"
OUT = tempfile.mkdtemp(prefix="hk_ustack_cc.")
cc = {os.path.basename(e["file"]): e for e in json.load(open(f"{OBJ}/compile_commands.json"))}
NM = subprocess.run(["xcrun", "-f", "llvm-nm"], capture_output=True, text=True).stdout.strip() or "nm"
rc = 0
for proto, src, extra_inc in (("hk_top.c", f"{U}/osfmk/kern/hk_ustack.c", [f"{U}/osfmk"]),
                              ("blazer_usbcon.c", f"{U}/osfmk/arm64/blazer_usbcon.c", [f"{U}/osfmk", f"{U}/osfmk/arm64", f"{X}/osfmk/arm64"])):
    e = cc[proto]
    argv = shlex.split(e["command"]) if "command" in e else list(e["arguments"])
    i = argv.index(e["file"]); argv[i] = src
    o = argv.index("-o"); obj = f"{OUT}/{os.path.basename(src)}.o"; argv[o + 1] = obj
    argv = [a for a in argv if a != "-w"]
    argv[1:1] = [f"-I{p}" for p in extra_inc]
    argv += ["-Werror=implicit-function-declaration", "-Werror=int-conversion", "-Werror=incompatible-pointer-types",
             "-Werror=return-type", "-Wformat", "-Werror=format-security"]
    r = subprocess.run(argv, cwd=e["directory"], capture_output=True, text=True)
    print(f"== {os.path.basename(src)} rc {r.returncode}")
    print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if "warning:" in l or "error:" in l)[:6000])
    if r.returncode:
        rc = 1; continue
    nm = subprocess.run([NM, obj], capture_output=True, text=True).stdout
    keep = [l for l in nm.splitlines() if any(k in l for k in ("hk_ustack", "hk_us_", "copyinmap", "bsd_getthreadname",
            "recount_thread_time_mach", "uc_setup", "PE_parse_boot_arg_str", "tasks_threads_lock", "thread_wakeup", "get_user_regs"))]
    print("\n".join(sorted(keep)))
    print(subprocess.run(["file", obj], capture_output=True, text=True).stdout.strip())
    print(subprocess.run(["shasum", "-a", "256", src], capture_output=True, text=True).stdout.strip())
subprocess.run(["rm", "-rf", OUT])
sys.exit(rc)
