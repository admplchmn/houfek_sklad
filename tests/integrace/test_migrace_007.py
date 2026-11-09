"""Integrační test migrace 007 – staging importu z XLSM (stg.Davka, stg.Bunka; ostrov H).

Ověřuje, co v migračním skriptu bez SQL Serveru lokálně nepoznáme: že dávka dostane čas
ze SYSUTCDATETIME(), že primární klíč nepustí dvakrát tutéž buňku a že buňka musí patřit
skutečné dávce. Oprávnění (SELECT a INSERT na schématu stg) test neřeší – ta poskytuje Role,
nikoli testovací spojení (přihlašuje se jako `sa`).

Porušení omezení zahodí celou transakci spojení (XACT_ABORT), proto test, který chybu čeká,
už pak nic nedělá. Název souboru je jedinečný podle náhodné značky, aby nepřekážela data,
která v databázi potvrdily jiné testy.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from tests.integrace.zaklad import ZakladIntegrace

NEEXISTUJE = 2_000_000_000        # takové DavkaID nemůže existovat → FK 547


class TestMigrace007(ZakladIntegrace):
    # --- pomocná data ------------------------------------------------------------------------

    def _davka(self) -> int:
        """Dávka s jedinečným názvem souboru; vrací DavkaID."""
        return self.spoj.vloz("INSERT INTO stg.Davka (Soubor) VALUES (?)", f"TEST-007-{uuid.uuid4().hex[:8]}.xlsm")

    def _bunka(self, davka_id: int) -> None:
        """Jedna neprázdná buňka listu `Databáze`, jak ji načítá ostrov H 1:1."""
        self.spoj.proved("INSERT INTO stg.Bunka (DavkaID, List, Radek, Sloupec, Hodnota) "
                         "VALUES (?, N'Databáze', 2, 3, N'BPLE001')", davka_id)

    # --- dávka (jedno načtení = jedna dávka, nic se nepřepisuje) ------------------------------

    def test_davka_se_ulozi_s_vychozim_casem(self):
        """Čas i bez zadání sedí (TD-11: UTC ze SYSUTCDATETIME()); CLI má uživatele NULL."""
        radek = self.spoj.dotaz("SELECT NactenoKdy, NacetlUzivatelID FROM stg.Davka WHERE DavkaID = ?",
                                self._davka())[0]
        self.assertIsInstance(radek["NactenoKdy"], datetime)
        self.assertIsNone(radek["NacetlUzivatelID"])

    # --- buňky 1:1 ----------------------------------------------------------------------------

    def test_dvojite_vlozeni_teze_bunky_server_odmitne(self):
        """Primární klíč (DavkaID, List, Radek, Sloupec): tatáž buňka patří do dávky jednou."""
        davka = self._davka()
        self._bunka(davka)
        with self.assertRaises(Exception) as zachyceno:
            self._bunka(davka)
        self.assertIn("PK_Bunka", str(zachyceno.exception))

    def test_bunka_z_neexistujici_davky_server_odmitne(self):
        with self.assertRaises(Exception) as zachyceno:
            self._bunka(NEEXISTUJE)
        self.assertIn("FK_Bunka_Davka", str(zachyceno.exception))
