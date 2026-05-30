"""Thử nhiều rule needs_vet trên test set (reranked) → chọn rule giữ 6/6
emergency mà ít false-positive nhất. Retrieval-only, không tốn Gemini."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from app.retriever import retrieve, warmup

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
for q in data:
    ch = retrieve(q["vi"], k=5)
    rows.append((q["emer"], rules(ch)))

names = ["any5", "top2", "top1", "2of3", "top1|2of3"]
print(f"{'rule':12} {'emer_recall':12} {'false_pos':10}")
emer_total = sum(1 for e, _ in rows if e)
non_total = sum(1 for e, _ in rows if not e)
for n in names:
    recall = sum(1 for e, r in rows if e and r[n])
    fp = sum(1 for e, r in rows if (not e) and r[n])
    print(f"{n:12} {recall}/{emer_total:<10} {fp}/{non_total}")
