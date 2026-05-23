"""Rule-based classifier — gán topic, content_type, severity, level cho từng chunk.

Đọc:  data/chunks/all.jsonl  (output của chunker)
Ghi:  data/chunks/classified.jsonl

Mục đích metadata:
  - topic         → filter ở retrieval (tránh kéo nhầm chunk khác chủ đề)
  - content_type  → biết chunk là triệu chứng / điều trị / cảnh báo...
  - severity      → high → LLM bắt buộc khuyên đi thú y
  - level         → calibrate tone (beginner vs advanced)

Cách chạy:
  uv run python -m pipeline.classifier
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "chunks" / "all.jsonl"
OUTPUT = ROOT / "data" / "chunks" / "classified.jsonl"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Keyword lists (tiếng Việt + một số EN thuật ngữ chuyên môn)
# ---------------------------------------------------------------------------

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "breed": [
        "giống mèo", "phân loại giống", "thuần chủng", "lai", "phả hệ",
        "anh lông ngắn", "british shorthair", "anh lông dài", "british longhair",
        "ba tư", "persian", "bengal", "scottish fold", "tai cụp", "tai gập",
        "munchkin", "chân ngắn", "sphynx", "không lông", "maine coon",
        "ragdoll", "abyssinian", "siamese", "mèo xiêm", "american shorthair",
        "exotic", "savannah", "devon rex", "cornish rex", "russian blue",
        "norwegian forest", "burmese", "tonkinese", "himalayan", "angora",
        "ald", "aln", "mướp", "mun", "tam thể", "mèo ta",
        "odd eyes", "mắt 2 màu", "phối giống",
    ],
    "nutrition": [
        "thức ăn", "dinh dưỡng", "khẩu phần", "calo", "protein",
        "pate", "hạt khô", "thịt", "cá", "sữa", "snack", "thưởng",
        "vitamin", "khoáng", "taurine", "omega", "amino acid",
        "aafco", "kcal", "wet food", "dry food", "raw", "homemade",
        "biếng ăn", "bỏ ăn", "kén ăn", "ăn vặt",
        "công thức", "nấu pate", "mix feeding",
        "thực đơn", "uống nước", "khát",
    ],
    "health": [
        "bệnh", "triệu chứng", "tiêm phòng", "vaccine", "vacxin",
        "thú y", "thuốc", "điều trị", "chẩn đoán", "viêm", "nhiễm",
        "ký sinh", "sán", "giun", "ve mèo", "rận", "bọ chét",
        "fip", "fiv", "felv", "viêm phúc mạc", "tiểu đường", "suy thận",
        "ung thư", "khối u", "tử vong", "ho", "nôn", "tiêu chảy", "sốt",
        "co giật", "động kinh", "gãy xương", "tai nạn",
        "triệt sản", "thiến", "phẫu thuật", "xét nghiệm",
        "ngộ độc", "dị ứng", "kháng sinh", "kháng viêm",
        "vết thương", "chấn thương", "bị thương",
    ],
    "behavior": [
        "hành vi", "tâm lý", "tính cách", "kêu", "meo", "gừ", "gầm",
        "cọ đầu", "tặng quà", "tin tưởng", "yêu bạn", "stress", "căng thẳng",
        "đánh dấu lãnh thổ", "đi tiểu bậy", "cào đồ", "cắn yêu",
        "huấn luyện", "dạy mèo", "luyện mèo",
        "nhào bột", "kneading",
        "sợ hãi", "ghen tị", "ghen tuông",
        "đực", "cái", "động dục", "gọi đực", "gọi cái",
    ],
    "care": [
        "chăm sóc", "vệ sinh", "tắm", "chải lông", "cắt móng",
        "rụng lông", "khay cát", "vệ sinh khay", "thay cát",
        "nuôi mèo", "mèo đẻ", "mèo sơ sinh", "mèo con", "kitten",
        "chuồng", "lồng", "nệm cho mèo", "đồ chơi",
        "vận chuyển", "carrier", "đi du lịch",
        "phát triển", "trưởng thành", "tháng tuổi",
        "gửi mèo", "trông giữ",
        "cạo lông", "tỉa lông",
    ],
}

# Priority order: first match wins
CONTENT_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("warning", [
        "cấp cứu", "khẩn cấp", "nguy hiểm", "tử vong", "chết",
        "ngay lập tức", "đưa ngay", "lập tức đưa",
        "ngộ độc", "hóc", "khó thở",
    ]),
    ("symptom", [
        "triệu chứng", "dấu hiệu bệnh", "biểu hiện", "nhận biết bệnh",
        "biểu hiện khi", "dấu hiệu của",
    ]),
    ("treatment", [
        "điều trị", "chữa trị", "phác đồ", "liều dùng",
        "phẫu thuật", "thủ thuật", "tiêm thuốc",
    ]),
    ("prevention", [
        "phòng tránh", "phòng ngừa", "ngừa", "tiêm phòng", "vaccine",
        "tránh bệnh", "biện pháp phòng",
    ]),
    ("qa", [
        "có phải", "có nên", "có được", "tại sao", "vì sao",
        "câu hỏi thường gặp", "faq",
    ]),
]
# Else: "info"

HIGH_SEVERITY = [
    "tử vong", "chết", "fip", "viêm phúc mạc", "felv", "fiv",
    "suy thận", "tiểu đường", "ung thư", "khối u",
    "co giật", "động kinh", "khó thở", "ngừng thở",
    "cấp cứu", "khẩn cấp", "ngộ độc nặng",
]
MEDIUM_SEVERITY = [
    "tiêu chảy", "nôn", "ho", "sốt", "đau", "sưng", "viêm",
    "ký sinh", "sán", "giun", "ve", "rận", "nhiễm trùng",
    "bỏ ăn", "mệt mỏi",
]

ADVANCED_TERMS = [
    "aafco", "kcal", "mg/kg", "iu/kg",
    "taurine", "arginine", "arachidonic", "amino acid",
    "fvrcp", "felv", "fiv", "fip",
    "sdma", "creatinine", "azotemia", "albumin", "globulin",
    "hematocrit", "hemoglobin",
    "thyroid", "tuyến giáp", "thyroxine",
    "dimethyl arginine", "ph máu",
    "antibiotic", "kháng sinh nhóm",
    "tica", "cfa", "fife", "wcf",
    "chondrodysplasia", "polycystic", "hcm",
]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    return s.lower()


def _count_matches(text: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in text)


def classify_topic(text: str, source_default: str) -> tuple[str, int]:
    """Return (topic, n_keyword_hits). Fall back to source_default nếu hòa/không hit."""
    scores: dict[str, int] = {}
    for topic, kws in TOPIC_KEYWORDS.items():
        scores[topic] = _count_matches(text, kws)
    top = max(scores, key=scores.get)
    if scores[top] == 0:
        return source_default, 0
    # Nếu top sát source_default (chênh <= 1) thì ưu tiên source_default — giảm flip
    if top != source_default and scores[top] - scores.get(source_default, 0) <= 1:
        return source_default, scores[source_default]
    return top, scores[top]


def classify_content_type(text: str) -> str:
    for ctype, kws in CONTENT_TYPE_RULES:
        if any(kw in text for kw in kws):
            return ctype
    return "info"


def classify_severity(text: str, topic: str) -> str:
    if topic != "health":
        return "n/a"
    if any(kw in text for kw in HIGH_SEVERITY):
        return "high"
    if any(kw in text for kw in MEDIUM_SEVERITY):
        return "medium"
    return "low"


def classify_level(text: str) -> str:
    if _count_matches(text, ADVANCED_TERMS) >= 1:
        return "advanced"
    return "beginner"


def classify(chunk: dict) -> dict:
    # Ghép heading + article_title + text để tối đa keyword phát hiện
    bag = " ".join(filter(None, [
        chunk.get("article_title", ""),
        chunk.get("section_title") or "",
        chunk.get("text", ""),
    ]))
    bag_l = _normalize(bag)

    topic, topic_hits = classify_topic(bag_l, chunk.get("topic_hint", "care"))
    content_type = classify_content_type(bag_l)
    severity = classify_severity(bag_l, topic)
    level = classify_level(bag_l)

    return {
        **chunk,
        "topic": topic,
        "topic_hits": topic_hits,
        "content_type": content_type,
        "severity": severity,
        "level": level,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(INPUT))
    p.add_argument("--output", default=str(OUTPUT))
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    topic_counter: Counter = Counter()
    ctype_counter: Counter = Counter()
    severity_counter: Counter = Counter()
    level_counter: Counter = Counter()
    flipped = 0  # số chunk có topic khác topic_hint

    with in_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            classified = classify(chunk)
            fout.write(json.dumps(classified, ensure_ascii=False) + "\n")
            topic_counter[classified["topic"]] += 1
            ctype_counter[classified["content_type"]] += 1
            severity_counter[classified["severity"]] += 1
            level_counter[classified["level"]] += 1
            if classified["topic"] != chunk.get("topic_hint"):
                flipped += 1

    total = sum(topic_counter.values())
    print(f"\n=== Classified {total:,} chunks → {out_path} ===\n")

    def _show(name: str, counter: Counter) -> None:
        print(f"{name}:")
        for k, v in counter.most_common():
            pct = v * 100 // total
            bar = "█" * (pct // 2)
            print(f"  {k:12s} {v:6,} ({pct:>3}%) {bar}")
        print()

    _show("topic", topic_counter)
    _show("content_type", ctype_counter)
    _show("severity", severity_counter)
    _show("level", level_counter)

    print(f"Flipped from topic_hint: {flipped:,} chunks ({flipped * 100 // total}%)")


if __name__ == "__main__":
    main()
