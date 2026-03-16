import asyncio

import click

from .routines import ors_routing_analyze, pgrouting_analyze


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
def pgr_analyze(hospital_id, dsn, skip_network):
    """
    Use pgrouting to generate cost calculations
    """
    asyncio.run(pgrouting_analyze(hospital_id, dsn, skip_network))


@emsde.command()
@click.argument("hospital_id", type=int)
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
def ors_analyze(hospital_id, dsn, ors_url):
    """
    Use open routing service to generate cost calculations
    """
    asyncio.run(ors_routing_analyze(hospital_id, dsn, ors_url))



if __name__ == "__main__":
    emsde()
