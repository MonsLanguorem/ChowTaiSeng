import csv
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import dash
from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

# -----------------------------
# Paths / constants
# -----------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_FILE = DATA_DIR / "dashboard_data.csv"

APP_TITLE = "CTS — Greater Sydney Location Dashboard"

# Cache for expensive figure creation (small here, but keeps UI snappy)
_CACHE: Dict[Tuple[str, str], Any] = {}

# -----------------------------
# Metric metadata (labels + FAQ)
# -----------------------------
METRIC_META: Dict[str, Dict[str, str]] = {
    "NPV_5Y_AUD": {
        "label": "NPV (5Y) — AUD",
        "desc": "Net Present Value over 5 years. Higher is better (more value created).",
    },
    "Net_Income_pa": {
        "label": "Net Income (pa) — AUD",
        "desc": "Annual net profit after operating costs (and after the model’s cost assumptions).",
    },
    "EBIT_pa": {
        "label": "EBIT (pa) — AUD",
        "desc": "Earnings Before Interest and Tax per year — operating profit before financing and tax.",
    },
    "Revenue_pa": {
        "label": "Revenue (pa) — AUD",
        "desc": "Estimated annual revenue.",
    },
    "Gross_Profit_pa": {
        "label": "Gross Profit (pa) — AUD",
        "desc": "Revenue minus COGS (cost of goods sold).",
    },
    "COGS_pa": {
        "label": "COGS (pa) — AUD",
        "desc": "Cost of goods sold. Typically shown as a negative number in the model.",
    },
    "Total_OPEX_pa": {
        "label": "Total OPEX (pa) — AUD",
        "desc": "Total annual operating expenses (typically negative in the model).",
    },
    "Rent_Total_AUD_pa": {
        "label": "Total Rent (pa) — AUD",
        "desc": "Total annual rent payment.",
    },
    "Rent_per_sqm_pa": {
        "label": "Rent per sqm (pa) — AUD",
        "desc": "Annual rent per square metre.",
    },
    "Store_Size_sqm": {
        "label": "Store Size — sqm",
        "desc": "Assumed store size (square metres).",
    },
    "Sales_Index": {
        "label": "Sales Index",
        "desc": "Relative sales multiplier used in the model (higher = stronger sales potential).",
    },
    "Income_Index": {
        "label": "Income Index",
        "desc": "Relative index of household income in the catchment (higher = wealthier).",
    },
    "Footfall_Index": {
        "label": "Footfall Index",
        "desc": "Relative index of footfall / pedestrian traffic (higher = busier).",
    },
    "Income_Proxy_HH_Weekly": {
        "label": "Income Proxy (HH weekly)",
        "desc": "Proxy for household weekly income used as an input into Income Index.",
    },
    "Footfall_Proxy": {
        "label": "Footfall Proxy",
        "desc": "Proxy for footfall used as an input into Footfall Index.",
    },
    "Initial_Investment_AUD": {
        "label": "Initial Investment — AUD",
        "desc": "Up-front investment required to open the store (fit-out, setup, etc.).",
    },
}

# -----------------------------
# Data loading
# -----------------------------

def _sniff_delimiter(sample: str) -> str:
    """Detect delimiter among comma / tab / semicolon."""
    candidates = [",", "\t", ";"]
    best = ","
    best_count = -1
    for d in candidates:
        c = sample.count(d)
        if c > best_count:
            best_count = c
            best = d
    return best


def _to_float(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none"}:
        return None
    # tolerate commas in numbers
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return v


def load_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing data file: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delim = _sniff_delimiter(sample)
        reader = csv.DictReader(f, delimiter=delim)
        rows: List[Dict[str, Any]] = []
        for r in reader:
            rr: Dict[str, Any] = {}
            for k, v in r.items():
                if k is None:
                    continue
                kk = str(k).strip()
                rr[kk] = _to_float(v)
            rows.append(rr)

    # Basic sanity
    if not rows:
        raise ValueError("Data file loaded but contains 0 rows")
    return rows


ROWS = load_rows(DATA_FILE)

# Identify columns
ALL_COLUMNS = list(ROWS[0].keys())

# Map columns
LAT_COL = "Latitude"
LON_COL = "Longitude"
NAME_COL = "Display_Name"

# Numeric metric candidates
EXCLUDE_FROM_METRICS = {"Location_ID", "Area", "Anchor", "Type", "SA2_NAME21", "SA2_CODE21", NAME_COL, LAT_COL, LON_COL,
                        "Income_Source_URL", "Footfall_Source_URL"}


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and x is not None and not (x != x)  # NaN check


def infer_metrics(rows: List[Dict[str, Any]]) -> List[str]:
    metrics: List[str] = []
    for col in ALL_COLUMNS:
        if col in EXCLUDE_FROM_METRICS:
            continue
        # count numeric values
        nums = sum(1 for r in rows if _is_number(r.get(col)))
        if nums >= max(3, int(0.5 * len(rows))):
            metrics.append(col)
    # Prefer key metrics first
    preferred = [
        "NPV_5Y_AUD",
        "Net_Income_pa",
        "EBIT_pa",
        "Revenue_pa",
        "Gross_Profit_pa",
        "Rent_Total_AUD_pa",
        "Rent_per_sqm_pa",
        "Store_Size_sqm",
        "Sales_Index",
        "Income_Index",
        "Footfall_Index",
    ]
    ordered: List[str] = []
    for p in preferred:
        if p in metrics:
            ordered.append(p)
    for m in metrics:
        if m not in ordered:
            ordered.append(m)
    return ordered


METRICS = infer_metrics(ROWS)
DEFAULT_METRIC = "NPV_5Y_AUD" if "NPV_5Y_AUD" in METRICS else (METRICS[0] if METRICS else "Store_Size_sqm")


def metric_label(metric: str) -> str:
    return METRIC_META.get(metric, {}).get("label", metric)


# -----------------------------
# Figure builders
# -----------------------------

def _get_values(metric: str) -> List[float]:
    vals = []
    for r in ROWS:
        v = r.get(metric)
        if _is_number(v):
            vals.append(float(v))
    return vals


def build_summary_cards(metric: str) -> List[dbc.Col]:
    vals = _get_values(metric)
    if not vals:
        mean_v = min_v = max_v = None
        min_name = max_name = "—"
    else:
        mean_v = sum(vals) / len(vals)
        # min/max rows
        min_row = min(ROWS, key=lambda r: float(r.get(metric)) if _is_number(r.get(metric)) else float("inf"))
        max_row = max(ROWS, key=lambda r: float(r.get(metric)) if _is_number(r.get(metric)) else float("-inf"))
        min_v = min_row.get(metric)
        max_v = max_row.get(metric)
        min_name = str(min_row.get(NAME_COL) or min_row.get("Anchor") or min_row.get("Location_ID") or "—")
        max_name = str(max_row.get(NAME_COL) or max_row.get("Anchor") or max_row.get("Location_ID") or "—")

    fmt = lambda x: "—" if x is None or (isinstance(x, float) and x != x) else f"{x:,.2f}"

    cards = [
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.Div("Mean", className="card-title"),
                    html.Div(fmt(mean_v), className="card-value"),
                    html.Div(metric, className="card-subtitle"),
                ]),
                className="metric-card",
            ),
            md=3,
        ),
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.Div("Min", className="card-title"),
                    html.Div(fmt(min_v), className="card-value"),
                    html.Div(f"{metric} — {min_name}", className="card-subtitle"),
                ]),
                className="metric-card",
            ),
            md=3,
        ),
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.Div("Max", className="card-title"),
                    html.Div(fmt(max_v), className="card-value"),
                    html.Div(f"{metric} — {max_name}", className="card-subtitle"),
                ]),
                className="metric-card",
            ),
            md=3,
        ),
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.Div("Locations", className="card-title"),
                    html.Div(str(len(ROWS)), className="card-value"),
                    html.Div("Candidate store locations", className="card-subtitle"),
                ]),
                className="metric-card",
            ),
            md=3,
        ),
    ]
    return cards


def _jitter_points(lats: List[float], lons: List[float]) -> Tuple[List[float], List[float]]:
    """Deterministic tiny jitter for exact duplicates (so overlapping stores become visible)."""
    seen: Dict[Tuple[float, float], int] = {}
    out_lat, out_lon = [], []
    for lat, lon in zip(lats, lons):
        key = (round(lat, 6), round(lon, 6))
        idx = seen.get(key, 0)
        seen[key] = idx + 1
        # ~50-150m offsets depending on idx
        d = 0.0006
        out_lat.append(lat + (idx % 3 - 1) * d)
        out_lon.append(lon + ((idx // 3) % 3 - 1) * d)
    return out_lat, out_lon


def build_point_map(metric: str) -> go.Figure:
    cache_key = ("map", metric)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    lats: list[float] = []
    lons: list[float] = []
    names: list[str] = []
    values: list[float] = []

    for r in ROWS:
        lat = r.get(LAT_COL)
        lon = r.get(LON_COL)
        v = r.get(metric)
        if _is_number(lat) and _is_number(lon) and _is_number(v):
            lats.append(float(lat))
            lons.append(float(lon))
            names.append(str(r.get(NAME_COL, "")))
            values.append(float(v))

    # Always return a valid Figure, even if inputs are missing
    fig = go.Figure()

    if not lats:
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0b1220",
            plot_bgcolor="#0b1220",
            margin=dict(l=10, r=10, t=40, b=10),
            height=700,
            title="Map — no valid coordinates/values",
        )
        _CACHE[cache_key] = fig
        return fig

    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    fig.add_trace(
        go.Scattermapbox(
            lat=lats,
            lon=lons,
            mode="markers",
            text=names,
            customdata=values,
            hovertemplate="<b>%{text}</b><br>"
                          + metric_label(metric)
                          + ": %{customdata:,.2f}<extra></extra>",
            marker=dict(
                size=14,
                color=values,
                colorscale="RdYlGn",  # low=red, high=green
                showscale=True,
                colorbar=dict(
                    title=metric_label(metric),
                    tickformat=",.0f",
                ),
                line=dict(width=1, color="#111827"),
            ),
        )
    )

    fig.update_layout(
        template="plotly_dark",
        title=f"{metric_label(metric)} — map of {len(lats)} store points",
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="#0b1220",
        plot_bgcolor="#0b1220",
        mapbox=dict(
            style="carto-positron",  # less colourful base layer
            center=dict(lat=center_lat, lon=center_lon),
            zoom=10,
        ),
        height=700,
    )

    _CACHE[cache_key] = fig
    return fig

def build_bar(metric: str) -> go.Figure:
    cache_key = ("bar", metric)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    data = []
    for r in ROWS:
        nm = str(r.get(NAME_COL) or r.get("Anchor") or r.get("Location_ID") or "")
        v = r.get(metric)
        if _is_number(v):
            data.append((nm, float(v)))

    data.sort(key=lambda x: x[1], reverse=True)

    fig = go.Figure(
        go.Bar(
            x=[x[0] for x in data],
            y=[x[1] for x in data],
            hovertemplate=f"%{{x}}<br>{metric_label(metric)}: %{{y:,.2f}}<extra></extra>",
        )
    )

    fig.update_layout(
        template="plotly_dark",
        title=f"{metric_label(metric)} — comparison across {len(data)} locations",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=50, b=80),
        xaxis=dict(tickangle=-35),
        height=420,
    )

    _CACHE[cache_key] = fig
    return fig


def build_scatter_npv_net_income() -> go.Figure:
    cache_key = ("scatter", "npv_net")
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    xs, ys = [], []
    hover = []
    for r in ROWS:
        npv = r.get("NPV_5Y_AUD")
        ni = r.get("Net_Income_pa")
        if not _is_number(npv) or not _is_number(ni):
            continue
        nm = str(r.get(NAME_COL) or r.get("Anchor") or r.get("Location_ID") or "")
        xs.append(float(npv))
        ys.append(float(ni))
        hover.append(nm)

    fig = go.Figure(
        go.Scatter(
            x=xs,
            y=ys,
            mode="markers",
            marker=dict(size=11, opacity=0.9),
            hovertext=hover,
            hovertemplate=(
                "<b>%{hovertext}</b><br>"
                "NPV (5Y): %{x:,.0f} AUD<br>"
                "Net Income (pa): %{y:,.0f} AUD<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        template="plotly_dark",
        title="NPV (5Y) vs Net Income (pa)",
        xaxis=dict(
            title="NPV (5Y) — AUD",
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor="rgba(255,255,255,0.55)",
        ),
        yaxis=dict(
            title="Net Income (pa) — AUD",
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor="rgba(255,255,255,0.55)",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=50, b=40),
        height=420,
    )

    _CACHE[cache_key] = fig
    return fig

# -----------------------------
# UI components
# -----------------------------

def build_table(rows: List[Dict[str, Any]]) -> dash_table.DataTable:
    columns = [{"name": c, "id": c} for c in ALL_COLUMNS]

    # Make strings explicit for dash table
    table_rows: List[Dict[str, Any]] = []
    for r in rows:
        rr = {}
        for k in ALL_COLUMNS:
            v = r.get(k)
            if isinstance(v, float) and v != v:  # NaN
                rr[k] = None
            else:
                rr[k] = v
        table_rows.append(rr)

    return dash_table.DataTable(
        id="full-table",
        columns=columns,
        data=table_rows,
        page_size=11,
        filter_action="native",
        sort_action="native",
        sort_mode="multi",
        fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "maxHeight": "460px", "overflowY": "auto"},
        style_header={
            "backgroundColor": "#0b1220",
            "color": "#e5e7eb",
            "fontWeight": "600",
            "border": "1px solid #1f2937",
        },
        style_data={
            "backgroundColor": "#111827",
            "color": "#e5e7eb",
            "border": "1px solid #1f2937",
            "fontSize": "12px",
        },
        style_cell={
            "padding": "8px",
            "minWidth": "120px",
            "width": "160px",
            "maxWidth": "260px",
            "whiteSpace": "nowrap",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
        },
        style_data_conditional=[
            {
                "if": {"row_index": "odd"},
                "backgroundColor": "#0f172a",
            }
        ],
    )


def build_faq() -> dbc.Accordion:
    # Keep it brief + practical
    items = []

    def add_item(title: str, body: str) -> None:
        items.append(
            dbc.AccordionItem(
                html.Div(body, className="faq-text"),
                title=title,
            )
        )

    add_item(
        "How to use this dashboard?",
        "1) Choose a metric in the dropdown. 2) The map and charts update automatically. "
        "3) Hover any point to see the location and key financial metrics. "
        "4) Use the table filters to quickly find or compare locations.",
    )

    add_item(
        "What is NPV (5Y)?",
        "NPV is the Net Present Value of expected cashflows over 5 years, discounted to today. "
        "In this model: higher NPV means the store location is expected to create more value.",
    )

    add_item(
        "What is Net Income (pa) vs EBIT (pa)?",
        "Net Income (pa) is the annual profit after operating costs (and the model’s assumptions). "
        "EBIT (pa) is operating profit before interest and tax — useful to compare operational performance.",
    )

    add_item(
        "What do the indices mean (Sales / Income / Footfall Index)?",
        "Indices are relative multipliers. Higher value = stronger signal (e.g., higher footfall, higher income, higher sales potential). "
        "They help the model scale revenue and/or demand assumptions consistently across locations.",
    )

    add_item(
        "Why do some points look very close?",
        "Some candidate stores sit in the same SA2 / neighbourhood. If two points share identical coordinates, "
        "the dashboard applies a tiny visual offset so both remain clickable.",
    )

    add_item(
        "Where do income & footfall inputs come from?",
        "The table includes Income_Source_URL and Footfall_Source_URL columns. Use those links to trace the original sources used for proxies/indices.",
    )

    return dbc.Accordion(items, start_collapsed=True, always_open=False)


# -----------------------------
# Dash app
# -----------------------------

external_stylesheets = [dbc.themes.DARKLY]
app: Dash = dash.Dash(__name__, external_stylesheets=external_stylesheets, title=APP_TITLE)
server = app.server  # for gunicorn/WSGI deployments
server = app.server

metric_options = [{"label": f"{metric_label(m)} ({m})" if metric_label(m) != m else m, "value": m} for m in METRICS]

app.layout = dbc.Container(
    fluid=True,
    className="app-container",
    children=[
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H1(APP_TITLE, className="app-title"),
                        html.Div(
                            "Pick a metric to compare the 11 candidate store locations. "
                            "Points are coloured by the selected metric; hover for details.",
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
                                html.Div("Ready", id="status", className="status-value"),
                                html.Div("", id="status-sub", className="status-sub"),
                            ]
                        ),
                        className="status-card",
                    ),
                    md=3,
                ),
            ],
            className="mb-3",
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
                                    options=metric_options,
                                    value=DEFAULT_METRIC,
                                    clearable=False,
                                    searchable=True,
                                    className="metric-dropdown",
                                ),
                            ],
                            md=8,
                        ),
                        dbc.Col(
                            dbc.Button(
                                "Reset caches",
                                id="reset-cache",
                                color="secondary",
                                outline=True,
                                className="w-100 mt-4",
                            ),
                            md=4,
                        ),
                    ],
                    align="end",
                )
            ),
            className="control-card mb-3",
        ),

        dbc.Row(id="cards", className="g-3 mb-3"),

        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            dcc.Loading(
                                dcc.Graph(
                                    id="map",
                                    config={"displayModeBar": True, "scrollZoom": True},
                                    style={"height": "720px"},
                                ),
                                type="default",
                            )
                        ),
                        className="panel-card",
                    ),
                    md=12,
                ),
            ],
            className="g-3 mb-3",
        ),

        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            dcc.Loading(
                                dcc.Graph(id="bar", config={"displayModeBar": True}, style={"height": "420px"}),
                                type="default",
                            )
                        ),
                        className="panel-card",
                    ),
                    md=6,
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            dcc.Loading(
                                dcc.Graph(id="scatter", config={"displayModeBar": True}, style={"height": "420px"}),
                                type="default",
                            )
                        ),
                        className="panel-card",
                    ),
                    md=6,
                ),
            ],
            className="g-3 mb-3",
        ),

        # IMPORTANT: Dash components accept only ONE positional argument.
        # If you pass multiple positional children, the second one is treated as `id`.
        # Wrap multiple children in a list.
        dbc.Card(
            [
                dbc.CardHeader("All locations — full table", className="section-header"),
                dbc.CardBody(build_table(ROWS)),
            ],
            className="mb-4",
        ),

        dbc.Card(
            dbc.CardBody(
                [
                    html.H4("FAQ", className="section-title"),
                    build_faq(),
                ]
            ),
            className="panel-card mb-3",
        ),

        # hidden store for caching state if needed later
        dcc.Store(id="dummy"),
    ],
)


@app.callback(
    Output("cards", "children"),
    Output("map", "figure"),
    Output("bar", "figure"),
    Output("scatter", "figure"),
    Output("status", "children"),
    Output("status-sub", "children"),
    Input("metric", "value"),
    Input("reset-cache", "n_clicks"),
)
def update(metric: str, reset_clicks: int | None):
    # Reset caches
    if reset_clicks:
        _CACHE.clear()

    metric = metric or DEFAULT_METRIC

    cards = build_summary_cards(metric)
    fig_map = build_point_map(metric)
    fig_bar = build_bar(metric)
    fig_scatter = build_scatter_npv_net_income()

    status = "Updated"
    sub = f"Metric: {metric_label(metric)}"

    return cards, fig_map, fig_bar, fig_scatter, status, sub


if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", "8050")))
