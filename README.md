# CTS Greater Sydney Dashboard (Dash + Render)

## What this is
A small Dash web app that:
- Reads `data/cts_universal_table.csv` (11 candidate CTS locations)
- Loads SA2 polygons for Greater Sydney from `data/sa2_greater_sydney_2021.geojson` (preferred)
- Lets you pick a metric and renders a choropleth map for the **11 candidate SA2s** (GeoJSON is filtered at load time for faster updates)
- Shows an interactive table (sort + filter), KPI cards, and comparison charts for all 11 locations

## Important: moving/renaming the GeoJSON on GitHub
Do **NOT** rename/move large `.geojson` files using GitHub's **web editor** — it can accidentally save an empty file
(2 bytes), which breaks Render deploy.

Use one of these instead:
- **GitHub Desktop** (recommended on Mac) → move the file in Finder → commit → push
- Terminal: `git mv` → commit → push
- Or upload the file directly into `data/` using **Add file → Upload files** (no editing)

## Render settings
Create a **Web Service** from your GitHub repo.

**Build command**
```bash
pip install -r requirements.txt
```

**Start command**
```bash
gunicorn app:server --bind 0.0.0.0:$PORT
```

This repo pins Python via `runtime.txt` (Python 3.12).

## Local run
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:8050
