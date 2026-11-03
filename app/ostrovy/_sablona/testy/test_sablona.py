"""Vzor testů ostrova: celá svislá cesta přes HTTP + čisté pravidlo bez DB.

Testy jsou unittest, takže běží přes `python -m pytest` i `python -m unittest`.
"""
import unittest
import uuid

from app.ostrovy import _sablona
from app.ostrovy._sablona import domena
from app.platforma.chyby import AppError
from tests.pomocnik import TestovaciDatabaze, prihlas, testovaci_aplikace


class TestDomena(unittest.TestCase):
    def test_limit_kusu(self):
        domena.over_pocet(domena.LIMIT_KS)
        with self.assertRaises(AppError) as chyba:
            domena.over_pocet(domena.LIMIT_KS + 1)
        self.assertEqual(chyba.exception.kod, "SABLONA_PRILIS_MNOHO")


class TestEndpointy(unittest.TestCase):
    def setUp(self):
        self.db = TestovaciDatabaze()
        self.app = testovaci_aplikace([_sablona.OSTROV], self.db)
        self.klient = self.app.test_client()

    def tearDown(self):
        self.db.smaz()

    def test_zalozeni_a_cteni(self):
        prihlas(self.klient, "SABLONA_ZAPIS")
        odpoved = self.klient.post("/api/sablona/polozky",
                                   json={"requestId": str(uuid.uuid4()), "kod": "A1", "pocetKs": 30})
        self.assertEqual(odpoved.status_code, 200, odpoved.json)
        self.assertEqual(odpoved.json["code"], "OK")
        self.assertIsNotNone(odpoved.json["transakceId"])
        polozka_id = odpoved.json["data"]["polozkaId"]

        detail = self.klient.get(f"/api/sablona/polozky/{polozka_id}")
        self.assertEqual(detail.json["data"]["pocetKs"], 30)
        self.assertIsNone(detail.json["transakceId"])

    def test_bez_opravneni(self):
        prihlas(self.klient)
        odpoved = self.klient.post("/api/sablona/polozky",
                                   json={"requestId": str(uuid.uuid4()), "kod": "A1", "pocetKs": 1})
        self.assertEqual(odpoved.status_code, 403)
        self.assertEqual(odpoved.json["code"], "NO_PERMISSION")

    def test_chyba_ostrova(self):
        prihlas(self.klient, "SABLONA_ZAPIS")
        odpoved = self.klient.post("/api/sablona/polozky",
                                   json={"requestId": str(uuid.uuid4()), "kod": "A1", "pocetKs": 10_001})
        self.assertEqual(odpoved.status_code, 409)
        self.assertEqual(odpoved.json["code"], "SABLONA_PRILIS_MNOHO")
        self.assertEqual(self.db.hodnota("SELECT COUNT(*) FROM dbo.SablonaPolozka"), 0)

    def test_neexistujici_polozka(self):
        prihlas(self.klient)
        odpoved = self.klient.get("/api/sablona/polozky/999")
        self.assertEqual(odpoved.status_code, 404)
        self.assertEqual(odpoved.json["code"], "NOT_FOUND")

    def test_obrazovka(self):
        prihlas(self.klient, "SABLONA_ZAPIS")
        odpoved = self.klient.get("/ui/sablona/ukazka")
        self.assertEqual(odpoved.status_code, 200)
        self.assertIn("api.post('/api/sablona/polozky'", odpoved.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
