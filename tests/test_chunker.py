"""Unit tests cho pipeline.chunker — heading detection + chunking heuristics."""

from __future__ import annotations

from pipeline.chunker import (
    MIN_CHUNK_CHARS,
    _make_chunk_id,
    chunk_article,
    is_heading,
    parse_sections,
    split_section,
)

LONG = "Đây là một đoạn văn bản đủ dài để được coi là body, " * 3  # > 80 chars


# --- is_heading ---------------------------------------------------------------

def test_heading_short_line_followed_by_long_body():
    assert is_heading("Đặc điểm ngoại hình", LONG) is True


def test_heading_rejects_terminal_punctuation():
    assert is_heading("Mèo Anh lông ngắn rất dễ thương.", LONG) is False


def test_heading_rejects_bullet_lines():
    assert is_heading("- một gạch đầu dòng", LONG) is False


def test_heading_rejects_numbered_list():
    assert is_heading("1. Bước đầu tiên", LONG) is False


def test_heading_rejects_separator_lines():
    assert is_heading("--------------------", LONG) is False


def test_heading_rejects_when_next_line_too_short():
    assert is_heading("Đặc điểm ngoại hình", "ngắn") is False


def test_heading_rejects_overly_long_line():
    assert is_heading("x" * 200, LONG) is False


# --- parse_sections -----------------------------------------------------------

def test_parse_sections_splits_on_heading():
    text = f"Giới thiệu\n{LONG}\nDinh dưỡng\n{LONG}"
    sections = parse_sections(text)
    headings = [h for h, _ in sections]
    assert headings == ["Giới thiệu", "Dinh dưỡng"]


def test_parse_sections_leading_body_has_none_heading():
    text = f"{LONG}\nDinh dưỡng\n{LONG}"
    sections = parse_sections(text)
    assert sections[0][0] is None


# --- split_section ------------------------------------------------------------

def test_split_section_respects_max_chars():
    paras = ["a" * 100, "b" * 100, "c" * 100]
    chunks = list(split_section(paras, max_chars=250))
    assert len(chunks) == 2  # 100+100 fit, third spills over
    assert all(len(c) <= 250 for c in chunks)


def test_split_section_keeps_oversized_paragraph_whole():
    big = "z" * 5000
    chunks = list(split_section([big], max_chars=3000))
    assert chunks == [big]  # never splits mid-paragraph


# --- chunk_article ------------------------------------------------------------

def _article(text: str) -> dict:
    return {
        "url": "https://example.com/meo",
        "source": "example",
        "topic_hint": "care",
        "title": "Bài viết test",
        "text": text,
    }


def test_chunk_article_prepends_heading_to_body():
    art = _article(f"Dinh dưỡng cho mèo\n{LONG}")
    chunks = chunk_article(art)
    assert chunks[0]["text"].startswith("Dinh dưỡng cho mèo")
    assert chunks[0]["section_title"] == "Dinh dưỡng cho mèo"


def test_chunk_article_drops_tiny_chunks():
    art = _article("ngắn quá")  # below MIN_CHUNK_CHARS, no heading
    assert chunk_article(art) == []


def test_chunk_article_sets_metadata_and_charcount():
    art = _article(f"Tiêu đề mục\n{LONG}")
    c = chunks = chunk_article(art)[0]
    assert c["char_count"] == len(c["text"])
    assert c["source_url"] == "https://example.com/meo"
    assert c["source"] == "example"
    assert len(c["text"]) >= MIN_CHUNK_CHARS


def test_make_chunk_id_is_deterministic_and_indexed():
    a = _make_chunk_id("https://example.com/x", 0)
    b = _make_chunk_id("https://example.com/x", 0)
    c = _make_chunk_id("https://example.com/x", 1)
    assert a == b
    assert a != c
    assert a.endswith("_000") and c.endswith("_001")
