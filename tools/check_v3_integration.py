#!/usr/bin/env python3
"""Compile the example against the real v3 shim source without editing it."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "research/laguna-usb-console"
V3 = ROOT / "shim"
OUT = LANE / "out"


def main():
    source = (V3 / "shim.c").read_text()
    marker = "void shim_main(uint64_t dtb)\n"
    if source.count(marker) != 1:
        raise SystemExit("v3 shim_main marker changed; integration review required")
    source = source.replace(marker, '#include "teguload_v3_usb.inc"\n\n' + marker)
    call = '''\tstage = "payload admission";\n'''
    replacement = '''\tstage = "USB diagnostic";
\tint usb_status = tgl_usb_console_start();
\tcon_hex2("USB", "init=", (uint32_t)(int32_t)usb_status,
\t    "active=", laguna_usb_transfer_active());
\ttgl_usb_console_wait();
\tstage = "payload admission";
'''
    if source.count(call) != 1:
        raise SystemExit("v3 payload-admission marker changed; integration review required")
    source = source.replace(call, replacement)
    generated = OUT / "v3-usb-integration.c"
    generated.write_text(source)
    compiler = os.environ.get("CLANG", "clang")
    object_path = OUT / "v3-usb-integration.arm64.o"
    command = [
        compiler, "--target=aarch64-none-elf", "-O2", "-ffreestanding",
        "-fno-builtin", "-nostdlib", "-fno-pic", "-mgeneral-regs-only",
        "-mstrict-align", "-fno-stack-protector", "-fno-jump-tables",
        "-Wall", "-Wextra", "-Werror", "-DTGL_USB_WAIT_SECONDS=1",
        "-I" + str(OUT), "-I" + str(LANE / "shim"),
        "-I" + str(LANE / "integration"), "-I" + str(V3),
        "-c", str(generated), "-o", str(object_path),
    ]
    subprocess.run(command, check=True)
    readelf = os.environ.get("LLVM_READELF", "/opt/homebrew/opt/llvm/bin/llvm-readelf")
    relocations = subprocess.check_output([readelf, "-r", str(object_path)], text=True)
    if "ABS64" in relocations:
        raise SystemExit("absolute ABS64 relocation in v3 integration object")
    print("PASS v3 integration compile (DMA admission remains default-off)")


if __name__ == "__main__":
    main()
