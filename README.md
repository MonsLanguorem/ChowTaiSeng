# CTS Sydney Dashboard (Render-ready)

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8050

## Render settings
Create a **Web Service** from this repo.

**Build Command**
```bash
pip install -r requirements.txt
```

**Start Command**
```bash
gunicorn app:server --bind 0.0.0.0:$PORT
```

### Notes
- This version intentionally avoids `pandas` so it works even if Render builds with a newer Python runtime.
- Data is loaded from `data/dashboard_data.csv` (exported from your Excel sheet `Dashboard_Data`).
