"""#4 — guard the silent coupling between ingest and query embeddings.

pipeline/ingest.py embeds passages with `sentence_transformers`, while
app/retriever.py deliberately bypasses it (Windows DLL crashes) and hand-rolls
mean-pool + L2-normalize via `transformers`. They MUST stay numerically aligned,
or retrieval degrades silently with no error. This test pins that invariant:
the retriever's manual pooling must match sentence_transformers for the same
input text (cosine ≈ 1.0).

Slow: loads the e5-small model twice (~470 MB, cached). Run with
`-m "not slow"` to skip during fast iterations.
"""

from __future__ import annotations

import pytest

MODEL_NAME = "intfloat/multilingual-e5-small"
TEXT = "Mèo Anh lông ngắn là giống mèo phổ biến, tính cách điềm tĩnh và thân thiện."


@pytest.mark.slow
def test_retriever_pooling_matches_sentence_transformers():
    np = pytest.importorskip("numpy")
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:  # ST crashes on some Windows boxes — that's *why* retriever avoids it
        pytest.skip(f"sentence_transformers unavailable here: {e}")

    from app.retriever import _embed_query

    # retriever path: prepends "query: " then manual mean-pool + normalize
    manual = np.asarray(_embed_query(TEXT), dtype=np.float64)

    # sentence_transformers path (same prefix) — what ingest.py relies on
    st = SentenceTransformer(MODEL_NAME)
    reference = np.asarray(
        st.encode(["query: " + TEXT], normalize_embeddings=True)[0],
        dtype=np.float64,
    )

    assert manual.shape == reference.shape == (384,)
    # both are L2-normalized → dot product is cosine similarity
    cosine = float(np.dot(manual, reference))
    assert cosine > 0.999, f"pooling drift detected: cosine={cosine:.6f}"
