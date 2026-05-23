"""Retriever — embed query bằng e5-small + ChromaDB top-k search.

Sử dụng:
    from app.retriever import retrieve
    chunks = retrieve("Mèo Anh lông ngắn ăn gì?", k=5, topic_filter="nutrition")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import chromadb

ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = ROOT / "data" / "chromadb"
MODEL_NAME = "intfloat/multilingual-e5-small"
COLLECTION = "meo_kb"
E5_QUERY_PREFIX = "query: "

# Lazy singletons — khởi tạo 1 lần per process
_model = None
_collection = None


def _ensure_hf_home():
    """Đảm bảo HF_HOME trỏ về D:\\hf-cache trên Windows nếu chưa set."""
    if not os.getenv("HF_HOME"):
        d_path = Path("D:/hf-cache")
        if d_path.parent.exists():  # có ổ D:
            os.environ["HF_HOME"] = str(d_path)


def get_model():
    global _model
    if _model is None:
        _ensure_hf_home()
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_collection(COLLECTION)
    return _collection


def warmup():
    """Gọi ở startup để tránh latency request đầu tiên."""
    get_model()
    get_collection()


def retrieve(
    query: str,
    k: int = 5,
    topic_filter: Optional[str] = None,
    min_score: float = 0.0,
) -> list[dict]:
    """Embed query → search top-k chunks → return list of dicts với metadata + score."""
    model = get_model()
    coll = get_collection()

    query_emb = model.encode(
        [E5_QUERY_PREFIX + query],
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0].tolist()

    where = {"topic": topic_filter} if topic_filter and topic_filter != "auto" else None
    n_fetch = k * 3 if where else k  # over-fetch khi có filter để đề phòng

    results = coll.query(
        query_embeddings=[query_emb],
        n_results=n_fetch,
        where=where,
    )

    chunks: list[dict] = []
    for i in range(len(results["ids"][0])):
        # ChromaDB returns cosine DISTANCE (0 = identical, 2 = opposite).
        # Convert sang similarity score (1 - distance/2) cho dễ đọc.
        distance = results["distances"][0][i]
        score = 1 - distance / 2
        if score < min_score:
            continue
        meta = results["metadatas"][0][i]
        chunks.append({
            "chunk_id": results["ids"][0][i],
            "text": results["documents"][0][i],
            "score": round(score, 4),
            **meta,
        })

    return chunks[:k]
