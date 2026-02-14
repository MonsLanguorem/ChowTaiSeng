import os
import json
import gzip
from pathlib import Path

import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, dash_table
import dash_bootstrap_components as dbc


# ---------------------------
# Paths / configuration
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

EXCEL_PATH = Path(os.getenv("CTS_EXCEL_PATH", str(DATA_DIR / "CTS_Sydney_SingleStore_PnL_Model_v9_working.xlsx")))
EXCEL_SHEET = os.getenv("CTS_EXCEL_SHEET", "Dashboard_Data")

GEOJSON_PATH = Path(os.getenv("CTS_GEOJSON_PATH", str(DATA_DIR / "sa2_greater_sydney_2021.geojson.gz")))

SYDNEY_CENTER = {"lat": -33.8688, "lon": 151.2093}
DEFAULT_ZOOM = 9.2


def load_geojson(path: Path) -> dict:
    """
    Loads a GeoJSON file, supporting .geojson and .geojson.gz.
    This avoids Git LFS issues on Render by allowing us to store a gzip in the repo.
    """
    if not path.exists():
        raise FileNotFoundError(f"GeoJSON not found: {path}")

    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_dashboard_table(excel_path: Path, sheet_name: str) -> pd.DataFrame:
    """
    Reads the universal 11-location table from Excel.
    Expected sheet: Dashboard_Data
    """
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    # Normalize SA2 code to string (featureidkey expects string matching)
    if "SA2_CODE21" in df.columns:
        df["SA2_CODE21"] = df["SA2_CODE21"].astype(str)

    return df


# Load data once at startup (Render-friendly)
GEOJSON = load_geojson(GEOJSON_PATH)

# Base SA2 index (all polygons)
sa2_rows = []
for feat in GEOJSON.get("features", []):
    props = feat.get("properties", {})
    sa2_rows.append({
        "SA2_CODE21": str(props.get("SA2_CODE21")),
        "SA2_NAME21": props.get("SA2_NAME21"),
    })
SA2_INDEX = pd.DataFrame(sa2_rows).dropna(subset=["SA2_CODE21"])

LOC_DF = load_dashboard_table(EXCEL_PATH, EXCEL_SHEET)

# Merge to get a map table that includes *all* SA2 polygons (metrics are NaN unless it's one of 11 locations)
MAP_DF = SA2_INDEX.merge(
    LOC_DF,
    on=["SA2_CODE21", "SA2_NAME21"],
    how="left"
)

# Metric dictionary (label -> column)
METRICS = {
    "Revenue (AUD p.a.)": "Revenue_pa",
    "Gross Profit (AUD p.a.)": "Gross_Profit_pa",
    "Total OPEX (AUD p.a.)": "Total_OPEX_pa",
    "EBIT (AUD p.a.)": "EBIT_pa",
    "Net Income (AUD p.a.)": "Net_Income_pa",
    "Initial Investment (AUD)": "Initial_Investment_AUD",
    "NPV (5y, AUD)": "NPV_5Y_AUD",
    "Sales Index (unitless)": "Sales_Index",
    "Rent (AUD p.a.)": "Rent_Total_AUD_pa",
    "Income Proxy HH Weekly (AUD)": "Income_Proxy_HH_Weekly",
    "Footfall Proxy (unitless)": "Footfall_Proxy",
}

DEFAULT_METRIC_COL = "Net_Income_pa"


def fmt_number(x):
    if pd.isna(x):
        return ""
    try:
        return f"{float(x):,.0f}"
    except Exception:
        return str(x)


# ---------------------------
# Dash app
# ---------------------------
app = Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
server = app.server

app.title = "CTS – Greater Sydney Location Dashboard"


def make_map(metric_col: str):
    # Use a copy so we can construct a clean hover string for the 11 locations only
    df = MAP_DF.copy()

    # For hover: show SA2 name and (if location exists) show the location_id/anchor
    df["__is_location"] = df["Location_ID"].notna()

    # Choropleth
    fig = px.choropleth_mapbox(
        df,
        geojson=GEOJSON,
        locations="SA2_CODE21",
        featureidkey="properties.SA2_CODE21",
        color=metric_col,
        hover_name="SA2_NAME21",
        hover_data={
            metric_col: True,
            "Location_ID": True,
            "Anchor": True,
            "Type": True,
            "Store_Size_sqm": True,
        },
        mapbox_style="carto-positron",
        center=SYDNEY_CENTER,
        zoom=DEFAULT_ZOOM,
        opacity=0.45,
        color_continuous_scale="Viridis",
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    # Format hover numbers
    fig.update_traces(
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            "Value: %{z:,.0f}<br>"
            "Location_ID: %{customdata[0]}<br>"
            "Anchor: %{customdata[1]}<br>"
            "Type: %{customdata[2]}<br>"
            "Store size: %{customdata[3]} sqm<br>"
            "<extra></extra>"
        ),
        customdata=df[["Location_ID", "Anchor", "Type", "Store_Size_sqm"]].values
    )

    return fig


def make_ranking(metric_col: str):
    df = LOC_DF.copy()
    df = df.sort_values(metric_col, ascending=False, na_position="last")

    fig = px.bar(
        df,
        x="Location_ID",
        y=metric_col,
        hover_data=["Area", "Anchor", "Type"],
        title="11-location ranking",
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=45, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title=None,
    )
    return fig


def make_stats(metric_col: str):
    s = LOC_DF[metric_col]
    s = pd.to_numeric(s, errors="coerce")

    valid = s.dropna()
    if valid.empty:
        return {"min": "", "median": "", "max": ""}

    return {
        "min": fmt_number(valid.min()),
        "median": fmt_number(valid.median()),
        "max": fmt_number(valid.max()),
    }


TABLE_COLS = [
    "Location_ID", "Area", "Anchor", "Type", "Store_Size_sqm",
    "Revenue_pa", "Gross_Profit_pa", "Total_OPEX_pa", "EBIT_pa", "Net_Income_pa",
    "Initial_Investment_AUD", "NPV_5Y_AUD"
]


def table_columns():
    cols = []
    for c in TABLE_COLS:
        cols.append({"name": c, "id": c, "type": "numeric" if c.endswith(("_pa", "_AUD")) or c in ["Store_Size_sqm"] else "text"})
    return cols


def table_data():
    df = LOC_DF.copy()
    # Keep only defined columns if they exist
    use = [c for c in TABLE_COLS if c in df.columns]
    df = df[use]
    return df.to_dict("records")


app.layout = dbc.Container(
    fluid=True,
    children=[
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H2("CTS – Greater Sydney Location Dashboard", className="mt-3"),
                        html.Div(
                            "Select a metric to paint SA2 polygons. Only SA2s with one of the 11 candidate locations are colored; others remain neutral.",
                            className="text-secondary mb-2",
                        ),
                    ],
                    width=12,
                )
            ]
        ),

        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Label("Metric"),
                                    dcc.Dropdown(
                                        id="metric",
                                        options=[{"label": k, "value": v} for k, v in METRICS.items()],
                                        value=DEFAULT_METRIC_COL,
                                        clearable=False,
                                    ),
                                    html.Div(id="stats", className="mt-3"),
                                ]
                            ),
                            className="mb-3",
                        ),
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("All 11 locations (table)", className="mb-2"),
                                    dash_table.DataTable(
                                        id="table",
                                        columns=table_columns(),
                                        data=table_data(),
                                        sort_action="native",
                                        filter_action="native",
                                        page_action="native",
                                        page_size=11,
                                        style_table={"overflowX": "auto"},
                                        style_cell={
                                            "fontFamily": "Arial",
                                            "fontSize": 12,
                                            "padding": "8px",
                                            "backgroundColor": "#111111",
                                            "color": "#EDEDED",
                                            "border": "1px solid #2A2A2A",
                                        },
                                        style_header={
                                            "backgroundColor": "#1E1E1E",
                                            "color": "#FFFFFF",
                                            "fontWeight": "bold",
                                            "border": "1px solid #2A2A2A",
                                        },
                                    ),
                                ]
                            ),
                            className="mb-3",
                        ),
                    ],
                    md=4,
                ),

                dbc.Col(
                    [
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    dcc.Graph(id="map", config={"displayModeBar": False}),
                                ]
                            ),
                            className="mb-3",
                        ),
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    dcc.Graph(id="ranking", config={"displayModeBar": False}),
                                ]
                            ),
                            className="mb-3",
                        ),
                    ],
                    md=8,
                ),
            ]
        ),

        dbc.Row(
            [
                dbc.Col(
                    html.Div(
                        [
                            html.Small(
                                [
                                    "Data source: Excel sheet ",
                                    html.Code(EXCEL_SHEET),
                                    " in ",
                                    html.Code(EXCEL_PATH.name),
                                    ". Geo polygons: SA2 2021 Greater Sydney.",
                                ],
                                className="text-secondary",
                            )
                        ],
                        className="mb-4",
                    ),
                    width=12,
                )
            ]
        ),
    ],
)


@app.callback(
    Output("map", "figure"),
    Output("ranking", "figure"),
    Output("stats", "children"),
    Input("metric", "value"),
)
def update(metric_col):
    metric_col = metric_col or DEFAULT_METRIC_COL

    fig_map = make_map(metric_col)
    fig_rank = make_ranking(metric_col)

    st = make_stats(metric_col)
    stats_block = dbc.Row(
        [
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Min", className="text-secondary"), html.H4(st["min"])])), md=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Median", className="text-secondary"), html.H4(st["median"])])), md=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Max", className="text-secondary"), html.H4(st["max"])])), md=4),
        ],
        className="g-2"
    )

    return fig_map, fig_rank, stats_block


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=False)
