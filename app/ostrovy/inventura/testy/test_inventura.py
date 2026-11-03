"""Testy ostrova F: pravidla inventury (hotová) a HTTP kontrakt nad vzorovými daty (kostra fáze 0)."""
import unittest

from app.ostrovy import dily, inventura, sklad, struktura
from app.ostrovy.inventura import domena
from app.platforma.chyby import AppError
from tests.pomocnik import ZakladTestuOstrova, rid

# Chyby ostrovů C, D a E projdou endpointy F – aplikace je musí znát.
OSTROVY = (struktura.OSTROV, dily.OSTROV, sklad.OSTROV, inventura.OSTROV)


def polozka(pozice=1, typ="DYN", ocekavany=(12, 30), skutecny=(12, 30), stav="ZAPSANO"):
    return domena.Polozka(pozice, f"P{pozice}", typ, ocekavany[0], ocekavany[1],
                          skutecny[0] if skutecny else None, skutecny[1] if skutecny else None, stav)


def kod_chyby(funkce, *args) -> str:
    try:
        funkce(*args)
    except AppError as chyba:
        return chyba.kod
    raise AssertionError("čekala se chyba")


class TestPravidla(unittest.TestCase):
    def test_vyhodnoceni(self):
        self.assertEqual(domena.vyhodnot(12, 30, 12, 30), ("SHODA", 0))
        self.assertEqual(domena.vyhodnot(12, 30, 12, 28), ("ROZDIL", -2))
        self.assertEqual(domena.vyhodnot(12, 30, None, 0), ("ROZDIL", -30))     # očekávaný díl chybí
        self.assertEqual(domena.vyhodnot(None, 0, None, 0), ("SHODA", 0))
        self.assertEqual(domena.vyhodnot(14, 12, 12, 3), ("JINY_DIL", -9))
        self.assertEqual(domena.vyhodnot(None, 0, 12, 3), ("JINY_DIL", 3))      # díl na pozici, která měla být prázdná

    def test_rozsah_zapis_a_stav(self):
        domena.over_rozsah("FULL", None)
        for typ, cil in [("FULL", 1), ("BOX", None)]:
            self.assertEqual(kod_chyby(domena.over_rozsah, typ, cil), "VALIDATION_ERROR")
        domena.over_zapis(None, 0)
        domena.over_zapis(12, 1)
        self.assertEqual(kod_chyby(domena.over_zapis, None, 5), "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(domena.over_zapis, 12, 0), "VALIDATION_ERROR")
        self.assertEqual(domena.stav_polozky(False, None, 7), "CEKA")
        self.assertEqual(domena.stav_polozky(True, 7, 7), "ZAPSANO")
        self.assertEqual(domena.stav_polozky(True, None, None), "ZAPSANO")
        self.assertEqual(domena.stav_polozky(True, 6, 7), "PREPOCITAT")

    def test_dokonceni(self):
        self.assertEqual(kod_chyby(domena.over_dokonceni, [polozka(skutecny=None, stav="CEKA")], {}),
                         "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(domena.over_dokonceni, [polozka(stav="PREPOCITAT")], {}), "INVENTORY_RECOUNT")
        jiny_ve_stat = polozka(5, "STAT", (14, 12), (12, 3))
        self.assertEqual(kod_chyby(domena.over_dokonceni, [jiny_ve_stat], {}), "VALIDATION_ERROR")
        domena.over_dokonceni([jiny_ve_stat], {5: "BPLE039-A"})
        domena.over_dokonceni([polozka(6, "DYN", (14, 12), (12, 3))], {})       # DYN: nalezený díl zůstává na místě

    def test_plan_korekci(self):
        plan = domena.planuj_korekce([
            polozka(1),                                          # shoda – nic
            polozka(2, ocekavany=(12, 30), skutecny=(12, 28)),   # rozdíl – nový stav
            polozka(3, ocekavany=(14, 5), skutecny=(12, 4)),     # jiný díl v DYN – odepsat a zaúčtovat na místě
            polozka(4, "STAT", (14, 12), (12, 3)),               # jiný díl ve STAT – odepsat a přičíst na cíl
            polozka(5, ocekavany=(None, 0), skutecny=None, stav="CEKA"),
        ], {4: 391})
        self.assertEqual(plan, [domena.Korekce(2, 12, 28), domena.Korekce(3, 14, 0), domena.Korekce(3, 12, 4),
                                domena.Korekce(4, 14, 0), domena.Korekce(391, 12, None, pricist_ks=3)])


class TestInventuraHttp(ZakladTestuOstrova):
    ostrovy = OSTROVY

    def setUp(self):
        super().setUp()
        self.prihlas("INVENTURA", "KOREKCE")

    def test_seznam_a_slepy_detail(self):
        self.assertEqual(self.over_ok(self.klient.get("/api/inventura"))["celkem"], 3)
        self.assertEqual(self.over_ok(self.klient.get("/api/inventura?stav="))["celkem"], 4)
        detail = self.over_ok(self.klient.get("/api/inventura/1"))
        stavy = {p["kod"]: (p["stavPolozky"], p["ocekavanyPocetKs"], p["vyhodnoceni"]) for p in detail["polozky"]}
        self.assertEqual(stavy, {"BPLE038-G": ("ZAPSANO", 0, "SHODA"), "BPLE038-H": ("CEKA", None, None),
                                 "BPLE038-CH": ("CEKA", None, None), "BPLE038-I": ("PREPOCITAT", 10, "ROZDIL")})
        self.assertEqual((detail["pocetPolozek"], detail["pocetZapsanych"], detail["pocetKPrepoctu"]), (4, 2, 1))
        self.over_chybu(self.klient.get("/api/inventura/99"), 404, "NOT_FOUND")

    def test_zalozeni(self):
        nova = self.over_ok(self.klient.post("/api/inventura", json={"typRozsahu": "BOX", "cilId": 39}))
        self.assertEqual([(p["kod"], p["stavPolozky"], p["ocekavanyDilId"]) for p in nova["polozky"]],
                         [("BPLE039-A", "CEKA", None)])
        otevrena = self.over_ok(self.klient.post("/api/inventura", json={"typRozsahu": "POZICE", "cilId": 152,
                                                                         "slepa": False}))
        self.assertEqual(otevrena["polozky"][0]["ocekavanyPocetKs"], 0)
        self.over_chybu(self.klient.post("/api/inventura", json={"typRozsahu": "UROVEN", "cilId": 3}),
                        409, "ALREADY_EXISTS")                                 # BPLE037-A je v inventuře 4
        self.assertEqual(self.chybna_pole(self.klient.post("/api/inventura", json={"typRozsahu": "BOX"})), {"cilId"})
        self.over_chybu(self.klient.post("/api/inventura", json={"typRozsahu": "UROVEN", "cilId": 9}), 404, "NOT_FOUND")

    def test_zapis(self):
        prazdna = self.over_ok(self.klient.post("/api/inventura/1/polozky/382", json={"skutecnyPocetKs": 0}))
        self.assertEqual((prazdna["vyhodnoceni"], prazdna["stavPolozky"], prazdna["ocekavanyPocetKs"]),
                         ("SHODA", "ZAPSANO", 0))
        prepocet = self.over_ok(self.klient.post("/api/inventura/1/polozky/384", json={
            "skutecnyDilId": 14, "skutecnyPocetKs": 8}))
        self.assertEqual((prepocet["vyhodnoceni"], prepocet["stavPolozky"]), ("SHODA", "ZAPSANO"))
        jiny = self.over_ok(self.klient.post("/api/inventura/1/polozky/383", json={
            "skutecnyDilId": 12, "skutecnyPocetKs": 4}))
        self.assertEqual((jiny["vyhodnoceni"], jiny["rozdilKs"]), ("JINY_DIL", 4))
        self.assertEqual(self.chybna_pole(self.klient.post("/api/inventura/1/polozky/382", json={
            "skutecnyPocetKs": 3})), {"skutecnyPocetKs"})
        self.over_chybu(self.klient.post("/api/inventura/1/polozky/101", json={"skutecnyPocetKs": 0}), 404, "NOT_FOUND")
        self.over_chybu(self.klient.post("/api/inventura/2/polozky/502", json={"skutecnyPocetKs": 0}),
                        409, "CONCURRENT_CHANGE")

    def test_dokonceni(self):
        def dokonci(inventura_id, **telo):
            return self.klient.post(f"/api/inventura/{inventura_id}/dokoncit", json={"requestId": rid(), **telo})

        self.over_chybu(dokonci(1), 400, "VALIDATION_ERROR")                   # H a CH nejsou zapsané
        obalka = self.over_chybu(dokonci(4), 409, "INVENTORY_RECOUNT")
        self.assertEqual(obalka["data"]["pozice"], ["BPLE037-A"])
        self.assertEqual(self.chybna_pole(dokonci(3)), {"cileJinyDil"})         # jiný díl ve STAT bez cíle (Q-17)
        self.assertEqual(self.chybna_pole(dokonci(3, cileJinyDil={"501": "BPLE038-G"})), {"cileJinyDil"})  # V3 ≠ V1
        vysledek = self.over_ok(dokonci(3, cileJinyDil={"501": "BPLE039-A"}))
        self.assertEqual((vysledek["pocetShod"], vysledek["pocetJinychDilu"], vysledek["pohyby"]),
                         (3, 1, [70001, 70002]))
        self.over_chybu(dokonci(2), 409, "CONCURRENT_CHANGE")
        self.prihlas("INVENTURA")
        self.over_chybu(dokonci(3, cileJinyDil={"501": "BPLE039-A"}), 403, "NO_PERMISSION")

    def test_zruseni(self):
        self.assertEqual(self.over_ok(self.klient.post("/api/inventura/1/zrusit", json={"duvod": "špatný rozsah"}))
                         ["stavInventury"], "ZRUSENA")
        self.over_chybu(self.klient.post("/api/inventura/2/zrusit", json={"duvod": "pozdě"}), 409, "CONCURRENT_CHANGE")


if __name__ == "__main__":
    unittest.main()
