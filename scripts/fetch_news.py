#!/usr/bin/env python3
"""
Fetch berita terkait UU TPKS, Kekerasan Seksual, KBG, dan KBGO
dari Google News RSS, AKUMULASI ke docs/data/news.json (tidak menimpa data lama)
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
    {"id": "tpks",             "label": "UU TPKS",                        "query": "UU TPKS kekerasan seksual"},
    {"id": "kekerasan_seksual","label": "Kekerasan Seksual",              "query": "kekerasan seksual Indonesia"},
    {"id": "kbg",              "label": "Kekerasan Berbasis Gender",       "query": "kekerasan berbasis gender KBG"},
    {"id": "kbgo",             "label": "Kekerasan Berbasis Gender Online","query": "kekerasan berbasis gender online KBGO"},
]

MAX_PER_KEYWORD = 15          # batas RSS Google News
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "news.json")

# Hapus berita lebih tua dari N hari (0 = simpan selamanya)
MAX_AGE_DAYS = 0

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
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    for ent, rep in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),("&#39;","'")]:
        text = text.replace(ent, rep)
    return re.sub(r"\s+", " ", text).strip()


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


def extract_source(title):
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return "Tidak diketahui"


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
            title     = clean_html(title_raw)
            link      = item.findtext("link", "")
            pub_date  = parse_date(item.findtext("pubDate", ""))
            desc      = clean_html(item.findtext("description", ""))
            source    = extract_source(title_raw)
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()
            articles.append({
                "title":         title,
                "link":          link,
                "pubDate":       pub_date,
                "source":        source,
                "description":   desc[:300] if desc else "",
                "keyword_id":    keyword_obj["id"],
                "keyword_label": keyword_obj["label"],
            })
    except (URLError, ET.ParseError, Exception) as e:
        print(f"  [ERROR] {keyword_obj['label']}: {e}")
    return articles


def load_existing():
    """Baca data lama dari news.json jika ada."""
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("articles", [])
    except Exception as e:
        print(f"  [WARN] Gagal membaca data lama: {e}")
        return []


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

    # 3. Gabungkan — deduplikasi berdasarkan URL
    seen_links = set()
    combined   = []

    # Prioritaskan data baru (masuk dulu)
    for a in new_articles:
        if a["link"] and a["link"] not in seen_links:
            seen_links.add(a["link"])
            combined.append(a)

    # Tambahkan arsip lama yang belum ada
    for a in old_articles:
        if a["link"] and a["link"] not in seen_links:
            seen_links.add(a["link"])
            combined.append(a)

    # 4. Opsional: buang artikel terlalu lama
    if MAX_AGE_DAYS > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        before = len(combined)
        combined = [
            a for a in combined
            if _parse_iso(a.get("pubDate","")) >= cutoff
        ]
        print(f"  Dipangkas (>{MAX_AGE_DAYS} hari): {before - len(combined)} artikel dihapus")

    # 5. Sort terbaru di atas
    combined.sort(key=lambda x: x.get("pubDate",""), reverse=True)

    # 6. Hitung stats per keyword
    stats = {kw["id"]: 0 for kw in KEYWORDS}
    for a in combined:
        kid = a.get("keyword_id","")
        if kid in stats:
            stats[kid] += 1

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total":      len(combined),
        "stats":      stats,
        "new_this_fetch": len(new_articles),
        "keywords":   [{"id": k["id"], "label": k["label"]} for k in KEYWORDS],
        "articles":   combined,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    added = len(combined) - len(old_articles)
    print(f"\n✓ Selesai.")
    print(f"  Baru ditambahkan : {max(added,0)} artikel unik")
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
