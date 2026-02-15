import os
import csv
import json
import gzip
import math
import statistics
from datetime import datetime, timezone

import plotly.express as px
import plotly.graph_objects as go

from dash import Dash, dcc, html, Input, Output, State, dash_table, no_update
import dash_bootstrap_components as dbc


# -----------------------------
# Paths / constants
# -----------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "cts_universal_table.csv")

GEOJSON_PATH = os.path.join(DATA_DIR, "sa2_greater_sydney_2021.geojson")
GEOJSON_GZ_PATH = os.path.join(DATA_DIR, "sa2_greater_sydney_2021.geojson.gz")

# SA2 feature ID (matches ABS SA2_CODE21)
FEATURE_ID_KEY = "properties.SA2_CODE21"


# -----------------------------
# Helpers
# -----------------------------
def _parse_number(x):
    """
    Best-effort parse of numbers coming from CSV exported from Excel.
    Accepts: None, "", "1,234", "$1,234.56", "-$1,234", "1.2e6"
    Returns: float or None
    """
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() in {"na", "n/a", "none", "null"}:
        return None

    # Remove currency symbols and spaces
    s = s.replace("$", "").replace("AUD", "").replace("a$", "").replace("A$", "")
    s = s.replace(" ", "").replace(",", "")

    # Handle parentheses negatives: (123) -> -123
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]

    try:
        return float(s)
    except Exception:
        return None


def load_csv(path: str):
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_geojson_any():
    """
    Loads either a .geojson or .geojson.gz file.
    Prefers gz if present.
    """
    if os.path.exists(GEOJSON_GZ_PATH):
        with gzip.open(GEOJSON_GZ_PATH, "rt", encoding="utf-8") as f:
            return json.load(f)
    if os.path.exists(GEOJSON_PATH):
        with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(
        "GeoJSON not found. Expected one of:\n"
        f" - {GEOJSON_GZ_PATH}\n"
        f" - {GEOJSON_PATH}"
    )


def filter_geojson_to_sa2_codes(geojson, sa2_codes: set[str]):
    """Keep only features matching candidate SA2_CODE21 (fast + small payload)."""
    feats = geojson.get("features", [])
    keep = [ft for ft in feats if str(ft.get("properties", {}).get("SA2_CODE21")) in sa2_codes]
    if not keep:
        # Fallback to original geojson if mismatch (won't crash; just slower).
        return geojson
    return {"type": "FeatureCollection", "features": keep}


def metric_columns(rows):
    if not rows:
        return []
    cols = list(rows[0].keys())
    # exclude obvious non-metrics
    exclude = {"Location_ID", "SA2_NAME21", "SA2_CODE21", "Income_Source_URL", "Footfall_Source_URL"}
    candidates = [c for c in cols if c not in exclude and not c.endswith("_URL")]

    numeric = []
    for c in candidates:
        parsed = [_parse_number(r.get(c)) for r in rows]
        if any(v is not None and (not math.isnan(v)) for v in parsed):
            numeric.append(c)
    return numeric


def build_df_map(rows, metric):
    out = []
    for r in rows:
        out.append(
            {
                "SA2_CODE21": str(r.get("SA2_CODE21")),
                "SA2_NAME21": r.get("SA2_NAME21"),
                "Location_ID": r.get("Location_ID"),
                "Metric_Value": _parse_number(r.get(metric)),
                # helpful anchors
                "NPV_5Y_AUD": _parse_number(r.get("NPV_5Y_AUD")),
                "Net_Income_pa": _parse_number(r.get("Net_Income_pa")),
            }
        )
    return out


def fmt(x, digits=0):
    if x is None:
        return "—"
    try:
        return f"{x:,.{digits}f}"
    except Exception:
        return "—"


def build_summary_cards(df_map, metric_label):
    vals = [d["Metric_Value"] for d in df_map if d["Metric_Value"] is not None]
    if not vals:
        return dbc.Alert("No numeric values found for this metric.", color="warning")

    vmin = min(vals)
    vmax = max(vals)
    vmean = statistics.mean(vals)

    # best / worst locations
    best = max(df_map, key=lambda d: -1e18 if d["Metric_Value"] is None else d["Metric_Value"])
    worst = min(df_map, key=lambda d: 1e18 if d["Metric_Value"] is None else d["Metric_Value"])

    def card(title, value, subtitle=None):
        return dbc.Card(
            dbc.CardBody(
                [
                    html.Div(title, className="kpi-title"),
                    html.Div(value, className="kpi-value"),
                    html.Div(subtitle or "", className="kpi-subtitle"),
                ]
            ),
            className="kpi-card",
        )

    return dbc.Row(
        [
            dbc.Col(card("Mean", fmt(vmean, 2), metric_label), md=3),
            dbc.Col(card("Min", fmt(vmin, 2), f"{metric_label} — {worst['SA2_NAME21']}"), md=3),
            dbc.Col(card("Max", fmt(vmax, 2), f"{metric_label} — {best['SA2_NAME21']}"), md=3),
            dbc.Col(card("Locations", str(len(df_map)), "Candidate SA2 regions"), md=3),
        ],
        className="g-3",
    )


# -----------------------------
# Load data once (startup)
# -----------------------------
ROWS = load_csv(CSV_PATH)
SA2_CODES = {str(r.get("SA2_CODE21")) for r in ROWS if r.get("SA2_CODE21")}
GEOJSON_ALL = load_geojson_any()
GEOJSON = filter_geojson_to_sa2_codes(GEOJSON_ALL, SA2_CODES)

METRICS = metric_columns(ROWS)
DEFAULT_METRIC = METRICS[0] if METRICS else None

# Simple caches (prevents re-building figures if user toggles metrics repeatedly)
_MAP_CACHE = {}
_BAR_CACHE = {}
_SCATTER_CACHE = {}


# -----------------------------
# Figure builders
# -----------------------------
def build_map(metric: str):
    if metric in _MAP_CACHE:
        return _MAP_CACHE[metric]

    df_map = build_df_map(ROWS, metric)

    # Use a robust hovertemplate (no Python variables like "customdata"!)
    # customdata: [SA2_NAME21, Location_ID, Metric_Value, Net_Income, NPV]
    customdata = [
        [
            d["SA2_NAME21"],
            d["Location_ID"],
            d["Metric_Value"] if d["Metric_Value"] is not None else float("nan"),
            d["Net_Income_pa"] if d["Net_Income_pa"] is not None else float("nan"),
            d["NPV_5Y_AUD"] if d["NPV_5Y_AUD"] is not None else float("nan"),
        ]
        for d in df_map
    ]

    fig = px.choropleth_mapbox(
        df_map,
        geojson=GEOJSON,
        locations="SA2_CODE21",
        featureidkey=FEATURE_ID_KEY,
        color="Metric_Value",
        hover_name="SA2_NAME21",
        mapbox_style="open-street-map",
        center={"lat": -33.8688, "lon": 151.2093},
        zoom=9.0,
        opacity=0.65,
        color_continuous_scale="Turbo",
    )

    hovertemplate = (
        "<b>%{customdata[0]}</b><br>"
        "Location: %{customdata[1]}<br>"
        f"{metric}: %{{customdata[2]:,.2f}}<br>"
        "Net Income (pa): %{customdata[3]:,.0f}<br>"
        "NPV (5Y): %{customdata[4]:,.0f}"
        "<extra></extra>"
    )

    fig.update_traces(
        customdata=customdata,
        hovertemplate=hovertemplate,
        marker_line_width=1,
        marker_line_color="rgba(255,255,255,0.65)",
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=560,
        paper_bgcolor="white",
        plot_bgcolor="white",
        coloraxis_colorbar=dict(title="", ticks="outside"),
    )

    _MAP_CACHE[metric] = fig
    return fig


def build_metric_bar(metric: str):
    if metric in _BAR_CACHE:
        return _BAR_CACHE[metric]

    df_map = build_df_map(ROWS, metric)
    # sort descending by metric value (None last)
    df_sorted = sorted(df_map, key=lambda d: -1e18 if d["Metric_Value"] is None else d["Metric_Value"], reverse=True)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[d["SA2_NAME21"] for d in df_sorted],
            y=[d["Metric_Value"] for d in df_sorted],
            hovertemplate="<b>%{x}</b><br>Value: %{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"{metric} — comparison across 11 locations",
        margin=dict(l=30, r=20, t=50, b=120),
        height=380,
        xaxis_tickangle=35,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )

    _BAR_CACHE[metric] = fig
    return fig


def build_npv_scatter():
    # Static, but cache anyway
    if "npv_scatter" in _SCATTER_CACHE:
        return _SCATTER_CACHE["npv_scatter"]

    x = []
    y = []
    names = []
    for r in ROWS:
        npv = _parse_number(r.get("NPV_5Y_AUD"))
        ni = _parse_number(r.get("Net_Income_pa"))
        if npv is None or ni is None:
            continue
        x.append(npv)
        y.append(ni)
        names.append(r.get("SA2_NAME21"))

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="markers+text",
            text=[n.split(" - ")[0] for n in names],
            textposition="top center",
            hovertemplate="<b>%{text}</b><br>NPV (5Y): %{x:,.0f}<br>Net Income (pa): %{y:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="NPV (5Y) vs Net Income (pa)",
        xaxis_title="NPV (5Y) — AUD",
        yaxis_title="Net Income (pa) — AUD",
        margin=dict(l=40, r=20, t=50, b=40),
        height=380,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    _SCATTER_CACHE["npv_scatter"] = fig
    return fig


def build_table(rows):
    # Keep all fields, but make URLs clickable.
    cols = list(rows[0].keys()) if rows else []
    # Put key identifiers first
    preferred = ["Location_ID", "SA2_NAME21", "SA2_CODE21"]
    ordered = preferred + [c for c in cols if c not in preferred]
    columns = [{"name": c, "id": c, "presentation": "markdown" if c.endswith("_URL") else "input"} for c in ordered]

    def row_to_display(r):
        out = dict(r)
        for k, v in list(out.items()):
            if k.endswith("_URL") and v:
                out[k] = f"[link]({v})"
        return out

    data = [row_to_display(r) for r in rows]

    return dash_table.DataTable(
        id="full-table",
        columns=columns,
        data=data,
        page_size=15,
        sort_action="native",
        filter_action="native",
        row_selectable=False,
        style_table={"overflowX": "auto"},
        style_cell={
            "fontFamily": "system-ui, -apple-system, Segoe UI, Roboto, Arial",
            "fontSize": 12,
            "padding": "8px",
            "minWidth": "110px",
            "maxWidth": "380px",
            "whiteSpace": "normal",
        },
        style_header={
            "backgroundColor": "#111827",
            "color": "white",
            "fontWeight": "600",
            "border": "0px",
        },
        style_data={"border": "0px"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#F9FAFB"},
        ],
        markdown_options={"link_target": "_blank"},
        fixed_rows={"headers": True},
    )


# -----------------------------
# App / layout
# -----------------------------
app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="CTS — Greater Sydney Location Dashboard",
)
server = app.server

map_initial = build_map(DEFAULT_METRIC) if DEFAULT_METRIC else go.Figure()
bar_initial = build_metric_bar(DEFAULT_METRIC) if DEFAULT_METRIC else go.Figure()
scatter_initial = build_npv_scatter()
summary_initial = build_summary_cards(build_df_map(ROWS, DEFAULT_METRIC), DEFAULT_METRIC) if DEFAULT_METRIC else dbc.Alert("No metrics found.", color="warning")

app.layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H1("CTS — Greater Sydney Location Dashboard", className="app-title"),
                        html.Div(
                            "Pick a metric, then click Update. Map highlights the 11 candidate SA2 regions. "
                            "Hover any region to see SA2 name + key metrics.",
                            className="app-subtitle",
                        ),
                    ],
                    md=9,
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div("Status", className="status-title"),
                                html.Div("Ready", id="status-text", className="status-value"),
                                html.Div("—", id="last-updated", className="status-subtitle"),
                            ]
                        ),
                        className="status-card",
                    ),
                    md=3,
                ),
            ],
            className="mt-3 mb-2",
        ),

        dbc.Card(
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Label("Metric", className="control-label"),
                                dcc.Dropdown(
                                    id="metric",
                                    options=[{"label": m, "value": m} for m in METRICS],
                                    value=DEFAULT_METRIC,
                                    clearable=False,
                                    className="control-dropdown",
                                ),
                            ],
                            md=8,
                        ),
                        dbc.Col(
                            dbc.Button(
                                "Update",
                                id="btn-update",
                                color="primary",
                                className="w-100 mt-4",
                                n_clicks=0,
                            ),
                            md=2,
                        ),
                        dbc.Col(
                            dbc.Button(
                                "Reset caches",
                                id="btn-reset",
                                color="secondary",
                                outline=True,
                                className="w-100 mt-4",
                                n_clicks=0,
                            ),
                            md=2,
                        ),
                    ],
                    className="g-3 align-items-end",
                )
            ),
            className="controls-card",
        ),

        html.Div(summary_initial, id="summary-cards", className="mt-3"),

        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            dbc.Spinner(
                                dcc.Graph(id="map", figure=map_initial, config={"displayModeBar": False}),
                                color="light",
                                fullscreen=False,
                                spinner_style={"width": "3rem", "height": "3rem"},
                            )
                        ),
                        className="viz-card",
                    ),
                    md=7,
                ),
                dbc.Col(
                    [
                        dbc.Card(
                            dbc.CardBody(
                                dbc.Spinner(
                                    dcc.Graph(id="bar", figure=bar_initial, config={"displayModeBar": False}),
                                    color="light",
                                    fullscreen=False,
                                )
                            ),
                            className="viz-card mb-3",
                        ),
                        dbc.Card(
                            dbc.CardBody(
                                dbc.Spinner(
                                    dcc.Graph(id="scatter", figure=scatter_initial, config={"displayModeBar": False}),
                                    color="light",
                                    fullscreen=False,
                                )
                            ),
                            className="viz-card",
                        ),
                    ],
                    md=5,
                ),
            ],
            className="mt-3 g-3",
        ),

        dbc.Card(
            [
                dbc.CardHeader("All 11 locations — full table"),
                dbc.CardBody(build_table(ROWS)),
            ],
            className="mt-3 mb-5",
        ),

        html.Div(
            "Data source: this app reads a pre-extracted CSV table + ABS SA2 (2021) polygons. "
            "For speed, polygons are filtered to the 11 candidate SA2 codes.",
            className="footer-note",
        ),
    ],
    fluid=True,
)


# -----------------------------
# Callbacks
# -----------------------------
@app.callback(
    Output("map", "figure"),
    Output("bar", "figure"),
    Output("summary-cards", "children"),
    Output("status-text", "children"),
    Output("last-updated", "children"),
    Input("btn-update", "n_clicks"),
    Input("btn-reset", "n_clicks"),
    State("metric", "value"),
    prevent_initial_call=True,
)
def update(n_clicks_update, n_clicks_reset, metric):
    ctx = __import__("dash").callback_context
    trigger = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None

    if trigger == "btn-reset":
        _MAP_CACHE.clear()
        _BAR_CACHE.clear()
        _SCATTER_CACHE.clear()
        return build_map(metric), build_metric_bar(metric), build_summary_cards(build_df_map(ROWS, metric), metric), "Ready (cache reset)", _now()

    if not metric:
        return no_update, no_update, no_update, "Ready", _now()

    # Build figures (cached)
    fig_map = build_map(metric)
    fig_bar = build_metric_bar(metric)
    summary = build_summary_cards(build_df_map(ROWS, metric), metric)

    return fig_map, fig_bar, summary, "Updated", _now()


def _now():
    return "Last updated: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


if __name__ == "__main__":
    app.run_server(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", "8050")))
