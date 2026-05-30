"""Unit tests cho pipeline.classifier — rule-based topic/content_type/severity/level.

classify_* nhận text đã lowercase (giống classify() làm trước khi gọi).
"""

from __future__ import annotations

from pipeline.classifier import (
    classify,
    classify_content_type,
    classify_level,
    classify_severity,
    classify_topic,
)


# --- classify_topic -----------------------------------------------------------

def test_topic_flips_to_dominant_when_two_plus_hits():
    text = "thức ăn và dinh dưỡng giàu protein cho mèo"  # 3 nutrition hits
    topic, hits = classify_topic(text, source_default="care")
    assert topic == "nutrition"
    assert hits >= 2


def test_topic_keeps_default_on_single_hit():
    text = "một bài viết chỉ nhắc tới protein một lần"  # 1 nutrition hit
    topic, _ = classify_topic(text, source_default="care")
    assert topic == "care"  # < 2 hits → không flip


def test_topic_keeps_default_on_no_hit():
    topic, hits = classify_topic("nội dung không liên quan", source_default="breed")
    assert topic == "breed"
    assert hits == 0


# --- classify_content_type ----------------------------------------------------

def test_content_type_detects_warning():
    assert classify_content_type("đây là tình huống cấp cứu nguy hiểm") == "warning"


def test_content_type_detects_symptom():
    assert classify_content_type("các triệu chứng thường gặp") == "symptom"


def test_content_type_warning_has_priority_over_symptom():
    # chứa cả keyword warning ("cấp cứu") lẫn symptom ("triệu chứng")
    assert classify_content_type("triệu chứng nặng, cần cấp cứu") == "warning"


def test_content_type_defaults_to_info():
    assert classify_content_type("giới thiệu chung về giống mèo") == "info"


# --- classify_severity --------------------------------------------------------

def test_severity_high_for_health_emergency():
    assert classify_severity("mèo bị co giật", topic="health") == "high"


def test_severity_medium_for_health_minor():
    assert classify_severity("mèo bị tiêu chảy nhẹ", topic="health") == "medium"


def test_severity_low_for_health_without_keywords():
    assert classify_severity("thông tin sức khỏe chung", topic="health") == "low"


def test_severity_na_for_non_health_topic():
    assert classify_severity("mèo bị co giật", topic="breed") == "n/a"


# --- classify_level -----------------------------------------------------------

def test_level_advanced_on_technical_term():
    assert classify_level("hàm lượng taurine theo chuẩn aafco") == "advanced"


def test_level_beginner_by_default():
    assert classify_level("mèo con rất dễ thương và đáng yêu") == "beginner"


# --- classify (integration) ---------------------------------------------------

def test_classify_returns_all_fields_and_preserves_input():
    chunk = {
        "chunk_id": "abc_000",
        "text": "Mèo bị co giật, khó thở là dấu hiệu cấp cứu cần đưa đi thú y ngay.",
        "topic_hint": "health",
        "article_title": "Cấp cứu cho mèo",
        "section_title": None,
    }
    out = classify(chunk)
    assert out["chunk_id"] == "abc_000"  # input preserved
    assert out["topic"] == "health"
    assert out["content_type"] == "warning"
    assert out["severity"] == "high"
    assert out["level"] in {"beginner", "advanced"}
    assert isinstance(out["topic_hits"], int)
