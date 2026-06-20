#!/usr/bin/env python3
"""
Fetch berita terkait UU TPKS, Kekerasan Seksual, KBG, dan KBGO
dari Google News RSS, simpan ke docs/data/news.json
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError
import time

KEYWORDS = [
    {"id": "tpks", "label": "UU TPKS", "query": "UU TPKS kekerasan seksual"},
    {"id": "kekerasan_seksual", "label": "Kekerasan Seksual", "query": "kekerasan seksual Indonesia"},
    {"id": "kbg", "label": "Kekerasan Berbasis Gender", "query": "kekerasan berbasis gender KBG"},
    {"id": "kbgo", "label": "Kekerasan Berbasis Gender Online", "query": "kekerasan berbasis gender online KBGO"},
]

MAX_PER_KEYWORD = 15
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "news.json")

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
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_date(date_str):
    """Parse RSS date string ke ISO format."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()

def extract_source(title):
    """Ekstrak nama media dari judul Google News (format: 'Judul - Media')."""
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
        items = channel.findall("item")
        for item in items[:MAX_PER_KEYWORD]:
            title_raw = item.findtext("title", "")
            title = clean_html(title_raw)
            link = item.findtext("link", "")
            pub_date = parse_date(item.findtext("pubDate", ""))
            description = clean_html(item.findtext("description", ""))
            source_name = extract_source(title_raw)
            # Hapus nama media dari judul
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()
            articles.append({
                "title": title,
                "link": link,
                "pubDate": pub_date,
                "source": source_name,
                "description": description[:300] if description else "",
                "keyword_id": keyword_obj["id"],
                "keyword_label": keyword_obj["label"],
            })
    except (URLError, ET.ParseError, Exception) as e:
        print(f"  [ERROR] {keyword_obj['label']}: {e}")
    return articles

def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    all_articles = []
    stats = {}

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Mulai fetch berita...")

    for kw in KEYWORDS:
        print(f"  Fetching: {kw['label']}...")
        articles = fetch_rss(kw)
        all_articles.extend(articles)
        stats[kw["id"]] = len(articles)
        print(f"    → {len(articles)} berita ditemukan")
        time.sleep(2)  # jeda antar request

    # Deduplicate berdasarkan link
    seen_links = set()
    unique_articles = []
    for a in all_articles:
        if a["link"] not in seen_links:
            seen_links.add(a["link"])
            unique_articles.append(a)

    # Sort by date terbaru
    unique_articles.sort(key=lambda x: x["pubDate"], reverse=True)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(unique_articles),
        "stats": stats,
        "keywords": [{"id": k["id"], "label": k["label"]} for k in KEYWORDS],
        "articles": unique_articles,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Selesai. {len(unique_articles)} artikel unik disimpan ke {OUTPUT_PATH}")
    for kw in KEYWORDS:
        print(f"  {kw['label']}: {stats[kw['id']]} artikel")

if __name__ == "__main__":
    main()
