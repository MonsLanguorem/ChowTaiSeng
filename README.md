# CTS — Greater Sydney Dashboard (Render-ready)

This repo contains a small Dash web app (`app.py`) that:
- loads the **11-location universal table** from `data/cts_universal_table.csv`
- loads **Greater Sydney SA2 polygons** from `data/sa2_greater_sydney_2021.geojson`
- renders:
  - a map (all SA2 shown in light grey; the 11 selected regions shown as a heatmap)
  - a bar chart comparing the selected metric across the 11 locations
  - a searchable/sortable table of all 11 locations

## Local run
```bash
pip install -r requirements.txt
python app.py
```
Open: http://127.0.0.1:8050

## Deploy to Render (Web Service)

**Build command**
```bash
pip install -r requirements.txt
```

**Start command**
```bash
gunicorn app:server --bind 0.0.0.0:$PORT
```

If you see Render using an experimental Python version (e.g. 3.14) and you get weird build/runtime issues, set the service's **Python Version** in Render to a stable version (3.11 or 3.12).
