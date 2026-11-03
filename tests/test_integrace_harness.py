"""Pojistky harnessu integračních testů (tests/integrace/zaklad.py): jen testovací databáze, nikdy PowerKey,
a ze souboru .env jen proměnné HOUFEK_TEST_DB_*. Běží bez SQL Serveru."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.integrace import zaklad

ZAKLAD = {"HOUFEK_TEST_DB_SERVER": "localhost", "HOUFEK_TEST_DB_UZIVATEL": "sa", "HOUFEK_TEST_DB_HESLO": "x"}


class TestHarnessIntegrace(unittest.TestCase):
    def konfigurace(self, prostredi, ze_souboru=None):
        with mock.patch.dict(os.environ, prostredi, clear=True), \
                mock.patch.object(zaklad, "_ze_souboru_env", return_value=ze_souboru or {}):
            return zaklad.konfigurace()

    def test_jen_testovaci_databaze(self):
        self.assertIsNone(self.konfigurace({}))                                       # bez serveru se přeskočí
        self.assertEqual(self.konfigurace({**ZAKLAD, "HOUFEK_TEST_DB_NAZEV": "HoufekSklad_TEST"}).db_nazev,
                         "HoufekSklad_TEST")
        for nazev in ("PowerKey_TEST", "HoufekSklad_DEV"):
            with self.subTest(nazev=nazev), self.assertRaises(RuntimeError):
                self.konfigurace({**ZAKLAD, "HOUFEK_TEST_DB_NAZEV": nazev})

    def test_prostredi_prebije_soubor_env(self):
        konf = self.konfigurace({"HOUFEK_TEST_DB_NAZEV": "B_TEST"}, {**ZAKLAD, "HOUFEK_TEST_DB_NAZEV": "A_TEST"})
        self.assertEqual((konf.db_server, konf.db_nazev), ("localhost", "B_TEST"))

    def test_z_env_jen_testovaci_promenne(self):
        with tempfile.TemporaryDirectory() as slozka:
            soubor = Path(slozka) / ".env"
            soubor.write_text("HOUFEK_DB_HESLO=provozni\nHOUFEK_TEST_DB_NAZEV=HoufekSklad_TEST\n"
                              "HOUFEK_TEST_DB_SERVER=\n", encoding="utf-8")
            self.assertEqual(zaklad._ze_souboru_env(soubor), {"HOUFEK_TEST_DB_NAZEV": "HoufekSklad_TEST"})
            self.assertEqual(zaklad._ze_souboru_env(Path(slozka) / "neni.env"), {})

    def test_nazev_databaze_bez_vlozeni_sql(self):
        konf = self.konfigurace({**ZAKLAD, "HOUFEK_TEST_DB_NAZEV": "X_TEST]; DROP DATABASE y; --"})
        with self.assertRaises(RuntimeError):
            zaklad._zaloz_databazi(konf)


if __name__ == "__main__":
    unittest.main()
