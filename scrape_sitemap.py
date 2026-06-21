#!/usr/bin/env python3
"""
Scraper sitemap Kompas & Tempo — ambil metadata berita (judul, tanggal, URL, deskripsi)
yang mengandung kata kunci KBG/TPKS, lalu gabungkan ke docs/data/news.json

Jalankan SEKALI untuk inisialisasi arsip historis:
    python scripts/scrape_sitemap.py

Proses bisa memakan waktu 30–90 menit tergantung ukuran sitemap.
Aman dihentikan (Ctrl+C) dan dilanjutkan — data yang sudah dikumpulkan tersimpan.
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin

# ── Konfigurasi ──────────────────────────────────────────────────
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "news.json")
PROGRESS_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "scrape_progress.json")

# Kata kunci pencarian (case-insensitive, cek di judul + deskripsi)
SEARCH_KEYWORDS = [
    "tpks", "kekerasan seksual", "pelecehan seksual",
    "kekerasan berbasis gender", "kbg", "kbgo",
    "kekerasan gender", "perkosaan", "pemerkosaan",
    "kdrt", "kekerasan dalam rumah tangga",
    "gender based violence", "sexual violence",
    "revenge porn", "siswi", "korban pelecehan",
]

# Mapping kata kunci → topik dashboard
KEYWORD_TO_TOPIC = {
    "tpks":                       ("tpks",              "UU TPKS"),
    "kekerasan seksual":          ("kekerasan_seksual", "Kekerasan Seksual"),
    "pelecehan seksual":          ("kekerasan_seksual", "Kekerasan Seksual"),
    "perkosaan":                  ("kekerasan_seksual", "Kekerasan Seksual"),
    "pemerkosaan":                ("kekerasan_seksual", "Kekerasan Seksual"),
    "korban pelecehan":           ("kekerasan_seksual", "Kekerasan Seksual"),
    "kekerasan berbasis gender":  ("kbg",               "Kekerasan Berbasis Gender"),
    "kbg":                        ("kbg",               "Kekerasan Berbasis Gender"),
    "kekerasan gender":           ("kbg",               "Kekerasan Berbasis Gender"),
    "kdrt":                       ("kbg",               "Kekerasan Berbasis Gender"),
    "kekerasan dalam rumah tangga":("kbg",              "Kekerasan Berbasis Gender"),
    "gender based violence":      ("kbg",               "Kekerasan Berbasis Gender"),
    "kbgo":                       ("kbgo",              "Kekerasan Berbasis Gender Online"),
    "revenge porn":               ("kbgo",              "Kekerasan Berbasis Gender Online"),
    "gender based violence online":("kbgo",             "Kekerasan Berbasis Gender Online"),
    "sexual violence":            ("kekerasan_seksual", "Kekerasan Seksual"),
    "siswi":                      ("kekerasan_seksual", "Kekerasan Seksual"),
}

# Sitemap index masing-masing media
SOURCES = [
    {
        "id":     "kompas",
        "label":  "Kompas.com",
        "sitemap_index": "https://www.kompas.com/sitemap/sitemap_index.xml",
        "url_filter": "kompas.com",
        "delay": 2.0,
    },
    {
        "id":     "tempo",
        "label":  "Tempo.co",
        "sitemap_index": "https://www.tempo.co/sitemap.xml",
        "url_filter": "tempo.co",
        "delay": 2.0,
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml, text/xml, */*",
    "Accept-Language": "id-ID,id;q=0.9",
    "Cache-Control": "no-cache",
}

NS = {
    "sm":   "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
    "image":"http://www.google.com/schemas/sitemap-image/1.1",
}

# ── Helpers ──────────────────────────────────────────────────────
def fetch_xml(url, delay=1.0):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as r:
            data = r.read()
        time.sleep(delay)
        return ET.fromstring(data)
    except HTTPError as e:
        print(f"    [HTTP {e.code}] {url}")
    except URLError as e:
        print(f"    [URLError] {url}: {e.reason}")
    except ET.ParseError as e:
        print(f"    [ParseError] {url}: {e}")
    except Exception as e:
        print(f"    [Error] {url}: {e}")
    return None

def clean(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    for ent, rep in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),("&#39;","'"),("&nbsp;"," ")]:
        text = text.replace(ent, rep)
    return re.sub(r"\s+", " ", text).strip()

def classify(title, desc=""):
    haystack = (title + " " + (desc or "")).lower()
    for kw, (kid, klabel) in KEYWORD_TO_TOPIC.items():
        if kw in haystack:
            return kid, klabel
    return None, None

def parse_date_flexible(s):
    if not s:
        return None
    s = s.strip()
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s[:25], fmt[:len(fmt)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    # fallback: ambil YYYY-MM-DD dari string
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass
    return None

# ── Load / save ──────────────────────────────────────────────────
def load_existing_articles():
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("articles", [])
    except Exception:
        return []

def load_progress():
    if not os.path.exists(PROGRESS_PATH):
        return {"done_sitemaps": []}
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"done_sitemaps": []}

def save_progress(progress):
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

def save_articles(all_articles):
    """Simpan artikel ke news.json dengan deduplikasi."""
    seen = set()
    unique = []
    for a in all_articles:
        if a["link"] and a["link"] not in seen:
            seen.add(a["link"])
            unique.append(a)
    unique.sort(key=lambda x: x.get("pubDate",""), reverse=True)

    stats = {}
    for a in unique:
        kid = a.get("keyword_id","")
        stats[kid] = stats.get(kid, 0) + 1

    output = {
        "updated_at":      datetime.now(timezone.utc).isoformat(),
        "total":           len(unique),
        "stats":           stats,
        "new_this_fetch":  0,
        "keywords": [
            {"id":"tpks",              "label":"UU TPKS"},
            {"id":"kekerasan_seksual", "label":"Kekerasan Seksual"},
            {"id":"kbg",               "label":"Kekerasan Berbasis Gender"},
            {"id":"kbgo",              "label":"Kekerasan Berbasis Gender Online"},
        ],
        "articles": unique,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return len(unique)

# ── Sitemap parsing ──────────────────────────────────────────────
def get_child_sitemaps(index_url, delay):
    """Ambil daftar URL sitemap anak dari sitemap index."""
    print(f"  Membaca sitemap index: {index_url}")
    root = fetch_xml(index_url, delay)
    if root is None:
        return []
    urls = []
    # Coba dengan dan tanpa namespace
    for loc in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
        urls.append(loc.text.strip())
    if not urls:
        for loc in root.iter("loc"):
            urls.append(loc.text.strip())
    print(f"    → {len(urls)} child sitemaps ditemukan")
    return urls

def parse_sitemap_urls(sitemap_url, source_label, delay):
    """Parse satu sitemap XML, kembalikan list artikel yang relevan."""
    root = fetch_xml(sitemap_url, delay)
    if root is None:
        return []

    articles = []
    # Coba namespace news sitemap dulu (lebih kaya metadata)
    urls_el = (root.findall(".//sm:url", NS) or root.findall(".//url"))

    for url_el in urls_el:
        # URL
        loc = (url_el.findtext("sm:loc", namespaces=NS) or
               url_el.findtext("loc") or "").strip()
        if not loc:
            continue

        # Tanggal
        pub = (url_el.findtext("sm:lastmod", namespaces=NS) or
               url_el.findtext("lastmod") or
               url_el.findtext("news:news/news:publication_date", namespaces=NS) or
               url_el.findtext(".//publication_date") or "")
        pub_iso = parse_date_flexible(pub)

        # Judul — dari news:title atau tebak dari URL
        title = (url_el.findtext("news:news/news:title", namespaces=NS) or
                 url_el.findtext(".//title") or "")
        title = clean(title)
        if not title:
            # Coba ekstrak dari URL slug
            slug = loc.rstrip("/").split("/")[-1]
            title = slug.replace("-", " ").title()

        # Deskripsi / keywords dari news sitemap
        desc = (url_el.findtext("news:news/news:keywords", namespaces=NS) or
                url_el.findtext(".//description") or "")
        desc = clean(desc)[:300]

        # Klasifikasi topik
        kid, klabel = classify(title, desc)
        if kid is None:
            # Coba dari URL juga
            kid, klabel = classify(loc)
        if kid is None:
            continue  # tidak relevan

        articles.append({
            "title":         title,
            "link":          loc,
            "pubDate":       pub_iso or datetime.now(timezone.utc).isoformat(),
            "source":        source_label,
            "description":   desc,
            "keyword_id":    kid,
            "keyword_label": klabel,
        })

    return articles

# ── Main ─────────────────────────────────────────────────────────
def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    print("=" * 60)
    print("SCRAPER SITEMAP — Kompas & Tempo")
    print("Mengumpulkan arsip berita KBG/TPKS historis")
    print("=" * 60)
    print("Tips: Proses ini bisa memakan waktu lama.")
    print("      Aman dihentikan (Ctrl+C) — progress tersimpan.\n")

    # Load state
    existing   = load_existing_articles()
    progress   = load_progress()
    done_sitemaps = set(progress.get("done_sitemaps", []))

    all_articles = list(existing)
    seen_links   = {a["link"] for a in all_articles}

    total_added = 0

    for source in SOURCES:
        print(f"\n{'─'*50}")
        print(f"📰 {source['label']}")
        print(f"{'─'*50}")

        child_sitemaps = get_child_sitemaps(source["sitemap_index"], source["delay"])

        if not child_sitemaps:
            # Mungkin langsung sitemap (bukan index)
            child_sitemaps = [source["sitemap_index"]]

        total_sm = len(child_sitemaps)
        for i, sm_url in enumerate(child_sitemaps, 1):
            if sm_url in done_sitemaps:
                print(f"  [{i}/{total_sm}] Skip (sudah diproses): {sm_url.split('/')[-1]}")
                continue

            print(f"  [{i}/{total_sm}] {sm_url.split('/')[-1]} ...", end=" ", flush=True)

            try:
                arts = parse_sitemap_urls(sm_url, source["label"], source["delay"])
            except KeyboardInterrupt:
                print("\n\n⚠️  Dihentikan oleh pengguna. Menyimpan progress...")
                _finalize(all_articles, progress, done_sitemaps, total_added)
                sys.exit(0)

            # Filter duplikat
            new = [a for a in arts if a["link"] not in seen_links]
            for a in new:
                seen_links.add(a["link"])
                all_articles.append(a)
            total_added += len(new)

            print(f"{len(arts)} ditemukan, {len(new)} baru | total arsip: {len(all_articles)}")

            # Tandai selesai
            done_sitemaps.add(sm_url)
            progress["done_sitemaps"] = list(done_sitemaps)

            # Simpan setiap 10 sitemap agar tidak hilang jika terputus
            if i % 10 == 0:
                save_articles(all_articles)
                save_progress(progress)
                print(f"    💾 Progress disimpan ({len(all_articles)} artikel total)")

    _finalize(all_articles, progress, done_sitemaps, total_added)


def _finalize(all_articles, progress, done_sitemaps, total_added):
    progress["done_sitemaps"] = list(done_sitemaps)
    save_progress(progress)
    total = save_articles(all_articles)
    print(f"\n{'='*60}")
    print(f"✓ Selesai!")
    print(f"  Artikel baru ditambahkan : {total_added}")
    print(f"  Total arsip sekarang     : {total}")
    print(f"  Tersimpan di             : {OUTPUT_PATH}")
    print(f"\nJalankan fetch_news.py untuk melanjutkan monitoring berita baru.")


if __name__ == "__main__":
    main()
