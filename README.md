# CTS Sydney Dashboard (Render-ready)

## What this is
A Dash app that reads the 11-location universal table from Excel (`Dashboard_Data` sheet) and paints Greater Sydney SA2 polygons.
Only SA2s that correspond to the 11 candidate locations carry values; other polygons remain neutral.

## Local run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Render deploy (Web Service)
**Build Command**
```bash
pip install -r requirements.txt
```

**Start Command**
```bash
gunicorn app:server --bind 0.0.0.0:$PORT
```

## Updating the Excel
Replace:
`data/CTS_Sydney_SingleStore_PnL_Model_v9_working.xlsx`
and keep the sheet name `Dashboard_Data`.

## Environment variables (optional)
- `CTS_EXCEL_PATH` – override excel path
- `CTS_EXCEL_SHEET` – override sheet name (default `Dashboard_Data`)
- `CTS_GEOJSON_PATH` – override geojson path (default gz in `data/`)
