"""Tune MEO_RETRIEVAL_HISTORY_TURNS: how many prior USER turns to fold into the
retrieval query. Tests BOTH directions:
  - coreference: entity established N turns back must still be retrieved (favors larger N)
  - dilution: after a topic switch, stale turns must NOT dominate (favors smaller N)
Retrieval-only — no Gemini quota.
"""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
import os
os.environ.setdefault("HF_HOME", "D:/hf-cache")
from app.retriever import retrieve, warmup

# (user_turns oldest->current, good_kws to hit, distractor_kws that must NOT dominate, label)
CASES = [
    (["Tôi nuôi một con mèo Ba Tư.", "Lông của bé nên chải bao lâu một lần?"],
     ["ba tư", "persian", "lông dài"], [], "coref-1: Persian grooming"),
    (["Mèo nhà mình là Anh lông ngắn 3 tháng tuổi.", "Bé nên ăn mấy bữa một ngày?"],
     ["anh lông ngắn", "mèo con", "tháng tuổi"], [], "coref-1: ALN kitten feeding"),
    (["Tôi có một bé mèo Sphynx không lông.", "Bé ăn thức ăn nào tốt?", "Mình có cần tắm cho bé thường xuyên không?"],
     ["sphynx", "không lông", "tắm"], [], "coref-2: Sphynx bathing"),
    (["Tôi mới nuôi mèo Ragdoll.", "Bé hay kêu nhiều không?", "Tính cách bé ra sao?", "Bé này dễ bị bệnh gì không?"],
     ["ragdoll", "hiền", "tính cách", "thân thiện"], [], "coref-3: Ragdoll"),
    (["Mèo của tôi bị tiêu chảy nặng phải làm sao?", "Cảm ơn. Giờ tôi muốn hỏi mèo Anh lông ngắn ăn gì?"],
     ["anh lông ngắn", "thức ăn", "dinh dưỡng"], ["tiêu chảy"], "switch: diarrhea -> ALN food"),
    (["Làm sao để cắt móng cho mèo an toàn?", "Còn mèo Maine Coon có đặc điểm gì?"],
     ["maine coon", "mỹ lông dài", "mèo lớn"], ["cắt móng", "móng"], "switch: nails -> Maine Coon"),
]


def query_for(turns, n):
    if n <= 0:
        return turns[-1]
    return " ".join(turns[-(n + 1):])


def hit(chunks, kws, top=3):
    for c in chunks[:top]:
        bag = ((c.get("article_title") or "") + " " + c.get("text", "")).lower()
        if any(k in bag for k in kws):
            return True
    return False


def top1_distracted(chunks, distractors):
    if not chunks or not distractors:
        return False
    bag = ((chunks[0].get("article_title") or "") + " " + chunks[0].get("text", "")).lower()
    return any(d in bag for d in distractors)


def main():
    warmup()
    Ns = [0, 1, 2, 3]
    print(f"{'case':34} " + " ".join(f"N={n}" for n in Ns))
    agg = {n: {"good": 0, "dilute": 0} for n in Ns}
    for turns, good, distr, label in CASES:
        row = []
        for n in Ns:
            ch = retrieve(query_for(turns, n), k=5)
            g = hit(ch, good); d = top1_distracted(ch, distr)
            agg[n]["good"] += g; agg[n]["dilute"] += d
            mark = "✓" if g else "·"
            if d: mark += "!"   # distracted by stale topic
            row.append(f"{mark:3}")
        print(f"{label:34} " + " ".join(f"{c:3}" for c in row))
    print()
    ncase = len(CASES)
    print(f"{'':34} " + " ".join(f"N={n}" for n in Ns))
    print(f"{'good-hits (higher better)':34} " + " ".join(f"{agg[n]['good']}/{ncase}".ljust(4) for n in Ns))
    print(f"{'dilution (lower better)':34} " + " ".join(f"{agg[n]['dilute']}/{ncase}".ljust(4) for n in Ns))


if __name__ == "__main__":
    main()
