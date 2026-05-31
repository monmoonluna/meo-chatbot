# meo-chatbot

RAG chatbot tiếng Việt tư vấn về mèo — **sức khỏe, dinh dưỡng, giống, chăm sóc, hành vi**.

- 🐱 10 nguồn VN, **2,927 articles**, **75,264 chunks** đã embed
- 🔒 An toàn: severity=high → bot bắt buộc khuyên đi thú y
- 📚 Citations: mỗi câu trả lời kèm 5 nguồn gốc click được
- 💰 Stack 100% free tier: e5-small local + Gemini free + ChromaDB local

## Kiến trúc

```
crawler/       →  data/raw/        →  data/cleaned/   →  data/chunks/   →  data/chromadb/
(httpx +          (1 file/bài,        (consolidated      (section-aware    (e5-small
 trafilatura)      idempotent)         JSONL)             chunking +        vectors,
                                                          metadata)         ChromaDB local)
                                                                              │
                                                                              ▼
            POST /chat ──► app/main.py (FastAPI) ◄── retriever → top-20 → reranker → top-5 → Gemini
                                                                  ▲                ▲
                                                       e5-small embedding   bge-reranker-v2-m3
                                                                          (cross-encoder)
```

## Setup (cho người clone repo)

Yêu cầu: **Python 3.13+** và **[uv](https://docs.astral.sh/uv/getting-started/installation/)**.

```powershell
git clone https://github.com/monmoonluna/meo-chatbot
cd meo-chatbot
uv sync          # cài deps theo uv.lock

# (Khuyến nghị) move HF model cache sang ổ D
[Environment]::SetEnvironmentVariable('HF_HOME', 'D:\hf-cache', 'User')
```

## Lấy dữ liệu (3 phương án)

Repo **KHÔNG chứa data** — gitignore. Reproducible từ `crawler/sources.py`.

### A. Quick smoke test (1 phút)
```powershell
.\.venv\Scripts\python.exe -m crawler.crawl --source pethealth --limit 20
.\.venv\Scripts\python.exe -m pipeline.chunker --source pethealth
```

### B. Full crawl + pipeline (~3-5 giờ)
```powershell
# Crawl 10 sources tuần tự (resilient to OS kills via auto-restart wrapper)
.\scripts\run_phase2_pipeline.ps1

# Hoặc từng bước manual
.\.venv\Scripts\python.exe -m crawler.crawl --source all
.\.venv\Scripts\python.exe -m pipeline.chunker --source all
.\.venv\Scripts\python.exe -m pipeline.classifier
.\.venv\Scripts\python.exe -m pipeline.ingest
```

Nếu Python bị OS kill (Windows Defender quét định kỳ), dùng scheduled task:
```powershell
.\scripts\setup_scheduler.ps1   # task chạy mỗi 10 phút, tự skip nếu đã đủ
```

### C. Download data sẵn từ Hugging Face (NHANH NHẤT, ~5 phút thay vì 4h)

**Người chia sẻ** (upload 1 lần):
```powershell
# 1. Tạo HF account + Write token: https://huggingface.co/settings/tokens
.\.venv\Scripts\hf.exe auth login   # paste token

# 2. Upload (~1 GB: chromadb + classified chunks)
.\.venv\Scripts\python.exe scripts\upload_data.py --repo-id YOUR_USERNAME/meo-chatbot-data
# Tuỳ chọn: --private, --include-cleaned
```

> ⚠️ `huggingface_hub` Python API có thể hang ở step commit khi file > 100 MB.
> Nếu upload bị stuck cuối, kill Python và dùng `hf` CLI cho file riêng lẻ:
> ```powershell
> .\.venv\Scripts\hf.exe upload YOUR_USERNAME/meo-chatbot-data `
>   path\to\file path/in/repo --repo-type dataset
> ```

**Người clone repo** (download 1 lần):
```powershell
.\.venv\Scripts\python.exe scripts\download_data.py --repo-id Monmoonluna/meo-chatbot-data
# → tải về data/chromadb + data/chunks (~1 GB)

# Verify:
.\.venv\Scripts\python.exe -c "import chromadb; print(chromadb.PersistentClient('data/chromadb').get_collection('meo_kb').count())"
# Phải in: 75264
```

Sau khi download, **chạy chatbot ngay** không cần crawl/embed nữa.

## Chạy chatbot

```powershell
# 1. Lấy Gemini API key free tại https://aistudio.google.com/app/apikey
Copy-Item .env.example .env
# (mở .env, paste key vào GEMINI_API_KEY=...)

# 2. Run server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# 3. Mở http://localhost:8000/docs → Try /chat
```

Test bằng curl:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Mèo Anh lông ngắn ăn gì?"}]}'
```

## API contract (cho team web tích hợp)

### `POST /chat`

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "Mèo bỏ ăn 2 ngày có sao không?"}
  ],
  "session_id": "optional-uuid",
  "user_level": "auto",
  "topic_filter": "auto",
  "top_k": 5
}
```

**Response:**
```json
{
  "reply": "⚠️ Đây có thể là tình huống cần thú y khẩn cấp...",
  "citations": [
    {
      "index": 1,
      "source_url": "https://pethealth.vn/...",
      "source_name": "pethealth",
      "section_title": "...",
      "snippet": "..."
    }
  ],
  "topic_detected": "health",
  "needs_vet": true,
  "session_id": "..."
}
```

Khi `needs_vet=true`, team web nên render **banner đỏ** kèm số hotline thú y.

### `GET /health`
Trả `{"status": "ok"}` để liveness check.

## Nguồn dữ liệu (10 nguồn VN)

### Phase 1 — đa chủ đề
| Source | Topic mạnh | Articles |
|---|---|---:|
| pethealth.vn | Bệnh lý (ca thực tế) | 132 |
| paddy.vn | Care + behavior | 366 |
| tropicpet.vn | Care từ góc nhìn vet | 541 |
| mozzi.vn | Dinh dưỡng | 46 |
| champetsfamily.com | Breed (chi tiết nhất) | 335 |

### Phase 2 — focus behavior
| Source | Note | Articles |
|---|---|---:|
| petspace.vn | Đọc vị cảm xúc | 25 |
| petthings.vn | 14 điều không nên + ghen | 75 |
| kingspet.vn | Trầm cảm + ghét chủ | 391 |
| fagopet.vn | Trầm cảm chi tiết | 400 |
| mochicat.vn | Cào, sợ hãi, đa dạng | 2,483 |

**Tổng: 4,794 articles** (sau dedup URL: 2,927).

## Tech stack

| Layer | Tool | Lý do |
|---|---|---|
| Crawl | `httpx` + `trafilatura` | Async, robust HTML extract |
| Chunker | Python heuristic | Section-aware, prepend heading |
| Classifier | Rule-based VN keywords + fallback | Fast, deterministic, no LLM cost |
| Embedding (ingest) | `sentence-transformers` + e5-small | Batched bulk encode, normalize |
| Embedding (retriever) | `transformers` AutoModel + manual mean-pool | Robust khi sentence_transformers crash trên 1 số máy Windows (xem Troubleshooting) |
| Reranker | `bge-reranker-v2-m3` (transformers cross-encoder) | e5 cosine bị nén (~0.94-0.96); cross-encoder tách bạch relevance → top-20 rerank → top-5. Tự tắt graceful nếu model chưa tải |
| Vector DB | `chromadb` PersistentClient | Free, no server, embedded |
| LLM | `gemini-2.5-flash` (fallback chain) | Free tier 1500/day |
| API | `fastapi` + `uvicorn` | Auto OpenAPI docs cho team web |

## Scripts reference

```
scripts/
├── progress.ps1               # Crawl progress bar (10 sources)
├── spot_check.py              # Sample random chunks để verify quality
├── eval_queries.py            # 30-query suite thủ công + auto-flag issues
├── eval_external.py           # External suite: câu hỏi dataset công khai + LLM-judge
├── eval_external_set.json     # 45 câu hỏi thật (playcat Q&A) đã dịch VN
├── tune_needs_vet.py          # So sánh các rule needs_vet trên external set
├── test_retrieval.py          # Test retrieval không cần Gemini key
├── crawl_with_restart.ps1     # Auto-restart crawler (silent kill resilient)
├── run_phase2_pipeline.ps1    # Omnibus crawl → chunk → classify → ingest → eval
├── finish_pipeline.ps1        # Auto-restart ingest + eval
├── run_ingest_once.ps1        # Single-pass ingest cho Task Scheduler
└── setup_scheduler.ps1        # Register Windows scheduled task (OS-level resilient)
```

## Cấu trúc project

```
meo-chatbot/
├── crawler/             # Async sitemap crawler
│   ├── sources.py       # 10 nguồn config (regex filter + topic hint)
│   └── crawl.py
├── pipeline/            # Data processing
│   ├── chunker.py       # Section-aware, ≤800 tokens/chunk
│   ├── classifier.py    # 4 metadata fields: topic/content_type/severity/level
│   └── ingest.py        # Embed + incremental ChromaDB load
├── app/                 # FastAPI service
│   ├── main.py          # /chat endpoint
│   ├── retriever.py     # e5-small + ChromaDB top-k
│   ├── llm.py           # Gemini multi-model fallback
│   ├── prompts.py       # System prompt + safety rules
│   └── schemas.py       # Pydantic API contract
├── scripts/             # Operational helpers
├── data/                # (gitignored) crawl + chunks + ChromaDB
├── .env.example
└── pyproject.toml
```

## Đánh giá chất lượng

### A. Internal suite — 30 query thủ công (`scripts/eval_queries.py`)

| Metric | Score |
|---|---|
| Retrieval top-1 đúng topic | **29/30** (97%) |
| Emergency → `needs_vet=true` | **6/6** (100%) |
| LLM grounded (không bịa) | ✓ — báo "không đủ thông tin" khi context không đủ |
| Multi-topic queries | 5/5 OK |

```powershell
.\.venv\Scripts\python.exe scripts\eval_queries.py            # retrieval-only
.\.venv\Scripts\python.exe scripts\eval_queries.py --with-llm # full RAG
```

### B. External suite — câu hỏi thật từ dataset công khai (`scripts/eval_external.py`)

45 câu hỏi mèo thật trích từ HuggingFace `playcat/playcat-cat-behavior-new-data-set`
(community Q&A: r/CatAdvice, r/AskVet, r/cats, r/CATHELP, StackExchange Pets), dịch
sang tiếng Việt tự nhiên, cân bằng 5 topic + 9 ca khẩn cấp thật. Bộ câu hỏi ở
`scripts/eval_external_set.json`. Có thêm **LLM-as-judge** (Gemini chấm faithfulness
+ helpfulness 1-5).

```powershell
# Full RAG + judge (tốn ~2 Gemini call/câu)
.\.venv\Scripts\python.exe scripts\eval_external.py --with-llm --judge
```

**Kết quả đo — retrieval + safety** (45 câu, đo lại 2 lần ra cùng số → ổn định,
không phụ thuộc LLM):

| Metric | Score | Ghi chú |
|---|---|---|
| Topic match (top-5 majority) | **34/45** (76%) | sau khi thêm reranker |
| Emergency → `needs_vet=true` | **9/9** (100%) | recall cấp cứu tuyệt đối |
| Over-trigger (câu lành tính) | **10/36** (28%) | severity mislabel — xem dưới |

> **Faithfulness / helpfulness (LLM-as-judge): chưa có số sạch.** Free-tier
> Gemini cạn quota ngày (RPD) khi chạy cả batch → phần lớn reply là lỗi
> `ResourceExhausted`. Chạy lại `--judge` sau khi quota reset (hoặc bật billing)
> để điền. *KHÔNG* lấy số faithfulness từ run bị quota chặn — nó vô nghĩa.

**Baseline (trước cải tiến)** phát hiện 3 vấn đề → đã fix:

| Vấn đề (baseline) | Fix |
|---|---|
| Citations `[n]` rớt ~42% (18/31) | Prompt bắt buộc + ví dụ mẫu (`app/prompts.py`) |
| e5 cosine bị nén → topic precision thấp, give-up | **Cross-encoder rerank** top-20→top-5 (`app/retriever.py`) |
| `needs_vet` over-trigger ~1/3 câu lành tính | Giữ rule permissive (xem dưới) — fix gốc ở classifier |

**`needs_vet` — tune bằng `scripts/tune_needs_vet.py`** (an toàn > precision):

| Rule | Emergency recall | False-positive |
|---|---|---|
| `any high in top-5` (đang dùng) | **6/6** | 7/25 |
| `high in top-2` | 4/6 ❌ | 3/25 |
| `high in top-1` | 3/6 ❌ | 1/25 |

Các rule chặt hơn **bỏ sót 2-3 ca cấp cứu thật** (vd máu trong phân, viêm bàng
quang — chunk severity=high không phải lúc nào cũng rank 1) → giữ rule permissive,
chấp nhận over-trigger. Over-trigger còn lại là do **mislabel severity** ở
`pipeline/classifier.py`, không phải lỗi gate.

## Troubleshooting

Các vấn đề thực tế đã gặp khi cài/chạy + cách fix:

### 1. `uvicorn` đứng mãi ở "Warming up retriever..."

Nguyên nhân thường gặp (xếp theo khả năng cao → thấp):

**a) Model chưa download xong** — `sentence_transformers` tải model im lặng không hiện progress.
```powershell
# Pre-download bằng hf CLI (verbose) trước khi chạy uvicorn
.\.venv\Scripts\hf.exe download intfloat/multilingual-e5-small
```

**b) `HF_HOME` trỏ về folder rỗng** — `app/retriever.py` set `HF_HOME=D:\hf-cache` nếu có ổ D:, nhưng model thật ở `C:\Users\<user>\.cache\huggingface\`. Hai cách fix:
```powershell
# Option 1: unset HF_HOME, dùng default C:
[Environment]::SetEnvironmentVariable('HF_HOME', $null, 'User')
$env:HF_HOME = $null

# Option 2: download trực tiếp về D:
$env:HF_HOME = "D:\hf-cache"
.\.venv\Scripts\hf.exe download intfloat/multilingual-e5-small
```

> ⚠️ **KHÔNG dùng `Move-Item` để chuyển cache từ C: sang D:** — sẽ phá symlinks/cấu trúc → SentenceTransformer tìm file không thấy → hang. Luôn re-download bằng `hf download`.

### 2. `import sentence_transformers` crash Python im lặng

Một số máy Windows (torch 2.12 + transformers 5.9) → segfault không trace.

Đã workaround bằng cách dùng `transformers.AutoModel` thay vì `sentence_transformers` trong `app/retriever.py`. Output bit-exact identical, ChromaDB vectors giữ nguyên valid.

Test phát hiện crash:
```powershell
python -c "import sentence_transformers; print('OK')"  # rỗng = đã crash
python -c "from transformers import AutoModel; print('OK')"  # in OK = ổn
```

Nếu cả 2 đều fail → reinstall: `pip install --force-reinstall transformers`.

### 3. HuggingFace upload hang ở 99% (file > 100MB)

`huggingface_hub` Python API có bug hang ở step commit cuối. Workaround:
```powershell
# Kill Python đang stuck, upload từng file qua hf CLI
.\.venv\Scripts\hf.exe upload <repo-id> <local-file> <repo-path> --repo-type dataset
```

### 4. Crawler bị OS kill sau ~17 phút (Windows Defender?)

Pipeline đã có 2 layer workaround:
- `scripts/crawl_with_restart.ps1` — PowerShell auto-restart loop
- `scripts/setup_scheduler.ps1` — Windows Task Scheduler (resilient nhất, scheduler service ở SYSTEM level)

Khi crawl hoặc ingest đứng > 5 phút mà file count không tăng → kill + relaunch hoặc dùng scheduler.

## Known limitations / Future work

- **Behavior topic ~2-3%** trong corpus — Phase 2 sources tag `topic_hint=behavior` nhưng classifier flip nhiều sang topic khác. Tune classifier hoặc thêm nguồn behavior-only.
- **Severity over-labeling** — một số chunk lành tính (vd "an toàn khi di chuyển bằng xe") bị gán `severity=high` → `needs_vet` over-trigger ~7/25 câu lành tính trong external suite. Fix gốc: tune `pipeline/classifier.py`, KHÔNG siết `needs_vet` gate (sẽ bỏ sót cấp cứu — xem Đánh giá chất lượng phần B).
- **Breed coverage mỏng** — community Q&A gần như không có câu hỏi giống; KB breed chủ yếu dựa champetsfamily. Cần thêm nguồn breed-specific (sitemap phải verify thật, đừng đoán URL).
- **Reranker tăng latency** — bge-reranker-v2-m3 chấm 20 cặp/query trên CPU (~5-8s). Set `MEO_RERANK=0` để tắt (fallback e5 ordering) nếu cần nhanh; hoặc chạy GPU.
- **Stateless** — `session_id` chỉ trả về, không lưu lịch sử. Team web phải gửi `messages[]` mỗi request hoặc tự lưu Redis.
- **Single-instance** — ChromaDB local, không scale horizontal. Để production cần switch lên Qdrant Cloud hoặc tương tự.
- **`google-generativeai` deprecated** — chưa migrate sang `google-genai` (warning, không fail).
- **OS silent-killer trên Windows** — pipeline đã có workaround (Task Scheduler) nhưng nguyên nhân chưa rõ (có thể Defender / scheduled tasks). Linux deploy sẽ không gặp.
- **`sentence_transformers` không tin cậy trên 1 số máy Windows** — retriever đã bypass dùng `transformers` trực tiếp. Ingest vẫn dùng `sentence_transformers`; nếu fail trên máy bạn, có thể sửa `pipeline/ingest.py` theo cùng pattern hoặc download data sẵn từ HF (không cần re-ingest).

## License & Data ethics

- **Code**: MIT (default)
- **Data crawled**: respected robots.txt; lưu `source_url` trong metadata để minh bạch khi bot trích nguồn. Không redistribute nguyên văn — chỉ retrieve làm context cho LLM.
- **Models**: bge-m3 (MIT), multilingual-e5-small (MIT), Gemini API (Google ToS).
