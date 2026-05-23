"""Ingest — embed chunks bằng multilingual-e5-small và push vào ChromaDB persistent.

Đọc:  data/chunks/classified.jsonl  (output của classifier)
Ghi:  data/chromadb/                (ChromaDB persistent client)

intfloat/multilingual-e5-small: 384-dim, multilingual (incl Vietnamese), MIT,
chạy local. ~470 MB. Nhanh hơn bge-m3 ~5-10x trên CPU, quality gap ~3-5%
trên VN retrieval benchmarks — chấp nhận được cho v1.

Lưu ý: e5 models yêu cầu prefix "passage: " cho documents và "query: " cho queries.

Cách chạy:
  uv run python -m pipeline.ingest --limit 50      # test
  uv run python -m pipeline.ingest                 # full ~30-60 phút
  uv run python -m pipeline.ingest --reset         # xóa collection + load lại
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import chromadb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "chunks" / "classified.jsonl"
CHROMA_DIR = ROOT / "data" / "chromadb"

COLLECTION = "meo_kb"
MODEL_NAME = "intfloat/multilingual-e5-small"
BATCH_SIZE = 64  # e5-small nhỏ, batch lớn hơn
CHROMA_BATCH = 256  # insert batch into ChromaDB
E5_PASSAGE_PREFIX = "passage: "  # bắt buộc cho e5 family

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_model():
    """Lazy import — model download có thể mất 1-2 phút lần đầu."""
    print(f"Loading {MODEL_NAME}... (lần đầu sẽ tải ~470 MB)")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print(f"  ✓ Loaded in {time.time() - t0:.1f}s")
    return model


def embed_texts(model, texts: list[str]) -> list[list[float]]:
    """Trả về list[384-dim]. E5 family cần prefix 'passage: ' cho documents."""
    prefixed = [E5_PASSAGE_PREFIX + t for t in texts]
    embeddings = model.encode(
        prefixed,
        batch_size=BATCH_SIZE,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,  # giúp cosine similarity ổn định
    )
    return embeddings.tolist()


# Chroma yêu cầu metadata values là str/int/float/bool, không list/None
def _clean_meta(c: dict) -> dict:
    keep = ("source_url", "source", "article_title", "article_date", "language",
            "section_title", "topic", "content_type", "severity", "level",
            "char_count", "topic_hits")
    out = {}
    for k in keep:
        v = c.get(k)
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            v = ", ".join(map(str, v))
        if not isinstance(v, (str, int, float, bool)):
            v = str(v)
        out[k] = v
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(INPUT))
    p.add_argument("--limit", type=int, default=None, help="Test với N chunk đầu")
    p.add_argument("--reset", action="store_true", help="Xóa collection và load lại từ đầu")
    args = p.parse_args()

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if args.reset:
        try:
            client.delete_collection(COLLECTION)
            print(f"  ✓ Reset collection: {COLLECTION}")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"Collection '{COLLECTION}' has {collection.count()} existing items\n")

    # Đọc chunks chưa được ingest
    existing_ids = set(collection.get(include=[])["ids"]) if collection.count() > 0 else set()
    chunks = []
    with Path(args.input).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if c["chunk_id"] in existing_ids:
                continue
            chunks.append(c)
            if args.limit and len(chunks) >= args.limit:
                break

    if not chunks:
        print("Không có chunk mới để ingest.")
        return

    print(f"Sẽ ingest {len(chunks):,} chunks mới\n")
    model = load_model()

    print("\nEmbedding + uploading...")
    bar = tqdm(range(0, len(chunks), CHROMA_BATCH), desc="batches")
    for start in bar:
        batch = chunks[start:start + CHROMA_BATCH]
        texts = [c["text"] for c in batch]
        ids = [c["chunk_id"] for c in batch]
        metas = [_clean_meta(c) for c in batch]
        embeddings = embed_texts(model, texts)
        collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
        bar.set_postfix(total=collection.count())

    print(f"\n=== Done: {collection.count():,} chunks in ChromaDB → {CHROMA_DIR} ===")


if __name__ == "__main__":
    main()
