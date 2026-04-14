"""
Generate accessibility data files for the hospital accessibility JS application.

Produces a directory containing chart JSON files, stats.json, hospitals.geojson,
and PMTiles hexagon data files. The JS application in web/ reads these files at
runtime to render the interactive map and charts.
"""

import json
import pickle
import shutil
import sys
import tempfile
from pathlib import Path

import click
import numpy as np
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

# Per-state, per-age-group coverage for any hospital and Level 2-or-3
SQL_STATE_AGE_LEVEL_COVERAGE = """
WITH state_geoms AS (
    SELECT name, ST_Union(geom) AS geom
    FROM osm_germany.place_polygon_nested
    WHERE name = ANY(%(state_names)s)
    GROUP BY name
),
level_times AS (
    SELECT
        r.gitter_id,
        CAST(h.notfall AS float)::int AS hospital_level,
        MIN(r.total_cost_seconds)     AS min_secs
    FROM ems_germany_analysis.{cost_table} r
    JOIN ems_germany_analysis.notfall_krankenhauser_geocoded h ON r.hospital_id = h.id
    WHERE r.total_cost_seconds IS NOT NULL
    GROUP BY r.gitter_id, CAST(h.notfall AS float)::int
),
cell_times AS (
    SELECT
        gitter_id,
        MIN(min_secs)                                                  AS min_secs_any,
        LEAST(
            MIN(CASE WHEN hospital_level = 2 THEN min_secs END),
            MIN(CASE WHEN hospital_level = 3 THEN min_secs END)
        )                                                              AS min_secs_l23
    FROM level_times
    GROUP BY gitter_id
),
cell_state AS (
    SELECT
        ct.*,
        c.insgesamt_bevoelkerung AS population,
        c.a65undaelter           AS pop_65plus,
        c.unter18                AS pop_under18,
        c.a18bis29               AS pop_18to29,
        c.a30bis49               AS pop_30to49,
        c.a50bis64               AS pop_50to64,
        s.name                   AS state
    FROM cell_times ct
    JOIN zensus.alter_in_5_altersklassen_{resolution} c ON c.gitter_id_{resolution} = ct.gitter_id
    JOIN state_geoms s ON ST_Within(c.geom, s.geom)
    WHERE c.insgesamt_bevoelkerung > 0
)
SELECT
    state,
    SUM(pop_under18)                                                                                 AS total_pop_0_17,
    SUM(pop_18to29)                                                                                  AS total_pop_18_29,
    SUM(pop_30to49)                                                                                  AS total_pop_30_49,
    SUM(pop_50to64)                                                                                  AS total_pop_50_64,
    SUM(pop_65plus)                                                                                  AS total_pop_65plus,
    -- Median travel times
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY min_secs_any))::numeric / 60, 1)             AS median_any,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY min_secs_l23))::numeric / 60, 1)             AS median_l23,
    -- pct population > 30 min (underserved proxy)
    ROUND(100.0 * SUM(CASE WHEN min_secs_any > 1800 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1)  AS u30_any,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 > 1800 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1)  AS u30_l23,
    -- Any hospital coverage by age group x threshold
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <=  900 THEN pop_under18 ELSE 0 END) / NULLIF(SUM(pop_under18), 0), 1) AS any_p15_0_17,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 1800 THEN pop_under18 ELSE 0 END) / NULLIF(SUM(pop_under18), 0), 1) AS any_p30_0_17,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 3600 THEN pop_under18 ELSE 0 END) / NULLIF(SUM(pop_under18), 0), 1) AS any_p60_0_17,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <=  900 THEN pop_18to29  ELSE 0 END) / NULLIF(SUM(pop_18to29),  0), 1) AS any_p15_18_29,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 1800 THEN pop_18to29  ELSE 0 END) / NULLIF(SUM(pop_18to29),  0), 1) AS any_p30_18_29,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 3600 THEN pop_18to29  ELSE 0 END) / NULLIF(SUM(pop_18to29),  0), 1) AS any_p60_18_29,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <=  900 THEN pop_30to49  ELSE 0 END) / NULLIF(SUM(pop_30to49),  0), 1) AS any_p15_30_49,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 1800 THEN pop_30to49  ELSE 0 END) / NULLIF(SUM(pop_30to49),  0), 1) AS any_p30_30_49,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 3600 THEN pop_30to49  ELSE 0 END) / NULLIF(SUM(pop_30to49),  0), 1) AS any_p60_30_49,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <=  900 THEN pop_50to64  ELSE 0 END) / NULLIF(SUM(pop_50to64),  0), 1) AS any_p15_50_64,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 1800 THEN pop_50to64  ELSE 0 END) / NULLIF(SUM(pop_50to64),  0), 1) AS any_p30_50_64,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 3600 THEN pop_50to64  ELSE 0 END) / NULLIF(SUM(pop_50to64),  0), 1) AS any_p60_50_64,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <=  900 THEN pop_65plus  ELSE 0 END) / NULLIF(SUM(pop_65plus),  0), 1) AS any_p15_65plus,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 1800 THEN pop_65plus  ELSE 0 END) / NULLIF(SUM(pop_65plus),  0), 1) AS any_p30_65plus,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 3600 THEN pop_65plus  ELSE 0 END) / NULLIF(SUM(pop_65plus),  0), 1) AS any_p60_65plus,
    -- Total population coverage by threshold (both categories)
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <=  900 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1) AS any_p15_total,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 1800 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1) AS any_p30_total,
    ROUND(100.0 * SUM(CASE WHEN min_secs_any <= 3600 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1) AS any_p60_total,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <=  900 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1) AS l23_p15_total,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 1800 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1) AS l23_p30_total,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 3600 THEN population ELSE 0 END) / NULLIF(SUM(population), 0), 1) AS l23_p60_total,
    -- Level 2-or-3 coverage by age group x threshold
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <=  900 THEN pop_under18 ELSE 0 END) / NULLIF(SUM(pop_under18), 0), 1) AS l23_p15_0_17,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 1800 THEN pop_under18 ELSE 0 END) / NULLIF(SUM(pop_under18), 0), 1) AS l23_p30_0_17,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 3600 THEN pop_under18 ELSE 0 END) / NULLIF(SUM(pop_under18), 0), 1) AS l23_p60_0_17,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <=  900 THEN pop_18to29  ELSE 0 END) / NULLIF(SUM(pop_18to29),  0), 1) AS l23_p15_18_29,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 1800 THEN pop_18to29  ELSE 0 END) / NULLIF(SUM(pop_18to29),  0), 1) AS l23_p30_18_29,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 3600 THEN pop_18to29  ELSE 0 END) / NULLIF(SUM(pop_18to29),  0), 1) AS l23_p60_18_29,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <=  900 THEN pop_30to49  ELSE 0 END) / NULLIF(SUM(pop_30to49),  0), 1) AS l23_p15_30_49,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 1800 THEN pop_30to49  ELSE 0 END) / NULLIF(SUM(pop_30to49),  0), 1) AS l23_p30_30_49,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 3600 THEN pop_30to49  ELSE 0 END) / NULLIF(SUM(pop_30to49),  0), 1) AS l23_p60_30_49,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <=  900 THEN pop_50to64  ELSE 0 END) / NULLIF(SUM(pop_50to64),  0), 1) AS l23_p15_50_64,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 1800 THEN pop_50to64  ELSE 0 END) / NULLIF(SUM(pop_50to64),  0), 1) AS l23_p30_50_64,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 3600 THEN pop_50to64  ELSE 0 END) / NULLIF(SUM(pop_50to64),  0), 1) AS l23_p60_50_64,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <=  900 THEN pop_65plus  ELSE 0 END) / NULLIF(SUM(pop_65plus),  0), 1) AS l23_p15_65plus,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 1800 THEN pop_65plus  ELSE 0 END) / NULLIF(SUM(pop_65plus),  0), 1) AS l23_p30_65plus,
    ROUND(100.0 * SUM(CASE WHEN min_secs_l23 <= 3600 THEN pop_65plus  ELSE 0 END) / NULLIF(SUM(pop_65plus),  0), 1) AS l23_p60_65plus
FROM cell_state
GROUP BY state
ORDER BY state;
"""

# Per-state, per-age-group mean travel time to nearest hospital (any level)
SQL_STATE_AGE_BREAKDOWN = """
WITH state_geoms AS (
    SELECT name, ST_Union(geom) AS geom
    FROM osm_germany.place_polygon_nested
    WHERE name = ANY(%(state_names)s)
    GROUP BY name
),
per_cell AS (
    SELECT
        r.gitter_id,
        MIN(r.total_cost_seconds) AS min_secs_any
    FROM ems_germany_analysis.{cost_table} r
    WHERE r.total_cost_seconds IS NOT NULL
    GROUP BY r.gitter_id
),
cell_state AS (
    SELECT
        p.gitter_id,
        p.min_secs_any::numeric,
        c.insgesamt_bevoelkerung AS population,
        c.unter18                AS pop_0_17,
        c.a18bis29               AS pop_18_29,
        c.a30bis49               AS pop_30_49,
        c.a50bis64               AS pop_50_64,
        c.a65undaelter           AS pop_65plus,
        s.name                   AS state
    FROM per_cell p
    JOIN zensus.alter_in_5_altersklassen_{resolution} c ON c.gitter_id_{resolution} = p.gitter_id
    JOIN state_geoms s ON ST_Within(c.geom, s.geom)
    WHERE c.insgesamt_bevoelkerung > 0
)
SELECT
    state,
    COUNT(*)                                                                        AS census_cells,
    SUM(population)                                                                 AS total_population,
    ROUND((SUM(population  * min_secs_any) / NULLIF(SUM(population),  0) / 60), 1)  AS mean_travel_all,
    ROUND((SUM(pop_0_17    * min_secs_any) / NULLIF(SUM(pop_0_17),    0) / 60), 1)  AS mean_travel_0_17,
    ROUND((SUM(pop_18_29   * min_secs_any) / NULLIF(SUM(pop_18_29),   0) / 60), 1)  AS mean_travel_18_29,
    ROUND((SUM(pop_30_49   * min_secs_any) / NULLIF(SUM(pop_30_49),   0) / 60), 1)  AS mean_travel_30_49,
    ROUND((SUM(pop_50_64   * min_secs_any) / NULLIF(SUM(pop_50_64),   0) / 60), 1)  AS mean_travel_50_64,
    ROUND((SUM(pop_65plus  * min_secs_any) / NULLIF(SUM(pop_65plus),  0) / 60), 1)  AS mean_travel_65plus
FROM cell_state
GROUP BY state
ORDER BY state;
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
    conn: psycopg.Connection, sql: str, cache_path: Path, use_cache: bool, params=None
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

LEVEL_COLORS = {1: "#6b9ec7", 2: "#9b7dbf", 3: "#c4744d"}
LEVEL_NAMES = {1: "Level 1 (Basic)", 2: "Level 2 (Advanced)", 3: "Level 3 (Comprehensive)"}

# Age group display names, their df_cell column names, and chart colors
AGE_GROUPS = [
    ("0–17", "pop_under18", "#2563a8"),
    ("18–29", "pop_18to29", "#1a7a6e"),
    ("30–49", "pop_30to49", "#d97706"),
    ("50–64", "pop_50to64", "#7c3aed"),
    ("65+", "pop_65plus", "#c0392b"),
]
# Mapping from display name to SQL_STATE_AGE_BREAKDOWN column
AGE_STATE_COLS = {
    "0–17": "mean_travel_0_17",
    "18–29": "mean_travel_18_29",
    "30–49": "mean_travel_30_49",
    "50–64": "mean_travel_50_64",
    "65+": "mean_travel_65plus",
}


def chart_coverage_bars(df_cell: pd.DataFrame) -> dict:
    """Grouped bar: % population within 15 / 30 / 60 min by hospital level."""
    thresholds = [(15, 900), (30, 1800), (60, 3600)]
    level_cols = {1: "min_secs_l1", 2: "min_secs_l2", 3: "min_secs_l3"}
    threshold_colors = {"≤ 15 min": "#2c7bb6", "≤ 30 min": "#74add1", "≤ 60 min": "#abd9e9"}

    by_threshold: dict[str, dict] = {
        f"≤ {label} min": {"x": [], "y": []} for label, _ in thresholds
    }
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

        series.append(
            {
                "name": LEVEL_NAMES[level],
                "color": LEVEL_COLORS[level],
                "x": [round(v, 2) for v in sub["min_min"].tolist()],
                "y": [round(v, 2) for v in sub["cum_pct"].tolist()],
            }
        )

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

        series.append(
            {
                "name": LEVEL_NAMES[level],
                "color": LEVEL_COLORS[level],
                "x": [str(b) for b in pop_per_bin.index],
                "y": (100 * pop_per_bin / total).round(2).tolist(),
            }
        )

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
        groups_data["All ages"].append(
            round(100 * within["population"].sum() / total_pop, 1) if total_pop else 0
        )
        groups_data["Age 65+"].append(
            round(100 * within["pop_65plus"].sum() / total_65p, 1) if total_65p else 0
        )
        groups_data["Under 18"].append(
            round(100 * within["pop_under18"].sum() / total_u18, 1) if total_u18 else 0
        )

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
    df3_pct30 = df3.sort_values("pct_within_30min")

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


def _weighted_percentiles(
    values: np.ndarray, weights: np.ndarray, percentiles: list[float]
) -> list[float]:
    """Compute weighted percentiles. values and weights must be 1-D numpy arrays."""
    if weights.sum() == 0:
        return [float("nan")] * len(percentiles)
    order = np.argsort(values)
    vals = values[order]
    wts = weights[order]
    cum = np.cumsum(wts)
    total = cum[-1]
    result = []
    for p in percentiles:
        thr = p / 100.0 * total
        idx = int(np.searchsorted(cum, thr, side="left"))
        idx = min(idx, len(vals) - 1)
        result.append(float(vals[idx]))
    return result


def chart_sidebar_hist(df_cell: pd.DataFrame) -> dict:
    """Population-weighted histogram of travel times to nearest hospital (any level)."""
    sub = df_cell.dropna(subset=["min_secs_any"]).copy()
    sub["min_min"] = sub["min_secs_any"] / 60
    bins = list(range(0, 91, 5))
    sub["bin"] = pd.cut(sub["min_min"], bins=bins, right=False)
    pop_per_bin = sub.groupby("bin", observed=False)["population"].sum()
    total = pop_per_bin.sum()
    return {
        "series": [
            {
                "name": "All hospitals",
                "color": "#2563a8",
                "x": [str(b) for b in pop_per_bin.index],
                "y": (100 * pop_per_bin / total).round(2).tolist(),
            }
        ]
    }


def chart_age_box(df_cell: pd.DataFrame) -> dict:
    """Population-weighted box-plot summary statistics per age group (min_secs_any)."""
    sub = df_cell.dropna(subset=["min_secs_any"]).copy()
    times = (sub["min_secs_any"] / 60).to_numpy()
    groups = []
    for label, pop_col, color in AGE_GROUPS:
        if pop_col not in sub.columns:
            continue
        weights = sub[pop_col].fillna(0).to_numpy().astype(float)
        if weights.sum() == 0:
            continue
        q1, median, q3 = _weighted_percentiles(times, weights, [25, 50, 75])
        iqr = q3 - q1
        # Weighted mean
        mean_val = float(np.sum(times * weights) / weights.sum())
        groups.append(
            {
                "name": label,
                "color": color,
                "q1": round(q1, 2),
                "median": round(median, 2),
                "q3": round(q3, 2),
                "lowerfence": round(max(0, q1 - 1.5 * iqr), 2),
                "upperfence": round(q3 + 1.5 * iqr, 2),
                "mean": round(mean_val, 2),
            }
        )
    return {"groups": groups}


def chart_age_cdf(df_cell: pd.DataFrame) -> dict:
    """CDF per age group: cumulative share of age-group population within X minutes."""
    sub = df_cell.dropna(subset=["min_secs_any"]).copy()
    sub["min_min"] = sub["min_secs_any"] / 60
    sub = sub.sort_values("min_min")
    series = []
    for label, pop_col, color in AGE_GROUPS:
        if pop_col not in sub.columns:
            continue
        group_pop = sub[pop_col].fillna(0)
        total_pop = group_pop.sum()
        if total_pop == 0:
            continue
        cum_pct = 100 * group_pop.cumsum() / total_pop
        # Downsample for smooth curve
        step = max(1, len(sub) // 5000)
        series.append(
            {
                "name": label,
                "color": color,
                "x": [round(v, 2) for v in sub["min_min"].iloc[::step].tolist()],
                "y": [round(v, 2) for v in cum_pct.iloc[::step].tolist()],
            }
        )
    return {"series": series}


def chart_age_bar(df_cell: pd.DataFrame) -> dict:
    """Population-weighted mean ± std travel time per age group (min_secs_any)."""
    sub = df_cell.dropna(subset=["min_secs_any"]).copy()
    times = (sub["min_secs_any"] / 60).to_numpy()
    bars = []
    for label, pop_col, color in AGE_GROUPS:
        if pop_col not in sub.columns:
            continue
        weights = sub[pop_col].fillna(0).to_numpy().astype(float)
        total_w = weights.sum()
        if total_w == 0:
            continue
        mean_val = float(np.sum(times * weights) / total_w)
        variance = float(np.sum(weights * (times - mean_val) ** 2) / total_w)
        bars.append(
            {
                "name": label,
                "color": color,
                "mean": round(mean_val, 2),
                "std": round(variance**0.5, 2),
            }
        )
    return {"bars": bars}


def chart_bl_bar(df_states: pd.DataFrame) -> dict | None:
    """Horizontal bar: median travel time by Bundesland for Level 3, sorted ascending."""
    df3 = df_states[df_states["hospital_level"] == 3].copy()
    if df3.empty:
        return None
    df3 = df3.sort_values("median_travel_min")
    return {
        "states": df3["state"].tolist(),
        "medians": [float(v) for v in df3["median_travel_min"].tolist()],
    }


def chart_bl_pct(df_states: pd.DataFrame) -> dict | None:
    """Bar chart: % population >30 min from Level 3 hospital by Bundesland."""
    df3 = df_states[df_states["hospital_level"] == 3].copy()
    if df3.empty:
        return None
    df3 = df3.sort_values("pct_within_30min")
    return {
        "states": df3["state"].tolist(),
        "pct_over30": [round(100 - float(v), 1) for v in df3["pct_within_30min"].tolist()],
    }


def chart_bl_scatter(df_state_age: pd.DataFrame) -> dict | None:
    """Scatter: population density proxy vs median travel time per Bundesland."""
    if df_state_age.empty:
        return None
    df = df_state_age.copy()
    df["density"] = df["total_population"] / df["census_cells"].replace(0, float("nan"))
    df = df.dropna(subset=["density", "mean_travel_all"])
    return {
        "points": [
            {
                "state": row["state"],
                "density": round(float(row["density"]), 1),
                "mean": round(float(row["mean_travel_all"]), 1),
            }
            for _, row in df.iterrows()
        ]
    }


def chart_combined_heat(df_state_age: pd.DataFrame) -> dict | None:
    """Heatmap matrix: rows = Bundesland, columns = age group, values = mean travel time."""
    if df_state_age.empty:
        return None
    age_labels = [label for label, _, _ in AGE_GROUPS]
    states = df_state_age["state"].tolist()
    z = []
    for _, row in df_state_age.iterrows():
        row_vals = []
        for label in age_labels:
            col = AGE_STATE_COLS[label]
            row_vals.append(float(row[col]) if row[col] is not None else None)
        z.append(row_vals)
    return {"states": states, "age_groups": age_labels, "z": z}


def chart_age_level_bl(df_cell: pd.DataFrame, df_state_age_level: pd.DataFrame) -> dict:
    """Grouped bar: % of each age group within threshold for Any hospital vs Level 2/3.

    Returns one dataset per region (All Germany + each Bundesland) for use with
    the chart-age-level-bl web component, which provides a region dropdown and
    threshold selector.
    """
    thresholds = [("15", 900), ("30", 1800), ("60", 3600)]
    age_groups = [
        ("0–17", "pop_under18"),
        ("18–29", "pop_18to29"),
        ("30–49", "pop_30to49"),
        ("50–64", "pop_50to64"),
        ("65+", "pop_65plus"),
    ]

    def _cov(df: pd.DataFrame, col: str, secs: int, pop: str) -> float:
        sub = df.dropna(subset=[col])
        total = sub[pop].sum()
        if total == 0:
            return 0.0
        return round(float(100 * sub.loc[sub[col] <= secs, pop].sum() / total), 1)

    def _stats(df: pd.DataFrame, col: str) -> dict:
        sub = df.dropna(subset=[col]).copy()
        total = sub["population"].sum()
        if total == 0:
            return {"median": None, "underserved_pct": None}
        median = float(np.average(sub[col] / 60, weights=sub["population"].clip(lower=0)))
        u30 = round(float(100 * sub.loc[sub[col] > 1800, "population"].sum() / total), 1)
        return {"median": round(median, 1), "underserved_pct": u30}

    nat = df_cell.copy()
    nat["min_secs_l23"] = nat[["min_secs_l2", "min_secs_l3"]].min(axis=1)

    def _build_region_from_df(df: pd.DataFrame) -> dict:
        entry: dict = {}
        df = df.copy()
        df["min_secs_l23"] = df[["min_secs_l2", "min_secs_l3"]].min(axis=1)
        for thr_label, thr_secs in thresholds:
            entry[thr_label] = {
                "any": [_cov(df, "min_secs_any", thr_secs, ag[1]) for ag in age_groups],
                "l23": [_cov(df, "min_secs_l23", thr_secs, ag[1]) for ag in age_groups],
            }
        entry["stats"] = {"any": _stats(df, "min_secs_any"), "l23": _stats(df, "min_secs_l23")}
        return entry

    regions: dict[str, dict] = {"All Germany": _build_region_from_df(nat)}

    # Per-state values come from the SQL result (wide-format row per state)
    if not df_state_age_level.empty:
        col_map = {
            "0–17": ("0_17", "total_pop_0_17"),
            "18–29": ("18_29", "total_pop_18_29"),
            "30–49": ("30_49", "total_pop_30_49"),
            "50–64": ("50_64", "total_pop_50_64"),
            "65+": ("65plus", "total_pop_65plus"),
        }
        thr_map = {"15": "p15", "30": "p30", "60": "p60"}

        cols = df_state_age_level.columns
        for _, row in df_state_age_level.iterrows():
            state = row["state"]
            entry: dict = {}
            for thr_label, thr_key in thr_map.items():
                any_vals, l23_vals = [], []
                for ag_label, (ag_suffix, _) in col_map.items():
                    any_col = f"any_{thr_key}_{ag_suffix}"
                    l23_col = f"l23_{thr_key}_{ag_suffix}"
                    any_vals.append(
                        float(row[any_col]) if any_col in cols and pd.notna(row[any_col]) else None
                    )
                    l23_vals.append(
                        float(row[l23_col]) if l23_col in cols and pd.notna(row[l23_col]) else None
                    )
                entry[thr_label] = {"any": any_vals, "l23": l23_vals}

            entry["stats"] = {
                "any": {
                    "median": float(row["median_any"])
                    if "median_any" in cols and pd.notna(row["median_any"])
                    else None,
                    "underserved_pct": float(row["u30_any"])
                    if "u30_any" in cols and pd.notna(row["u30_any"])
                    else None,
                },
                "l23": {
                    "median": float(row["median_l23"])
                    if "median_l23" in cols and pd.notna(row["median_l23"])
                    else None,
                    "underserved_pct": float(row["u30_l23"])
                    if "u30_l23" in cols and pd.notna(row["u30_l23"])
                    else None,
                },
            }
            regions[state] = entry

    return {"age_groups": [ag[0] for ag in age_groups], "data": regions}


def chart_bl_coverage(df_cell: pd.DataFrame, df_state_age_level: pd.DataFrame) -> dict:
    """Horizontal bar: % population within threshold per Bundesland for any vs Level 2/3.

    Returns state-sorted arrays for each category × threshold combination, plus
    national summary stats, for use with the chart-bl-coverage web component.
    """
    thresholds = [("15", 900), ("30", 1800), ("60", 3600)]

    # Build a working copy with the derived l23 column up front so all helpers can use it.
    nat = df_cell.copy()
    nat["min_secs_l23"] = nat[["min_secs_l2", "min_secs_l3"]].min(axis=1)

    def _nat_stats(col: str) -> dict:
        sub = nat.dropna(subset=[col]).copy()
        total = sub["population"].sum()
        if total == 0:
            return {"median": None, "underserved_pct": None}
        median = float(np.average(sub[col] / 60, weights=sub["population"].clip(lower=0)))
        u30 = round(float(100 * sub.loc[sub[col] > 1800, "population"].sum() / total), 1)
        return {"median": round(median, 1), "underserved_pct": u30}

    # National summary stats
    nat_stats = {"any": _nat_stats("min_secs_any"), "l23": _nat_stats("min_secs_l23")}

    states: list[str] = []
    any_vals: dict[str, list] = {"15": [], "30": [], "60": []}
    l23_vals: dict[str, list] = {"15": [], "30": [], "60": []}

    if not df_state_age_level.empty:
        cols = df_state_age_level.columns
        for _, row in df_state_age_level.sort_values("state").iterrows():
            states.append(row["state"])
            for thr_label, _ in thresholds:
                any_col = f"any_p{thr_label}_total"
                l23_col = f"l23_p{thr_label}_total"
                any_vals[thr_label].append(
                    float(row[any_col]) if any_col in cols and pd.notna(row[any_col]) else None
                )
                l23_vals[thr_label].append(
                    float(row[l23_col]) if l23_col in cols and pd.notna(row[l23_col]) else None
                )

    return {"states": states, "any": any_vals, "l23": l23_vals, "stats": nat_stats}


def chart_sm_age(df_state_age: pd.DataFrame, age_col: str, label: str) -> dict | None:
    """Small multiple: horizontal bar of mean travel time by Bundesland for one age group."""
    if df_state_age.empty or age_col not in df_state_age.columns:
        return None
    df = df_state_age[["state", age_col]].dropna(subset=[age_col])
    df = df.sort_values(age_col)
    return {
        "label": label,
        "states": df["state"].tolist(),
        "values": [round(float(v), 1) for v in df[age_col].tolist()],
    }


# ---------------------------------------------------------------------------
# Summary table (kept for reference; not used in new template)
# ---------------------------------------------------------------------------


def render_summary_table(df_summary: pd.DataFrame) -> str:
    rows_html = ""
    for _, row in df_summary.iterrows():
        level = int(row["hospital_level"])
        rows_html += f"""
        <tr>
          <td><span class="level-badge level-{level}">Level {level}</span></td>
          <td>{int(row["hospital_count"])}</td>
          <td>{int(row["census_cells_covered"]):,}</td>
          <td>{float(row["avg_travel_min"]):.1f}</td>
          <td>{float(row["median_travel_min"]):.1f}</td>
          <td>{float(row["pct_routes_15min"]):.1f}%</td>
          <td>{float(row["pct_routes_30min"]):.1f}%</td>
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
                    "avg_travel_l1": float(row[2]) if row[2] is not None else None,
                    "avg_travel_l2": float(row[3]) if row[3] is not None else None,
                    "avg_travel_l3": float(row[4]) if row[4] is not None else None,
                    "total_population": int(row[5]) if row[5] is not None else 0,
                    "pop_under18": int(row[6]) if row[6] is not None else 0,
                    "pop_18to29": int(row[7]) if row[7] is not None else 0,
                    "pop_30to49": int(row[8]) if row[8] is not None else 0,
                    "pop_50to64": int(row[9]) if row[9] is not None else 0,
                    "pop_65plus": int(row[10]) if row[10] is not None else 0,
                }
                f.write(
                    json.dumps(
                        {"type": "Feature", "geometry": json.loads(row[0]), "properties": props}
                    )
                )
                count += 1
        f.write("]}")
    return count


def generate_pmtiles(conn: psycopg.Connection, out_dir: Path) -> None:
    """Export hex travel tables to GeoJSON and tile with tippecanoe."""
    pmtiles_dir = out_dir / "pmtiles"
    pmtiles_dir.mkdir(exist_ok=True)

    configs = [
        ("hex_travel_5km", "hex_5km", 0, 9),
        ("hex_travel_1km", "hex_1km", 7, 12),
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
                    "-o",
                    str(pmtiles_path),
                    f"-Z{zoom_min}",
                    f"-z{zoom_max}",
                    "-l",
                    name,
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
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row["lon"]), float(row["lat"])],
                },
                "properties": {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "level": int(row["level"]),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------


def _compute_kpis(df_cell: pd.DataFrame, cols: list[str]) -> dict:
    """Compute summary KPIs for the effective travel time = min across cols."""
    sub = df_cell.copy()
    sub["_eff_secs"] = sub[cols].min(axis=1)
    sub = sub.dropna(subset=["_eff_secs"])
    total_pop = sub["population"].sum()
    if total_pop == 0:
        return {"median": 0.0, "cov30": 0.0, "underserved_m": 0.0}
    median = float(np.average(sub["_eff_secs"] / 60, weights=sub["population"].clip(lower=0)))
    cov30 = float(100 * sub.loc[sub["_eff_secs"] <= 1800, "population"].sum() / total_pop)
    underserved_m = float(sub.loc[sub["_eff_secs"] > 1800, "population"].sum() / 1e6)
    return {
        "median": round(median, 1),
        "cov30": round(cov30, 1),
        "underserved_m": round(underserved_m, 2),
    }


def compute_stats_by_selection(df_cell: pd.DataFrame) -> dict:
    """Compute summary KPIs for each hospital level selection (single and pairs)."""
    col = {
        "any": ["min_secs_any"],
        "l1": ["min_secs_l1"],
        "l2": ["min_secs_l2"],
        "l3": ["min_secs_l3"],
        "l1,l2": ["min_secs_l1", "min_secs_l2"],
        "l1,l3": ["min_secs_l1", "min_secs_l3"],
        "l2,l3": ["min_secs_l2", "min_secs_l3"],
    }
    return {key: _compute_kpis(df_cell, cols) for key, cols in col.items()}


def write_stats_json(df_cell: pd.DataFrame, out_dir: Path) -> None:
    """Write stats.json — per-selection KPI data consumed by the JS app at runtime."""
    stats = compute_stats_by_selection(df_cell)
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main generate function
# ---------------------------------------------------------------------------


def generate(
    dsn: str,
    output: str,
    skip_states: bool,
    skip_tiles: bool,
    use_cache: bool = True,
    resolution: str = "1km",
) -> None:
    """Generate accessibility data files (JSON, GeoJSON, PMTiles) into the output directory."""
    if shutil.which("tippecanoe") is None:
        click.echo("Error: tippecanoe is not installed or not in PATH.", err=True)
        click.echo("Install tippecanoe: https://github.com/felt/tippecanoe", err=True)
        sys.exit(1)

    cache_dir = _cache_dir()
    cost_table = f"census_hospital_route_from_census_{resolution}"
    sql_summary = SQL_SUMMARY.format(cost_table=cost_table)
    sql_per_cell = SQL_PER_CELL.format(cost_table=cost_table, resolution=resolution)
    sql_states = SQL_STATES.format(cost_table=cost_table, resolution=resolution)
    sql_state_age = SQL_STATE_AGE_BREAKDOWN.format(cost_table=cost_table, resolution=resolution)
    sql_state_age_level = SQL_STATE_AGE_LEVEL_COVERAGE.format(
        cost_table=cost_table, resolution=resolution
    )

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
            conn, sql_summary, cache_dir / f"{cost_table}_summary.pkl", use_cache
        )
        if df_summary.empty:
            click.echo("No data found in census_hospital_route. Has routing been run?", err=True)
            sys.exit(1)

        click.echo("Fetching per-cell travel times…")
        df_cell = _fetch_cached(
            conn, sql_per_cell, cache_dir / f"{cost_table}_per_cell.pkl", use_cache
        )
        click.echo(f"  → {len(df_cell):,} census cells with data")

        click.echo("Fetching hospital locations…")
        df_hospitals = _fetch_cached(
            conn, SQL_HOSPITALS_MAP, cache_dir / f"{cost_table}_hospitals_map.pkl", use_cache
        )

        if skip_states:
            df_states = pd.DataFrame()
            df_state_age = pd.DataFrame()
            df_state_age_level = pd.DataFrame()
            click.echo("Skipping state-level analysis (--skip-states).")
        else:
            click.echo("Fetching federal state breakdown (this may take a moment)…")
            try:
                df_states = _fetch_cached(
                    conn,
                    sql_states,
                    cache_dir / f"{cost_table}_states.pkl",
                    use_cache,
                    params={"state_names": GERMAN_STATES},
                )
                click.echo(f"  → {len(df_states):,} state × level rows")
            except psycopg.Error as e:
                click.echo(f"  State query failed ({e}); skipping.", err=True)
                df_states = pd.DataFrame()

            click.echo("Fetching state × age-group breakdown…")
            try:
                df_state_age = _fetch_cached(
                    conn,
                    sql_state_age,
                    cache_dir / f"{cost_table}_state_age.pkl",
                    use_cache,
                    params={"state_names": GERMAN_STATES},
                )
                click.echo(f"  → {len(df_state_age):,} state rows")
            except psycopg.Error as e:
                click.echo(f"  State × age query failed ({e}); skipping.", err=True)
                df_state_age = pd.DataFrame()

            click.echo("Fetching state × age-group × level coverage…")
            try:
                df_state_age_level = _fetch_cached(
                    conn,
                    sql_state_age_level,
                    cache_dir / f"{cost_table}_state_age_level.pkl",
                    use_cache,
                    params={"state_names": GERMAN_STATES},
                )
                click.echo(f"  → {len(df_state_age_level):,} state rows")
            except psycopg.Error as e:
                click.echo(f"  State × age × level query failed ({e}); skipping.", err=True)
                df_state_age_level = pd.DataFrame()

    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not skip_tiles:
        click.echo("Generating PMTiles…")
        with psycopg.connect(dsn) as conn2:
            generate_pmtiles(conn2, out_dir)
    else:
        click.echo("Skipping PMTiles generation…")

    click.echo("Building hospitals GeoJSON…")
    hospitals_geojson = build_hospitals_geojson(df_hospitals)
    hospitals_path = out_dir / "hospitals.geojson"
    hospitals_path.write_text(json.dumps(hospitals_geojson), encoding="utf-8")
    click.echo(f"  → {len(hospitals_geojson['features']):,} hospital features")

    click.echo("Building charts…")
    chart_data: dict[str, dict | None] = {
        "chart-cdf.json": chart_cdf(df_cell),
        "chart-age-box.json": chart_age_box(df_cell),
        "chart-age-cdf.json": chart_age_cdf(df_cell),
        "chart-age-bar.json": chart_age_bar(df_cell),
        "chart-bl-bar.json": chart_bl_bar(df_states),
        "chart-bl-pct.json": chart_bl_pct(df_states),
        "chart-bl-scatter.json": chart_bl_scatter(df_state_age),
        "chart-combined-heat.json": chart_combined_heat(df_state_age),
        "chart-sm-0-17.json": chart_sm_age(df_state_age, "mean_travel_0_17", "0–17"),
        "chart-sm-18-29.json": chart_sm_age(df_state_age, "mean_travel_18_29", "18–29"),
        "chart-sm-30-49.json": chart_sm_age(df_state_age, "mean_travel_30_49", "30–49"),
        "chart-sm-50-64.json": chart_sm_age(df_state_age, "mean_travel_50_64", "50–64"),
        "chart-sm-65plus.json": chart_sm_age(df_state_age, "mean_travel_65plus", "65+"),
        "chart-age-level-bl.json": chart_age_level_bl(df_cell, df_state_age_level),
        "chart-bl-coverage.json": chart_bl_coverage(df_cell, df_state_age_level),
    }
    for filename, data in chart_data.items():
        if data is not None:
            (out_dir / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    click.echo("Writing stats.json…")
    write_stats_json(df_cell, out_dir)

    click.echo(f"  → hospitals.geojson ({hospitals_path.stat().st_size / 1024:.0f} KB)")
    click.echo(f"  → stats.json        ({(out_dir / 'stats.json').stat().st_size / 1024:.0f} KB)")
    for filename, data in chart_data.items():
        if data is not None:
            click.echo(f"  → {filename:<32} ({(out_dir / filename).stat().st_size / 1024:.0f} KB)")
    click.echo(f"Data written to: {out_dir}/")
    click.echo("Run 'npm run build' in web/ to build the JS application.")
