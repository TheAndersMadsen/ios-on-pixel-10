#!/usr/bin/env python3
"""Capture bounded laguna ramdump regions from an existing ABL fastboot state.

Read-only device policy: enumeration, getvar, ramdump-mode query, named
stage_file, and get_staged only.  No reboot, flash, slot/mode/devinfo/policy
write, raw-bank staging, or bare region listing in the default capture path.

Usage:
  python3 capture-fastboot.py /path/to/new-evidence-dir
  python3 capture-fastboot.py /path/to/new-evidence-dir --probe-only
  python3 capture-fastboot.py /path/to/new-evidence-dir --diagnostics
  python3 capture-fastboot.py /path/to/new-evidence-dir --list-only
  python3 capture-fastboot.py /path/to/new-evidence-dir --diagnostics --named-only

The default first proves the upload channel with RAMDUMP_MSG.txt (1 KiB), then
retrieves kernel.log (4 MiB, PA 0x95200000..0x955fffff).  --diagnostics then
adds bootreason.log, abl.log, and abl_last.log after the primary evidence is
safe.  --list-only runs the optional bare listing with a hard 10-second bound;
the ABL listing code only formats names/sizes and does not read raw banks.  The
phone must ALREADY be in a responsive ABL fastboot session.  USB enumeration
alone is insufficient: the
original zero-byte sequence followed a bare-listing hang that left every later
fastboot command timing out.  The output directory must be new.

--named-only skips every probe and captures the five fixed regions with
stage_file/get_staged alone, for capture by hand.

A zero-byte output is always a failed capture, never an empty-region success.
Modern fastboot creates the local output before issuing `upload`; preserve the
command log to distinguish FAIL/timeout/transport errors from a DATA length.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import time

REGIONS = {
    "RAMDUMP_MSG.txt": 0x400,
    "kernel.log": 0x400000,
    "bootreason.log": 0x200,
    "abl.log": 0x80000,
    "abl_last.log": 0x80000,
}
DIAGNOSTIC_REGIONS = ("bootreason.log", "abl.log", "abl_last.log")


def decode_abl_log(data):
    """Return only the current prefix of an ABL u64-offset/capacity log."""
    if len(data) < 16:
        raise RuntimeError("truncated ABL log header")
    offset, capacity = struct.unpack_from("<QQ", data)
    if not offset and not capacity and not any(data):
        return b""
    if capacity != len(data) - 16 or offset > capacity:
        raise RuntimeError("unknown ABL log header")
    return data[16:16 + offset]


def run_bounded(argv, timeout, cwd=None):
    """Kill the whole fastboot child process group on a hard timeout."""
    started = datetime.datetime.now(datetime.timezone.utc)
    monotonic = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        output = proc.communicate(timeout=timeout)[0]
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGKILL)
        output = proc.communicate()[0]
    return {
        "argv": argv,
        "cwd": str(cwd) if cwd is not None else None,
        "started_utc": started.isoformat(),
        "elapsed_seconds": round(time.monotonic() - monotonic, 3),
        "timeout_seconds": timeout,
        "returncode": proc.returncode,
        "output": output,
        "timed_out": timed_out,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--fastboot", default="fastboot")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list-only", action="store_true")
    mode.add_argument("--probe-only", action="store_true")
    mode.add_argument("--diagnostics", action="store_true",
                      help="also capture bootreason.log, abl.log, and abl_last.log")
    parser.add_argument("--named-only", action="store_true",
                        help="five fixed named diagnostics, no probes/listings; requires --diagnostics")
    args = parser.parse_args()
    if args.named_only and not args.diagnostics:
        parser.error("--named-only requires --diagnostics and excludes listing/probe modes")

    out_dir = args.out_dir.resolve()
    if out_dir.exists():
        parser.error(f"refusing to reuse existing evidence directory: {out_dir}")
    out_dir.mkdir(parents=True, mode=0o700)

    manifest = {
        "captured_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "in-progress",
        "device_writes": "none",
        "default_skips_bare_listing": True,
        "requires_responsive_abl_not_fastbootd": True,
        "list_only": args.list_only,
        "probe_only": args.probe_only,
        "diagnostics": args.diagnostics,
        "commands": [],
        "files": {},
    }
    if args.named_only:
        manifest["named_only"] = True
    records = []

    def save():
        manifest["commands"] = [{
            "argv": record["argv"],
            "cwd": record["cwd"],
            "started_utc": record["started_utc"],
            "elapsed_seconds": record["elapsed_seconds"],
            "timeout_seconds": record["timeout_seconds"],
            "returncode": record["returncode"],
            "timed_out": record["timed_out"],
            "log": record["log"],
        } for record in records]
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    def invoke(argv, timeout, log_name, cwd=None, output_transform=None):
        record = run_bounded(argv, timeout, cwd)
        output = record["output"]
        if output_transform is not None:
            output = output_transform(output)
        record["log"] = log_name
        (out_dir / log_name).write_bytes(output)
        records.append(record)
        save()
        if record["timed_out"] or record["returncode"] != 0:
            raise RuntimeError(
                f"command failed or timed out: {' '.join(argv)}; see {log_name}"
            )
        return record["output"]

    def capture(name, timeout):
        expected = REGIONS[name]
        invoke([args.fastboot, "oem", "ramdump", "stage_file", name], 15,
               f"stage-{name}")
        # get_staged's argument is a HOST output path, not a device region name.
        invoke([args.fastboot, "get_staged", name], timeout,
               f"get-staged-{name}", cwd=out_dir)
        target = out_dir / name
        if not target.is_file():
            raise RuntimeError(f"fastboot returned success without creating {target}")
        size = target.stat().st_size
        if size == 0:
            raise RuntimeError(
                f"{name}: zero-byte failure artifact; inspect get-staged-{name} "
                "and the preceding stage log"
            )
        if size != expected:
            raise RuntimeError(f"{name}: got {size:#x} bytes, expected {expected:#x}")
        raw = target.read_bytes()
        manifest["files"][name] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if name in ("abl.log", "abl_last.log"):
            decoded = decode_abl_log(raw)
            decoded_name = name + ".txt"
            (out_dir / decoded_name).write_bytes(decoded)
            manifest["files"][name].update({
                "current_prefix_bytes": len(decoded),
                "decoded_current_prefix": decoded_name,
            })
        save()

    try:
        if not args.named_only:
            host_version = invoke([args.fastboot, "--version"], 5,
                                  "host-fastboot-version.txt")
            manifest["host_fastboot_version"] = host_version.decode(
                "utf-8", "replace"
            ).splitlines()
            save()

            devices = invoke(
                [args.fastboot, "devices"], 5, "devices.txt",
                output_transform=lambda _output: b"<fastboot device list redacted>\n",
            )
            attached = [line for line in devices.splitlines()
                        if line.strip() and not line.startswith(b"<")]
            if len(attached) != 1:
                raise RuntimeError(
                    f"expected exactly one ABL fastboot device, observed {len(attached)}"
                )

            product = invoke([args.fastboot, "getvar", "product"], 8, "product.txt")
            if not re.search(rb"product:\s*blazer(?:\s|$)", product):
                raise RuntimeError("expected product:blazer in ABL fastboot; stopped before staging")
            userspace = invoke([args.fastboot, "getvar", "is-userspace"], 8,
                               "is-userspace.txt")
            if not re.search(rb"is-userspace:\s*no(?:\s|$)", userspace):
                raise RuntimeError("expected ABL fastboot (is-userspace:no), not fastbootd")
            invoke([args.fastboot, "getvar", "version-bootloader"], 8,
                   "bootloader-version.txt")
            enter_reason = invoke([args.fastboot, "getvar", "enter-reason"], 8,
                                  "enter-reason.txt")
            manifest["fastboot_enter_reason"] = enter_reason.decode("utf-8", "replace")
            save()

            mode_output = invoke([args.fastboot, "oem", "ramdump"], 8, "ramdump-mode.txt")
            manifest["ramdump_mode_query"] = mode_output.decode("utf-8", "replace")
            save()

        if args.list_only:
            listing = invoke([args.fastboot, "oem", "ramdump", "stage_file"], 10,
                             "regions.txt")
            if b"kernel.log" not in listing:
                raise RuntimeError("bare listing completed without kernel.log")
        else:
            capture("RAMDUMP_MSG.txt", 20)
            if not args.probe_only:
                capture("kernel.log", 60)
                manifest["files"]["kernel.log"].update({
                    "physical_base": "0x95200000",
                    "physical_end_exclusive": "0x95600000",
                    "console": {"file_offset": 0, "bytes": 0x200000},
                    "pmsg": {"file_offset": 0x200000, "bytes": 0x200000},
                    "marker": {"file_offset": 0x200100, "pa": "0x95400100"},
                    "marker_scratch": {"file_offset": 0x201000, "pa": "0x95401000"},
                    "panic_mirror": {"file_offset": 0x230000, "pa": "0x95430000"},
                })
                save()
            if args.diagnostics:
                for name in DIAGNOSTIC_REGIONS:
                    capture(name, 30)
        manifest["status"] = "success"
        save()
    except (RuntimeError, OSError) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        save()
        print(str(error), file=sys.stderr)
        print(f"failure records preserved in {out_dir}", file=sys.stderr)
        return 2

    if args.list_only:
        print(f"region list preserved in {out_dir / 'regions.txt'}")
    else:
        for name, info in manifest["files"].items():
            print(f"captured {name}: {info['bytes']} bytes sha256={info['sha256']}")
        if not args.probe_only:
            print("decode: python3 tools/read-ramdump.py "
                  f"{out_dir / 'kernel.log'} --dump-base 0x95200000 --logs --tail 32768")
    print("No device writes or reboots performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
