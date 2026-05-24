"""Retriever — embed query bằng e5-small + ChromaDB top-k search.

Dùng `transformers` trực tiếp (AutoModel + AutoTokenizer) thay vì
`sentence_transformers` — vì sentence_transformers crash silently khi
import trên một số máy Windows (DLL conflict?). transformers ổn định hơn.

Tự implement mean-pooling + L2 normalize để match output của sentence_transformers.

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
MAX_LENGTH = 512

# Lazy singletons — khởi tạo 1 lần per process
_model = None
_tokenizer = None
_collection = None


def _ensure_hf_home():
    """Đảm bảo HF_HOME trỏ về D:\\hf-cache trên Windows nếu chưa set."""
    if not os.getenv("HF_HOME"):
        d_path = Path("D:/hf-cache")
        if d_path.parent.exists():  # có ổ D:
            os.environ["HF_HOME"] = str(d_path)


def get_model():
    """Load AutoModel + AutoTokenizer lazy. ~5-15s lần đầu (load từ cache)."""
    global _model, _tokenizer
    if _model is None:
        _ensure_hf_home()
        from transformers import AutoModel, AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModel.from_pretrained(MODEL_NAME)
        _model.eval()
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


def _embed_query(text: str) -> list[float]:
    """Embed 1 query → 384-dim vector. Mean-pool + L2 normalize (giống e5/sentence-transformers)."""
    import torch
    model = get_model()
    tokenizer = _tokenizer  # set by get_model

    inputs = tokenizer(
        [E5_QUERY_PREFIX + text],
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="pt",
    )
    with torch.no_grad():
        outputs = model(**inputs)

    # Mean pool weighted by attention mask
    last_hidden = outputs.last_hidden_state  # (1, seq_len, hidden)
    mask = inputs["attention_mask"].unsqueeze(-1).float()  # (1, seq_len, 1)
    summed = (last_hidden * mask).sum(dim=1)
    count = mask.sum(dim=1).clamp(min=1e-9)
    pooled = summed / count

    # L2 normalize → cosine similarity với ChromaDB
    normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
    return normalized[0].tolist()


def retrieve(
    query: str,
    k: int = 5,
    topic_filter: Optional[str] = None,
    min_score: float = 0.0,
) -> list[dict]:
    """Embed query → search top-k chunks → return list of dicts với metadata + score."""
    coll = get_collection()
    query_emb = _embed_query(query)

    where = {"topic": topic_filter} if topic_filter and topic_filter != "auto" else None
    n_fetch = k * 3 if where else k

    results = coll.query(
        query_embeddings=[query_emb],
        n_results=n_fetch,
        where=where,
    )

    chunks: list[dict] = []
    for i in range(len(results["ids"][0])):
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
