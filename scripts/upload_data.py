"""Upload pre-built ChromaDB + classified chunks lên Hugging Face Datasets.

Yêu cầu:
  1. Tạo HF account: https://huggingface.co/join
  2. Tạo write token: https://huggingface.co/settings/tokens (chọn "Write" permission)
  3. Set token (1 trong 2 cách):
       - huggingface-cli login   (lưu vào ~/.cache/huggingface)
       - HF_TOKEN=hf_xxx... python scripts/upload_data.py

Cách chạy:
  uv run python scripts/upload_data.py
  uv run python scripts/upload_data.py --repo-id myusername/meo-chatbot-data --private
"""

from __future__ import annotations

import argparse
import os
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
        help="HF dataset repo (username/repo-name)",
    )
    p.add_argument("--private", action="store_true", help="Create as private dataset")
    p.add_argument(
        "--include-cleaned",
        action="store_true",
        help="Also upload cleaned/*.jsonl (article JSONL). +112 MB.",
    )
    args = p.parse_args()

    from huggingface_hub import HfApi, login

    # Auth: env var > cached login > prompt
    token = os.getenv("HF_TOKEN")
    if token:
        login(token=token, add_to_git_credential=False)

    api = HfApi()

    print(f"Creating dataset repo: {args.repo_id} (private={args.private})")
    api.create_repo(
        repo_id=args.repo_id,
        repo_type="dataset",
        private=args.private,
        exist_ok=True,
    )

    # README for the dataset page
    dataset_readme = f"""---
license: cc-by-nc-4.0
language:
- vi
tags:
- cat
- veterinary
- rag
- vietnamese
size_categories:
- 10K<n<100K
---

# meo-chatbot data

Pre-built RAG data for [meo-chatbot](https://github.com/monmoonluna/meo-chatbot) — Vietnamese cat advisor chatbot.

## Contents

- `chromadb/` — ChromaDB persistent client with **75,264 chunks** (384-dim e5-small embeddings)
- `chunks/classified.jsonl` — raw chunks with metadata (topic, content_type, severity, level)
- `cleaned/*.jsonl` — original articles per source (optional, only if `--include-cleaned`)

## Sources (10 VN cat websites)

pethealth.vn, paddy.vn, tropicpet.vn, mozzi.vn, champetsfamily.com,
petspace.vn, petthings.vn, kingspet.vn, fagopet.vn, mochicat.vn

## Usage

```python
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="{args.repo_id}",
    repo_type="dataset",
    local_dir="data/",
)
```

Then run chatbot per [main repo README](https://github.com/monmoonluna/meo-chatbot).

## License

Data crawled from public blogs with robots.txt respect. `source_url` in metadata
for attribution. Non-commercial use only (CC-BY-NC-4.0).
"""
    print("Uploading dataset card (README.md)...")
    api.upload_file(
        path_or_fileobj=dataset_readme.encode("utf-8"),
        path_in_repo="README.md",
        repo_id=args.repo_id,
        repo_type="dataset",
    )

    print("\nUploading chromadb/ (~929 MB)...")
    api.upload_folder(
        folder_path=str(ROOT / "data" / "chromadb"),
        path_in_repo="chromadb",
        repo_id=args.repo_id,
        repo_type="dataset",
    )

    print("\nUploading chunks/classified.jsonl (~141 MB)...")
    api.upload_file(
        path_or_fileobj=str(ROOT / "data" / "chunks" / "classified.jsonl"),
        path_in_repo="chunks/classified.jsonl",
        repo_id=args.repo_id,
        repo_type="dataset",
    )

    if args.include_cleaned:
        print("\nUploading cleaned/*.jsonl (~112 MB)...")
        api.upload_folder(
            folder_path=str(ROOT / "data" / "cleaned"),
            path_in_repo="cleaned",
            repo_id=args.repo_id,
            repo_type="dataset",
            allow_patterns=["*.jsonl"],
        )

    print(f"\n=== DONE ===")
    print(f"Dataset: https://huggingface.co/datasets/{args.repo_id}")


if __name__ == "__main__":
    main()
