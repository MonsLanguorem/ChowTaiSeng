import csv
import json
from pathlib import Path

import dash
from dash import Dash, html, dcc, dash_table, Input, Output
import plotly.graph_objects as go
import dash_bootstrap_components as dbc

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
GEOJSON_PATH = DATA_DIR / "sa2_greater_sydney_2021.geojson"
TABLE_PATH = DATA_DIR / "cts_universal_table.csv"


def load_geojson(path: Path) -> dict:
    """Load GeoJSON from one of:
    1) data/*.geojson (plain)
    2) data/*.geojson.gz (gzipped)
    3) data/*.geojson.gz.b64 (base64-encoded gzipped)

    The .gz.b64 fallback is included to avoid issues where cloud-synced folders
    (e.g., iCloud "Optimize Mac Storage") may leave placeholder files in git that
    are only a few bytes long.
    """
    import base64
    import gzip
    import urllib.request

    candidates = [
        path,
        path.with_suffix(path.suffix + ".gz"),
        path.with_suffix(path.suffix + ".gz.b64"),
    ]

    for cand in candidates:
        if not cand.exists():
            continue

        size = cand.stat().st_size
        if size < 100:
            # Likely a placeholder/empty file
            continue

        if cand.name.endswith(".geojson.gz"):
            with gzip.open(cand, "rb") as f:
                raw = f.read()
            return json.loads(raw.decode("utf-8"))

        if cand.name.endswith(".geojson.gz.b64"):
            txt = cand.read_text(encoding="utf-8")
            txt = "".join(txt.split())  # remove newlines/spaces
            gz_bytes = base64.b64decode(txt.encode("ascii"))
            raw = gzip.decompress(gz_bytes)
            return json.loads(raw.decode("utf-8"))

        raw = cand.read_bytes()
        return json.loads(raw.decode("utf-8"))

    # Optional: download if GEOJSON_URL is provided
    url = os.environ.get("GEOJSON_URL", "").strip()
    if url:
        raw = urllib.request.urlopen(url, timeout=60).read()
        # If it looks gzipped, decompress it
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        # Cache as .geojson.gz for faster next boot
        try:
            gz_bytes = gzip.compress(raw, compresslevel=9)
            cache_path = path.with_suffix(path.suffix + ".gz")
            cache_path.write_bytes(gz_bytes)
        except Exception:
            pass
        return json.loads(raw.decode("utf-8"))

    raise ValueError(
        "GeoJSON file missing/empty. Expected one of: "
        f"{candidates[0].name}, {candidates[1].name}, {candidates[2].name}. "
        "If you're using a cloud-synced folder (iCloud/Dropbox), make sure the file is fully downloaded (no cloud icon) "
        "before committing/pushing."
    )


def load_table(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Data table not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            rows.append(r)
        return rows


def coerce_number(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s == "" or s.lower() in {"none", "nan"}:
        return None
    # remove common formatting
    s = s.replace(",", "")
    s = s.replace("$", "")
    try:
        return float(s)
    except ValueError:
        return None


GEOJSON_ALL = load_geojson(GEOJSON_PATH)
ROWS = load_table(TABLE_PATH)

# Required keys
ID_KEY = "SA2_CODE21"
NAME_KEY = "SA2_NAME21"

SA2_CODES = [str(r.get(ID_KEY, "")).strip() for r in ROWS if str(r.get(ID_KEY, "")).strip()]
SA2_SET = set(SA2_CODES)

# Build metric list (numeric columns only)
all_cols = list(ROWS[0].keys()) if ROWS else []
reserved = { "Location_ID", "Location_Name", ID_KEY, NAME_KEY }
metric_cols = []
for c in all_cols:
    if c in reserved:
        continue
    vals = [coerce_number(r.get(c)) for r in ROWS]
    vals = [v for v in vals if v is not None]
    if len(vals) >= 3:  # at least some numeric values
        metric_cols.append(c)

# Create a GeoJSON subset for the 11 selected SA2 polygons
features_selected = []
for ft in GEOJSON_ALL.get("features", []):
    code = str(ft.get("properties", {}).get(ID_KEY, "")).strip()
    if code in SA2_SET:
        features_selected.append(ft)
GEOJSON_SELECTED = {"type": "FeatureCollection", "features": features_selected}

# Lookup dicts
by_sa2 = {}
for r in ROWS:
    code = str(r.get(ID_KEY, "")).strip()
    if code:
        by_sa2[code] = r


def make_fig(metric: str) -> go.Figure:
    # base layer: all SA2 (light outlines)
    all_ids = []
    for ft in GEOJSON_ALL.get("features", []):
        all_ids.append(str(ft.get("properties", {}).get(ID_KEY, "")).strip())

    base = go.Choroplethmapbox(
        geojson=GEOJSON_ALL,
        locations=all_ids,
        z=[0 for _ in all_ids],
        featureidkey=f"properties.{ID_KEY}",
        colorscale=[[0, "#AAAAAA"], [1, "#AAAAAA"]],
        showscale=False,
        marker_opacity=0.06,
        marker_line_width=0.6,
        hoverinfo="skip",
        name="All SA2",
    )

    # focus layer: 11 SA2 with metric values
    sel_ids = []
    z = []
    names = []
    loc_names = []
    for code in SA2_CODES:
        r = by_sa2.get(code, {})
        sel_ids.append(code)
        z.append(coerce_number(r.get(metric)))
        names.append(str(r.get(NAME_KEY, "")))
        loc_names.append(str(r.get("Location_Name", "")))

    focus = go.Choroplethmapbox(
        geojson=GEOJSON_SELECTED,
        locations=sel_ids,
        z=z,
        featureidkey=f"properties.{ID_KEY}",
        colorscale="Viridis",
        marker_opacity=0.62,
        marker_line_width=1.2,
        colorbar=dict(title=metric, len=0.6),
        customdata=list(zip(names, loc_names, z)),
        hovertemplate="<b>%{customdata[0]}</b><br>"
                      "Location: %{customdata[1]}<br>"
                      f"{metric}: %{customdata[2]:,.2f}<extra></extra>",
        name="Selected (11)",
    )

    fig = go.Figure(data=[base, focus])
    fig.update_layout(
        mapbox_style="carto-positron",
        mapbox_zoom=9,
        mapbox_center={"lat": -33.8688, "lon": 151.2093},
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01),
    )
    return fig


def make_bar(metric: str) -> go.Figure:
    x = []
    y = []
    for code in SA2_CODES:
        r = by_sa2.get(code, {})
        x.append(str(r.get("Location_Name", r.get(NAME_KEY, code))))
        y.append(coerce_number(r.get(metric)))
    fig = go.Figure(go.Bar(x=x, y=y))
    fig.update_layout(
        margin={"l": 30, "r": 10, "t": 10, "b": 80},
        xaxis_title="Location / SA2",
        yaxis_title=metric,
    )
    fig.update_xaxes(tickangle=30)
    return fig


app = Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
server = app.server

metric_dropdown = dcc.Dropdown(
    id="metric",
    options=[{"label": c, "value": c} for c in metric_cols],
    value=metric_cols[0] if metric_cols else None,
    clearable=False,
    style={"color": "#000"},
)

app.layout = dbc.Container(
    fluid=True,
    children=[
        html.H2("CTS — Greater Sydney Location Dashboard", style={"marginTop": "12px"}),
        html.Div(
            "Pick a metric to visualise across the 11 candidate SA2 regions. "
            "Map shows all SA2 polygons in light grey, with the 11 selected regions highlighted as a heatmap.",
            style={"opacity": 0.9, "marginBottom": "10px"},
        ),
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Metric"),
                        metric_dropdown,
                    ],
                    md=4,
                ),
                dbc.Col(
                    [
                        html.Div(
                            id="kpi",
                            style={"paddingTop": "26px", "fontSize": "14px", "opacity": 0.9},
                        )
                    ],
                    md=8,
                ),
            ],
            style={"marginBottom": "10px"},
        ),
        dbc.Row(
            [
                dbc.Col(dcc.Graph(id="map", style={"height": "70vh"}), md=8),
                dbc.Col(dcc.Graph(id="bar", style={"height": "70vh"}), md=4),
            ]
        ),
        html.Hr(),
        html.H4("All 11 locations — full table"),
        dash_table.DataTable(
            id="table",
            columns=[{"name": c, "id": c} for c in all_cols],
            data=ROWS,
            sort_action="native",
            filter_action="native",
            page_action="native",
            page_size=20,
            style_table={"overflowX": "auto"},
            style_cell={
                "fontFamily": "Arial",
                "fontSize": "12px",
                "padding": "6px",
                "whiteSpace": "normal",
                "height": "auto",
            },
            style_header={"fontWeight": "bold"},
        ),
        html.Div(
            "Data sources: this app reads a pre-extracted CSV table (Dashboard_Data) and a SA2 GeoJSON file.",
            style={"marginTop": "10px", "opacity": 0.7, "fontSize": "12px"},
        ),
    ],
)

@app.callback(
    Output("map", "figure"),
    Output("bar", "figure"),
    Output("kpi", "children"),
    Input("metric", "value"),
)
def update(metric):
    if not metric:
        return go.Figure(), go.Figure(), ""
    fig_map = make_fig(metric)
    fig_bar = make_bar(metric)
    vals = [coerce_number(r.get(metric)) for r in ROWS]
    vals = [v for v in vals if v is not None]
    kpi = ""
    if vals:
        kpi = f"Selected metric range across 11 locations: min={min(vals):,.2f}, max={max(vals):,.2f}, avg={sum(vals)/len(vals):,.2f}"
    return fig_map, fig_bar, kpi


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=8050, debug=False)
