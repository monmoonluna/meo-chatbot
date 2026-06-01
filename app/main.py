"""FastAPI service — endpoint /chat cho team web tích hợp.

Chạy local:
    uv run uvicorn app.main:app --reload

Docs tự sinh: http://localhost:8000/docs

Test bằng curl:
    curl -X POST http://localhost:8000/chat \
      -H "Content-Type: application/json" \
      -d '{"messages":[{"role":"user","content":"Mèo Anh lông ngắn ăn gì?"}]}'
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from collections import OrderedDict, defaultdict, deque
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .llm import LLMUnavailable, generate_reply
from .retriever import retrieve, warmup
from .schemas import ChatRequest, ChatResponse, Citation

load_dotenv()  # đọc .env nếu có


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warmup model + ChromaDB ở startup → tránh latency request đầu
    print("Warming up retriever (load model + collection)...")
    warmup()
    print("Ready.")
    yield


app = FastAPI(
    title="MèoBot API",
    version="0.1.0",
    description="RAG chatbot tiếng Việt về mèo — sức khỏe, dinh dưỡng, giống, chăm sóc, hành vi.",
    lifespan=lifespan,
)

# CORS — production nên chỉ allow domain của team web
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# --- Auth + rate limiting (chỉ áp cho /chat, không áp cho /health) ---
# API_KEY: nếu set, client phải gửi header `X-API-Key` khớp. Không set → bỏ qua
#          (tiện cho local dev). Production NÊN set để tránh lộ quota Gemini.
# RATE_LIMIT_PER_MIN: số request tối đa mỗi IP trong 60s. <=0 để tắt.
API_KEY = os.getenv("API_KEY")
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))
_RATE_WINDOW_SEC = 60.0
_request_log: dict[str, deque[float]] = defaultdict(deque)

# needs_vet gate: 1 chunk severity=="high" chỉ kích hoạt cảnh báo thú y khi nó
# đủ LIÊN QUAN (rerank_score >= ngưỡng). Dry-run trên eval_external_set.json:
# sàn rerank_score của chunk-high ở 9/9 câu cấp cứu = 0.937 → ngưỡng 0.5 giữ
# 9/9 recall mà loại các flag rõ ràng sai (Maine Coon gầy rr=0.11, mèo gạt đồ
# rr=0.25). Khi reranker tắt/hỏng (rerank_score None hoặc 0) → fallback về
# "any high" để an toàn tuyệt đối. Đặt 0 để tắt gate (về hành vi cũ).
NEEDS_VET_MIN_RR = float(os.getenv("MEO_NEEDS_VET_MIN_RR", "0.5"))

# Cổng INTENT cấp 2: chunk severity=high thường rất "liên quan" về mặt ngữ nghĩa
# với cả câu hỏi lành tính (đặt lồng vận chuyển, lịch tiêm phòng, hắt hơi...) →
# reranker cho điểm 0.98+, vượt cả sàn cấp cứu 0.937, nên ngưỡng rr KHÔNG tách
# được. Dry-run eval_external_set.json: yêu cầu thêm câu hỏi có NGÔN NGỮ cấp tính
# giữ 9/9 recall mà giảm over-trigger 8→1. Đặt MEO_NEEDS_VET_REQUIRE_INTENT=0 để
# trở về hành vi cũ (chỉ cổng rr). RỦI RO: list từ khoá → câu cấp cứu diễn đạt
# không có từ khoá nào có thể bị bỏ sót; list dưới đây cố tình rộng.
NEEDS_VET_REQUIRE_INTENT = os.getenv("MEO_NEEDS_VET_REQUIRE_INTENT", "1").strip().lower() not in (
    "0", "false", "no", "off", ""
)

# Dấu hiệu cấp tính ở CÂU HỎI (red-flag thú y). Cố tình rộng — thiên về recall.
_ACUTE_INTENT = (
    "khó thở", "há miệng", "thở gấp", "thở khò", "tím tái", "thở dốc",
    "co giật", "động kinh", "co cứng", "ngất", "bất tỉnh", "hôn mê", "lả đi",
    "nằm im", "không động đậy", "đột ngột", "đột nhiên",
    "ngộ độc", "ăn phải", "nuốt phải", "nuốt", "hóc", "mắc nghẹn",
    "không đi tiểu", "bí tiểu", "tiểu không", "không tiểu được", "rặn tiểu",
    "nôn liên tục", "nôn nhiều", "nôn ra máu", "nôn mãi", "ói liên tục", "ói nhiều",
    "tiêu chảy nặng", "phân có máu", "có máu", "ra máu", "chảy máu", "máu",
    "sốt cao", "sốt 4", "sốt 39", "sốt 40", "sốt 41",
    "bỏ ăn", "không ăn", "không chịu ăn", "chán ăn",
    "cấp cứu", "nguy hiểm", "nguy kịch", "khẩn cấp",
    "tai nạn", "ngã", "té", "chấn thương", "gãy", "va đập",
    "liệt", "sưng to", "đau dữ dội", "đau quằn", "rên", "kêu đau", "co rúm",
)


def _has_acute_intent(text: str) -> bool:
    """True nếu câu hỏi chứa dấu hiệu cấp tính (chỉ dùng khi REQUIRE_INTENT bật)."""
    n = (text or "").lower()
    return any(kw in n for kw in _ACUTE_INTENT)

# Banner cảnh báo thú y, server-side prepend khi needs_vet=True. Trước đây phụ
# thuộc LLM tự chèn → eval cho thấy LLM bỏ sót 9/9 → ép server-side để chắc chắn.
_VET_BANNER = (
    "⚠️ **Dấu hiệu này có thể nghiêm trọng — hãy đưa mèo đến bác sĩ thú y để được "
    "khám trực tiếp.** Thông tin dưới đây chỉ mang tính tham khảo, không thay thế "
    "chẩn đoán của thú y.\n\n"
)


# --- Response cache (giảm tải quota Gemini cho câu hỏi lặp) ---
# Chỉ cache request đơn lượt (1 message) + topic auto → câu hỏi phổ biến không
# tốn quota LLM lần 2. Bounded LRU theo MEO_REPLY_CACHE (mặc định 256, 0 = tắt).
REPLY_CACHE_MAX = int(os.getenv("MEO_REPLY_CACHE", "256"))
_reply_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()


def _normalize_q(text: str) -> str:
    """Chuẩn hoá câu hỏi cho cache key: lowercase + gộp khoảng trắng."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _cache_key(req: ChatRequest):
    """Khoá cache cho request đơn lượt, topic auto. None → không cache."""
    if REPLY_CACHE_MAX <= 0:
        return None
    if len(req.messages) != 1 or req.topic_filter != "auto":
        return None
    return (req.user_level, req.top_k, _normalize_q(req.messages[-1].content))


def _cache_get(key) -> dict | None:
    if key is None:
        return None
    with _cache_lock:
        hit = _reply_cache.get(key)
        if hit is not None:
            _reply_cache.move_to_end(key)  # LRU: vừa dùng → đẩy về cuối
        return hit


def _cache_put(key, payload: dict) -> None:
    if key is None:
        return
    with _cache_lock:
        _reply_cache[key] = payload
        _reply_cache.move_to_end(key)
        while len(_reply_cache) > REPLY_CACHE_MAX:
            _reply_cache.popitem(last=False)  # evict oldest


def _compute_needs_vet(chunks: list[dict], query: str = "") -> bool:
    """True nếu có chunk severity=='high' đủ liên quan (rerank_score >= ngưỡng)
    VÀ (tuỳ chọn) câu hỏi có ngôn ngữ cấp tính.

    Khi rerank_score thiếu (None) hoặc reranker tắt (0 cho mọi chunk high) →
    fallback về "any high" để giữ an toàn (recall ưu tiên hơn precision).
    Cổng intent (NEEDS_VET_REQUIRE_INTENT) áp dụng SAU cổng rr: chỉ bật banner khi
    chính câu hỏi mô tả tình huống cấp tính → loại cry-wolf trên câu lành tính mà
    vẫn giữ 9/9 recall cấp cứu (xem _ACUTE_INTENT).
    """
    high = [c for c in chunks if c.get("severity") == "high"]
    if not high:
        return False

    if NEEDS_VET_MIN_RR <= 0:
        rr_pass = True
    else:
        rrs = [c.get("rerank_score") for c in high]
        if all(rr is None or rr == 0 for rr in rrs):
            rr_pass = True  # reranker off/failed → đừng tắt cảnh báo
        else:
            rr_pass = any(rr is not None and rr >= NEEDS_VET_MIN_RR for rr in rrs)
    if not rr_pass:
        return False

    if NEEDS_VET_REQUIRE_INTENT and not _has_acute_intent(query):
        return False  # chunk nghiêm trọng nhưng câu hỏi không cấp tính → không cry-wolf
    return True


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()  # client thật khi chạy sau proxy/LB
    return request.client.host if request.client else "unknown"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def rate_limit(request: Request) -> None:
    if RATE_LIMIT_PER_MIN <= 0:
        return
    ip = _client_ip(request)
    now = time.monotonic()
    log = _request_log[ip]
    while log and now - log[0] > _RATE_WINDOW_SEC:
        log.popleft()
    if len(log) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({RATE_LIMIT_PER_MIN}/min). Try again shortly.",
        )
    log.append(now)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
)
def chat(req: ChatRequest) -> ChatResponse:
    if req.messages[-1].role != "user":
        raise HTTPException(400, "Last message must come from user")

    last_user = req.messages[-1].content
    topic = req.topic_filter if req.topic_filter != "auto" else None
    session_id = req.session_id or str(uuid.uuid4())

    # Cache hit (chỉ câu đơn lượt + topic auto) → trả ngay, bỏ qua retrieval + LLM.
    ck = _cache_key(req)
    cached = _cache_get(ck)
    if cached is not None:
        return ChatResponse(
            reply=cached["reply"],
            citations=[Citation(**c) for c in cached["citations"]],
            topic_detected=cached["topic_detected"],
            needs_vet=cached["needs_vet"],
            session_id=session_id,
        )

    chunks = retrieve(last_user, k=req.top_k, topic_filter=topic)

    if not chunks:
        return ChatResponse(
            reply="Mình chưa có đủ thông tin trong knowledge base để trả lời câu hỏi này. "
                  "Bạn thử hỏi cụ thể hơn (vd: tên giống mèo, triệu chứng cụ thể) hoặc liên hệ thú y.",
            citations=[],
            topic_detected=None,
            needs_vet=False,
            session_id=session_id,
        )

    # needs_vet: chunk severity=="high" CHỈ kích hoạt khi đủ liên quan
    # (rerank_score >= NEEDS_VET_MIN_RR) VÀ câu hỏi có ngôn ngữ cấp tính
    # (NEEDS_VET_REQUIRE_INTENT). Dry-run trên eval_external_set.json giữ 9/9 recall
    # cấp cứu đồng thời giảm over-trigger 8→1 (loại cry-wolf: đặt lồng, tiêm phòng,
    # hắt hơi, mắt đỏ... có chunk-high rr 0.98+ nhưng câu hỏi không cấp tính).
    needs_vet = _compute_needs_vet(chunks, last_user)

    topic_counts: dict[str, int] = {}
    for c in chunks:
        t = c.get("topic", "unknown")
        topic_counts[t] = topic_counts.get(t, 0) + 1
    topic_detected = max(topic_counts, key=topic_counts.get) if topic_counts else None

    try:
        reply = generate_reply(
            [m.model_dump() for m in req.messages],
            chunks,
            user_level=req.user_level,
        )
    except LLMUnavailable as e:
        # Hết quota mọi key / thiếu key / lỗi mạng → 503 thân thiện, không lộ
        # chuỗi lỗi kỹ thuật cho người dùng cuối. Chi tiết log ở server.
        print(f"[chat] LLM unavailable: {e.detail}")
        raise HTTPException(
            status_code=503,
            detail="Hệ thống đang tạm thời quá tải, bạn vui lòng thử lại sau ít phút nhé.",
            headers={"Retry-After": "30"},
        )

    # Server-side: ép banner cảnh báo thú y khi needs_vet (không phụ thuộc LLM
    # tự chèn — eval cho thấy LLM bỏ sót). Tránh nhân đôi nếu reply đã mở bằng ⚠.
    if needs_vet and not reply.lstrip().startswith("⚠"):
        reply = _VET_BANNER + reply

    citations = [
        Citation(
            index=i + 1,
            source_url=c.get("source_url", ""),
            source_name=c.get("source", ""),
            section_title=c.get("section_title"),
            snippet=(c.get("text", "")[:200] + "...") if len(c.get("text", "")) > 200
                    else c.get("text", ""),
        )
        for i, c in enumerate(chunks)
    ]

    _cache_put(ck, {
        "reply": reply,
        "citations": [c.model_dump() for c in citations],
        "topic_detected": topic_detected,
        "needs_vet": needs_vet,
    })

    return ChatResponse(
        reply=reply,
        citations=citations,
        topic_detected=topic_detected,
        needs_vet=needs_vet,
        session_id=session_id,
    )
