"""Testy ostrova D bez databáze: čistá pravidla a HTTP kontrakt (400/403).

Služby pracují nad T-SQL, takže jejich testy jsou `test_dily_sql.py` (SQL Server). Tady zůstává
to, co databázi nepotřebuje: pravidla z `domena.py` a odpovědi, které skončí dřív, než se
dorazí do služby – chybějící/neznamé pole vstupu (400) a chybějící oprávnění (403).
"""
import unittest
from decimal import Decimal

from app.ostrovy import dily
from app.ostrovy.dily import domena
from app.platforma.chyby import AppError
from app.platforma.typy import PotrebaMista, Rozmer
from tests.pomocnik import ZakladTestuOstrova


class TestPotrebaMista(unittest.TestCase):
    def chyba(self, *args) -> set[str]:
        with self.assertRaises(AppError) as zachyceno:
            domena.potreba_mista(*args)
        self.assertEqual(zachyceno.exception.kod, "VALIDATION_ERROR")
        return {c["pole"] for c in zachyceno.exception.data["chyby"]}

    def test_bez_velikosti_a_pevne_velikosti(self):
        self.assertIsNone(domena.potreba_mista(None, None, None))
        self.assertEqual(domena.potreba_mista("V1", None, None), PotrebaMista("V1"))
        self.assertEqual(self.chyba("V1", Decimal("10"), None), {"potrebnaDelkaMm"})
        self.assertEqual(self.chyba(None, Decimal("10"), Decimal("10")), {"potrebnaDelkaMm"})

    def test_v6_potrebuje_oba_rozmery(self):
        self.assertEqual(domena.potreba_mista("V6", Decimal("800"), Decimal("400")),
                         PotrebaMista("V6", Rozmer(Decimal("800"), Decimal("400"))))
        self.assertEqual(self.chyba("V6", None, Decimal("400")), {"potrebnaDelkaMm"})
        self.assertEqual(self.chyba("V6", Decimal("0"), Decimal("0")), {"potrebnaDelkaMm", "potrebnaHloubkaMm"})


class TestKodyCiselniku(unittest.TestCase):
    def test_materialy_a_operace(self):
        self.assertEqual(domena.normalizuj_kod_ciselniku("materialy", " s 235 "), "S235")
        self.assertEqual(domena.normalizuj_kod_ciselniku("materialy", "1.4301"), "1.4301")
        self.assertEqual(domena.normalizuj_kod_ciselniku("operace", "laser"), "LASER")
        for typ, kod in [("materialy", "ocel č"), ("materialy", ""), ("operace", "LASER-1")]:
            with self.assertRaises(AppError, msg=(typ, kod)):
                domena.normalizuj_kod_ciselniku(typ, kod)

    def test_tloustky(self):
        self.assertEqual(domena.normalizuj_kod_ciselniku("tloustky", "3"), "3.00")
        self.assertEqual(domena.normalizuj_kod_ciselniku("tloustky", "2,5"), "2.50")
        for kod in ["0", "-1", "1000", "1.234", "abc", "NaN", "Infinity"]:
            with self.assertRaises(AppError, msg=kod) as zachyceno:
                domena.normalizuj_kod_ciselniku("tloustky", kod)
            self.assertEqual(zachyceno.exception.kod, "VALIDATION_ERROR")

    def test_neznamy_ciselnik(self):
        with self.assertRaises(AppError) as zachyceno:
            domena.normalizuj_kod_ciselniku("barvy", "RAL")
        self.assertEqual(zachyceno.exception.kod, "NOT_FOUND")

    def test_nazev_ma_jen_operace(self):
        domena.over_nazev_ciselniku("operace", "Laser", zakladani=True)
        domena.over_nazev_ciselniku("materialy", None, zakladani=True)
        for typ, nazev, zakladani in [("operace", None, True), ("operace", None, False), ("materialy", "Ocel", True)]:
            with self.assertRaises(AppError, msg=(typ, nazev)):
                domena.over_nazev_ciselniku(typ, nazev, zakladani=zakladani)


class TestOdmitnuteVstupy(ZakladTestuOstrova):
    """400 a 403 z HTTP vrstvy – služba se zavolat ani musí, proto stačí sqlite kostry."""

    ostrovy = (dily.OSTROV,)

    def test_nezname_pole_filtru(self):
        self.prihlas("DIL_CIST")
        self.assertEqual(self.chybna_pole(self.klient.get("/api/dily?barva=modra")), {"barva"})

    def test_chybi_povinny_udaj_cesky(self):
        self.prihlas("DIL_CIST", "KMEN_EDIT")
        obalka = self.over_chybu(self.klient.post("/api/dily", json={}), 400, "VALIDATION_ERROR")
        self.assertEqual(obalka["data"]["chyby"], [{"pole": "identifikacniCislo", "zprava": "Povinný údaj.",
                                                    "typ": "missing"}])

    def test_patch_bez_zmeneny_pole_a_s_neznamym_polem(self):
        self.prihlas("DIL_CIST", "KMEN_EDIT")
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/dily/12", json={"duvod": "nic"})), {"telo"})
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/dily/12", json={"duvod": "oprava",
                                                                                  "cislo": "X"})), {"cislo"})

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST")
        for volani in (lambda: self.klient.post("/api/dily", json={"identifikacniCislo": "X1"}),
                       lambda: self.klient.patch("/api/dily/1", json={"duvod": "oprava", "nazev": "X"}),
                       lambda: self.klient.post("/api/dily/1/deaktivovat", json={"duvod": "konec"}),
                       lambda: self.klient.patch("/api/dily/1/velikost", json={"velikostPoziceId": 1,
                                                                               "duvod": "větší"}),
                       lambda: self.klient.post("/api/dily/ciselniky/materialy", json={"kod": "X"})):
            with self.subTest(volani=volani):
                self.over_chybu(volani(), 403, "NO_PERMISSION")

    def test_bez_prihlaseni(self):
        self.over_chybu(self.klient.get("/api/dily"), 401, "NOT_AUTHENTICATED")


if __name__ == "__main__":
    unittest.main()
