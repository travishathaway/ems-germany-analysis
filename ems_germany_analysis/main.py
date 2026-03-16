import asyncio
from asyncio import Semaphore, CancelledError, create_task
from typing import NamedTuple

import click
import psycopg.sql
import psycopg_pool
from rich.progress import Progress

from .constants import CENSUS_HOSPITAL_ROUTE_TABLE
from .db import get_db_pool, create_tables


@click.group()
def emsde():
    pass


class Hospital(NamedTuple):
    id: int
    name: str
    x: float
    y: float


@emsde.command()
@click.argument("hospital_id", type=int)
@click.option(
    "--dsn",
    required=True,
    envvar="EMSDE_DSN",
    help="PostgreSQL connection string (or set EMSDE_DSN env var)."
)
@click.option(
    "--skip-network",
    is_flag=True,
    envvar="EMSDE_DSN",
    help="Whether to skip generating a routing network."
)
def analyze(hospital_id, dsn, skip_network):
    asyncio.run(_analyze(hospital_id, dsn, skip_network))


async def _analyze(hospital_id, dsn, skip_network):
    pool = await get_db_pool(dsn)

    try:
        async with pool.connection() as conn:
            # Create tables we use to save analysis results
            await create_tables(conn, "ems_germany_analysis")

            async with conn.cursor() as cur:
                # Find a hospital and generate a 20km buffer around it
                await cur.execute("""
                    SELECT
                        id, name, ST_X(geom), ST_Y(geom)
                    FROM
                        ems_germany_analysis.notfall_krankenhauser_geocoded
                    WHERE id = %(hospital_id)s
                """, {"hospital_id": hospital_id})
                hospital = Hospital(*await cur.fetchone())

                # Generate a routing network we can use
                if not skip_network:
                    with Progress() as progress:
                        progress.add_task(f"Creating routing network for {hospital.name} ({hospital.x}, {hospital.y})", total=None)

                        await cur.execute("""
                            CALL osm_germany.routing_prepare_road_network(
                                ST_SetSRID(ST_MakePoint(%(x)s, %(y)s), 3035),
                                20000.0
                            )
                        """, {"x": hospital.x, "y": hospital.y})

                # Find the nearest vertex point to the hospital
                await cur.execute("""
                SELECT v.id AS start_id, v.geom
                    FROM osm_germany.routing_road_vertex v
                    INNER JOIN (SELECT
                        ST_SetSRID(ST_MakePoint(%(x)s, %(y)s), 3035)
                            AS geom
                        ) p ON v.geom <-> p.geom < 20
                    ORDER BY v.geom <-> p.geom
                    LIMIT 1
                """, {"x": hospital.x, "y": hospital.y})

                res = await cur.fetchone()
                if res is None:
                    raise click.ClickException("Could not find a routing network vertex for hospital.")

                hospital_vertex_id = res[0]

                print(hospital_vertex_id)

                # Fetch all the census points and their nearest routing vertex
                await cur.execute("""
                SELECT DISTINCT ON (a.gitter_id_100m)
                    a.gitter_id_100m    AS gitter_id,
                    b.id        		AS vertex_id,
                    ST_Distance(a.geom, b.geom) AS distance
                FROM  zensus.alter_in_5_altersklassen_100m a
                CROSS JOIN LATERAL (
                    SELECT *
                    FROM osm_germany.routing_road_vertex b
                    ORDER BY a.geom <-> b.geom
                    LIMIT 1
                ) b
                WHERE
                    ST_Contains(
                        ST_Buffer(
                            ST_SetSRID(
                                ST_MakePoint(%(x)s, %(y)s),
                            3035),
                        15000),
                    a.geom
                    )
                ORDER BY a.gitter_id_100m, ST_Distance(a.geom, b.geom)
                """, {"x": hospital.x, "y": hospital.y})

                census_rows = await cur.fetchall()

        semaphore = Semaphore(10)
        tasks = [
            create_task(_calculate_and_save_cost(
                pool, semaphore, gitter_id, hospital_vertex_id, hospital_id, vertex_id, distance
            ))
            for gitter_id, vertex_id, distance in census_rows
        ]
        try:
            await asyncio.gather(*tasks)
        except CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print("Cancelled all tasks.")

    finally:
        await pool.close()


async def _calculate_and_save_cost(
    pool: psycopg_pool.AsyncConnectionPool,
    semaphore: Semaphore,
    gitter_id: str,
    hospital_vertex_id: int,
    hospital_id: int,
    vertex_id: int,
    distance: float
) -> None:
    """
    Calculate the routing cost and save it to the database
    """
    async with semaphore, pool.connection() as conn, conn.cursor() as cur:
        try:
            await cur.execute("""
                SELECT
                    segments, total_cost_seconds, geom
                FROM
                    osm_germany.route_motor_travel_time(%(hospital_vertex_id)s, %(vertex_id)s)
            """, {"hospital_vertex_id": hospital_vertex_id, "vertex_id": vertex_id})

            segments, total_cost_seconds, geom = await cur.fetchone()

            if total_cost_seconds is not None and geom is not None:
                prepared_sql = psycopg.sql.SQL("""
                    INSERT INTO {schema}.{table} VALUES (%s, %s, %s, %s, %s)
                """).format(
                    schema=psycopg.sql.Identifier("ems_germany_analysis"),
                    table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE)
                )
                await cur.execute(prepared_sql, (
                    gitter_id, hospital_id, total_cost_seconds, geom, distance
                ))

        except CancelledError:
            # optionally log here
            raise


if __name__ == "__main__":
    emsde()
