"""Jednotkové testy pravidel ostrova G (`domena.py`) – bez databáze a bez Flasku."""
import unittest

from app.ostrovy.prehledy import domena
from app.ostrovy.prehledy.domena import barva_boxu


class TestBarvaBoxu(unittest.TestCase):
    def test_barvy(self):
        self.assertEqual(barva_boxu("BLOKOVANY", "DYN"), "CERVENA")
        self.assertEqual(barva_boxu("BLOKOVANY", "STAT"), "CERVENA")
        self.assertEqual(barva_boxu("VOLNY", "DYN"), "ZELENA")
        self.assertEqual(barva_boxu("OBSAZENY", "DYN"), "MODRA")   # 17.1 krok 7, Q-31
        self.assertEqual(barva_boxu("OBSAZENY", "STAT"), "SEDA")
        self.assertEqual(barva_boxu("VOLNY", "STAT"), "ZELENA")   # zadání 7.2: úplně prázdný = zelená i u STAT


class TestLaserQ22(unittest.TestCase):
    """Kap. 14: „chybí ve STAT“ je dané zadáním, odečtení DYN je přepínač (Q-22)."""

    def test_bez_odecteni_dyn(self):
        self.assertEqual(domena.doporuceni_laser(30, 12, 0, None, odecitat_dyn=False), (18, 18))   # příklad kap. 14
        self.assertEqual(domena.doporuceni_laser(40, 12, 8, 20, odecitat_dyn=False), (28, 40))     # na celé dávky

    def test_s_odectenim_dyn(self):
        self.assertEqual(domena.doporuceni_laser(40, 12, 8, 20, odecitat_dyn=True), (28, 20))
        self.assertEqual(domena.doporuceni_laser(40, 12, 30, 20, odecitat_dyn=True), (28, 0))

    def test_staci_stat(self):
        self.assertEqual(domena.doporuceni_laser(10, 12, 0, 20, odecitat_dyn=False), (0, 0))
        self.assertEqual(domena.doporuceni_laser(40, 12, 8, None, odecitat_dyn=False), (28, 28))   # bez dávky


class TestSouhrnUmisteniPoradi(unittest.TestCase):
    def test_souhrn_a_text_umisteni(self):
        self.assertEqual(domena.souhrn_zasob(["OK", "VYCERPANO", "OK"]),
                         {"sledovane": 3, "OK": 2, "NA_MINIMU": 0, "POD_MINIMEM": 0, "VYCERPANO": 1})
        self.assertEqual([domena.text_umisteni(True, 2), domena.text_umisteni(True, 1), domena.text_umisteni(True, 0),
                          domena.text_umisteni(False, 3), domena.text_umisteni(False, 0)],
                         ["STAT + 2× DYN", "STAT + DYN", "STAT", "3× DYN", "–"])

    def test_poradi_umisteni(self):
        klice = sorted([("DYN", "BPLE010", 1), ("STAT", "BSTAT900", 4), ("DYN", "BPLE002", 2)],
                       key=lambda u: domena.poradi_umisteni(*u))
        self.assertEqual([k[1] for k in klice], ["BSTAT900", "BPLE002", "BPLE010"])


if __name__ == "__main__":
    unittest.main()
