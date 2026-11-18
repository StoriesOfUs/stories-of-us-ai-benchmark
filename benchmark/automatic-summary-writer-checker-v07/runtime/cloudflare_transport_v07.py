#!/usr/bin/env python3
"""Single-attempt direct Workers AI transport for the V07 pilot."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import socket
import time
from typing import Any, BinaryIO
import urllib.error
import urllib.request


ACCOUNT_RE = re.compile(r"^[0-9a-fA-F]{32}$")
CAPTURE_LIMIT_BYTES = 1_048_576
READ_CHUNK_BYTES = 64 * 1024
SOCKET_TIMEOUT_SECONDS = 180
SAFE_HEADERS = {"content-type", "cf-ray", "date", "server"}


class TransportStop(RuntimeError):
    pass


def validate_credentials(account_id: str, token: str) -> None:
    if ACCOUNT_RE.fullmatch(account_id) is None:
        raise TransportStop("Local Account ID validation failed before state creation")
    if not token:
        raise TransportStop("Local token validation failed before state creation")


@dataclass
class TransportResult:
    status: int | None
    body: bytes
    headers: dict[str, str]
    elapsed_seconds: float
    error: str | None = None
    uncertain: bool = False
    truncated: bool = False
    timeout_phase: str | None = None
    response_started: bool = False
    timeout_seconds: int = SOCKET_TIMEOUT_SECONDS


class BodyReadTimeout(TimeoutError):
    def __init__(self, body: bytes, truncated: bool):
        super().__init__("Response body read timed out")
        self.body = body
        self.truncated = truncated


def _read_bounded(stream: BinaryIO) -> tuple[bytes, bool]:
    observed = bytearray()
    try:
        while len(observed) <= CAPTURE_LIMIT_BYTES:
            remaining = CAPTURE_LIMIT_BYTES + 1 - len(observed)
            chunk = stream.read(min(READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            observed.extend(chunk)
    except (TimeoutError, socket.timeout) as exc:
        raise BodyReadTimeout(
            bytes(observed[:CAPTURE_LIMIT_BYTES]),
            len(observed) > CAPTURE_LIMIT_BYTES,
        ) from exc
    return bytes(observed[:CAPTURE_LIMIT_BYTES]), len(observed) > CAPTURE_LIMIT_BYTES


class CloudflareChatTransport:
    """One direct account Workers AI chat-completion call; no retry/fallback."""

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
            with urllib.request.urlopen(request, timeout=SOCKET_TIMEOUT_SECONDS) as response:
                headers = {k.lower(): v for k, v in response.headers.items() if k.lower() in SAFE_HEADERS}
                try:
                    body, truncated = _read_bounded(response)
                except BodyReadTimeout as exc:
                    return TransportResult(
                        response.status, exc.body, headers, time.monotonic() - started,
                        error="TIMEOUT", uncertain=True, truncated=exc.truncated,
                        timeout_phase="BODY_READ", response_started=True,
                    )
                return TransportResult(
                    response.status, body, headers, time.monotonic() - started,
                    truncated=truncated, response_started=True,
                )
        except urllib.error.HTTPError as exc:
            headers = {k.lower(): v for k, v in exc.headers.items() if k.lower() in SAFE_HEADERS}
            try:
                body, truncated = _read_bounded(exc)
            except BodyReadTimeout as read_exc:
                return TransportResult(
                    exc.code, read_exc.body, headers, time.monotonic() - started,
                    error="TIMEOUT", uncertain=True, truncated=read_exc.truncated,
                    timeout_phase="BODY_READ", response_started=True,
                )
            return TransportResult(
                exc.code, body, headers, time.monotonic() - started,
                error="HTTP_ERROR", truncated=truncated, response_started=True,
            )
        except (TimeoutError, socket.timeout):
            return TransportResult(
                None, b"", {}, time.monotonic() - started,
                error="TIMEOUT", uncertain=True, timeout_phase="OPEN_OR_HEADERS",
            )
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return TransportResult(
                    None, b"", {}, time.monotonic() - started,
                    error="TIMEOUT", uncertain=True, timeout_phase="OPEN_OR_HEADERS",
                )
            return TransportResult(None, b"", {}, time.monotonic() - started, error="NETWORK_ERROR", uncertain=True)
        except OSError:
            return TransportResult(None, b"", {}, time.monotonic() - started, error="NETWORK_ERROR", uncertain=True)


def sanitize_body(body: bytes, account_id: str, token: str) -> str:
    text = body.decode("utf-8", errors="replace")
    for secret in (account_id, token):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{4,}", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(authorization[\"'\s:=]+)([^\s,}\]]+)", r"\1[REDACTED]", text)
    if any(secret and secret in text for secret in (account_id, token)):
        raise TransportStop("Secret redaction failed before persistence")
    return text
