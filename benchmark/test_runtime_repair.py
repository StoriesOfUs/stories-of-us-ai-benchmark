#!/usr/bin/env python3
"""Model-free regression checks for result persistence and error diagnostics."""
from __future__ import annotations

import hashlib
import json
import pathlib
import stat
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "benchmark/run_benchmark.py"
JOB_MANIFEST = ROOT / "benchmark/job_manifest.py"


def executable(path: pathlib.Path, source: str) -> pathlib.Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def run(fake_source: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    with tempfile.TemporaryDirectory() as temporary:
        folder = pathlib.Path(temporary)
        fake = executable(folder / "llama-cli", fake_source)
        model = folder / "model.gguf"
        model.write_bytes(b"public-safe-test-model-placeholder")
        cases = folder / "cases.json"
        cases.write_text(json.dumps({"cases": [{
            "case_id": "test",
            "url": "https://example.org/article",
            "source_name": "Example Source",
            "title": "Example",
            "publication_date": "2026-10-30",
            "category": "Access",
            "country": "United Kingdom",
            "region": "Northern Europe",
            "disability_relevance": "An access measure affecting disabled people.",
            "evidence": ["The source reports an access measure for disabled people."]
        }]}), encoding="utf-8")
        output = folder / "result.json"
        command = [
            sys.executable, str(RUNNER), "--binary", str(fake), "--model", str(model),
            "--expected-sha256", hashlib.sha256(model.read_bytes()).hexdigest(),
            "--model-id", "granite-test", "--cases", str(cases), "--output", str(output),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        return completed, json.loads(output.read_text(encoding="utf-8"))


success, success_data = run("""#!/usr/bin/env python3
import sys
if '--version' in sys.argv:
    print('fake llama-cli 1')
else:
    print('Example Source reports an access measure for disabled people. The article describes one supported practical detail.')
""")
failure, failure_data = run("""#!/usr/bin/env python3
import sys
if '--version' in sys.argv:
    print('fake llama-cli 1')
else:
    print('bounded diagnostic', file=sys.stderr)
    raise SystemExit(7)
""")

with tempfile.TemporaryDirectory() as temporary:
    manifest = pathlib.Path(temporary) / "model.json"
    init = subprocess.run([
        sys.executable, str(JOB_MANIFEST), "init", "--model-id", "test-model",
        "--model-revision", "abc", "--model-sha256", "0" * 64,
        "--runtime-revision", "def", "--output", str(manifest),
    ], capture_output=True, text=True, check=False)
    finalise = subprocess.run([
        sys.executable, str(JOB_MANIFEST), "finalise", "--output", str(manifest),
        "--validation", "success", "--build", "success", "--download", "failure",
        "--inference", "skipped",
    ], capture_output=True, text=True, check=False)
    enforce = subprocess.run([
        sys.executable, str(JOB_MANIFEST), "enforce", "--output", str(manifest),
    ], capture_output=True, text=True, check=False)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))

checks = {
    "single_turn_flag": '"--single-turn"' in RUNNER.read_text(encoding="utf-8"),
    "old_conversation_flag_removed": '"-cnv"' not in RUNNER.read_text(encoding="utf-8"),
    "success_exit": success.returncode == 0,
    "success_manifest": success_data["status"] == "SUCCESS",
    "success_raw_output_retained": "Example Source" in success_data["results"][0]["raw_response"],
    "failure_exit": failure.returncode == 1,
    "failure_manifest": failure_data["status"] == "FAILURE",
    "failure_return_code": failure_data["results"][0]["return_code"] == 7,
    "failure_stderr_retained": "bounded diagnostic" in failure_data["results"][0]["stderr"],
    "failure_manifest_initialised": init.returncode == 0,
    "failure_manifest_finalised": finalise.returncode == 0 and manifest_data["status"] == "FAILURE",
    "failure_status_enforced": enforce.returncode == 1,
    "failure_phase_retained": manifest_data["failure_reason"] == "DOWNLOAD_FAILURE",
}
failed = [name for name, passed in checks.items() if not passed]
print(json.dumps({"status": "PASS" if not failed else "FAIL", "checks": checks, "failed": failed}, indent=2))
raise SystemExit(1 if failed else 0)
