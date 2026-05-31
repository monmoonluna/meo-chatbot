"""LLM wrapper — Gemini với fallback graceful + xoay vòng nhiều API key khi quota cạn.

Model thử theo thứ tự (ENV GEMINI_MODEL override nếu set):
  1. gemini-2.5-flash       (mặc định, chất lượng tốt nhất trong chuỗi)
  2. gemini-2.5-flash-lite  (lighter, quota cao hơn)
  3. gemini-2.0-flash       (fallback — quota free tier riêng → thêm headroom)
  4. gemini-2.0-flash-lite  (fallback cuối)

Lưu ý: gemini-1.5-flash đã bị Google gỡ (404 NotFound) — KHÔNG đưa lại vào chuỗi.

Nhiều API key (nhân quota free tier) — cấu hình theo 1 trong các cách:
  - GEMINI_API_KEYS="key1,key2,key3,key4,key5"   (khuyến nghị, phân tách , hoặc khoảng trắng)
  - GEMINI_API_KEY_1 ... GEMINI_API_KEY_5         (đánh số)
  - GEMINI_API_KEY                                 (1 key, tương thích ngược)
Tất cả nguồn được gộp + khử trùng lặp. Mỗi request xoay vòng (round-robin) điểm
bắt đầu để rải tải; khi 1 key hết quota (429/ResourceExhausted) thì tự nhảy sang
key kế tiếp. Free tier có hạn ngạch theo từng project/key → 5 key ≈ 5× quota ngày.
"""

from __future__ import annotations

import os
import re
import threading
import warnings

from .prompts import SYSTEM_PROMPT, build_user_prompt

# Suppress deprecation warning từ google-generativeai (chưa migrate sang google-genai)
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

DEFAULT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

_QUOTA_MARKERS = ("429", "quota", "exceeded", "resourceexhausted", "resource_exhausted",
                  "rate limit", "too many requests")
_AUTH_MARKERS = ("api key", "api_key", "permission", "unauthenticated",
                 "401", "403", "invalid argument: api key")

_cursor_lock = threading.Lock()
_key_cursor = 0


def gemini_api_keys() -> list[str]:
    """Mọi key Gemini đã cấu hình, theo thứ tự, đã khử trùng lặp.

    Gộp từ GEMINI_API_KEYS (phân tách , / khoảng trắng / xuống dòng),
    GEMINI_API_KEY, và GEMINI_API_KEY_1..10.
    """
    raw: list[str] = []
    multi = os.getenv("GEMINI_API_KEYS")
    if multi:
        raw += re.split(r"[,\s]+", multi.strip())
    single = os.getenv("GEMINI_API_KEY")
    if single:
        raw.append(single)
    for i in range(1, 11):
        k = os.getenv(f"GEMINI_API_KEY_{i}")
        if k:
            raw.append(k)
    seen: set[str] = set()
    out: list[str] = []
    for k in raw:
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _ordered_keys() -> list[str]:
    """Danh sách key, xoay vòng điểm bắt đầu mỗi lần gọi để rải tải đều."""
    keys = gemini_api_keys()
    if len(keys) <= 1:
        return keys
    global _key_cursor
    with _cursor_lock:
        start = _key_cursor % len(keys)
        _key_cursor = (_key_cursor + 1) % len(keys)
    return keys[start:] + keys[:start]


def _get_models_to_try() -> list[str]:
    """Nếu user set GEMINI_MODEL → chỉ dùng model đó. Còn không → thử lần lượt."""
    custom = os.getenv("GEMINI_MODEL")
    if custom:
        return [custom]
    return DEFAULT_MODELS


def generate_reply(
    messages: list[dict],
    chunks: list[dict],
    user_level: str = "auto",
) -> str:
    keys = _ordered_keys()
    if not keys:
        return (
            "[Server thiếu GEMINI_API_KEY — chưa thể gọi LLM]\n\n"
            f"Đã retrieve {len(chunks)} chunk liên quan:\n" +
            "\n".join(f"  [{i+1}] {c.get('section_title') or c.get('article_title')}"
                      for i, c in enumerate(chunks))
        )

    import google.generativeai as genai

    prompt = build_user_prompt(messages, chunks, user_level=user_level)
    config = {"temperature": 0.3, "max_output_tokens": 1024}
    models = _get_models_to_try()

    last_error = None
    for key in keys:
        genai.configure(api_key=key)
        key_exhausted = False
        for model_name in models:
            try:
                model = genai.GenerativeModel(
                    model_name,
                    system_instruction=SYSTEM_PROMPT,
                    generation_config=config,
                )
                response = model.generate_content(prompt)
                try:
                    return response.text
                except Exception:
                    return ("Mình không thể trả lời câu hỏi này (bộ lọc an toàn của LLM "
                            "đã chặn). Vui lòng diễn đạt lại hoặc liên hệ thú y trực tiếp.")
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if any(m in err_str for m in _QUOTA_MARKERS):
                    continue  # model kế tiếp; hết model → key kế tiếp
                if any(m in err_str for m in _AUTH_MARKERS):
                    key_exhausted = True  # key hỏng/sai → bỏ qua, thử key kế tiếp
                    break
                # Lỗi khác (network, server) → return luôn
                return f"[LLM error] {type(e).__name__}: {str(e)[:200]}"
        _ = key_exhausted  # (chỉ để rõ ý: rơi xuống đây nghĩa là thử key kế tiếp)

    return (
        f"[Hết quota free tier cho TẤT CẢ {len(keys)} key × {len(models)} model Gemini. "
        f"Đợi quota reset (nửa đêm giờ Pacific) hoặc thêm key vào GEMINI_API_KEYS. "
        f"Lỗi cuối: {type(last_error).__name__}]"
    )
