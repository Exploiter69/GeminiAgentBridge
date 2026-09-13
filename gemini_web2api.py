#!/usr/bin/env python3
"""Compatibility launcher for GeminiAgentBridge.

The maintained implementation lives in the ``gemini_web2api`` package. This
file is intentionally tiny so the historical command continues to work while
never starting the retired direct StreamGenerate server.
"""

from gemini_web2api.__main__ import main


if __name__ == "__main__":
    main()
