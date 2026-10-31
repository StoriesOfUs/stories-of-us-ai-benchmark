#!/usr/bin/env python3
"""Validate the public-safe benchmark package without model inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re


PUBLIC_LABEL = "EXPERIMENTAL AI VERIFICATION — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION"


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--holdout", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    paths = {name: pathlib.Path(value).resolve() for name, value in vars(args).items() if name != "output"}
    baseline = json.loads(paths["baseline"].read_text(encoding="utf-8"))
    holdout = json.loads(paths["holdout"].read_text(encoding="utf-8"))
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    workflow = paths["workflow"].read_text(encoding="utf-8")

    assert len(holdout["articles"]) == 6
    assert len(holdout["claims"]) == 18
    assert {name: holdout["reference_counts"][name] for name in ["entailment", "neutral", "contradiction"]} == {
        "entailment": 6, "neutral": 6, "contradiction": 6
    }
    assert len({row["category"] for row in holdout["articles"]}) >= 5
    assert config["preserved_model_settings"]["entailment_threshold"] == 0.5
    assert config["preserved_model_settings"]["entailment_margin"] == 0.3
    assert config["preserved_model_settings"]["threshold_recalibration"] is False
    assert config["preserved_model_settings"]["model_input_limit"] == 512
    assert manifest["model_id"] == "cross-encoder/nli-deberta-v3-small"
    assert manifest["revision"] == "fa2804872c3b4bd748f38c0185cc85775361e735"
    assert manifest["model_card_label_order"] == ["contradiction", "entailment", "neutral"]
    assert re.search(r"(?m)^on:\s*\n\s+workflow_dispatch:\s*$", workflow)
    assert not re.search(r"(?m)^\s+(push|pull_request|schedule|repository_dispatch|deployment):", workflow)
    assert re.search(r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$", workflow)
    lowered = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths.values()).lower()
    for forbidden in ["netlify", "stories-of-us-site", "528 curated", "github_token", "secrets."]:
        assert forbidden not in lowered, forbidden
    baseline_ids = {row["claim_id"] for row in baseline["claims"]}
    required = set(config["historical_diagnostic_claim_ids"] + config["control_claim_ids"])
    assert required <= baseline_ids
    output = {
        "schema_version": "stories-of-us-self-contained-evidence-validation-v01",
        "status": "PASS",
        "public_label": PUBLIC_LABEL,
        "holdout_articles": 6,
        "holdout_claims": 18,
        "holdout_reference_counts": holdout["reference_counts"],
        "category_count": len({row["category"] for row in holdout["articles"]}),
        "workflow_manual_only": True,
        "workflow_contents_read": True,
        "fixed_thresholds_verified": True,
        "input_hashes": {name: digest(path) for name, path in paths.items()},
    }
    target = pathlib.Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "holdout_claims": 18}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
