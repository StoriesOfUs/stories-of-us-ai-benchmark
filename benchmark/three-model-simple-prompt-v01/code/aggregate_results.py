#!/usr/bin/env python3
"""Aggregate model result files without turning blocked or failed slots into success."""
from __future__ import annotations

import argparse
import json
import pathlib


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-a", required=True)
    parser.add_argument("--model-b", required=True)
    parser.add_argument("--blocked-c", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    slots = []
    for path in [args.model_a, args.model_b]:
        source = pathlib.Path(path)
        if source.is_file():
            payload = json.loads(source.read_text(encoding="utf-8"))
            slots.extend(payload["results"])
        else:
            key = "A" if path == args.model_a else "B"
            for case_id in ["bbc_disabled_bay", "druk_dpo_funding"]:
                slots.append({"model_key": key, "case_id": case_id, "execution_status": "FAILURE", "failure_reason": "RESULT_FILE_MISSING", "text": ""})
    blocked = json.loads(pathlib.Path(args.blocked_c).read_text(encoding="utf-8"))
    slots.extend(blocked["results"])
    ordered = sorted(slots, key=lambda row: (row["case_id"], row["model_key"]))
    counts = {
        "intended_slots": 6,
        "successful_outputs": sum(row["execution_status"] == "SUCCESS" for row in ordered),
        "blocked_model_access": sum(row["execution_status"] == "BLOCKED_MODEL_ACCESS" for row in ordered),
        "technical_failures": sum(row["execution_status"] == "FAILURE" for row in ordered),
    }
    payload = {
        "schema_version": "stories-of-us-three-model-simple-prompt-combined-results-v01",
        "public_label": "EXPERIMENTAL AI OUTPUT — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION",
        "counts": counts,
        "technical_status": "PASS" if counts["successful_outputs"] == 6 else "PARTIAL",
        "results": ordered,
    }
    target = pathlib.Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
