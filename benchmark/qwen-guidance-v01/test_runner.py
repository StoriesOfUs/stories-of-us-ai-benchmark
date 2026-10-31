#!/usr/bin/env python3
"""Model-free regression checks for three-condition execution and failure evidence."""
from __future__ import annotations

import hashlib
import json
import pathlib
import stat
import subprocess
import sys
import tempfile


BENCH = pathlib.Path(__file__).resolve().parent
RUNNER = BENCH / "run_qwen_guidance.py"


def executable(path: pathlib.Path, source: str) -> pathlib.Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def frozen_inputs(folder: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    case = {
        "case_id": "test", "evaluation_group": "fresh_unseen", "source_name": "Example Source",
        "title": "Example", "url": "https://example.org/article", "publication_date": "2026-10-31",
        "category": "Access", "country": "United Kingdom", "region": "Northern Europe",
        "article_facts": {"main_actor": "Example group", "principal_development": "A proposed access measure",
            "disabled_community": "Disabled passengers", "specific_concern": "Step-free transport",
            "event_status": "Proposed", "geographic_scope": "United Kingdom", "qualifications": "Not yet completed"},
        "verified_facts": [{"fact_id": "f1", "fact": "A measure was proposed.", "evidence_ref": "article"}],
        "eligibility": {"status": "VERIFIED_ELIGIBLE", "category_evidence": "Access", "geography_evidence": "UK"},
    }
    cases = folder / "cases.json"
    cases.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    conditions = folder / "conditions.json"
    conditions.write_text(json.dumps({"conditions": [
        {"condition_id": "A", "name": "A", "practical_guidance": False, "illustrative_examples": False},
        {"condition_id": "B", "name": "B", "practical_guidance": True, "illustrative_examples": False},
        {"condition_id": "C", "name": "C", "practical_guidance": True, "illustrative_examples": True},
    ]}), encoding="utf-8")
    examples = folder / "examples.json"
    examples.write_text(json.dumps({"examples": [{"summary": "Fictional style example. It has a second sentence."}]}), encoding="utf-8")
    return cases, conditions, examples


def run(fake_source: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    with tempfile.TemporaryDirectory() as temporary:
        folder = pathlib.Path(temporary)
        fake = executable(folder / "llama-cli", fake_source)
        model = folder / "model.gguf"
        model.write_bytes(b"public-safe-test-model-placeholder")
        cases, conditions, examples = frozen_inputs(folder)
        output = folder / "result.json"
        command = [sys.executable, str(RUNNER), "--binary", str(fake), "--model", str(model),
            "--expected-sha256", hashlib.sha256(model.read_bytes()).hexdigest(), "--model-id", "qwen-test",
            "--model-revision", "test-revision", "--cases", str(cases), "--conditions", str(conditions),
            "--examples", str(examples), "--output", str(output)]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        return completed, json.loads(output.read_text(encoding="utf-8"))


success, success_data = run("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '--version' in sys.argv:
    print('fake llama-cli 1')
else:
    output = Path(sys.argv[sys.argv.index('--output-file') + 1])
    output.write_text('User:\\n<PROMPT>\\n\\nAssistant:\\nExample Source reports a proposed access measure for disabled passengers. The plan would add verified step-free transport information.\\n', encoding='utf-8')
""")
failure, failure_data = run("""#!/usr/bin/env python3
import sys
if '--version' in sys.argv:
    print('fake llama-cli 1')
else:
    print('bounded diagnostic', file=sys.stderr)
    raise SystemExit(7)
""")

checks = {
    "success_exit": success.returncode == 0,
    "three_conditions_run": len(success_data["results"]) == 3 and {row["condition_id"] for row in success_data["results"]} == {"A", "B", "C"},
    "same_case_all_conditions": {row["case_id"] for row in success_data["results"]} == {"test"},
    "output_text_retained": all("Example Source" in row["summary"] for row in success_data["results"]),
    "condition_c_larger_prompt": success_data["results"][2]["prompt_characters"] > success_data["results"][1]["prompt_characters"] > success_data["results"][0]["prompt_characters"],
    "failure_exit": failure.returncode == 1,
    "all_failures_preserved": len(failure_data["results"]) == 3 and all(row["return_code"] == 7 for row in failure_data["results"]),
    "stderr_retained": all("bounded diagnostic" in row["stderr"] for row in failure_data["results"]),
    "protected_examples_false": success_data["frozen_inputs"]["protected_curated_examples_used"] is False,
}
failed = [name for name, passed in checks.items() if not passed]
print(json.dumps({"status": "PASS" if not failed else "FAIL", "checks": checks, "failed": failed}, indent=2))
raise SystemExit(1 if failed else 0)
