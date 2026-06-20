# Monitor Berita — UU TPKS & Kekerasan Berbasis Gender

Dashboard pemantauan berita otomatis untuk isu:
- **UU TPKS** (Undang-Undang Tindak Pidana Kekerasan Seksual)
- **Kekerasan Seksual** di Indonesia
- **Kekerasan Berbasis Gender (KBG)**
- **Kekerasan Berbasis Gender Online (KBGO)**

**Dashboard:** `https://<username>.github.io/<repo-name>/`

---

## Cara Kerja

```
Google News RSS → Python (fetch_news.py) → docs/data/news.json → GitHub Pages
                        ↑
              GitHub Actions (tiap 6 jam)
```

1. GitHub Actions menjalankan `scripts/fetch_news.py` tiap 6 jam
2. Script mengambil berita dari Google News RSS berdasarkan 4 kata kunci
3. Hasil disimpan ke `docs/data/news.json`
4. Dashboard GitHub Pages membaca JSON dan menampilkan berita secara otomatis

---

## Setup

### 1. Fork / Clone repo ini

### 2. Aktifkan GitHub Pages
- Buka **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: `main`, folder: `/docs`

### 3. Jalankan fetch pertama kali (opsional)
```bash
python scripts/fetch_news.py
git add docs/data/news.json
git commit -m "init: data berita pertama"
git push
```

### 4. GitHub Actions berjalan otomatis
Lihat status di tab **Actions** — fetch berjalan tiap 6 jam.
Bisa juga dijalankan manual via **Actions → Update Berita Monitor → Run workflow**.

---

## Struktur File

```
├── .github/
│   └── workflows/
│       └── update-news.yml    # Scheduler GitHub Actions
├── scripts/
│   └── fetch_news.py          # Script fetch berita dari Google News RSS
├── docs/
│   ├── index.html             # Dashboard utama
│   └── data/
│       └── news.json          # Data berita (auto-generated)
└── README.md
```

---

## Kustomisasi Kata Kunci

Edit bagian `KEYWORDS` di `scripts/fetch_news.py`:

```python
KEYWORDS = [
    {"id": "tpks", "label": "UU TPKS", "query": "UU TPKS kekerasan seksual"},
    {"id": "kekerasan_seksual", "label": "Kekerasan Seksual", "query": "kekerasan seksual Indonesia"},
    {"id": "kbg", "label": "Kekerasan Berbasis Gender", "query": "kekerasan berbasis gender KBG"},
    {"id": "kbgo", "label": "KBGO", "query": "kekerasan berbasis gender online KBGO"},
]
```

---

*Dibuat untuk keperluan riset dan advokasi. Data bersumber dari Google News RSS — tidak berafiliasi dengan Google.*
