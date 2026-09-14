#!/usr/bin/env python3
"""Run an authenticated live Gemini Web transport smoke test.

The cookie path is supplied locally and is never printed. This is deliberately
not part of CI because it requires a real Gemini Web session.
"""
from __future__ import annotations

import argparse
import os
import sys

from gemini_web2api.backend import BackendRequest
from gemini_web2api.config import CONFIG
from gemini_web2api.modern import _BACKEND


def _model_name(value) -> str:
    return str(getattr(value, "name", None) or getattr(value, "id", None) or value)


def _select_model(requested: str | None) -> str:
    if requested:
        return requested
    models = _BACKEND.list_models()
    if not models:
        raise RuntimeError("Gemini Web account returned no models")
    return _model_name(models[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookie-file", required=True)
    parser.add_argument("--prompt", default="Reply exactly LIVE_GEMINI_WEB_OK")
    parser.add_argument("--model", default=None, help="Account-visible model name; omit to use the first discovered model")
    parser.add_argument("--stream", action="store_true", help="Also verify the maintained streaming transport")
    args = parser.parse_args()

    if not os.path.isfile(args.cookie_file):
        print("cookie file does not exist", file=sys.stderr)
        return 2

    CONFIG["upstream_backend"] = "modern"
    CONFIG["cookie_file"] = args.cookie_file
    try:
        model = _select_model(args.model)
        request = BackendRequest(prompt=args.prompt, model=model)
        response = _BACKEND.generate_response(request)
        if not response.text.strip():
            print("LIVE_GEMINI_WEB_EMPTY", file=sys.stderr)
            return 1
        print("LIVE_GEMINI_WEB_OK")
        print(f"MODEL_RESOLVED={model}")
        print(f"THOUGHTS_PRESENT={bool(response.thoughts.strip())}")

        if args.stream:
            streamed = "".join(_BACKEND.generate_stream_response(
                BackendRequest(prompt=args.prompt, model=model, stream=True)
            ))
            if not streamed.strip():
                print("LIVE_GEMINI_WEB_STREAM_EMPTY", file=sys.stderr)
                return 1
            print("LIVE_GEMINI_WEB_STREAM_OK")
        return 0
    except Exception as exc:
        print(f"LIVE_GEMINI_WEB_FAILED: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        _BACKEND.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
