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
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
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

    needs_vet = any(
        c.get("severity") == "high" or c.get("content_type") == "warning"
        for c in chunks
    )

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
