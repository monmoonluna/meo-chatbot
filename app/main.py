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

    # needs_vet stays intentionally PERMISSIVE: trigger if ANY retrieved (reranked)
    # chunk is severity=="high". Empirically tuned on scripts/eval_external_set.json
    # (scripts/tune_needs_vet.py): this is the only rule that keeps 6/6 emergency
    # recall. Tighter rules (high in top-1/top-2, ≥2-of-top-3) each MISS 2-3 real
    # emergencies because some — e.g. blood in stool, cystitis — don't rank their
    # high-severity chunk first. Safety recall dominates here; the residual
    # over-trigger (~7/25 benign queries) is a severity *labeling* issue (some
    # benign chunks like travel-safety are mislabeled high) to fix in
    # pipeline/classifier.py, NOT by weakening this gate. content_type=="warning"
    # is far too broad (~22% of KB) and deliberately does NOT drive needs_vet.
    needs_vet = any(c.get("severity") == "high" for c in chunks)

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
