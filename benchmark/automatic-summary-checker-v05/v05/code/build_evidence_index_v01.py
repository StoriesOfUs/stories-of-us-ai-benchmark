#!/usr/bin/env python3
"""Build stable paragraph indexes for the frozen private evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from checker_core_v01 import load_json, paragraphize, validate_case


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    case_document = load_json(args.cases)
    index: dict[str, object] = {
        "schema_version": "stories-of-us-private-evidence-index-v01",
        "cases": {},
    }
    for case in case_document["cases"]:
        evidence_path = package_root / "private" / "evidence" / case["evidence_file"]
        evidence = paragraphize(evidence_path.read_text(encoding="utf-8"))
        validate_case(case, evidence)
        index["cases"][case["case_id"]] = {
            "source_file": case["evidence_file"],
            "paragraphs": evidence,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

