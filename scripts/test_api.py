"""Test client cho /chat API — KHÔNG cần frontend.

Dùng urllib (không phụ thuộc requests) + UTF-8 chuẩn để gửi tiếng Việt không bị
lỗi như curl trên Windows.

Cách chạy (server phải đang chạy: python -m uvicorn app.main:app):
  python scripts/test_api.py "Mèo của tôi nôn liên tục, phải làm gì?"
  python scripts/test_api.py "Mèo Anh lông ngắn ăn gì?" --topic nutrition --level beginner
  python scripts/test_api.py --health           # chỉ ping GET /health

Tuỳ chọn:
  --base   URL gốc (mặc định http://localhost:8000)
  --topic  auto|breed|nutrition|health|care|behavior  (mặc định auto)
  --level  auto|beginner|advanced                     (mặc định auto)
  --top-k  số chunk lấy về (1-20, mặc định 5)
  --api-key  gửi header X-API-Key (nếu server đặt env API_KEY)
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def call(base: str, path: str, payload: dict | None, api_key: str | None) -> tuple[int, dict]:
    url = base.rstrip("/") + path
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["X-API-Key"] = api_key
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    method = "POST" if data is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except Exception:
            pass
        return e.code, {"error": body, "retry_after": e.headers.get("Retry-After")}
    except urllib.error.URLError as e:
        print(f"❌ Không kết nối được {url} — server đã chạy chưa? ({e.reason})")
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", help="Câu hỏi tiếng Việt")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--topic", default="auto")
    ap.add_argument("--level", default="auto")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--health", action="store_true", help="Chỉ gọi GET /health")
    args = ap.parse_args()

    if args.health:
        status, body = call(args.base, "/health", None, args.api_key)
        print(f"GET /health → {status}  {body}")
        return

    if not args.question:
        ap.error("cần truyền câu hỏi, hoặc dùng --health")

    payload = {
        "messages": [{"role": "user", "content": args.question}],
        "topic_filter": args.topic,
        "user_level": args.level,
        "top_k": args.top_k,
    }
    print(f"POST {args.base}/chat\n→ Q: {args.question}\n")
    status, body = call(args.base, "/chat", payload, args.api_key)

    if status != 200:
        print(f"❌ HTTP {status}")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return

    print(f"✅ HTTP 200 | needs_vet={body.get('needs_vet')} | "
          f"topic_detected={body.get('topic_detected')} | session={body.get('session_id')}")
    print("\n--- REPLY ---")
    print(body.get("reply", ""))
    cites = body.get("citations", [])
    print(f"\n--- CITATIONS ({len(cites)}) ---")
    for c in cites:
        print(f"  [{c['index']}] {c.get('source_name')} — {c.get('section_title') or ''}")
        print(f"      {c.get('source_url')}")


if __name__ == "__main__":
    main()
