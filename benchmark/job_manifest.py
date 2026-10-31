#!/usr/bin/env python3
"""Create, finalise and enforce one public-safe model execution manifest."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


LABEL = "EXPERIMENTAL AI OUTPUT — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION"


def write(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--model-id", required=True)
    init.add_argument("--model-revision", required=True)
    init.add_argument("--model-sha256", required=True)
    init.add_argument("--runtime-revision", required=True)
    init.add_argument("--output", required=True, type=pathlib.Path)

    finalise = sub.add_parser("finalise")
    finalise.add_argument("--output", required=True, type=pathlib.Path)
    for phase in ("validation", "build", "download", "inference"):
        finalise.add_argument(f"--{phase}", required=True)

    enforce = sub.add_parser("enforce")
    enforce.add_argument("--output", required=True, type=pathlib.Path)

    args = parser.parse_args()
    if args.command == "init":
        write(args.output, {
            "schema_version": "stories-of-us-public-model-execution-v02",
            "public_label": LABEL,
            "status": "NOT_EXECUTED",
            "model_id": args.model_id,
            "model_revision": args.model_revision,
            "model_sha256": args.model_sha256,
            "runtime_revision": args.runtime_revision,
            "workflow_phases": {},
            "results": [],
        })
        return 0

    if not args.output.is_file():
        print(f"Missing execution manifest: {args.output}", file=sys.stderr)
        return 1
    data = json.loads(args.output.read_text(encoding="utf-8"))
    if args.command == "finalise":
        phases = {phase: getattr(args, phase) for phase in ("validation", "build", "download", "inference")}
        data["workflow_phases"] = phases
        if data.get("status") == "NOT_EXECUTED":
            data["status"] = "FAILURE"
            data["failure_reason"] = next(
                (f"{phase.upper()}_{outcome.upper()}" for phase, outcome in phases.items() if outcome != "success"),
                "INFERENCE_RESULT_MISSING",
            )
        write(args.output, data)
        return 0

    return 0 if data.get("status") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
