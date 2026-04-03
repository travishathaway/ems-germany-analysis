"""
Module for various functions and classes to help with database connections.
"""
from logging import getLogger
from typing import NamedTuple

import click
import psycopg
import psycopg.sql
from psycopg_pool import AsyncConnectionPool

from .constants import (
    CENSUS_HOSPITAL_ROUTE_TABLE_100M,
    CENSUS_HOSPITAL_ROUTE_TABLE_1KM,
    CENSUS_HOSPITAL_ROUTE_TABLE_10KM,
    CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_100M,
    CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_1KM,
    CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_10KM,
    ResolutionSuffix
)
from .errors import EmsGermanyError


logger = getLogger(__name__)


async def get_db_pool(dsn: str) -> AsyncConnectionPool:
    """
    Create a database connection pool and make sure the database is ready for import.

    Returns a connection pool instead of a single connection to support concurrent workers.
    """
    # Test database connection first
    try:
        logger.info("Connecting to PostgreSQL database...")
        async with await psycopg.AsyncConnection.connect(dsn):
            pass
        logger.info("Successfully connected to PostgreSQL database!")
    except psycopg.Error as e:
        logger.error(f"Error connecting to PostgreSQL: {e!s}")
        raise EmsGermanyError("Error connecting to PostgreSQL")

    # Create connection pool for concurrent workers
    try:
        pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=2,
            max_size=30,  # must exceed the largest semaphore (25) plus cursor connection overhead
            open=False,
        )
        await pool.open()
        logger.debug("Created database connection pool")
        return pool
    except psycopg.Error as e:
        raise EmsGermanyError(f"Error creating connection pool: {e!s}")


async def create_tables(
    conn: psycopg.AsyncConnection,
    resolution: ResolutionSuffix,
    schema: str = "public"
) -> None:
    """
    Create all tables needed for the application.
    """
    async with conn.cursor() as cursor:
        try:
            logger.info("creating tables")

            match resolution:
                case ResolutionSuffix.m100:
                    await create_route_cost_table(cursor, CENSUS_HOSPITAL_ROUTE_TABLE_100M, schema=schema)
                case ResolutionSuffix.km1:
                    await create_route_cost_table(cursor, CENSUS_HOSPITAL_ROUTE_TABLE_1KM, schema=schema)
                case ResolutionSuffix.km10:
                    await create_route_cost_table(cursor, CENSUS_HOSPITAL_ROUTE_TABLE_10KM, schema=schema)

            logger.info("done creating tables")
        except psycopg.Error as e:
            raise EmsGermanyError(f"Error creating tables: {e!s}")


async def create_tables_from_census(
    conn: psycopg.AsyncConnection,
    resolution: ResolutionSuffix,
    schema: str = "public"
) -> None:
    """
    Create all tables needed for the from-census analysis.
    """
    async with conn.cursor() as cursor:
        try:
            match resolution:
                case ResolutionSuffix.m100:
                    await create_route_cost_table(cursor, CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_100M, schema=schema)
                case ResolutionSuffix.km1:
                    await create_route_cost_table(cursor, CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_1KM, schema=schema)
                case ResolutionSuffix.km10:
                    await create_route_cost_table(cursor, CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_10KM, schema=schema)
        except psycopg.Error as e:
            raise EmsGermanyError(f"Error creating tables: {e!s}")


async def create_route_cost_table(
    cursor: psycopg.AsyncCursor,
    table: str,
    schema: str = "public",
) -> None:
    prepared_sql = psycopg.sql.SQL("""
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            gitter_id VARCHAR(40),
            hospital_id INTEGER NOT NULL,
            total_cost_seconds DOUBLE PRECISION,
            geom GEOMETRY,
            distance DOUBLE PRECISION,
            PRIMARY KEY (gitter_id, hospital_id)
        )
    """).format(
        schema=psycopg.sql.Identifier(schema),
        table=psycopg.sql.Identifier(table)
    )
    await cursor.execute(prepared_sql)

    await cursor.execute(psycopg.sql.SQL("""
        CREATE INDEX IF NOT EXISTS {idx_geom}
        ON {schema}.{table} USING GIST (geom)
    """).format(
        idx_geom=psycopg.sql.Identifier(f"{table}_geom_idx"),
        schema=psycopg.sql.Identifier(schema),
        table=psycopg.sql.Identifier(table),
    ))

    await cursor.execute(psycopg.sql.SQL("""
        CREATE INDEX IF NOT EXISTS {idx_hospital}
        ON {schema}.{table} (hospital_id)
    """).format(
        idx_hospital=psycopg.sql.Identifier(f"{table}_hospital_id_idx"),
        schema=psycopg.sql.Identifier(schema),
        table=psycopg.sql.Identifier(table),
    ))


# ---------------------------------------------------------------------------
# Hex table creation (synchronous, used by report generation)
# ---------------------------------------------------------------------------

def create_hex_tables_sync(conn: psycopg.Connection) -> None:
    """Create hex grid and travel time aggregate tables in ems_germany_analysis schema.

    Grid tables are created once and reused across runs (expensive spatial operation).
    Travel time tables are always recreated to reflect the latest routing data.
    """
    click.echo("  → Creating hex grid tables (skipped if already populated)…")
    with conn.cursor() as cur:
        _create_hex_grid_if_empty(cur, "hex_grid_5km",  5000, "1km")
        _create_hex_grid_if_empty(cur, "hex_grid_1km",  1000, "1km")
        _create_hex_grid_if_empty(cur, "hex_grid_100m",  100, "100m")
    conn.commit()

    click.echo("  → Building hex travel time aggregates…")
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")  # these queries can be slow
        _create_hex_travel_table(
            cur, "hex_grid_5km",  "hex_travel_5km",
            "census_hospital_route_from_census_1km",   "1km",
        )
        _create_hex_travel_table(
            cur, "hex_grid_1km",  "hex_travel_1km",
            "census_hospital_route_from_census_1km",   "1km",
        )
        _create_hex_travel_table(
            cur, "hex_grid_100m", "hex_travel_100m",
            "census_hospital_route_from_census_100m", "100m",
        )
    conn.commit()


def _create_hex_grid_if_empty(
    cur: psycopg.Cursor,
    table_name: str,
    size_m: int,
    census_resolution: str,
) -> None:
    schema = psycopg.sql.Identifier("ems_germany_analysis")
    table  = psycopg.sql.Identifier(table_name)
    census_schema = psycopg.sql.Identifier("zensus")
    census_table  = psycopg.sql.Identifier(f"alter_in_5_altersklassen_{census_resolution}")
    idx    = psycopg.sql.Identifier(f"{table_name}_geom_idx")

    cur.execute(psycopg.sql.SQL("""
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            hex_id SERIAL PRIMARY KEY,
            geom GEOMETRY(Polygon, 3035)
        )
    """).format(schema=schema, table=table))

    cur.execute(psycopg.sql.SQL("""
        CREATE INDEX IF NOT EXISTS {idx}
        ON {schema}.{table} USING GIST(geom)
    """).format(idx=idx, schema=schema, table=table))

    cur.execute(psycopg.sql.SQL(
        "SELECT COUNT(*) FROM {schema}.{table}"
    ).format(schema=schema, table=table))
    row = cur.fetchone()
    count = row[0] if row else 0

    if count == 0:
        click.echo(f"    Populating {table_name} ({size_m}m hexagons)…")
        cur.execute(psycopg.sql.SQL("""
            INSERT INTO {schema}.{table} (geom)
            SELECT geom FROM (
                SELECT (ST_HexagonGrid(
                    {size_m},
                    ST_SetSRID(ST_Envelope(ST_Collect(geom)), 3035)
                )).*
                FROM {census_schema}.{census_table}
            ) AS hexagons
        """).format(
            schema=schema,
            table=table,
            size_m=psycopg.sql.Literal(size_m),
            census_schema=census_schema,
            census_table=census_table,
        ))
        cur.execute(psycopg.sql.SQL(
            "ANALYZE {schema}.{table}"
        ).format(schema=schema, table=table))
    else:
        click.echo(f"    {table_name} already populated ({count:,} rows), skipping.")


def _create_hex_travel_table(
    cur: psycopg.Cursor,
    grid_table: str,
    travel_table: str,
    cost_table: str,
    census_resolution: str,
) -> None:
    click.echo(f"    Building {travel_table}…")

    schema_str = "ems_germany_analysis"

    schema        = psycopg.sql.Identifier(schema_str)
    census_schema = psycopg.sql.Identifier("zensus")
    travel        = psycopg.sql.Identifier(travel_table)
    cost          = psycopg.sql.Identifier(cost_table)
    grid          = psycopg.sql.Identifier(grid_table)
    census_tbl    = psycopg.sql.Identifier(f"alter_in_5_altersklassen_{census_resolution}")
    gitter_col    = psycopg.sql.Identifier(f"gitter_id_{census_resolution}")
    travel_idx    = psycopg.sql.Identifier(f"{travel_table}_geom_idx")

    # if the table exists, we skip populating
    cur.execute(psycopg.sql.SQL("""
        SELECT EXISTS (
            SELECT FROM
                pg_tables
            WHERE
                schemaname = {schema} AND
                tablename = {table}
        )
    """).format(schema=schema_str, table=travel_table))

    if cur.fetchone()[0]:
        click.echo(f"    {travel_table} already exists, skipping.")
        return

    cur.execute(psycopg.sql.SQL("""
        CREATE TABLE {schema}.{travel} AS
        WITH cell_min_times AS (
            SELECT
                r.gitter_id,
                CAST(h.notfall AS float)::int AS hospital_level,
                MIN(r.total_cost_seconds) AS min_secs
            FROM {schema}.{cost} r
            JOIN {schema}.notfall_krankenhauser_geocoded h
                ON r.hospital_id = h.id
            WHERE r.total_cost_seconds IS NOT NULL
            GROUP BY r.gitter_id, CAST(h.notfall AS float)::int
        ),
        cell_data AS (
            SELECT
                c.geom,
                t1.min_secs AS min_secs_l1,
                t2.min_secs AS min_secs_l2,
                t3.min_secs AS min_secs_l3,
                LEAST(t1.min_secs, t2.min_secs, t3.min_secs) AS min_secs_any,
                c.insgesamt_bevoelkerung                AS population,
                COALESCE(c.unter18,       0)            AS pop_under18,
                COALESCE(c.a18bis29,      0)            AS pop_18to29,
                COALESCE(c.a30bis49,      0)            AS pop_30to49,
                COALESCE(c.a50bis64,      0)            AS pop_50to64,
                COALESCE(c.a65undaelter,  0)            AS pop_65plus
            FROM {census_schema}.{census_tbl} c
            LEFT JOIN cell_min_times t1
                ON t1.gitter_id = c.{gitter_col} AND t1.hospital_level = 1
            LEFT JOIN cell_min_times t2
                ON t2.gitter_id = c.{gitter_col} AND t2.hospital_level = 2
            LEFT JOIN cell_min_times t3
                ON t3.gitter_id = c.{gitter_col} AND t3.hospital_level = 3
            WHERE c.insgesamt_bevoelkerung > 0
        )
        SELECT
            h.hex_id,
            ST_Transform(h.geom, 3857)         AS geom,
            AVG(d.min_secs_l1)  / 60.0         AS avg_travel_l1,
            AVG(d.min_secs_l2)  / 60.0         AS avg_travel_l2,
            AVG(d.min_secs_l3)  / 60.0         AS avg_travel_l3,
            AVG(d.min_secs_any) / 60.0         AS avg_travel_any,
            SUM(d.population)                  AS total_population,
            SUM(d.pop_under18)                 AS pop_under18,
            SUM(d.pop_18to29)                  AS pop_18to29,
            SUM(d.pop_30to49)                  AS pop_30to49,
            SUM(d.pop_50to64)                  AS pop_50to64,
            SUM(d.pop_65plus)                  AS pop_65plus
        FROM {schema}.{grid} h
        JOIN cell_data d ON ST_Contains(h.geom, d.geom)
        GROUP BY h.hex_id, h.geom
        HAVING SUM(d.population) > 0
    """).format(
        schema=schema,
        travel=travel,
        cost=cost,
        census_schema=census_schema,
        census_tbl=census_tbl,
        gitter_col=gitter_col,
        grid=grid,
    ))

    cur.execute(psycopg.sql.SQL("""
        CREATE INDEX {travel_idx}
        ON {schema}.{travel} USING GIST(geom)
    """).format(travel_idx=travel_idx, schema=schema, travel=travel))

    cur.execute(psycopg.sql.SQL(
        "ANALYZE {schema}.{travel}"
    ).format(schema=schema, travel=travel))


class Hospital(NamedTuple):
    """
    Represents a record from the configured hospital table.
    """
    id: int
    name: str
    x: float   # EPSG:3035 easting
    y: float   # EPSG:3035 northing
    lon: float  # WGS84 longitude
    lat: float  # WGS84 latitude


async def get_hospitals(
    conn: psycopg.AsyncConnection,
    table: str = "notfall_krankenhauser_geocoded",
    schema: str = "public"
) -> list[Hospital]:
    async with conn.cursor() as cursor:
        try:
            await cursor.execute(psycopg.sql.SQL("""
                SELECT
                    id,
                    name,
                    ST_X(geom),
                    ST_Y(geom),
                    ST_X(ST_Transform(geom, 4326)),
                    ST_Y(ST_Transform(geom, 4326))
                FROM
                    {schema}.{table}
            """).format(
                schema=psycopg.sql.Identifier(schema),
                table=psycopg.sql.Identifier(table)
            ))

            return [Hospital(*row) for row in await cursor.fetchall()]

        except psycopg.Error as e:
            raise EmsGermanyError(f"Error getting hospital ids: {e!s}")
