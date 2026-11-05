"""Harness integračních testů proti SQL Serveru (TD-01, docs/adr/0009 vrstva 3).

Bez konfigurace se všechny testy přeskočí (CI bez databáze, vývoj bez DB). Konfigurace jsou proměnné
HOUFEK_TEST_DB_* v prostředí nebo v souboru .env (z .env se čtou jen ony). Nejjednodušší je testovací
SQL Server v Dockeru (docker-compose.yml, docs/vyvoj.md 1.1):

    docker compose up -d
    python -m unittest discover -s tests/integrace -t .     # nebo python -m nastroje.over_vse

    proměnné: HOUFEK_TEST_DB_SERVER, HOUFEK_TEST_DB_NAZEV=HoufekSklad_TEST, HOUFEK_TEST_DB_UZIVATEL,
    HOUFEK_TEST_DB_HESLO, [HOUFEK_TEST_DB_DUVEROVAT_CERTIFIKATU=1]

Pojistky (testy zapisují):
- název databáze musí obsahovat TEST a nesmí to být PowerKey ani jiná cizí databáze,
- chybějící testovací databázi harness založí (s RCSI jako v provozu, ADR-0005),
- schéma se na začátku dorovná chybějícími migracemi (totéž co `python -m nastroje.testovaci_db`,
  pod migračním zámkem; skript už provedený s jiným otiskem je chyba),
- každý test dostane vlastní spojení a na konci se vše vrátí zpět (rollback).

Na co rollback NEplatí (a testy s tím musí počítat): `@transakce` i `spojeni_pro_skript()` si otevírají
vlastní spojení a potvrzují, takže jejich zápis v databázi zůstane. Test proto (a) používá jedinečné
`requestId`/kódy, (b) netvrdí nic o globálním počtu řádků, (c) čísla, která Create vrátil, si pamatuje v
`self`, ne v domněnce, že příště budou stejná. Vzorový svět v `HoufekSklad_TEST` není – data od
ostrovů C a D si test založí sám jejich funkcemi `zaloz_*` v transakci testu, takže se na konci
vrátí zpět (a počítá s tím, že je někdo vložil před ním).

HTTP test bere klienta z vlastní instance `vytvor_aplikaci(OSTROVY, KONFIGURACE)`, ne z `self.app`.
Harness drží pushnutý app context `self.app`, takže by požadavky jejího klienta sdílely `g` a hák
`over_kontext` (ostrov B) by se zavolal jen jednou za test, ne při každém požadavku.

Hesla jen v proměnných prostředí nebo v .env (je v .gitignore), nikdy v kódu ani v repozitáři.
"""
from __future__ import annotations

import dataclasses
import os
import re
import unittest
from pathlib import Path

from app.ostrovy import OSTROVY
from app.platforma import migrace_db, vytvor_aplikaci
from app.platforma.db import Spojeni, otevri_spojeni, spojeni_pro_skript
from app.platforma.konfigurace import Konfigurace

PREDPONA = "HOUFEK_TEST_DB_"
ZAKAZANE_DATABAZE = ("POWERKEY",)
SOUBOR_ENV = Path(__file__).resolve().parents[2] / ".env"


def _ze_souboru_env(soubor: Path = SOUBOR_ENV) -> dict[str, str]:
    """HOUFEK_TEST_DB_* ze souboru .env v kořeni repozitáře; nic jiného z něj harness nečte ani nenastaví."""
    from dotenv import dotenv_values

    if not soubor.exists():
        return {}
    return {k: v for k, v in dotenv_values(soubor, encoding="utf-8").items() if k.startswith(PREDPONA) and v}


def konfigurace() -> Konfigurace | None:
    """Konfigurace testovací DB z HOUFEK_TEST_DB_* (proměnná prostředí přebije .env), nebo None (testy se přeskočí)."""
    prostredi = {**_ze_souboru_env(), **os.environ}
    hodnoty = {f"HOUFEK_DB_{k[len(PREDPONA):]}": v for k, v in prostredi.items() if k.startswith(PREDPONA)}
    if not hodnoty.get("HOUFEK_DB_SERVER") or not hodnoty.get("HOUFEK_DB_NAZEV"):
        return None
    nazev = hodnoty["HOUFEK_DB_NAZEV"].upper()
    if "TEST" not in nazev or any(z in nazev for z in ZAKAZANE_DATABAZE):
        raise RuntimeError(f"Integrační testy smí běžet jen nad testovací databází (název s TEST), ne nad "
                           f"{hodnoty['HOUFEK_DB_NAZEV']!r}.")
    return Konfigurace.z_prostredi({**hodnoty, "HOUFEK_VYVOJ": "1"})


KONFIGURACE = konfigurace()
_aplikace = None
_chyba: Exception | None = None


def _zaloz_databazi(konf: Konfigurace) -> None:
    """Na čistém serveru (Docker) testovací databázi založí, když chybí – s RCSI jako v provozu (ADR-0005)."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", konf.db_nazev):
        raise RuntimeError(f"Název testovací databáze smí mít jen písmena, číslice a _: {konf.db_nazev!r}.")
    import pyodbc  # jen integrační testy

    retezec = dataclasses.replace(konf, db_nazev="master").pripojovaci_retezec_migrace()
    pripojeni = pyodbc.connect(retezec, autocommit=True, timeout=konf.db_limit_prihlaseni_s)
    try:
        pripojeni.execute(f"IF DB_ID(N'{konf.db_nazev}') IS NULL BEGIN CREATE DATABASE [{konf.db_nazev}]; "
                          f"ALTER DATABASE [{konf.db_nazev}] SET READ_COMMITTED_SNAPSHOT ON; END")
    finally:
        pripojeni.close()


def aplikace():
    """Jedna aplikace na běh testů; databáze založená, schéma dorovnané migracemi."""
    global _aplikace, _chyba
    if _chyba is not None:
        raise _chyba            # server nejede: nečekat znovu u každého testu
    if _aplikace is None:
        try:
            _zaloz_databazi(KONFIGURACE)
        except Exception as chyba:
            _chyba = RuntimeError(f"Testovací databázi na {KONFIGURACE.db_server} se nepodařilo připravit: {chyba}\n"
                                  "Běží `docker compose up -d` (server startuje asi 20 s) a sedí heslo v .env?")
            raise _chyba from chyba
        _aplikace = vytvor_aplikaci(OSTROVY, KONFIGURACE)
        with _aplikace.app_context(), migrace_db.zamek_upgrade():
            migrace_db._proved_chybejici()
    return _aplikace


@unittest.skipUnless(KONFIGURACE, "Integrační testy: nastavte HOUFEK_TEST_DB_* (tests/integrace/zaklad.py).")
class ZakladIntegrace(unittest.TestCase):
    """Test s otevřeným spojením `self.spoj`; na konci se všechno vrátí zpět."""

    def setUp(self) -> None:
        self.app = aplikace()
        self.kontext = self.app.app_context()
        self.kontext.push()
        self.spoj: Spojeni = otevri_spojeni()

    def tearDown(self) -> None:
        self.spoj._rollback()
        self.spoj._zavri()
        self.kontext.pop()

    def druhe_spojeni(self) -> Spojeni:
        """Další spojení (souběh, zámky); zavře se samo na konci testu."""
        spoj = otevri_spojeni()
        self.addCleanup(spoj._zavri)
        self.addCleanup(spoj._rollback)
        return spoj

    def uzivatel_testu(self) -> int:
        """Neaktivní technický uživatel pro FK SkladovaTransakce.UzivatelID (potvrdí se, přihlásit se nedá)."""
        with spojeni_pro_skript() as spoj:
            uzivatel_id = spoj.hodnota("SELECT UzivatelID FROM dbo.Uzivatel WHERE OsobniCislo = 'TEST-INTEGRACE'")
            if uzivatel_id is None:
                uzivatel_id = spoj.vloz(
                    "INSERT INTO dbo.Uzivatel (OsobniCislo, Jmeno, Prijmeni, RoleID, Aktivni) "
                    "SELECT 'TEST-INTEGRACE', N'Integrační', N'Test', RoleID, 0 FROM dbo.Role WHERE KodRole = 'ADMIN'")
        return int(uzivatel_id)
