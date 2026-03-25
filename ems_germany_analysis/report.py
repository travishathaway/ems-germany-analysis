"""
Generate a hospital accessibility report for Germany.

Produces a directory containing index.html with interactive charts (Plotly),
an interactive map (MapLibre GL JS), and GeoJSON data files loaded dynamically.
"""
import json
import pickle
import sys
from pathlib import Path

import click
import pandas as pd
import platformdirs
import plotly.graph_objects as go
import psycopg
from plotly.subplots import make_subplots

from .constants import APP_NAME

# ---------------------------------------------------------------------------
# SQL queries
# ---------------------------------------------------------------------------

# Overall summary: one row per hospital level
SQL_SUMMARY = """
SELECT
    CAST(h.notfall AS float)::int         AS hospital_level,
    COUNT(DISTINCT r.hospital_id)          AS hospital_count,
    COUNT(DISTINCT r.gitter_id)            AS census_cells_covered,
    ROUND(AVG(r.total_cost_seconds)::numeric / 60, 1)    AS avg_travel_min,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.total_cost_seconds))::numeric / 60,
        1
    )                                                     AS median_travel_min,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE r.total_cost_seconds <= 900)
        / NULLIF(COUNT(*), 0),
        1
    )                                                     AS pct_routes_15min,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE r.total_cost_seconds <= 1800)
        / NULLIF(COUNT(*), 0),
        1
    )                                                     AS pct_routes_30min
FROM ems_germany_analysis.{cost_table} r
JOIN ems_germany_analysis.notfall_krankenhauser_geocoded h ON r.hospital_id = h.id
WHERE r.total_cost_seconds IS NOT NULL
GROUP BY CAST(h.notfall AS float)::int
ORDER BY 1;
"""

# Per census cell: minimum travel time to nearest hospital of each level
SQL_PER_CELL = """
WITH min_times AS (
    SELECT
        r.gitter_id,
        MIN(CASE WHEN CAST(h.notfall AS float)::int = 1 THEN r.total_cost_seconds END) AS min_secs_l1,
        MIN(CASE WHEN CAST(h.notfall AS float)::int = 2 THEN r.total_cost_seconds END) AS min_secs_l2,
        MIN(CASE WHEN CAST(h.notfall AS float)::int = 3 THEN r.total_cost_seconds END) AS min_secs_l3,
        MIN(r.total_cost_seconds)                                                        AS min_secs_any
    FROM ems_germany_analysis.{cost_table} r
    JOIN ems_germany_analysis.notfall_krankenhauser_geocoded h ON r.hospital_id = h.id
    WHERE r.total_cost_seconds IS NOT NULL
    GROUP BY r.gitter_id
)
SELECT
    m.gitter_id,
    m.min_secs_l1,
    m.min_secs_l2,
    m.min_secs_l3,
    m.min_secs_any,
    c.insgesamt_bevoelkerung AS population,
    c.a65undaelter           AS pop_65plus,
    c.unter18                AS pop_under18,
    c.a18bis29               AS pop_18to29,
    c.a30bis49               AS pop_30to49,
    c.a50bis64               AS pop_50to64
FROM min_times m
JOIN zensus.alter_in_5_altersklassen_{resolution} c ON c.gitter_id_{resolution} = m.gitter_id
WHERE c.insgesamt_bevoelkerung > 0;
"""

# Census cell centroids for the map (WGS84)
SQL_MAP_CELLS = """
WITH min_times AS (
    SELECT
        r.gitter_id,
        MIN(CASE WHEN CAST(h.notfall AS float)::int = 1 THEN r.total_cost_seconds END) AS min_secs_l1,
        MIN(CASE WHEN CAST(h.notfall AS float)::int = 2 THEN r.total_cost_seconds END) AS min_secs_l2,
        MIN(CASE WHEN CAST(h.notfall AS float)::int = 3 THEN r.total_cost_seconds END) AS min_secs_l3,
        MIN(r.total_cost_seconds)                                                        AS min_secs_any
    FROM ems_germany_analysis.{cost_table} r
    JOIN ems_germany_analysis.notfall_krankenhauser_geocoded h ON r.hospital_id = h.id
    WHERE r.total_cost_seconds IS NOT NULL
    GROUP BY r.gitter_id
)
SELECT
    ST_X(ST_Transform(ST_Centroid(c.geom), 4326))     AS lon,
    ST_Y(ST_Transform(ST_Centroid(c.geom), 4326))     AS lat,
    ROUND(m.min_secs_any::numeric / 60, 1)            AS min_min_any,
    ROUND(m.min_secs_l1::numeric  / 60, 1)            AS min_min_l1,
    ROUND(m.min_secs_l2::numeric  / 60, 1)            AS min_min_l2,
    ROUND(m.min_secs_l3::numeric  / 60, 1)            AS min_min_l3,
    c.insgesamt_bevoelkerung                           AS population,
    c.a65undaelter                                     AS pop_65plus,
    c.unter18                                          AS pop_under18,
    c.a18bis29                                         AS pop_18to29,
    c.a30bis49                                         AS pop_30to49,
    c.a50bis64                                         AS pop_50to64
FROM min_times m
JOIN zensus.alter_in_5_altersklassen_{resolution} c ON c.gitter_id_{resolution} = m.gitter_id
WHERE c.insgesamt_bevoelkerung > 0;
"""

# Hospital locations for the map
SQL_HOSPITALS_MAP = """
SELECT
    id,
    name,
    CAST(notfall AS float)::int                    AS level,
    ST_X(ST_Transform(geom, 4326))                 AS lon,
    ST_Y(ST_Transform(geom, 4326))                 AS lat
FROM ems_germany_analysis.notfall_krankenhauser_geocoded
ORDER BY id;
"""

# Federal state breakdown — uses spatial join to place_polygon_nested
# Filtered to known German Bundesland names to avoid matching sub-regions
GERMAN_STATES = [
    "Rhineland-Palatinate",
    "Saarland",
    "North Rhine-Westphalia",
    "Bremen",
    "Lower Saxony",
    "Brandenburg",
    "Berlin",
    "Saxony",
    "Thuringia",
    "Hesse",
    "Bavaria",
    "Baden-Württemberg",
    "Schleswig-Holstein",
    "Hamburg",
    "Saxony-Anhalt",
    "Mecklenburg-Vorpommern",
]

SQL_STATES = """
WITH state_geoms AS (
    SELECT name, ST_Union(geom) AS geom
    FROM osm_germany.place_polygon_nested
    WHERE name = ANY(%(state_names)s)
    GROUP BY name
),
min_times AS (
    SELECT
        r.gitter_id,
        CAST(h.notfall AS float)::int AS hospital_level,
        MIN(r.total_cost_seconds)     AS min_secs
    FROM ems_germany_analysis.{cost_table} r
    JOIN ems_germany_analysis.notfall_krankenhauser_geocoded h ON r.hospital_id = h.id
    WHERE r.total_cost_seconds IS NOT NULL
    GROUP BY r.gitter_id, CAST(h.notfall AS float)::int
),
cell_state AS (
    SELECT
        t.*,
        c.insgesamt_bevoelkerung AS population,
        c.a65undaelter           AS pop_65plus,
        c.unter18                AS pop_under18,
        c.a18bis29               AS pop_18to29,
        c.a30bis49               AS pop_30to49,
        c.a50bis64               AS pop_50to64,
        s.name                   AS state
    FROM min_times t
    JOIN zensus.alter_in_5_altersklassen_{resolution} c ON c.gitter_id_{resolution} = t.gitter_id
    JOIN state_geoms s ON ST_Within(c.geom, s.geom)
    WHERE c.insgesamt_bevoelkerung > 0
)
SELECT
    state,
    hospital_level,
    COUNT(DISTINCT gitter_id)                                   AS census_cells,
    SUM(population)                                             AS total_population,
    SUM(pop_65plus)                                             AS total_pop_65_plus,
    SUM(pop_under18)                                            AS total_pop_under18,
    SUM(pop_18to29)                                             AS total_pop_18to29,
    SUM(pop_30to49)                                             AS total_pop_30to49,
    SUM(pop_50to64)                                             AS total_pop_50to64,
    ROUND(AVG(min_secs)::numeric / 60, 1)                       AS avg_travel_min,
    ROUND(
        (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY min_secs))::numeric / 60,
        1
    )                                                           AS median_travel_min,
    ROUND(
        100.0 * SUM(CASE WHEN min_secs <= 900  THEN population ELSE 0 END)
        / NULLIF(SUM(population), 0), 1
    )                                                           AS pct_within_15min,
    ROUND(
        100.0 * SUM(CASE WHEN min_secs <= 1800 THEN population ELSE 0 END)
        / NULLIF(SUM(population), 0), 1
    )                                                           AS pct_within_30min,
    ROUND(
        100.0 * SUM(CASE WHEN min_secs <= 3600 THEN population ELSE 0 END)
        / NULLIF(SUM(population), 0), 1
    )                                                           AS pct_within_60min
FROM cell_state
GROUP BY state, hospital_level
ORDER BY state, hospital_level;
"""


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_df(conn: psycopg.Connection, sql: str, params=None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def _cache_dir() -> Path:
    d = Path(platformdirs.user_cache_dir(APP_NAME))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_cached(
    conn: psycopg.Connection,
    sql: str,
    cache_path: Path,
    use_cache: bool,
    params=None,
) -> pd.DataFrame:
    """Load DataFrame from pickle cache if available; otherwise fetch from DB and cache."""
    if use_cache and cache_path.exists():
        click.echo(f"  → loaded from cache: {cache_path.name}")
        with cache_path.open("rb") as fh:
            return pickle.load(fh)  # noqa: S301
    df = fetch_df(conn, sql, params)
    with cache_path.open("wb") as fh:
        pickle.dump(df, fh)
    return df


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

LEVEL_COLORS = {1: "#4dac26", 2: "#f1b614", 3: "#d7191c"}
LEVEL_NAMES  = {1: "Level 1 (Basic)", 2: "Level 2 (Advanced)", 3: "Level 3 (Comprehensive)"}


def chart_coverage_bars(df_cell: pd.DataFrame) -> str:
    """Stacked/grouped bar: % population within 15 / 30 / 60 min by hospital level."""
    thresholds = [(15, 900), (30, 1800), (60, 3600)]
    level_cols = {1: "min_secs_l1", 2: "min_secs_l2", 3: "min_secs_l3"}

    rows = []
    for level, col in level_cols.items():
        sub = df_cell.dropna(subset=[col])
        total_pop = sub["population"].sum()
        if total_pop == 0:
            continue
        for label, secs in thresholds:
            pct = 100 * sub.loc[sub[col] <= secs, "population"].sum() / total_pop
            rows.append({"level": LEVEL_NAMES[level], "threshold": f"≤ {label} min", "pct": pct})

    df = pd.DataFrame(rows)
    fig = go.Figure()
    threshold_colors = {"≤ 15 min": "#2c7bb6", "≤ 30 min": "#74add1", "≤ 60 min": "#abd9e9"}
    for thr, color in threshold_colors.items():
        sub = df[df["threshold"] == thr]
        fig.add_trace(go.Bar(
            name=thr, x=sub["level"], y=sub["pct"].round(1),
            marker_color=color,
            text=sub["pct"].round(1).astype(str) + "%",
            textposition="outside",
        ))

    fig.update_layout(
        title="Population Coverage by Hospital Level and Travel Time Threshold",
        xaxis_title="Hospital Level",
        yaxis_title="Population covered (%)",
        yaxis_range=[0, 110],
        barmode="group",
        legend_title="Travel time",
        template="plotly_white",
        font=dict(family="Arial, sans-serif"),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def chart_cdf(df_cell: pd.DataFrame) -> str:
    """CDF: cumulative % of population vs. travel time (minutes)."""
    level_cols = {1: "min_secs_l1", 2: "min_secs_l2", 3: "min_secs_l3"}
    fig = go.Figure()

    for level, col in level_cols.items():
        sub = df_cell.dropna(subset=[col]).copy()
        sub["min_min"] = sub[col] / 60
        sub = sub.sort_values("min_min")
        sub["cum_pop"] = sub["population"].cumsum()
        total_pop = sub["population"].sum()
        sub["cum_pct"] = 100 * sub["cum_pop"] / total_pop

        # Downsample for a smooth curve without overloading the browser
        if len(sub) > 5000:
            sub = sub.iloc[:: max(1, len(sub) // 5000)]

        fig.add_trace(go.Scatter(
            x=sub["min_min"], y=sub["cum_pct"],
            mode="lines",
            name=LEVEL_NAMES[level],
            line=dict(color=LEVEL_COLORS[level], width=2),
        ))

    fig.add_vline(x=15, line_dash="dash", line_color="gray", annotation_text="15 min")
    fig.add_vline(x=30, line_dash="dash", line_color="gray", annotation_text="30 min")

    fig.update_layout(
        title="Cumulative Population Accessibility (CDF)",
        xaxis_title="Travel time to nearest hospital (minutes)",
        yaxis_title="Cumulative population (%)",
        xaxis_range=[0, 90],
        legend_title="Hospital level",
        template="plotly_white",
        font=dict(family="Arial, sans-serif"),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def chart_travel_histogram(df_cell: pd.DataFrame) -> str:
    """Population-weighted histogram of travel times by hospital level."""
    level_cols = {1: "min_secs_l1", 2: "min_secs_l2", 3: "min_secs_l3"}
    bins = list(range(0, 91, 5))  # 5-minute bins up to 90 min
    fig = go.Figure()

    for level, col in level_cols.items():
        sub = df_cell.dropna(subset=[col]).copy()
        sub["min_min"] = sub[col] / 60

        sub["bin"] = pd.cut(sub["min_min"], bins=bins, right=False)
        pop_per_bin = sub.groupby("bin", observed=False)["population"].sum()
        total = pop_per_bin.sum()

        fig.add_trace(go.Bar(
            x=[str(b) for b in pop_per_bin.index],
            y=(100 * pop_per_bin / total).round(2),
            name=LEVEL_NAMES[level],
            marker_color=LEVEL_COLORS[level],
            opacity=0.7,
        ))

    fig.update_layout(
        title="Distribution of Travel Times (Population-Weighted)",
        xaxis_title="Travel time bin (minutes)",
        yaxis_title="Share of population (%)",
        barmode="group",
        legend_title="Hospital level",
        template="plotly_white",
        font=dict(family="Arial, sans-serif"),
        xaxis_tickangle=-45,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def chart_equity(df_cell: pd.DataFrame) -> str:
    """Compare accessibility for elderly (65+) vs. general population."""
    level_col = "min_secs_l3"  # Focus on Level 3 (highest care)
    thresholds = [15, 30, 60]

    sub = df_cell.dropna(subset=[level_col]).copy()
    sub["min_min_l3"] = sub[level_col] / 60

    rows = []
    for thr in thresholds:
        total_pop   = sub["population"].sum()
        total_65p   = sub["pop_65plus"].sum()
        total_u18   = sub["pop_under18"].sum()

        within = sub[sub["min_min_l3"] <= thr]
        rows.append({
            "threshold": f"≤ {thr} min",
            "All ages":  100 * within["population"].sum()  / total_pop  if total_pop  else 0,
            "Age 65+":   100 * within["pop_65plus"].sum()  / total_65p  if total_65p  else 0,
            "Under 18":  100 * within["pop_under18"].sum() / total_u18  if total_u18  else 0,
        })

    df = pd.DataFrame(rows)
    fig = go.Figure()
    group_colors = {"All ages": "#2c7bb6", "Age 65+": "#d7191c", "Under 18": "#4dac26"}

    for group, color in group_colors.items():
        fig.add_trace(go.Bar(
            name=group, x=df["threshold"], y=df[group].round(1),
            marker_color=color,
            text=df[group].round(1).astype(str) + "%",
            textposition="outside",
        ))

    fig.update_layout(
        title="Equity Analysis: Access to Level 3 Hospitals by Age Group",
        xaxis_title="Travel time threshold",
        yaxis_title="Population covered (%)",
        yaxis_range=[0, 110],
        barmode="group",
        legend_title="Age group",
        template="plotly_white",
        font=dict(family="Arial, sans-serif"),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def chart_states(df_states: pd.DataFrame) -> str:
    """Heatmap: median travel time to Level 3 hospital by federal state."""
    df3 = df_states[df_states["hospital_level"] == 3].copy()
    if df3.empty:
        return "<p><em>State-level data not available.</em></p>"

    df3 = df3.sort_values("median_travel_min")
    fig = make_subplots(rows=1, cols=2, subplot_titles=(
        "Median Travel Time to Nearest Level 3 Hospital (min)",
        "% Population within 30 min of Level 3 Hospital",
    ))

    fig.add_trace(go.Bar(
        x=df3["median_travel_min"], y=df3["state"],
        orientation="h", name="Median (min)",
        marker_color="#d7191c",
    ), row=1, col=1)

    df3_sorted30 = df3.sort_values("pct_within_30min")
    fig.add_trace(go.Bar(
        x=df3_sorted30["pct_within_30min"], y=df3_sorted30["state"],
        orientation="h", name="% within 30 min",
        marker_color="#2c7bb6",
    ), row=1, col=2)

    fig.update_layout(
        height=550,
        showlegend=False,
        template="plotly_white",
        font=dict(family="Arial, sans-serif"),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def render_summary_table(df_summary: pd.DataFrame) -> str:
    rows_html = ""
    for _, row in df_summary.iterrows():
        level = int(row["hospital_level"])
        rows_html += f"""
        <tr>
          <td><span class="level-badge level-{level}">Level {level}</span></td>
          <td>{int(row['hospital_count'])}</td>
          <td>{int(row['census_cells_covered']):,}</td>
          <td>{float(row['avg_travel_min']):.1f}</td>
          <td>{float(row['median_travel_min']):.1f}</td>
          <td>{float(row['pct_routes_15min']):.1f}%</td>
          <td>{float(row['pct_routes_30min']):.1f}%</td>
        </tr>"""
    return f"""
    <table class="summary-table">
      <thead>
        <tr>
          <th>Hospital Level</th>
          <th>Hospitals</th>
          <th>Census Cells Covered</th>
          <th>Avg Travel (min)</th>
          <th>Median Travel (min)</th>
          <th>Routes ≤ 15 min</th>
          <th>Routes ≤ 30 min</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>"""


# ---------------------------------------------------------------------------
# MapLibre map
# ---------------------------------------------------------------------------

def build_map_geojson(df_map: pd.DataFrame) -> dict:
    """Convert map DataFrame to a GeoJSON FeatureCollection."""
    features = []
    for _, row in df_map.iterrows():
        props = {
            "min_any":     None if pd.isna(row["min_min_any"]) else float(row["min_min_any"]),
            "min_l1":      None if pd.isna(row["min_min_l1"])  else float(row["min_min_l1"]),
            "min_l2":      None if pd.isna(row["min_min_l2"])  else float(row["min_min_l2"]),
            "min_l3":      None if pd.isna(row["min_min_l3"])  else float(row["min_min_l3"]),
            "pop":         int(row["population"]),
            "pop_65plus":  int(row["pop_65plus"])  if not pd.isna(row["pop_65plus"])  else 0,
            "pop_under18": int(row["pop_under18"]) if not pd.isna(row["pop_under18"]) else 0,
            "pop_18to29":  int(row["pop_18to29"])  if not pd.isna(row["pop_18to29"])  else 0,
            "pop_30to49":  int(row["pop_30to49"])  if not pd.isna(row["pop_30to49"])  else 0,
            "pop_50to64":  int(row["pop_50to64"])  if not pd.isna(row["pop_50to64"])  else 0,
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(row["lon"]), float(row["lat"])]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


def build_hospitals_geojson(df_hospitals: pd.DataFrame) -> dict:
    features = []
    for _, row in df_hospitals.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(row["lon"]), float(row["lat"])]},
            "properties": {
                "id":    int(row["id"]),
                "name":  row["name"],
                "level": int(row["level"]),
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def render_html(
    summary_table_html: str,
    chart_coverage: str,
    chart_cdf_html: str,
    chart_hist_html: str,
    chart_equity_html: str,
    chart_states_html: str,
    total_cells: int,
    data_note: str,
    resolution: str = "1km",
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Hospital Accessibility in Germany</title>
  <script src="https://cdn.plot.ly/plotly-3.0.1.min.js"></script>
  <script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
  <link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "Helvetica Neue", Arial, sans-serif;
      color: #333;
      background: #f7f7f7;
      line-height: 1.5;
    }}
    header {{
      background: #1a3a5c;
      color: #fff;
      padding: 28px 40px;
    }}
    header h1 {{ font-size: 1.8rem; font-weight: 600; }}
    header p  {{ margin-top: 6px; opacity: 0.8; font-size: 0.95rem; }}

    nav {{
      background: #fff;
      border-bottom: 1px solid #ddd;
      padding: 0 40px;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    nav ul {{ display: flex; gap: 0; list-style: none; }}
    nav ul li a {{
      display: block;
      padding: 14px 18px;
      text-decoration: none;
      color: #555;
      font-size: 0.88rem;
      font-weight: 500;
      border-bottom: 3px solid transparent;
      transition: color 0.15s, border-color 0.15s;
    }}
    nav ul li a:hover {{ color: #1a3a5c; border-color: #1a3a5c; }}

    main {{ max-width: 1200px; margin: 0 auto; padding: 40px 20px; }}

    section {{
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 1px 4px rgba(0,0,0,.08);
      padding: 32px;
      margin-bottom: 32px;
    }}
    h2 {{
      font-size: 1.25rem;
      font-weight: 600;
      color: #1a3a5c;
      margin-bottom: 6px;
    }}
    .section-desc {{
      color: #666;
      font-size: 0.9rem;
      margin-bottom: 20px;
    }}
    .data-note {{
      background: #fff8e1;
      border-left: 4px solid #f1b614;
      padding: 10px 14px;
      border-radius: 4px;
      font-size: 0.85rem;
      color: #7a6000;
      margin-bottom: 20px;
    }}

    /* Summary table */
    .summary-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    .summary-table th {{
      background: #1a3a5c;
      color: #fff;
      padding: 10px 14px;
      text-align: left;
      font-weight: 500;
    }}
    .summary-table td {{
      padding: 9px 14px;
      border-bottom: 1px solid #eee;
    }}
    .summary-table tr:hover td {{ background: #f5f8ff; }}
    .level-badge {{
      display: inline-block;
      padding: 2px 10px;
      border-radius: 12px;
      font-size: 0.82rem;
      font-weight: 600;
      color: #fff;
    }}
    .level-1 {{ background: #4dac26; }}
    .level-2 {{ background: #f1b614; color: #333; }}
    .level-3 {{ background: #d7191c; }}

    /* Map */
    #map-container {{
      position: relative;
      height: 560px;
      border-radius: 6px;
      overflow: hidden;
    }}
    #map {{ width: 100%; height: 100%; }}
    #map-controls {{
      position: absolute;
      top: 12px;
      left: 12px;
      background: rgba(255,255,255,0.95);
      padding: 12px 16px;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      z-index: 10;
      font-size: 0.85rem;
    }}
    #map-controls strong {{ display: block; margin-bottom: 8px; color: #1a3a5c; }}
    .map-btn {{
      display: block;
      width: 100%;
      margin-bottom: 5px;
      padding: 5px 10px;
      border: 1px solid #ccc;
      border-radius: 4px;
      background: #f5f5f5;
      cursor: pointer;
      font-size: 0.82rem;
      text-align: left;
      transition: background 0.15s;
    }}
    .map-btn.active {{ background: #1a3a5c; color: #fff; border-color: #1a3a5c; }}
    .map-btn:hover:not(.active) {{ background: #e8eef5; }}
    #map-legend {{
      position: absolute;
      bottom: 30px;
      right: 12px;
      background: rgba(255,255,255,0.95);
      padding: 10px 14px;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      z-index: 10;
      font-size: 0.82rem;
    }}
    #map-legend strong {{ display: block; margin-bottom: 6px; color: #1a3a5c; }}
    .legend-row {{ display: flex; align-items: center; gap: 8px; margin: 3px 0; }}
    .legend-dot {{
      width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
    }}
    .legend-grad {{
      width: 130px; height: 12px; border-radius: 3px;
      background: linear-gradient(to right, #1a9641, #a6d96a, #ffffbf, #fdae61, #d7191c);
    }}
    .legend-labels {{ display: flex; justify-content: space-between; font-size: 0.78rem; color: #666; }}

    .chart-wrap {{ margin-top: 8px; }}
    .chart-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }}
    @media (max-width: 800px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>

<header>
  <h1>Hospital Accessibility Analysis — Germany</h1>
  <p>Travel time from census population grid ({resolution}) to emergency hospitals by care level</p>
</header>

<nav>
  <ul>
    <li><a href="#summary">Summary</a></li>
    <li><a href="#coverage">Coverage</a></li>
    <li><a href="#distribution">Distribution</a></li>
    <li><a href="#map">Map</a></li>
    <li><a href="#equity">Equity</a></li>
    <li><a href="#states">By State</a></li>
  </ul>
</nav>

<main>

  <!-- ── 1. Summary ── -->
  <section id="summary">
    <h2>Summary Statistics</h2>
    <p class="section-desc">
      Each census grid cell ({resolution} × {resolution}) is matched to all hospitals within 15 km.
      Travel times are driving durations in seconds computed via road network routing.
      Hospital levels: <strong>Level 1</strong> (basic emergency care),
      <strong>Level 2</strong> (advanced), <strong>Level 3</strong> (comprehensive / trauma centre).
    </p>
    <div class="data-note">
      ⚠ {data_note}
    </div>
    {summary_table_html}
  </section>

  <!-- ── 2. Coverage ── -->
  <section id="coverage">
    <h2>Population Coverage by Travel Time Threshold</h2>
    <p class="section-desc">
      Share of the covered population that can reach the nearest hospital of each level
      within 15, 30, or 60 minutes of driving.
    </p>
    <div class="chart-wrap">{chart_coverage}</div>
  </section>

  <!-- ── 3. Distribution ── -->
  <section id="distribution">
    <h2>Travel Time Distributions</h2>
    <p class="section-desc">
      Left: cumulative distribution function (CDF) showing what fraction of the population
      is within a given drive time. Right: population-weighted histogram in 5-minute bins.
    </p>
    <div class="chart-grid">
      <div class="chart-wrap">{chart_cdf_html}</div>
      <div class="chart-wrap">{chart_hist_html}</div>
    </div>
  </section>

  <!-- ── 4. Map ── -->
  <section id="map">
    <h2>Interactive Accessibility Map</h2>
    <p class="section-desc">
      Each dot represents one census grid cell coloured by travel time (minutes) to the
      nearest hospital of the selected level. Toggle layers using the controls.
      ({total_cells:,} census cells with routing data shown.)
    </p>
    <div id="map-container">
      <div id="map"></div>
      <div id="map-controls">
        <strong>Show travel time to:</strong>
        <button class="map-btn active" onclick="setLayer('any')">Any hospital</button>
        <button class="map-btn" onclick="setLayer('l1')">Level 1 hospitals</button>
        <button class="map-btn" onclick="setLayer('l2')">Level 2 hospitals</button>
        <button class="map-btn" onclick="setLayer('l3')">Level 3 hospitals</button>
        <hr style="margin:8px 0;border-color:#ddd">
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
          <input type="checkbox" id="toggle-hospitals" checked onchange="toggleHospitals(this.checked)">
          Show hospitals
        </label>
      </div>
      <div id="map-legend">
        <strong>Travel time (min)</strong>
        <div class="legend-grad"></div>
        <div class="legend-labels"><span>0</span><span>15</span><span>30</span><span>45</span><span>60+</span></div>
        <br>
        <strong>Hospitals</strong>
        <div class="legend-row">
          <svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#6b9ec7"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">1</text></svg>
          Level 1
        </div>
        <div class="legend-row">
          <svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#9b7dbf"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">2</text></svg>
          Level 2
        </div>
        <div class="legend-row">
          <svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#c4744d"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">3</text></svg>
          Level 3
        </div>
      </div>
    </div>
  </section>

  <!-- ── 5. Equity ── -->
  <section id="equity">
    <h2>Equity Analysis — Age Group Comparison</h2>
    <p class="section-desc">
      Comparing coverage rates for the overall population, adults aged 65 and over,
      and children under 18, for access to the nearest Level 3 (comprehensive) hospital.
    </p>
    <div class="chart-wrap">{chart_equity_html}</div>
  </section>

  <!-- ── 6. By State ── -->
  <section id="states">
    <h2>Regional Breakdown by Federal State</h2>
    <p class="section-desc">
      Median travel time and 30-minute coverage rate to the nearest Level 3 hospital,
      disaggregated by German <em>Bundesland</em>.
    </p>
    <div class="chart-wrap">{chart_states_html}</div>
  </section>

</main>

<script>
// ── MapLibre setup ──
// GeoJSON data loaded from external files (cells.geojson, hospitals.geojson)

const TRAVEL_COLOR = [
  "interpolate", ["linear"],
  ["coalesce", ["get", "min_any"], 999],
    0,  "#1a9641",
   15,  "#a6d96a",
   30,  "#ffffbf",
   45,  "#fdae61",
   60,  "#d7191c",
  999,  "#aaaaaa"
];

function makeTravelColor(prop) {{
  return [
    "interpolate", ["linear"],
    ["coalesce", ["get", prop], 999],
      0,  "#1a9641",
     15,  "#a6d96a",
     30,  "#ffffbf",
     45,  "#fdae61",
     60,  "#d7191c",
    999,  "#aaaaaa"
  ];
}}

const HOSPITAL_COLORS = {{"1": "#6b9ec7", "2": "#9b7dbf", "3": "#c4744d"}};

const map = new maplibregl.Map({{
  container: "map",
  style: {{
    version: 8,
    sources: {{
      "carto-base": {{
        type: "raster",
        tiles: ["https://a.basemaps.cartocdn.com/light_nolabels/{{z}}/{{x}}/{{y}}.png",
                "https://b.basemaps.cartocdn.com/light_nolabels/{{z}}/{{x}}/{{y}}.png",
                "https://c.basemaps.cartocdn.com/light_nolabels/{{z}}/{{x}}/{{y}}.png"],
        tileSize: 256,
        attribution: "© <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors © <a href='https://carto.com/attributions'>CARTO</a>",
      }},
      "carto-labels": {{
        type: "raster",
        tiles: ["https://a.basemaps.cartocdn.com/light_only_labels/{{z}}/{{x}}/{{y}}.png",
                "https://b.basemaps.cartocdn.com/light_only_labels/{{z}}/{{x}}/{{y}}.png",
                "https://c.basemaps.cartocdn.com/light_only_labels/{{z}}/{{x}}/{{y}}.png"],
        tileSize: 256,
      }},
    }},
    layers: [{{ id: "carto-base-layer", type: "raster", source: "carto-base" }}],
  }},
  center: [10.45, 51.2],
  zoom: 5.5,
}});

map.addControl(new maplibregl.NavigationControl(), "top-right");

// Draw a numbered circle icon onto a canvas and return ImageData for map.addImage()
function makeHospitalIcon(label, color) {{
  const size = 20;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const r = size / 2;

  // Colored filled circle
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(r, r, r - 1, 0, Math.PI * 2);
  ctx.fill();

  // White number centered in the circle
  ctx.fillStyle = "#fff";
  ctx.font = `bold ${{size * 0.55}}px Arial, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, r, r + 0.5);

  const img = ctx.getImageData(0, 0, size, size);
  return {{ width: size, height: size, data: img.data }};
}}

map.on("load", () => {{
  // Register hospital icons — numbered by level, all the same size
  map.addImage("hospital-1", makeHospitalIcon("1", "#6b9ec7"));
  map.addImage("hospital-2", makeHospitalIcon("2", "#9b7dbf"));
  map.addImage("hospital-3", makeHospitalIcon("3", "#c4744d"));

  // Census cells layer
  map.addSource("cells", {{ type: "geojson", data: "cells.geojson" }});
  map.addLayer({{
    id: "cells-layer",
    type: "circle",
    source: "cells",
    paint: {{
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 2, 9, 5],
      "circle-color": makeTravelColor("min_any"),
      "circle-opacity": 0.7,
    }},
  }});

  // Hospital markers — symbol layer using canvas-drawn cross icons
  map.addSource("hospitals", {{ type: "geojson", data: "hospitals.geojson" }});
  map.addLayer({{
    id: "hospitals-layer",
    type: "symbol",
    source: "hospitals",
    layout: {{
      "icon-image": [
        "match", ["to-string", ["get", "level"]],
        "1", "hospital-1",
        "2", "hospital-2",
        "hospital-3"
      ],
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    }},
  }});

  // Labels on top of all data layers
  map.addLayer({{ id: "carto-labels-layer", type: "raster", source: "carto-labels" }});

  // Popup for census cells
  const popup = new maplibregl.Popup({{ closeButton: false, closeOnClick: false }});
  map.on("mouseenter", "cells-layer", (e) => {{
    map.getCanvas().style.cursor = "pointer";
    const p = e.features[0].properties;
    const fmt = (v) => v == null || v >= 999 ? "n/a" : v.toFixed(1) + " min";
    popup.setLngLat(e.lngLat).setHTML(`
      <div style="font-size:12px;line-height:1.6">
        <strong>Travel time</strong><br>
        Any hospital: ${{fmt(p.min_any)}}<br>
        Level 1: ${{fmt(p.min_l1)}}<br>
        Level 2: ${{fmt(p.min_l2)}}<br>
        Level 3: ${{fmt(p.min_l3)}}
        <hr style="margin:4px 0;border-color:#ddd">
        <strong>Population</strong><br>
        Total: ${{p.pop}}<br>
        Under 18: ${{p.pop_under18}}<br>
        18–29: ${{p.pop_18to29}}<br>
        30–49: ${{p.pop_30to49}}<br>
        50–64: ${{p.pop_50to64}}<br>
        65+: ${{p.pop_65plus}}
      </div>
    `).addTo(map);
  }});
  map.on("mouseleave", "cells-layer", () => {{
    map.getCanvas().style.cursor = "";
    popup.remove();
  }});

  // Popup for hospitals
  map.on("click", "hospitals-layer", (e) => {{
    const p = e.features[0].properties;
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(`<strong>${{p.name}}</strong><br>Level ${{p.level}} hospital`)
      .addTo(map);
  }});
}});

let currentProp = "min_any";

function setLayer(level) {{
  const propMap = {{ any: "min_any", l1: "min_l1", l2: "min_l2", l3: "min_l3" }};
  currentProp = propMap[level];
  map.setPaintProperty("cells-layer", "circle-color", makeTravelColor(currentProp));
  document.querySelectorAll(".map-btn").forEach((b, i) => {{
    b.classList.toggle("active", ["any","l1","l2","l3"][i] === level);
  }});
}}

function toggleHospitals(visible) {{
  map.setLayoutProperty("hospitals-layer", "visibility", visible ? "visible" : "none");
}}
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main generate function
# ---------------------------------------------------------------------------

def generate(dsn: str, output: str, skip_states: bool, use_cache: bool = True, resolution: str = "1km") -> None:
    """Generate a hospital accessibility report as a directory with index.html and GeoJSON files."""
    cache_dir = _cache_dir()
    cost_table = f"census_hospital_route_from_census_{resolution}"
    sql_summary = SQL_SUMMARY.format(cost_table=cost_table)
    sql_per_cell = SQL_PER_CELL.format(cost_table=cost_table, resolution=resolution)
    sql_map_cells = SQL_MAP_CELLS.format(cost_table=cost_table, resolution=resolution)
    sql_states = SQL_STATES.format(cost_table=cost_table, resolution=resolution)

    click.echo("Connecting to database…")
    try:
        conn = psycopg.connect(dsn)
    except psycopg.Error as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    with conn:
        click.echo("Fetching summary statistics…")
        df_summary = _fetch_cached(
            conn, sql_summary,
            cache_dir / f"{cost_table}_summary.pkl",
            use_cache,
        )
        if df_summary.empty:
            click.echo("No data found in census_hospital_route. Has routing been run?", err=True)
            sys.exit(1)

        click.echo("Fetching per-cell travel times…")
        df_cell = _fetch_cached(
            conn, sql_per_cell,
            cache_dir / f"{cost_table}_per_cell.pkl",
            use_cache,
        )
        click.echo(f"  → {len(df_cell):,} census cells with data")

        click.echo("Fetching map data (census centroids)…")
        df_map = _fetch_cached(
            conn, sql_map_cells,
            cache_dir / f"{cost_table}_map_cells.pkl",
            use_cache,
        )

        click.echo("Fetching hospital locations…")
        df_hospitals = _fetch_cached(
            conn, SQL_HOSPITALS_MAP,
            cache_dir / f"{cost_table}_hospitals_map.pkl",
            use_cache,
        )

        if skip_states:
            df_states = pd.DataFrame()
            click.echo("Skipping state-level analysis (--skip-states).")
        else:
            click.echo("Fetching federal state breakdown (this may take a moment)…")
            try:
                df_states = _fetch_cached(
                    conn, sql_states,
                    cache_dir / f"{cost_table}_states.pkl",
                    use_cache,
                    params={"state_names": GERMAN_STATES},
                )
                click.echo(f"  → {len(df_states):,} state × level rows")
            except psycopg.Error as e:
                click.echo(f"  State query failed ({e}); skipping.", err=True)
                df_states = pd.DataFrame()

    conn.close()

    data_note = (
        "Routing calculation is still in progress. Statistics reflect only the routes computed "
        "so far and will change as more data is added."
    )

    click.echo("Building charts…")
    c_coverage = chart_coverage_bars(df_cell)
    c_cdf      = chart_cdf(df_cell)
    c_hist     = chart_travel_histogram(df_cell)
    c_equity   = chart_equity(df_cell)
    c_states   = chart_states(df_states)
    summary_tbl = render_summary_table(df_summary)

    click.echo("Building map GeoJSON…")
    cells_geojson     = build_map_geojson(df_map)
    hospitals_geojson = build_hospitals_geojson(df_hospitals)
    click.echo(f"  → {len(cells_geojson['features']):,} cell features, "
               f"{len(hospitals_geojson['features']):,} hospital features")

    click.echo("Assembling HTML report…")
    html = render_html(
        summary_table_html=summary_tbl,
        chart_coverage=c_coverage,
        chart_cdf_html=c_cdf,
        chart_hist_html=c_hist,
        chart_equity_html=c_equity,
        chart_states_html=c_states,
        total_cells=len(df_map),
        data_note=data_note,
        resolution=resolution,
    )

    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)

    cells_path     = out_dir / "cells.geojson"
    hospitals_path = out_dir / "hospitals.geojson"
    index_path     = out_dir / "index.html"

    cells_path.write_text(json.dumps(cells_geojson), encoding="utf-8")
    hospitals_path.write_text(json.dumps(hospitals_geojson), encoding="utf-8")
    index_path.write_text(html, encoding="utf-8")

    click.echo(f"  → cells.geojson     ({cells_path.stat().st_size / 1024:.0f} KB)")
    click.echo(f"  → hospitals.geojson ({hospitals_path.stat().st_size / 1024:.0f} KB)")
    click.echo(f"  → index.html        ({index_path.stat().st_size / 1024:.0f} KB)")
    click.echo(f"Report written to: {out_dir}/")
