"""
Module for various functions and classes to help with database connections.
"""
from logging import getLogger

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
