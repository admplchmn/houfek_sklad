import unittest

from app.ostrovy.sklad import rozhrani as sklad


class TestStavZasoby(unittest.TestCase):
    def test_poradi_pravidel(self):
        self.assertEqual(sklad.stav_zasoby(0, 0), "VYCERPANO")      # N-08: minimum 0 a stav 0
        self.assertEqual(sklad.stav_zasoby(0, 10), "VYCERPANO")
        self.assertEqual(sklad.stav_zasoby(9, 10), "POD_MINIMEM")
        self.assertEqual(sklad.stav_zasoby(10, 10), "NA_MINIMU")
        self.assertEqual(sklad.stav_zasoby(11, 10), "OK")
        self.assertEqual(sklad.stav_zasoby(1, 0), "OK")


if __name__ == "__main__":
    unittest.main()
