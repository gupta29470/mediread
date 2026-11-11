"""Local Ollama client with streaming, timing and peak-RSS capture.

Only ``http://127.0.0.1:<port>`` is allowed. The client refuses any non-loopback
base URL, so an evaluation run cannot silently become cloud inference.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

DEFAULT_BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if DEFAULT_BASE.startswith("0.0.0.0"):
    DEFAULT_BASE = DEFAULT_BASE.replace("0.0.0.0", "127.0.0.1")

GENERATION_OPTIONS = {
    "temperature": 0.0,
    "seed": 42,
    "top_p": 1.0,
    "top_k": 1,
    "repeat_penalty": 1.0,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    "num_ctx": 8192,
    "num_predict": 700,
}


def _assert_local(base_url: str) -> None:
    if not any(host in base_url for host in ("127.0.0.1", "localhost", "[::1]")):
        raise ValueError(f"refusing non-local Ollama URL: {base_url}")


@dataclass
class GenerationResult:
    text: str
    ttft_ms: float | None
    total_ms: float
    prompt_eval_count: int | None
    eval_count: int | None
    eval_duration_ns: int | None
    prompt_eval_duration_ns: int | None
    load_duration_ns: int | None
    peak_rss_mb: float | None
    error: str | None = None
    raw_chunks: int = 0

    @property
    def tokens_per_second(self) -> float | None:
        if self.eval_count and self.eval_duration_ns:
            return round(self.eval_count / (self.eval_duration_ns / 1e9), 2)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ttft_ms": round(self.ttft_ms, 1) if self.ttft_ms is not None else None,
            "total_ms": round(self.total_ms, 1),
            "prompt_eval_count": self.prompt_eval_count,
            "eval_count": self.eval_count,
            "tokens_per_second": self.tokens_per_second,
            "peak_rss_mb": round(self.peak_rss_mb, 1) if self.peak_rss_mb else None,
            "chunks": self.raw_chunks,
            "error": self.error,
        }


class _RSSSampler:
    """Sample the resident size of the loaded Ollama runner process.

    ``ps``/``pgrep`` are blocked in some sandboxes, so this uses psutil. The
    runner appears as ``llama-server`` on current Ollama builds and as
    ``ollama runner`` on older ones; both are recognised.
    """

    def __init__(self, interval: float = 0.4) -> None:
        self.interval = interval
        self.peak_kb = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        try:
            import psutil  # noqa: F401
        except Exception:
            return self
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        import psutil

        while not self._stop.is_set():
            try:
                for proc in psutil.process_iter(["name", "cmdline", "memory_info"]):
                    try:
                        name = (proc.info["name"] or "").lower()
                        cmd = " ".join(proc.info["cmdline"] or []).lower()
                        if "llama-server" not in name and "ollama runner" not in cmd:
                            continue
                        rss = proc.info["memory_info"].rss
                        self.peak_kb = max(self.peak_kb, int(rss / 1024))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception:
                pass
            self._stop.wait(self.interval)


def chat(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict,
    base_url: str = DEFAULT_BASE,
    options: dict | None = None,
    timeout: float = 600.0,
) -> GenerationResult:
    _assert_local(base_url)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
        "think": False,
        "keep_alive": "15m",
        "format": schema,
        "options": {**GENERATION_OPTIONS, **(options or {})},
    }
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    ttft = None
    parts: list[str] = []
    meta: dict[str, Any] = {}
    chunks = 0
    error = None

    with _RSSSampler() as sampler:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for line in response:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        error = str(chunk["error"])
                        break
                    content = chunk.get("message", {}).get("content") or ""
                    if content:
                        if ttft is None:
                            ttft = (time.perf_counter() - started) * 1000.0
                        parts.append(content)
                    chunks += 1
                    if chunk.get("done"):
                        meta = chunk
                        break
        except urllib.error.HTTPError as exc:
            error = f"HTTP {exc.code}: {exc.read()[:300]!r}"
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

    total_ms = (time.perf_counter() - started) * 1000.0
    return GenerationResult(
        text="".join(parts),
        ttft_ms=ttft,
        total_ms=total_ms,
        prompt_eval_count=meta.get("prompt_eval_count"),
        eval_count=meta.get("eval_count"),
        eval_duration_ns=meta.get("eval_duration"),
        prompt_eval_duration_ns=meta.get("prompt_eval_duration"),
        load_duration_ns=meta.get("load_duration"),
        peak_rss_mb=(sampler.peak_kb / 1024.0) if sampler.peak_kb else None,
        error=error,
        raw_chunks=chunks,
    )


def runtime_metadata(base_url: str = DEFAULT_BASE) -> dict[str, Any]:
    """Ollama version plus exact model digests, sizes and quantization."""
    _assert_local(base_url)
    with urllib.request.urlopen(f"{base_url}/api/version", timeout=10) as response:
        version = json.loads(response.read())["version"]
    with urllib.request.urlopen(f"{base_url}/api/tags", timeout=10) as response:
        tags = json.loads(response.read())["models"]
    models = {}
    for entry in tags:
        models[entry["name"]] = {
            "digest": entry["digest"],
            "size_bytes": entry["size"],
            "size_gb": round(entry["size"] / 1e9, 2),
            **entry.get("details", {}),
        }
    return {"ollama_version": version, "base_url": base_url, "models": models}
