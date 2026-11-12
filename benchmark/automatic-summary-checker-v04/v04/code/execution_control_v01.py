#!/usr/bin/env python3
"""Fail-closed V04 execution controls for simulation and a future approved run.

The package ships with no authority or live state. A network call is impossible
unless a later owner authority record matches the exact final manifest and all
preflight fields. Offline tests inject MockTransport and isolated temporary state.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, BinaryIO, Protocol
import urllib.error
import urllib.request

from checker_core_v01 import extract_recognised_usage


CAPTURE_LIMIT_BYTES = 131072
ACCOUNT_RE = re.compile(r"^[0-9A-Fa-f]{32}$")
SAFE_HEADERS = {"cf-ray", "content-type", "date", "server"}


class SafetyStop(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_credentials(account_id: str, token: str, confirmation: str) -> None:
    if ACCOUNT_RE.fullmatch(account_id) is None:
        raise SafetyStop("Local Account ID validation failed before state creation")
    if not token:
        raise SafetyStop("Local token validation failed before state creation")
    if token != confirmation:
        raise SafetyStop("Hidden token entries did not match before state creation")


def verify_manifest(package_root: Path) -> str:
    path = package_root / "recovery" / "freeze_manifest_v01.json"
    if not path.is_file():
        raise SafetyStop("Execution locked: final freeze manifest is absent")
    manifest = read_json(path)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SafetyStop("Execution locked: manifest is incomplete")
    for relative, expected in files.items():
        target = package_root / relative
        if not target.is_file() or sha_file(target) != expected:
            raise SafetyStop(f"Frozen file mismatch: {relative}")
    return sha_file(path)


def require_authority(authority_path: Path, freeze_hash: str, execution_day: str) -> dict[str, Any]:
    if not authority_path.is_file():
        raise SafetyStop("Execution locked: exact-freeze authority is absent")
    value = read_json(authority_path)
    exact = {
        "freeze_manifest_sha256": freeze_hash,
        "approval_scope": "ONE_BOUNDED_AUTOMATIC_SUMMARY_CHECKER_CLAIM_IDENTIFICATION_TEST_V04",
        "maximum_requests": 35,
        "maximum_retries": 0,
        "hard_neuron_cap": 17666,
        "maximum_additional_expenditure": "£0",
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            raise SafetyStop(f"Execution locked: authority field {key} does not match")
    if execution_day not in {"DAY_1_DEVELOPMENT", "DAY_2_D14_CORRECTION", "DAY_3_EVALUATION"}:
        raise SafetyStop("Unknown execution day")
    if value.get("authorised_execution_days", {}).get(execution_day) is not True:
        raise SafetyStop(f"Execution locked: {execution_day} is not authorised")
    required = (
        "workers_free_eligibility_currently_verified",
        "model_availability_currently_verified",
        "pricing_currently_verified",
        "interface_currently_verified",
        "private_evidence_route_currently_verified",
        "exact_tokenizer_counts_currently_verified",
        "no_paid_fallback",
        "no_model_substitution",
        "no_account_switching",
    )
    if any(value.get(field) is not True for field in required):
        raise SafetyStop("Execution locked: a mandatory authority prerequisite is absent or false")
    if value.get("allowance_status_by_day", {}).get(execution_day) not in {
        "VERIFIED_SUFFICIENT",
        "OWNER_APPROVED_EXACT_EXPERIMENT_UNKNOWN_EXCEPTION",
    }:
        raise SafetyStop("Execution locked: day-specific allowance evidence or exception is absent")
    return value


@dataclass
class TransportResult:
    status: int | None
    body: bytes
    headers: dict[str, str]
    elapsed_seconds: float
    error: str | None = None
    uncertain: bool = False
    truncated: bool = False


class Transport(Protocol):
    def send(self, payload: dict[str, Any], account_id: str, token: str) -> TransportResult: ...


def _read_bounded(stream: BinaryIO) -> tuple[bytes, bool]:
    observed = stream.read(CAPTURE_LIMIT_BYTES + 1)
    return observed[:CAPTURE_LIMIT_BYTES], len(observed) > CAPTURE_LIMIT_BYTES


class CloudflareChatTransport:
    """One OpenAI-compatible Chat Completions request; no retries or fallback."""

    def send(self, payload: dict[str, Any], account_id: str, token: str) -> TransportResult:
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body, truncated = _read_bounded(response)
                headers = {k.lower(): v for k, v in response.headers.items() if k.lower() in SAFE_HEADERS}
                return TransportResult(response.status, body, headers, time.monotonic() - started, truncated=truncated)
        except urllib.error.HTTPError as exc:
            body, truncated = _read_bounded(exc)
            headers = {k.lower(): v for k, v in exc.headers.items() if k.lower() in SAFE_HEADERS}
            return TransportResult(exc.code, body, headers, time.monotonic() - started, error="HTTP_ERROR", truncated=truncated)
        except (TimeoutError, socket.timeout):
            return TransportResult(None, b"", {}, time.monotonic() - started, error="TIMEOUT", uncertain=True)
        except (urllib.error.URLError, OSError):
            return TransportResult(None, b"", {}, time.monotonic() - started, error="NETWORK_ERROR", uncertain=True)


def sanitize_body(body: bytes, account_id: str, token: str) -> str:
    text = body.decode("utf-8", errors="replace")
    for secret in (account_id, token):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{4,}", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(authorization[\"'\s:=]+)([^\s,}\]]+)", r"\1[REDACTED]", text)
    if any(secret and secret in text for secret in (account_id, token)):
        raise SafetyStop("Secret redaction failed before persistence")
    return text


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": "stories-of-us-automatic-checker-state-v01",
        "created_at_utc": now(),
        "status": "ACTIVE",
        "stage": "DEVELOPMENT",
        "consumed_slots": [],
        "reservations": [],
        "cumulative_requests": 0,
        "cumulative_retries": 0,
        "revision_case_ids": [],
        "day_reservations": {
            "DAY_1_DEVELOPMENT": 0.0,
            "DAY_2_D14_CORRECTION": 0.0,
            "DAY_3_EVALUATION": 0.0,
        },
    }


def require_scoring_gate_ready(scoring_results: Any, expected_count: int) -> None:
    """Refuse progression unless every protected adjudication is resolved and safe.

    The caller still decides the stage's accuracy/decision thresholds. This check
    independently prevents a PASS from bypassing missing/partial coverage,
    inventions, duplicates, inventory gaps or uncertain semantic mappings.
    """
    if not isinstance(scoring_results, list) or len(scoring_results) != expected_count:
        raise SafetyStop("Gate progression requires the complete protected scoring set")
    for result in scoring_results:
        if not isinstance(result, dict):
            raise SafetyStop("Gate progression received an invalid protected score")
        if result.get("adjudication_status") != "RESOLVED":
            raise SafetyStop("Unresolved semantic adjudication blocks gate progression")
        if result.get("gate_progression_permitted") is not True:
            raise SafetyStop("Protected scoring failure blocks gate progression")


class PersistentController:
    def __init__(self, state_root: Path, transport: Transport):
        self.state_root = state_root
        self.transport = transport
        self.state_path = state_root / "experiment_state_v01.json"
        self.lock_path = state_root / "run.lock"

    def create_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            raise SafetyStop("Repeat execution refused: persistent state already exists")
        state = initial_state()
        write_json(self.state_path, state)
        return state

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            raise SafetyStop("Execution state is absent")
        return read_json(self.state_path)

    def acquire(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise SafetyStop("Concurrent execution refused") from exc
        os.write(fd, f"pid={os.getpid()} utc={now()}\n".encode("utf-8"))
        os.close(fd)

    def release(self) -> None:
        self.lock_path.unlink(missing_ok=True)

    def reserve_and_send(
        self,
        slot_id: str,
        execution_day: str,
        reserved_neurons: float,
        payload: dict[str, Any],
        account_id: str,
        token: str,
    ) -> TransportResult:
        state = self.load_state()
        if state["status"] != "ACTIVE":
            raise SafetyStop("Terminal experiment state refuses transmission")
        if slot_id in state["consumed_slots"]:
            raise SafetyStop("Consumed request slot cannot be repeated")
        if state["cumulative_requests"] >= 35:
            raise SafetyStop("Request cap reached")
        if state["cumulative_retries"] != 0:
            raise SafetyStop("Retry counter violates the frozen zero-retry rule")
        if execution_day == "DAY_1_DEVELOPMENT" and state["stage"] != "DEVELOPMENT":
            raise SafetyStop("Development transmission is not permitted in the current stage")
        if execution_day == "DAY_2_D14_CORRECTION" and state["stage"] not in {"D14_REVISION", "D14_RECHECK"}:
            raise SafetyStop("D14 correction transmission is blocked by the development gate")
        if execution_day == "DAY_3_EVALUATION" and state["stage"] not in {"EVALUATION", "REVISION", "RECHECK"}:
            raise SafetyStop("Evaluation-day transmission is blocked by the complete development correction gate")
        if slot_id.startswith("REV__"):
            revision_case_id = slot_id.removeprefix("REV__")
            if execution_day == "DAY_2_D14_CORRECTION" and revision_case_id != "D14":
                raise SafetyStop("Only D14 may use the development-correction slot")
            if execution_day == "DAY_3_EVALUATION" and revision_case_id not in {"E02", "E06", "E12"}:
                raise SafetyStop("Evaluation revision is not in the frozen allocation")
            if revision_case_id in state["revision_case_ids"]:
                raise SafetyStop("A second revision for this case is forbidden")
            if len(state["revision_case_ids"]) >= 4:
                raise SafetyStop("Four-revision experiment cap reached")
            state["revision_case_ids"].append(revision_case_id)
        if slot_id.startswith("RECHECK__"):
            recheck_case_id = slot_id.removeprefix("RECHECK__")
            if execution_day == "DAY_2_D14_CORRECTION" and recheck_case_id != "D14":
                raise SafetyStop("Only D14 may use the development-recheck slot")
            if execution_day == "DAY_3_EVALUATION" and recheck_case_id not in {"E02", "E06", "E12"}:
                raise SafetyStop("Evaluation recheck is not in the frozen allocation")
        if execution_day == "DAY_1_DEVELOPMENT" and state["day_reservations"][execution_day] + reserved_neurons > 8252.693280 + 1e-9:
            raise SafetyStop("Day-1 reservation limit would be exceeded")
        if execution_day == "DAY_2_D14_CORRECTION" and state["day_reservations"][execution_day] + reserved_neurons > 702.617440 + 1e-9:
            raise SafetyStop("Day-2 reservation limit would be exceeded")
        if execution_day == "DAY_3_EVALUATION" and state["day_reservations"][execution_day] + reserved_neurons > 8710.006944 + 1e-9:
            raise SafetyStop("Day-3 reservation limit would be exceeded")

        reservation = {
            "slot_id": slot_id,
            "execution_day": execution_day,
            "reserved_neurons": reserved_neurons,
            "reserved_at_utc": now(),
            "status": "CONSUMED_BEFORE_TRANSMISSION",
        }
        state["consumed_slots"].append(slot_id)
        state["reservations"].append(reservation)
        state["cumulative_requests"] += 1
        state["day_reservations"][execution_day] += reserved_neurons
        write_json(self.state_path, state)

        result = self.transport.send(payload, account_id, token)
        capture = {
            "slot_id": slot_id,
            "captured_at_utc": now(),
            "http_status": result.status,
            "safe_headers": result.headers,
            "transport_error": result.error,
            "uncertain": result.uncertain,
            "capture_truncated": result.truncated,
            "sanitised_body": sanitize_body(result.body, account_id, token),
            "recognised_usage": extract_recognised_usage(result.body),
        }
        write_json(self.state_root / "responses" / f"{slot_id}.json", capture)
        return result

    def record_development_gate(self, passed: bool, scoring_results: Any = None) -> None:
        state = self.load_state()
        if state["stage"] != "DEVELOPMENT":
            raise SafetyStop("Development gate cannot be recorded in the current stage")
        if passed:
            require_scoring_gate_ready(scoring_results, 15)
            development_slots = [value for value in state["consumed_slots"] if value.startswith("DEV_CHECK__")]
            if len(development_slots) != 15:
                raise SafetyStop("Development PASS requires all 15 consumed checker slots")
            state["stage"] = "WAITING_UTC_DAY_2_D14_CORRECTION"
        else:
            state["stage"] = "FAILED_GATE"
            state["status"] = "FAILED_GATE"
        write_json(self.state_path, state)

    def start_day_2(self) -> None:
        state = self.load_state()
        if state["stage"] != "WAITING_UTC_DAY_2_D14_CORRECTION" or state["status"] != "ACTIVE":
            raise SafetyStop("Day 2 is blocked until the initial development coverage gate passes")
        state["stage"] = "D14_REVISION"
        write_json(self.state_path, state)

    def begin_development_recheck(self) -> None:
        state = self.load_state()
        if state["stage"] != "D14_REVISION":
            raise SafetyStop("D14 recheck cannot begin before its sole revision")
        if "REV__D14" not in state["consumed_slots"]:
            raise SafetyStop("D14 recheck requires the consumed revision slot")
        state["stage"] = "D14_RECHECK"
        write_json(self.state_path, state)

    def record_development_correction_gate(self, passed: bool, scoring_results: Any = None) -> None:
        state = self.load_state()
        if state["stage"] != "D14_RECHECK":
            raise SafetyStop("D14 correction gate cannot be recorded before complete recheck")
        if passed:
            require_scoring_gate_ready(scoring_results, 1)
            if "RECHECK__D14" not in state["consumed_slots"]:
                raise SafetyStop("D14 correction PASS requires the consumed complete-recheck slot")
            state["stage"] = "WAITING_UTC_DAY_3_EVALUATION"
        else:
            state["stage"] = "FAILED_GATE"
            state["status"] = "FAILED_GATE"
        write_json(self.state_path, state)

    def start_day_3(self) -> None:
        state = self.load_state()
        if state["stage"] != "WAITING_UTC_DAY_3_EVALUATION" or state["status"] != "ACTIVE":
            raise SafetyStop("Day 3 is blocked until D14's corrected summary passes complete rechecking")
        state["stage"] = "EVALUATION"
        write_json(self.state_path, state)

    def begin_revision_stage(self, scoring_results: Any = None) -> None:
        state = self.load_state()
        if state["stage"] != "EVALUATION":
            raise SafetyStop("Revision stage cannot begin before initial evaluation")
        evaluation_slots = [value for value in state["consumed_slots"] if value.startswith("EVAL_CHECK__")]
        if len(evaluation_slots) != 12:
            raise SafetyStop("Revision stage requires all 12 initial evaluation slots")
        require_scoring_gate_ready(scoring_results, 12)
        state["stage"] = "REVISION"
        write_json(self.state_path, state)

    def begin_recheck_stage(self) -> None:
        state = self.load_state()
        if state["stage"] != "REVISION":
            raise SafetyStop("Recheck stage cannot begin before revisions")
        state["stage"] = "RECHECK"
        write_json(self.state_path, state)

    def mark_terminal(self, status: str) -> None:
        if status not in {"COMPLETE", "FAILED_GATE", "SAFETY_STOP"}:
            raise ValueError("Unknown terminal status")
        state = self.load_state()
        state["status"] = status
        state["terminal_at_utc"] = now()
        write_json(self.state_path, state)
