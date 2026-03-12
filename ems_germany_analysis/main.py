import click


@click.group()
def emsde():
    pass


@emsde.command()
@click.option(
    "--dsn",
    required=True,
    envvar="EMSDE_DSN",
    help="PostgreSQL connection string (or set EMSDE_DSN env var)."
)
def analyze():
    print("Hello from ems-germany-analysis!")


if __name__ == "__main__":
    emsde()
