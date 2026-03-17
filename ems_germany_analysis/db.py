"""
Module for various functions and classes to help with database connections.
"""
from logging import getLogger
from typing import NamedTuple

import psycopg
import psycopg.sql
from psycopg_pool import AsyncConnectionPool

from .constants import CENSUS_HOSPITAL_ROUTE_TABLE
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
            max_size=10,
            open=False,
        )
        await pool.open()
        logger.debug("Created database connection pool")
        return pool
    except psycopg.Error as e:
        raise EmsGermanyError(f"Error creating connection pool: {e!s}")


async def create_tables(conn: psycopg.AsyncConnection, schema: str = "public") -> None:
    """
    Create all tables needed for the application.
    """
    async with conn.cursor() as cursor:
        try:
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
                table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE)
            )
            await cursor.execute(prepared_sql)

            await cursor.execute(psycopg.sql.SQL("""
                CREATE INDEX IF NOT EXISTS {idx_geom}
                ON {schema}.{table} USING GIST (geom)
            """).format(
                idx_geom=psycopg.sql.Identifier(f"{CENSUS_HOSPITAL_ROUTE_TABLE}_geom_idx"),
                schema=psycopg.sql.Identifier(schema),
                table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE),
            ))

            await cursor.execute(psycopg.sql.SQL("""
                CREATE INDEX IF NOT EXISTS {idx_hospital}
                ON {schema}.{table} (hospital_id)
            """).format(
                idx_hospital=psycopg.sql.Identifier(f"{CENSUS_HOSPITAL_ROUTE_TABLE}_hospital_id_idx"),
                schema=psycopg.sql.Identifier(schema),
                table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE),
            ))
        except psycopg.Error as e:
            raise EmsGermanyError(f"Error creating tables: {e!s}")


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
