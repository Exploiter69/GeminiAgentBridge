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
    report = run_benchmark(5)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.all_pass and all(
        metric == 1.0 for metric in (report.pass_at_1, report.pass_at_3, report.pass_pow_3, report.pass_pow_5)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
