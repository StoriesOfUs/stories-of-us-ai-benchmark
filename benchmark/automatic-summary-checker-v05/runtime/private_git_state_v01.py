#!/usr/bin/env python3
"""Durable private-Git state for the proposed V05 live experiment.

Every request slot is committed and pushed before a transport call can begin.
The module never prints private content, credentials or Git command output.
"""
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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


class PersistenceBackend(Protocol):
    def persist(self, paths: list[Path], message: str) -> str: ...


class GitPersistence:
    """Commit, push and remotely verify private state without exposing output."""

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
        relative = []
        for path in paths:
            resolved = path.resolve()
            try:
                relative.append(str(resolved.relative_to(self.repository_root)))
            except ValueError as exc:
                raise StateStop("Private persistence path escaped the repository") from exc
        self._run(["git", "add", "-A", "--", *relative])
        # The quiet diff command returns 1 when changes exist. Run it explicitly
        # without check so a no-change transaction can be rejected cleanly.
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
        remote = self._run(
            ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{self.branch}"],
            capture=True,
        )
        remote_head = remote.split()[0] if remote else ""
        if local_head != remote_head:
            raise StateStop("Private remote commit verification failed")
        return local_head


def new_state() -> dict[str, Any]:
    return {
        "schema_version": "stories-of-us-v05-live-experiment-state-v01",
        "status": "ACTIVE",
        "stage": "NOT_STARTED",
        "created_at_utc": utc_now(),
        "operation_dates": {},
        "completed_operations": [],
        "consumed_slots": [],
        "revision_case_ids": [],
    }


def new_ledger() -> dict[str, Any]:
    return {
        "schema_version": "stories-of-us-v05-live-request-ledger-v01",
        "maximum_requests": 44,
        "maximum_retries": 0,
        "aggregate_input_ceiling": 624000,
        "aggregate_output_ceiling": 103424,
        "hard_neuron_cap": 25410,
        "requests": [],
        "cumulative_requests": 0,
        "cumulative_retries": 0,
        "reserved_input_tokens": 0,
        "reserved_output_tokens": 0,
        "reserved_neurons": 0.0,
        "known_provider_input_tokens": 0,
        "known_provider_output_tokens": 0,
        "known_provider_neurons": 0.0,
        "recognised_usage_requests": 0,
        "unknown_usage_requests": 0,
        "day_reserved_neurons": {
            "DAY_0_FOCUSED_DIAGNOSTICS": 0.0,
            "DAY_1_DEVELOPMENT": 0.0,
            "DAY_2_D14_CORRECTION": 0.0,
            "DAY_3_EVALUATION": 0.0,
        },
    }


class DurablePrivateState:
    DAY_CAPS = {
        "DAY_0_FOCUSED_DIAGNOSTICS": 5579.981280,
        "DAY_1_DEVELOPMENT": 9299.968800,
        "DAY_2_D14_CORRECTION": 772.435808,
        "DAY_3_EVALUATION": 9757.282464,
    }

    def __init__(self, repository_root: Path, backend: PersistenceBackend):
        self.repository_root = repository_root.resolve()
        self.backend = backend
        self.live_root = self.repository_root / "live_v05"
        self.state_path = self.live_root / "state/experiment_state_v01.json"
        self.ledger_path = self.live_root / "state/request_resource_ledger_v01.json"
        self.lock_path = self.live_root / "state/locks/active_dispatch.lock"

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.state_path.is_file() or not self.ledger_path.is_file():
            raise StateStop("Live state is absent")
        return read_json(self.state_path), read_json(self.ledger_path)

    def start_operation(self, operation: str, run_id: str, utc_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.lock_path.exists():
            raise StateStop("Concurrent or interrupted operation lock exists")
        state = read_json(self.state_path) if self.state_path.exists() else new_state()
        ledger = read_json(self.ledger_path) if self.ledger_path.exists() else new_ledger()
        if operation in state["completed_operations"]:
            raise StateStop("Repeat operation refused")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(
            json.dumps({"operation": operation, "run_id": run_id, "utc_date": utc_date}) + "\n",
            encoding="utf-8",
        )
        atomic_json(self.state_path, state)
        atomic_json(self.ledger_path, ledger)
        self.backend.persist(
            [self.lock_path, self.state_path, self.ledger_path],
            f"v05 reserve operation {operation}",
        )
        return state, ledger

    def reserve_request(
        self,
        slot_id: str,
        execution_day: str,
        conservative_input_tokens: int,
        output_tokens: int,
        reserved_neurons: float,
        exact_count: dict[str, Any],
    ) -> dict[str, Any]:
        state, ledger = self.load()
        if state["status"] != "ACTIVE":
            raise StateStop("Terminal live state refuses transmission")
        if slot_id in state["consumed_slots"]:
            raise StateStop("Consumed request slot cannot be repeated")
        if ledger["cumulative_requests"] >= ledger["maximum_requests"]:
            raise StateStop("Request cap reached")
        if ledger["cumulative_retries"] != 0:
            raise StateStop("Zero-retry contract has been violated")
        if execution_day not in self.DAY_CAPS:
            raise StateStop("Unknown execution day")
        if ledger["reserved_input_tokens"] + conservative_input_tokens > ledger["aggregate_input_ceiling"]:
            raise StateStop("Aggregate input reservation would be exceeded")
        if ledger["reserved_output_tokens"] + output_tokens > ledger["aggregate_output_ceiling"]:
            raise StateStop("Aggregate output reservation would be exceeded")
        if ledger["reserved_neurons"] + reserved_neurons > ledger["hard_neuron_cap"] + 1e-9:
            raise StateStop("Aggregate neuron hard cap would be exceeded")
        day_total = ledger["day_reserved_neurons"][execution_day] + reserved_neurons
        if day_total > self.DAY_CAPS[execution_day] + 1e-9:
            raise StateStop("Daily neuron reservation would be exceeded")
        if slot_id.startswith("REV__"):
            case_id = slot_id.removeprefix("REV__")
            if case_id in state["revision_case_ids"]:
                raise StateStop("Second revision is forbidden")
            if len(state["revision_case_ids"]) >= 4:
                raise StateStop("Four-revision experiment cap reached")
            state["revision_case_ids"].append(case_id)

        record = {
            "slot_id": slot_id,
            "execution_day": execution_day,
            "reserved_at_utc": utc_now(),
            "status": "CONSUMED_BEFORE_TRANSMISSION",
            "conservative_input_tokens": conservative_input_tokens,
            "output_tokens": output_tokens,
            "reserved_neurons": reserved_neurons,
            "exact_local_count": exact_count,
            "transmission_started": False,
            "usage_status": "UNKNOWN_NOT_YET_OBSERVED",
        }
        state["consumed_slots"].append(slot_id)
        ledger["requests"].append(record)
        ledger["cumulative_requests"] += 1
        ledger["reserved_input_tokens"] += conservative_input_tokens
        ledger["reserved_output_tokens"] += output_tokens
        ledger["reserved_neurons"] = round(ledger["reserved_neurons"] + reserved_neurons, 9)
        ledger["day_reserved_neurons"][execution_day] = round(day_total, 9)
        atomic_json(self.state_path, state)
        atomic_json(self.ledger_path, ledger)
        commit = self.backend.persist(
            [self.state_path, self.ledger_path],
            f"v05 consume request {slot_id}",
        )
        record["durable_pretransmission_commit"] = commit
        atomic_json(self.ledger_path, ledger)
        self.backend.persist(
            [self.ledger_path],
            f"v05 verify durable reservation {slot_id}",
        )
        return record

    def mark_transmission_started(self, slot_id: str) -> None:
        state, ledger = self.load()
        record = next((row for row in ledger["requests"] if row["slot_id"] == slot_id), None)
        if record is None or record["status"] != "CONSUMED_BEFORE_TRANSMISSION":
            raise StateStop("Transmission cannot start without a durable consumed reservation")
        record["transmission_started"] = True
        record["status"] = "TRANSMISSION_STARTED"
        atomic_json(self.ledger_path, ledger)
        self.backend.persist([self.ledger_path], f"v05 transmission started {slot_id}")

    def save_response(
        self,
        slot_id: str,
        capture: dict[str, Any],
        usage: dict[str, Any],
    ) -> Path:
        state, ledger = self.load()
        record = next((row for row in ledger["requests"] if row["slot_id"] == slot_id), None)
        if record is None:
            raise StateStop("Response has no consumed request reservation")
        response_path = self.live_root / "responses" / f"{slot_id}.json"
        atomic_json(response_path, capture)
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
        self.backend.persist(
            [response_path, self.ledger_path],
            f"v05 capture response {slot_id}",
        )
        return response_path

    def save_parsed(self, slot_id: str, value: dict[str, Any]) -> Path:
        path = self.live_root / "results/parsed" / f"{slot_id}.json"
        atomic_json(path, value)
        self.backend.persist([path], f"v05 save parsed result {slot_id}")
        return path

    def transition(self, stage: str, extra: dict[str, Any] | None = None) -> None:
        state, _ = self.load()
        state["stage"] = stage
        state["updated_at_utc"] = utc_now()
        if extra:
            state.update(extra)
        atomic_json(self.state_path, state)
        self.backend.persist([self.state_path], f"v05 stage {stage}")

    def save_operation_result(self, operation: str, value: dict[str, Any]) -> Path:
        path = self.live_root / "results/operations" / f"{operation}_result_v01.json"
        atomic_json(path, value)
        self.backend.persist([path], f"v05 save operation result {operation}")
        return path

    def safety_stop(self, reason_class: str) -> None:
        state, _ = self.load()
        state["status"] = "SAFETY_STOP"
        state["safety_stop_reason_class"] = reason_class
        state["updated_at_utc"] = utc_now()
        atomic_json(self.state_path, state)
        self.backend.persist([self.state_path], "v05 safety stop")
        # Deliberately retain the dispatch lock for explicit recovery review.

    def finish_operation(self, operation: str, next_stage: str, utc_date: str) -> None:
        state, _ = self.load()
        state["stage"] = next_stage
        state["operation_dates"][operation] = utc_date
        state["completed_operations"].append(operation)
        state["updated_at_utc"] = utc_now()
        atomic_json(self.state_path, state)
        self.lock_path.unlink(missing_ok=True)
        self.backend.persist(
            [self.state_path, self.lock_path],
            f"v05 complete operation {operation}",
        )
