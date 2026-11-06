#!/usr/bin/env python3
"""Build the deterministic model-facing input inventory without model code."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import dedicated_checker_contract_v01 as contract  # noqa: E402


development = contract.load_json(ROOT / "fixtures/development_cases_model_facing_frozen_v01.json")
evaluation = contract.load_json(ROOT / "fixtures/evaluation_cases_model_facing_frozen_v01.json")
cases = contract.cases_by_id([development, evaluation])
records = []
for case_id, case in cases.items():
    stage = "development" if case_id.startswith("dev") else "reserved_evaluation"
    for claim in case["atomic_claims"]:
        common = {
            "stage": stage,
            "case_id": case_id,
            "claim_id": claim["claim_id"],
            "evidence_ids": [row["evidence_id"] for row in case["verified_evidence"]],
            "claim": claim["claim"],
        }
        for candidate, text in (
            ("hhem_2_1_open", contract.hhem_input(case, claim)),
            ("minicheck_flan_t5_large", contract.minicheck_input(case, claim)),
        ):
            if contract.input_has_answer_leakage(text):
                raise SystemExit(f"answer leakage in {case_id}:{claim['claim_id']}:{candidate}")
            records.append({
                **common,
                "candidate": candidate,
                "formatted_input": text,
                "formatted_input_sha256": contract.sha256_text(text),
                "utf8_bytes": len(text.encode("utf-8")),
                "conservative_token_upper_bound_not_exact_count": contract.conservative_token_upper_bound(text),
            })

result = {
    "schema_version": "stories-of-us-dedicated-checker-model-input-inventory-v01",
    "status": "FROZEN_MODEL_FACING_NO_ANSWER_KEYS",
    "records": records,
    "record_count": len(records),
    "logical_claim_count": len(records) // 2,
    "important": "The complete strings are frozen. Byte-derived bounds are not exact tokenizer counts; exact pinned-tokenizer counts remain mandatory before inference.",
}
output = ROOT / "fixtures/model_inputs_frozen_v01.json"
output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(output)
