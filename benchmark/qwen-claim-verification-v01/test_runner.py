#!/usr/bin/env python3
"""Model-free regression tests for authoring, checking, rewriting and failure evidence."""
from __future__ import annotations

import hashlib
import json
import pathlib
import stat
import subprocess
import sys
import tempfile


BENCH = pathlib.Path(__file__).resolve().parent
RUNNER = BENCH / "run_claim_benchmark.py"


def executable(path: pathlib.Path, source: str) -> pathlib.Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def inputs(folder: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    case = {
        "case_id": "test", "evaluation_group": "frozen_final", "source_name": "Example Source",
        "title": "Example", "url": "https://example.org/article", "publication_date": "2026-10-31",
        "category": "Access", "country": "United Kingdom", "region": "Northern Europe", "complexity": "complex",
        "two_main_points": [
            {"point_id": "p1", "fact_ids": ["f1"], "point": "A group proposes an access measure."},
            {"point_id": "p2", "fact_ids": ["f2"], "point": "The proposal includes step-free information."}
        ],
        "essential_qualification_fact_ids": ["f3"],
        "verified_facts": [
            {"fact_id": "f1", "status": "PLANNED OR PROPOSED", "fact": "A group proposed an access measure.", "evidence_ref": "article"},
            {"fact_id": "f2", "status": "PLANNED OR PROPOSED", "fact": "The proposal would add step-free information.", "evidence_ref": "article"},
            {"fact_id": "f3", "status": "UNSUPPORTED OR UNCERTAIN", "fact": "The source does not report completion.", "evidence_ref": "article"}
        ]
    }
    cases = folder / "cases.json"
    cases.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    methods = folder / "methods.json"
    methods.write_text(json.dumps({"methods": [{"method_id": "A"}, {"method_id": "B"}]}), encoding="utf-8")
    return cases, methods


def run(fake_source: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    with tempfile.TemporaryDirectory() as temporary:
        folder = pathlib.Path(temporary)
        fake = executable(folder / "llama-cli", fake_source)
        model = folder / "model.gguf"
        model.write_bytes(b"public-safe-test-model-placeholder")
        cases, methods = inputs(folder)
        output = folder / "result.json"
        command = [sys.executable, str(RUNNER), "--binary", str(fake), "--model", str(model),
            "--expected-sha256", hashlib.sha256(model.read_bytes()).hexdigest(), "--model-id", "qwen-test",
            "--model-revision", "test-revision", "--cases", str(cases), "--methods", str(methods), "--output", str(output)]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        return completed, json.loads(output.read_text(encoding="utf-8"))


success, success_data = run(r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
if '--version' in sys.argv:
    print('fake llama-cli 1')
    raise SystemExit(0)
prompt = sys.argv[sys.argv.index('-p') + 1]
output = Path(sys.argv[sys.argv.index('--output-file') + 1])
if 'separate semantic claim checker' in prompt:
    if 'improves access' in prompt:
        text = json.dumps({"overall":"REWRITE","claims":[{"claim":"The measure improves access.","status":"UNSUPPORTED OR UNCERTAIN","evidence_ids":[],"finding":"The source reports a proposal, not an achieved improvement."}],"rewrite_instructions":["Describe the proposal without claiming completion."]})
    else:
        text = json.dumps({"overall":"PASS","claims":[{"claim":"The group proposes a measure.","status":"PLANNED OR PROPOSED","evidence_ids":["f1","f2"],"finding":"The wording preserves proposal status."}],"rewrite_instructions":[]})
elif 'single controlled rewrite' in prompt:
    text = 'Example Source reports a proposed access measure for disabled passengers. The plan would add step-free transport information.'
elif 'TWO-MAIN-POINTS METHOD' in prompt:
    text = 'Example Source reports a measure that improves access for disabled passengers. It adds step-free transport information.'
else:
    text = 'Example Source reports a proposed access measure for disabled passengers. The plan would add step-free transport information.'
output.write_text('User:\n<PROMPT>\n\nAssistant:\n' + text + '\n', encoding='utf-8')
''')

failure, failure_data = run(r'''#!/usr/bin/env python3
import sys
if '--version' in sys.argv:
    print('fake llama-cli 1')
else:
    print('bounded diagnostic', file=sys.stderr)
    raise SystemExit(7)
''')

row = success_data["results"][0]
checks = {
    "success_exit": success.returncode == 0,
    "baseline_preserved": "proposed" in row["method_a"]["summary"],
    "unsafe_initial_preserved": "improves access" in row["method_b"]["initial"]["summary"],
    "semantic_checker_requests_rewrite": row["method_b"]["initial_claim_check"]["parsed"]["overall"] == "REWRITE",
    "unsupported_claim_has_no_fake_evidence": row["method_b"]["initial_claim_check"]["parsed"]["claims"][0]["evidence_ids"] == [],
    "one_rewrite_performed": row["method_b"]["rewrite_performed"] is True,
    "rewrite_preserves_plan_status": "proposed" in row["method_b"]["rewrite"]["summary"],
    "final_check_passes": row["method_b"]["final_claim_check"]["parsed"]["overall"] == "PASS",
    "final_status_pass": row["method_b"]["final_status"] == "PASS",
    "five_actual_success_inferences": success_data["inference_calls"] == 5,
    "failure_exit": failure.returncode == 1,
    "two_actual_failure_inferences": failure_data["inference_calls"] == 2,
    "independent_authoring_failures_preserved": failure_data["results"][0]["method_a"]["return_code"] == 7 and failure_data["results"][0]["method_b"]["initial"]["return_code"] == 7,
    "failure_stderr_retained": "bounded diagnostic" in failure_data["results"][0]["method_a"]["stderr"],
    "protected_examples_false": success_data["frozen_inputs"]["protected_curated_examples_used"] is False,
}
failed = [name for name, passed in checks.items() if not passed]
print(json.dumps({"status": "PASS" if not failed else "FAIL", "checks": checks, "failed": failed}, indent=2))
raise SystemExit(1 if failed else 0)
