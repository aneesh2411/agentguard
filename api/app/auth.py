"""Optional API-key auth for mutating endpoints.

Set AGENTGUARD_API_KEY to require an X-API-Key header on writes
(POST /runs, /budgets, /integrations/*). Unset means local dev mode:
writes are open. Read endpoints stay open either way for now.
"""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def require_write_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("AGENTGUARD_API_KEY")
    if expected is None:
        return  # local dev mode
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
