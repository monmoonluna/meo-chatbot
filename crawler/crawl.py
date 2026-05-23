"""Crawler cho 5 nguồn dữ liệu tiếng Việt về mèo.

Pipeline:
  1. Đọc sitemap.xml (đệ quy nếu là sitemap-index)
  2. Lọc URL khớp `url_filter_regex` của từng nguồn
  3. Fetch HTML, dùng trafilatura để extract text + metadata
  4. Lưu mỗi bài thành 1 file JSON trong data/raw/<source>/
  5. Append vào data/cleaned/<source>.jsonl (1 dòng/bài)

Cách chạy:
  uv run python -m crawler.crawl --source all
  uv run python -m crawler.crawl --source pethealth --limit 5
  uv run python -m crawler.crawl --source mozzi --rate 3.0
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

import httpx
import trafilatura
from tqdm.asyncio import tqdm

from crawler.sources import SOURCES, Source, get_source

# Windows PowerShell defaults to cp1252 — force UTF-8 cho Vietnamese text + Unicode glyphs
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CLEAN_DIR = ROOT / "data" / "cleaned"

USER_AGENT = "MeoBot-Research-Crawler/0.1 (educational; +https://github.com/yourrepo)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MIN_TEXT_LEN = 200  # bỏ qua trang quá ngắn (thường là page lỗi/index)


# ---------------------------------------------------------------------------
# Sitemap discovery
# ---------------------------------------------------------------------------

def _strip_xmlns(xml_text: str) -> str:
    """Bỏ default namespace để ElementTree iter() đơn giản hơn."""
    return re.sub(r'\sxmlns="[^"]+"', "", xml_text, count=1)


def parse_sitemap(xml_text: str) -> list[str]:
    """Trả về danh sách <loc> URL — không phân biệt sitemap-index hay urlset."""
    try:
        root = ET.fromstring(_strip_xmlns(xml_text))
    except ET.ParseError as e:
        print(f"  [!] sitemap parse error: {e}", file=sys.stderr)
        return []
    return [loc.text.strip() for loc in root.iter("loc") if loc.text]


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        print(f"  [!] fetch {url}: {e}", file=sys.stderr)
        return None
    if url.endswith(".gz"):
        try:
            return gzip.decompress(r.content).decode("utf-8", errors="ignore")
        except Exception:
            return None
    return r.text


async def discover_urls(client: httpx.AsyncClient, source: Source) -> list[str]:
    """Walk sitemap đệ quy → trả về URL bài viết khớp filter."""
    pattern = re.compile(source.url_filter_regex, re.IGNORECASE)
    seen_sitemaps: set[str] = set()
    articles: set[str] = set()
    queue = list(source.sitemap_urls)

    while queue:
        sm_url = queue.pop(0)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)
        xml = await _fetch_text(client, sm_url)
        if not xml:
            continue
        for child in parse_sitemap(xml):
            low = child.lower()
            if low.endswith(".xml") or low.endswith(".xml.gz"):
                queue.append(child)
            elif pattern.search(child):
                articles.add(child)

    articles.update(source.extra_seed_urls)
    return sorted(articles)


# ---------------------------------------------------------------------------
# Robots.txt
# ---------------------------------------------------------------------------

def load_robots(base_url: str) -> RobotFileParser:
    rp = RobotFileParser()
    rp.set_url(f"{base_url.rstrip('/')}/robots.txt")
    try:
        rp.read()
    except Exception as e:
        print(f"  [!] robots.txt unavailable for {base_url}: {e}", file=sys.stderr)
    return rp


# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

def _slug_for(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1] or "index"
    tail = re.sub(r"[^a-zA-Z0-9_-]+", "-", tail).strip("-").lower()[:80]
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{tail}-{h}"


def extract_article(html: str, url: str) -> dict | None:
    """Trafilatura extract → dict với text + metadata."""
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        deduplicate=True,
    )
    if not text or len(text) < MIN_TEXT_LEN:
        return None

    md = trafilatura.extract_metadata(html)
    md_dict = md.as_dict() if md else {}

    return {
        "url": url,
        "title": md_dict.get("title"),
        "author": md_dict.get("author"),
        "date": md_dict.get("date"),
        "description": md_dict.get("description"),
        "categories": md_dict.get("categories"),
        "tags": md_dict.get("tags"),
        "language": md_dict.get("language") or "vi",
        "text": text,
        "text_length": len(text),
    }


async def crawl_one(
    client: httpx.AsyncClient,
    source: Source,
    url: str,
    raw_dir: Path,
) -> dict | None:
    """Return article dict for NEW fetches only. Returns None for cache hits
    (caller skips sleep + skip re-append to avoid wasted time + JSONL dupes)."""
    raw_path = raw_dir / f"{_slug_for(url)}.json"
    if raw_path.exists():
        return None  # cache hit — already in raw/ + cleaned/.jsonl from initial run

    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        print(f"  [!] {url}: {e}", file=sys.stderr)
        return None

    article = extract_article(r.text, url)
    if not article:
        return None

    article.update({
        "source": source.name,
        "topic_hint": source.topic_hint,
        "crawled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    raw_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    return article


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def crawl_source(source: Source, limit: int | None, rate: float | None) -> int:
    rate = rate if rate is not None else source.rate_limit_sec
    raw_dir = RAW_DIR / source.name
    raw_dir.mkdir(parents=True, exist_ok=True)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {source.name}  (rate={rate}s)  ===")
    robots = load_robots(source.base_url)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "vi,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT, http2=False) as client:
        urls = await discover_urls(client, source)
        urls = [u for u in urls if robots.can_fetch(USER_AGENT, u)]
        print(f"  → {len(urls)} URL khớp filter & robots.txt cho phép")
        if limit:
            urls = urls[:limit]

        out_file = CLEAN_DIR / f"{source.name}.jsonl"
        new_count = 0
        with out_file.open("a", encoding="utf-8") as fout:
            for url in tqdm(urls, desc=source.name):
                article = await crawl_one(client, source, url, raw_dir)
                if article is None:
                    continue  # cache hit or fetch error — skip sleep + skip write
                fout.write(json.dumps(article, ensure_ascii=False) + "\n")
                fout.flush()
                new_count += 1
                await asyncio.sleep(rate)

    print(f"  ✓ {new_count} bài → {out_file}")
    return new_count


async def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl 5 nguồn tiếng Việt về mèo.")
    parser.add_argument(
        "--source",
        default="all",
        help="Tên nguồn hoặc 'all'. Có: " + ", ".join(s.name for s in SOURCES),
    )
    parser.add_argument("--limit", type=int, default=None, help="Số URL tối đa mỗi nguồn (test)")
    parser.add_argument("--rate", type=float, default=None, help="Override rate_limit_sec")
    args = parser.parse_args()

    if args.source == "all":
        targets = SOURCES
    else:
        targets = [get_source(args.source)]

    total = 0
    for src in targets:
        total += await crawl_source(src, args.limit, args.rate)
    print(f"\n=== Xong: {total} bài mới ===")


if __name__ == "__main__":
    asyncio.run(main())
