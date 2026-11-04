"""Kontrola hranic ostrova (nastroje/hranice_ostrova.py): větev ostrova mění jen svou složku."""
import unittest

from nastroje.hranice_ostrova import mimo_ostrov


class TestHraniceOstrova(unittest.TestCase):
    def test_jen_vlastni_slozka(self):
        soubory = ["app/ostrovy/sklad/sluzby.py", "app/ostrovy/sklad/testy/test_sklad.py"]
        self.assertEqual(mimo_ostrov("ostrov/sklad/42-vydej", soubory), [])

    def test_cizi_a_sdilene_soubory_jsou_mimo(self):
        soubory = ["app/ostrovy/sklad/sluzby.py", "app/ostrovy/dily/rozhrani.py", "kontrakty/openapi.json"]
        self.assertEqual(mimo_ostrov("ostrov/sklad/42-vydej", soubory),
                         ["app/ostrovy/dily/rozhrani.py", "kontrakty/openapi.json"])

    def test_neznamy_ostrov_neprojde(self):
        self.assertEqual(mimo_ostrov("ostrov/sklady/1", ["app/ostrovy/sklady/x.py"]), ["app/ostrovy/sklady/x.py"])
        self.assertTrue(mimo_ostrov("ostrov/_sablona/1", []))

    def test_ostatni_vetve_se_nekontroluji(self):
        self.assertEqual(mimo_ostrov("platforma/ci", ["app/platforma/http.py", "sql/migrace/005.sql"]), [])


if __name__ == "__main__":
    unittest.main()
