# CTS Greater Sydney Dashboard (Dash + Plotly)

## What this repo does
- Reads the *universal* table from the Excel model (sheet: `Dashboard_Data`)
- Renders a Greater Sydney SA2 choropleth + location markers
- Lets you switch metrics, view rankings, and explore a full 11-location table

## Folder structure
- `app.py`
- `requirements.txt`
- `runtime.txt` (optional)
- `python-version.txt` (optional)
- `data/`
  - `CTS_Sydney_SingleStore_PnL_Model_v8.xlsx`
  - `sa2_greater_sydney_2021.geojson`

## Run locally
```bash
pip install -r requirements.txt
python app.py
```

## Deploy to Render
Create a new **Web Service** from this repo.

**Start command**:
```bash
gunicorn app:server
```

**Environment**:
- Python (Render will read `runtime.txt` / `python-version.txt` if present)

If you update the Excel model:
1) Replace `data/CTS_Sydney_SingleStore_PnL_Model_v8.xlsx`
2) Ensure the sheet name stays `Dashboard_Data`
3) Redeploy / trigger a new build
