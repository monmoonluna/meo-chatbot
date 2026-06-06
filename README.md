---
title: MeoBot
emoji: 🐱
colorFrom: pink
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---
# meo-chatbot

RAG chatbot tiếng Việt tư vấn về mèo — **sức khỏe, dinh dưỡng, giống, chăm sóc, hành vi**.

- 🐱 11 nguồn VN, **4,975 articles**, **76,487 chunks** đã embed
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
# Phải in: 76487
```

Sau khi download, **chạy chatbot ngay** không cần crawl/embed nữa.

> **Cập nhật khi data có phiên bản mới** (vd đã tải bản cũ trước đó): `snapshot_download`
> chỉ ghi đè file đổi theo hash, KHÔNG xoá file thừa → an toàn nhất là XOÁ data cũ rồi
> tải lại sạch. `git pull` để lấy code khớp data mới luôn.
> ```powershell
> git pull
> Remove-Item -Recurse -Force data\chromadb, data\chunks
> .\.venv\Scripts\python.exe scripts\download_data.py --repo-id Monmoonluna/meo-chatbot-data
> ```
> Kiểm tra `count` để biết đã lên bản mới chưa: **76487** = mới, **75264** = vẫn cũ.

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

## Deploy free (Hugging Face Spaces — Docker)

Toàn bộ stack chạy **$0/tháng** trên HF Spaces CPU Basic (2 vCPU, 16 GB RAM, 50 GB
disk) — đủ chứa cả 2 model + ChromaDB. Một Space = **một git repo có Dockerfile**;
deploy = thêm 2 file → push → set secret.

### 1. `Dockerfile` (ở gốc repo)

```dockerfile
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git && rm -rf /var/lib/apt/lists/*

# HF Spaces chạy non-root uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/app/hf-cache
WORKDIR /home/user/app

RUN pip install --user --no-cache-dir uv
COPY --chown=user . .
RUN uv sync --no-dev

# tải sẵn ChromaDB + chunks (~1 GB) từ HF dataset
RUN uv run python scripts/download_data.py --repo-id Monmoonluna/meo-chatbot-data
# (tuỳ chọn) cache model vào image → cold start nhanh; bỏ dòng này nếu build OOM
RUN uv run python -c "from app.retriever import warmup; warmup()"

EXPOSE 7860
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
```

### 2. Front-matter ở ĐẦU `README.md`

HF đọc block YAML ở dòng đầu tiên (phần còn lại của README giữ nguyên bên dưới):

```yaml
---
title: MiuCare Assistant
emoji: 🐱
colorFrom: pink
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---
```

### 3. Tạo Space + push code

Tạo Space tại https://huggingface.co/new-space → **SDK = Docker**, **Blank**. Rồi:

```powershell
git remote add space https://huggingface.co/spaces/<user>/meo-chatbot
git add Dockerfile README.md
git commit -m "Add HF Spaces Docker deploy"
git push space HEAD:main --force   # --force lần đầu để ghi đè boilerplate Space tự tạo
```

> Không push `data/` (đã gitignore) — Dockerfile tự tải lúc build. Khi hỏi mật khẩu,
> dùng **HF access token** (Settings → Access Tokens → write), không phải mật khẩu tài khoản.

### 4. Set secret + tinh chỉnh

Space → **Settings → Variables and secrets**:
- Secret `GEMINI_API_KEY` (hoặc `GEMINI_API_KEYS=key1,key2,...` để xoay vòng).
- (Khuyến nghị) Variable `MEO_RERANK_CANDIDATES=8`, `MEO_RERANK_MAX_LENGTH=384` để giữ
  request reranker dưới timeout proxy trên CPU free. Hoặc `MEO_RERANK=0` (≈5s, mất rerank-gate).

### 5. Test

App phục vụ ở root của Space:
- `https://<user>-meo-chatbot.hf.space/health` → `{"status":"ok"}`
- `https://<user>-meo-chatbot.hf.space/docs` → Try `/chat`

### Vận hành

- **Cập nhật code**: sửa → `git add` → `commit` → `git push space HEAD:main` (lần sau
  không cần `--force`) → HF tự build lại. Đổi **biến môi trường** → sửa Settings rồi
  **Restart** (không cần push). Đổi **data** → **Factory rebuild** để bỏ Docker cache.
- **Tắt máy không ảnh hưởng** — server chạy trên cloud HF, gọi API được từ mọi nơi.
- Free Space **ngủ sau ~48h** không ai gọi → request đầu chờ ~1-2 phút thức lại. Muốn
  luôn thức (vẫn free): ping `/health` định kỳ bằng UptimeRobot.

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

### Hội thoại nhiều lượt (multi-turn) — FE gửi context thế nào

Server **stateless** (không lưu lịch sử). Để bot hiểu câu tham chiếu ngược ("con
mèo này", "nó", "bé ấy"), **FE tự giữ hội thoại và gửi lại cả mảng `messages[]`
mỗi request** — các lượt cũ (cả `user` lẫn `assistant`) + câu hỏi mới ở cuối.

**Lượt 1** — FE gửi câu đầu, rồi LƯU `reply` nhận về:
```json
{ "messages": [ {"role": "user", "content": "Tôi nuôi một con mèo Maine Coon."} ] }
```

**Lượt 2** — FE gửi LỊCH SỬ + câu mới:
```json
{ "messages": [
    {"role": "user",      "content": "Tôi nuôi một con mèo Maine Coon."},
    {"role": "assistant", "content": "<reply của lượt 1>"},
    {"role": "user",      "content": "Con mèo này nên ăn gì?"}
] }
```
→ bot giải "con mèo này" = Maine Coon (cả khi trả lời lẫn khi truy hồi KB).

**Quy tắc cho FE:**
1. Giữ một mảng `messages` trong state (localStorage / DB / component state).
2. Mỗi lần user hỏi: thêm `{"role":"user","content": <câu mới>}` rồi POST cả mảng.
3. Nhận `reply` → thêm `{"role":"assistant","content": <reply>}` vào mảng.
4. `session_id` server trả về chỉ để FE log/analytics — **server KHÔNG dùng nó để nhớ**.

**Gửi bao nhiêu lịch sử:** ~6 lượt gần nhất là đủ (server dùng tối đa 6 lượt cho
prompt, 2 lượt user cuối cho retrieval; thừa thì tự cắt). Chỉ gửi câu mới mà bỏ
lịch sử → bot mất ngữ cảnh, không giải được tham chiếu.

## Nguồn dữ liệu (11 nguồn VN)

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

### Phase 3 — breed detail (lấp gap body-condition)
| Source | Note | Articles |
|---|---|---:|
| petchoice.vn | Breed chi tiết (sitemap đã verify) | 192 |

**Tổng: 4,975 articles** (11 nguồn, sau dedup URL) → **76,487 chunks**.

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
│   ├── sources.py       # 11 nguồn config (regex filter + topic hint)
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

**Kết quả đo** (45 câu; số deterministic từ run v7, faithfulness từ run judge gần nhất — xem ghi chú dưới bảng):

| Metric | Score | Ghi chú |
|---|---|---|
| Topic match (top-5 majority) | **34/45** (76%) | sau khi thêm reranker |
| Emergency → `needs_vet=true` | **9/9** (100%) | recall cấp cứu tuyệt đối |
| Emergency có banner ⚠️ | **9/9** (100%) | banner server-side, không phụ thuộc LLM |
| Over-trigger (câu lành tính) | **1/36** (3%) | rerank-gate (11→8) + intent-gate (8→1), recall vẫn 9/9 |
| Grounded (không bỏ cuộc) | **43/45** (96%) | 2 còn lại: 1 KB gap (Maine Coon), 1 soft-help |
| Có citation `[n]` | **45/45** (100%) | sau khi sửa max_output_tokens + tắt thinking |
| Latency (end-to-end /chat) | **~30s** | reranker ~28s (CPU) + LLM ~5s; trước ~90s. LLM riêng ~5s nhờ tắt thinking |
| **Faithfulness** (LLM-judge 1-5) | **4.86** | toàn bộ 45 câu (run `--judge` gần nhất) |
| **Faithfulness** — subset health/cấp cứu | **5.00** (n=15) | chấm LẠI sau khi đổi prompt/thinking/token-cap → KHÔNG regress (v3 subset ~4.57) |
| **Helpfulness** (LLM-judge 1-5) | **4.69** | toàn bộ 45 câu |

> Số deterministic (topic / needs_vet / grounded / citation) từ run generate-only
> v7 (`eval_external_results_v7.md`): thinking tắt, `max_output_tokens=2048`, eval
> harness đã sửa (truyền câu hỏi vào `_compute_needs_vet`). Faithfulness 4.86 từ run
> `--judge` đầy đủ gần nhất; sau 3 thay đổi generation của phiên này, đã chấm lại
> riêng subset health/cấp cứu (`--topic health --judge`, `v8_health.md`) = 5.00/5,
> xác nhận không hallucination trên các câu an toàn-trọng yếu. Full 45-câu re-judge
> hoãn do hạn ngạch free-tier. Chuỗi model `gemini-2.5-flash → 2.5-flash-lite →
> 2.0-flash → 2.0-flash-lite`, xoay vòng nhiều API key (`GEMINI_API_KEYS`).

**Baseline (trước cải tiến)** phát hiện 3 vấn đề → đã fix:

| Vấn đề (baseline) | Fix |
|---|---|
| Citations `[n]` rớt ~42% (18/31) | Prompt bắt buộc + ví dụ mẫu (`app/prompts.py`) |
| e5 cosine bị nén → topic precision thấp, give-up | **Cross-encoder rerank** top-20→top-5 (`app/retriever.py`) |
| `needs_vet` over-trigger ~1/3 câu lành tính | Rerank-gate + intent-gate (xem dưới) → còn 1/36 |

**`needs_vet` — 3 cổng an toàn** (recall cấp cứu LUÔN giữ **9/9**). Chunk
`severity=high` chỉ bật banner ⚠️ khi cả ba thoả:
1. **rerank-gate** — chunk đủ liên quan (`rerank_score ≥ 0.5`); reranker hỏng → fallback "any high" (không bao giờ tắt cảnh báo ngầm).
2. **intent-gate** — câu hỏi có ngôn ngữ cấp tính (`_ACUTE_INTENT`, ~120 biến thể). Vì `severity` là thuộc tính của *chunk*, không phải mức khẩn của *câu hỏi* (vd "đặt lồng vận chuyển ở đâu" vẫn kéo về chunk-high liên quan).
3. **severity tách khỏi topic** — tính cho cả `care` (không chỉ `health`) + bổ sung từ khoá sản khoa/sốc nhiệt (`khó đẻ`, `rặn lâu`, `say nắng`...) → cấp cứu ngoài health (vd đẻ khó) cũng kích hoạt.

Hai cổng đầu đưa over-trigger **11/36 → 1/36** mà không rớt recall. (Đã thử siết
theo `severity`/rank: mọi rule giảm over-trigger đều rớt recall cấp cứu tệ hơn 1:1
— keyword-nặng-trong-body vừa gây nhiễu lành tính VỪA là tín hiệu cấp cứu thật,
không tách được.) Banner **prepend server-side** (LLM hay bỏ sót). Tắt intent-gate:
`MEO_NEEDS_VET_REQUIRE_INTENT=0`.

**Guard:** `scripts/tune_needs_vet.py` (retrieval-only, không tốn quota) `assert`
recall 9/9 trên set gốc VÀ intent-recall đầy đủ trên 20 ca khẩu ngữ
(`emergency_stress_set.json`) — chạy lại sau mỗi lần sửa từ khoá.

**Topic routing 34/45 (76%) — phần lớn là *artifact thước đo*, không phải lỗi truy
hồi.** `topic_detected` = topic xuất hiện nhiều nhất trong top-5. Recall thật ~91%:
7/11 ca "sai" có topic đúng VẪN trong top-5 nhưng bị majority-vote đè, và là **chồng
lấn taxonomy** (vd "tiêm phòng" gắn `health` còn test kỳ vọng `care`) — answer vẫn
đúng (faithfulness xác nhận); chỉ ~1 ca thiếu nội dung thật → crawl thêm không đáng.
Đã vá vài **bug substring classifier** (`cá`→`các`, `ho`→`cho/khô`, `sán`→`sản`,
`chết`→`lông chết`) — keyword 2–3 ký tự khớp nhầm hàng chục nghìn chunk, bơm sai
topic/severity; bound bằng cụm cụ thể (behavior coverage +3.9k, health hết phình giả).

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

- **Latency ~30s/query** — reranker (bge-reranker-v2-m3, CPU) là ~99% (embed 0.07s,
  ChromaDB 0.05s). Đã tinh chỉnh 90s→30s qua `MEO_RERANK_CANDIDATES=10` +
  `MEO_RERANK_MAX_LENGTH=384` (KHÔNG hạ 256 — rớt 1 ca cấp cứu). Xuống <5s cần GPU /
  ONNX / reranker nhỏ hơn. Tắt nhanh: `MEO_RERANK=0` (mất rerank-gate của needs_vet).
- **Multi-turn do FE quản lý** — server stateless, FE gửi `messages[]` mỗi request
  (xem "Hội thoại nhiều lượt" ở phần API). Chưa có session store server-side (Redis)
  để FE chỉ gửi câu mới.
- **2 ca cấp cứu vẫn KB/ranking gap** — say nắng (bài có nhưng rerank rớt sát ngưỡng)
  + collapse. Body-condition theo giống còn mỏng (đã thêm nguồn petchoice).
- **Single-instance** — ChromaDB local, không scale ngang → production cần Qdrant Cloud.
- **Windows OS silent-kill** khi crawl (Defender?) — workaround auto-restart + Task
  Scheduler; Linux deploy không gặp.
- **`sentence_transformers` crash trên vài máy Windows** — retriever bypass bằng
  `transformers` trực tiếp (output bit-exact). Ingest vẫn dùng nó; nếu fail → tải
  data sẵn từ HF.
- **SDK** — đã migrate `google-genai`; gỡ `google-generativeai` (deprecated).

## License & Data ethics

- **Code**: MIT (default)
- **Data crawled**: respected robots.txt; lưu `source_url` trong metadata để minh bạch khi bot trích nguồn. Không redistribute nguyên văn — chỉ retrieve làm context cho LLM.
- **Models**: bge-m3 (MIT), multilingual-e5-small (MIT), Gemini API (Google ToS).
