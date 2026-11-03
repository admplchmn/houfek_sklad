"""Testy HTTP kontraktu ostrova C nad vzorovými daty (kostra fáze 0) a hledání míst v rozhraní."""
import unittest

from app.ostrovy import struktura
from app.ostrovy.struktura import rozhrani
from app.platforma.chyby import AppError
from tests.pomocnik import ZakladTestuOstrova, rid


class TestHledaniMist(unittest.TestCase):
    def kod_chyby(self, funkce, *args) -> str:
        with self.assertRaises(AppError) as zachyceno:
            funkce(None, *args)
        return zachyceno.exception.kod

    def test_najdi_vnitrni_pozici(self):
        self.assertEqual(rozhrani.najdi_vnitrni_pozici(None, " bple038-ch ").vnitrni_pozice_id, 383)
        self.assertEqual(rozhrani.najdi_vnitrni_pozici(None, "HOUFEK-PLE-R01-U04-BPLE038-CH").kod, "BPLE038-CH")
        self.assertEqual(self.kod_chyby(rozhrani.najdi_vnitrni_pozici, "HOUFEK-PLE-R01-U03-BPLE038-CH"),
                         "INVALID_BARCODE")                                   # starý štítek po přesunu (Q-02)
        self.assertEqual(self.kod_chyby(rozhrani.najdi_vnitrni_pozici, "BPLE038"), "WRONG_SCAN_LEVEL")
        self.assertEqual(self.kod_chyby(rozhrani.najdi_vnitrni_pozici, "HOUFEK-PLE-R01"), "WRONG_SCAN_LEVEL")
        self.assertEqual(self.kod_chyby(rozhrani.najdi_vnitrni_pozici, "AAR10044"), "INVALID_BARCODE")
        self.assertEqual(self.kod_chyby(rozhrani.najdi_vnitrni_pozici, "BPLE099-A"), "NOT_FOUND")

    def test_najdi_objekt_a_mista(self):
        self.assertEqual(rozhrani.najdi_objekt(None, "HOUFEK-PLE-R02").regal_id, 2)
        self.assertEqual(rozhrani.najdi_objekt(None, "BSTAT037").box_id, 137)
        self.assertEqual(rozhrani.najdi_objekt(None, "BSTAT037-1").vnitrni_pozice_id, 501)
        self.assertEqual(sorted(rozhrani.nacti_mista(None, [101, 501, 999])), [101, 501])
        self.assertEqual([m.kod for m in rozhrani.kandidatni_mista_dyn(None, 1, "V3")],
                         ["BPLE038-G", "BPLE038-H", "BPLE038-CH", "BPLE038-I"])

    def test_rozsah_inventury(self):
        self.assertEqual(rozhrani.pozice_v_rozsahu(None, "BOX", 137), [501, 502, 503, 504])
        vse = rozhrani.pozice_v_rozsahu(None, "FULL", None)
        self.assertEqual(rozhrani.pozice_v_rozsahu(None, "PRAC", 1), vse)
        self.assertEqual(self.kod_chyby(rozhrani.pozice_v_rozsahu, "FULL", 1), "VALIDATION_ERROR")
        self.assertEqual(self.kod_chyby(rozhrani.pozice_v_rozsahu, "SVET", None), "VALIDATION_ERROR")
        self.assertEqual(self.kod_chyby(rozhrani.pozice_v_rozsahu, "UROVEN", 9), "NOT_FOUND")


class TestCteni(ZakladTestuOstrova):
    ostrovy = (struktura.OSTROV,)

    def setUp(self):
        super().setUp()
        self.prihlas("DIL_CIST")

    def test_pracoviste_regaly_urovne(self):
        self.assertEqual(len(self.over_ok(self.klient.get("/api/struktura/pracoviste"))["polozky"]), 8)
        self.assertEqual(len(self.over_ok(self.klient.get("/api/struktura/pracoviste?aktivni="))["polozky"]), 8)
        regaly = self.over_ok(self.klient.get("/api/struktura/regaly?pracovisteId=1"))["polozky"]
        self.assertEqual([r["kod"] for r in regaly], ["HOUFEK-PLE-R01", "HOUFEK-PLE-R02"])
        urovne = self.over_ok(self.klient.get("/api/struktura/urovne?regalId=1"))["polozky"]
        self.assertEqual([(u["kodUrovne"], u["pocetBoxu"]) for u in urovne], [("U04", 2), ("U03", 2)])
        self.assertEqual(self.chybna_pole(self.klient.get("/api/struktura/urovne")), {"regalId"})

    def test_boxy_urovne_a_detail(self):
        boxy = self.over_ok(self.klient.get("/api/struktura/urovne/4/boxy"))["polozky"]
        self.assertEqual([(b["kodBoxu"], b["kodPoziceUrovne"]) for b in boxy], [("BPLE052", "P01"), ("BPLE038", "P02")])
        box = self.over_ok(self.klient.get("/api/struktura/boxy/37"))
        self.assertEqual((box["fullBoxKlic"], box["delkaMm"], box["pozice"][0]["kod"]),
                         ("HOUFEK-PLE-R01-U03-BPLE037", 400.0, "BPLE037-A"))
        self.over_chybu(self.klient.get("/api/struktura/boxy/999"), 404, "NOT_FOUND")
        self.over_chybu(self.klient.get("/api/struktura/urovne/999/boxy"), 404, "NOT_FOUND")

    def test_vnitrni_pozice_a_cleneni(self):
        pozice = self.over_ok(self.klient.get("/api/struktura/vnitrni-pozice/152"))
        self.assertEqual((pozice["adresa"], pozice["rozmerC7DelkaMm"], pozice["blokovano"]),
                         ("HOUFEK-PLE-R01-U04-BPLE052-R", 800.0, False))
        cleneni = self.over_ok(self.klient.get("/api/struktura/cleneni"))["polozky"]
        self.assertEqual([c["kodCleneni"] for c in cleneni], ["C1", "C2", "C3", "C4", "C5", "C6", "C7"])
        self.assertEqual([p["dynKod"] for p in cleneni[3]["pozice"]], ["G", "H", "CH", "I"])


class TestBlokace(ZakladTestuOstrova):
    ostrovy = (struktura.OSTROV,)

    def setUp(self):
        super().setUp()
        self.prihlas("BLOKACE")

    def blokuj(self, kod, blokovat=True, request_id=None):
        return self.klient.post("/api/struktura/blokace", json={
            "requestId": request_id or rid(), "kod": kod, "blokovat": blokovat, "duvod": "poškozený box"})

    def test_box_a_pozice(self):
        odpoved = self.blokuj("BPLE037")
        data = self.over_ok(odpoved)
        self.assertEqual((data["typ"], data["kod"], data["vnitrniPoziceId"], data["zmeneno"]),
                         ("BOX", "BPLE037", None, True))
        self.assertIsNotNone(odpoved.json["transakceId"])
        data = self.over_ok(self.blokuj("HOUFEK-PLE-R02-U01-BSTAT037-1"))
        self.assertEqual((data["typ"], data["kod"], data["vnitrniPoziceId"]), ("POZICE", "BSTAT037-1", 501))

    def test_stejny_request_id_vrati_stejny_vysledek(self):
        request_id = rid()
        prvni = self.blokuj("BPLE037", request_id=request_id).json
        druhy = self.blokuj("BPLE037", request_id=request_id).json
        self.assertEqual((druhy["transakceId"], druhy["data"]), (prvni["transakceId"], prvni["data"]))
        self.over_chybu(self.blokuj("BPLE038", request_id=request_id), 400, "VALIDATION_ERROR")

    def test_beze_zmeny_je_varovani(self):
        odpoved = self.blokuj("BPLE037-A", blokovat=False)
        self.assertFalse(self.over_ok(odpoved)["zmeneno"])
        self.assertEqual([v["code"] for v in odpoved.json["varovani"]], ["BEZ_ZMENY"])

    def test_chyby(self):
        self.assertEqual(self.chybna_pole(self.blokuj("HOUFEK-PLE-R01")), {"kod"})
        self.over_chybu(self.blokuj("AAR10044"), 400, "INVALID_BARCODE")
        self.over_chybu(self.blokuj("HOUFEK-PLE-R01-U03-BPLE038"), 400, "INVALID_BARCODE")
        self.over_chybu(self.blokuj("BPLE099"), 404, "NOT_FOUND")
        self.assertEqual(self.chybna_pole(self.klient.post("/api/struktura/blokace", json={
            "kod": "BPLE037", "blokovat": True, "duvod": "test"})), {"requestId"})
        self.prihlas("DIL_CIST")
        self.over_chybu(self.blokuj("BPLE037"), 403, "NO_PERMISSION")


class TestSprava(ZakladTestuOstrova):
    ostrovy = (struktura.OSTROV,)

    def setUp(self):
        super().setUp()
        self.prihlas("BOX_EDIT")

    def post(self, cesta, **telo):
        return self.klient.post(f"/api/struktura{cesta}", json=telo)

    def test_pracoviste(self):
        self.assertEqual(self.over_ok(self.post("/pracoviste", kodPracoviste=" 3mo "))["kodPracoviste"], "3MO")
        self.over_chybu(self.post("/pracoviste", kodPracoviste="ple"), 409, "ALREADY_EXISTS")
        self.assertEqual(self.chybna_pole(self.post("/pracoviste", kodPracoviste="PLEX")), {"kodPracoviste"})
        zmena = self.klient.patch("/api/struktura/pracoviste/1", json={"nazev": "Lisovna", "duvod": "přejmenování"})
        self.assertEqual(self.over_ok(zmena)["nazev"], "Lisovna")
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/struktura/pracoviste/1", json={
            "kodPracoviste": "PLX", "duvod": "kód je v barcode"})), {"kodPracoviste"})
        self.over_chybu(self.post("/pracoviste/1/deaktivovat", duvod="zrušeno"), 409, "NOT_EMPTY")
        self.assertFalse(self.over_ok(self.post("/pracoviste/3/deaktivovat", duvod="zrušeno"))["aktivni"])

    def test_regal_a_uroven(self):
        regal = self.over_ok(self.post("/regaly", pracovisteId=1, kodRegalu="r3"))
        self.assertEqual((regal["kodRegalu"], regal["kod"]), ("R03", "HOUFEK-PLE-R03"))
        self.over_chybu(self.post("/regaly", pracovisteId=1, kodRegalu="R01"), 409, "ALREADY_EXISTS")
        self.over_chybu(self.post("/regaly", pracovisteId=99, kodRegalu="R01"), 404, "NOT_FOUND")
        uroven = self.over_ok(self.post("/urovne", regalId=1, kodUrovne="u5", delkaPlochyMm=2400, hloubkaPlochyMm=800))
        self.assertEqual((uroven["kodUrovne"], uroven["poradi"], uroven["pocetBoxu"]), ("U05", 5, 0))
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/struktura/urovne/3", json={
            "poradi": None, "duvod": "oprava"})), {"poradi"})
        self.over_chybu(self.post("/urovne/4/deaktivovat", duvod="zrušeno"), 409, "NOT_EMPTY")
        self.assertFalse(self.over_ok(self.post("/urovne/9/deaktivovat", duvod="zrušeno"))["aktivni"])
        self.over_chybu(self.post("/regaly/3/deaktivovat", duvod="zrušeno"), 409, "NOT_EMPTY")


class TestOperaceBoxu(ZakladTestuOstrova):
    ostrovy = (struktura.OSTROV,)

    def setUp(self):
        super().setUp()
        self.prihlas("BOX_EDIT")

    def post(self, cesta, **telo):
        return self.klient.post(f"/api/struktura{cesta}", json=telo)

    def test_zalozeni_boxu(self):
        box = self.over_ok(self.post("/urovne/4/boxy", typBoxu="DYN", cleneniId=4, delkaMm=400, hloubkaMm=360))
        self.assertEqual((box["kodBoxu"], box["poradi"], box["kodPoziceUrovne"], box["fullBoxKlic"]),
                         ("BPLE053", 3, "P03", "HOUFEK-PLE-R01-U04-BPLE053"))
        self.assertEqual([p["kod"] for p in box["pozice"]], ["BPLE053-G", "BPLE053-H", "BPLE053-CH", "BPLE053-I"])
        stat = self.over_ok(self.post("/urovne/4/boxy", typBoxu="STAT", cleneniId=4, delkaMm=400, hloubkaMm=360,
                                      poradi=1))
        self.assertEqual((stat["kodBoxu"], stat["poradi"], [p["kodPozice"] for p in stat["pozice"]]),
                         ("BSTAT038", 1, ["4", "3", "1", "2"]))
        c7 = self.over_ok(self.post("/urovne/3/boxy", typBoxu="DYN", cleneniId=7, delkaMm=900, hloubkaMm=450))
        self.assertEqual((c7["pozice"][0]["kodPozice"], c7["pozice"][0]["rozmerC7DelkaMm"]), ("R", 900.0))

    def test_zalozeni_boxu_chyby(self):
        self.over_chybu(self.post("/urovne/4/boxy", typBoxu="DYN", cleneniId=1, delkaMm=400, hloubkaMm=360,
                                  cisloBoxu=37), 409, "ALREADY_EXISTS")
        self.assertEqual(self.chybna_pole(self.post("/urovne/4/boxy", typBoxu="DYN", cleneniId=1, delkaMm=400,
                                                    hloubkaMm=360, poradi=4)), {"poradi"})
        self.assertEqual(self.chybna_pole(self.post("/urovne/4/boxy", typBoxu="MIX", cleneniId=1, delkaMm=0,
                                                    hloubkaMm=360)), {"typBoxu", "delkaMm"})
        self.over_chybu(self.post("/urovne/4/boxy", typBoxu="DYN", cleneniId=8, delkaMm=400, hloubkaMm=360),
                        404, "NOT_FOUND")

    def test_vymena_a_presun(self):
        self.over_chybu(self.post("/boxy/37/vymena", typBoxu="DYN", cleneniId=1, delkaMm=400, hloubkaMm=360,
                                  duvod="prasklý box"), 409, "NOT_EMPTY")
        novy = self.over_ok(self.post("/boxy/52/vymena", typBoxu="DYN", cleneniId=2, delkaMm=400, hloubkaMm=360,
                                      duvod="prasklý box"))
        self.assertEqual((novy["kodBoxu"], novy["poradi"], novy["kodCleneni"]), ("BPLE053", 1, "C2"))
        box = self.over_ok(self.post("/boxy/38/presun", cilUrovenId=3, duvod="nové uspořádání"))
        self.assertEqual((box["fullBoxKlic"], box["poradi"], box["pozice"][0]["kod"]),
                         ("HOUFEK-PLE-R01-U03-BPLE038", 3, "BPLE038-G"))     # na konec za BPLE037, BPLE039
        self.assertEqual(self.chybna_pole(self.post("/boxy/38/presun", cilUrovenId=4, duvod="test")), {"cilUrovenId"})
        self.assertEqual(self.chybna_pole(self.post("/boxy/38/presun", cilUrovenId=9, duvod="jiné pracoviště")),
                         {"cilUrovenId"})                                     # DYN box mimo své pracoviště (Q-30)
        stat = self.over_ok(self.post("/boxy/137/presun", cilUrovenId=9, duvod="STAT smí kamkoli"))
        self.assertEqual(stat["fullBoxKlic"], "HOUFEK-1SV-R01-U01-BSTAT037")

    def test_poradi_rekonfigurace_deaktivace(self):
        poradi = self.over_ok(self.post("/boxy/38/poradi", novePoradi=1, duvod="u uličky"))["polozky"]
        self.assertEqual([(b["kodBoxu"], b["kodPoziceUrovne"]) for b in poradi],
                         [("BPLE038", "P01"), ("BPLE052", "P02")])
        self.assertEqual(self.chybna_pole(self.post("/boxy/38/poradi", novePoradi=3, duvod="test")), {"novePoradi"})
        box = self.over_ok(self.post("/boxy/52/rekonfigurace", cleneniId=2, duvod="menší díly"))
        self.assertEqual([p["kod"] for p in box["pozice"]], ["BPLE052-B", "BPLE052-C"])
        obalka = self.over_chybu(self.post("/boxy/38/rekonfigurace", cleneniId=1, duvod="test"), 409, "NOT_EMPTY")
        self.assertIn("zásoba na BPLE038-I", obalka["message"])
        self.assertEqual(self.chybna_pole(self.post("/boxy/38/rekonfigurace", cleneniId=4, duvod="test")),
                         {"cleneniId"})
        obalka = self.over_chybu(self.post("/boxy/137/rekonfigurace", cleneniId=1, duvod="test"), 409, "NOT_EMPTY")
        self.assertIn("statické přiřazení na BSTAT037-1, BSTAT037-2", obalka["message"])
        self.assertFalse(self.over_ok(self.post("/boxy/52/deaktivovat", duvod="vyřazen"))["aktivni"])
        self.over_chybu(self.post("/boxy/37/deaktivovat", duvod="vyřazen"), 409, "NOT_EMPTY")

    def test_rozmer_c7(self):
        pozice = self.over_ok(self.post("/vnitrni-pozice/152/rozmer-c7", delkaMm=900, hloubkaMm=450.5,
                                        duvod="přepážka"))
        self.assertEqual((pozice["rozmerC7DelkaMm"], pozice["rozmerC7HloubkaMm"]), (900.0, 450.5))
        self.assertEqual(self.chybna_pole(self.post("/vnitrni-pozice/152/rozmer-c7", delkaMm=1200, hloubkaMm=450,
                                                    duvod="přepážka")), {"delkaMm"})
        self.over_chybu(self.post("/vnitrni-pozice/101/rozmer-c7", delkaMm=100, hloubkaMm=100, duvod="test"),
                        400, "VALIDATION_ERROR")

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST")
        self.over_chybu(self.post("/boxy/52/deaktivovat", duvod="vyřazen"), 403, "NO_PERMISSION")


if __name__ == "__main__":
    unittest.main()
