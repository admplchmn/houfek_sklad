"""Testy ostrova E: čistá pravidla (hotová) a HTTP kontrakt skladových operací nad vzorovými daty."""
import re
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path

from app.ostrovy import dily, sklad, struktura
from app.ostrovy.dily import ukazky as dily_vzory
from app.ostrovy.sklad import domena
from app.ostrovy.sklad.rozhrani import ObsahInfo, StatMistoInfo
from app.ostrovy.struktura import ukazky as mista
from app.platforma.chyby import AppError
from app.platforma.typy import Kontext, PotrebaMista
from tests.pomocnik import ZakladTestuOstrova, rid

POHLEDY_E = Path(sklad.__file__).with_name("pohledy.sql")
# Chyby ostrovů C a D (INVALID_BARCODE, WRONG_SCAN_LEVEL …) projdou endpointy E – aplikace je musí znát.
OSTROVY = (struktura.OSTROV, dily.OSTROV, sklad.OSTROV)
V1, V3 = PotrebaMista("V1"), PotrebaMista("V3")
MISTO_DYN_V3 = mista.MISTA[381]          # BPLE038-G, prázdná
MISTO_STAT = mista.MISTA[501]            # BSTAT037-1


def kod_chyby(funkce, *args, **kwargs) -> str:
    try:
        funkce(*args, **kwargs)
    except AppError as chyba:
        return chyba.kod
    raise AssertionError("čekala se chyba")


def kdo(*opravneni: str, role: str = "SKL") -> Kontext:
    return Kontext(1, None, role, frozenset(opravneni))


class TestZasobaAUpozorneni(unittest.TestCase):
    def test_stav_zasoby_shodny_s_pohledem_v_zasoba_dilu(self):
        """CASE v pohledu v_ZasobaDilu (T-SQL) dává pro každý stav a minimum stejný výsledek jako Python."""
        sql = POHLEDY_E.read_text(encoding="utf-8")
        case = re.search(r"CAST\((CASE .*? END) AS VARCHAR", sql, re.S)[1]
        case = case.replace("stat.StatKs", "s").replace("stat.MinimalniPocetKs", "m")
        db = sqlite3.connect(":memory:")
        for stav in range(0, 13):
            for minimum in (0, 1, 5, 10, 12):
                ze_sql = db.execute(f"SELECT {case} FROM (SELECT ? AS s, ? AS m)", (stav, minimum)).fetchone()[0]
                self.assertEqual(ze_sql, domena.stav_zasoby(stav, minimum), (stav, minimum))

    def test_upozorneni_bez_spamu(self):
        v = domena.vyhodnot_upozorneni
        self.assertEqual(v(7, 10, None), domena.AkceUpozorneni("ZALOZIT", "POD_MINIMEM"))
        self.assertEqual(v(0, 10, "POD_MINIMEM"), domena.AkceUpozorneni("AKTUALIZOVAT", "VYCERPANO"))
        self.assertEqual(v(6, 10, "POD_MINIMEM").akce, "NIC")               # další výdej beze změny stavu
        self.assertEqual(v(10, 10, "POD_MINIMEM"), domena.AkceUpozorneni("AKTUALIZOVAT", "NA_MINIMU"))
        self.assertEqual(v(11, 10, "NA_MINIMU").akce, "UZAVRIT")            # doplnění nad minimum
        self.assertEqual(v(11, 10, None).akce, "NIC")
        self.assertEqual(v(0, 0, None), domena.AkceUpozorneni("ZALOZIT", "VYCERPANO"))   # N-08

    def test_mekke_maximum(self):
        self.assertIsNone(domena.varovani_nad_maximem(40, 40, "BSTAT037-1"))
        self.assertIsNone(domena.varovani_nad_maximem(400, None, "BSTAT037-1"))
        self.assertEqual(domena.varovani_nad_maximem(41, 40, "BSTAT037-1").kod, "NAD_MAXIMEM")


class TestKontrolyOperaci(unittest.TestCase):
    def test_cil_prijmu_dyn(self):
        over = domena.over_cil_prijmu_dyn
        over(MISTO_DYN_V3, V3, None)
        self.assertEqual(kod_chyby(over, MISTO_DYN_V3, None, None), "PART_HAS_NO_SIZE")
        self.assertEqual(kod_chyby(over, MISTO_STAT, V3, None), "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(over, replace(MISTO_DYN_V3, blokovano=True), V3, None), "POSITION_BLOCKED")
        self.assertEqual(kod_chyby(over, MISTO_DYN_V3, V3, ObsahInfo(381, 14, 1)), "POSITION_OCCUPIED")
        self.assertEqual(kod_chyby(over, MISTO_DYN_V3, V1, None), "SIZE_MISMATCH")

    def test_cil_uskladneni_stat(self):
        over = domena.over_cil_uskladneni_stat
        stat = StatMistoInfo(1, 14, 501, 10, 25, 40)
        over(MISTO_STAT, stat, 14, ObsahInfo(501, 14, 12))
        self.assertEqual(kod_chyby(over, MISTO_DYN_V3, stat, 14, None), "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(over, MISTO_STAT, None, 14, None), "WRONG_PART")
        self.assertEqual(kod_chyby(over, MISTO_STAT, stat, 12, None), "WRONG_PART")
        self.assertEqual(kod_chyby(over, replace(MISTO_STAT, blokovano=True), stat, 14, None), "POSITION_BLOCKED")

    def test_zdroj(self):
        obsah = ObsahInfo(501, 14, 12)
        self.assertEqual(domena.over_zdroj(MISTO_STAT, obsah, 12), obsah)
        self.assertEqual(kod_chyby(domena.over_zdroj, MISTO_STAT, obsah, 13), "INSUFFICIENT_STOCK")
        self.assertEqual(kod_chyby(domena.over_zdroj, MISTO_STAT, None, 1), "INSUFFICIENT_STOCK")
        self.assertEqual(kod_chyby(domena.over_zdroj, MISTO_STAT, obsah, 1, ocekavany_stav_ks=11),
                         "CONCURRENT_CHANGE")
        self.assertEqual(kod_chyby(domena.over_zdroj, MISTO_STAT, obsah, 1, dil_id=12), "WRONG_PART")
        self.assertEqual(kod_chyby(domena.over_zdroj, replace(MISTO_STAT, blokovano=True), obsah, 1),
                         "POSITION_BLOCKED")

    def test_presun_cele_davky(self):
        zdroj, cil = mista.MISTA[101], mista.MISTA[391]
        davka = ObsahInfo(101, 12, 30)
        self.assertEqual(domena.over_presun(zdroj, cil, davka, None, V1), davka)
        self.assertEqual(kod_chyby(domena.over_presun, zdroj, zdroj, davka, None, V1), "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(domena.over_presun, MISTO_STAT, cil, davka, None, V1), "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(domena.over_presun, zdroj, replace(cil, pracoviste="1SV"), davka, None, V1),
                         "VALIDATION_ERROR")                                  # mezi pracovišti výdej + příjem (Q-07)
        self.assertEqual(kod_chyby(domena.over_presun, zdroj, cil, None, None, None), "INSUFFICIENT_STOCK")

    def test_kandidati_podle_cisla_boxu(self):
        a = replace(MISTO_DYN_V3, vnitrni_pozice_id=1, kod_boxu="BPLE010", poradi_v_boxu=1)
        b = replace(MISTO_DYN_V3, vnitrni_pozice_id=2, kod_boxu="BPLE002", poradi_v_boxu=2)
        c = replace(MISTO_DYN_V3, vnitrni_pozice_id=3, kod_boxu="BPLE002", poradi_v_boxu=1)
        jiny_regal = replace(MISTO_DYN_V3, vnitrni_pozice_id=4, kod_boxu="BPLE001", regal_id=2)
        blokovana = replace(MISTO_DYN_V3, vnitrni_pozice_id=5, kod_boxu="BPLE001", blokovano=True)
        vyber = domena.vyber_kandidaty([a, b, c, jiny_regal, blokovana], V3, obsazene={2}, regal_id=1)
        self.assertEqual([m.vnitrni_pozice_id for m in vyber], [3, 1, 4])
        self.assertEqual(kod_chyby(domena.vyber_kandidaty, [a], None, set(), 1), "PART_HAS_NO_SIZE")

    def test_stat_misto(self):
        self.assertEqual(kod_chyby(domena.over_min_opt_max, 10, 5, 40), "VALIDATION_ERROR")
        domena.over_min_opt_max(0, None, None)
        over = domena.over_stat_pozici
        over(MISTO_STAT, V3, prepsat_velikost=False, kdo=kdo(), duvod=None)
        over(MISTO_STAT, None, prepsat_velikost=False, kdo=kdo(), duvod=None)          # díl bez velikosti (Q-26)
        self.assertEqual(kod_chyby(over, MISTO_DYN_V3, V3, prepsat_velikost=False, kdo=kdo(), duvod=None),
                         "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(over, MISTO_STAT, V1, prepsat_velikost=False, kdo=kdo(), duvod=None),
                         "SIZE_MISMATCH")
        self.assertEqual(kod_chyby(over, MISTO_STAT, V1, prepsat_velikost=True, kdo=kdo(), duvod="x"),
                         "NO_PERMISSION")
        self.assertEqual(kod_chyby(over, MISTO_STAT, V1, prepsat_velikost=True, kdo=kdo(role="TECH"), duvod=None),
                         "VALIDATION_ERROR")
        over(MISTO_STAT, V1, prepsat_velikost=True, kdo=kdo(role="TECH"), duvod="přípravek se vejde")

    def test_zpusob_potvrzeni(self):
        domena.over_zpusob_potvrzeni("SKEN", kdo())
        domena.over_zpusob_potvrzeni("RUCNE", kdo("RUCNI_POTVRZENI"))
        self.assertEqual(kod_chyby(domena.over_zpusob_potvrzeni, "RUCNE", kdo()), "NO_PERMISSION")


class TestOperace(ZakladTestuOstrova):
    ostrovy = OSTROVY

    def setUp(self):
        super().setUp()
        self.prihlas("DIL_CIST", "SKLAD_PRIJEM", "SKLAD_VYDEJ", "SKLAD_PRESUN")

    def post(self, cesta, **telo):
        telo.setdefault("requestId", rid())
        return self.klient.post(f"/api/sklad{cesta}", json=telo)

    def test_kandidati(self):
        data = self.over_ok(self.klient.get("/api/sklad/kandidati-dyn?dilId=14&regalId=1"))
        kody = [k["kod"] for k in data["polozky"]]
        self.assertEqual(kody, ["BPLE038-G", "BPLE038-H", "BPLE038-CH"])            # BPLE038-I je obsazená
        data = self.over_ok(self.klient.get("/api/sklad/kandidati-dyn?dilId=12&kodRegalu=houfek-ple-r01"))
        self.assertEqual([k["kod"] for k in data["polozky"]], ["BPLE039-A"])
        jinde = self.over_ok(self.klient.get(
            "/api/sklad/kandidati-dyn?dilId=14&regalId=2&vcetneOstatnichRegalu=true"))
        self.assertTrue(all(k["jinyRegal"] for k in jinde["polozky"]) and jinde["polozky"])
        self.over_chybu(self.klient.get("/api/sklad/kandidati-dyn?dilId=13&regalId=1"), 409, "PART_HAS_NO_SIZE")
        self.assertEqual(self.chybna_pole(self.klient.get("/api/sklad/kandidati-dyn?dilId=14&regalId=1"
                                                          "&kodRegalu=HOUFEK-PLE-R01")), {"regalId"})

    def test_prijem_dyn(self):
        odpoved = self.post("/prijem-dyn", dilId=14, cilKod="BPLE038-G", pocetKs=20)
        data = self.over_ok(odpoved)
        self.assertEqual([(p["typPohybu"], p["mnozstvi"], p["stavPoKs"]) for p in data["pohyby"]],
                         [("PRIJEM", 20, 20)])
        self.assertEqual((data["cil"]["stavKs"], data["cil"]["stavBoxu"]), (20, "OBSAZENY"))
        self.assertIsNotNone(odpoved.json["transakceId"])
        self.over_chybu(self.post("/prijem-dyn", dilId=12, cilKod="BPLE038-G", pocetKs=1), 409, "SIZE_MISMATCH")
        self.over_chybu(self.post("/prijem-dyn", dilId=12, cilKod="BPLE037-A", pocetKs=1), 409, "POSITION_OCCUPIED")
        self.over_chybu(self.post("/prijem-dyn", dilId=13, cilKod="BPLE038-G", pocetKs=1), 409, "PART_HAS_NO_SIZE")
        self.over_chybu(self.post("/prijem-dyn", dilId=14, cilKod="BPLE038", pocetKs=1), 400, "WRONG_SCAN_LEVEL")
        self.assertEqual(self.chybna_pole(self.post("/prijem-dyn", dilId=14, cilKod="BSTAT037-3", pocetKs=1)),
                         {"cilKod"})
        self.assertEqual(self.chybna_pole(self.post("/prijem-dyn", dilId=14, cilKod="BPLE038-G", pocetKs=0)),
                         {"pocetKs"})

    def test_rucni_potvrzeni_a_request_id(self):
        self.over_chybu(self.post("/prijem-dyn", dilId=14, cilKod="BPLE038-G", pocetKs=5, zpusobPotvrzeni="RUCNE"),
                        403, "NO_PERMISSION")
        self.prihlas("SKLAD_PRIJEM", "RUCNI_POTVRZENI")
        request_id = rid()
        prvni = self.post("/prijem-dyn", requestId=request_id, dilId=14, cilKod="BPLE038-G", pocetKs=5,
                          zpusobPotvrzeni="RUCNE").json
        druhy = self.post("/prijem-dyn", requestId=request_id, dilId=14, cilKod="BPLE038-G", pocetKs=5,
                          zpusobPotvrzeni="RUCNE").json
        self.assertEqual((prvni["code"], druhy["transakceId"], druhy["data"]),
                         ("OK", prvni["transakceId"], prvni["data"]))
        self.assertEqual(self.chybna_pole(self.klient.post("/api/sklad/prijem-dyn", json={
            "dilId": 14, "cilKod": "BPLE038-G", "pocetKs": 5})), {"requestId"})

    def test_uskladneni_do_stat(self):
        odpoved = self.post("/prijem-stat", dilId=14, cilKod="BSTAT037-1", pocetKs=30)
        data = self.over_ok(odpoved)
        self.assertEqual((data["pohyby"][0]["stavPredKs"], data["cil"]["stavKs"], data["stavZasoby"]), (12, 42, "OK"))
        self.assertEqual([v["code"] for v in odpoved.json["varovani"]], ["NAD_MAXIMEM"])     # Q-11
        z_dyn = self.over_ok(self.post("/prijem-stat", dilId=14, cilKod="BSTAT037-1", pocetKs=3,
                                       zdrojKod="BPLE038-I"))
        self.assertEqual([(p["typPohybu"], p["kod"], p["mnozstvi"]) for p in z_dyn["pohyby"]],
                         [("PRESUN-OUT", "BPLE038-I", -3), ("PRESUN-IN", "BSTAT037-1", 3)])
        self.assertEqual(z_dyn["zdroj"]["stavKs"], 5)
        doplneni = self.over_ok(self.post("/prijem-stat", dilId=13, cilKod="BSTAT037-2", pocetKs=10))
        self.assertEqual((doplneni["stavZasoby"], doplneni["upozorneni"]), ("OK", "UZAVRENO"))
        castecne = self.over_ok(self.post("/prijem-stat", dilId=13, cilKod="BSTAT037-2", pocetKs=5))
        self.assertEqual((castecne["stavZasoby"], castecne["upozorneni"]), ("NA_MINIMU", "AKTUALIZOVANO"))
        self.over_chybu(self.post("/prijem-stat", dilId=12, cilKod="BSTAT037-1", pocetKs=1), 409, "WRONG_PART")
        self.over_chybu(self.post("/prijem-stat", dilId=14, cilKod="BSTAT037-1", pocetKs=1, zdrojKod="BPLE037-A"),
                        409, "WRONG_PART")
        self.over_chybu(self.post("/prijem-stat", dilId=14, cilKod="BSTAT037-1", pocetKs=9, zdrojKod="BPLE038-I"),
                        409, "INSUFFICIENT_STOCK")

    def test_vydej(self):
        data = self.over_ok(self.post("/vydej", zdrojKod="BSTAT037-1", pocetKs=5))
        self.assertEqual((data["pohyby"][0]["mnozstvi"], data["stavZasoby"], data["upozorneni"]),
                         (-5, "POD_MINIMEM", "ZALOZENO"))
        cely = self.over_ok(self.post("/vydej", zdrojKod="BPLE037-A", pocetKs=30, ocekavanyStavKs=30))
        self.assertEqual((cely["zdroj"]["stavKs"], cely["zdroj"]["dilId"], cely["zdroj"]["stavBoxu"]),
                         (0, None, "VOLNY"))
        self.over_chybu(self.post("/vydej", zdrojKod="BPLE037-A", pocetKs=1, ocekavanyStavKs=29),
                        409, "CONCURRENT_CHANGE")
        self.over_chybu(self.post("/vydej", zdrojKod="BPLE037-A", pocetKs=31), 409, "INSUFFICIENT_STOCK")
        self.over_chybu(self.post("/vydej", zdrojKod="BSTAT037-2", pocetKs=1), 409, "INSUFFICIENT_STOCK")

    def test_presun(self):
        odpoved = self.post("/presun", zdrojKod="BPLE037-A", cilKod="BPLE039-A")
        data = self.over_ok(odpoved)
        self.assertEqual([(p["typPohybu"], p["mnozstvi"]) for p in data["pohyby"]],
                         [("PRESUN-OUT", -30), ("PRESUN-IN", 30)])
        self.assertEqual((data["zdroj"]["stavBoxu"], data["cil"]["stavBoxu"]), ("VOLNY", "OBSAZENY"))
        v_boxu = self.over_ok(self.post("/presun", zdrojKod="BPLE038-I", cilKod="BPLE038-G"))
        self.assertEqual((v_boxu["zdroj"]["stavBoxu"], v_boxu["cil"]["stavKs"]), ("OBSAZENY", 8))
        self.over_chybu(self.post("/presun", zdrojKod="BPLE037-A", cilKod="BPLE039-A", pocetKs=10), 400,
                        "WHOLE_BATCH_ONLY")
        self.over_chybu(self.post("/presun", zdrojKod="BPLE037-A", cilKod="BPLE038-G"), 409, "SIZE_MISMATCH")
        self.over_chybu(self.post("/presun", zdrojKod="BPLE038-G", cilKod="BPLE038-H"), 409, "INSUFFICIENT_STOCK")
        self.assertEqual(self.chybna_pole(self.post("/presun", zdrojKod="BSTAT037-1", cilKod="BPLE038-G")),
                         {"zdrojKod"})

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST")
        self.over_chybu(self.post("/vydej", zdrojKod="BPLE037-A", pocetKs=1), 403, "NO_PERMISSION")


class TestStatMistaAUpozorneni(ZakladTestuOstrova):
    ostrovy = OSTROVY

    def setUp(self):
        super().setUp()
        self.prihlas("DIL_CIST", "STAT_EDIT", "UPOZORNENI_UZAVRIT", role="TECH")

    def test_seznam_a_prirazeni(self):
        self.assertEqual(self.over_ok(self.klient.get("/api/sklad/stat-mista"))["celkem"], 2)
        vycerpana = self.over_ok(self.klient.get("/api/sklad/stat-mista?stavZasoby=VYCERPANO"))["polozky"]
        self.assertEqual([m["kod"] for m in vycerpana], ["BSTAT037-2"])
        nove = {"dilId": 12, "vnitrniPoziceId": 503, "minimalniKs": 5, "maximalniKs": 20}
        self.over_chybu(self.klient.post("/api/sklad/stat-mista", json=nove), 409, "SIZE_MISMATCH")
        radek = self.over_ok(self.klient.post("/api/sklad/stat-mista", json={
            **nove, "prepsatVelikost": True, "duvod": "díl V1 v přihrádce V3 vědomě"}))
        self.assertEqual((radek["kod"], radek["stavZasoby"]), ("BSTAT037-3", "VYCERPANO"))
        self.over_chybu(self.klient.post("/api/sklad/stat-mista", json={**nove, "dilId": 14}), 409, "ALREADY_EXISTS")
        self.assertEqual(self.chybna_pole(self.klient.post("/api/sklad/stat-mista",
                                                           json={**nove, "vnitrniPoziceId": 101})), {"vnitrniPoziceId"})
        self.assertEqual(self.chybna_pole(self.klient.post("/api/sklad/stat-mista",
                                                           json={**nove, "minimalniKs": 30})), {"maximalniKs"})

    def test_zmena_minima_a_ukonceni(self):
        odpoved = self.klient.patch("/api/sklad/stat-mista/1", json={"minimalniKs": 15, "duvod": "vyšší spotřeba"})
        self.assertEqual(self.over_ok(odpoved)["stavZasoby"], "POD_MINIMEM")
        self.assertEqual([v["code"] for v in odpoved.json["varovani"]], ["UPOZORNENI"])
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/sklad/stat-mista/1", json={
            "minimalniKs": None, "duvod": "test"})), {"minimalniKs"})
        self.over_chybu(self.klient.post("/api/sklad/stat-mista/1/ukoncit", json={"duvod": "konec dílu"}),
                        409, "NOT_EMPTY")
        konec = self.klient.post("/api/sklad/stat-mista/2/ukoncit", json={"duvod": "díl se nevyrábí"})
        self.assertFalse(self.over_ok(konec)["aktivni"])
        self.assertEqual([v["code"] for v in konec.json["varovani"]], ["UPOZORNENI"])

    def test_upozorneni(self):
        self.assertEqual(self.over_ok(self.klient.get("/api/sklad/upozorneni"))["celkem"], 1)
        self.assertEqual(self.over_ok(self.klient.get("/api/sklad/upozorneni?stav="))["celkem"], 2)
        uzavrene = self.over_ok(self.klient.post("/api/sklad/upozorneni/1/uzavrit", json={"poznamka": "díl ruší"}))
        self.assertEqual((uzavrene["stavUpozorneni"], uzavrene["poznamka"]), ("UZAVRENE", "díl ruší"))
        self.assertIsNotNone(uzavrene["datumUzavreni"])
        self.over_chybu(self.klient.post("/api/sklad/upozorneni/2/uzavrit", json={"poznamka": "znovu"}),
                        409, "CONCURRENT_CHANGE")
        self.over_chybu(self.klient.post("/api/sklad/upozorneni/99/uzavrit", json={"poznamka": "nic"}),
                        404, "NOT_FOUND")


class TestVzorovaData(unittest.TestCase):
    def test_vzory_e_odpovidaji_vzorum_c_a_d(self):
        from app.ostrovy.sklad import ukazky
        from app.ostrovy.struktura import rozhrani as struktura

        self.assertEqual(set(ukazky.OBSAH), set(mista.OBSAZENE_POZICE))
        self.assertEqual({s.vnitrni_pozice_id for s in ukazky.STAT_MISTA}, set(mista.STAT_PRIRAZENE_POZICE))
        for obsah in ukazky.OBSAH.values():
            misto, dil = mista.MISTA[obsah.vnitrni_pozice_id], dily_vzory.DIL_INFO[obsah.dil_id]
            if misto.typ_boxu == "DYN":
                self.assertTrue(struktura.vejde_se(misto, dil.potreba), misto.kod)
            else:
                stat = next(s for s in ukazky.STAT_MISTA if s.vnitrni_pozice_id == obsah.vnitrni_pozice_id)
                self.assertEqual(stat.dil_id, obsah.dil_id, misto.kod)


if __name__ == "__main__":
    unittest.main()
