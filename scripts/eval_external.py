"""Đánh giá chất lượng RAG trên câu hỏi mèo lấy từ dataset công khai (HuggingFace
playcat community Q&A), đã dịch sang tiếng Việt.

Run:
    uv run python scripts/eval_external.py --with-llm
    uv run python scripts/eval_external.py --with-llm --delay 3   # nếu bị rate limit

Output: scripts/eval_external_results.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from app.retriever import retrieve, warmup  # noqa: E402

SET_PATH = Path(__file__).parent / "eval_external_set.json"

JUDGE_PROMPT = """Bạn là giám khảo đánh giá câu trả lời của chatbot tư vấn về mèo.
Cho CÂU HỎI, CONTEXT (các đoạn knowledge base bot được phép dùng) và CÂU TRẢ LỜI,
hãy chấm 2 tiêu chí trên thang 1-5:

- faithfulness: mọi khẳng định trong câu trả lời CÓ được context chống lưng không?
  5 = hoàn toàn dựa vào context, không bịa. 1 = bịa nhiều / mâu thuẫn context.
  (Nếu bot nói "không đủ thông tin" mà context đúng là không liên quan → faithfulness=5.)
- helpfulness: câu trả lời có thực sự giải đáp đúng trọng tâm câu hỏi không?
  5 = trả lời trực tiếp, hữu ích. 1 = lạc đề / vô dụng.

CHỈ trả về JSON đúng định dạng, không giải thích thêm:
{"faithfulness": <1-5>, "helpfulness": <1-5>, "note": "<lý do ngắn gọn>"}"""


def judge_reply(question: str, chunks: list[dict], reply: str) -> dict | None:
    """Dùng Gemini làm giám khảo chấm faithfulness + helpfulness. None nếu lỗi."""
    import os
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    import google.generativeai as genai
    genai.configure(api_key=key)
    ctx = "\n\n".join(
        f"[{i+1}] (topic={c.get('topic')}, sev={c.get('severity')}) {c.get('text','')[:600]}"
        for i, c in enumerate(chunks)
    )
    prompt = f"CÂU HỎI: {question}\n\nCONTEXT:\n{ctx}\n\nCÂU TRẢ LỜI:\n{reply}"
    for model_name in ("gemini-2.5-flash", "gemini-2.5-flash-lite",
                        "gemini-2.0-flash", "gemini-2.0-flash-lite"):
        try:
            model = genai.GenerativeModel(
                model_name, system_instruction=JUDGE_PROMPT,
                generation_config={"temperature": 0.0, "max_output_tokens": 256,
                                   "response_mime_type": "application/json"},
            )
            raw = model.generate_content(prompt).text
            d = json.loads(raw)
            return {"faithfulness": int(d["faithfulness"]),
                    "helpfulness": int(d["helpfulness"]),
                    "note": str(d.get("note", ""))[:200]}
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "quota" in err:
                continue
            return None
    return None


def score_one(q: dict, chunks: list[dict], reply: str | None) -> tuple[list[str], dict]:
    """Trả về (flags, metrics) cho 1 câu hỏi."""
    flags: list[str] = []
    m = {"retrieved": len(chunks), "top_score": chunks[0]["score"] if chunks else 0.0,
         "topic_match": None, "needs_vet": None, "grounded": None,
         "has_citation": None, "vet_prefix": None}

    if not chunks:
        flags.append("🔴 NO_RETRIEVAL")
        return flags, m

    top = chunks[0]
    # 1. Topic match (majority of top-5, like app/main.py topic_detected)
    counts: dict[str, int] = {}
    for c in chunks:
        counts[c.get("topic", "?")] = counts.get(c.get("topic", "?"), 0) + 1
    detected = max(counts, key=counts.get)
    m["topic_detected"] = detected
    m["topic_match"] = (detected == q["topic"])
    if not m["topic_match"]:
        flags.append(f"🟡 TOPIC: got={detected} exp={q['topic']}")

    # 2. Retrieval confidence
    if top["score"] < 0.90:
        flags.append(f"🔴 LOW_SCORE={top['score']}")
    elif top["score"] < 0.93:
        flags.append(f"🟡 LOW_SCORE={top['score']}")

    # 3. Safety: needs_vet logic mirrors app/main.py (severity==high)
    needs_vet = any(c.get("severity") == "high" for c in chunks)
    m["needs_vet"] = needs_vet
    if q["emer"] and not needs_vet:
        flags.append("🔴 EMER_MISSED (needs_vet=False)")
    if (not q["emer"]) and needs_vet:
        flags.append("🟡 OVER_TRIGGER (needs_vet=True)")

    if reply is not None:
        low = reply.lower()
        m["grounded"] = not ("không đủ thông tin" in low or "không có đủ thông tin" in low)
        if not m["grounded"]:
            flags.append("🟡 LLM_GIVES_UP")
        if "[llm error]" in low or "hết quota" in low or "thiếu gemini" in low:
            flags.append("🔴 LLM_ERROR")
            m["grounded"] = None
        m["has_citation"] = ("[1]" in reply or "[2]" in reply or "[3]" in reply)
        if not m["has_citation"]:
            flags.append("🟡 NO_CITATION")
        m["vet_prefix"] = reply.strip().startswith("⚠")
        if q["emer"] and not m["vet_prefix"]:
            flags.append("🔴 NO_VET_WARNING_PREFIX")

    if not flags:
        flags.append("🟢 OK")
    return flags, m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-llm", action="store_true")
    ap.add_argument("--judge", action="store_true",
                    help="Gemini chấm faithfulness+helpfulness mỗi reply (cần --with-llm, tốn thêm quota)")
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--limit", type=int, default=0, help="chỉ chạy N câu đầu (debug)")
    ap.add_argument("--output", default=str(Path(__file__).parent / "eval_external_results.md"))
    args = ap.parse_args()

    data = json.loads(SET_PATH.read_text(encoding="utf-8"))
    questions = data["questions"]
    if args.limit:
        questions = questions[:args.limit]

    print("Loading retriever...")
    warmup()
    print(f"Ready. {len(questions)} questions (with_llm={args.with_llm})\n")

    gen = None
    if args.with_llm:
        from app.llm import generate_reply
        gen = generate_reply

    results = []
    flag_counter: dict[str, int] = {}
    t0 = time.time()
    for i, q in enumerate(questions, 1):
        print(f"  [{i:2d}/{len(questions)}] [{q['topic']:9s}]{'⚠' if q['emer'] else ' '} {q['vi'][:55]}",
              end=" ", flush=True)
        chunks = retrieve(q["vi"], k=5)
        reply = None
        if gen:
            reply = gen([{"role": "user", "content": q["vi"]}], chunks, user_level="auto")
            time.sleep(args.delay)
        flags, metrics = score_one(q, chunks, reply)
        jdg = None
        if args.judge and reply:
            jdg = judge_reply(q["vi"], chunks, reply)
            time.sleep(args.delay)
            if jdg:
                metrics["faithfulness"] = jdg["faithfulness"]
                metrics["helpfulness"] = jdg["helpfulness"]
        for f in flags:
            key = f.split(":")[0].split("=")[0].strip()
            flag_counter[key] = flag_counter.get(key, 0) + 1
        results.append({"q": q, "chunks": chunks, "reply": reply, "flags": flags,
                        "metrics": metrics, "judge": jdg})
        suffix = f" | F={jdg['faithfulness']} H={jdg['helpfulness']}" if jdg else ""
        print(" ".join(flags) + suffix)

    elapsed = time.time() - t0

    # Aggregate metrics
    n = len(results)
    topic_ok = sum(1 for r in results if r["metrics"].get("topic_match"))
    emer = [r for r in results if r["q"]["emer"]]
    emer_vet_ok = sum(1 for r in results if r["q"]["emer"] and r["metrics"].get("needs_vet"))
    nonemer = [r for r in results if not r["q"]["emer"]]
    over_trig = sum(1 for r in nonemer if r["metrics"].get("needs_vet"))
    if args.with_llm:
        grounded = sum(1 for r in results if r["metrics"].get("grounded"))
        cited = sum(1 for r in results if r["metrics"].get("has_citation"))
        gaveup = sum(1 for r in results if r["metrics"].get("grounded") is False)
        prefix_ok = sum(1 for r in emer if r["metrics"].get("vet_prefix"))
    judged = [r for r in results if r.get("judge")]
    if judged:
        avg_faith = sum(r["judge"]["faithfulness"] for r in judged) / len(judged)
        avg_help = sum(r["judge"]["helpfulness"] for r in judged) / len(judged)

    out = Path(args.output)
    with out.open("w", encoding="utf-8") as f:
        f.write("# RAG Eval — câu hỏi từ dataset công khai (dịch sang VN)\n\n")
        f.write(f"- Date: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"- Dataset: `{data['_meta']['source_dataset']}`\n")
        f.write(f"- Mode: {'with-llm' if args.with_llm else 'retrieval-only'}\n")
        f.write(f"- Questions: {n} | Elapsed: {elapsed:.0f}s\n\n")
        f.write("## Aggregate scores\n\n")
        f.write(f"- Topic match (detected==expected): **{topic_ok}/{n}** ({topic_ok/n:.0%})\n")
        f.write(f"- Emergency → needs_vet=True: **{emer_vet_ok}/{len(emer)}**\n")
        f.write(f"- Non-emergency over-trigger: **{over_trig}/{len(nonemer)}**\n")
        if args.with_llm:
            f.write(f"- Grounded (không 'bỏ cuộc'): **{grounded}/{n}**\n")
            f.write(f"- Has citation [n]: **{cited}/{n}**\n")
            f.write(f"- LLM gave up ('không đủ thông tin'): **{gaveup}/{n}**\n")
            f.write(f"- Emergency replies với ⚠️ prefix: **{prefix_ok}/{len(emer)}**\n")
        if judged:
            f.write(f"- Judge faithfulness (1-5): **{avg_faith:.2f}** (n={len(judged)})\n")
            f.write(f"- Judge helpfulness (1-5): **{avg_help:.2f}** (n={len(judged)})\n")
        f.write("\n## Flag summary\n\n")
        for fl, c in sorted(flag_counter.items(), key=lambda x: -x[1]):
            f.write(f"- `{fl}`: {c}\n")
        f.write("\n## Detailed results\n\n")
        for i, r in enumerate(results, 1):
            q = r["q"]
            f.write(f"### {i}. [{q['topic']}]{' ⚠EMER' if q['emer'] else ''} {q['vi']}\n\n")
            f.write(f"*EN gốc:* {q['en']}\n\n")
            f.write(f"**Flags:** {' / '.join(r['flags'])}\n\n")
            f.write("**Top retrieval:**\n\n")
            for j, c in enumerate(r["chunks"], 1):
                head = (c.get("section_title") or c.get("article_title") or "[no head]")[:70]
                rr = c.get("rerank_score")
                rr_s = f"`rr={rr}` " if rr is not None else ""
                f.write(f"{j}. {rr_s}`e5={c['score']}` `topic={c.get('topic')}` "
                        f"`sev={c.get('severity')}` — {head}  \n")
            if r.get("judge"):
                jdg = r["judge"]
                f.write(f"\n**Judge:** faithfulness={jdg['faithfulness']}/5, "
                        f"helpfulness={jdg['helpfulness']}/5 — {jdg['note']}\n")
            if r["reply"]:
                f.write(f"\n**Reply:**\n\n> {r['reply'].strip()[:1500]}\n\n")
            f.write("---\n\n")

    print(f"\nDone in {elapsed:.0f}s → {out}")
    print("\n=== Aggregate ===")
    print(f"  Topic match: {topic_ok}/{n}")
    print(f"  Emergency needs_vet: {emer_vet_ok}/{len(emer)}")
    print(f"  Over-trigger: {over_trig}/{len(nonemer)}")
    if args.with_llm:
        print(f"  Grounded: {grounded}/{n} | Cited: {cited}/{n} | Gave up: {gaveup}/{n}")
        print(f"  Emer ⚠ prefix: {prefix_ok}/{len(emer)}")
    if judged:
        print(f"  Judge faithfulness: {avg_faith:.2f}/5 | helpfulness: {avg_help:.2f}/5")
    print("\n=== Flags ===")
    for fl, c in sorted(flag_counter.items(), key=lambda x: -x[1]):
        print(f"  {fl}: {c}")


if __name__ == "__main__":
    main()
