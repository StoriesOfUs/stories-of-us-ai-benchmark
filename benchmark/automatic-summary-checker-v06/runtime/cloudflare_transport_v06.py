#!/usr/bin/env python3
"""Single-attempt direct Workers AI transport with bounded safe capture."""
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


def _read_bounded(stream: BinaryIO) -> tuple[bytes, bool]:
    observed = stream.read(CAPTURE_LIMIT_BYTES + 1)
    return observed[:CAPTURE_LIMIT_BYTES], len(observed) > CAPTURE_LIMIT_BYTES


class CloudflareChatTransport:
    """One direct account Workers AI Chat Completions call; no retry/fallback."""

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
        raise TransportStop("Secret redaction failed before persistence")
    return text
