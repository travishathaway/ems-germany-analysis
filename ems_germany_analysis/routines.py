import asyncio
import json
import logging
from asyncio import Semaphore, CancelledError, create_task

import click
import httpx
import psycopg.sql
import psycopg_pool
from rich.progress import Progress

from .constants import (
    APP_NAME,
    CENSUS_HOSPITAL_ROUTE_TABLE_100M,
    CENSUS_HOSPITAL_ROUTE_TABLE_1KM,
    CENSUS_HOSPITAL_ROUTE_TABLE_10KM,
    CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_100M,
    CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_1KM,
    CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_10KM,
    ResolutionSuffix
)
from .db import get_db_pool, create_tables, create_tables_from_census, get_hospitals, Hospital
from .errors import EmsGermanyError

logger = logging.getLogger(APP_NAME)

# Composed once per cost_table value; reused across every row insert.
_INSERT_ROUTE_SQL_TEMPLATE = psycopg.sql.SQL("""
    INSERT INTO {schema}.{table}
        (gitter_id, hospital_id, total_cost_seconds, geom, distance)
    VALUES (%s, %s, %s, ST_Transform(ST_GeomFromGeoJSON(%s), 3035), %s)
    ON CONFLICT (gitter_id, hospital_id) DO UPDATE SET
        total_cost_seconds = EXCLUDED.total_cost_seconds,
        geom = EXCLUDED.geom
""")

# Inserted when ORS cannot calculate a route. DO NOTHING on conflict ensures a
# previously successful result is never overwritten by a sentinel.
_INSERT_SENTINEL_SQL_TEMPLATE = psycopg.sql.SQL("""
    INSERT INTO {schema}.{table}
        (gitter_id, hospital_id, total_cost_seconds, geom, distance)
    VALUES (%s, %s, NULL, NULL, NULL)
    ON CONFLICT (gitter_id, hospital_id) DO NOTHING
""")


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
                    table=psycopg.sql.Identifier(CENSUS_HOSPITAL_ROUTE_TABLE_100M)
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
    buffer: int,
    resolution: ResolutionSuffix
) -> None:
    """Run ORS-based routing analysis for a single hospital."""
    pool = await get_db_pool(dsn)

    match resolution:
        case ResolutionSuffix.m100:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_100M
        case ResolutionSuffix.km1:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_1KM
        case ResolutionSuffix.km10:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_10KM

    try:
        async with pool.connection() as conn:
            await create_tables(conn, resolution, schema="ems_germany_analysis")

            async with conn.cursor() as cur:
                hospitals = await get_hospitals(conn, table=hospital_table, schema="ems_germany_analysis")

                if not hospitals:
                    raise EmsGermanyError(f"No hospitals found.")

        for hospital in hospitals:
            async with pool.connection() as conn, conn.cursor() as cur:
                prepared_sql = psycopg.sql.SQL("""
                    SELECT
                        p.{gitter_id},
                        ST_Y(ST_Transform(p.geom, 4326)) AS lat,
                        ST_X(ST_Transform(p.geom, 4326)) AS lon
                    FROM
                        zensus.{census_table} p
                    LEFT JOIN
                        {schema}.{table} r
                    ON
                        p.{gitter_id} = r.gitter_id
                        AND r.hospital_id = %(hospital_id)s
                    WHERE
                        r.gitter_id is null
                    AND 
                        ST_Contains(
                            ST_Buffer(ST_SetSRID(ST_MakePoint(%(x)s, %(y)s), 3035), %(buffer)s),
                            p.geom
                        )
                """).format(
                    gitter_id=psycopg.sql.Identifier(f"gitter_id_{resolution}"),
                    census_table=psycopg.sql.Identifier(f"alter_in_5_altersklassen_{resolution}"),
                    schema=psycopg.sql.Identifier("ems_germany_analysis"),
                    table=psycopg.sql.Identifier(cost_table)
                )
                await cur.execute(
                    prepared_sql,
                    {"x": hospital.x, "y": hospital.y, "buffer": buffer, "hospital_id": hospital.id}
                )
                census_rows = await cur.fetchall()

            await _process_multiple_ors(pool, census_rows, hospital, ors_url, cost_table)

    finally:
        await pool.close()


async def _process_multiple_ors(
    pool: psycopg_pool.AsyncConnectionPool,
    census_rows: list,
    hospital: Hospital,
    ors_url: str,
    cost_table: str
) -> None:
    """
    Processes census_rows to query OpenRoutingService and import it into the database
    """
    semaphore = Semaphore(10)

    async with httpx.AsyncClient() as client:
        with Progress() as progress:
            task_id = progress.add_task(
                f"Routing {len(census_rows)} points for {hospital.name} ({hospital.id})",
                total=len(census_rows),
            )
            tasks = [
                # TODO: This needs to be broken up into a NamedTuple because there are too
                #       many arguments to the function!
                create_task(_ors_calculate_and_save(
                    pool, client, semaphore, progress, task_id,
                    gitter_id, hospital.id,
                    hospital.lat, hospital.lon,
                    census_lat, census_lon,
                    ors_url, cost_table
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
    cost_table: str
) -> None:
    """Call ORS directions API and persist the result."""
    async with semaphore:
        try:
            response = await client.post(
                f"{ors_url}/v2/directions/driving-car/geojson",
                json={
                    "coordinates": [[hospital_lon, hospital_lat], [census_lon, census_lat]],
                },
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
                    table=psycopg.sql.Identifier(cost_table),
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


async def ors_routing_analyze_from_census_point(
    dsn: str,
    ors_url: str,
    hospital_table: str,
    resolution: ResolutionSuffix,
    page_size: int = 100_000,
) -> None:
    """Run ORS-based routing analysis starting from each census point."""
    pool = await get_db_pool(dsn)

    match resolution:
        case ResolutionSuffix.m100:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_100M
        case ResolutionSuffix.km1:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_1KM
        case ResolutionSuffix.km10:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_10KM

    def _build_base_sql() -> psycopg.sql.Composed:
        return psycopg.sql.SQL("""
            SELECT
                p.{gitter_id},
                ST_Y(ST_Transform(p.geom, 4326)) AS census_lat,
                ST_X(ST_Transform(p.geom, 4326)) AS census_lon,
                h.id    AS hospital_id,
                ST_Y(ST_Transform(h.geom, 4326)) AS hospital_lat,
                ST_X(ST_Transform(h.geom, 4326)) AS hospital_lon
            FROM
                zensus.{census_table} p
            CROSS JOIN LATERAL (
                (SELECT id, geom FROM {schema}.{hospital_table} WHERE notfall = '1.0' ORDER BY p.geom <-> geom LIMIT 2)
                UNION ALL
                (SELECT id, geom FROM {schema}.{hospital_table} WHERE notfall = '2.0' ORDER BY p.geom <-> geom LIMIT 2)
                UNION ALL
                (SELECT id, geom FROM {schema}.{hospital_table} WHERE notfall = '3.0' ORDER BY p.geom <-> geom LIMIT 2)
            ) h
            WHERE NOT EXISTS (
                SELECT 1 FROM {schema}.{cost_table} r
                WHERE r.gitter_id = p.{gitter_id}
            )
        """).format(
            gitter_id=psycopg.sql.Identifier(f"gitter_id_{resolution}"),
            census_table=psycopg.sql.Identifier(f"alter_in_5_altersklassen_{resolution}"),
            schema=psycopg.sql.Identifier("ems_germany_analysis"),
            hospital_table=psycopg.sql.Identifier(hospital_table),
            cost_table=psycopg.sql.Identifier(cost_table),
        )

    # Pre-compose once; passed through to every row insert instead of rebuilding per row.
    insert_sql = _INSERT_ROUTE_SQL_TEMPLATE.format(
        schema=psycopg.sql.Identifier("ems_germany_analysis"),
        table=psycopg.sql.Identifier(cost_table),
    )
    sentinel_sql = _INSERT_SENTINEL_SQL_TEMPLATE.format(
        schema=psycopg.sql.Identifier("ems_germany_analysis"),
        table=psycopg.sql.Identifier(cost_table),
    )

    try:
        async with pool.connection() as conn:
            await create_tables_from_census(conn, resolution, schema="ems_germany_analysis")

            async with conn.cursor() as cur:
                # Cheaper count: 2 routes to 3 hospitals per census point not yet in the cost table,
                # avoiding the expensive CROSS JOIN LATERAL used by _build_base_sql().
                count_sql = psycopg.sql.SQL("""
                    SELECT COUNT(*) * 2 * 3
                    FROM zensus.{census_table} p
                    WHERE NOT EXISTS (
                        SELECT 1 FROM {schema}.{cost_table} r
                        WHERE r.gitter_id = p.{gitter_id}
                    )
                """).format(
                    census_table=psycopg.sql.Identifier(f"alter_in_5_altersklassen_{resolution}"),
                    schema=psycopg.sql.Identifier("ems_germany_analysis"),
                    cost_table=psycopg.sql.Identifier(cost_table),
                    gitter_id=psycopg.sql.Identifier(f"gitter_id_{resolution}"),
                )
                await cur.execute(count_sql)
                (total,) = await cur.fetchone()

        with Progress() as progress:
            task_id = progress.add_task(
                f"Routing {total} census-hospital pairs (ORS)",
                total=total,
            )

            # Single client for the entire run — reuses HTTP connections across all pages.
            async with httpx.AsyncClient() as client:
                # Use a server-side cursor so the query executes once and results are
                # streamed in pages, avoiding the O(n²) cost of re-running the full
                # query (with its expensive LATERAL join) on every iteration.
                async with pool.connection() as conn:
                    async with conn.cursor(name="census_pairs_cursor") as cur:
                        await cur.execute(_build_base_sql())
                        while True:
                            rows = await cur.fetchmany(page_size)
                            if not rows:
                                break
                            await _process_multiple_ors_from_census(
                                pool, client, rows, ors_url, insert_sql, sentinel_sql, progress, task_id
                            )

    finally:
        await pool.close()


async def _process_multiple_ors_from_census(
    pool: psycopg_pool.AsyncConnectionPool,
    client: httpx.AsyncClient,
    rows: list,
    ors_url: str,
    insert_sql: psycopg.sql.Composed,
    sentinel_sql: psycopg.sql.Composed,
    progress: Progress,
    task_id: int,
) -> None:
    """Process census→hospital pairs through ORS and persist results."""
    semaphore = Semaphore(25)

    tasks = [
        create_task(_ors_calculate_and_save_from_census(
            pool, client, semaphore, progress, task_id,
            gitter_id, hospital_id,
            census_lat, census_lon,
            hospital_lat, hospital_lon,
            ors_url, insert_sql, sentinel_sql
        ))
        for gitter_id, census_lat, census_lon, hospital_id, hospital_lat, hospital_lon in rows
    ]
    try:
        await asyncio.gather(*tasks)
    except CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.error("Cancelled all tasks.")


async def _ors_calculate_and_save_from_census(
    pool: psycopg_pool.AsyncConnectionPool,
    client: httpx.AsyncClient,
    semaphore: Semaphore,
    progress: Progress,
    task_id: int,
    gitter_id: str,
    hospital_id: int,
    census_lat: float,
    census_lon: float,
    hospital_lat: float,
    hospital_lon: float,
    ors_url: str,
    insert_sql: psycopg.sql.Composed,
    sentinel_sql: psycopg.sql.Composed,
) -> None:
    """Call ORS directions API (census→hospital) and persist the result."""
    async with semaphore:
        try:
            response = await client.post(
                f"{ors_url}/v2/directions/driving-car/geojson",
                json={
                    "coordinates": [[census_lon, census_lat], [hospital_lon, hospital_lat]],
                },
            )
            if response.status_code != 200:
                logger.error(
                    "ORS request failed for gitter_id=%s hospital_id=%s: HTTP %s - %s",
                    gitter_id, hospital_id, response.status_code, response.text
                )
                async with pool.connection() as conn, conn.cursor() as cur:
                    await cur.execute(sentinel_sql, (gitter_id, hospital_id))
                return

            data = response.json()
            feature = data["features"][0]
            total_cost_seconds = feature["properties"]["summary"]["duration"]
            geometry_json = json.dumps(feature["geometry"])

            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(insert_sql, (
                    gitter_id, hospital_id, total_cost_seconds, geometry_json, None
                ))
        except CancelledError:
            raise
        except Exception:
            logger.exception(
                "Error processing ORS route for gitter_id=%s hospital_id=%s",
                gitter_id, hospital_id
            )
            try:
                async with pool.connection() as conn, conn.cursor() as cur:
                    await cur.execute(sentinel_sql, (gitter_id, hospital_id))
            except Exception:
                logger.exception(
                    "Failed to insert sentinel for gitter_id=%s hospital_id=%s",
                    gitter_id, hospital_id
                )
        finally:
            progress.advance(task_id)


async def ors_routing_cleanup(
    dsn: str,
    ors_url: str,
    hospital_table: str,
    resolution: ResolutionSuffix,
    page_size: int = 100_000,
) -> None:
    """Re-route census-hospital pairs missing from a prior run.

    Census points that are fully absent from the cost table are left to the main
    ors_analyze run. This only processes points that have *some* entries but
    fewer than 6, i.e. partial failures. Pairs that ORS cannot route are
    recorded as NULL sentinels so they are never retried again.
    """
    pool = await get_db_pool(dsn)

    match resolution:
        case ResolutionSuffix.m100:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_100M
        case ResolutionSuffix.km1:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_1KM
        case ResolutionSuffix.km10:
            cost_table = CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_10KM

    def _build_cleanup_sql() -> psycopg.sql.Composed:
        return psycopg.sql.SQL("""
            SELECT
                p.{gitter_id},
                ST_Y(ST_Transform(p.geom, 4326)) AS census_lat,
                ST_X(ST_Transform(p.geom, 4326)) AS census_lon,
                h.id    AS hospital_id,
                ST_Y(ST_Transform(h.geom, 4326)) AS hospital_lat,
                ST_X(ST_Transform(h.geom, 4326)) AS hospital_lon
            FROM zensus.{census_table} p
            CROSS JOIN LATERAL (
                (SELECT id, geom FROM {schema}.{hospital_table} WHERE notfall = '1.0' ORDER BY p.geom <-> geom LIMIT 2)
                UNION ALL
                (SELECT id, geom FROM {schema}.{hospital_table} WHERE notfall = '2.0' ORDER BY p.geom <-> geom LIMIT 2)
                UNION ALL
                (SELECT id, geom FROM {schema}.{hospital_table} WHERE notfall = '3.0' ORDER BY p.geom <-> geom LIMIT 2)
            ) h
            LEFT JOIN {schema}.{cost_table} r ON p.{gitter_id} = r.gitter_id AND h.id = r.hospital_id
            WHERE r.gitter_id IS NULL
            AND p.{gitter_id} IN (
                SELECT gitter_id FROM {schema}.{cost_table}
                GROUP BY gitter_id HAVING COUNT(*) < 6
            )
            ORDER BY p.{gitter_id}, h.id
        """).format(
            gitter_id=psycopg.sql.Identifier(f"gitter_id_{resolution}"),
            census_table=psycopg.sql.Identifier(f"alter_in_5_altersklassen_{resolution}"),
            schema=psycopg.sql.Identifier("ems_germany_analysis"),
            hospital_table=psycopg.sql.Identifier(hospital_table),
            cost_table=psycopg.sql.Identifier(cost_table),
        )

    insert_sql = _INSERT_ROUTE_SQL_TEMPLATE.format(
        schema=psycopg.sql.Identifier("ems_germany_analysis"),
        table=psycopg.sql.Identifier(cost_table),
    )
    sentinel_sql = _INSERT_SENTINEL_SQL_TEMPLATE.format(
        schema=psycopg.sql.Identifier("ems_germany_analysis"),
        table=psycopg.sql.Identifier(cost_table),
    )

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Sum of missing routes across all partially-processed census points.
                count_sql = psycopg.sql.SQL("""
                    SELECT COALESCE(SUM(6 - cnt), 0)
                    FROM (
                        SELECT COUNT(*) AS cnt
                        FROM {schema}.{cost_table}
                        GROUP BY gitter_id
                        HAVING COUNT(*) < 6
                    ) sub
                """).format(
                    schema=psycopg.sql.Identifier("ems_germany_analysis"),
                    cost_table=psycopg.sql.Identifier(cost_table),
                )
                await cur.execute(count_sql)
                (total,) = await cur.fetchone()

        if total == 0:
            click.echo("No incomplete records found. Nothing to clean up.")
            return

        with Progress() as progress:
            task_id = progress.add_task(
                f"Cleaning up {total} missing census-hospital pairs (ORS)",
                total=total,
            )

            async with httpx.AsyncClient() as client:
                async with pool.connection() as conn:
                    async with conn.cursor(name="cleanup_cursor") as cur:
                        await cur.execute(_build_cleanup_sql())
                        while True:
                            rows = await cur.fetchmany(page_size)
                            if not rows:
                                break
                            await _process_multiple_ors_from_census(
                                pool, client, rows, ors_url, insert_sql, sentinel_sql, progress, task_id
                            )

    finally:
        await pool.close()
