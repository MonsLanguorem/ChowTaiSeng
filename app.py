import csv
import gzip
import json
import os
from pathlib import Path

import dash
from dash import html, dcc, dash_table, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
GEOJSON_GZ = DATA_DIR / "sa2_greater_sydney_2021.geojson.gz"
DATA_CSV = DATA_DIR / "dashboard_data.csv"


def load_geojson_gz(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def load_rows_csv(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            # Coerce numeric fields when possible
            rr = {}
            for k, v in r.items():
                if v is None:
                    rr[k] = None
                    continue
                vv = v.strip()
                if vv == "":
                    rr[k] = None
                    continue
                # Keep SA2_CODE21 as string for geojson matching
                if k == "SA2_CODE21":
                    rr[k] = vv
                    continue
                # Try int/float
                try:
                    if "." in vv:
                        rr[k] = float(vv)
                    else:
                        rr[k] = int(vv)
                except Exception:
                    rr[k] = vv
            rows.append(rr)
        return rows


GEOJSON = load_geojson_gz(GEOJSON_GZ)
ROWS = load_rows_csv(DATA_CSV)

# Identify metric columns (numeric) excluding IDs
ID_COLS = {"Location_ID", "Anchor", "Location_Type", "SA2_NAME21", "SA2_CODE21"}
METRIC_COLS = []
for k in ROWS[0].keys():
    if k in ID_COLS:
        continue
    # Consider metric if at least one row has a number
    if any(isinstance(r.get(k), (int, float)) for r in ROWS):
        METRIC_COLS.append(k)

DEFAULT_METRIC = "Net_Income_pa" if "Net_Income_pa" in METRIC_COLS else (METRIC_COLS[0] if METRIC_COLS else None)


def build_choropleth(metric: str) -> go.Figure:
    loc_codes = [r["SA2_CODE21"] for r in ROWS if r.get("SA2_CODE21")]
    z_vals = [r.get(metric) for r in ROWS if r.get("SA2_CODE21")]
    hover = [
        f"{r.get('SA2_NAME21', 'Unknown')}<br>{metric}: {r.get(metric):,}"
        if isinstance(r.get(metric), (int, float))
        else f"{r.get('SA2_NAME21', 'Unknown')}<br>{metric}: N/A"
        for r in ROWS
        if r.get("SA2_CODE21")
    ]

    fig = go.Figure(
        go.Choroplethmapbox(
            geojson=GEOJSON,
            locations=loc_codes,
            featureidkey="properties.SA2_CODE21",
            z=z_vals,
            text=hover,
            hoverinfo="text",
            marker_opacity=0.55,
            marker_line_width=1,
            colorbar_title=metric,
        )
    )

    # Center on Greater Sydney roughly
    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=9,
        mapbox_center={"lat": -33.8688, "lon": 151.2093},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        height=650,
    )
    return fig


def metric_summary(rows: list[dict], metric: str) -> dict:
    vals = [r.get(metric) for r in rows if isinstance(r.get(metric), (int, float))]
    if not vals:
        return {"n": 0, "min": None, "max": None, "avg": None}
    return {
        "n": len(vals),
        "min": min(vals),
        "max": max(vals),
        "avg": sum(vals) / len(vals),
    }


app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
server = app.server

app.layout = dbc.Container(
    fluid=True,
    children=[
        dbc.Row(
            dbc.Col(
                html.H2("CTS — Greater Sydney Location Dashboard (11 candidate areas)", className="mt-3 mb-2")
            )
        ),
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Metric"),
                        dcc.Dropdown(
                            id="metric-dd",
                            options=[{"label": m, "value": m} for m in METRIC_COLS],
                            value=DEFAULT_METRIC,
                            clearable=False,
                        ),
                        html.Div(id="metric-cards", className="mt-3"),
                    ],
                    md=3,
                ),
                dbc.Col(
                    dcc.Graph(id="map", figure=build_choropleth(DEFAULT_METRIC) if DEFAULT_METRIC else go.Figure()),
                    md=9,
                ),
            ],
            className="mb-3",
        ),
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H4("All 11 locations — table"),
                        dash_table.DataTable(
                            id="tbl",
                            columns=[{"name": c, "id": c} for c in ROWS[0].keys()],
                            data=ROWS,
                            page_size=15,
                            sort_action="native",
                            filter_action="native",
                            style_table={"overflowX": "auto"},
                            style_cell={"fontFamily": "Arial", "fontSize": 12, "padding": "6px"},
                            style_header={"fontWeight": "bold"},
                        ),
                    ],
                    md=12,
                )
            ],
            className="mb-5",
        ),
        dbc.Row(
            dbc.Col(
                html.Div(
                    [
                        html.H4("Comparison chart"),
                        dcc.Graph(id="bar"),
                    ]
                )
            )
        ),
        dbc.Row(
            dbc.Col(
                html.Div(
                    "Data sources: see your Excel model (Dashboard_Data sheet) for all assumptions and links.",
                    className="text-muted mt-3 mb-4",
                )
            )
        ),
    ],
)


@app.callback(
    Output("map", "figure"),
    Output("bar", "figure"),
    Output("metric-cards", "children"),
    Input("metric-dd", "value"),
)
def update(metric: str):
    fig_map = build_choropleth(metric)

    # Bar chart by location_id
    xs = [r["Location_ID"] for r in ROWS]
    ys = [r.get(metric) for r in ROWS]
    fig_bar = go.Figure(go.Bar(x=xs, y=ys))
    fig_bar.update_layout(margin={"r": 10, "t": 40, "l": 10, "b": 50}, height=350, title=f"{metric} by Location_ID")

    s = metric_summary(ROWS, metric)
    cards = dbc.Row(
        [
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Count"), html.H4(f"{s['n']}")])), md=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Average"), html.H4(f"{s['avg']:,.0f}" if s['avg'] is not None else "N/A")])), md=4),
            dbc.Col(dbc.Card(dbc.CardBody([html.Div("Min / Max"), html.H4(f"{s['min']:,.0f} / {s['max']:,.0f}" if s['min'] is not None else "N/A")])), md=4),
        ],
        className="g-2",
    )

    return fig_map, fig_bar, cards


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", 8050)), debug=False)
