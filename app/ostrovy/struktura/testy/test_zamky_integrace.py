"""TD-01: zámky pozic (struktura.zamkni_mista) nad SQL Serverem – souběh dvou spojení (ADR-0005).

Testovací data musí být potvrzená: druhé spojení pod RCSI do nepotvrzených řádků nevidí
a měřilo by něco jiného než souběžný zádech. Struktura proto vzniká přes spojeni_pro_skript()
(který potvrzuje) s unikátním kódem pracoviště a v testovací databázi zůstává – stejně jako
data testů Platformy; rollback self.spoj se jí nedotkne.
"""
from __future__ import annotations

import unittest
import uuid

from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.db import Spojeni, spojeni_pro_skript
from app.platforma.sql_chyby import je_limit_zamku
from app.platforma.typy import Kontext
from tests.integrace.zaklad import ZakladIntegrace

POZIC_V_BOXU = 6   # členění C6: čtyři boxy jsou 24 pozic, tedy víc než zamyká rozhraní po jedné (20)


class TestZamknutiMist(ZakladIntegrace):
    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(1, None, "TEST", frozenset())

    def potvrz_uroven(self, pocet_boxu: int) -> list[int]:
        """Pracoviště + regál + úroveň + boxy C6; vrátí ID všech jejich vnitřních pozic."""
        with spojeni_pro_skript() as spoj:
            pracoviste = struktura.zaloz_pracoviste(spoj, self.kdo, self.novy_kod(spoj), None)
            regal = struktura.zaloz_regal(spoj, self.kdo, pracoviste, "R01", None)
            uroven = struktura.zaloz_uroven(spoj, self.kdo, regal, "U01", 1, 2400, 800)
            for _ in range(pocet_boxu):
                struktura.zaloz_box(spoj, self.kdo, uroven, None, "DYN", "C6", 400, 360)
            return [r["VnitrniPoziceID"] for r in spoj.dotaz(
                "SELECT VnitrniPoziceID FROM dbo.v_Misto WHERE UrovenID = ? ORDER BY VnitrniPoziceID", uroven)]

    @staticmethod
    def novy_kod(spoj: Spojeni) -> str:
        """Kód pracoviště, který v databázi ještě není (potvrzená data z předchozích běhů zůstávají)."""
        while True:
            kod = "T" + uuid.uuid4().hex[:2].upper()
            if not spoj.hodnota("SELECT COUNT(*) FROM dbo.Pracoviste WHERE KodPracoviste = ?", kod):
                return kod

    def druhe_spojeni_s_timeoutem(self) -> Spojeni:
        """Druhé spojení počká na cizí zámek jen 200 ms (vzor tests/integrace/test_platforma.py)."""
        druhe = self.druhe_spojeni()
        druhe.proved("SET LOCK_TIMEOUT 200;")
        return druhe

    def test_zamcenou_pozici_druhe_spojeni_nedostane(self):
        """Zámek drží do konce transakce: druhé spojení dostane limit zámků (1222 → CONCURRENT_CHANGE)."""
        ids = self.potvrz_uroven(1)
        self.assertEqual(len(ids), POZIC_V_BOXU)
        struktura.zamkni_mista(self.spoj, ids[:1])
        struktura.zamkni_mista(self.spoj, ids[:1])                     # vlastník se vlastním zámkem nezablokuje
        druhe = self.druhe_spojeni_s_timeoutem()
        with self.assertRaises(Exception) as zachyceno:
            struktura.zamkni_mista(druhe, ids[:1])
        self.assertTrue(je_limit_zamku(zachyceno.exception), zachyceno.exception)

    def test_zamcenou_sadu_nad_davku_druhe_spojeni_nedostane(self):
        """Nad 20 pozic se zamkýnají dávkami (IN (…) po sobě vzestupně); souběh skončí stejně 1222."""
        ids = self.potvrz_uroven(4)
        self.assertGreater(len(ids), struktura._ZAMKY_PO_JEDNOM)
        struktura.zamkni_mista(self.spoj, ids)
        struktura.zamkni_mista(self.spoj, ids)                         # podruhé ve stejné transakci
        druhe = self.druhe_spojeni_s_timeoutem()
        with self.assertRaises(Exception) as zachyceno:
            struktura.zamkni_mista(druhe, ids)
        self.assertTrue(je_limit_zamku(zachyceno.exception), zachyceno.exception)


if __name__ == "__main__":
    unittest.main()
