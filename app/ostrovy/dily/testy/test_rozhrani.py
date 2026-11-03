import unittest

from app.ostrovy.dily import rozhrani as dily


class TestNormalizace(unittest.TestCase):
    def test_normalizace(self):
        self.assertEqual(dily.normalizuj_identifikacni_cislo(" ce21ra  10\t100194 "), "CE21RA 10 100194")
        self.assertEqual(dily.normalizuj_identifikacni_cislo("aar10044"), "AAR10044")
        self.assertEqual(dily.normalizuj_identifikacni_cislo(""), "")


if __name__ == "__main__":
    unittest.main()
