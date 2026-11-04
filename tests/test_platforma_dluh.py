"""Splacený technický dluh fáze 0 → 1 (docs/technicky-dluh.md): TD-09, TD-12, TD-15 a běh kostry bez SQL Serveru."""
from __future__ import annotations

import logging
import unittest
from contextlib import contextmanager
from unittest import mock

import click

from app.ostrovy import OSTROVY, _sablona
from app.platforma import migrace_db, vytvor_aplikaci
from app.platforma.db import cteni
from app.platforma.konfigurace import Konfigurace
from tests.pomocnik import TestovaciDatabaze, rid, testovaci_aplikace


class TestCteniNezapisuje(unittest.TestCase):
    """TD-09: zápis ve službě @cteni skončí chybou místo tichého zahození."""

    def setUp(self):
        self.db = TestovaciDatabaze()
        self.app = testovaci_aplikace([], self.db)

    def tearDown(self):
        self.db.smaz()

    def test_zapis_v_cteni_selze(self):
        @cteni
        def spatna_sluzba(spoj):
            spoj.proved("INSERT INTO dbo.SablonaPolozka (Kod, PocetKs) VALUES ('X', 1)")

        @cteni
        def dobra_sluzba(spoj):
            return spoj.hodnota("SELECT COUNT(*) FROM dbo.SablonaPolozka")

        with self.app.app_context():
            with self.assertRaisesRegex(RuntimeError, "@transakce"):
                spatna_sluzba()
            self.assertEqual(dobra_sluzba(), 0)


class TestLogovani(unittest.TestCase):
    """TD-12: aplikace nastavuje jen logger „houfek“ a handler přidá jen jednou."""

    def test_vic_instanci_nezdvoji_handler_a_nesaha_na_koren(self):
        koren = logging.getLogger()
        pred = list(koren.handlers)
        db = TestovaciDatabaze()
        try:
            for _ in range(3):
                testovaci_aplikace([], db)
        finally:
            db.smaz()
        nase = [h for h in logging.getLogger("houfek").handlers if getattr(h, "_houfek", False)]
        self.assertEqual(len(nase), 1)
        self.assertEqual(koren.handlers, pred)


class TestZamekUpgradu(unittest.TestCase):
    """TD-15: druhý souběžný `flask db upgrade` hned skončí srozumitelnou chybou."""

    def zamek(self, vysledek_zamku):
        volani = []

        class Spojeni:
            dialekt = "mssql"

            def hodnota(self, sql, *parametry):
                volani.append(("zamkni" if "getapplock" in sql else "odemkni", parametry))
                return vysledek_zamku if "getapplock" in sql else 0

        @contextmanager
        def spojeni_pro_skript(migrace=False):
            yield Spojeni()

        return volani, mock.patch.object(migrace_db, "spojeni_pro_skript", spojeni_pro_skript)

    def test_zamek_ziskan_a_uvolnen(self):
        volani, zaplata = self.zamek(0)
        with zaplata, migrace_db.zamek_upgrade():
            pass
        self.assertEqual(volani, [("zamkni", ("houfek_db_upgrade",)), ("odemkni", ("houfek_db_upgrade",))])

    def test_druhy_upgrade_skonci_chybou(self):
        volani, zaplata = self.zamek(-1)
        with zaplata, self.assertRaisesRegex(click.ClickException, "právě běží"):
            with migrace_db.zamek_upgrade():
                self.fail("upgrade nesmí běžet bez zámku")
        self.assertEqual([v[0] for v in volani], ["zamkni"])


class TestKostraBezDatabaze(unittest.TestCase):
    """Vývoj bez HOUFEK_DB_SERVER: aplikace naběhne nad dočasnou sqlite a kostra jde proklikat (TD-04).

    Ověřuje se Platforma a šablona ostrova – jen jejich tabulky v sqlite kostry jsou. Ostrovy s
    hotovou fází 1 čtou nad SQL Serverem (docs/vyvoj.md, sekce 1.1), proto se tu nevolají.
    """

    def test_aplikace_bez_db_obslouzi_cteni_i_skladovy_prikaz(self):
        app = vytvor_aplikaci([*OSTROVY, _sablona.OSTROV], Konfigurace(vyvoj=True))
        try:
            klient = app.test_client()
            self.assertEqual(klient.post("/api/system/vyvojove-prihlaseni", json={
                "uzivatelId": 1, "kodRole": "ADMIN"}).status_code, 200)
            self.assertEqual(klient.get("/api/system/zdravi").json["data"]["databaze"], "KOSTRA")
            odpoved = klient.post("/api/sablona/polozky", json={"requestId": rid(), "kod": "SBL037",
                                                                "pocetKs": 30})
            self.assertEqual(odpoved.json["code"], "OK")
            self.assertIsNotNone(odpoved.json["transakceId"])
            polozka_id = odpoved.json["data"]["polozkaId"]
            self.assertEqual(klient.get(f"/api/sablona/polozky/{polozka_id}").json["data"]["kod"], "SBL037")
        finally:
            app.extensions["houfek_kostra_db"].smaz()

    def test_provoz_bez_db_nespusti_kostru(self):
        app = vytvor_aplikaci([], Konfigurace(vyvoj=False, tajny_klic="k" * 40))
        self.assertNotIn("houfek_kostra_db", app.extensions)


if __name__ == "__main__":
    unittest.main()
