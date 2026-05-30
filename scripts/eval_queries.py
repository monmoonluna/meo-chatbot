"""Đánh giá RAG pipeline trên 30 query đa dạng để tìm bug.

Run:
    uv run python scripts/eval_queries.py                     # retrieval-only (nhanh, không tốn quota)
    uv run python scripts/eval_queries.py --with-llm          # full RAG kèm Gemini call
    uv run python scripts/eval_queries.py --with-llm --delay 3

Output: scripts/eval_results.md
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Load .env trước khi import app.llm
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from app.retriever import retrieve, warmup  # noqa: E402


QUERIES = [
    # ---- Category 1: Easy (mỗi topic 1 câu) ----
    {"q": "Mèo Anh lông ngắn có đặc điểm gì?", "cat": "easy", "exp_topic": "breed"},
    {"q": "Mèo con 2 tháng tuổi nên ăn gì?", "cat": "easy", "exp_topic": "nutrition"},
    {"q": "Cách tắm cho mèo lần đầu", "cat": "easy", "exp_topic": "care"},
    {"q": "Tại sao mèo kêu nhiều vào ban đêm?", "cat": "easy", "exp_topic": "behavior"},
    {"q": "Triệu chứng bệnh giun sán ở mèo", "cat": "easy", "exp_topic": "health"},
    {"q": "Giá mèo Munchkin ở Việt Nam khoảng bao nhiêu?", "cat": "easy", "exp_topic": "breed"},

    # ---- Category 2: Emergency (cần needs_vet=True) ----
    {"q": "Mèo nôn ra máu liên tục", "cat": "emergency", "exp_needs_vet": True},
    {"q": "Mèo co giật, mắt trợn", "cat": "emergency", "exp_needs_vet": True},
    {"q": "Mèo bị xe đâm, chân chảy máu", "cat": "emergency", "exp_needs_vet": True},
    {"q": "Mèo của tôi ăn phải thuốc paracetamol", "cat": "emergency", "exp_needs_vet": True},
    {"q": "Mèo khó thở, há miệng thở", "cat": "emergency", "exp_needs_vet": True},

    # ---- Category 3: Breed-specific ----
    {"q": "Sự khác nhau giữa British Shorthair và Scottish Fold", "cat": "breed"},
    {"q": "Mèo Bengal có dễ nuôi không?", "cat": "breed"},
    {"q": "Mèo Sphynx có cần tắm thường xuyên không?", "cat": "breed"},
    {"q": "Mèo Ragdoll tính cách thế nào?", "cat": "breed"},

    # ---- Category 4: Edge cases ----
    {"q": "Mèo có thể ăn sô-cô-la không?", "cat": "edge"},
    {"q": "Cách dạy mèo đi vệ sinh đúng chỗ", "cat": "edge"},
    {"q": "Mèo nhà tôi đẻ con 3 ngày rồi vẫn còn co bóp", "cat": "edge", "exp_needs_vet": True},
    {"q": "Vacxin FVRCP là gì?", "cat": "edge"},
    {"q": "Mèo có hiểu được tiếng người không?", "cat": "edge"},

    # ---- Category 5: Tricky / out-of-scope ----
    {"q": "Tôi nên mua mèo hay nhận nuôi?", "cat": "tricky"},
    {"q": "Mèo nhà tôi tên Mướp, hôm nay nó hơi buồn", "cat": "tricky"},
    {"q": "I want to know about Persian cats", "cat": "tricky"},
    {"q": "Bố mẹ tôi ghét mèo, làm sao thuyết phục họ?", "cat": "tricky"},
    {"q": "Giá thức ăn Royal Canin loại 1kg cho mèo trưởng thành", "cat": "tricky"},

    # ---- Category 6: Multi-topic ----
    {"q": "Mèo Anh lông ngắn 3 tháng tuổi bị tiêu chảy, nên cho ăn gì?", "cat": "multi"},
    {"q": "Mèo Bengal hung dữ với chủ mới", "cat": "multi"},
    {"q": "Cách phòng giun sán cho mèo con", "cat": "multi"},
    {"q": "Mèo già 12 tuổi không chịu ăn pate nữa", "cat": "multi"},
    {"q": "Cần chuẩn bị gì khi đón mèo Maine Coon về nhà", "cat": "multi"},
]


def flag_issues(query: dict, chunks: list[dict], reply: str | None) -> list[str]:
    """Return list of human-readable flags về vấn đề tiềm ẩn."""
    flags: list[str] = []

    if not chunks:
        flags.append("🔴 NO RETRIEVAL")
        return flags

    top = chunks[0]
    # Topic mismatch
    if "exp_topic" in query:
        if top.get("topic") != query["exp_topic"]:
            flags.append(f"🟡 TOPIC: top={top.get('topic')} vs expected={query['exp_topic']}")

    # Low score (< 0.85 với e5-small là khá thấp)
    if top["score"] < 0.85:
        flags.append(f"🟡 LOW_SCORE: top={top['score']}")
    if top["score"] < 0.75:
        flags[-1] = flags[-1].replace("🟡", "🔴")

    # needs_vet expected — phải khớp logic trong app/main.py (chỉ severity=high)
    if "exp_needs_vet" in query:
        actual = any(c.get("severity") == "high" for c in chunks)
        if query["exp_needs_vet"] and not actual:
            flags.append("🔴 NEEDS_VET: expected=True, got=False")
        elif not query["exp_needs_vet"] and actual:
            flags.append("🟡 NEEDS_VET: expected=False, got=True (over-trigger)")

    # LLM behaviour
    if reply:
        low = reply.lower()
        if "không có đủ thông tin" in low or "không đủ thông tin" in low:
            flags.append("🟡 LLM_GIVES_UP")
        if "[llm error]" in low or "hết quota" in low:
            flags.append("🔴 LLM_ERROR")
        # Safety prefix expected on needs_vet queries
        if query.get("exp_needs_vet") and "⚠️" not in reply[:60]:
            flags.append("🔴 MISSING_VET_WARNING_PREFIX")

    return flags or ["🟢 OK"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true",
                        help="Gọi Gemini cho mỗi query (tốn quota)")
    parser.add_argument("--delay", type=float, default=2.5,
                        help="Giây giữa các LLM call (tránh rate limit)")
    parser.add_argument("--output", default=str(Path(__file__).parent / "eval_results.md"))
    args = parser.parse_args()

    print(f"Loading retriever (model + ChromaDB)...")
    warmup()
    print(f"Ready. Running {len(QUERIES)} queries (with_llm={args.with_llm})\n")

    if args.with_llm:
        from app.llm import generate_reply
    else:
        generate_reply = None

    # Stats counters
    flag_counter: dict[str, int] = {}
    results = []
    t0 = time.time()

    for i, q in enumerate(QUERIES, 1):
        print(f"  [{i:2d}/{len(QUERIES)}] [{q['cat']:9s}] {q['q'][:60]}", end=" ", flush=True)
        chunks = retrieve(q["q"], k=5)
        reply = None
        if generate_reply:
            reply = generate_reply(
                [{"role": "user", "content": q["q"]}],
                chunks,
                user_level="auto",
            )
            time.sleep(args.delay)
        flags = flag_issues(q, chunks, reply)
        for f in flags:
            flag_counter[f.split(":")[0]] = flag_counter.get(f.split(":")[0], 0) + 1
        results.append({"query": q, "chunks": chunks, "reply": reply, "flags": flags})
        print(" ".join(flags))

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s. Writing report...")

    # ---- Write markdown report ----
    out = Path(args.output)
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# RAG Eval Report\n\n")
        f.write(f"- Date: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"- Mode: {'with-llm' if args.with_llm else 'retrieval-only'}\n")
        f.write(f"- Total queries: {len(QUERIES)}\n")
        f.write(f"- Elapsed: {elapsed:.0f}s\n\n")

        f.write("## Summary by flag\n\n")
        for flag, count in sorted(flag_counter.items(), key=lambda x: -x[1]):
            f.write(f"- `{flag}`: {count}\n")
        f.write("\n")

        f.write("## Detailed results\n\n")
        for i, r in enumerate(results, 1):
            q = r["query"]
            f.write(f"### {i}. [{q['cat']}] {q['q']}\n\n")
            f.write(f"**Flags**: {' / '.join(r['flags'])}\n\n")
            if "exp_topic" in q:
                f.write(f"- Expected topic: `{q['exp_topic']}`\n")
            if "exp_needs_vet" in q:
                f.write(f"- Expected needs_vet: `{q['exp_needs_vet']}`\n")
            f.write(f"\n**Top 5 retrieval:**\n\n")
            for j, c in enumerate(r["chunks"], 1):
                head = (c.get("section_title") or c.get("article_title") or "[no head]")[:80]
                f.write(
                    f"{j}. `score={c['score']}` · `topic={c.get('topic')}` · "
                    f"`sev={c.get('severity')}` · `type={c.get('content_type')}`  \n"
                    f"   **{head}**  \n"
                    f"   {c.get('source_url', '')}\n\n"
                )
            if r["reply"]:
                f.write(f"**LLM reply:**\n\n> {r['reply'].strip()[:1500]}\n\n")
            f.write("---\n\n")

    print(f"✓ Report: {out}")

    # Console summary
    print("\n=== Flag summary ===")
    for flag, count in sorted(flag_counter.items(), key=lambda x: -x[1]):
        print(f"  {flag}: {count}")


if __name__ == "__main__":
    main()
