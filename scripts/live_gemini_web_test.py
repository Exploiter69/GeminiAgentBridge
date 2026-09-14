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
from gemini_web2api.gemini import generate, generate_stream
from gemini_web2api.models import resolve_model


def _select_model(requested: str | None, backend: str) -> tuple[str, object]:
    if requested:
        name = requested
    elif backend == "legacy":
        name = CONFIG.get("default_model", "gemini-3.6-flash")
    else:
        from gemini_web2api.modern import _BACKEND
        models = _BACKEND.list_models()
        if not models:
            raise RuntimeError("Gemini Web account returned no models")
        from gemini_web2api.model_catalog import model_name
        name = model_name(models[0])

    requested_name, resolved_id, think_mode, error, extra = resolve_model(name)
    if error:
        raise RuntimeError(error)
    return name, (resolved_id, think_mode, extra)


def _require_marker(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise RuntimeError(
            f"{label} response did not contain the requested success marker"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookie-file", required=True)
    parser.add_argument("--prompt", default="Reply exactly LIVE_GEMINI_WEB_OK")
    parser.add_argument(
        "--model",
        default=None,
        help="Model name/alias; omit to use the account default for modern or bridge default for legacy",
    )
    parser.add_argument(
        "--backend",
        choices=("legacy", "modern", "auto"),
        default="modern",
        help="Gemini Web transport to verify",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Also verify the maintained streaming transport",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.cookie_file):
        print("cookie file does not exist", file=sys.stderr)
        return 2

    CONFIG["upstream_backend"] = args.backend
    CONFIG["cookie_file"] = args.cookie_file

    marker = "LIVE_GEMINI_WEB_OK"

    try:
        model, resolved = _select_model(args.model, args.backend)
        resolved_id, think_mode, extra = resolved

        request = BackendRequest(
            prompt=args.prompt,
            model=resolved_id,
            think_mode=think_mode,
            provider_options=extra or {},
        )

        if args.backend == "legacy":
            response_text = generate(
                args.prompt,
                resolved_id,
                think_mode=think_mode,
                extra_fields=extra,
            )
        else:
            from gemini_web2api.modern import _BACKEND
            response = _BACKEND.generate_response(
                BackendRequest(prompt=args.prompt, model=model)
            )
            response_text = response.text

        _require_marker(response_text, marker, "live")
        print("LIVE_GEMINI_WEB_OK")
        print(f"BACKEND={args.backend}")
        print(f"MODEL_RESOLVED={model}")

        if args.backend != "legacy":
            try:
                print(f"THOUGHTS_PRESENT={bool(response.thoughts.strip())}")
            except UnboundLocalError:
                pass
        else:
            print("THOUGHTS_PRESENT=False")

        if args.stream:
            if args.backend == "legacy":
                streamed = "".join(
                    generate_stream(
                        args.prompt,
                        resolved_id,
                        think_mode=think_mode,
                        extra_fields=extra,
                    )
                )
            else:
                from gemini_web2api.modern import _BACKEND
                streamed = "".join(
                    _BACKEND.generate_stream_response(
                        BackendRequest(
                            prompt=args.prompt,
                            model=model,
                            stream=True,
                        )
                    )
                )

            _require_marker(streamed, marker, "live stream")
            print("LIVE_GEMINI_WEB_STREAM_OK")

        return 0

    except Exception as exc:
        print(
            f"LIVE_GEMINI_WEB_FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if args.backend != "legacy":
            try:
                from gemini_web2api.modern import _BACKEND
                _BACKEND.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
