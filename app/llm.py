"""LLM wrapper — Gemini với fallback graceful + tự retry model khác khi quota cạn.

Model thử theo thứ tự (ENV GEMINI_MODEL override nếu set):
  1. gemini-2.5-flash       (mặc định, chất lượng tốt nhất trong chuỗi)
  2. gemini-2.5-flash-lite  (lighter, quota cao hơn)
  3. gemini-2.0-flash       (fallback — quota free tier riêng → thêm headroom)
  4. gemini-2.0-flash-lite  (fallback cuối)

Lưu ý: gemini-1.5-flash đã bị Google gỡ (404 NotFound) — KHÔNG đưa lại vào
chuỗi. Mỗi model có hạn ngạch free tier riêng nên xếp nhiều model giúp tránh
cạn quota giữa chừng (429) như đã gặp khi chạy eval batch lớn.
"""

from __future__ import annotations

import os
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

_configured = False


def _ensure_configured() -> bool:
    global _configured
    if _configured:
        return True
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return False
    import google.generativeai as genai
    genai.configure(api_key=key)
    _configured = True
    return True


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
    if not _ensure_configured():
        return (
            "[Server thiếu GEMINI_API_KEY — chưa thể gọi LLM]\n\n"
            f"Đã retrieve {len(chunks)} chunk liên quan:\n" +
            "\n".join(f"  [{i+1}] {c.get('section_title') or c.get('article_title')}"
                      for i, c in enumerate(chunks))
        )

    import google.generativeai as genai

    prompt = build_user_prompt(messages, chunks, user_level=user_level)
    config = {"temperature": 0.3, "max_output_tokens": 1024}

    last_error = None
    for model_name in _get_models_to_try():
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
            # 429 quota — thử model kế tiếp
            if "429" in err_str or "quota" in err_str or "exceeded" in err_str:
                continue
            # Lỗi khác (auth, network) → return luôn, đừng thử tiếp
            return f"[LLM error] {type(e).__name__}: {str(e)[:200]}"

    return (
        f"[Hết quota free tier cho tất cả model Gemini đã thử. "
        f"Đợi vài phút rồi thử lại, hoặc set GEMINI_MODEL trong .env. "
        f"Lỗi cuối: {type(last_error).__name__}]"
    )
