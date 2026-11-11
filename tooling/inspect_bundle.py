"""Inspect a .litertlm bundle: embedded tokenizer, metadata, and comparison to source.

    python tooling/inspect_bundle.py bundle.litertlm merged-fp16/tokenizer.json
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import zlib
from pathlib import Path


def unpack(bundle: Path, out: Path) -> None:
    import shutil, subprocess
    executable = shutil.which("litert-lm") or str(Path(sys.executable).with_name("litert-lm"))
    subprocess.run([executable, "unpack", str(bundle), "--output-dir", str(out),
                    "--allow-overwrite"], check=True)


def decode_tokenizer(section: Path) -> bytes | None:
    raw = section.read_bytes()
    for skip in (8, 4, 0):
        for wbits in (15, 31, -15):
            try:
                data = zlib.decompress(raw[skip:], wbits)
                if data.startswith(b"{"):
                    return data
            except zlib.error:
                continue
    return None


def main() -> int:
    bundle = Path(sys.argv[1])
    source = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "unpacked"
        unpack(bundle, out)
        model_dir = next(p for p in out.rglob("model.toml")).parent
        toml = (model_dir / "model.toml").read_text()
        tokenizer_section = next(model_dir.glob("*Tokenizer*"))
        data = decode_tokenizer(tokenizer_section)
        tokenizer = json.loads(data) if data else None
        meta = (model_dir / "LlmMetadataProto.pbtext").read_text(errors="ignore")

        report = {
            "bundle": str(bundle),
            "bundle_bytes": bundle.stat().st_size,
            "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "sections": re.findall(r'section_type = "([^"]+)"', toml),
            "metadata": {
                "stop_tokens": re.findall(r'token_str: "([^"]+)"', meta),
                "max_num_tokens": re.search(r"max_num_tokens: (\d+)", meta).group(1)
                if "max_num_tokens" in meta else None,
                "sampler": {
                    "type": re.search(r"sampler_params \{\s*type: (\w+)", meta).group(1)
                    if "sampler_params" in meta else None,
                    "temperature": re.search(r"temperature: ([0-9.]+)", meta).group(1)
                    if "temperature" in meta else None,
                    "top_k": re.search(r"k: (\d+)", meta).group(1) if "k:" in meta else None,
                    "top_p": re.search(r"p: ([0-9.]+)", meta).group(1) if "p:" in meta else None,
                },
                "jinja_template": "jinja_prompt_template" in meta,
                "thinking_channel": "thought" in meta,
                "llm_model_type": re.search(r"llm_model_type \{\s*(\w+)", meta).group(1)
                if "llm_model_type" in meta else None,
            },
            "embedded_tokenizer": None,
            "source_tokenizer": None,
            "tokenizer_identical": None,
        }
        if tokenizer is not None:
            report["embedded_tokenizer"] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "vocab": len(tokenizer.get("model", {}).get("vocab", {})),
                "added_tokens": len(tokenizer.get("added_tokens", [])),
                "chat_template": bool(tokenizer.get("chat_template")),
            }
        if source is not None and tokenizer is not None:
            src = source.read_bytes()
            report["source_tokenizer"] = {
                "bytes": len(src),
                "sha256": hashlib.sha256(src).hexdigest(),
                "vocab": len(json.loads(src).get("model", {}).get("vocab", {})),
            }
            report["tokenizer_identical"] = hashlib.sha256(src).hexdigest() == \
                report["embedded_tokenizer"]["sha256"]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
