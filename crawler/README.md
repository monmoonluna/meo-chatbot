# Crawler — 5 nguồn tiếng Việt về mèo

## Nguồn đã chọn

| name | URL | Ưu tiên RAG | Mảng mạnh |
|------|-----|-------------|-----------|
| `wcfvietnam` | wcfvietnam.vn | #1 Giống mèo | Tiêu chuẩn giống chính thức |
| `mozzi` | mozzi.vn | #2 Dinh dưỡng | Pate, hạt khô, mix feeding |
| `pethealth` | pethealth.vn | #3 Sức khỏe | Bệnh lý mèo chi tiết |
| `paddy` | paddy.vn | #4 Chăm sóc | Đa dạng, content dài |
| `tropicpet` | tropicpet.vn | #5 Hành vi | Góc nhìn bệnh viện thú y |

## Cách chạy

Test thử trên 1 nguồn, giới hạn 5 URL:

```powershell
uv run python -m crawler.crawl --source pethealth --limit 5
```

Chạy thật toàn bộ (mất ~1-2 giờ, có rate limit):

```powershell
uv run python -m crawler.crawl --source all
```

Override rate (cẩn thận — đừng quá thấp):

```powershell
uv run python -m crawler.crawl --source mozzi --rate 3.0
```

## Output

```
data/
├── raw/
│   ├── pethealth/
│   │   ├── benh-o-meo-a1b2c3d4.json    # 1 bài / file (idempotent)
│   │   └── ...
│   ├── paddy/
│   └── ...
└── cleaned/
    ├── pethealth.jsonl                  # 1 bài / dòng — dùng cho chunk
    ├── paddy.jsonl
    └── ...
```

Schema mỗi record:

```json
{
  "url": "https://pethealth.vn/blogs/cac-loai-benh/benh-o-meo",
  "title": "...",
  "author": null,
  "date": "2025-10-15",
  "description": "...",
  "categories": ["Các loại bệnh"],
  "tags": ["mèo", "bệnh"],
  "language": "vi",
  "text": "...",
  "text_length": 4231,
  "source": "pethealth",
  "topic_hint": "health",
  "crawled_at": "2026-05-23T10:15:00+00:00"
}
```

## Đặc điểm

- **Idempotent**: nếu file `raw/<source>/<slug>.json` đã tồn tại, không crawl lại.
- **Tôn trọng robots.txt**: bỏ qua URL bị disallow.
- **Rate limit per-source**: 2–2.5s/request (xem `sources.py`).
- **User-Agent định danh rõ**: dễ liên hệ nếu admin site có thắc mắc.
- **Lọc bài thin**: bỏ qua trang < 200 ký tự (thường là page lỗi).

## Mở rộng

- Thêm nguồn mới → edit `sources.py`, thêm 1 `Source(...)` vào `SOURCES`.
- Bước tiếp (sau crawl): chunking + gán metadata `topic`/`content_type`/`severity` rồi embed.

## Pháp lý

- Đã đọc robots.txt từng site; tất cả 5 nguồn đều cho phép crawl public pages.
- Mỗi record lưu `url` gốc — bot sẽ trích nguồn khi trả lời.
- Không redistribute nguyên văn; chỉ dùng làm context cho LLM trả lời câu hỏi user.
