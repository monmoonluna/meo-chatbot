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
| **Faithfulness** (LLM-judge 1-5) | **4.86** | *(run judge gần nhất; v7 generate-only chưa chấm lại)* |
| **Helpfulness** (LLM-judge 1-5) | **4.69** | *(run judge gần nhất)* |

> Số deterministic (topic / needs_vet / grounded / citation) từ run generate-only
> v7 (`eval_external_results_v7.md`): thinking tắt, `max_output_tokens=2048`, eval
> harness đã sửa (truyền câu hỏi vào `_compute_needs_vet`). Faithfulness/Helpfulness
> giữ từ run `--judge` đầy đủ gần nhất (chưa chấm lại do hạn ngạch free-tier).
> Chuỗi model `gemini-2.5-flash → 2.5-flash-lite → 2.0-flash → 2.0-flash-lite`,
> xoay vòng nhiều API key (`GEMINI_API_KEYS`).

**Baseline (trước cải tiến)** phát hiện 3 vấn đề → đã fix:

| Vấn đề (baseline) | Fix |
|---|---|
| Citations `[n]` rớt ~42% (18/31) | Prompt bắt buộc + ví dụ mẫu (`app/prompts.py`) |
| e5 cosine bị nén → topic precision thấp, give-up | **Cross-encoder rerank** top-20→top-5 (`app/retriever.py`) |
| `needs_vet` over-trigger ~1/3 câu lành tính | Rerank-gate + intent-gate (xem dưới) → còn 1/36 |

**`needs_vet` — rerank-relevance gate** (an toàn > precision): chunk `severity=high`
chỉ bật cảnh báo khi nó đủ **liên quan** (`rerank_score >= 0.5`); nếu reranker
tắt/hỏng thì fallback về "any high" để không bao giờ tắt cảnh báo ngầm.

| Rule | Emergency recall | Over-trigger |
|---|---|---|
| `any high in top-5` (cũ) | **9/9** | 11/36 |
| `high + rerank_score>=0.5` | **9/9** | 8/36 |
| `high + rr>=0.5 + intent` (đang dùng) | **9/9** | **1/36** |
| `high in top-2` | 4/6 ❌ | — |
| `high in top-1` | 3/6 ❌ | — |

Các rule "rank-based" chặt hơn **bỏ sót ca cấp cứu thật** (vd máu trong phân, viêm
bàng quang — chunk severity=high không phải lúc nào cũng rank 1). Rerank gate giữ
9/9 recall (sàn `rerank_score` của chunk-high ở câu cấp cứu = 0.937) mà loại các
flag rõ ràng sai (Maine Coon gầy `rr=0.11`, mèo gạt đồ vật `rr=0.25`).

**Còn 8/36 over-trigger — đã thử fix ở classifier, KẾT LUẬN: không nên.** Phân tích
10.590 chunk `high` cho thấy phần lớn được gán high vì keyword nặng (vd `khó thở`,
`khối u`, `tử vong`) nằm trong **body** như nhắc thoáng qua, không phải tiêu đề. Thử
2 rule chặt hơn (validate offline trên đúng chunk v3 đã retrieve):

| Rule severity | Emergency recall | Over-trigger |
|---|---|---|
| `any HIGH_SEVERITY kw` (đang dùng) | **9/9** | 8/36 |
| kw phải nằm trong **title** | 4/9 ❌ | 2/36 |
| hybrid (kw cấp tính ở body OK, tên bệnh mãn tính chỉ tính ở title) | 7/9 ❌ | 7/36 |

→ **Trên trục `severity` của chunk, mọi rule giảm over-trigger đều giảm recall cấp
cứu, tỉ lệ tệ hơn 1:1** (hybrid mất 2 ca thật — viêm bàng quang tái phát, nôn liên
tục — để đổi lấy 1 ca lành tính). Lý do: keyword-nặng-trong-body vừa gây over-trigger
lành tính VỪA là tín hiệu bắt cấp cứu thật — **không tách được bằng severity**.

**`needs_vet` — intent-gate (đòn bẩy thứ 2, trục câu hỏi).** Phân tích rerank cho thấy
7/8 câu lành tính over-trigger lại có chunk-high **rất liên quan** (`rr` 0.98–0.999,
vượt cả sàn cấp cứu 0.937) → ngưỡng `rr` đã cạn (chỉ hạ được 11→8). Mấu chốt:
`severity` là thuộc tính của **chunk**, không phải mức cấp tính của **câu hỏi**. "Đặt
lồng vận chuyển ở đâu" kéo về chunk-high liên quan nhưng bản thân câu hỏi không cấp
tính. Nên thêm cổng cấp 2: chỉ bật banner khi **câu hỏi** chứa ngôn ngữ cấp tính
(`khó thở`, `nôn liên tục`, `máu`, `không đi tiểu`, `ngộ độc`... — list red-flag
cố tình rộng, xem stress-test bên dưới). Dry-run `eval_external_set.json`:
**over-trigger 8→1, recall giữ 9/9**
(ca còn lại "mèo bỏ ăn đợi bao lâu" — `bỏ ăn >24h` là red-flag thật, chấp nhận được).

Bật/tắt bằng `MEO_NEEDS_VET_REQUIRE_INTENT` (mặc định 1; đặt 0 → về cổng chỉ-rr).

**Rủi ro keyword → stress-test để vá.** Intent dựa trên keyword nên câu cấp cứu diễn
đạt khẩu ngữ/gián tiếp có thể lọt. Đã soạn `scripts/emergency_stress_set.json` (20 ca
cấp cứu thật phrasing đời thường: `liếm phải thuốc tẩy`, `sùi bọt mép`, `thở khó`,
`rặn mãi mà không thấy nước tiểu`, `rơi từ tầng 3`, `ăn nhầm bả chuột`, `gặm phải lá
bách hợp`, `mắt lồi`...). List hẹp ban đầu **lọt 11/20** → mở rộng `_ACUTE_INTENT`
(~120 biến thể, gom theo nhóm hô hấp/thần kinh/ngộ độc/tiết niệu/...) → **intent
recall 17/17** (ca có chunk-high liên quan), mà over-trigger trên set gốc **vẫn 1/36**.
Còn **3 ca KB-coverage gap** (đẻ khó, mèo sơ sinh hạ thân nhiệt, ọe dịch vàng) —
retrieve KHÔNG ra chunk severity=high nào → intent không cứu được, đây là **lỗ hổng
nội dung KB** (mục tiêu crawl tương lai), không phải lỗi gate.

**Regression-guard:** `scripts/tune_needs_vet.py` (retrieval-only, không tốn quota)
`assert` cả hai: recall 9/9 trên set gốc VÀ intent-recall đầy đủ trên stress set —
chạy lại sau mỗi lần sửa `_ACUTE_INTENT`.

Khi `needs_vet=true`, server **tự prepend banner ⚠️** (không phụ thuộc LLM tự chèn —
eval cho thấy LLM bỏ sót 9/9). Logic: `app/main.py:_compute_needs_vet`.

**Topic routing 34/45 — điều tra kỹ: phần lớn là *artifact của thước đo*, không phải
lỗi truy hồi.** `topic_detected` = `topic` xuất hiện nhiều nhất trong top-5 (count
majority). Ba phát hiện (validate offline trên đúng top-5 đã retrieve):

1. **Đổi cách bình chọn là no-op.** count = rerank-weighted = e5-weighted → **đúng
   y hệt 34/45**, sai cùng các câu. Không ship đổi voting.
2. **Recall thực = 41/45 (91%).** Trong 11 ca "sai", **7 ca** topic đúng VẪN nằm
   trong top-5 nhưng bị majority-vote đè; nội dung truy hồi đúng (vd "mèo con tiêm
   phòng khi nào" → top hit *Lịch Tiêm Phòng Cho Mèo Con* rr=0.999, chỉ "sai" vì
   tiêm phòng gắn nhãn `health` còn test-set kỳ vọng `care`). Đây là **chồng lấn
   taxonomy**, không phải answer sai (faithfulness 4.86 xác nhận). Chỉ **~1 ca** là
   thiếu nội dung thật (Maine Coon gầy — body-condition theo giống, rr cao nhất 0.42).
   → Crawl thêm KB **không đáng** cho 1 ca; "76%" đánh giá thấp chất lượng thực.
3. **Một bug nhãn ĐÃ fix:** keyword nutrition `"cá"` (2 ký tự) khớp nhầm `"các"`
   (từ tiếng Việt cực phổ biến) như substring → fire ở **69.363/75.264 chunk (92%)**,
   trong đó **82% là nhiễu `các`** chứ không phải cá (thức ăn). Bơm điểm nutrition sai
   → flip nhầm (vd nội dung "giới thiệu thú cưng mới" bị gắn `nutrition`). Fix: thay
   `"cá"` trần bằng cụm cụ thể (`cá hồi`, `cá ngừ`, `thịt cá`, `ăn cá`). Kết quả
   re-classify: `nutrition` 14%→8% (bỏ nhãn thừa), `health` **+1.460 chunk** (severity
   `high` 10.590→10.765 → cảnh báo cấp cứu MẠNH hơn, không yếu đi), chỉ 7 chunk rời
   health. Áp dụng bằng `pipeline.ingest` update metadata-only (không re-embed).

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
- **`needs_vet` over-trigger 8/36 câu lành tính** — đã giảm từ 10/36 bằng rerank-relevance gate. Đã điều tra fix sâu hơn ở `pipeline/classifier.py` và **kết luận không khả thi**: keyword nặng trong body vừa gây over-trigger vừa là tín hiệu bắt cấp cứu thật, mọi rule severity chặt hơn đều làm rớt recall cấp cứu tệ hơn 1:1 (xem bảng ở Đánh giá chất lượng phần B). 8/36 là cái giá chấp nhận được cho recall 9/9.
- **Breed coverage mỏng** — community Q&A gần như không có câu hỏi giống; KB breed chủ yếu dựa champetsfamily. Cần thêm nguồn breed-specific (sitemap phải verify thật, đừng đoán URL).
- **Reranker là 99% latency** — profile cho thấy embed ~0.07s, ChromaDB ~0.05s,
  nhưng bge-reranker-v2-m3 (XLM-R-large, 568M) chấm cặp trên CPU là phần còn lại.
  Đã tinh chỉnh: `MEO_RERANK_CANDIDATES=10` (giảm từ 20) + `MEO_RERANK_MAX_LENGTH=384`
  (giảm từ 512) → ~80s xuống ~28s/query mà **vẫn giữ recall cấp cứu 9/9**
  (`tune_needs_vet.py`). KHÔNG hạ max_length xuống 256 (làm rớt 1 ca cấp cứu → 8/9).
  Cần nhanh hơn nữa: `MEO_RERANK=0` (tắt rerank, fallback e5 — nhưng mất rerank-gate
  của needs_vet), reranker nhỏ hơn (phải re-validate ngưỡng gate), hoặc GPU.
- **Stateless** — `session_id` chỉ trả về, không lưu lịch sử. Team web phải gửi `messages[]` mỗi request hoặc tự lưu Redis.
- **Single-instance** — ChromaDB local, không scale horizontal. Để production cần switch lên Qdrant Cloud hoặc tương tự.
- **SDK Gemini** — đã migrate sang `google-genai` (SDK mới); `google-generativeai` cũ (deprecated) đã gỡ khỏi dependencies.
- **OS silent-killer trên Windows** — pipeline đã có workaround (Task Scheduler) nhưng nguyên nhân chưa rõ (có thể Defender / scheduled tasks). Linux deploy sẽ không gặp.
- **`sentence_transformers` không tin cậy trên 1 số máy Windows** — retriever đã bypass dùng `transformers` trực tiếp. Ingest vẫn dùng `sentence_transformers`; nếu fail trên máy bạn, có thể sửa `pipeline/ingest.py` theo cùng pattern hoặc download data sẵn từ HF (không cần re-ingest).

## License & Data ethics

- **Code**: MIT (default)
- **Data crawled**: respected robots.txt; lưu `source_url` trong metadata để minh bạch khi bot trích nguồn. Không redistribute nguyên văn — chỉ retrieve làm context cho LLM.
- **Models**: bge-m3 (MIT), multilingual-e5-small (MIT), Gemini API (Google ToS).
