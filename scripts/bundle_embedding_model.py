#!/usr/bin/env python3
"""Download the bundled sentence-embedding model into the nltest package.

Run before building a PyPI wheel so ``pip install nltest`` works fully offline:

    python scripts/bundle_embedding_model.py

The model files are included in the wheel via setuptools package-data and are
NOT committed to git (see .gitignore).
"""

from __future__ import annotations

import os
import sys

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
TARGET = os.path.join(os.path.dirname(__file__), "..", "nltest", "bundled_models", "all-MiniLM-L6-v2")


def main() -> int:
    target = os.path.normpath(TARGET)
    marker = os.path.join(target, "config.json")
    if os.path.isfile(marker):
        print(f"Model already bundled at {target}")
        return 0

    os.makedirs(target, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is required to bundle the model: pip install huggingface_hub", file=sys.stderr)
        return 1

    print(f"Downloading {MODEL_ID} -> {target}")
    snapshot_download(repo_id=MODEL_ID, local_dir=target, local_dir_use_symlinks=False)
    if not os.path.isfile(marker):
        print("Download finished but config.json is missing", file=sys.stderr)
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
