#!/usr/bin/env python3
"""Build deterministic public and complete V04 package manifests.

This is a mechanical offline freeze utility. It excludes the manifest itself,
post-freeze receipts, any future authority JSON, live state and Python caches.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "recovery/freeze_manifest_v01.json"
PUBLIC = ROOT / "recovery/public_manifest_v01.json"
RECEIPT = ROOT / "recovery/freeze_manifest_sha256_v01.txt"
HANDOVER_RECEIPT = ROOT / "reports/06_freeze_receipt.md"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        text = relative.as_posix()
        if "__pycache__" in relative.parts or text.endswith(".pyc"):
            continue
        if path in {MANIFEST, RECEIPT, HANDOVER_RECEIPT}:
            continue
        if text.startswith("state/live/"):
            continue
        if text.startswith("authority/") and text != "authority/README.md":
            continue
        yield path, text


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


public_files = {}
for path, relative in relative_files():
    if relative == "README.md" or relative.startswith("code/") or relative.startswith("immutable/"):
        if relative != "immutable/revision_allocation_v01.json":
            public_files[relative] = sha(path)
write(PUBLIC, {
    "schema_version": "stories-of-us-public-upload-manifest-v04",
    "status": "PROPOSED_ONLY_NOT_UPLOADED",
    "files": public_files,
    "excluded": ["private/", "authority/", "state/", "reports containing protected case annotations"],
})

files = {relative: sha(path) for path, relative in relative_files()}
write(MANIFEST, {
    "schema_version": "stories-of-us-automatic-checker-claim-identification-freeze-v04",
    "status": "PREPARATION_PASS_EXECUTION_LOCKED_RELIABILITY_NOT_TESTED",
    "created_date": "2026-11-10",
    "file_count": len(files),
    "files": files,
    "excluded_mutable_or_post_freeze_paths": [
        "recovery/freeze_manifest_v01.json",
        "recovery/freeze_manifest_sha256_v01.txt",
        "reports/06_freeze_receipt.md",
        "authority/execution_authority_APPROVED_v01.json",
        "state/live/",
        "__pycache__/",
    ],
    "execution_authority_present": False,
    "live_state_present": False,
})

freeze_hash = sha(MANIFEST)
RECEIPT.write_text(freeze_hash + "\n", encoding="utf-8")
HANDOVER_RECEIPT.write_text(
    "# 06 — Freeze receipt\n\n"
    f"Freeze-manifest SHA-256: `{freeze_hash}`\n\n"
    f"Frozen file count: {len(files)}. The receipt and manifest are excluded from the manifest to avoid a self-referential hash. "
    "No live authority or state is present.\n",
    encoding="utf-8",
)
print(freeze_hash)
