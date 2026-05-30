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

# --- Reranker (cross-encoder) ---
# e5-small là bi-encoder: cosine scores bị nén (~0.92-0.96) nên không phân biệt
# được chunk thực sự liên quan với chunk chỉ trùng từ khoá. Cross-encoder chấm
# điểm từng cặp (query, passage) → relevance tách bạch hơn nhiều, dùng để
# re-rank top-N candidate từ ChromaDB rồi mới lấy top-k.
# Dùng transformers.AutoModelForSequenceClassification trực tiếp (KHÔNG
# FlagEmbedding/sentence_transformers) cho nhất quán + tránh crash trên Windows.
RERANK_ENABLED = os.getenv("MEO_RERANK", "1") != "0"
RERANKER_MODEL = os.getenv("MEO_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
# Số candidate kéo từ ChromaDB trước khi rerank (nhiều hơn k để reranker có
# không gian sắp xếp lại). 0.0 sigmoid floor = giữ tất cả; tune qua env.
RERANK_CANDIDATES = int(os.getenv("MEO_RERANK_CANDIDATES", "20"))
# Floor trên rerank score (sigmoid 0-1). Chunk dưới ngưỡng bị loại → khi tất cả
# rớt, app/main.py trả fallback "không đủ thông tin" thay vì bịa.
RERANK_MIN_SCORE = float(os.getenv("MEO_RERANK_MIN_SCORE", "0.05"))

# Conservative relevance floor. e5-small cosine scores are compressed: on-topic
# tiếng Việt queries land ~0.96+, but English/conversational cat queries dip to
# ~0.92, overlapping off-topic (~0.90-0.94). A floor of 0.90 only filters
# blatant mismatches (coding/weather/recipe questions) without rejecting real
# cat questions — when everything falls below it, app/main.py returns the
# "không đủ thông tin" fallback instead of answering from irrelevant chunks.
DEFAULT_MIN_SCORE = float(os.getenv("MEO_MIN_SCORE", "0.90"))

# Lazy singletons — khởi tạo 1 lần per process
_model = None
_tokenizer = None
_collection = None
_reranker = None
_reranker_tok = None
_rerank_disabled = False  # set True nếu load reranker fail → fallback e5 ordering


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


def get_reranker():
    """Load cross-encoder lazy. Trả None nếu disabled hoặc load fail (fallback e5)."""
    global _reranker, _reranker_tok, _rerank_disabled
    if not RERANK_ENABLED or _rerank_disabled:
        return None
    if _reranker is None:
        _ensure_hf_home()
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            _reranker_tok = AutoTokenizer.from_pretrained(RERANKER_MODEL)
            _reranker = AutoModelForSequenceClassification.from_pretrained(RERANKER_MODEL)
            _reranker.eval()
        except Exception as e:  # model chưa tải / OOM / DLL issue → degrade gracefully
            print(f"[retriever] reranker load failed ({type(e).__name__}: {e}); "
                  f"fallback to e5 ordering. Set MEO_RERANK=0 to silence.")
            _rerank_disabled = True
            return None
    return _reranker


def _rerank(query: str, chunks: list[dict]) -> list[dict]:
    """Chấm lại từng (query, chunk.text) bằng cross-encoder, gán rerank_score
    (sigmoid 0-1), sort giảm dần. No-op nếu reranker không khả dụng."""
    model = get_reranker()
    if model is None or not chunks:
        return chunks
    import torch
    pairs = [[query, c.get("text", "")] for c in chunks]
    inputs = _reranker_tok(
        pairs, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt",
    )
    with torch.no_grad():
        logits = model(**inputs).logits.view(-1)
        scores = torch.sigmoid(logits)
    for c, s in zip(chunks, scores.tolist()):
        c["rerank_score"] = round(float(s), 4)
    chunks.sort(key=lambda c: c["rerank_score"], reverse=True)
    return chunks


def warmup():
    """Gọi ở startup để tránh latency request đầu tiên."""
    get_model()
    get_collection()
    get_reranker()


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
    min_score: Optional[float] = None,
) -> list[dict]:
    """Embed query → search top-k chunks → return list of dicts với metadata + score.

    min_score=None → dùng DEFAULT_MIN_SCORE (env MEO_MIN_SCORE, mặc định 0.90).
    Truyền 0.0 để tắt floor (vd: debug/eval muốn xem raw scores).
    """
    if min_score is None:
        min_score = DEFAULT_MIN_SCORE
    coll = get_collection()
    query_emb = _embed_query(query)

    where = {"topic": topic_filter} if topic_filter and topic_filter != "auto" else None
    # Khi rerank: kéo nhiều candidate hơn để cross-encoder có không gian sắp lại.
    if RERANK_ENABLED and not _rerank_disabled:
        n_fetch = max(RERANK_CANDIDATES, k * 3 if where else k)
    else:
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
            "score": round(score, 4),  # e5 cosine (giữ cho citation/backward-compat)
            **meta,
        })

    # Cross-encoder rerank → sort theo rerank_score, lọc floor, lấy top-k.
    chunks = _rerank(query, chunks)
    if any("rerank_score" in c for c in chunks):
        chunks = [c for c in chunks if c.get("rerank_score", 0.0) >= RERANK_MIN_SCORE]

    return chunks[:k]
