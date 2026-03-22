import asyncio
import logging
import sys

import click

from .constants import APP_NAME, ResolutionSuffix
from .report import generate as generate_report_html
from .routines import (
    ors_routing_analyze,
    ors_routing_analyze_from_census_point,
    pgrouting_analyze
)


def _setup_logging(log_file: str | None) -> None:
    """Configure root logger with either a file handler or stderr handler."""
    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.WARNING)

    # Allow INFO and above from your own package
    logging.getLogger(APP_NAME).setLevel(logging.INFO)


@click.group()
def emsde():
    pass


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
@click.option(
    "--log-file",
    default=None,
    envvar="EMSDE_LOG_FILE",
    help="Write logs to this file instead of stderr (or set EMSDE_LOG_FILE env var).",
    type=click.Path(dir_okay=False, writable=True),
)
def pgr_analyze(hospital_id, dsn, skip_network, log_file):
    """
    Use pgrouting to generate cost calculations
    """
    _setup_logging(log_file)
    asyncio.run(pgrouting_analyze(hospital_id, dsn, skip_network))


@emsde.command()
@click.option(
    "--dsn",
    required=True,
    envvar="EMSDE_DSN",
    help="PostgreSQL connection string (or set EMSDE_DSN env var)."
)
@click.option(
    "--ors-url",
    required=True,
    envvar="EMSDE_ORS_URL",
    help="URL for open routing service (or set EMSDE_ORS_URL env var)."
)
@click.option(
    "--hospital-table",
    default="notfall_krankenhauser_geocoded",
    envvar="EMSDE_HOSPITAL_TABLE",
    help="Table storing hospital data (or set EMSDE_HOSPITAL_TABLE env var)."
)
@click.option(
    "--log-file",
    default=None,
    envvar="EMSDE_LOG_FILE",
    help="Write logs to this file instead of stderr (or set EMSDE_LOG_FILE env var).",
    type=click.Path(dir_okay=False, writable=True),
)
@click.option(
    "--buffer",
    default=15_000,
    envvar="EMSDE_BUFFER",
    help="Buffer to use for including points around hospital (or set EMSDE_BUFFER env var).",
)
@click.option(
    "--resolution",
    default="100m",
    envvar="EMSDE_RESOLUTION",
    help="Resolution to use when select census points to calculate (or set EMSDE_RESOLUTION env var).",
)
@click.option(
    "--method",
    default="hospital",
    type=click.Choice(["hospital", "census"]),
    envvar="EMSDE_METHOD",
    help="Whether to route from hospitals outward or from census points inward.",
)
def ors_analyze(dsn, ors_url, hospital_table, log_file, buffer, resolution, method):
    """
    Use open routing service to generate cost calculations

    TODO:
        - Add "schema" as an option
    """
    _setup_logging(log_file)
    logger = logging.getLogger(APP_NAME)

    logger.info("Starting import")

    try:
        resolution = ResolutionSuffix(resolution)
    except ValueError as e:
        raise click.ClickException(f"{e!r}")

    if method == "census":
        asyncio.run(ors_routing_analyze_from_census_point(dsn, ors_url, hospital_table, resolution))
    else:
        asyncio.run(ors_routing_analyze(dsn, ors_url, hospital_table, buffer, resolution))

    logger.info("Import Finished")


@emsde.command()
@click.option(
    "--dsn",
    required=True,
    envvar="EMSDE_DSN",
    help="PostgreSQL connection string (or set EMSDE_DSN env var)."
)
@click.option(
    "--output",
    default="accessibility_report",
    type=click.Path(file_okay=False, writable=True),
    help="Output directory (default: accessibility_report).",
)
@click.option(
    "--skip-states",
    is_flag=True,
    help="Skip the federal state spatial join (slow for large datasets).",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Force re-fetch all data from the database, ignoring cached DataFrames.",
)
def report(dsn, output, skip_states, no_cache):
    """
    Generate a hospital accessibility report as a directory containing
    index.html and GeoJSON data files.
    """
    generate_report_html(dsn, output, skip_states, use_cache=not no_cache)


if __name__ == "__main__":
    emsde()
