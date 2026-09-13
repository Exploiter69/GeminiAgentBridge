"""Configuration management."""
import json
import os

DEFAULT_CONFIG = {
    "port": 8081,
    # Local-only by default. Remote binding requires explicit API keys.
    "host": "127.0.0.1",
    "retry_attempts": 3,
    "retry_delay_sec": 2,
    "retry_backoff_multiplier": 2.0,
    "retry_max_delay_sec": 30.0,
    "request_timeout_sec": 180,
    "upstream_backend": "modern",
    "gemini_bl": "boq_assistant-bard-web-server_20260716.08_p0",
    "auth_user": None,
    "xsrf_token": None,
    "default_model": "gemini-3.6-flash",
    "log_requests": True,
    "cookie_file": None,
    "proxy": None,
    "api_keys": [],
    "temporary_chats": False,
    "prompt_soft_budget_chars": 0,
    "tool_schema_budget_chars": 30000,
    "tool_repair_attempts": 1,
    "planner_enabled": False,
    # HTTP/resource safety limits.
    "max_request_body_bytes": 4 * 1024 * 1024,
    "max_image_bytes": 10 * 1024 * 1024,
    "max_image_redirects": 3,
}

CONFIG = dict(DEFAULT_CONFIG)


def load_config(path: str = None):
    """Load config from JSON file."""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            CONFIG.update(json.load(f))
    return CONFIG


def find_config():
    """Search for config file in standard locations."""
    for p in ["./config.json", os.path.expanduser("~/.config/gemini-web2api/config.json")]:
        if os.path.exists(p):
            return p
    return None
