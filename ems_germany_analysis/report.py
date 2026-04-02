"""
Generate a hospital accessibility report for Germany.

Produces a directory containing index.html with interactive charts (Plotly),
an interactive map (MapLibre GL JS), and PMTiles hexagon data files.
"""
import importlib.resources
import json
import pickle
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click
import pandas as pd
import platformdirs
import psycopg

from .constants import APP_NAME
from .db import create_hex_tables_sync

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


def chart_coverage_bars(df_cell: pd.DataFrame) -> dict:
    """Grouped bar: % population within 15 / 30 / 60 min by hospital level."""
    thresholds = [(15, 900), (30, 1800), (60, 3600)]
    level_cols = {1: "min_secs_l1", 2: "min_secs_l2", 3: "min_secs_l3"}
    threshold_colors = {"≤ 15 min": "#2c7bb6", "≤ 30 min": "#74add1", "≤ 60 min": "#abd9e9"}

    by_threshold: dict[str, dict] = {f"≤ {label} min": {"x": [], "y": []} for label, _ in thresholds}
    for level, col in level_cols.items():
        sub = df_cell.dropna(subset=[col])
        total_pop = sub["population"].sum()
        if total_pop == 0:
            continue
        for label, secs in thresholds:
            key = f"≤ {label} min"
            pct = round(100 * sub.loc[sub[col] <= secs, "population"].sum() / total_pop, 1)
            by_threshold[key]["x"].append(LEVEL_NAMES[level])
            by_threshold[key]["y"].append(pct)

    return {
        "traces": [
            {"name": name, "color": threshold_colors[name], "x": vals["x"], "y": vals["y"]}
            for name, vals in by_threshold.items()
        ]
    }


def chart_cdf(df_cell: pd.DataFrame) -> dict:
    """CDF: cumulative % of population vs. travel time (minutes)."""
    level_cols = {1: "min_secs_l1", 2: "min_secs_l2", 3: "min_secs_l3"}
    series = []

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

        series.append({
            "name":  LEVEL_NAMES[level],
            "color": LEVEL_COLORS[level],
            "x": [round(v, 2) for v in sub["min_min"].tolist()],
            "y": [round(v, 2) for v in sub["cum_pct"].tolist()],
        })

    return {"series": series}


def chart_travel_histogram(df_cell: pd.DataFrame) -> dict:
    """Population-weighted histogram of travel times by hospital level."""
    level_cols = {1: "min_secs_l1", 2: "min_secs_l2", 3: "min_secs_l3"}
    bins = list(range(0, 91, 5))  # 5-minute bins up to 90 min
    series = []

    for level, col in level_cols.items():
        sub = df_cell.dropna(subset=[col]).copy()
        sub["min_min"] = sub[col] / 60
        sub["bin"] = pd.cut(sub["min_min"], bins=bins, right=False)
        pop_per_bin = sub.groupby("bin", observed=False)["population"].sum()
        total = pop_per_bin.sum()

        series.append({
            "name":  LEVEL_NAMES[level],
            "color": LEVEL_COLORS[level],
            "x": [str(b) for b in pop_per_bin.index],
            "y": (100 * pop_per_bin / total).round(2).tolist(),
        })

    return {"series": series}


def chart_equity(df_cell: pd.DataFrame) -> dict:
    """Compare accessibility for elderly (65+) vs. general population."""
    level_col = "min_secs_l3"  # Focus on Level 3 (highest care)
    thresholds = [15, 30, 60]
    group_colors = {"All ages": "#2c7bb6", "Age 65+": "#d7191c", "Under 18": "#4dac26"}

    sub = df_cell.dropna(subset=[level_col]).copy()
    sub["min_min_l3"] = sub[level_col] / 60

    total_pop = sub["population"].sum()
    total_65p = sub["pop_65plus"].sum()
    total_u18 = sub["pop_under18"].sum()

    groups_data: dict[str, list] = {"All ages": [], "Age 65+": [], "Under 18": []}
    x_labels = []
    for thr in thresholds:
        within = sub[sub["min_min_l3"] <= thr]
        x_labels.append(f"≤ {thr} min")
        groups_data["All ages"].append(round(100 * within["population"].sum() / total_pop, 1) if total_pop else 0)
        groups_data["Age 65+"].append(round(100 * within["pop_65plus"].sum()  / total_65p,  1) if total_65p  else 0)
        groups_data["Under 18"].append(round(100 * within["pop_under18"].sum() / total_u18,  1) if total_u18  else 0)

    return {
        "groups": [
            {"name": name, "color": group_colors[name], "x": x_labels, "y": vals}
            for name, vals in groups_data.items()
        ]
    }


def chart_states(df_states: pd.DataFrame) -> dict | None:
    """Median travel time and 30-min coverage by federal state for Level 3 hospitals."""
    df3 = df_states[df_states["hospital_level"] == 3].copy()
    if df3.empty:
        return None

    df3_median = df3.sort_values("median_travel_min")
    df3_pct30  = df3.sort_values("pct_within_30min")

    return {
        "median": [
            {"state": row["state"], "value": float(row["median_travel_min"])}
            for _, row in df3_median.iterrows()
        ],
        "pct30": [
            {"state": row["state"], "value": float(row["pct_within_30min"])}
            for _, row in df3_pct30.iterrows()
        ],
    }


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
# PMTiles generation
# ---------------------------------------------------------------------------

def _write_hex_geojson(conn: psycopg.Connection, table: str, output_path: Path) -> int:
    """Stream hex travel table rows to a GeoJSON file. Returns feature count."""
    sql = f"""
        SELECT
            ST_AsGeoJSON(ST_Transform(geom, 4326)),
            avg_travel_any, avg_travel_l1, avg_travel_l2, avg_travel_l3,
            total_population, pop_under18, pop_18to29, pop_30to49, pop_50to64, pop_65plus
        FROM ems_germany_analysis.{table}
    """
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        f.write('{"type":"FeatureCollection","features":[')
        first = True
        with conn.cursor() as cur:
            cur.execute(sql)
            for row in cur:
                if not first:
                    f.write(",")
                first = False
                props = {
                    "avg_travel_any": float(row[1]) if row[1] is not None else None,
                    "avg_travel_l1":  float(row[2]) if row[2] is not None else None,
                    "avg_travel_l2":  float(row[3]) if row[3] is not None else None,
                    "avg_travel_l3":  float(row[4]) if row[4] is not None else None,
                    "total_population": int(row[5]) if row[5] is not None else 0,
                    "pop_under18":    int(row[6])  if row[6]  is not None else 0,
                    "pop_18to29":     int(row[7])  if row[7]  is not None else 0,
                    "pop_30to49":     int(row[8])  if row[8]  is not None else 0,
                    "pop_50to64":     int(row[9])  if row[9]  is not None else 0,
                    "pop_65plus":     int(row[10]) if row[10] is not None else 0,
                }
                f.write(json.dumps({
                    "type": "Feature",
                    "geometry": json.loads(row[0]),
                    "properties": props,
                }))
                count += 1
        f.write("]}")
    return count


def generate_pmtiles(conn: psycopg.Connection, out_dir: Path) -> None:
    """Export hex travel tables to GeoJSON and tile with tippecanoe."""
    pmtiles_dir = out_dir / "pmtiles"
    pmtiles_dir.mkdir(exist_ok=True)

    configs = [
        ("hex_travel_5km",  "hex_5km",  0,  9),
        ("hex_travel_1km",  "hex_1km",  7, 12),
        ("hex_travel_100m", "hex_100m", 10, 14),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for table, name, zoom_min, zoom_max in configs:
            click.echo(f"  → Exporting {table} to GeoJSON…")
            geojson_path = tmp_path / f"{name}.geojson"
            count = _write_hex_geojson(conn, table, geojson_path)
            click.echo(f"    {count:,} features")

            pmtiles_path = pmtiles_dir / f"{name}.pmtiles"
            click.echo(f"  → Tiling {name}.pmtiles (z{zoom_min}–z{zoom_max})…")
            subprocess.run(
                [
                    "tippecanoe",
                    "-o", str(pmtiles_path),
                    f"-Z{zoom_min}", f"-z{zoom_max}",
                    "-l", name,
                    "--drop-densest-as-needed",
                    "--extend-zooms-if-still-dropping",
                    "-P",
                    "-f",
                    str(geojson_path),
                ],
                check=True,
            )
            size_mb = pmtiles_path.stat().st_size / 1024 / 1024
            click.echo(f"    → {pmtiles_path.name} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Hospital GeoJSON
# ---------------------------------------------------------------------------

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

def _chart_element(tag: str, src: str | None) -> str:
    """Render a chart custom element with a src URL, or an empty element if no data."""
    if src is None:
        return f"<{tag}></{tag}>"
    return f'<{tag} src="{src}"></{tag}>'


def render_report(
    summary_table_html: str,
    chart_coverage_src: str,
    chart_cdf_src: str,
    chart_hist_src: str,
    chart_equity_src: str,
    chart_states_src: str | None,
    total_cells: int,
    data_note: str,
    resolution: str = "1km",
) -> str:
    """Render the report HTML by loading the template and substituting placeholders."""
    pkg = importlib.resources.files("ems_germany_analysis")
    template_text = pkg.joinpath("templates/report.html").read_text(encoding="utf-8")
    return (
        template_text
        .replace("<!-- INSERT_RESOLUTION -->", resolution)
        .replace("<!-- INSERT_DATA_NOTE -->", data_note)
        .replace("<!-- INSERT_SUMMARY_TABLE -->", summary_table_html)
        .replace("<!-- INSERT_CHART_COVERAGE -->", _chart_element("chart-coverage", chart_coverage_src))
        .replace("<!-- INSERT_CHART_CDF -->",      _chart_element("chart-cdf",      chart_cdf_src))
        .replace("<!-- INSERT_CHART_HIST -->",     _chart_element("chart-histogram", chart_hist_src))
        .replace("<!-- INSERT_CHART_EQUITY -->",   _chart_element("chart-equity",   chart_equity_src))
        .replace("<!-- INSERT_CHART_STATES -->",   _chart_element("chart-states",   chart_states_src))
        .replace("<!-- INSERT_TOTAL_CELLS -->", f"{total_cells:,}")
    )


# ---------------------------------------------------------------------------
# Main generate function
# ---------------------------------------------------------------------------

def generate(dsn: str, output: str, skip_states: bool, use_cache: bool = True, resolution: str = "1km") -> None:
    """Generate a hospital accessibility report as a directory with index.html and PMTiles data."""
    if shutil.which("tippecanoe") is None:
        click.echo("Error: tippecanoe is not installed or not in PATH.", err=True)
        click.echo("Install tippecanoe: https://github.com/felt/tippecanoe", err=True)
        sys.exit(1)

    cache_dir = _cache_dir()
    cost_table = f"census_hospital_route_from_census_{resolution}"
    sql_summary = SQL_SUMMARY.format(cost_table=cost_table)
    sql_per_cell = SQL_PER_CELL.format(cost_table=cost_table, resolution=resolution)
    sql_states = SQL_STATES.format(cost_table=cost_table, resolution=resolution)

    click.echo("Connecting to database…")
    try:
        conn = psycopg.connect(dsn)
    except psycopg.Error as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo("Creating hex grid and travel time tables (this may take a while on first run)…")
    create_hex_tables_sync(conn)

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

    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)

    click.echo("Generating PMTiles…")
    with psycopg.connect(dsn) as conn2:
        generate_pmtiles(conn2, out_dir)

    click.echo("Building hospitals GeoJSON…")
    hospitals_geojson = build_hospitals_geojson(df_hospitals)
    hospitals_path = out_dir / "hospitals.geojson"
    hospitals_path.write_text(json.dumps(hospitals_geojson), encoding="utf-8")
    click.echo(f"  → {len(hospitals_geojson['features']):,} hospital features")

    click.echo("Building charts…")
    chart_data = {
        "chart-coverage.json": chart_coverage_bars(df_cell),
        "chart-cdf.json":      chart_cdf(df_cell),
        "chart-hist.json":     chart_travel_histogram(df_cell),
        "chart-equity.json":   chart_equity(df_cell),
        "chart-states.json":   chart_states(df_states),
    }
    for filename, data in chart_data.items():
        if data is not None:
            (out_dir / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    summary_tbl = render_summary_table(df_summary)

    data_note = (
        "Routing calculation is still in progress. Statistics reflect only the routes computed "
        "so far and will change as more data is added."
    )

    click.echo("Assembling HTML report…")
    html = render_report(
        summary_table_html=summary_tbl,
        chart_coverage_src="chart-coverage.json",
        chart_cdf_src="chart-cdf.json",
        chart_hist_src="chart-hist.json",
        chart_equity_src="chart-equity.json",
        chart_states_src="chart-states.json" if chart_data["chart-states.json"] is not None else None,
        total_cells=len(df_cell),
        data_note=data_note,
        resolution=resolution,
    )

    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    # Copy web component JS files from package templates to output directory
    pkg = importlib.resources.files("ems_germany_analysis")
    component_files = [
        "chart-coverage.js",
        "chart-cdf.js",
        "chart-histogram.js",
        "chart-equity.js",
        "chart-states.js",
        "accessibility-map.js",
    ]
    for js_file in component_files:
        text = pkg.joinpath(f"templates/{js_file}").read_text(encoding="utf-8")
        (out_dir / js_file).write_text(text, encoding="utf-8")

    click.echo(f"  → hospitals.geojson ({hospitals_path.stat().st_size / 1024:.0f} KB)")
    click.echo(f"  → index.html        ({index_path.stat().st_size / 1024:.0f} KB)")
    for js_file in component_files:
        click.echo(f"  → {js_file:<30} ({(out_dir / js_file).stat().st_size / 1024:.0f} KB)")
    for filename in chart_data:
        p = out_dir / filename
        if p.exists():
            click.echo(f"  → {filename:<30} ({p.stat().st_size / 1024:.0f} KB)")
    click.echo(f"Report written to: {out_dir}/")
