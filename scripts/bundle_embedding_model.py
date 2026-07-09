#!/usr/bin/env python3
"""Download the bundled sentence-embedding model into the nltest package.

Run before building a PyPI wheel so ``pip install nl-test`` works fully offline:

    python scripts/bundle_embedding_model.py

Only the files required by sentence-transformers at runtime are downloaded
(~90 MB), not the full Hugging Face repo (ONNX/OpenVINO/TF variants).
"""

from __future__ import annotations

import os
import shutil
import sys

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
TARGET = os.path.join(os.path.dirname(__file__), "..", "nltest", "bundled_models", "all-MiniLM-L6-v2")

# Minimal runtime set for SentenceTransformer local load (keeps wheel under PyPI size limits).
ALLOW_PATTERNS = [
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "model.safetensors",
    "1_Pooling/config.json",
]


def main() -> int:
    target = os.path.normpath(TARGET)
    marker = os.path.join(target, "config.json")
    if os.path.isfile(marker) and os.path.isfile(os.path.join(target, "model.safetensors")):
        print(f"Model already bundled at {target}")
        return 0

    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is required to bundle the model: pip install huggingface_hub", file=sys.stderr)
        return 1

    print(f"Downloading {MODEL_ID} (minimal runtime files) -> {target}")
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=target,
        allow_patterns=ALLOW_PATTERNS,
    )
    if not os.path.isfile(marker):
        print("Download finished but config.json is missing", file=sys.stderr)
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
