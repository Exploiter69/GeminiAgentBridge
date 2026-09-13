#!/usr/bin/env python3
"""Run the permanent Phase 9 trajectory reliability benchmark."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gemini_web2api.trajectory import run_benchmark


def main() -> int:
    report = run_benchmark(3)
    payload = report.as_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.all_pass and report.pass_at_1 == 1.0 and report.pass_at_3 == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
