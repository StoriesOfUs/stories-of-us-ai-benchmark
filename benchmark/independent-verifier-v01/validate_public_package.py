#!/usr/bin/env python3
"""Validate the public boundary and frozen design of the verifier benchmark."""
from __future__ import annotations

import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmark/independent-verifier-v01"
WORKFLOW = ROOT / ".github/workflows/manual-independent-verifier-v01.yml"
CASES = BENCH / "evaluation_cases_v01.json"
MANIFEST = BENCH / "model_manifest_v01.json"
RUNNER = BENCH / "run_independent_verifier.py"
OUTPUT = BENCH / "validation_results_v01.json"


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    claims = cases["claims"]
    groups = {name: [row for row in claims if row["group"] == name] for name in {
        "known_historical_failures", "known_supported_controls", "frozen_unseen_holdout"
    }}
    holdout = groups["frozen_unseen_holdout"]
    historical_ids = {
        row["historical_case_id"] for row in groups["known_historical_failures"]
    }
    evidence_ids = {
        article["article_id"]: {row["evidence_id"] for row in article["evidence"]}
        for article in cases["articles"]
    }
    reference_counts = {
        label: sum(row["reference_nli_label"] == label for row in holdout)
        for label in ["entailment", "neutral", "contradiction"]
    }
    public_files = [
        *BENCH.glob("*.json"), *BENCH.glob("*.py"), *BENCH.glob("*.md"),
        BENCH / "requirements-v01.txt", WORKFLOW,
    ]
    checks = {
        "freeze_recorded": bool(cases.get("frozen_at_utc")),
        "manual_atomic_claims_disclosed": cases["freeze_rules"].get("manual_atomic_claim_inventory") is True,
        "automatic_extraction_not_overclaimed": cases["freeze_rules"].get("automatic_claim_extraction_status") == "NOT_IMPLEMENTED",
        "three_groups_only": set(groups) == {"known_historical_failures", "known_supported_controls", "frozen_unseen_holdout"},
        "five_known_failure_cases": historical_ids == {"hist_dpo", "hist_bca", "hist_connect", "hist_puck", "hist_vanda"},
        "known_failures_have_atomic_claims": len(groups["known_historical_failures"]) >= 5,
        "multiple_supported_controls": len(groups["known_supported_controls"]) >= 5,
        "holdout_at_least_twelve": len(holdout) >= 12,
        "holdout_balanced": min(reference_counts.values()) >= 4,
        "holdout_three_categories": len({
            next(article["category"] for article in cases["articles"] if article["article_id"] == row["article_id"])
            for row in holdout
        }) >= 3,
        "holdout_not_calibration": cases["freeze_rules"].get("holdout_not_used_for_calibration") is True,
        "claim_ids_unique": len({row["claim_id"] for row in claims}) == len(claims),
        "article_ids_valid": all(row["article_id"] in evidence_ids for row in claims),
        "evidence_references_valid": all(set(row["evidence_ids"]).issubset(evidence_ids[row["article_id"]]) for row in claims),
        "reference_labels_valid": all(row["reference_nli_label"] in {"entailment", "neutral", "contradiction"} for row in claims),
        "reference_reasons_present": all(str(row.get("reference_reason", "")).strip() for row in claims),
        "direct_source_urls": all(article["url"].startswith("https://") and "news.google.com" not in article["url"] for article in cases["articles"]),
        "evidence_bounded": all(len(item["text"]) <= 500 for article in cases["articles"] for item in article["evidence"]),
        "official_model": manifest["model_id"] == "cross-encoder/nli-deberta-v3-small",
        "pinned_revision": manifest["revision"] == "fa2804872c3b4bd748f38c0185cc85775361e735",
        "apache_license": manifest["license"] == "apache-2.0",
        "label_mapping_verified": manifest["model_card_label_order"] == ["contradiction", "entailment", "neutral"],
        "input_limit_verified": manifest["max_position_embeddings"] == 512,
        "safetensors_selected": manifest["selected_format"] == "safetensors" and manifest["remote_code_allowed"] is False,
        "manual_workflow_only": re.search(r"(?m)^on:\s*\n\s{2}workflow_dispatch:\s*$", workflow) is not None,
        "no_other_workflow_triggers": all(re.search(rf"(?m)^\s{{2}}{trigger}:\s*$", workflow) is None for trigger in ["push", "pull_request", "schedule", "repository_dispatch"]),
        "read_only_permissions": re.search(r"(?m)^permissions:\s*\n\s{2}contents:\s*read\s*$", workflow) is not None,
        "bounded_job": "timeout-minutes: 45" in workflow,
        "short_artifact_retention": "retention-days: 7" in workflow,
        "no_secrets": "secrets." not in workflow and "${{ secrets" not in workflow,
        "no_deployment": all(token not in workflow.lower() for token in ["netlify", "deploy", "pages"]),
        "no_repository_write": "persist-credentials: false" in workflow and "contents: write" not in workflow,
        "weights_not_artifacted": "model.safetensors" not in workflow.split("Upload", 1)[-1],
        "temporary_weight_removal": "Remove temporary model files" in workflow,
        "premise_hypothesis_order": "premise=evidence; hypothesis=claim" in runner,
        "neutral_not_supported": 'return "NOT_ESTABLISHED"' in runner,
        "rejects_truncation": "EVIDENCE_PAIR_EXCEEDS_MODEL_LIMIT" in runner and "truncation=False" in runner,
        "no_remote_code": "trust_remote_code=False" in runner,
        "development_only_calibration": "DEVELOPMENT_GROUPS" in runner and "holdout_used_for_calibration\": False" in runner,
        "three_repeatability_passes": "requires exactly three repeatability passes" in runner,
        "operational_not_authorised": "NOT_AUTHORISED" in runner,
    }
    credential_patterns = ["github_pat_", "gho_", "AKIA", "BEGIN PRIVATE KEY", "Bearer "]
    for path in public_files:
        if not path.is_file():
            checks[f"file_exists:{path.name}"] = False
            continue
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(ROOT))
        checks[f"no_local_path:{relative}"] = "/Applications/MAMP/" not in text and "/Users/" not in text
        checks[f"no_credentials:{relative}"] = all(pattern not in text for pattern in credential_patterns)
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "failed": failed,
        "holdout_reference_counts": reference_counts,
        "claim_counts": {name: len(rows) for name, rows in groups.items()},
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
