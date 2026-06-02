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


# Slug patterns thường xuất hiện trong URL bài về mèo (kể cả khi không có "meo")
_CAT_SLUG = r"(meo|kitten|hanh-vi|tam-ly|stress|tram-cam|cao-cau|huan-luyen|ghet|ghen)"


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

    # ===== Behavior-focused VN sources (Phase 2) — lấp gap 3% behavior =====
    # Regex narrow: BẮT BUỘC có "meo" hoặc behavior-related keyword trong URL
    # để loại bỏ content khác (chó/cá/promo events) ở các site đa thú cưng.
    Source(
        name="petspace",
        base_url="https://petspace.vn",
        sitemap_urls=["https://petspace.vn/sitemap.xml"],
        url_filter_regex=rf"/blogs/.+{_CAT_SLUG}",
        topic_hint="behavior",
        rate_limit_sec=2.0,
    ),
    Source(
        name="petthings",
        base_url="https://petthings.vn",
        sitemap_urls=["https://petthings.vn/sitemap.xml"],
        url_filter_regex=rf"/blogs/.+{_CAT_SLUG}",
        topic_hint="behavior",
        rate_limit_sec=2.0,
    ),
    Source(
        name="mochicat",
        base_url="https://mochicat.vn",
        sitemap_urls=["https://mochicat.vn/sitemap.xml"],
        # mochicat đa thú cưng (cá+chó+mèo) → bắt buộc "meo" cụ thể trong slug
        # (keyword như "huan-luyen" trùng với content chó)
        url_filter_regex=r"mochicat\.vn/[^/]*meo[^/]*/?$",
        topic_hint="behavior",
        rate_limit_sec=2.5,
    ),
    Source(
        name="kingspet",
        base_url="https://kingspet.vn",
        sitemap_urls=["https://kingspet.vn/sitemap.xml"],
        url_filter_regex=rf"kingspet\.vn/[^/]*{_CAT_SLUG}[^/]*/?$",
        topic_hint="behavior",
        rate_limit_sec=2.5,
    ),
    Source(
        name="fagopet",
        base_url="https://fagopet.vn",
        sitemap_urls=["https://fagopet.vn/sitemaps/sitemap_posts.xml"],
        url_filter_regex=rf"fagopet\.vn/[^/]*{_CAT_SLUG}",
        topic_hint="behavior",
        rate_limit_sec=2.5,
    ),

    # ===== Breed-detail source (Phase 3) — lấp gap thể trạng giống =====
    # Eval cho thấy KB thiếu nội dung body-condition theo giống (vd "Maine Coon
    # 2 tuổi trông gầy có bình thường không" → không retrieve được chunk liên quan).
    # petchoice.vn (Shopify): sitemap index THẬT đã verify → sitemap_blogs_1.xml có
    # ~320 URL, ~240 (75%) về mèo, gồm bài chuyên giống (Maine Coon, Ragdoll,
    # Munchkin, Angora) kèm cân nặng/đặc điểm. Có bài /blogs/news/meo-maine-coon.
    # (Đã loại chomeow.com: sitemap.xml trả HTML, không phải sitemap thật.)
    Source(
        name="petchoice",
        base_url="https://petchoice.vn",
        sitemap_urls=["https://petchoice.vn/sitemap.xml"],  # index → discovers sitemap_blogs_1.xml
        url_filter_regex=r"/blogs/.+(meo|kitten|cat)",
        topic_hint="breed",
        rate_limit_sec=2.0,
    ),
]


def get_source(name: str) -> Source:
    for s in SOURCES:
        if s.name == name:
            return s
    raise ValueError(f"Unknown source: {name}. Available: {[s.name for s in SOURCES]}")
