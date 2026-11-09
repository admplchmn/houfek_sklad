"""Integrační test migrace 006 – zámek PINu (D-33, TD-07) a nečinnost terminálu (D-34, TD-06).

Ověřuje, co v migračním skriptu bez SQL Serveru lokálně nepoznáme: výchozí hodnoty nových
sloupců, že CHECK nepustí záporný počet pokusů ani cizí kód výsledku a že cizí klíče ukazují
jen na skutečného uživatele a terminál. Oprávnění (DENY UPDATE a DELETE) test neřeší – ta
poskytuje Role, nikoli testovací spojení (přihlašuje se jako `sa`).

Porušení omezení zahodí celou transakci spojení (XACT_ABORT), proto test, který chybu čeká,
už pak nic nedělá. Kódy jsou jedinečné podle náhodné značky, aby nepřekážela data, která
v databázi potvrdily jiné testy.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from tests.integrace.zaklad import ZakladIntegrace

NEEXISTUJE = 2_000_000_000        # takové ID nemůže existovat → FK 547
VYSLEDKY = ("USPECH", "CHYBNY_PIN", "ZAMCENO", "NEZNAMY", "NEAKTIVNI")


class TestMigrace006(ZakladIntegrace):
    # --- pomocná data ------------------------------------------------------------------------

    def _uzivatel(self) -> int:
        """Nový uživatel s jedinečným osobním číslem; vrací UzivatelID."""
        return self.spoj.vloz("INSERT INTO dbo.Uzivatel (OsobniCislo, Jmeno, Prijmeni, RoleID, Aktivni) "
                              "VALUES (?, N'Testovací', N'Uživatel', (SELECT RoleID FROM dbo.Role "
                              "WHERE KodRole = 'TECH'), 1)", f"TEST-006-{uuid.uuid4().hex[:8]}")

    def _terminal(self) -> int:
        """Nový terminál s jedinečným kódem; vrací TerminalID."""
        return self.spoj.vloz("INSERT INTO dbo.Terminal (KodTerminalu, NazevTerminalu) "
                              "VALUES (?, N'Testovací terminál')", f"TST006-{uuid.uuid4().hex[:8]}")

    def _pokus(self, osobni_cislo: str, vysledek: str, uzivatel_id: int | None = None,
               terminal_id: int | None = None) -> int:
        return self.spoj.vloz("INSERT INTO dbo.PrihlaseniPokus (OsobniCislo, Vysledek, UzivatelID, TerminalID) "
                              "VALUES (?, ?, ?, ?)", osobni_cislo, vysledek, uzivatel_id, terminal_id)

    # --- počítadlo pokusů a zámek účtu (D-33) ------------------------------------------------

    def test_novy_uzivatel_zacina_na_nule_a_bez_zamku(self):
        uzivatel = self._uzivatel()
        radek = self.spoj.dotaz("SELECT ChybnePokusy, ZamcenoDo FROM dbo.Uzivatel WHERE UzivatelID = ?",
                                uzivatel)[0]
        self.assertEqual(radek["ChybnePokusy"], 0)
        self.assertIsNone(radek["ZamcenoDo"])

    def test_zamceno_do_se_ulozi(self):
        """ZamcenoDo je čas v UTC (TD-11); po jeho uplynutí se uživatel může zkusit přihlásit znovu."""
        uzivatel = self._uzivatel()
        do = datetime(2026, 11, 9, 14, 15, 0)
        self.spoj.proved("UPDATE dbo.Uzivatel SET ChybnePokusy = 5, ZamcenoDo = ? WHERE UzivatelID = ?", do, uzivatel)
        radek = self.spoj.dotaz("SELECT ChybnePokusy, ZamcenoDo FROM dbo.Uzivatel WHERE UzivatelID = ?",
                                uzivatel)[0]
        self.assertEqual((radek["ChybnePokusy"], radek["ZamcenoDo"]), (5, do))

    def test_zaporny_pocet_pokusu_server_odmitne(self):
        uzivatel = self._uzivatel()
        with self.assertRaises(Exception) as zachyceno:
            self.spoj.proved("UPDATE dbo.Uzivatel SET ChybnePokusy = -1 WHERE UzivatelID = ?", uzivatel)
        self.assertIn("CK_Uzivatel_ChybnePokusy", str(zachyceno.exception))

    # --- historie pokusů o přihlášení (D-33) --------------------------------------------------

    def test_pokus_se_ulozi_vsemi_vysledky(self):
        """Všech pět kódů z D-33 se uloží a řádek dostane čas ze SYSUTCDATETIME()."""
        uzivatel, terminal = self._uzivatel(), self._terminal()
        for vysledek in VYSLEDKY:
            pokus = self._pokus("TEST-006-OSOBNI", vysledek, uzivatel, terminal)
            radek = self.spoj.dotaz("SELECT Vysledek, DatumCas FROM dbo.PrihlaseniPokus WHERE PokusID = ?",
                                    pokus)[0]
            self.assertEqual(radek["Vysledek"], vysledek)
            self.assertIsInstance(radek["DatumCas"], datetime)

    def test_pokus_i_pro_nezname_osobni_cislo(self):
        """UzivatelID i TerminalID zůstanou NULL, když při pokusu nebylo co vyplnit."""
        pokus = self._pokus("TEST-006-NEZNAMY", "NEZNAMY")
        radek = self.spoj.dotaz("SELECT UzivatelID, TerminalID FROM dbo.PrihlaseniPokus WHERE PokusID = ?",
                                pokus)[0]
        self.assertEqual((radek["UzivatelID"], radek["TerminalID"]), (None, None))

    def test_jiny_vysledek_pokusu_server_odmitne(self):
        with self.assertRaises(Exception) as zachyceno:
            self._pokus("TEST-006-OSOBNI", "NEUSPEL")
        self.assertIn("CK_PrihlaseniPokus_Vysledek", str(zachyceno.exception))

    def test_pokus_s_neexistujicim_uzivatelem_server_odmitne(self):
        with self.assertRaises(Exception) as zachyceno:
            self._pokus("TEST-006-OSOBNI", "USPECH", uzivatel_id=NEEXISTUJE)
        self.assertIn("FK_PrihlaseniPokus_Uzivatel", str(zachyceno.exception))

    def test_pokus_s_neexistujicim_terminalem_server_odmitne(self):
        with self.assertRaises(Exception) as zachyceno:
            self._pokus("TEST-006-OSOBNI", "USPECH", terminal_id=NEEXISTUJE)
        self.assertIn("FK_PrihlaseniPokus_Terminal", str(zachyceno.exception))
