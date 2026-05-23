"""Spot-check chất lượng chunk: random sample + outliers (ngắn/dài)."""

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

random.seed(42)
CHUNKS = Path(__file__).resolve().parent.parent / "data" / "chunks" / "all.jsonl"

by_source: dict[str, list[dict]] = defaultdict(list)
with CHUNKS.open(encoding="utf-8") as f:
    for line in f:
        c = json.loads(line)
        by_source[c["source"]].append(c)

print(f"Total: {sum(len(v) for v in by_source.values())} chunks\n")

# 2 random per source
print("=" * 80)
print(" RANDOM 2 PER SOURCE")
print("=" * 80)
for src in sorted(by_source):
    print(f"\n--- {src} ---")
    samples = random.sample(by_source[src], min(2, len(by_source[src])))
    for c in samples:
        head = c["section_title"] or "[no heading]"
        print(f"\n  [{c['char_count']:>4}c] {head}")
        print(f"  url: {c['source_url']}")
        body = c["text"][:280].replace("\n", " ")
        print(f"  >>> {body}{'…' if len(c['text']) > 280 else ''}")

# Top 5 shortest (potential junk)
print("\n" + "=" * 80)
print(" 5 CHUNKS NGẮN NHẤT (potential junk)")
print("=" * 80)
all_chunks = [c for cs in by_source.values() for c in cs]
shortest = sorted(all_chunks, key=lambda c: c["char_count"])[:5]
for c in shortest:
    print(f"\n  [{c['char_count']:>4}c] {c['source']} | {c['section_title'] or '[no head]'}")
    print(f"  >>> {c['text'][:300]}")

# Top 5 longest (might hit max_chars)
print("\n" + "=" * 80)
print(" 5 CHUNKS DÀI NHẤT (sát max_chars)")
print("=" * 80)
longest = sorted(all_chunks, key=lambda c: -c["char_count"])[:5]
for c in longest:
    print(f"\n  [{c['char_count']:>4}c] {c['source']} | {c['section_title'] or '[no head]'}")
    print(f"  >>> {c['text'][:300]}…")

# Stats
print("\n" + "=" * 80)
print(" STATS")
print("=" * 80)
print(f"\n  Total chunks: {len(all_chunks):,}")
chunk_lens = [c["char_count"] for c in all_chunks]
chunk_lens.sort()
print(f"  Median chars: {chunk_lens[len(chunk_lens)//2]}")
print(f"  P10 / P90: {chunk_lens[len(chunk_lens)//10]} / {chunk_lens[len(chunk_lens)*9//10]}")
no_heading = sum(1 for c in all_chunks if not c["section_title"])
print(f"  Chunks không heading: {no_heading:,} ({no_heading * 100 // len(all_chunks)}%)")
