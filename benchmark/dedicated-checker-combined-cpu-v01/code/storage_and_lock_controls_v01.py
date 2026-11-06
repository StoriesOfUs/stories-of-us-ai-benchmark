#!/usr/bin/env python3
"""Standard-library freeze, authority and inode-aware storage controls."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
OUTPUTS = ROOT / "outputs"
MANIFEST = FIXTURES / "freeze_manifest_v01.json"
AUTHORITY = FIXTURES / "execution_authority_APPROVED_v01.json"
LOCK = OUTPUTS / "execution_consumed_lock_v01.json"


class SafetyStop(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def freeze_hash() -> str:
    if not MANIFEST.is_file():
        raise SafetyStop("freeze manifest absent")
    return sha256_file(MANIFEST)


def verify_freeze() -> int:
    manifest = load_json(MANIFEST)
    checked = 0
    for relative, expected in manifest["frozen_files"].items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise SafetyStop(f"frozen file mismatch: {relative}")
        checked += 1
    return checked


def parse_wheel_lock(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)\s+@\s+(?P<url>https://\S+\.whl)#sha256=(?P<sha256>[0-9a-f]{64})$")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.fullmatch(line)
        if not match:
            raise SafetyStop(f"invalid wheel-lock line: {line}")
        rows.append(match.groupdict())
    names = [re.sub(r"[-_.]+", "-", row["name"]).lower() for row in rows]
    if len(names) != len(set(names)):
        raise SafetyStop("duplicate distribution in wheel lock")
    return rows


def authority_state(authority_path: Path, lock_path: Path, expected_freeze: str) -> dict[str, str]:
    if lock_path.exists():
        return {"state": "REPEAT_REFUSED", "reason": "one-use lock already exists"}
    if not authority_path.is_file():
        return {"state": "LOCKED_NOT_AUTHORISED", "reason": "authority file absent"}
    try:
        authority = load_json(authority_path)
    except (OSError, json.JSONDecodeError):
        return {"state": "BLOCKED_INVALID_AUTHORITY", "reason": "authority file malformed"}
    required = (
        "execution_authorised",
        "owner_approved_public_repository_upload_and_single_dispatch",
        "owner_approved_pinned_cpu_dependency_installation",
        "owner_approved_pinned_model_tokenizer_download_and_cpu_loading",
        "owner_approved_bounded_checker_inference",
        "owner_confirmed_standard_public_runner_eligible_and_zero_cost",
    )
    if not all(authority.get(key) is True for key in required):
        return {"state": "BLOCKED_INVALID_AUTHORITY", "reason": "authority flags incomplete"}
    if authority.get("approved_freeze_manifest_sha256") != expected_freeze:
        return {"state": "BLOCKED_INVALID_AUTHORITY", "reason": "approved freeze hash mismatch"}
    if authority.get("maximum_workflow_runs") != 1 or authority.get("maximum_run_attempt") != 1:
        return {"state": "BLOCKED_INVALID_AUTHORITY", "reason": "one-use limits changed"}
    if authority.get("maximum_retries") != 0 or authority.get("maximum_expenditure_gbp") != 0:
        return {"state": "BLOCKED_INVALID_AUTHORITY", "reason": "retry or cost limit changed"}
    return {"state": "APPROVED", "reason": "authority valid"}


def account_paths(paths: Iterable[Path]) -> dict[str, int]:
    """Measure stored bytes without following or double-counting links/inodes."""
    seen: set[tuple[int, int]] = set()
    regular_logical = allocated = entries = symlinks = hardlink_repeats = symlink_target_logical = 0
    for root in paths:
        if not root.exists() and not root.is_symlink():
            continue
        candidates = [root]
        if root.is_dir() and not root.is_symlink():
            candidates.extend(root.rglob("*"))
        for path in candidates:
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            entries += 1
            if stat.S_ISLNK(info.st_mode):
                symlinks += 1
                allocated += int(getattr(info, "st_blocks", 0)) * 512
                try:
                    target = path.stat()
                    if stat.S_ISREG(target.st_mode):
                        symlink_target_logical += int(target.st_size)
                except FileNotFoundError:
                    pass
                continue
            inode = (int(info.st_dev), int(info.st_ino))
            if inode in seen:
                hardlink_repeats += 1
                continue
            seen.add(inode)
            allocated += int(getattr(info, "st_blocks", 0)) * 512
            if stat.S_ISREG(info.st_mode):
                regular_logical += int(info.st_size)
    return {
        "entries_seen": entries,
        "unique_inodes": len(seen),
        "regular_file_logical_bytes_unique": regular_logical,
        "allocated_bytes_unique": allocated,
        "symlink_count": symlinks,
        "hardlink_repeats_not_double_counted": hardlink_repeats,
        "symlink_target_logical_bytes_diagnostic_only": symlink_target_logical,
    }
