import asyncio
import json
import logging
from asyncio import Semaphore, CancelledError, create_task

import click
import httpx
import psycopg.sql
import psycopg_pool
from rich.progress import Progress

from .constants import APP_NAME, CENSUS_HOSPITAL_ROUTE_TABLE
from .db import get_db_pool, create_tables, get_hospitals, Hospital
from .errors import EmsGermanyError

logger = logging.getLogger(APP_NAME)


async def pgrouting_analyze(hospital_id, dsn, skip_network):
    pool = await get_db_pool(dsn)

    try:
        async with pool.connection() as conn:
            # Create tables we use to save analysis results
            await create_tables(conn, "ems_germany_analysis")

            async with conn.cursor() as cur:
                # Find a hospital and generate a 20km buffer around it
                await cur.execute("""
                    SELECT
                        id, name,
                        ST_X(geom), ST_Y(geom),
                        ST_X(ST_Transform(geom, 4326)),
                        ST_Y(ST_Transform(geom, 4326))
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

                logger.debug("Hospital vertex id: %s", hospital_vertex_id)

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
        with Progress() as progress:
            task_id = progress.add_task(
                f"Routing {len(census_rows)} points for {hospital.name} (pgRouting)",
                total=len(census_rows),
            )
            tasks = [
                create_task(_calculate_and_save_cost(
                    pool, semaphore, progress, task_id,
                    gitter_id, hospital_vertex_id, hospital_id, vertex_id, distance
                ))
                for gitter_id, vertex_id, distance in census_rows
            ]
            try:
                await asyncio.gather(*tasks)
            except CancelledError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                logger.error("Cancelled all tasks.")

    finally:
        await pool.close()


async def _calculate_and_save_cost(
        pool: psycopg_pool.AsyncConnectionPool,
        semaphore: Semaphore,
        progress: Progress,
        task_id: int,
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
                    INSERT INTO {schema}.{table}
                        (gitter_id, hospital_id, total_cost_seconds, geom, distance)
                    VALUES (%s, %s, %s, %s, %s)
                """).format(
                    schema=psycopg.sql.Identifier("ems_germany_analysis"),
                    table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE)
                )
                await cur.execute(prepared_sql, (
                    gitter_id, hospital_id, total_cost_seconds, geom, distance
                ))

        except CancelledError:
            raise
        except Exception:
            logger.exception(
                "Error calculating cost for gitter_id=%s hospital_id=%s vertex_id=%s",
                gitter_id, hospital_id, vertex_id
            )
        finally:
            progress.advance(task_id)


async def ors_routing_analyze(
    dsn: str,
    ors_url: str,
    hospital_table: str,
    buffer: int
) -> None:
    """Run ORS-based routing analysis for a single hospital."""
    pool = await get_db_pool(dsn)

    try:
        async with pool.connection() as conn:
            await create_tables(conn, "ems_germany_analysis")

            async with conn.cursor() as cur:
                hospitals = await get_hospitals(conn, table=hospital_table, schema="ems_germany_analysis")

                if not hospitals:
                    raise EmsGermanyError(f"No hospitals found.")

        for hospital in hospitals:
            async with pool.connection() as conn, conn.cursor() as cur:
                prepared_sql = psycopg.sql.SQL("""
                    SELECT
                        p.gitter_id_100m,
                        ST_Y(ST_Transform(p.geom, 4326)) AS lat,
                        ST_X(ST_Transform(p.geom, 4326)) AS lon
                    FROM
                        zensus.alter_in_5_altersklassen_100m p
                    LEFT JOIN
                        {schema}.{table} r
                    ON
                        p.gitter_id_100m = r.gitter_id
                    WHERE
                        r.gitter_id is null
                    AND 
                        ST_Contains(
                            ST_Buffer(ST_SetSRID(ST_MakePoint(%(x)s, %(y)s), 3035), %(buffer)s),
                            p.geom
                        )
                """).format(
                    schema=psycopg.sql.Identifier("ems_germany_analysis"),
                    table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE)
                )
                await cur.execute(
                    prepared_sql,
                    {"x": hospital.x, "y": hospital.y, "buffer": buffer}
                )
                census_rows = await cur.fetchall()

            await _process_multiple_ors(pool, census_rows, hospital, ors_url)

    finally:
        await pool.close()


async def _process_multiple_ors(
    pool: psycopg_pool.AsyncConnectionPool,
    census_rows: list,
    hospital: Hospital,
    ors_url: str
) -> None:
    """
    Processes census_rows to query OpenRoutingService and import it into the database
    """
    semaphore = Semaphore(10)

    async with httpx.AsyncClient() as client:
        with Progress() as progress:
            task_id = progress.add_task(
                f"Routing {len(census_rows)} points for {hospital.name} (ORS)",
                total=len(census_rows),
            )
            tasks = [
                create_task(_ors_calculate_and_save(
                    pool, client, semaphore, progress, task_id,
                    gitter_id, hospital.id,
                    hospital.lat, hospital.lon,
                    census_lat, census_lon,
                    ors_url,
                ))
                for gitter_id, census_lat, census_lon in census_rows
            ]
            try:
                await asyncio.gather(*tasks)
            except CancelledError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                logger.error("Cancelled all tasks.")


async def _ors_calculate_and_save(
        pool: psycopg_pool.AsyncConnectionPool,
        client: httpx.AsyncClient,
        semaphore: Semaphore,
        progress: Progress,
        task_id: int,
        gitter_id: str,
        hospital_id: int,
        hospital_lat: float,
        hospital_lon: float,
        census_lat: float,
        census_lon: float,
        ors_url: str,
) -> None:
    """Call ORS directions API and persist the result."""
    async with semaphore:
        try:
            response = await client.post(
                f"{ors_url}/v2/directions/driving-car/geojson",
                json={"coordinates": [[hospital_lon, hospital_lat], [census_lon, census_lat]]},
            )
            if response.status_code != 200:
                logger.error(
                    "ORS request failed for gitter_id=%s hospital_id=%s: HTTP %s - %s",
                    gitter_id, hospital_id, response.status_code, response.text
                )
                return

            data = response.json()
            feature = data["features"][0]
            total_cost_seconds = feature["properties"]["summary"]["duration"]
            geometry_json = json.dumps(feature["geometry"])

            async with pool.connection() as conn, conn.cursor() as cur:
                prepared_sql = psycopg.sql.SQL("""
                    INSERT INTO {schema}.{table}
                        (gitter_id, hospital_id, total_cost_seconds, geom, distance)
                    VALUES (%s, %s, %s, ST_Transform(ST_GeomFromGeoJSON(%s), 3035), %s)
                    ON CONFLICT (gitter_id, hospital_id) DO UPDATE SET
                        total_cost_seconds = EXCLUDED.total_cost_seconds,
                        geom = EXCLUDED.geom
                """).format(
                    schema=psycopg.sql.Identifier("ems_germany_analysis"),
                    table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE),
                )
                await cur.execute(prepared_sql, (
                    gitter_id, hospital_id, total_cost_seconds, geometry_json, None
                ))
        except CancelledError:
            raise
        except Exception:
            logger.exception(
                "Error processing ORS route for gitter_id=%s hospital_id=%s",
                gitter_id, hospital_id
            )
        finally:
            progress.advance(task_id)
