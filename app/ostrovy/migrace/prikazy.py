"""Příkazy migrace (analýza 11.1). Fáze 1, krok 1: `nacti` a `report` hotové, `import` a `kontrola`
jsou kostra pro krok 2.

    flask migrace nacti <soubor.xlsm>       načte všechny listy 1:1 do stg.*
    flask migrace report [--davka N]        validační report (duplicity, neznámá pracoviště, …)
    flask migrace import [--nanecisto]      import přes rozhraní C, D, E; --nanecisto na konci vrátí zpět
    flask migrace kontrola                  kontrolní součty staging = cíl

Doplňovací tabulku firma nemá (rozhodnutí 3. 11., docs/migrace-xlsm.md sekce 4), proto příkazy
`doplnovaci-xlsx` a `nacti-doplneni` zanikají – import vezme jen to, co v sešitu je.
"""
import click
from flask.cli import AppGroup

from app.platforma.chyby import AppError

from . import sluzby

migrace_cli = AppGroup("migrace", help="Migrace z XLSM (ostrov H).")


def _zatim() -> None:
    raise click.ClickException("Ostrov H – zatím neimplementováno (krok 2).")


def _volej(sluzba, *args):
    """Zavolá službu; AppError je chyba příkazu, takže se nevypisuje traceback."""
    try:
        return sluzba(*args)
    except AppError as chyba:
        raise click.ClickException(chyba.zprava or chyba.kod) from chyba


@migrace_cli.command("nacti")
@click.argument("soubor", type=click.Path(exists=True, dir_okay=False))
def nacti(soubor: str) -> None:
    """Načte listy sešitu 1:1 do schématu stg – vždy jako novou dávku."""
    davka_id, po_listech = _volej(sluzby.nacti, soubor)
    click.echo(f"Dávka {davka_id}: {sum(po_listech.values())} buněk.")
    for nazev_listu, pocet in po_listech.items():
        click.echo(f"  {nazev_listu}: {pocet} buněk")


@migrace_cli.command("report")
@click.option("--davka", type=int, default=None, help="Dávka z `nacti`; bez volby se vezme nejnovější.")
def report(davka: int | None) -> None:
    """Validační report z buněk dávky (docs/migrace-xlsm.md, sekce 2 až 4)."""
    click.echo(_volej(sluzby.report, davka))


@migrace_cli.command("import")
@click.option("--nanecisto", is_flag=True, help="Provede import a na konci ho vrátí zpět.")
def import_(nanecisto: bool) -> None:
    _zatim()


@migrace_cli.command("kontrola")
def kontrola() -> None:
    _zatim()
