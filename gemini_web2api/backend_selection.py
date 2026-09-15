"""Backend selection helpers.

Selection is based only on the configured mode and local authentication format.
No credential values are returned, logged, or exposed.
"""
from __future__ import annotations

import json
import os


def _cookie_names(raw: str) -> set[str]:
    """Extract cookie names from common browser-export formats."""
    names: set[str] = set()
    raw = raw.strip()
    if not raw:
        return names

    if raw.startswith("{") or raw.startswith("["):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None

        if isinstance(data, dict):
            cookie_string = str(data.get("cookie", "") or "")
            for item in cookie_string.split(";"):
                if "=" in item:
                    names.add(item.split("=", 1)[0].strip())
            names.update(key for key in data if isinstance(key, str))
            return names

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("name"):
                    names.add(str(item["name"]).strip())
            return names

    for item in raw.split(";"):
        if "=" in item:
            names.add(item.split("=", 1)[0].strip())

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 7 and fields[5].strip():
            names.add(fields[5].strip())

    return names


def cookie_auth_kind(cookie_file: str | None) -> str:
    """Return ``legacy``, ``modern``, or ``unknown`` from cookie names only."""
    if not cookie_file or not os.path.exists(cookie_file):
        return "unknown"

    try:
        with open(cookie_file, "r", encoding="utf-8") as handle:
            names = _cookie_names(handle.read())

        if "__Secure-1PSID" in names or "__Secure-1PSIDTS" in names:
            return "modern"

        if names & {"SID", "HSID", "SSID", "APISID", "SAPISID"}:
            return "legacy"
    except (OSError, ValueError, TypeError):
        return "unknown"

    return "unknown"


def effective_backend(configured: str, cookie_file: str | None) -> str:
    """Resolve transport while preserving the original zero-config flow."""
    backend = str(configured or "auto").lower()
    if backend in {"modern", "legacy"}:
        return backend
    if backend != "auto":
        raise ValueError(f"unsupported upstream_backend: {backend}")

    # Secure PSID cookies identify the account-aware gemini-webapi transport.
    # Everything else intentionally remains on the original StreamGenerate
    # transport, including a completely unauthenticated startup.
    return "modern" if cookie_auth_kind(cookie_file) == "modern" else "legacy"
