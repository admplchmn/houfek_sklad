"""Testy ostrova D: čistá pravidla (hotová) a HTTP kontrakt nad vzorovými daty (kostra fáze 0)."""
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


class TestCteni(ZakladTestuOstrova):
    ostrovy = (dily.OSTROV,)

    def setUp(self):
        super().setUp()
        self.prihlas("DIL_CIST")

    def test_seznam_s_filtrem(self):
        data = self.over_ok(self.klient.get("/api/dily"))
        self.assertEqual((data["celkem"], data["strana"], data["velikost"]), (3, 1, 50))
        data = self.over_ok(self.klient.get("/api/dily?hledat=aar"))
        self.assertEqual([d["identifikacniCislo"] for d in data["polozky"]], ["AAR10044"])

    def test_detail_a_tvar_dat(self):
        data = self.over_ok(self.klient.get("/api/dily/12"))
        self.assertEqual(data["tloustkaMm"], 3.0)              # milimetry jako číslo (4.2)
        self.assertIsNone(data["potrebnaDelkaMm"])             # chybějící hodnota = null, klíč zůstává
        self.over_chybu(self.klient.get("/api/dily/999"), 404, "NOT_FOUND")

    def test_ciselniky(self):
        self.assertEqual(len(self.over_ok(self.klient.get("/api/dily/ciselniky/materialy"))["polozky"]), 6)
        self.over_chybu(self.klient.get("/api/dily/ciselniky/barvy"), 404, "NOT_FOUND")

    def test_neznamy_filtr_je_chyba(self):
        self.assertEqual(self.chybna_pole(self.klient.get("/api/dily?barva=modra")), {"barva"})


class TestSprava(ZakladTestuOstrova):
    ostrovy = (dily.OSTROV,)

    def setUp(self):
        super().setUp()
        self.prihlas("DIL_CIST", "KMEN_EDIT")

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST")
        self.over_chybu(self.klient.post("/api/dily", json={"identifikacniCislo": "X1"}), 403, "NO_PERMISSION")

    def test_zalozeni(self):
        novy = {"identifikacniCislo": " aar  99 ", "velikostPoziceId": 1, "poznamka": "Používat jen na servis."}
        data = self.over_ok(self.klient.post("/api/dily", json=novy))
        self.assertEqual((data["identifikacniCislo"], data["velikost"]), ("AAR 99", "V1"))
        self.assertEqual(data["poznamka"], "Používat jen na servis.")   # pokyn ze sloupce JINÉ INFORMACE (XLSM)
        self.over_chybu(self.klient.post("/api/dily", json={"identifikacniCislo": "aar10044"}), 409, "ALREADY_EXISTS")

    def test_zalozeni_v6_bez_rozmeru(self):
        odpoved = self.klient.post("/api/dily", json={"identifikacniCislo": "X6", "velikostPoziceId": 6})
        self.assertEqual(self.chybna_pole(odpoved), {"potrebnaDelkaMm", "potrebnaHloubkaMm"})

    def test_chyby_validace_cesky(self):
        obalka = self.over_chybu(self.klient.post("/api/dily", json={}), 400, "VALIDATION_ERROR")
        self.assertEqual(obalka["data"]["chyby"], [{"pole": "identifikacniCislo", "zprava": "Povinný údaj.",
                                                    "typ": "missing"}])

    def test_zmena_jen_poslanych_poli(self):
        data = self.over_ok(self.klient.patch("/api/dily/12", json={"duvod": "oprava názvu", "nazev": "Bok levý"}))
        self.assertEqual((data["nazev"], data["materialId"], data["poznamka"]), ("Bok levý", 1, None))
        data = self.over_ok(self.klient.patch("/api/dily/12", json={"duvod": "pokyn", "poznamka": "Musí být 1 mm."}))
        self.assertEqual(data["poznamka"], "Musí být 1 mm.")
        odpoved = self.klient.patch("/api/dily/12", json={"duvod": "nic"})
        self.assertEqual(self.chybna_pole(odpoved), {"telo"})
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/dily/12", json={"duvod": "oprava", "cislo": "X"})),
                         {"cislo"})

    def test_deaktivace_a_velikost(self):
        self.assertFalse(self.over_ok(self.klient.post("/api/dily/12/deaktivovat", json={"duvod": "konec výroby"}))
                         ["aktivni"])
        data = self.over_ok(self.klient.patch("/api/dily/12/velikost", json={
            "velikostPoziceId": 6, "potrebnaDelkaMm": 800, "potrebnaHloubkaMm": 400.5, "duvod": "nový přípravek"}))
        self.assertEqual((data["velikost"], data["potrebnaDelkaMm"], data["potrebnaHloubkaMm"]), ("V6", 800.0, 400.5))

    def test_ciselniky(self):
        self.assertEqual(self.over_ok(self.klient.post("/api/dily/ciselniky/tloustky", json={"kod": "2,75"}))["kod"],
                         "2.75")
        self.assertEqual(self.chybna_pole(self.klient.post("/api/dily/ciselniky/tloustky",
                                                           json={"kod": "4", "nazev": "čtyři"})), {"nazev"})
        self.over_chybu(self.klient.post("/api/dily/ciselniky/operace", json={"kod": "laser", "nazev": "Laser"}),
                        409, "ALREADY_EXISTS")
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/dily/ciselniky/operace/1",
                                                            json={"duvod": "oprava", "nazev": None})), {"nazev"})
        self.assertFalse(self.over_ok(self.klient.post("/api/dily/ciselniky/materialy/1/deaktivovat",
                                                       json={"duvod": "nepoužívá se"}))["aktivni"])


if __name__ == "__main__":
    unittest.main()
