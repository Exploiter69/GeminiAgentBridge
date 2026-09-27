"""Model aliases plus backend-aware resolution."""

from .config import CONFIG
from .backend_selection import effective_backend


MODELS = {
    "gemini-3.7-flash": {"mode": 1, "think": 4, "modern": "flash", "desc": "Gemini Web Flash compatibility alias"},
    "gemini-3.6-flash": {"mode": 1, "think": 4, "modern": "flash", "desc": "Gemini Web Flash compatibility alias"},
    "gemini-3.5-flash": {"mode": 1, "think": 4, "modern": "flash", "desc": "Gemini Web Flash compatibility alias"},
    "gemini-3.5-flash-thinking": {"mode": 2, "think": 0, "modern": None, "desc": "Legacy thinking-mode compatibility alias"},
    "gemini-3.1-pro": {"mode": 3, "think": 4, "modern": "pro", "desc": "Gemini Web Pro compatibility alias"},
    "gemini-3.1-pro-enhanced": {"mode": 3, "think": 4, "modern": "pro", "extra": {31: 2, 80: 3}, "desc": "Legacy enhanced Pro compatibility alias"},
    "gemini-auto": {"mode": 4, "think": 4, "modern": None, "desc": "Automatic model-selection compatibility alias"},
    "gemini-3.5-flash-thinking-lite": {"mode": 5, "think": 0, "modern": None, "desc": "Legacy adaptive-thinking compatibility alias"},
    "gemini-flash-lite": {"mode": 6, "think": 4, "modern": "flash-lite", "desc": "Gemini Web Flash Lite compatibility alias"},
}


def resolve_model(model_name: str, default: str = "gemini-3.6-flash"):
    """Resolve a requested public model without fabricating modern semantics."""
    if not isinstance(model_name, str) or not model_name.strip():
        return None, None, None, "model must be a non-empty string", None

    requested = model_name.strip()
    think_override = None
    if "@think=" in requested:
        requested, think_str = requested.rsplit("@think=", 1)
        try:
            think_override = int(think_str)
        except ValueError:
            return None, None, None, f"invalid think level: {think_str}", None
        if think_override < 0:
            return None, None, None, "think level must be non-negative", None

    backend = effective_backend(
        str(CONFIG.get("upstream_backend", "auto")).lower(),
        CONFIG.get("cookie_file"),
    )

    cfg = MODELS.get(requested)
    if not cfg:
        if backend == "legacy":
            return None, None, None, f"unknown model: {requested}", None
        return requested, requested, None, None, None

    if backend == "legacy":
        think_mode = think_override if think_override is not None else cfg["think"]
        return requested, cfg["mode"], think_mode, None, cfg.get("extra")

    # Modern gemini-webapi discovers the account's actual tier/model headers.
    # Its stable aliases are currently flash, pro and flash-lite. Do not map
    # legacy-only thinking modes to a different model and silently change user
    # intent; reject them instead.
    modern_name = cfg.get("modern")
    if modern_name is None:
        return None, None, None, (
            f"model {requested} uses legacy Gemini Web semantics and is not "
            "available through the account-aware modern backend"
        ), None
    if think_override not in (None, 0):
        return None, None, None, (
            "numeric @think= overrides are only supported by the legacy backend; "
            "select a thinking-capable account model instead"
        ), None

    return requested, modern_name, None, None, None
