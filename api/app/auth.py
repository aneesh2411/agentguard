"""Optional API-key auth.

Local prototype security model (NOT production-secure):
- Read endpoints (GET /, /summary, /runs, /alerts, /budgets) require
  X-API-Key only when AGENTGUARD_READ_KEY is set; unset means local dev
  mode with open reads, so the server must be bound to loopback (the
  default in the README quick start) and never exposed.
- Write endpoints (POST /runs, /budgets) require X-API-Key only when
  AGENTGUARD_API_KEY is set; unset means local dev mode with open writes.
- The LiteLLM receiver FAILS CLOSED: it answers 503 when AGENTGUARD_API_KEY
  is not set, because a receiver exists to accept data pushed from outside
  this process and must never sit open.
"""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def _configured_key() -> str | None:
    return os.environ.get("AGENTGUARD_API_KEY")


def require_write_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = _configured_key()
    if expected is None:
        return  # local dev mode
    _check(x_api_key, expected)


def require_read_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("AGENTGUARD_READ_KEY")
    if expected is None:
        return  # local dev mode
    _check(x_api_key, expected)


def require_receiver_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = _configured_key()
    if expected is None:
        raise HTTPException(status_code=503,
                            detail="receiver disabled: set AGENTGUARD_API_KEY")
    _check(x_api_key, expected)


def _check(provided: str | None, expected: str) -> None:
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401,
                            detail="invalid or missing API key")
