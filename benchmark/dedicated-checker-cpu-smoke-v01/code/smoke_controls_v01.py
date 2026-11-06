#!/usr/bin/env python3
"""Standard-library controls for the CPU dependency smoke test."""
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
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def freeze_hash(manifest_path: Path = MANIFEST) -> str:
    if not manifest_path.is_file():
        raise SafetyStop("freeze manifest absent")
    return sha256_file(manifest_path)


def verify_freeze(root: Path = ROOT, manifest_path: Path = MANIFEST) -> int:
    manifest = load_json(manifest_path)
    checked = 0
    for relative, expected in manifest["frozen_files"].items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise SafetyStop(f"frozen file mismatch: {relative}")
        checked += 1
    return checked


def parse_wheel_lock(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(
        r"^(?P<name>[A-Za-z0-9_.-]+)\s+@\s+"
        r"(?P<url>https://\S+\.whl)#sha256=(?P<sha256>[0-9a-f]{64})$"
    )
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.fullmatch(line)
        if not match:
            raise SafetyStop(f"invalid wheel-lock line: {line}")
        row = match.groupdict()
        row["name"] = canonical_name(row["name"])
        rows.append(row)
    names = [row["name"] for row in rows]
    if len(names) != len(set(names)):
        raise SafetyStop("duplicate distribution in wheel lock")
    return rows


def _authority_valid(authority: dict[str, Any], expected_freeze: str) -> tuple[bool, str]:
    required = (
        "execution_authorised",
        "owner_approved_cpu_wheel_installation",
        "owner_approved_single_public_runner_dispatch",
        "owner_approved_zero_model_downloads_and_inference",
        "owner_approved_zero_retries",
        "owner_approved_zero_cost",
        "owner_approved_documentation_closeout",
    )
    if not all(authority.get(key) is True for key in required):
        return False, "authority flags incomplete"
    if authority.get("approved_freeze_manifest_sha256") != expected_freeze:
        return False, "approved freeze hash mismatch"
    return True, "authority valid"


def preinstallation_authority_state(authority_path: Path, lock_path: Path, expected_freeze: str) -> dict[str, str]:
    if lock_path.exists():
        return {"state": "REPEAT_REFUSED", "reason": "one-use lock already exists"}
    if not authority_path.is_file():
        return {"state": "LOCKED_NOT_AUTHORISED", "reason": "authority file absent"}
    try:
        authority = load_json(authority_path)
    except (OSError, json.JSONDecodeError):
        return {"state": "BLOCKED_INVALID_AUTHORITY", "reason": "authority file malformed"}
    valid, reason = _authority_valid(authority, expected_freeze)
    return {"state": "APPROVED" if valid else "BLOCKED_INVALID_AUTHORITY", "reason": reason}


def postlock_authority_state(authority_path: Path, lock_path: Path, expected_freeze: str) -> dict[str, str]:
    if not authority_path.is_file() or not lock_path.is_file():
        return {"state": "BLOCKED", "reason": "authority or consumed lock absent"}
    try:
        authority = load_json(authority_path)
        lock = load_json(lock_path)
    except (OSError, json.JSONDecodeError):
        return {"state": "BLOCKED", "reason": "authority or lock malformed"}
    valid, reason = _authority_valid(authority, expected_freeze)
    if not valid:
        return {"state": "BLOCKED", "reason": reason}
    if lock.get("status") != "CONSUMED_RESERVED_BEFORE_INSTALLATION":
        return {"state": "BLOCKED", "reason": "lock state invalid"}
    if lock.get("freeze_manifest_sha256") != expected_freeze:
        return {"state": "BLOCKED", "reason": "lock freeze hash mismatch"}
    return {"state": "APPROVED_AFTER_LOCK", "reason": "authority and consumed lock valid"}


def account_paths(paths: Iterable[Path]) -> dict[str, int]:
    """Measure stored files without following or double-counting symlinks/hardlinks."""
    seen: set[tuple[int, int]] = set()
    regular_logical = 0
    allocated = 0
    entries = 0
    symlinks = 0
    symlink_target_logical = 0
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
        "symlink_target_logical_bytes_diagnostic_only": symlink_target_logical,
    }
