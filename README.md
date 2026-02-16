# CTS — Greater Sydney Location Dashboard (Dash + Render)

## What this is
A lightweight Dash web app that:
- Reads `data/dashboard_data.csv` (11 candidate store locations + metrics)
- Renders a **point map** using each store’s Latitude/Longitude
- Lets you pick any metric and compares the 11 locations via:
  - KPI cards (mean / min / max)
  - Point map (colour = selected metric)
  - Bar chart (selected metric)
  - Scatter plot (NPV vs Net Income)
  - Full sortable/filterable table
  - Brief FAQ

> Why points instead of SA2 polygons?
> Several stores sit in the same SA2 area. Points ensure **each store is visible** and can be compared independently.

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

Python is pinned via `runtime.txt`.

## Local run
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:8050
