#!/usr/bin/env python3
"""Mac, repo root: compile xnu-src/blazer_usbhost.c into a real arm64 kernel object with the exact command line the
current XNU build used for osfmk/arm64/blazer_usbcon.o (its .o.json), and list its symbols. Read-only on the XNU tree
and its build: the source is a copy outside the tree, the object goes to usbhost/build/. No lock needed (nothing in
the tree or obj is written). -w is kept (XNU headers), plus -Werror for the classes that matter.
USBHOST.md, 'ARM64 object'."""
import hashlib, json, os, shutil, subprocess, sys
R = os.getcwd()
U = f"{R}/research/ios26-phaseb-r1/usbhost"
OBJ = f"{R}/research/ios26-release-r1/work/build/obj/DEVELOPMENT_ARM64_BLAZER/osfmk/DEVELOPMENT"
OUT = f"{U}/build"
SRC = f"{OUT}/src"
os.makedirs(SRC, exist_ok=True)
for f in ("blazer_usbhost.c", "blazer_usbhost_core.inc"):
    shutil.copyfile(f"{U}/xnu-src/{f}", f"{SRC}/{f}")
raw = open(f"{OBJ}/blazer_usbcon.o.json").read().strip().rstrip(",")
d = json.loads(raw)
a = list(d["arguments"])
i = a.index("-xc"); assert a[i + 1].endswith("/osfmk/arm64/blazer_usbcon.c"), a[i + 1]
a[i + 1] = f"{SRC}/blazer_usbhost.c"
j = a.index("-o"); a[j + 1] = f"{OUT}/blazer_usbhost.o"
assert "-DBLAZER=1" in a or ("-D" in a and "BLAZER=1" in a), "BLAZER gate missing from the reference command"
a += ["-Werror=implicit-function-declaration", "-Werror=incompatible-pointer-types", "-Werror=int-conversion",
      "-Werror=return-type", "-Werror=shorten-64-to-32"]
r = subprocess.run(a, cwd=d["directory"], capture_output=True, text=True)
sys.stdout.write(r.stdout); sys.stderr.write(r.stderr)
if r.returncode:
    sys.exit(f"compile failed rc {r.returncode}")
tc = os.path.dirname(a[0])
nm = next(p for p in (f"{tc}/llvm-nm", f"{tc}/nm", shutil.which("nm")) if p and os.path.exists(p))
syms = subprocess.run([nm, "-m", f"{OUT}/blazer_usbhost.o"], capture_output=True, text=True).stdout
open(f"{OUT}/blazer_usbhost.o.nm.txt", "w").write(syms)
filet = subprocess.run(["file", f"{OUT}/blazer_usbhost.o"], capture_output=True, text=True).stdout
strs = subprocess.run(["strings", "-a", f"{OUT}/blazer_usbhost.o"], capture_output=True, text=True).stdout
print(filet.strip())
print("sha256", hashlib.sha256(open(f"{OUT}/blazer_usbhost.o", "rb").read()).hexdigest(), "blazer_usbhost.o")
want_def = ["_blazer_usbhost_start", "_usbhost_thread"]   # the core is static and -O2 inlines it into usbhost_thread
want_undef = ["_ml_io_map", "_blazer_stamp_page", "_kernel_thread_start_priority", "_PE_parse_boot_argn"]
want_str = ["blazer-usbhost: ENUM port %u speed %s dev %04x:%04x", "blazer_usbhost_window", "blazer-usbhost: refused: %s",
            "blazer-usbhost: host mode, GCTL %x, glue", "blazer-usbhost: xhci %x caplen %u", "address device: %s, cc %u",
            "blazer-usbhost: PASS, port %u enumerated", "blazer-usbhost: survey TCA", "blazer-usbhost: ep0 max packet %u"]
missing = [s for s in want_def if not any(l.endswith(" " + s) and "undefined" not in l for l in syms.splitlines())]
missing += [s for s in want_undef if not any(l.endswith(" " + s) and "undefined" in l for l in syms.splitlines())]
missing += [s for s in want_str if s not in strs]
for s in want_def + want_undef:
    print(next((l for l in syms.splitlines() if l.endswith(" " + s)), f"MISSING {s}"))
if "arm64" not in filet:
    missing.append("not an arm64 object")
if missing:
    sys.exit(f"missing: {missing}")
sects = subprocess.run(["size", "-m", f"{OUT}/blazer_usbhost.o"], capture_output=True, text=True).stdout
open(f"{OUT}/blazer_usbhost.o.size.txt", "w").write(sects)
print(next((l.strip() for l in sects.splitlines() if "__text" in l), "no __text?"))
print("OK: arm64 object with the implementation symbols (static functions may be inlined; the list above is what nm shows)")
