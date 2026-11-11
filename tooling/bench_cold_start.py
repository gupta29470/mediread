#!/usr/bin/env python
"""Measure a true cold start: unload, first request, capture load/total time."""

from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:11434"


def main() -> int:
    model = sys.argv[1]
    payload = {
        "model": model,
        "prompt": "Reply with the single word ok.",
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": 2},
    }
    started = time.perf_counter()
    request = urllib.request.Request(
        f"{BASE}/api/generate", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read())
    wall_ms = (time.perf_counter() - started) * 1000
    print(json.dumps({
        "model": model,
        "cold_wall_ms": round(wall_ms, 1),
        "load_ms": round(body.get("load_duration", 0) / 1e6, 1),
        "total_ms": round(body.get("total_duration", 0) / 1e6, 1),
        "prompt_tokens": body.get("prompt_eval_count"),
        "output_tokens": body.get("eval_count"),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
