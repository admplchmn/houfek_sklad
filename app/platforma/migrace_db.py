"""Migrace schématu: číslované T-SQL skripty v sql/migrace/ (pravidlo P11).

    flask db stav          – které skripty jsou provedené
    flask db upgrade       – provede chybějící skripty, každý v jedné transakci
    flask db oznac 001_…   – označí skript jako provedený (schéma založené ručně přes sqlcmd)

Provedený skript se už nikdy nemění; oprava = nový skript s vyšším číslem.
Migrace běží pod účtem pro migrace (HOUFEK_DB_UZIVATEL_MIGRACE, práva db_owner);
aplikace sama běží pod účtem s rolí app_sklad. Rozhodnutí: docs/adr/0003.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click
from flask.cli import AppGroup

from .db import spojeni_pro_skript

ADRESAR = Path(__file__).resolve().parents[2] / "sql" / "migrace"

_TABULKA_MIGRACI = """
IF OBJECT_ID(N'dbo.MigraceSchema', N'U') IS NULL
CREATE TABLE dbo.MigraceSchema (
    Soubor    NVARCHAR(200) NOT NULL CONSTRAINT PK_MigraceSchema PRIMARY KEY,
    Otisk     CHAR(64)      NOT NULL,
    Provedeno DATETIME2     NOT NULL CONSTRAINT DF_MigraceSchema_Provedeno DEFAULT (SYSUTCDATETIME())
);"""


def rozdel_na_davky(text: str) -> list[str]:
    """Rozdělí skript podle řádků GO (mimo blokové komentáře), jako sqlcmd."""
    davky: list[str] = []
    aktualni: list[str] = []
    v_komentari = False
    for radek in text.splitlines():
        if not v_komentari and re.fullmatch(r"\s*GO\s*(--.*)?", radek, flags=re.IGNORECASE):
            if "".join(aktualni).strip():
                davky.append("\n".join(aktualni))
            aktualni = []
            continue
        aktualni.append(radek)
        bez_retezcu = re.sub(r"'[^']*'", "", radek)
        bez_radkovych = bez_retezcu.split("--")[0] if not v_komentari else bez_retezcu
        for znacka in re.findall(r"/\*|\*/", bez_radkovych):
            v_komentari = znacka == "/*"
    if "".join(aktualni).strip():
        davky.append("\n".join(aktualni))
    return davky


ZAMEK_UPGRADE = "houfek_db_upgrade"
_ZAMKNI = ("SET NOCOUNT ON; DECLARE @r INT; EXEC @r = sp_getapplock @Resource = ?, @LockMode = 'Exclusive', "
           "@LockOwner = 'Session', @LockTimeout = 0; SELECT @r AS Vysledek;")
_ODEMKNI = ("SET NOCOUNT ON; DECLARE @r INT; EXEC @r = sp_releaseapplock @Resource = ?, @LockOwner = 'Session'; "
            "SELECT @r AS Vysledek;")


@contextmanager
def zamek_upgrade() -> Iterator[None]:
    """Jen jeden `flask db upgrade` najednou (TD-15): aplikační zámek SQL Serveru na relaci.

    Zámek drží samostatné spojení po celou dobu upgradu; skripty běží ve vlastních spojeních.
    Druhý souběžný upgrade nečeká a hned skončí srozumitelnou chybou (nic nezapíše).
    sqlite (testy) zámky aplikace nemá – tam se nic nezamyká.
    """
    with spojeni_pro_skript(migrace=True) as spoj:
        if spoj.dialekt != "mssql":
            yield
            return
        vysledek = spoj.hodnota(_ZAMKNI, ZAMEK_UPGRADE)
        if vysledek is None or int(vysledek) < 0:
            raise click.ClickException("Jiný `flask db upgrade` právě běží. Počkejte, až doběhne, a spusťte "
                                       "příkaz znovu – nic se nezapsalo.")
        try:
            yield
        finally:
            spoj.hodnota(_ODEMKNI, ZAMEK_UPGRADE)


def _skripty() -> list[Path]:
    return sorted(p for p in ADRESAR.glob("*.sql") if re.match(r"\d{3}_", p.name))


def _otisk(soubor: Path) -> str:
    return hashlib.sha256(soubor.read_bytes()).hexdigest()


db_cli = AppGroup("db", help="Migrace schématu databáze.")


@db_cli.command("stav")
def stav() -> None:
    with spojeni_pro_skript(migrace=True) as spoj:
        spoj.proved(_TABULKA_MIGRACI)
        provedene = {r["Soubor"]: r["Otisk"] for r in spoj.dotaz("SELECT Soubor, Otisk FROM dbo.MigraceSchema")}
    for skript in _skripty():
        otisk = provedene.get(skript.name)
        if otisk is None:
            click.echo(f"  čeká      {skript.name}")
        elif otisk != _otisk(skript):
            click.echo(f"  ZMĚNĚNO!  {skript.name}  (provedený skript se nesmí měnit)")
        else:
            click.echo(f"  provedeno {skript.name}")


@db_cli.command("upgrade")
def upgrade() -> None:
    with zamek_upgrade():
        _proved_chybejici()


def _proved_chybejici() -> None:
    with spojeni_pro_skript(migrace=True) as spoj:
        spoj.proved(_TABULKA_MIGRACI)
    with spojeni_pro_skript(migrace=True) as spoj:
        provedene = {r["Soubor"]: r["Otisk"] for r in spoj.dotaz("SELECT Soubor, Otisk FROM dbo.MigraceSchema")}
    for skript in _skripty():
        if skript.name in provedene:
            if provedene[skript.name] != _otisk(skript):
                raise click.ClickException(f"{skript.name} se po provedení změnil. Opravu dejte do nového skriptu.")
            continue
        click.echo(f"Provádím {skript.name} …")
        davky = rozdel_na_davky(skript.read_text(encoding="utf-8-sig"))
        try:
            with spojeni_pro_skript(migrace=True) as spoj:
                for davka in davky:
                    spoj.proved(davka)
                spoj.proved("INSERT INTO dbo.MigraceSchema (Soubor, Otisk) VALUES (?, ?)", skript.name, _otisk(skript))
        except Exception as chyba:
            raise click.ClickException(f"{skript.name} selhal, nic z něj se nezapsalo: {chyba}") from chyba
        click.echo(f"  hotovo {skript.name}")
    click.echo("Schéma je aktuální.")


@db_cli.command("oznac")
@click.argument("soubor")
def oznac(soubor: str) -> None:
    skript = ADRESAR / soubor
    if not skript.exists():
        raise click.ClickException(f"Skript {soubor} neexistuje v {ADRESAR}")
    with spojeni_pro_skript(migrace=True) as spoj:
        spoj.proved(_TABULKA_MIGRACI)
        spoj.proved("INSERT INTO dbo.MigraceSchema (Soubor, Otisk) VALUES (?, ?)", skript.name, _otisk(skript))
    click.echo(f"{soubor} označen jako provedený.")
