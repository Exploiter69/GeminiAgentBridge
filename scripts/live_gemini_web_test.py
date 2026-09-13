#!/usr/bin/env python3
"""Run one authenticated live Gemini Web transport smoke test.

The cookie path is supplied locally and is never printed. This is deliberately
not part of CI because it requires a real Gemini Web session.
"""
from __future__ import annotations

import argparse
import os
import sys

from gemini_web2api.config import CONFIG
from gemini_web2api.modern import _BACKEND


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookie-file", required=True)
    parser.add_argument("--prompt", default="Reply exactly LIVE_GEMINI_WEB_OK")
    parser.add_argument("--model-id", type=int, default=1)
    args = parser.parse_args()

    if not os.path.isfile(args.cookie_file):
        print("cookie file does not exist", file=sys.stderr)
        return 2

    CONFIG["upstream_backend"] = "modern"
    CONFIG["cookie_file"] = args.cookie_file
    try:
        text = _BACKEND.generate(args.prompt, args.model_id)
        ok = bool(text.strip())
        print("LIVE_GEMINI_WEB_OK" if ok else "LIVE_GEMINI_WEB_EMPTY")
        return 0 if ok else 1
    except Exception as exc:
        print(f"LIVE_GEMINI_WEB_FAILED: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        _BACKEND.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
