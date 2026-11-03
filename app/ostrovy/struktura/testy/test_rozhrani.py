"""Testy čistých funkcí rozhraní ostrova C (T13 – parser kódů, pravidlo velikosti)."""
import unittest
from dataclasses import replace
from decimal import Decimal

from app.ostrovy.struktura import rozhrani as struktura
from app.ostrovy.struktura import ukazky
from app.platforma.typy import PotrebaMista, Rozmer


class TestRozlozKod(unittest.TestCase):
    def over(self, kod, typ, typ_boxu=None, kod_boxu=None, kod_pozice=None):
        r = struktura.rozloz_kod(kod)
        self.assertEqual((r.typ, r.typ_boxu, r.kod_boxu, r.kod_pozice), (typ, typ_boxu, kod_boxu, kod_pozice), kod)
        return r

    def test_stat(self):
        self.over("BSTAT037-1", "POZICE", "STAT", "BSTAT037", "1")
        self.over("bstat037", "BOX", "STAT", "BSTAT037")

    def test_dyn(self):
        r = self.over("BPLE037-A", "POZICE", "DYN", "BPLE037", "A")
        self.assertEqual(r.kod_pracoviste, "PLE")
        self.assertEqual(r.kod_mista, "BPLE037-A")
        self.over("BPLE037-CH", "POZICE", "DYN", "BPLE037", "CH")
        self.over("B1SV037", "BOX", "DYN", "B1SV037")
        self.over(" bple052-r ", "POZICE", "DYN", "BPLE052", "R")

    def test_regal(self):
        r = self.over("HOUFEK-PLE-R01", "REGAL")
        self.assertEqual((r.kod_pracoviste, r.kod_regalu), ("PLE", "R01"))

    def test_dlouhy_tvar(self):
        r = self.over("HOUFEK-PLE-R01-U03-BPLE003-D", "POZICE", "DYN", "BPLE003", "D")
        self.assertEqual((r.kod_regalu, r.kod_urovne), ("R01", "U03"))
        self.over("HOUFEK-PLE-R02-U01-BSTAT037-1", "POZICE", "STAT", "BSTAT037", "1")
        self.over("HOUFEK-PLE-R01-U03-BPLE003", "BOX", "DYN", "BPLE003")

    def test_neplatne_a_text(self):
        for kod in ["BPLE037-S", "BPLE037-0", "BSTAT037-0", "HOUFEK-1SV-R01-U03-BPLE003-D", "CE21RA 10 100194", ""]:
            self.assertEqual(struktura.rozloz_kod(kod).typ, "TEXT", kod)
        self.assertEqual(struktura.rozloz_kod("ce21ra  10 100194").text, "CE21RA 10 100194")


class TestVejdeSe(unittest.TestCase):
    def test_pevne_velikosti(self):
        misto = ukazky.MISTO_BPLE037_A
        self.assertTrue(struktura.vejde_se(misto, PotrebaMista("V1")))
        self.assertFalse(struktura.vejde_se(misto, PotrebaMista("V2")))

    def test_c7(self):
        misto = ukazky.MISTO_BPLE052_R   # 800 × 400 mm
        self.assertTrue(struktura.vejde_se(misto, PotrebaMista("V6", Rozmer(Decimal("800"), Decimal("400")))))
        self.assertFalse(struktura.vejde_se(misto, PotrebaMista("V6", Rozmer(Decimal("801"), Decimal("400")))))
        self.assertFalse(struktura.vejde_se(misto, PotrebaMista("V6")))
        self.assertFalse(struktura.vejde_se(replace(misto, rozmer_c7=None),
                                            PotrebaMista("V6", Rozmer(Decimal("1"), Decimal("1")))))


class TestStavBoxu(unittest.TestCase):
    def test_priorita(self):
        self.assertEqual(struktura.stav_boxu(True, 3), "BLOKOVANY")
        self.assertEqual(struktura.stav_boxu(False, 1), "OBSAZENY")
        self.assertEqual(struktura.stav_boxu(False, 0), "VOLNY")


if __name__ == "__main__":
    unittest.main()
