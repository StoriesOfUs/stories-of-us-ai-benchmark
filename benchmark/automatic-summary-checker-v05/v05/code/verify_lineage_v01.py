#!/usr/bin/env python3
"""Verify V04's narrow scoring-only lineage from frozen V03."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


V04 = Path(__file__).resolve().parents[1]
V03 = V04.parent / "option_c_automatic_summary_checker_test_package_v03"
EXPECTED_V03_FREEZE = "5fb87aa319c6c948e5dc3174fff0578c622ef6312319ba4226c7dc3bf00c0189"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_files(root: Path, prefix: str) -> list[str]:
    base = root / prefix
    return sorted(path.relative_to(root).as_posix() for path in base.rglob("*") if path.is_file())


def main() -> None:
    result = {
        "schema_version": "stories-of-us-automatic-checker-v04-lineage-verification-v01",
        "status": "PASS",
        "source_v03_freeze": EXPECTED_V03_FREEZE,
        "checks": {},
        "scientific_file_comparison": {},
        "differences": [
            "Protected post-response adjudication now uses MAPPED, INVENTED, INVENTORY_GAP and UNCERTAIN_MAPPING portion dispositions.",
            "Inventory gaps and uncertain mappings remain explicit and block the affected gate.",
            "Execution-gate methods require complete resolved protected scoring before progression.",
            "A frozen resolution procedure preserves original responses, scores, inventories and versioning boundaries.",
            "Model-facing instructions, cases, evidence, protected inventories, answer keys, model settings, request schedule and resource ceilings are unchanged.",
        ],
    }

    result["checks"]["source_v03_manifest"] = sha(V03 / "recovery/freeze_manifest_v01.json") == EXPECTED_V03_FREEZE

    unchanged_prefixes = [
        "immutable/instructions",
        "immutable/schemas",
        "private/cases",
        "private/claim_inventories",
        "private/evidence",
    ]
    unchanged_files = [
        "private/answer_keys/correction_feedback_requirements_v01.json",
        "private/answer_keys/development_answer_key_v01.json",
        "private/answer_keys/evaluation_answer_key_v01.json",
        "private/provenance/answer_key_establishment_v01.md",
        "private/provenance/claim_inventory_completeness_review_v01.json",
        "private/provenance/claim_inventory_review_v01.md",
        "private/provenance/development_case_substitution_v01.md",
        "private/provenance/evaluation_selection_record_v01.json",
        "private/provenance/owner_editorial_decisions_v01.md",
        "immutable/request_schedule_and_resources_v01.json",
        "immutable/revision_allocation_v01.json",
        "reports/exact_tokenizer_counts_v01.json",
        "code/checker_core_v01.py",
        "code/payloads_v01.py",
        "code/summary_addendum_contract_v01.py",
    ]
    for prefix in unchanged_prefixes:
        old = relative_files(V03, prefix)
        new = relative_files(V04, prefix)
        key = f"tree::{prefix}"
        same_paths = old == new
        same_hashes = same_paths and all(sha(V03 / rel) == sha(V04 / rel) for rel in old)
        result["checks"][key] = same_hashes
        result["scientific_file_comparison"][key] = {
            "file_count": len(old),
            "same_paths": same_paths,
            "same_hashes": same_hashes,
        }
    for relative in unchanged_files:
        match = sha(V03 / relative) == sha(V04 / relative)
        result["checks"][f"unchanged::{relative}"] = match

    old_config = load(V03 / "immutable/model_and_execution_config_v01.json")
    new_config = load(V04 / "immutable/model_and_execution_config_v01.json")
    model_identity = {
        "checker": old_config["checker"] == new_config["checker"],
        "writer_revision": old_config["writer_revision"] == new_config["writer_revision"],
        "request_limits": all(old_config[key] == new_config[key] for key in ("maximum_requests", "maximum_probes", "maximum_retries")),
    }
    result["model_and_request_identity"] = model_identity
    result["checks"].update({f"model::{key}": value for key, value in model_identity.items()})

    old_resources = load(V03 / "immutable/request_schedule_and_resources_v01.json")
    new_resources = load(V04 / "immutable/request_schedule_and_resources_v01.json")
    result["checks"]["resource_contract_byte_identical"] = old_resources == new_resources

    if not all(result["checks"].values()):
        result["status"] = "FAIL"
    destination = V04 / "recovery/lineage_verification_v01.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["status"])


if __name__ == "__main__":
    main()

