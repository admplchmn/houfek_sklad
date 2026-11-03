"""Pojistka kostry fáze 0: vzorová data z `ukazky.py` se nesmí dostat do provozu.

Funkce rozhraní s komentářem `KOSTRA (fáze 0)` vracejí vzorová data, dokud je vlastník
nenahradí skutečnou implementací. Každý `ukazky.py` na prvním řádku volá `jen_ve_vyvoji`.
V provozním režimu (HOUFEK_VYVOJ=0) pak volání kostry skončí chybou (INTERNAL_ERROR
v logu s názvem modulu), místo aby terminál ukázal vymyšlenou zásobu jako skutečnou.

Mimo aplikaci (jednotkové testy bez app contextu) a ve vývoji se nic neděje.

`DocasnaSqlite` dovolí spustit kostru bez SQL Serveru (vývoj bez HOUFEK_DB_SERVER, testy):
jen tabulky Platformy (SkladovaTransakce, AuditZmen), aby fungovaly @transakce a requestId.
Data ostrovů jsou vzorová, nic z nich se neukládá.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable

from flask import current_app, has_app_context

SQLITE_PLATFORMY = """
CREATE TABLE dbo.Uzivatel (UzivatelID INTEGER PRIMARY KEY);
CREATE TABLE dbo.SkladovaTransakce (
    TransakceID TEXT PRIMARY KEY, KlientRequestID TEXT NOT NULL UNIQUE, TypOperace TEXT NOT NULL,
    UzivatelID INTEGER NOT NULL, TerminalID INTEGER, DatumCas TIMESTAMP DEFAULT CURRENT_TIMESTAMP, Vysledek TEXT);
CREATE TABLE dbo.AuditZmen (
    AuditID INTEGER PRIMARY KEY AUTOINCREMENT, DatumCas TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UzivatelID INTEGER NOT NULL, TypObjektu TEXT NOT NULL, ObjektID INTEGER NOT NULL, Pole TEXT NOT NULL,
    StaraHodnota TEXT, NovaHodnota TEXT, Poznamka TEXT);
CREATE TABLE dbo.SablonaPolozka (
    PolozkaID INTEGER PRIMARY KEY AUTOINCREMENT, Kod TEXT NOT NULL UNIQUE, PocetKs INTEGER NOT NULL,
    Zalozeno TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
INSERT INTO dbo.Uzivatel (UzivatelID) VALUES (1);
"""


class DocasnaSqlite:
    """Dočasná sqlite databáze připojená jako schéma `dbo`, aby fungovalo `dbo.Tabulka`."""

    def __init__(self, sql: str = SQLITE_PLATFORMY) -> None:
        self.adresar = tempfile.mkdtemp(prefix="houfek_kostra_")
        spoj = self.pripoj()
        spoj.executescript(sql)
        spoj.commit()
        spoj.close()

    def pripoj(self) -> sqlite3.Connection:
        spoj = sqlite3.connect(os.path.join(self.adresar, "main.sqlite"), timeout=5)
        spoj.execute("ATTACH DATABASE ? AS dbo", (os.path.join(self.adresar, "dbo.sqlite"),))
        return spoj

    def tovarna(self) -> Callable:
        from .db import Spojeni  # db importuje konfiguraci, kostra má zůstat lehká

        return lambda: Spojeni(self.pripoj(), "sqlite")

    def hodnota(self, sql: str, *parametry):
        spoj = self.pripoj()
        try:
            radek = spoj.execute(sql, parametry).fetchone()
            return radek[0] if radek else None
        finally:
            spoj.close()

    def smaz(self) -> None:
        shutil.rmtree(self.adresar, ignore_errors=True)


class KostraVProvozu(RuntimeError):
    """Volání neimplementované funkce rozhraní (vzorová data) v provozním režimu."""


def jen_ve_vyvoji(modul: str) -> None:
    if has_app_context() and not current_app.config.get("HOUFEK_VYVOJ"):
        raise KostraVProvozu(f"{modul}: kostra fáze 0 (vzorová data) se volala v provozním režimu. "
                             "Funkce rozhraní ještě není implementovaná.")
