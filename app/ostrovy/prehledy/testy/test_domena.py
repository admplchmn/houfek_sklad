import unittest

from app.ostrovy.prehledy.domena import barva_boxu


class TestBarvaBoxu(unittest.TestCase):
    def test_barvy(self):
        self.assertEqual(barva_boxu("BLOKOVANY", "DYN"), "CERVENA")
        self.assertEqual(barva_boxu("BLOKOVANY", "STAT"), "CERVENA")
        self.assertEqual(barva_boxu("VOLNY", "DYN"), "ZELENA")
        self.assertEqual(barva_boxu("OBSAZENY", "DYN"), "MODRA")   # 17.1 krok 7, Q-31
        self.assertEqual(barva_boxu("OBSAZENY", "STAT"), "SEDA")
        self.assertEqual(barva_boxu("VOLNY", "STAT"), "ZELENA")   # zadání 7.2: úplně prázdný = zelená i u STAT


if __name__ == "__main__":
    unittest.main()
