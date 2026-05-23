# meo-chatbot

Chatbot RAG tư vấn về mèo bằng tiếng Việt — sức khỏe, dinh dưỡng, giống, chăm sóc, hành vi.

## Kiến trúc

```
crawler/   →  data/raw/      →  data/cleaned/  →  data/chunks/  →  chromadb/
(crawl)       (1 file/bài)      (1 dòng/bài)     (chunk RAG)      (vector DB)
                                                                       ↓
                                                          retrieval + rerank + LLM
                                                                       ↓
                                                                  app/ (FastAPI)
```

## Setup (cho người mới clone repo)

### 1. Cài đặt

Yêu cầu: **Python 3.13+** và **uv** ([cài uv](https://docs.astral.sh/uv/getting-started/installation/)).

```powershell
git clone <repo-url>
cd meo-chatbot
uv sync          # cài tất cả deps từ uv.lock
```

### 2. Lấy data

Repo **không chứa data** (xem `.gitignore`). Có 3 lựa chọn:

#### Option A — Quick test (1 phút)
Chỉ crawl 20 bài từ 1 nguồn, đủ để test pipeline:
```powershell
uv run python -m crawler.crawl --source pethealth --limit 20
uv run python -m pipeline.chunker --source pethealth
```

#### Option B — Full crawl (~50 phút)
Lấy đầy đủ ~1400 bài từ 5 nguồn, giống production:
```powershell
uv run python -m crawler.crawl --source all
uv run python -m pipeline.chunker --source all
```

Theo dõi tiến độ ở terminal khác:
```powershell
.\scripts\progress.ps1
```

#### Option C — Download data đã sẵn (sau này)
*Khi vector DB đã ổn định, sẽ upload lên Hugging Face Dataset.*
```powershell
# huggingface-cli download monmoonluna/meo-chatbot-data --local-dir data/
```

### 3. Chạy chatbot (sau khi có API endpoint)

*Sẽ bổ sung khi `app/main.py` xong.*

## Nguồn data tiếng Việt

| Nguồn | Topic | Articles | License |
|---|---|---:|---|
| pethealth.vn | health | ~130 | Public blog (crawl per robots.txt) |
| mozzi.vn | nutrition | ~44 | Public blog |
| paddy.vn | care/behavior | ~367 | Public blog |
| tropicpet.vn | care/vet POV | ~539 | Public blog |
| champetsfamily.com | breed | ~332 | Public blog |

Mỗi chunk có metadata `source_url` để bot trích nguồn khi trả lời.

## Cấu trúc thư mục

```
meo-chatbot/
├── crawler/          # async crawler (httpx + trafilatura)
│   ├── sources.py    # config 5 nguồn
│   └── crawl.py
├── pipeline/         # chunking + classifying + ingest
│   └── chunker.py
├── scripts/
│   └── progress.ps1  # check tiến độ crawl
├── app/              # (chưa có) FastAPI service
├── data/             # (gitignored) crawl output + vectordb
└── pyproject.toml
```

## Tech stack

- **Python 3.13** + **uv** (deps + venv)
- **httpx + trafilatura** — crawl + extract
- **BAAI/bge-m3** — embedding song ngữ Việt-Anh
- **ChromaDB** — vector DB local
- **Gemini 2.0 Flash** — LLM (free tier)
- **FastAPI** — service cho team web
