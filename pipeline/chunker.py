"""Chunker — chia bài đã crawl thành chunk ≤ ~800 tokens (~3000 chars VN).

Strategy:
  1. Phát hiện heading bằng heuristic: line < 120 chars, không kết câu, line kế tiếp dài
  2. Mỗi section → 1 chunk nếu ≤ max_chars; ngược lại chia theo paragraph
  3. Prepend heading vào chunk text → embedding nắm được context

Input:  data/cleaned/<source>.jsonl
Output: data/chunks/all.jsonl  (consolidated)

Cách chạy:
  uv run python -m pipeline.chunker --source all
  uv run python -m pipeline.chunker --source paddy --max-chars 2500
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
CLEANED_DIR = ROOT / "data" / "cleaned"
CHUNKS_DIR = ROOT / "data" / "chunks"

MAX_CHARS = 3000          # ~800 tokens cho tiếng Việt với bge-m3
MIN_CHUNK_CHARS = 100     # bỏ chunk quá ngắn
HEADING_MAX_LEN = 120
HEADING_NEXT_MIN_LEN = 80
TERMINAL_PUNCT = (".", "?", "!", ",", ":", ";", "…")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------

def is_heading(line: str, next_nonempty: str) -> bool:
    """True nếu line nhìn giống heading H2/H3."""
    line = line.strip()
    if not line or len(line) >= HEADING_MAX_LEN:
        return False
    if line.endswith(TERMINAL_PUNCT):
        return False
    if line.startswith(("-", "•", "*", "+", "·", "|")):
        return False  # bullet hoặc markdown table row
    if line[0].isdigit() and "." in line[:4]:
        return False  # numbered list "1. ..."
    # Skip lines that are mostly separators (---, ===, |||)
    alnum_count = sum(1 for c in line if c.isalnum())
    if alnum_count / len(line) < 0.3:
        return False
    if not next_nonempty or len(next_nonempty) < HEADING_NEXT_MIN_LEN:
        return False
    return True


def parse_sections(text: str) -> list[tuple[str | None, list[str]]]:
    """Trả về [(heading, [paragraph, ...]), ...]. heading có thể None cho phần đầu."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_body: list[str] = []

    for i, line in enumerate(paragraphs):
        next_p = paragraphs[i + 1] if i + 1 < len(paragraphs) else ""
        if is_heading(line, next_p):
            if current_body:
                sections.append((current_heading, current_body))
            current_heading = line
            current_body = []
        else:
            current_body.append(line)

    if current_body:
        sections.append((current_heading, current_body))
    return sections


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _make_chunk_id(url: str, idx: int) -> str:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    return f"{h}_{idx:03d}"


def _with_heading(heading: str | None, body_text: str) -> str:
    return f"{heading}\n\n{body_text}" if heading else body_text


def split_section(paragraphs: list[str], max_chars: int) -> Iterator[str]:
    """Yield body chunks (chưa prepend heading), mỗi chunk ≤ max_chars."""
    current: list[str] = []
    current_len = 0
    sep_len = 2  # '\n\n' giữa các paragraph

    for para in paragraphs:
        para_len = len(para) + sep_len
        if not current and para_len > max_chars:
            # Paragraph đơn lẻ quá to → vẫn yield nguyên (không cắt giữa câu)
            yield para
            continue
        if current_len + para_len > max_chars and current:
            yield "\n\n".join(current)
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        yield "\n\n".join(current)


def chunk_article(article: dict, max_chars: int = MAX_CHARS) -> list[dict]:
    sections = parse_sections(article["text"])
    chunks: list[dict] = []
    base_meta = {
        "source_url": article["url"],
        "source": article["source"],
        "topic_hint": article["topic_hint"],
        "article_title": article.get("title"),
        "article_date": article.get("date"),
        "language": article.get("language", "vi"),
    }
    idx = 0
    for heading, paragraphs in sections:
        for body in split_section(paragraphs, max_chars):
            text = _with_heading(heading, body)
            if len(text) < MIN_CHUNK_CHARS:
                continue
            chunks.append({
                "chunk_id": _make_chunk_id(article["url"], idx),
                "section_title": heading,
                "text": text,
                "char_count": len(text),
                **base_meta,
            })
            idx += 1
    return chunks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Chunk các bài đã crawl.")
    p.add_argument("--source", default="all", help="Source name hoặc 'all'")
    p.add_argument("--max-chars", type=int, default=MAX_CHARS)
    p.add_argument("--output", default=str(CHUNKS_DIR / "all.jsonl"))
    args = p.parse_args()

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output)

    if args.source == "all":
        sources = sorted(f.stem for f in CLEANED_DIR.glob("*.jsonl"))
    else:
        sources = [args.source]

    if not sources:
        print(f"[!] Không có file nào trong {CLEANED_DIR}", file=sys.stderr)
        return

    total_articles = 0
    total_chunks = 0

    with out_path.open("w", encoding="utf-8") as fout:
        for source in sources:
            src_path = CLEANED_DIR / f"{source}.jsonl"
            if not src_path.exists():
                print(f"  [!] missing: {src_path}", file=sys.stderr)
                continue
            n_articles = 0
            n_chunks = 0
            chunk_lens: list[int] = []
            seen_urls: set[str] = set()  # dedupe — crawler append có thể tạo trùng
            with src_path.open("r", encoding="utf-8") as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        article = json.loads(line)
                    except json.JSONDecodeError as e:
                        print(f"  [!] JSON err in {source}: {e}", file=sys.stderr)
                        continue
                    if not article.get("text"):
                        continue
                    url = article.get("url")
                    if url in seen_urls:
                        continue  # skip duplicate article
                    seen_urls.add(url)
                    n_articles += 1
                    for chunk in chunk_article(article, args.max_chars):
                        fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                        n_chunks += 1
                        chunk_lens.append(chunk["char_count"])

            avg = sum(chunk_lens) // len(chunk_lens) if chunk_lens else 0
            print(f"  {source:18s}: {n_articles:4d} articles → {n_chunks:5d} chunks "
                  f"(avg {avg} chars, {n_chunks / max(n_articles,1):.1f}/article)")
            total_articles += n_articles
            total_chunks += n_chunks

    print(f"\n=== Total: {total_articles} articles → {total_chunks} chunks → {out_path} ===")


if __name__ == "__main__":
    main()
