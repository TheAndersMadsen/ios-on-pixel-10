#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Original hackios upstream inventory tool, 2026-11-02.
"""Pin selected GitHub source references without changing a build or device.

Uses the authenticated gh client. Source snapshots and receipts stay in ignored
research/. A refresh reports changed heads; it never applies an upstream change.
Run when reviewing an implementation milestone, not as a background watcher.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
SOURCES = (
    ("UniXNU/AdrenoMetal", "main", "metal", (
        "LICENSE", "README.md", "NativeBridgeMetalFrontend.h",
        "NativeBridgeMetalFrontend.mm", "bridge/NativeMetalBridge.h")),
    ("steelbrain/metal2vulkan", "master", "air", (
        "LICENSE", "Cargo.toml", "README.md",
        "crates/metal2vulkan-air/Cargo.toml", "crates/metal2vulkan-air/src/lib.rs")),
    ("dgigantino/ios-tegu", "ios26-bringup", "metal,surfaces,vm", (
        "README.md", "LICENSE")),
    ("UniXNU/Adreno740", "main", "uc,queue,vm", ("LICENSE", "README.md")),
    ("NWylynko/ios-flame", "main", "metal,validation", (
        "LICENSE", "README.md", "CREDITS.md", "METAL-NEXT.md")),
    ("dipa-studio/ios-sweet", "main", "surfaces,uc", ("LICENSE", "README.md")),
    ("torvalds/linux", "master", "firmware,queue,vm", (
        "COPYING", "drivers/gpu/drm/imagination/pvr_ccb.c",
        "drivers/gpu/drm/imagination/pvr_rogue_fwif.h",
        "drivers/gpu/drm/imagination/pvr_power.c")),
    ("GrapheneOS/kernel_manifest-6.18", "17", "firmware,vm", (
        "default.xml", "README.md")),
)


def api(endpoint):
    p = subprocess.run(["gh", "api", "--hostname", "github.com", endpoint],
                       text=True, capture_output=True, timeout=45)
    if p.returncode:
        # Do not print authentication/environment details or response bodies.
        raise RuntimeError("GitHub API failed: " + endpoint)
    return json.loads(p.stdout)


def write_json(path, value):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def related_audit():
    """Bind the existing cross-domain audit instead of collecting it again."""
    paths = [REPO / "docs/REUSE.md"]
    paths += [REPO / "docs/reuse/2026-11-02" / (name + ".md") for name in (
        "powervr-kernel", "powervr-compiler", "dma-memory", "metal-runtime",
        "local-backlog", "tegu")]
    return {"scope": "Snapshot evidence; newer actual source/runtime receipts take precedence",
            "files": [{"path": str(p.relative_to(REPO)),
                       "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in paths if p.is_file()]}


def snapshot(root, name, branch, owners, files, previous):
    meta = api("repos/" + name)
    commit = api("repos/" + name + "/commits/" + branch)
    sha = commit["sha"]
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("invalid commit identity")
    directory = root / "snapshots" / name.replace("/", "__") / sha
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "repo": name, "branch": branch, "commit": sha,
        "commit_date": commit["commit"]["committer"]["date"],
        "subject": commit["commit"]["message"].splitlines()[0],
        "url": commit["html_url"], "owners": owners.split(","),
        "visibility": meta.get("visibility"), "private": meta.get("private"),
        "archived": meta.get("archived"),
        "github_license_hint": (meta.get("license") or {}).get("spdx_id"),
        "license_status": "Per-file and dependency review required before copying",
        "previous_commit": previous.get(name),
        "head_changed": previous.get(name) not in (None, sha), "files": [],
    }
    for relative in files:
        entry = {"path": relative,
                 "url": f"https://github.com/{name}/blob/{sha}/{relative}"}
        endpoint = f"repos/{name}/contents/{relative}?ref={sha}"
        try:
            blob = api(endpoint)
        except RuntimeError:
            # LICENSE absence is meaningful. Never infer a permissive license.
            entry["status"] = "unavailable; not an adoption authorization"
            record["files"].append(entry)
            continue
        if blob.get("type") != "file" or blob.get("encoding") != "base64":
            raise ValueError("source endpoint is not a bounded base64 file")
        if blob.get("size", 0) > 4 * 1024 * 1024:
            raise ValueError("source file exceeds the snapshot bound")
        data = base64.b64decode(blob["content"], validate=False)
        if len(data) != blob["size"] or b"\0" in data:
            raise ValueError("source snapshot size mismatch or binary data")
        data.decode("utf-8")  # Only source text, never firmware/prebuilt artifacts.
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != data:
            raise ValueError("immutable snapshot changed")
        target.write_bytes(data)
        entry.update(status="saved", sha256=hashlib.sha256(data).hexdigest(),
                     git_blob=blob["sha"], bytes=len(data),
                     local_path=str(target.relative_to(REPO)))
        record["files"].append(entry)
    write_json(directory / "receipt.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=REPO / "research/ios26-metal-native-20261102/upstream")
    args = parser.parse_args()
    root = args.output.resolve()
    if not root.is_relative_to(REPO / "research"):
        parser.error("snapshots must remain inside this repository's ignored research/")
    root.mkdir(parents=True, exist_ok=True)
    current = root / "current.json"
    previous = {}
    if current.exists():
        previous = {r["repo"]: r["commit"] for r in json.loads(current.read_text())["sources"]}
    records, errors = [], []
    for name, branch, owners, files in SOURCES:
        try:
            record = snapshot(root, name, branch, owners, files, previous)
            records.append(record)
            print(name, record["commit"], "changed" if record["head_changed"] else "pinned",
                  "source_files", sum(f["status"] == "saved" for f in record["files"]),
                  flush=True)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
            errors.append({"repo": name, "error": str(e)})
            print("FAILED", name, str(e), file=sys.stderr, flush=True)
    report = {"schema": "hackios.native-gpu-upstream.v1",
              "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Source references only; no merge, build update or device action",
              "sources": records, "errors": errors, "related_audit": related_audit()}
    # Preserve a usable earlier index if any source failed in this refresh.
    destination = root / "last-attempt.json" if errors else current
    write_json(destination, report)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
