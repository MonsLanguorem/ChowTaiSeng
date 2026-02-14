
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import dash
from dash import dcc, html, dash_table, Input, Output
import dash_bootstrap_components as dbc


# ---------------------------
# Paths (Render/GitHub ready)
# ---------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

GEOJSON_PATH = DATA_DIR / "sa2_greater_sydney_2021.geojson"
EXCEL_PATH = DATA_DIR / "CTS_Sydney_SingleStore_PnL_Model_v8.xlsx"
EXCEL_SHEET = "Dashboard_Data"


# ---------------------------
# Data loading
# ---------------------------
def load_geojson(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_dashboard_df(excel_path: Path, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(excel_path, sheet_name=sheet, engine="openpyxl")
    # Coerce numerics where possible
    for c in df.columns:
        if c in {"Location_ID", "Area", "Type", "SA2_CODE21", "SA2_NAME21", "SA2_Mapping_Method", "Last_Updated"}:
            continue
        df[c] = pd.to_numeric(df[c], errors="ignore")
    # Ensure SA2_CODE is string for matching geojson properties
    df["SA2_CODE21"] = df["SA2_CODE21"].astype(str)
    return df

GEOJSON = load_geojson(GEOJSON_PATH)
DF_LOC = load_dashboard_df(EXCEL_PATH, EXCEL_SHEET)

# Build SA2 lookup from geojson
SA2_LOOKUP = {}
for ft in GEOJSON.get("features", []):
    props = ft.get("properties", {})
    code = str(props.get("SA2_CODE21"))
    SA2_LOOKUP[code] = {
        "SA2_NAME21": props.get("SA2_NAME21"),
    }

# Join SA2 names from geojson (authoritative) if missing/inconsistent
DF_LOC["SA2_NAME21"] = DF_LOC.apply(
    lambda r: SA2_LOOKUP.get(str(r["SA2_CODE21"]), {}).get("SA2_NAME21", r.get("SA2_NAME21")),
    axis=1
)

# Metric options: numeric columns only, exclude coordinates
EXCLUDE = {"Centroid_Lat", "Centroid_Lon"}
NUM_COLS = [c for c in DF_LOC.columns if c not in EXCLUDE and pd.api.types.is_numeric_dtype(DF_LOC[c])]
# Keep the most useful first
PREFERRED_ORDER = [
    "Revenue_pa", "Gross_Profit_pa", "Total_OPEX_pa", "EBIT_pa", "Net_Income_pa",
    "Initial_Investment_AUD", "NPV_5y_AUD",
    "Sales_Index", "Gross_Margin_%", "EBIT_Margin_%", "Net_Margin_%"
]
METRICS = [c for c in PREFERRED_ORDER if c in NUM_COLS] + [c for c in NUM_COLS if c not in PREFERRED_ORDER]

# Simple formatting map
CURRENCY_COLS = {c for c in METRICS if any(k in c for k in ["_pa", "AUD"]) and "%" not in c}
PCT_COLS = {c for c in METRICS if "%" in c}

def fmt_value(col: str, v):
    if pd.isna(v):
        return ""
    try:
        if col in PCT_COLS:
            return f"{float(v)*100:,.1f}%"
        if col in CURRENCY_COLS:
            return f"A${float(v):,.0f}"
        return f"{float(v):,.3g}"
    except Exception:
        return str(v)

def metric_aggregation(col: str) -> str:
    # If multiple candidate locations map to the same SA2, we aggregate for the polygon fill.
    if col in PCT_COLS or "Index" in col:
        return "mean"
    # Most money metrics should sum if they overlap (rare); change to mean if you prefer.
    return "sum"


# ---------------------------
# Map helpers
# ---------------------------
def jitter_latlon(lat, lon, idx, scale=0.002):
    # deterministic jitter to separate markers that share the same SA2 centroid
    angle = (idx * 137.50776405) % 360  # golden angle
    rad = math.radians(angle)
    r = scale * (1 + (idx % 3) * 0.35)
    return lat + r * math.sin(rad), lon + r * math.cos(rad)

def build_map(metric: str):
    # Aggregate to SA2-level for polygon fill
    agg = metric_aggregation(metric)
    df_sa2 = DF_LOC.groupby(["SA2_CODE21", "SA2_NAME21"], as_index=False)[metric].agg(agg)
    df_sa2.rename(columns={metric: "metric_value"}, inplace=True)

    # Choropleth mapbox: only SA2s with values will be coloured; rest remain blank.
    fig = px.choropleth_mapbox(
        df_sa2,
        geojson=GEOJSON,
        featureidkey="properties.SA2_CODE21",
        locations="SA2_CODE21",
        color="metric_value",
        hover_name="SA2_NAME21",
        hover_data={"SA2_CODE21": True, "metric_value": True},
        mapbox_style="open-street-map",
        zoom=9.2,
        center={"lat": -33.865, "lon": 151.21},
        opacity=0.55,
    )

    # Cleaner hover
    fig.update_traces(
        hovertemplate="<b>%{hovertext}</b><br>" +
                      "SA2: %{customdata[0]}<br>" +
                      f"{metric}: " + "%{z:.3g}<extra></extra>",
        customdata=np.stack([df_sa2["SA2_CODE21"]], axis=-1),
        marker_line_width=0.2,
        selector=dict(type="choroplethmapbox")
    )

    # Add location markers (11 candidate locations)
    # If multiple locations share a centroid, we jitter them slightly so they all appear.
    lats, lons, texts = [], [], []
    for i, r in DF_LOC.reset_index(drop=True).iterrows():
        lat, lon = r["Centroid_Lat"], r["Centroid_Lon"]
        if pd.isna(lat) or pd.isna(lon):
            continue
        jlat, jlon = jitter_latlon(float(lat), float(lon), i)
        lats.append(jlat); lons.append(jlon)
        texts.append(
            f"<b>{r['Location_ID']}</b><br>"
            f"Area: {r['Area']}<br>"
            f"SA2: {r['SA2_NAME21']}<br>"
            f"{metric}: {fmt_value(metric, r.get(metric))}"
        )

    fig.add_trace(go.Scattermapbox(
        lat=lats,
        lon=lons,
        mode="markers",
        marker={"size": 10, "opacity": 0.9},
        hovertemplate="%{text}<extra></extra>",
        text=texts,
        name="Candidate locations"
    ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01),
        coloraxis_colorbar=dict(title=metric),
    )
    return fig

def build_bar(metric: str):
    df = DF_LOC[["Location_ID", "Area", metric]].copy()
    df = df.sort_values(metric, ascending=True)
    fig = px.bar(df, x=metric, y="Location_ID", orientation="h", hover_data=["Area"])
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=380)
    return fig

def build_summary(metric: str):
    s = DF_LOC[metric].dropna()
    if s.empty:
        return {}
    return {
        "min": s.min(),
        "p25": s.quantile(0.25),
        "median": s.median(),
        "mean": s.mean(),
        "p75": s.quantile(0.75),
        "max": s.max(),
    }


# ---------------------------
# Dash app
# ---------------------------
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
server = app.server

app.layout = dbc.Container(fluid=True, children=[
    dbc.Row([
        dbc.Col([
            html.H2("CTS — Greater Sydney Candidate Locations Dashboard", className="mt-3"),
            html.Div(
                "Pick a metric to colour SA2 polygons (where we have data) and compare the 11 candidate locations.",
                className="text-muted"
            ),
        ], width=9),
        dbc.Col([
            html.Div("Metric", className="mt-3"),
            dcc.Dropdown(
                id="metric",
                options=[{"label": m, "value": m} for m in METRICS],
                value="Net_Income_pa" if "Net_Income_pa" in METRICS else METRICS[0],
                clearable=False
            )
        ], width=3),
    ], align="center"),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("SA2 map (Greater Sydney)"),
                dbc.CardBody([
                    dcc.Graph(id="map", config={"displayModeBar": True}, style={"height": "72vh"})
                ])
            ], className="mt-3")
        ], width=8),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Quick stats (11 locations)"),
                dbc.CardBody(id="summary_cards")
            ], className="mt-3"),

            dbc.Card([
                dbc.CardHeader("Location ranking"),
                dbc.CardBody([
                    dcc.Graph(id="bar", config={"displayModeBar": False})
                ])
            ], className="mt-3"),
        ], width=4),
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("All 11 locations — full table"),
                dbc.CardBody([
                    dash_table.DataTable(
                        id="table",
                        columns=[],
                        data=[],
                        sort_action="native",
                        filter_action="native",
                        page_action="native",
                        page_size=15,
                        style_table={"overflowX": "auto"},
                        style_cell={"fontFamily": "Arial", "fontSize": 12, "padding": "6px"},
                        style_header={"fontWeight": "bold"},
                    )
                ])
            ], className="mt-3 mb-4"),
        ])
    ])
])


@app.callback(
    Output("map", "figure"),
    Output("bar", "figure"),
    Output("table", "columns"),
    Output("table", "data"),
    Output("summary_cards", "children"),
    Input("metric", "value")
)
def update(metric: str):
    fig_map = build_map(metric)
    fig_bar = build_bar(metric)

    # Table columns: show a compact set first + selected metric + key economics
    base_cols = ["Location_ID", "Area", "Type", "SA2_NAME21", "Sales_Index", "Revenue_pa", "Gross_Profit_pa", "Total_OPEX_pa", "EBIT_pa", "Net_Income_pa", "Initial_Investment_AUD", "NPV_5y_AUD"]
    cols = [c for c in base_cols if c in DF_LOC.columns]
    if metric not in cols:
        cols.insert(5, metric)

    table_df = DF_LOC[cols].copy()

    columns = [{"name": c, "id": c} for c in cols]
    data = table_df.to_dict("records")

    # Summary cards
    stats = build_summary(metric)
    if not stats:
        cards = html.Div("No numeric data for this metric.", className="text-muted")
    else:
        cards = dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Min", className="text-muted"), html.H5(fmt_value(metric, stats["min"]))])), width=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Median", className="text-muted"), html.H5(fmt_value(metric, stats["median"]))])), width=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Max", className="text-muted"), html.H5(fmt_value(metric, stats["max"]))])), width=4),
        ], className="g-2")

    return fig_map, fig_bar, columns, data, cards


if __name__ == "__main__":
    app.run_server(debug=True)
