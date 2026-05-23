"""Test nhanh retrieval (không cần Gemini key) — verify embed + ChromaDB OK.

Chạy:
    uv run python scripts/test_retrieval.py
    uv run python scripts/test_retrieval.py "Mèo Anh lông ngắn ăn gì?"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from app.retriever import retrieve

DEFAULT_QUERIES = [
    ("Mèo Anh lông ngắn ăn gì để mau lớn?", "nutrition"),
    ("Mèo của tôi nôn liên tục 2 ngày nay, có nguy hiểm không?", "health"),
    ("Cách chăm sóc mèo Bengal con", "breed"),
    ("Vì sao mèo hay cọ đầu vào người?", "behavior"),
    ("Bao lâu thì nên thay cát mèo?", "care"),
]


def show_results(query: str, topic: str | None) -> None:
    print(f"\n{'=' * 80}")
    print(f"  Q: {query}")
    print(f"  Topic filter: {topic or 'auto'}")
    print(f"{'=' * 80}")
    chunks = retrieve(query, k=5, topic_filter=topic)
    if not chunks:
        print("  (no results)")
        return
    for i, c in enumerate(chunks, 1):
        head = c.get("section_title") or c.get("article_title", "[no title]")
        print(f"\n  [{i}] score={c['score']}  topic={c.get('topic')}  "
              f"severity={c.get('severity')}  type={c.get('content_type')}")
        print(f"      {head}")
        print(f"      {c.get('source_url', '')}")
        snippet = c["text"][:200].replace("\n", " ")
        print(f"      >>> {snippet}...")


def main() -> None:
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        show_results(query, None)
        return

    for q, topic in DEFAULT_QUERIES:
        show_results(q, topic)


if __name__ == "__main__":
    main()
