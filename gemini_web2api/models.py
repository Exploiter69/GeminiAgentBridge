"""Model aliases plus backend-aware resolution.

The modern gemini-webapi transport resolves model names against the authenticated
account at runtime. The legacy StreamGenerate transport still requires its
numeric mode/think slots, so those values remain isolated to that backend.
"""

from .config import CONFIG
from .backend_selection import effective_backend


MODELS = {
    "gemini-3.7-flash": {
        "mode": 1, "think": 4,
        "desc": "Compatibility alias; resolved by the authenticated Gemini Web account",
    },
    "gemini-3.6-flash": {
        "mode": 1, "think": 4,
        "desc": "Compatibility alias; resolved by the authenticated Gemini Web account",
    },
    "gemini-3.5-flash": {
        "mode": 1, "think": 4,
        "desc": "Compatibility alias; resolved by the authenticated Gemini Web account",
    },
    "gemini-3.5-flash-thinking": {
        "mode": 2, "think": 0,
        "desc": "Thinking-model compatibility alias; resolved by the authenticated account",
    },
    "gemini-3.1-pro": {
        "mode": 3, "think": 4,
        "desc": "Pro compatibility alias; resolved by the authenticated Gemini Web account",
    },
    "gemini-3.1-pro-enhanced": {
        "mode": 3, "think": 4,
        "extra": {31: 2, 80: 3},
        "desc": "Legacy enhanced Pro compatibility alias; not a fabricated modern capability",
    },
    "gemini-auto": {
        "mode": 4, "think": 4,
        "desc": "Automatic model-selection compatibility alias",
    },
    "gemini-3.5-flash-thinking-lite": {
        "mode": 5, "think": 0,
        "desc": "Adaptive-thinking compatibility alias",
    },
    "gemini-flash-lite": {
        "mode": 6, "think": 4,
        "desc": "Lightweight compatibility alias; resolved by the authenticated account",
    },
}


def resolve_model(model_name: str, default: str = "gemini-3.6-flash"):
    """Resolve a model without silently collapsing distinct user intent."""
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
        str(CONFIG.get("upstream_backend", "modern")).lower(),
        CONFIG.get("cookie_file"),
    )

    cfg = MODELS.get(requested)
    if not cfg:
        # Modern Gemini Web can resolve account-discovered model names directly.
        # Legacy mode cannot, so reject unknown names there rather than silently
        # routing them to an unrelated model.
        if backend != "legacy":
            return requested, requested, None, None, None
        return None, None, None, f"unknown model: {requested}", None

    mode_id = cfg["mode"]
    if backend == "legacy":
        think_mode = think_override if think_override is not None else cfg["think"]
        extra = cfg.get("extra")
    else:
        if think_override not in (None, 0):
            return None, None, None, (
                "numeric @think= overrides are only supported by the legacy backend; "
                "select a thinking-capable model instead"
            ), None
        think_mode = None
        extra = None

    # model_id is kept as the legacy numeric mode for compatibility. Modern
    # callers receive the actual requested model name in the same position.
    resolved_id = mode_id if backend == "legacy" else requested
    return requested, resolved_id, think_mode, None, extra
