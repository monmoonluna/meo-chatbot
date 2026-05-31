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
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .llm import generate_reply
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

# Banner cảnh báo thú y, server-side prepend khi needs_vet=True. Trước đây phụ
# thuộc LLM tự chèn → eval cho thấy LLM bỏ sót 9/9 → ép server-side để chắc chắn.
_VET_BANNER = (
    "⚠️ **Dấu hiệu này có thể nghiêm trọng — hãy đưa mèo đến bác sĩ thú y để được "
    "khám trực tiếp.** Thông tin dưới đây chỉ mang tính tham khảo, không thay thế "
    "chẩn đoán của thú y.\n\n"
)


def _compute_needs_vet(chunks: list[dict]) -> bool:
    """True nếu có chunk severity=='high' VÀ đủ liên quan (rerank_score >= ngưỡng).

    Khi rerank_score thiếu (None) hoặc reranker tắt (0 cho mọi chunk high) →
    fallback về "any high" để giữ an toàn (recall ưu tiên hơn precision).
    """
    high = [c for c in chunks if c.get("severity") == "high"]
    if not high:
        return False
    if NEEDS_VET_MIN_RR <= 0:
        return True
    rrs = [c.get("rerank_score") for c in high]
    if all(rr is None or rr == 0 for rr in rrs):
        return True  # reranker off/failed → đừng tắt cảnh báo
    return any(rr is not None and rr >= NEEDS_VET_MIN_RR for rr in rrs)


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

    chunks = retrieve(last_user, k=req.top_k, topic_filter=topic)
    session_id = req.session_id or str(uuid.uuid4())

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
    # (rerank_score >= NEEDS_VET_MIN_RR). Dry-run trên eval_external_set.json giữ
    # 9/9 recall cấp cứu (sàn rr của chunk-high = 0.937) đồng thời loại flag sai
    # rõ ràng (Maine Coon gầy rr=0.11, mèo gạt đồ rr=0.25). Xem _compute_needs_vet.
    needs_vet = _compute_needs_vet(chunks)

    topic_counts: dict[str, int] = {}
    for c in chunks:
        t = c.get("topic", "unknown")
        topic_counts[t] = topic_counts.get(t, 0) + 1
    topic_detected = max(topic_counts, key=topic_counts.get) if topic_counts else None

    reply = generate_reply(
        [m.model_dump() for m in req.messages],
        chunks,
        user_level=req.user_level,
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

    return ChatResponse(
        reply=reply,
        citations=citations,
        topic_detected=topic_detected,
        needs_vet=needs_vet,
        session_id=session_id,
    )
