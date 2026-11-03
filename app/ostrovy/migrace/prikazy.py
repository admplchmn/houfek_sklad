"""Příkazy migrace (analýza 11.1). Fáze 0: jen kostra příkazů.

    flask migrace nacti <soubor.xlsm>       načte všechny listy 1:1 do stg.*
    flask migrace report                    validační report (duplicity, neznámá pracoviště, …)
    flask migrace doplnovaci-xlsx           vygeneruje XLSX se sloupci, které XLSM nemá
    flask migrace nacti-doplneni <xlsx>     načte vyplněné doplnění
    flask migrace import [--nanecisto]      import přes rozhraní C, D, E; --nanecisto na konci vrátí zpět
    flask migrace kontrola                  kontrolní součty staging = cíl
"""
import click
from flask.cli import AppGroup

migrace_cli = AppGroup("migrace", help="Migrace z XLSM (ostrov H).")


def _zatim() -> None:
    raise click.ClickException("Ostrov H – zatím neimplementováno (fáze 1).")


@migrace_cli.command("nacti")
@click.argument("soubor", type=click.Path(exists=True, dir_okay=False))
def nacti(soubor: str) -> None:
    _zatim()


@migrace_cli.command("report")
def report() -> None:
    _zatim()


@migrace_cli.command("doplnovaci-xlsx")
def doplnovaci_xlsx() -> None:
    _zatim()


@migrace_cli.command("nacti-doplneni")
@click.argument("soubor", type=click.Path(exists=True, dir_okay=False))
def nacti_doplneni(soubor: str) -> None:
    _zatim()


@migrace_cli.command("import")
@click.option("--nanecisto", is_flag=True, help="Provede import a na konci ho vrátí zpět.")
def import_(nanecisto: bool) -> None:
    _zatim()


@migrace_cli.command("kontrola")
def kontrola() -> None:
    _zatim()
