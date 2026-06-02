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

from .prompts import SYSTEM_PROMPT, build_user_prompt


class LLMUnavailable(Exception):
    """LLM tạm thời không trả lời được (hết quota mọi key / lỗi mạng / thiếu key).

    main.py bắt exception này và trả HTTP 503 + thông điệp thân thiện, thay vì
    đẩy chuỗi lỗi kỹ thuật ('Hết quota...') ra cho người dùng cuối.
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


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
    # Gộp giá trị thô từ mọi nguồn rồi tách trên dấu phẩy/khoảng trắng. API key
    # Gemini (AIza...) không bao giờ chứa dấu phẩy/khoảng trắng, nên tách an toàn
    # — cho phép dồn nhiều key vào 1 biến GEMINI_API_KEY="k1,k2,..." cũng chạy.
    sources: list[str] = []
    for name in ("GEMINI_API_KEYS", "GEMINI_API_KEY"):
        v = os.getenv(name)
        if v:
            sources.append(v)
    for i in range(1, 11):
        v = os.getenv(f"GEMINI_API_KEY_{i}")
        if v:
            sources.append(v)
    seen: set[str] = set()
    out: list[str] = []
    for src in sources:
        for k in re.split(r"[,\s]+", src.strip()):
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
    """Sinh câu trả lời từ Gemini (SDK google-genai mới).

    Trả về string khi thành công (kể cả khi bộ lọc an toàn chặn → trả thông điệp
    lịch sự). RAISE `LLMUnavailable` khi thiếu key hoặc đã thử hết mọi key × model
    mà vẫn lỗi (quota/network) — để main.py trả 503 + UX thân thiện.
    """
    keys = _ordered_keys()
    if not keys:
        raise LLMUnavailable("no_api_keys")

    from google import genai
    from google.genai import types

    prompt = build_user_prompt(messages, chunks, user_level=user_level)
    models = _get_models_to_try()

    def _config_for(model_name: str) -> "types.GenerateContentConfig":
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            # 1024 cắt ngang câu trả lời danh sách dài (tiếng Việt) trước khi kịp gắn
            # [n] ở các gạch đầu dòng → rớt citation. 2048 đủ cho câu trả lời ~250 từ
            # kèm trích nguồn mà không bị cụt.
            max_output_tokens=2048,
        )
        # gemini-2.5* bật "thinking" mặc định: token suy nghĩ tính vào
        # max_output_tokens nhưng KHÔNG nằm trong .text → câu trả lời bị cụt giữa
        # chừng + tăng latency (~75s). RAG tra cứu không cần suy luận chuỗi → tắt.
        # Chỉ áp dụng cho 2.5 (2.0* không hỗ trợ thinking_config → sẽ 400).
        if model_name.startswith("gemini-2.5"):
            cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
        return cfg

    last_error = None
    for key in keys:
        client = genai.Client(api_key=key)
        for model_name in models:
            try:
                response = client.models.generate_content(
                    model=model_name, contents=prompt, config=_config_for(model_name),
                )
                text = response.text
                if not text:  # bộ lọc an toàn chặn / output rỗng
                    return ("Mình không thể trả lời câu hỏi này (bộ lọc an toàn của LLM "
                            "đã chặn). Vui lòng diễn đạt lại hoặc liên hệ thú y trực tiếp.")
                return text
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if any(m in err_str for m in _AUTH_MARKERS):
                    break  # key hỏng/sai → bỏ qua, thử key kế tiếp
                # quota (429/ResourceExhausted) hoặc network/server → thử model
                # kế, hết model → key kế. Không trả lỗi thô cho user nữa.
                continue

    # Đã thử hết keys × models mà vẫn lỗi → báo cho main.py xử lý UX.
    print(f"[LLM] kiệt quệ: {len(keys)} key × {len(models)} model đều lỗi. "
          f"Lỗi cuối: {type(last_error).__name__}: {str(last_error)[:200]}")
    raise LLMUnavailable("all_exhausted")
