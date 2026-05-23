"""Cấu hình 5 nguồn dữ liệu tiếng Việt về mèo.

Mỗi nguồn có:
- name: tên ngắn, dùng làm subdirectory
- base_url: domain gốc
- sitemap_urls: danh sách sitemap để discover URL
- url_filter_regex: regex; chỉ URL khớp mới được crawl (lọc bài về mèo)
- topic_hint: chủ đề mặc định gán cho chunk khi chưa phân loại tự động
- rate_limit_sec: thời gian chờ giữa 2 request liên tiếp đến cùng nguồn
"""

from dataclasses import dataclass, field


@dataclass
class Source:
    name: str
    base_url: str
    sitemap_urls: list[str]
    url_filter_regex: str
    topic_hint: str
    rate_limit_sec: float = 2.0
    extra_seed_urls: list[str] = field(default_factory=list)


SOURCES: list[Source] = [
    # Lịch sử: wcfvietnam.vn (TLS handshake fail từ VN) → meonhapkhau.com (không có
    # sitemap thật, mọi path return HTML) → champetsfamily.com (có sitemap chuẩn,
    # breed pages chi tiết)
    Source(
        name="champetsfamily",
        base_url="https://champetsfamily.com",
        sitemap_urls=[
            "https://champetsfamily.com/sitemap_index.xml",
            "https://champetsfamily.com/sitemap.xml",
        ],
        url_filter_regex=r"/blog/.+(meo|kitten|cat-)",
        topic_hint="breed",
        rate_limit_sec=2.5,
    ),
    Source(
        name="mozzi",
        base_url="https://mozzi.vn",
        sitemap_urls=["https://mozzi.vn/sitemap.xml"],
        url_filter_regex=r"/blogs/.+(meo|kitten|pate|hat-kho)",
        topic_hint="nutrition",
        rate_limit_sec=2.0,
    ),
    Source(
        name="pethealth",
        base_url="https://pethealth.vn",
        sitemap_urls=["https://pethealth.vn/sitemap.xml"],
        url_filter_regex=r"/blogs/.+(meo|kitten|cat)",
        topic_hint="health",
        rate_limit_sec=2.0,
    ),
    Source(
        name="paddy",
        base_url="https://paddy.vn",
        sitemap_urls=["https://paddy.vn/sitemap.xml"],
        url_filter_regex=r"/blogs/.+(meo|kitten|cat)",
        topic_hint="care",
        rate_limit_sec=2.0,
    ),
    Source(
        name="tropicpet",
        base_url="https://tropicpet.vn",
        sitemap_urls=[
            "https://tropicpet.vn/sitemap.xml",
            "https://tropicpet.vn/wp-sitemap.xml",
            "https://tropicpet.vn/sitemap_index.xml",
        ],
        url_filter_regex=r"(meo|kitten|cat-)",
        topic_hint="care",
        rate_limit_sec=2.5,
    ),
]


def get_source(name: str) -> Source:
    for s in SOURCES:
        if s.name == name:
            return s
    raise ValueError(f"Unknown source: {name}. Available: {[s.name for s in SOURCES]}")
