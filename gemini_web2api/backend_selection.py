"""Backend selection helpers.

Selection is based only on the configured mode and local authentication format.
No credential values are returned, logged, or exposed.
"""
from __future__ import annotations

import json
import os


def cookie_auth_kind(cookie_file: str | None) -> str:
    """Return ``legacy``, ``modern``, or ``unknown`` from cookie names only."""
    if not cookie_file or not os.path.exists(cookie_file):
        return "unknown"

    try:
        with open(cookie_file, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()

        if not raw:
            return "unknown"

        names: set[str] = set()

        if raw.startswith("{"):
            data = json.loads(raw)
            if not isinstance(data, dict):
                return "unknown"

            cookie_string = str(data.get("cookie", "") or "")
            for item in cookie_string.split(";"):
                if "=" in item:
                    names.add(item.split("=", 1)[0].strip())

            names.update(
                key.strip()
                for key in data
                if isinstance(key, str)
            )
        else:
            for item in raw.split(";"):
                if "=" in item:
                    names.add(item.split("=", 1)[0].strip())

        if "__Secure-1PSID" in names or "__Secure-1PSIDTS" in names:
            return "modern"

        legacy_names = {
            "SID",
            "HSID",
            "SSID",
            "APISID",
            "SAPISID",
        }
        if names & legacy_names:
            return "legacy"

    except (OSError, ValueError, TypeError):
        return "unknown"

    return "unknown"


def effective_backend(configured: str, cookie_file: str | None) -> str:
    """Resolve the transport without runtime-error fallback."""
    backend = str(configured or "modern").lower()

    if backend in {"modern", "legacy"}:
        return backend

    if backend != "auto":
        raise ValueError(f"unsupported upstream_backend: {backend}")

    detected = cookie_auth_kind(cookie_file)

    if detected in {"legacy", "modern"}:
        return detected

    raise RuntimeError(
        "auto backend could not identify a supported Gemini authentication format"
    )
