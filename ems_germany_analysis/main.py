import asyncio
import logging
import sys

import click

from .constants import (
    APP_NAME,
    ResolutionSuffix,
    CENSUS_HOSPITAL_ROUTE_TABLE_100M,
    CENSUS_HOSPITAL_ROUTE_TABLE_1KM,
    CENSUS_HOSPITAL_ROUTE_TABLE_10KM
)
from .routines import ors_routing_analyze, pgrouting_analyze


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
def ors_analyze(dsn, ors_url, hospital_table, log_file, buffer, resolution):
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

    asyncio.run(
        ors_routing_analyze(
            dsn, ors_url, hospital_table, buffer, resolution
        )
    )

    logger.info("Import Finished")


if __name__ == "__main__":
    emsde()
