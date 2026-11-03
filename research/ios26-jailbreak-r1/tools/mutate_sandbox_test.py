#!/usr/bin/env python3
"""HOST ONLY: prove the sandbox host test kills semantic regressions. No device access."""
from pathlib import Path
import os
import subprocess
import tempfile

A = Path("research/ios26-jailbreak-r1")
header = (A / "src/sweet_sandbox_check.h").read_text()
test = (A / "tools/test_sandbox_check.c").read_text()
mutations = {
    "blastdoor-only": ("return profile != 0 && profile[0] != 0;", "return profile != 0 && profile[0] == 'b';"),
    "null-profile-sandboxed": ("return profile != 0 && profile[0] != 0;", "return profile == 0 || profile[0] != 0;"),
    "drop-self-pid": (" || (long long)args[1] != self_pid", ""),
    "drop-null-operation": ("args[2] != 0 || ", ""),
    "drop-filter-type": (" || args[3] != 0", ""),
    "drop-result-pointer-check": ("args[0] == 0 || ", ""),
}
failed = []
with tempfile.TemporaryDirectory(prefix="hk-jb1-mutants.") as td:
    for name, (old, new) in mutations.items():
        assert header.count(old) == 1, (name, old)
        d = Path(td) / name
        d.mkdir()
        (d / "sweet_sandbox_check.h").write_text(header.replace(old, new))
        (d / "test.c").write_text(test)
        exe = d / "test"
        cc = os.environ.get("CC", "cc")
        subprocess.run([cc, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-I", str(d), str(d / "test.c"), "-o", str(exe)], check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        killed = run.returncode != 0
        print(f"{name}: {'KILLED' if killed else 'SURVIVED'} (rc {run.returncode})")
        if not killed:
            failed.append(name)
print(f"{'FAIL' if failed else 'PASS'}: {len(mutations) - len(failed)}/{len(mutations)} mutations killed")
raise SystemExit(bool(failed))
