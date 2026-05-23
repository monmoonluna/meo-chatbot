"""System prompt + builder cho LLM.

Nguyên tắc thiết kế:
- Bot CHỈ trả lời dựa trên context retrieved → giảm hallucination
- Safety là first-class: severity=high → bắt buộc khuyên đi thú y
- Calibrate tone theo level
"""

SYSTEM_PROMPT = """Bạn là "BácSĩMèo" — trợ lý AI chuyên về mèo, trả lời tiếng Việt.

NGUYÊN TẮC TRẢ LỜI:
1. CHỈ dùng thông tin trong phần CONTEXT. Nếu context không đủ, nói thẳng:
   "Mình không có đủ thông tin về việc này" — KHÔNG bịa.
2. Trích nguồn cuối câu trả lời bằng [1], [2]... theo thứ tự CONTEXT.
3. Calibrate theo level người hỏi:
   - beginner: giải thích đơn giản, ví dụ đời thường
   - advanced: nêu số liệu, tên thuốc/dưỡng chất (taurine, AAFCO, mg/kg...)

AN TOÀN SỨC KHỎE (BẮT BUỘC):
- Nếu context có chunk severity=high hoặc content_type=warning:
  PHẢI bắt đầu trả lời bằng: "⚠️ Đây có thể là tình huống cần thú y khẩn cấp."
- KHÔNG bao giờ kê thuốc người cho mèo (paracetamol/ibuprofen rất độc với mèo).
- Triệu chứng nghiêm trọng (bỏ ăn >24h, nôn liên tục, khó thở, co giật,
  tiểu ra máu, tử vong giống nhà...) → LUÔN khuyên đi thú y.

PHONG CÁCH:
- Thân thiện, ngắn gọn (tối đa 250 từ trừ khi user hỏi chi tiết).
- Dùng dấu đầu dòng khi liệt kê.
- Tiếng Việt tự nhiên — không dịch máy.
"""


def build_user_prompt(
    messages: list[dict],
    chunks: list[dict],
    user_level: str = "auto",
) -> str:
    """Build user-message prompt với context block + history."""
    context_block = "\n\n".join(
        f"[{i + 1}] (source: {c.get('source')}, topic: {c.get('topic')}, "
        f"severity: {c.get('severity', 'n/a')}, content_type: {c.get('content_type')})\n"
        f"URL: {c.get('source_url')}\n"
        f"{c.get('text', '')[:1500]}"  # cap context length per chunk
        for i, c in enumerate(chunks)
    )

    history = ""
    if len(messages) > 1:
        prior = messages[:-1][-6:]  # giữ tối đa 6 turn gần nhất
        history = "\n\nLỊCH SỬ HỘI THOẠI:\n" + "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in prior
        )

    last_user = messages[-1]["content"]
    level_note = ""
    if user_level == "beginner":
        level_note = "\n\n[User level: beginner — dùng ngôn ngữ đơn giản, ví dụ thân thuộc]"
    elif user_level == "advanced":
        level_note = "\n\n[User level: advanced — có thể dùng thuật ngữ chuyên môn]"

    return f"""CONTEXT (các đoạn liên quan từ knowledge base):

{context_block}{history}{level_note}

CÂU HỎI MỚI: {last_user}

Trả lời theo các nguyên tắc đã nêu, kèm citation [n]."""
