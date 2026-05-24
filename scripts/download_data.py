"""Download pre-built data từ Hugging Face Datasets — skip phải re-crawl 4 giờ.

Cách chạy:
  uv run python scripts/download_data.py
  uv run python scripts/download_data.py --repo-id myusername/meo-chatbot-data

Sau khi xong, có thể chạy chatbot ngay:
  uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--repo-id",
        default="monmoonluna/meo-chatbot-data",
        help="HF dataset repo to pull from",
    )
    p.add_argument(
        "--allow-patterns",
        nargs="+",
        default=["chromadb/**", "chunks/**"],
        help="Files to download (default: chromadb + chunks only, ~1GB)",
    )
    args = p.parse_args()

    from huggingface_hub import snapshot_download

    target = ROOT / "data"
    target.mkdir(parents=True, exist_ok=True)

    print(f"Downloading from huggingface.co/datasets/{args.repo_id}")
    print(f"  Allow patterns: {args.allow_patterns}")
    print(f"  Local dir: {target}")
    print()

    snapshot_download(
        repo_id=args.repo_id,
        repo_type="dataset",
        local_dir=str(target),
        allow_patterns=args.allow_patterns,
    )

    print()
    print("=== DONE ===")
    print()
    print("Verify ChromaDB:")
    print(
        '  uv run python -c "import chromadb; '
        "print(chromadb.PersistentClient('data/chromadb').get_collection('meo_kb').count())\""
    )


if __name__ == "__main__":
    main()
