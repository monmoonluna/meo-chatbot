"""Thử nhiều rule needs_vet trên test set (reranked) → chọn rule giữ recall
emergency mà ít false-positive nhất. Retrieval-only, không tốn Gemini.

Cũng là REGRESSION CHECK cho cổng production thực tế (_compute_needs_vet:
rerank-gate + intent-gate). Phải luôn giữ EMERGENCY RECALL = 9/9."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from app.retriever import retrieve, warmup
from app.main import _compute_needs_vet, NEEDS_VET_MIN_RR, NEEDS_VET_REQUIRE_INTENT

warmup()
data = json.loads((Path(__file__).parent / "eval_external_set.json").read_text(encoding="utf-8"))["questions"]

def rules(ch):
    sev = [c.get("severity") for c in ch]
    top1 = sev[0] == "high" if sev else False
    top2 = any(s == "high" for s in sev[:2])
    any5 = any(s == "high" for s in sev)         # rule hiện tại
    two_of_top3 = sum(1 for s in sev[:3] if s == "high") >= 2
    top1_or_2of3 = top1 or two_of_top3
    return {"any5": any5, "top2": top2, "top1": top1,
            "2of3": two_of_top3, "top1|2of3": top1_or_2of3}

rows = []
prod = []  # (emer, needs_vet từ cổng production thực tế, câu hỏi)
for q in data:
    ch = retrieve(q["vi"], k=5)
    rows.append((q["emer"], rules(ch)))
    prod.append((q["emer"], _compute_needs_vet(ch, q["vi"]), q["vi"]))

names = ["any5", "top2", "top1", "2of3", "top1|2of3"]
print(f"{'rule':12} {'emer_recall':12} {'false_pos':10}")
emer_total = sum(1 for e, _ in rows if e)
non_total = sum(1 for e, _ in rows if not e)
for n in names:
    recall = sum(1 for e, r in rows if e and r[n])
    fp = sum(1 for e, r in rows if (not e) and r[n])
    print(f"{n:12} {recall}/{emer_total:<10} {fp}/{non_total}")

# --- Cổng production thực tế (rr-gate + intent-gate) ---
print(f"\n=== PRODUCTION GATE (MIN_RR={NEEDS_VET_MIN_RR}, "
      f"REQUIRE_INTENT={NEEDS_VET_REQUIRE_INTENT}) ===")
emer_hit = sum(1 for e, nv, _ in prod if e and nv)
over = [v for e, nv, v in prod if (not e) and nv]
missed = [v for e, nv, v in prod if e and not nv]
print(f"EMERGENCY RECALL: {emer_hit}/{emer_total}   (PHẢI = {emer_total}/{emer_total})")
print(f"OVER-TRIGGER:     {len(over)}/{non_total}")
if missed:
    print("⚠️  EMERGENCY BỎ SÓT (REGRESSION!):")
    for v in missed:
        print("   -", v[:60])
if over:
    print("residual over-trigger (chấp nhận được nếu là red-flag mơ hồ):")
    for v in over:
        print("   -", v[:60])
assert emer_hit == emer_total, f"RECALL REGRESSION: {emer_hit}/{emer_total}"
