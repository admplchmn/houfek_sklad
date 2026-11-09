"""Testy nečinnosti relace v platformě (TD-06, D-34): PDA 15 minut posuvně, PC beze změny (12 h).

Čas se v testech nahrazuje `app.platforma.auth.teď` – test nečeká a nezávisí na hodinách stroje.
"""
from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import patch

from flask import Blueprint

from app.platforma.auth import vyzaduje
from app.platforma.http import odpoved
from app.platforma.kontrakty import teď
from app.platforma.ostrov import Ostrov
from tests.pomocnik import TestovaciDatabaze, prihlas, testovaci_aplikace

api = Blueprint("test_necinnost", __name__)


@api.get("/volani")
@vyzaduje("TEST_CIST")
def volani():
    return odpoved()


TEST_OSTROV = Ostrov(nazev="Test nečinnosti", prefix="necinnost", api=api, opravneni=["TEST_CIST"])


class ZakladNecinnosti(unittest.TestCase):
    def setUp(self):
        self.db = TestovaciDatabaze()
        self.app = testovaci_aplikace([TEST_OSTROV], self.db)
        self.klient = self.app.test_client()
        self.ted = teď()

    def tearDown(self):
        self.db.smaz()

    def prihlas_terminal(self, terminal_id: int | None = 7) -> None:
        """Přihlášení, jak ho dělá ostrov B: z terminálu, nebo bez něj (PC)."""
        prihlas(self.klient, "TEST_CIST", terminal_id=terminal_id)

    def volej(self, o: timedelta = timedelta()) -> tuple:
        """Další požadavek téže relace v čase `self.ted + o`; vrací (HTTP status, kód obálky)."""
        with patch("app.platforma.auth.teď", return_value=self.ted + o):
            odpoved_ = self.klient.get("/api/necinnost/volani")
        return odpoved_.status_code, odpoved_.json["code"]


class TestNecinnostTerminalu(ZakladNecinnosti):
    def test_do_ctyrnacti_minut_plati_a_cas_se_obnovi(self):
        self.prihlas_terminal()
        self.assertEqual(self.volej(), (200, "OK"))
        self.assertEqual(self.volej(timedelta(minutes=14)), (200, "OK"))
        # od obnovy uběhlo dalších 14 minut, tedy 28 od přihlášení – relace stále platí
        self.assertEqual(self.volej(timedelta(minutes=28)), (200, "OK"))

    def test_po_patnacti_minutach_se_odhlasi(self):
        self.prihlas_terminal()
        self.assertEqual(self.volej(), (200, "OK"))
        self.assertEqual(self.volej(timedelta(minutes=15)), (401, "NOT_AUTHENTICATED"))

    def test_odhlaseni_je_stejne_jako_bez_prihlaseni(self):
        self.prihlas_terminal()
        self.assertEqual(self.volej(), (200, "OK"))
        bez_prihlaseni = self.app.test_client().get("/api/necinnost/volani")
        self.assertEqual(self.volej(timedelta(minutes=20)),
                         (bez_prihlaseni.status_code, bez_prihlaseni.json["code"]))


class TestNecinnostPocitace(ZakladNecinnosti):
    def test_pc_se_po_15_minutach_se_neodhlasi(self):
        self.prihlas_terminal(terminal_id=None)
        self.assertEqual(self.volej(timedelta(minutes=15)), (200, "OK"))
        self.assertEqual(self.volej(timedelta(hours=11)), (200, "OK"))


if __name__ == "__main__":
    unittest.main()
