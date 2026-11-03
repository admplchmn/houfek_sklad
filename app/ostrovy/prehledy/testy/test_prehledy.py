"""Testy ostrova G: pravidla přehledů (hotová) a HTTP kontrakt nad vzorovými daty ostrovů B–E."""
import unittest

from app.ostrovy import dily, identita, prehledy, sklad, struktura
from app.ostrovy.prehledy import domena, ukazky
from tests.pomocnik import ZakladTestuOstrova

OSTROVY = (identita.OSTROV, struktura.OSTROV, dily.OSTROV, sklad.OSTROV, prehledy.OSTROV)


class TestPravidla(unittest.TestCase):
    def test_laser_q22(self):
        self.assertEqual(domena.doporuceni_laser(30, 12, 0, None, odecitat_dyn=False), (18, 18))   # příklad kap. 14
        self.assertEqual(domena.doporuceni_laser(40, 12, 8, 20, odecitat_dyn=False), (28, 40))     # na celé dávky
        self.assertEqual(domena.doporuceni_laser(40, 12, 8, 20, odecitat_dyn=True), (28, 20))
        self.assertEqual(domena.doporuceni_laser(40, 12, 30, 20, odecitat_dyn=True), (28, 0))
        self.assertEqual(domena.doporuceni_laser(10, 12, 0, 20, odecitat_dyn=False), (0, 0))

    def test_souhrn_a_text_umisteni(self):
        self.assertEqual(domena.souhrn_zasob(["OK", "VYCERPANO", "OK"]),
                         {"sledovane": 3, "OK": 2, "NA_MINIMU": 0, "POD_MINIMEM": 0, "VYCERPANO": 1})
        self.assertEqual([domena.text_umisteni(True, 2), domena.text_umisteni(True, 1), domena.text_umisteni(True, 0),
                          domena.text_umisteni(False, 3), domena.text_umisteni(False, 0)],
                         ["STAT + 2× DYN", "STAT + DYN", "STAT", "3× DYN", "–"])

    def test_poradi_umisteni(self):
        klice = sorted([("DYN", "BPLE010", 1), ("STAT", "BSTAT900", 4), ("DYN", "BPLE002", 2)],
                       key=lambda u: domena.poradi_umisteni(*u))
        self.assertEqual([k[1] for k in klice], ["BSTAT900", "BPLE002", "BPLE010"])


class TestPrehledy(ZakladTestuOstrova):
    ostrovy = OSTROVY

    def setUp(self):
        super().setUp()
        self.prihlas("DIL_CIST")

    def get(self, cesta):
        return self.over_ok(self.klient.get(f"/api/prehledy{cesta}"))

    def test_sken(self):
        pozice = self.get("/sken/BPLE038-I")
        self.assertEqual((pozice["presny"], pozice["polozky"][0]["popis"]), (True, "BX500-21 · 8 ks"))
        self.assertEqual(pozice["polozky"][0]["zvyrazneni"], {"regalId": 1, "urovenId": 4, "boxId": 38,
                                                              "vnitrniPoziceId": 384})
        # zadání 12.2: po skenu zdrojové pozice obsluha vidí díl a stav
        self.assertEqual(pozice["polozky"][0]["obsah"], {"dilId": 14, "identifikacniCislo": "BX500-21", "pocetKs": 8})
        dil = self.get("/sken/bx500-21")["polozky"][0]
        self.assertEqual((dil["typ"], dil["adresa"]), ("DIL", "HOUFEK-PLE-R02-U01-BSTAT037-1"))   # STAT první
        self.assertIsNone(dil["obsah"])
        self.assertEqual(self.get("/sken/AAR")["presny"], False)
        self.over_chybu(self.klient.get("/api/prehledy/sken/BPLE099-A"), 404, "NOT_FOUND")

    def test_hledani_s_filtry(self):
        self.assertEqual([v["kod"] for v in self.get("/hledat?q=a")["polozky"]], ["AAR10044", "CE21RA 10 100194"])
        self.assertEqual([v["kod"] for v in self.get("/hledat?q=a&typBoxu=DYN")["polozky"]], ["AAR10044"])
        self.assertEqual([v["kod"] for v in self.get("/hledat?q=a&materialId=2")["polozky"]], ["CE21RA 10 100194"])
        self.assertEqual([v["kod"] for v in self.get("/hledat?q=motor&stavZasoby=OK")["polozky"]], ["BX500-21"])
        self.assertEqual(self.get("/hledat?q=HOUFEK-PLE-R01")["polozky"][0]["typ"], "REGAL")
        self.assertEqual(self.chybna_pole(self.klient.get("/api/prehledy/hledat")), {"q"})

    def test_rozlozeni(self):
        data = self.get("/urovne/4/rozlozeni")
        boxy = {b["kodBoxu"]: (b["stavBoxu"], b["barva"], b["xMm"]) for b in data["boxy"]}
        self.assertEqual(boxy, {"BPLE052": ("VOLNY", "ZELENA", 20.0), "BPLE038": ("OBSAZENY", "MODRA", 1040.0)})
        # zadání 17.2: výstup obsahuje seřazené Pozice P01…Pn
        self.assertEqual([b["kodPoziceUrovne"] for b in data["boxy"]], ["P01", "P02"])
        i = next(p for p in data["boxy"][1]["pozice"] if p["kodPozice"] == "I")
        self.assertEqual((i["identifikacniCislo"], i["pocetKs"]), ("BX500-21", 8))
        # zadání 17: popup pozice nese i odkaz do Vaultu; prázdná pozice ho nemá
        self.assertEqual(i["vaultUrl"], "https://vault.example/BX500-21.pdf")
        self.assertIsNone(data["boxy"][0]["pozice"][0]["vaultUrl"])
        self.assertEqual(self.get("/urovne/7/rozlozeni")["boxy"][0]["barva"], "SEDA")

    def test_karta(self):
        karta = self.get("/dily/14/karta")
        self.assertEqual((karta["stat"]["kod"], karta["stat"]["stavZasoby"], karta["dynKs"], karta["celkemKs"]),
                         ("BSTAT037-1", "OK", 8, 20))
        self.assertEqual([u["kod"] for u in karta["umisteni"]], ["BSTAT037-1", "BPLE038-I"])
        # zadání 15: „BSTAT037 | aktuálně 12 | min … | max …“ a „Chybí do maxima“
        self.assertEqual((karta["stat"]["kodBoxu"], karta["stat"]["stavKs"], karta["stat"]["chybiDoMaximaKs"]),
                         ("BSTAT037", 12, 28))
        self.assertEqual([p["pohybId"] for p in karta["posledniPohyby"]], [5004, 5003, 5002])
        self.assertIsNone(self.get("/dily/12/karta")["stat"])
        self.over_chybu(self.klient.get("/api/prehledy/dily/99/karta"), 404, "NOT_FOUND")

    def test_zasoby_a_laser(self):
        data = self.get("/zasoby")
        self.assertEqual(data["souhrn"], {"sledovane": 2, "ok": 1, "naMinimu": 0, "podMinimem": 0, "vycerpano": 1})
        self.assertEqual([(z["identifikacniCislo"], z["umisteni"]) for z in data["polozky"]],
                         [("CE21RA 10 100194", "STAT"), ("BX500-21", "STAT + DYN")])          # nejhorší první
        # zadání 13.1: klik na konkrétní umístění → každé umístění zvlášť se zvýrazněním
        self.assertEqual([m["kod"] for m in data["polozky"][1]["mista"]], ["BSTAT037-1", "BPLE038-I"])
        problemy = self.get("/zasoby?jenProblemove=true")
        self.assertEqual((problemy["celkem"], problemy["souhrn"]["sledovane"]), (1, 2))
        # filtr „pouze díly s aktivním STAT umístěním“ vypnutý: přibude díl jen v DYN, bez stavu, na konci
        vse = self.get("/zasoby?jenSeStat=false")
        posledni = vse["polozky"][-1]
        self.assertEqual((vse["celkem"], vse["souhrn"]["sledovane"]), (3, 2))
        self.assertEqual((posledni["identifikacniCislo"], posledni["stavZasoby"], posledni["umisteni"],
                          posledni["zvyrazneni"]["vnitrniPoziceId"]), ("AAR10044", None, "DYN", 101))
        laser = self.get("/laser")["polozky"]
        self.assertEqual([(r["identifikacniCislo"], r["chybiVeStatKs"], r["doporucenoKs"]) for r in laser],
                         [("BX500-21", 28, 40), ("CE21RA 10 100194", 20, 20)])
        self.assertEqual(self.get("/laser?odecitatDyn=true")["polozky"][0]["doporucenoKs"], 20)

    def test_historie_a_transakce(self):
        data = self.get("/pohyby?kod=BPLE038-I")
        self.assertEqual([(p["pohybId"], p["celeJmeno"]) for p in data["polozky"]], [(5004, "Jan Novák"),
                                                                                  (5002, "Jan Novák")])
        self.assertEqual(self.get("/pohyby?od=2026-10-30")["celkem"], 1)
        transakce_id = str(ukazky.transakce_id(5003))
        detail = self.get(f"/transakce/{transakce_id}")
        self.assertEqual((detail["typOperace"], detail["pohyby"][0]["kod"]), ("PRIJEM_STAT", "BSTAT037-1"))
        self.assertIsNone(self.klient.get(f"/api/prehledy/transakce/{transakce_id}").json["transakceId"])
        self.over_chybu(self.klient.get("/api/prehledy/transakce/00000000-0000-4000-8000-000000000000"),
                        404, "NOT_FOUND")

    def test_ciselniky(self):
        data = self.get("/ciselniky")
        self.assertEqual((len(data["pracoviste"]), len(data["typyPohybu"]), data["typyBoxu"]), (8, 7, ["DYN", "STAT"]))


if __name__ == "__main__":
    unittest.main()
