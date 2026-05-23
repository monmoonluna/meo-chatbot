"""LLM wrapper — Gemini 2.0 Flash với fallback graceful nếu chưa có key."""

from __future__ import annotations

import os

from .prompts import SYSTEM_PROMPT, build_user_prompt

GEMINI_MODEL = "gemini-2.0-flash"

# Lazy init — chỉ configure khi có key
_configured = False


def _ensure_configured() -> bool:
    """Trả về True nếu Gemini đã sẵn sàng dùng (có key)."""
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


def generate_reply(
    messages: list[dict],
    chunks: list[dict],
    user_level: str = "auto",
) -> str:
    """Sinh phản hồi từ messages + retrieved chunks. Fallback nếu thiếu API key."""
    if not _ensure_configured():
        return (
            "[Server thiếu GEMINI_API_KEY — chưa thể gọi LLM]\n\n"
            f"Tuy nhiên đã retrieve {len(chunks)} chunk liên quan:\n" +
            "\n".join(f"  [{i+1}] {c.get('section_title') or c.get('article_title')}"
                      for i, c in enumerate(chunks))
        )

    import google.generativeai as genai

    model = genai.GenerativeModel(
        GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
        generation_config={
            "temperature": 0.3,  # độ creative thấp, ưu tiên grounded
            "max_output_tokens": 1024,
        },
    )

    prompt = build_user_prompt(messages, chunks, user_level=user_level)
    response = model.generate_content(prompt)

    # Gemini đôi khi block do safety → fall back text
    try:
        return response.text
    except Exception:
        return ("Mình không thể trả lời câu hỏi này (LLM filter). "
                "Hãy thử diễn đạt lại hoặc liên hệ thú y trực tiếp.")
