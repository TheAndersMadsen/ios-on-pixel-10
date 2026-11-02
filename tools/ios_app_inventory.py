#!/usr/bin/env python3
"""Compare mounted stock iOS apps with a constructed root; never change either.

The JSON report is a filesystem inventory, not a LaunchServices or launch test.
An optional plist lists the staged stock apps plus Settings and Phone for the
on-device registrar. Missing bundles remain in that list so they cannot silently
disappear from an acceptance result. Keep reports and Apple artifacts local.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat


def bundle_info(bundle):
    data = (bundle / "Info.plist").read_bytes()
    info = plistlib.loads(data)
    if not isinstance(info, dict):
        raise ValueError("Info.plist is not a dictionary")
    identifier = info.get("CFBundleIdentifier")
    executable = info.get("CFBundleExecutable")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("missing bundle identifier")
    if (not isinstance(executable, str) or not executable
            or Path(executable).name != executable or executable in (".", "..")):
        raise ValueError("invalid bundle executable")
    tags = info.get("SBAppTags", [])
    return {
        "bundle_id": identifier, "executable": executable,
        "info_sha256": hashlib.sha256(data).hexdigest(),
        "hidden_tag": isinstance(tags, list) and "hidden" in tags,
        "package_type": info.get("CFBundlePackageType"),
        "launch_prohibited": bool(info.get("SBAppLaunchProhibited", False)),
    }


def regular_files(bundle):
    """Do not follow bundle symlinks or count their targets as duplicate data."""
    files = {}
    if bundle.is_symlink():
        raise ValueError("bundle directory is a symlink")
    for directory, dirs, names in os.walk(bundle):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            record = path.lstat()
            if stat.S_ISREG(record.st_mode):
                files[path.relative_to(bundle).as_posix()] = record.st_size
    return files


def inventory(source, root):
    source, root = source.resolve(strict=True), root.resolve(strict=True)
    if not (source / "Applications").is_dir() or not (root / "Applications").is_dir():
        raise ValueError("both roots must contain Applications directories")
    if source == root:
        raise ValueError("source and constructed root must differ")
    rows = []
    for origin, subdir in (("system", "Applications"),
                           ("staged", "private/var/staged_system_apps")):
        directory = source / subdir
        if not directory.is_dir():
            raise ValueError(f"stock app directory is absent: {subdir}")
        for bundle in sorted(directory.glob("*.app")):
            row = {"name": bundle.name, "origin": origin,
                   "source_path": "/" + bundle.relative_to(source).as_posix(),
                   "target_path": "/Applications/" + bundle.name,
                   "runtime_registration": "untested", "runtime_launch": "untested"}
            try:
                row.update(bundle_info(bundle))
                stock = regular_files(bundle)
                target = root / row["target_path"].lstrip("/")
                present = target.is_dir() and not target.is_symlink()
                row["bundle_present"] = present
                actual = regular_files(target) if present else {}
                row["stock_bytes"] = sum(stock.values())
                row["stock_files"] = len(stock)
                row["absent_regular_files"] = len(stock.keys() - actual.keys())
                row["absent_regular_bytes"] = sum(stock[k] for k in stock.keys() - actual.keys())
                exe = target / row["executable"]
                row["executable_present"] = exe.is_file() and exe.resolve().is_relative_to(root)
                row["target_bundle_id"] = None
                if present:
                    row["target_bundle_id"] = bundle_info(target)["bundle_id"]
                    if row["target_bundle_id"] != row["bundle_id"]:
                        raise ValueError("constructed app has a different bundle identifier")
            except (OSError, ValueError, plistlib.InvalidFileException, TypeError) as error:
                row["error"] = str(error)
            rows.append(row)
    staged = [r for r in rows if r["origin"] == "staged" and "error" not in r]
    fs = os.statvfs(root)
    free = fs.f_bavail * fs.f_frsize
    missing_bytes = sum(r["absent_regular_bytes"] for r in staged)
    return {
        "schema": "hackios-app-inventory-v1", "source_root": str(source),
        "constructed_root": str(root), "apps": rows,
        "summary": {
            "system_bundles": sum(r["origin"] == "system" for r in rows),
            "staged_bundles": len(staged),
            "staged_bundles_absent": sum(not r["bundle_present"] for r in staged),
            "staged_regular_bytes_absent": missing_bytes, "root_available_bytes": free,
            "staged_content_exceeds_free_space": missing_bytes > free,
            "inventory_errors": sum("error" in r for r in rows),
        },
        "limits": ["App presence does not establish registration, visibility or launch.",
                   "File counts do not verify resource contents, signatures or PAC rewriting.",
                   "Capacity excludes HFS metadata, block rounding and framework dependencies.",
                   "Hidden tags are metadata, not a complete SpringBoard visibility policy."],
    }


def registration_manifest(report, only=()):
    requested = set(only)
    apps = [r for r in report["apps"] if "error" not in r and (
        r["bundle_id"] in requested if requested else
        r["origin"] == "staged" or r["bundle_id"] in ("com.apple.Preferences", "com.apple.mobilephone"))]
    found = {r["bundle_id"] for r in apps}
    if requested - found:
        raise ValueError("requested app identifier is absent from stock inventory")
    if len(found) != len(apps):
        raise ValueError("duplicate app identifiers in stock inventory")
    if not apps:
        raise ValueError("no applications selected")
    return {"schema": "hackios-stock-apps-v1", "apps": [
        {"bundle_id": r["bundle_id"], "path": r["target_path"]} for r in apps]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--only", action="append", default=[], metavar="BUNDLE_ID")
    args = p.parse_args()
    report = inventory(args.source, args.root)
    manifest = registration_manifest(report, args.only) if args.manifest else None
    # Exclusive output creation also prevents accidentally overwriting a source.
    with args.out.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if manifest:
        with args.manifest.open("xb") as stream:
            plistlib.dump(manifest, stream, fmt=plistlib.FMT_BINARY)
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
