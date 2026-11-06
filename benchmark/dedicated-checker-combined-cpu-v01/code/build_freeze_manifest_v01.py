#!/usr/bin/env python3
"""Build the preparation package freeze. Run only before owner approval."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "fixtures/freeze_manifest_v01.json"
EXCLUDED = {
    "fixtures/freeze_manifest_v01.json",
    "fixtures/execution_authority_APPROVED_v01.json",
    "reports/07_governance_handover.md",
}
EXCLUDED_PREFIXES = ("outputs/", "recovery_and_integrity/integrity_after_freeze")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    frozen: dict[str, str] = {}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in EXCLUDED or any(relative.startswith(value) for value in EXCLUDED_PREFIXES):
            continue
        frozen[relative] = sha(path)
    OUTPUT.write_text(json.dumps({
        "schema_version": "stories-of-us-combined-cpu-checker-freeze-v01",
        "package": ROOT.name,
        "execution_status": "LOCKED_NOT_AUTHORISED",
        "frozen_files": frozen,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(sha(OUTPUT))


if __name__ == "__main__":
    main()
