#!/usr/bin/env python3
"""
Fetch berita terkait UU TPKS, Kekerasan Seksual, KBG, dan KBGO
dari Google News RSS, AKUMULASI ke docs/data/news.json (tidak menimpa data lama)
Deduplikasi: cek URL + fallback judul+sumber
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError
import time

KEYWORDS = [
    {"id": "tpks",              "label": "UU TPKS",                         "query": "UU TPKS kekerasan seksual"},
    {"id": "kekerasan_seksual", "label": "Kekerasan Seksual",               "query": "kekerasan seksual Indonesia"},
    {"id": "kbg",               "label": "Kekerasan Berbasis Gender",        "query": "kekerasan berbasis gender KBG"},
    {"id": "kbgo",              "label": "Kekerasan Berbasis Gender Online", "query": "kekerasan berbasis gender online KBGO"},
]

MAX_PER_KEYWORD = 15
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "news.json")
MAX_AGE_DAYS = 0  # 0 = simpan selamanya

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def clean_html(text):
    """Bersihkan HTML entities termasuk &nbsp; dan duplikat spasi."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    for ent, rep in [
        ("&nbsp;", " "), ("&#160;", " "),
        ("&amp;",  "&"), ("&lt;",   "<"),
        ("&gt;",   ">"), ("&quot;", '"'), ("&#39;", "'"),
    ]:
        text = text.replace(ent, rep)
    # Buang pola "... - NamaMedia  NamaMedia" di akhir deskripsi Google News
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def clean_description(desc, title, source):
    """
    Deskripsi dari Google News RSS biasanya berisi:
    'Judul - Media  Media' — buang bagian duplikat itu.
    """
    desc = clean_html(desc)
    # Buang suffix '  NamaMedia' atau '- NamaMedia' di akhir
    if source and desc.endswith(source):
        desc = desc[: -len(source)].strip(" -\xa0")
    # Buang jika deskripsi hanya mengulang judul
    if desc.lower().startswith(title.lower()[:40]):
        parts = desc.split("  ")
        if len(parts) > 1:
            desc = parts[0].strip()
    return desc[:300].strip(" -")


def parse_date(date_str):
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()


def extract_source(title_raw):
    if " - " in title_raw:
        return title_raw.rsplit(" - ", 1)[-1].strip()
    return "Tidak diketahui"


def normalize_url(url):
    """Normalkan URL untuk deduplikasi: buang query string & fragment & trailing slash."""
    url = (url or "").strip()
    url = re.sub(r"[?#].*$", "", url).rstrip("/")
    return url.lower()


def title_key(title):
    """Kunci judul: lowercase, tanpa spasi, 80 karakter pertama."""
    return re.sub(r"\s+", "", (title or "").lower())[:80]


def fetch_rss(keyword_obj):
    query = quote_plus(keyword_obj["query"])
    url = f"https://news.google.com/rss/search?q={query}&hl=id&gl=ID&ceid=ID:id"
    articles = []
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return articles
        for item in channel.findall("item")[:MAX_PER_KEYWORD]:
            title_raw = item.findtext("title", "")
            source    = extract_source(title_raw)
            title     = clean_html(title_raw)
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()
            link     = item.findtext("link", "")
            pub_date = parse_date(item.findtext("pubDate", ""))
            desc_raw = item.findtext("description", "")
            desc     = clean_description(desc_raw, title, source)

            articles.append({
                "title":         title,
                "link":          link,
                "pubDate":       pub_date,
                "source":        source,
                "description":   desc,
                "keyword_id":    keyword_obj["id"],
                "keyword_label": keyword_obj["label"],
            })
    except (URLError, ET.ParseError, Exception) as e:
        print(f"  [ERROR] {keyword_obj['label']}: {e}")
    return articles


def load_existing():
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("articles", [])
    except Exception as e:
        print(f"  [WARN] Gagal membaca data lama: {e}")
        return []


def deduplicate(articles):
    """
    Deduplikasi dua lapis:
    1. URL ternormalisasi (buang query string)
    2. Judul ternormalisasi + sumber (untuk URL yang berbeda tapi konten sama)
    """
    seen_urls   = set()
    seen_titles = set()
    unique = []
    for a in articles:
        u = normalize_url(a.get("link", ""))
        t = title_key(a.get("title", "")) + "|" + re.sub(r"\s+", "", (a.get("source") or "").lower())
        if u and u in seen_urls:
            continue
        if t and len(t) > 5 and t in seen_titles:
            continue
        if u:
            seen_urls.add(u)
        if t:
            seen_titles.add(t)
        unique.append(a)
    return unique


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Mulai fetch berita...")

    # 1. Ambil berita baru
    new_articles = []
    for kw in KEYWORDS:
        print(f"  Fetching: {kw['label']}...")
        arts = fetch_rss(kw)
        new_articles.extend(arts)
        print(f"    → {len(arts)} berita ditemukan")
        time.sleep(2)

    # 2. Baca arsip lama
    old_articles = load_existing()
    print(f"\n  Arsip lama: {len(old_articles)} artikel")

    # 3. Gabungkan: baru dulu, lama kemudian
    combined = new_articles + old_articles

    # 4. Deduplikasi dua lapis
    combined = deduplicate(combined)

    # 5. Opsional: buang artikel terlalu lama
    if MAX_AGE_DAYS > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        before = len(combined)
        combined = [a for a in combined if _parse_iso(a.get("pubDate", "")) >= cutoff]
        print(f"  Dipangkas (>{MAX_AGE_DAYS} hari): {before - len(combined)} artikel dihapus")

    # 6. Sort terbaru di atas
    combined.sort(key=lambda x: x.get("pubDate", ""), reverse=True)

    # 7. Stats
    stats = {kw["id"]: 0 for kw in KEYWORDS}
    for a in combined:
        kid = a.get("keyword_id", "")
        if kid in stats:
            stats[kid] += 1

    output = {
        "updated_at":     datetime.now(timezone.utc).isoformat(),
        "total":          len(combined),
        "stats":          stats,
        "new_this_fetch": len(new_articles),
        "keywords":       [{"id": k["id"], "label": k["label"]} for k in KEYWORDS],
        "articles":       combined,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    added = len(combined) - len(old_articles)
    print(f"\n✓ Selesai.")
    print(f"  Baru ditambahkan : {max(added, 0)} artikel unik")
    print(f"  Total arsip      : {len(combined)} artikel")
    for kw in KEYWORDS:
        print(f"  {kw['label']}: {stats[kw['id']]} artikel")


def _parse_iso(iso_str):
    try:
        return datetime.fromisoformat(iso_str)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    main()
