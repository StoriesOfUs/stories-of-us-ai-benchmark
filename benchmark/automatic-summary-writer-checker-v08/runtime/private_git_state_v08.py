#!/usr/bin/env python3
"""Durable, isolated private state and reservation ledger for V08."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Protocol


class StateStop(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


class PersistenceBackend(Protocol):
    def persist(self, paths: list[Path], message: str) -> str: ...


class GitPersistence:
    """Commit, push and verify private state without printing Git output."""

    def __init__(self, repository_root: Path, branch: str = "main"):
        self.repository_root = repository_root.resolve()
        self.branch = branch

    def _run(self, arguments: list[str], capture: bool = False) -> str:
        environment = dict(os.environ)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            completed = subprocess.run(
                arguments,
                cwd=self.repository_root,
                env=environment,
                check=True,
                text=True,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as exc:
            raise StateStop("Private Git persistence failed; transmission is refused") from exc
        return completed.stdout.strip() if capture else ""

    def persist(self, paths: list[Path], message: str) -> str:
        relative: list[str] = []
        for path in paths:
            try:
                relative.append(str(path.resolve().relative_to(self.repository_root)))
            except ValueError as exc:
                raise StateStop("Private persistence path escaped the repository") from exc
        self._run(["git", "add", "-A", "--", *relative])
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.repository_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if diff.returncode == 0:
            raise StateStop("Private persistence produced no durable change")
        if diff.returncode != 1:
            raise StateStop("Private Git staged-state verification failed")
        self._run(["git", "commit", "-m", message])
        self._run(["git", "push", "origin", f"HEAD:{self.branch}"])
        local_head = self._run(["git", "rev-parse", "HEAD"], capture=True)
        remote = self._run(["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{self.branch}"], capture=True)
        remote_head = remote.split()[0] if remote else ""
        if local_head != remote_head:
            raise StateStop("Private remote commit verification failed")
        return local_head


OPERATIONS = (
    "stage0-challenges",
    "stage1-writer-first-drafts",
    "stage2-checker-part-one",
    "stage3-checker-completion-and-errors",
    "stage4a-revisions",
    "stage4b-complete-rechecks",
)
OPERATION_DAY = {
    "stage0-challenges": "DAY_0_CHALLENGES",
    "stage1-writer-first-drafts": "DAY_1_WRITER",
    "stage2-checker-part-one": "DAY_2_CHECKER_PART_ONE",
    "stage3-checker-completion-and-errors": "DAY_3_CHECKER_COMPLETION",
    "stage4a-revisions": "DAY_4_REVISIONS_AND_RECHECKS",
    "stage4b-complete-rechecks": "DAY_4_REVISIONS_AND_RECHECKS",
}
DAY_CAPS = {
    "DAY_0_CHALLENGES": 5239.256832,
    "DAY_1_WRITER": 1524.378880,
    "DAY_2_CHECKER_PART_ONE": 9823.606560,
    "DAY_3_CHECKER_COMPLETION": 9823.606560,
    "DAY_4_REVISIONS_AND_RECHECKS": 8073.449920,
}
OPERATION_REQUEST_CAPS = {
    "stage0-challenges": 8,
    "stage1-writer-first-drafts": 10,
    "stage2-checker-part-one": 15,
    "stage3-checker-completion-and-errors": 15,
    "stage4a-revisions": 10,
    "stage4b-complete-rechecks": 10,
}
MODEL_RESERVATIONS = {
    "@cf/openai/gpt-oss-120b": (14_000, 3_072, 654.907104),
    "@cf/google/gemma-4-26b-a4b-it": (16_000, 256, 152.437888),
}


def new_state(scientific_freeze: str) -> dict[str, Any]:
    return {
        "schema_version": "stories-of-us-v08-live-experiment-state-v01",
        "scientific_freeze_sha256": scientific_freeze,
        "status": "ACTIVE",
        "stage": "NOT_STARTED",
        "created_at_utc": utc_now(),
        "operation_dates": {},
        "allowance_preflight_records": {},
        "completed_operations": [],
        "consumed_slots": [],
        "revision_case_ids": [],
    }


def new_ledger() -> dict[str, Any]:
    return {
        "schema_version": "stories-of-us-v08-live-request-ledger-v01",
        "maximum_requests": 68,
        "maximum_gpt_oss_requests": 48,
        "maximum_gemma_requests": 20,
        "maximum_retries": 0,
        "aggregate_input_ceiling": 992000,
        "aggregate_output_ceiling": 152576,
        "hard_neuron_cap": 34485,
        "requests": [],
        "cumulative_requests": 0,
        "cumulative_gpt_oss_requests": 0,
        "cumulative_gemma_requests": 0,
        "cumulative_retries": 0,
        "reserved_input_tokens": 0,
        "reserved_output_tokens": 0,
        "reserved_neurons": 0.0,
        "known_provider_input_tokens": 0,
        "known_provider_output_tokens": 0,
        "known_provider_neurons": 0.0,
        "recognised_usage_requests": 0,
        "unknown_usage_requests": 0,
        "day_reserved_neurons": {key: 0.0 for key in DAY_CAPS},
        "operation_request_counts": {key: 0 for key in OPERATIONS},
    }


class DurablePrivateState:
    def __init__(self, repository_root: Path, backend: PersistenceBackend, scientific_freeze: str):
        self.repository_root = repository_root.resolve()
        self.backend = backend
        self.scientific_freeze = scientific_freeze
        self.live_root = self.repository_root / "live_v08"
        self.state_path = self.live_root / "state/experiment_state_v01.json"
        self.ledger_path = self.live_root / "state/request_resource_ledger_v01.json"
        self.lock_path = self.live_root / "state/locks/active_dispatch.lock"

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.state_path.is_file() or not self.ledger_path.is_file():
            raise StateStop("V08 live state is absent")
        state, ledger = read_json(self.state_path), read_json(self.ledger_path)
        if state.get("scientific_freeze_sha256") != self.scientific_freeze:
            raise StateStop("V08 live state belongs to another scientific freeze")
        return state, ledger

    def start_operation(self, operation: str, run_id: str, utc_date: str, allowance_preflight: dict[str, Any]) -> None:
        if operation not in OPERATIONS:
            raise StateStop("Unknown V08 operation")
        if self.lock_path.exists():
            raise StateStop("Concurrent or interrupted V08 operation lock exists")
        state = read_json(self.state_path) if self.state_path.exists() else new_state(self.scientific_freeze)
        ledger = read_json(self.ledger_path) if self.ledger_path.exists() else new_ledger()
        if operation in state["completed_operations"]:
            raise StateStop("Repeat V08 operation refused")
        if allowance_preflight.get("operation") != operation or allowance_preflight.get("utc_date") != utc_date:
            raise StateStop("Allowance preflight does not match this V08 operation")
        state.setdefault("allowance_preflight_records", {})[operation] = allowance_preflight
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps({
            "operation": operation,
            "run_id": run_id,
            "utc_date": utc_date,
            "allowance_preflight_sha256": allowance_preflight.get("receipt_sha256"),
        }) + "\n", encoding="utf-8")
        atomic_json(self.state_path, state)
        atomic_json(self.ledger_path, ledger)
        self.backend.persist([self.lock_path, self.state_path, self.ledger_path], f"v08 reserve operation {operation}")

    def reserve_request(self, slot_id: str, operation: str, model: str, exact_count: dict[str, Any]) -> None:
        state, ledger = self.load()
        if state["status"] != "ACTIVE":
            raise StateStop("Terminal V08 state refuses transmission")
        if operation not in OPERATIONS or model not in MODEL_RESERVATIONS:
            raise StateStop("Unknown V08 operation or model")
        if slot_id in state["consumed_slots"]:
            raise StateStop("Consumed V08 request slot cannot be repeated")
        if ledger["cumulative_requests"] >= 68 or ledger["cumulative_retries"] != 0:
            raise StateStop("V08 request or retry contract would be exceeded")
        if ledger["operation_request_counts"][operation] >= OPERATION_REQUEST_CAPS[operation]:
            raise StateStop("V08 operation request cap would be exceeded")
        conservative_input, output, neurons = MODEL_RESERVATIONS[model]
        if ledger["reserved_input_tokens"] + conservative_input > 992_000:
            raise StateStop("Aggregate V08 input reservation would be exceeded")
        if ledger["reserved_output_tokens"] + output > 152_576:
            raise StateStop("Aggregate V08 output reservation would be exceeded")
        if ledger["reserved_neurons"] + neurons > 34_485 + 1e-9:
            raise StateStop("Aggregate V08 neuron hard cap would be exceeded")
        day = OPERATION_DAY[operation]
        day_total = ledger["day_reserved_neurons"][day] + neurons
        if day_total > DAY_CAPS[day] + 1e-9:
            raise StateStop("V08 daily neuron reservation would be exceeded")
        model_key = "gpt_oss" if model == "@cf/openai/gpt-oss-120b" else "gemma"
        model_cap = 48 if model_key == "gpt_oss" else 20
        if ledger[f"cumulative_{model_key}_requests"] >= model_cap:
            raise StateStop("V08 per-model request cap would be exceeded")
        if operation == "stage4a-revisions":
            case_id = slot_id.removeprefix("REV__")
            if case_id in state["revision_case_ids"] or len(state["revision_case_ids"]) >= 10:
                raise StateStop("Second revision or revision cap violation")
            state["revision_case_ids"].append(case_id)
        record = {
            "slot_id": slot_id,
            "operation": operation,
            "execution_day": day,
            "model": model,
            "reserved_at_utc": utc_now(),
            "status": "CONSUMED_BEFORE_TRANSMISSION",
            "conservative_input_tokens": conservative_input,
            "output_tokens": output,
            "reserved_neurons": neurons,
            "exact_local_count": exact_count,
            "transmission_started": False,
            "usage_status": "UNKNOWN_NOT_YET_OBSERVED",
        }
        state["consumed_slots"].append(slot_id)
        ledger["requests"].append(record)
        ledger["cumulative_requests"] += 1
        ledger[f"cumulative_{model_key}_requests"] += 1
        ledger["operation_request_counts"][operation] += 1
        ledger["reserved_input_tokens"] += conservative_input
        ledger["reserved_output_tokens"] += output
        ledger["reserved_neurons"] = round(ledger["reserved_neurons"] + neurons, 9)
        ledger["day_reserved_neurons"][day] = round(day_total, 9)
        atomic_json(self.state_path, state)
        atomic_json(self.ledger_path, ledger)
        commit = self.backend.persist([self.state_path, self.ledger_path], f"v08 consume request {slot_id}")
        record["durable_pretransmission_commit"] = commit
        atomic_json(self.ledger_path, ledger)
        self.backend.persist([self.ledger_path], f"v08 verify durable reservation {slot_id}")

    def mark_transmission_started(self, slot_id: str) -> None:
        _, ledger = self.load()
        record = next((row for row in ledger["requests"] if row["slot_id"] == slot_id), None)
        if record is None or record["status"] != "CONSUMED_BEFORE_TRANSMISSION":
            raise StateStop("Transmission cannot start without a durable V08 reservation")
        record["transmission_started"] = True
        record["status"] = "TRANSMISSION_STARTED"
        atomic_json(self.ledger_path, ledger)
        self.backend.persist([self.ledger_path], f"v08 transmission started {slot_id}")

    def save_response(self, slot_id: str, capture: dict[str, Any], usage: dict[str, Any]) -> None:
        _, ledger = self.load()
        record = next((row for row in ledger["requests"] if row["slot_id"] == slot_id), None)
        if record is None:
            raise StateStop("V08 response has no consumed reservation")
        path = self.live_root / "responses" / f"{slot_id}.json"
        atomic_json(path, capture)
        record["status"] = "RESPONSE_CAPTURED"
        record["usage_status"] = usage.get("status", "UNKNOWN")
        record["provider_usage"] = usage
        if usage.get("status") == "RECOGNISED":
            ledger["recognised_usage_requests"] += 1
            ledger["known_provider_input_tokens"] += usage.get("prompt_tokens", 0)
            ledger["known_provider_output_tokens"] += usage.get("completion_tokens", 0)
            if isinstance(usage.get("neurons"), (int, float)):
                ledger["known_provider_neurons"] += usage["neurons"]
        else:
            ledger["unknown_usage_requests"] += 1
        atomic_json(self.ledger_path, ledger)
        self.backend.persist([path, self.ledger_path], f"v08 capture response {slot_id}")

    def save_parsed(self, slot_id: str, value: dict[str, Any]) -> None:
        path = self.live_root / "results/parsed" / f"{slot_id}.json"
        atomic_json(path, value)
        self.backend.persist([path], f"v08 save parsed result {slot_id}")

    def save_blocked(self, slot_id: str, operation: str, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise StateStop("Blocked V08 request requires an explicit reason")
        path = self.live_root / "results/blocked" / f"{slot_id}.json"
        atomic_json(path, {
            "schema_version": "stories-of-us-v08-blocked-request-v01",
            "slot_id": slot_id,
            "operation": operation,
            "status": "BLOCKED_NOT_ATTEMPTED",
            "reason": reason,
            "attempt_consumed": False,
        })
        self.backend.persist([path], f"v08 record blocked request {slot_id}")

    def save_operation_result(self, operation: str, value: dict[str, Any]) -> None:
        path = self.live_root / "results/operations" / f"{operation}_result_v01.json"
        atomic_json(path, value)
        self.backend.persist([path], f"v08 save operation result {operation}")

    def finish_operation(self, operation: str, next_stage: str, utc_date: str) -> None:
        state, _ = self.load()
        state["stage"] = next_stage
        state["operation_dates"][operation] = utc_date
        state["completed_operations"].append(operation)
        state["updated_at_utc"] = utc_now()
        atomic_json(self.state_path, state)
        self.lock_path.unlink(missing_ok=True)
        self.backend.persist([self.state_path, self.lock_path], f"v08 complete operation {operation}")

    def safety_stop(self, reason_class: str) -> None:
        state, _ = self.load()
        state["status"] = "SAFETY_STOP"
        state["safety_stop_reason_class"] = reason_class
        state["updated_at_utc"] = utc_now()
        atomic_json(self.state_path, state)
        self.backend.persist([self.state_path], "v08 safety stop")
        # Retain the active lock for explicit evidence review; never auto-recover.
