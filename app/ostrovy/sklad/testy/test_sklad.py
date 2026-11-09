"""Testy ostrova E: čistá pravidla (hotová) a HTTP kontrakt skladových operací nad vzorovými daty.

Zápis i čtení zásoby nad SQL Serverem je v `test_sklad_sql.py`; tady zůstávají pravidla bez DB a
HTTP testy, které databázi nepotřebují: chyby vstupu (400), chybějící oprávnění (403) a operace,
které se rozhodnou dřív, než by něco zapsaly. STAT místa i ruční uzavření upozornění už zapisují
nad SQL Serverem, proto tady z nich zbyly jen vzorový seznam a odmítnutí.
"""
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


def kdo(*opravneni: str, role: str = "SKL", terminal_id: int | None = None) -> Kontext:
    """Přihlášený kontext; `terminal_id` je PDA (login z terminálu, Q-15)."""
    return Kontext(1, terminal_id, role, frozenset(opravneni))


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
        """Q-15, D-18: na PC ručně s oprávněním, na terminálu (PDA) vždy jen sken – ani s oprávněním ne."""
        domena.over_zpusob_potvrzeni("SKEN", kdo())
        domena.over_zpusob_potvrzeni("RUCNE", kdo("RUCNI_POTVRZENI"))
        domena.over_zpusob_potvrzeni("SKEN", kdo(terminal_id=7))
        self.assertEqual(kod_chyby(domena.over_zpusob_potvrzeni, "RUCNE", kdo()), "NO_PERMISSION")
        self.assertEqual(kod_chyby(domena.over_zpusob_potvrzeni, "RUCNE", kdo("RUCNI_POTVRZENI", terminal_id=7)),
                         "VALIDATION_ERROR")


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
        """Samotný příjem testuje test_sklad_sql.py; tady chyby, které padnou dřív, než se začne zapisovat."""
        self.over_chybu(self.post("/prijem-dyn", dilId=12, cilKod="BPLE038-G", pocetKs=1), 409, "SIZE_MISMATCH")
        self.over_chybu(self.post("/prijem-dyn", dilId=12, cilKod="BPLE037-A", pocetKs=1), 409, "POSITION_OCCUPIED")
        self.over_chybu(self.post("/prijem-dyn", dilId=13, cilKod="BPLE038-G", pocetKs=1), 409, "PART_HAS_NO_SIZE")
        self.over_chybu(self.post("/prijem-dyn", dilId=14, cilKod="BPLE038", pocetKs=1), 400, "WRONG_SCAN_LEVEL")
        self.assertEqual(self.chybna_pole(self.post("/prijem-dyn", dilId=14, cilKod="BSTAT037-3", pocetKs=1)),
                         {"cilKod"})
        self.assertEqual(self.chybna_pole(self.post("/prijem-dyn", dilId=14, cilKod="BPLE038-G", pocetKs=0)),
                         {"pocetKs"})

    def test_rucni_potvrzeni_a_request_id(self):
        """Dvojí odeslání se stejným requestId (T14) testuje test_sklad_sql.py – potřebuje potvrzená data."""
        self.over_chybu(self.post("/prijem-dyn", dilId=14, cilKod="BPLE038-G", pocetKs=5, zpusobPotvrzeni="RUCNE"),
                        403, "NO_PERMISSION")
        self.assertEqual(self.chybna_pole(self.klient.post("/api/sklad/prijem-dyn", json={
            "dilId": 14, "cilKod": "BPLE038-G", "pocetKs": 5})), {"requestId"})

    def test_uskladneni_do_stat(self):
        """Uskladnění, přičtení i upozornění zásoby testuje test_sklad_sql.py; tady odmítnutí před zápisem."""
        self.over_chybu(self.post("/prijem-stat", dilId=12, cilKod="BSTAT037-1", pocetKs=1), 409, "WRONG_PART")
        self.over_chybu(self.post("/prijem-stat", dilId=14, cilKod="BSTAT037-1", pocetKs=1, zdrojKod="BPLE037-A"),
                        409, "WRONG_PART")
        self.over_chybu(self.post("/prijem-stat", dilId=14, cilKod="BSTAT037-1", pocetKs=9, zdrojKod="BPLE038-I"),
                        409, "INSUFFICIENT_STOCK")

    def test_vydej(self):
        """Výdej, vyprázdnění pozice i zásobové stavy testuje test_sklad_sql.py; tady odmítnutí před zápisem."""
        self.over_chybu(self.post("/vydej", zdrojKod="BPLE037-A", pocetKs=1, ocekavanyStavKs=29),
                        409, "CONCURRENT_CHANGE")
        self.over_chybu(self.post("/vydej", zdrojKod="BPLE037-A", pocetKs=31), 409, "INSUFFICIENT_STOCK")
        self.over_chybu(self.post("/vydej", zdrojKod="BSTAT037-2", pocetKs=1), 409, "INSUFFICIENT_STOCK")

    def test_presun(self):
        """Přesun celé dávky (dva pohyby, T05) testuje test_sklad_sql.py; tady odmítnutí před zápisem."""
        self.over_chybu(self.post("/presun", zdrojKod="BPLE037-A", cilKod="BPLE039-A", pocetKs=10), 400,
                        "WHOLE_BATCH_ONLY")
        self.over_chybu(self.post("/presun", zdrojKod="BPLE037-A", cilKod="BPLE038-G"), 409, "SIZE_MISMATCH")
        self.over_chybu(self.post("/presun", zdrojKod="BPLE038-G", cilKod="BPLE038-H"), 409, "INSUFFICIENT_STOCK")
        self.assertEqual(self.chybna_pole(self.post("/presun", zdrojKod="BSTAT037-1", cilKod="BPLE038-G")),
                         {"zdrojKod"})

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST")
        self.over_chybu(self.post("/vydej", zdrojKod="BPLE037-A", pocetKs=1), 403, "NO_PERMISSION")

    def test_t12_zadna_route_nastavi_pocet_ks(self):
        """T12: kusy mění jen skladové příkazy a korekce – endpoint „nastav stav pozici“ ostrov E nemá."""
        zapisy = {r.rule for r in self.app.url_map.iter_rules() if r.rule.startswith("/api/sklad")
                  and set(r.methods) & {"POST", "PUT", "PATCH", "DELETE"}}
        self.assertEqual(zapisy, {"/api/sklad/prijem-dyn", "/api/sklad/prijem-stat", "/api/sklad/presun",
                                   "/api/sklad/vydej", "/api/sklad/stat-mista",
                                   "/api/sklad/stat-mista/<int:stat_umisteni_id>",
                                   "/api/sklad/stat-mista/<int:stat_umisteni_id>/ukoncit",
                                   "/api/sklad/upozorneni/<int:upozorneni_id>/uzavrit"})
        # stav pozice nijak z HTTP nesjede: ostrov F (inventura) volá `rozhrani.zauctuj_korekci`, ne endpoint E


class TestStatMistaAUpozorneni(ZakladTestuOstrova):
    """Zápis STAT míst i ruční uzavření výstrah běží nad SQL Serverem (`test_sklad_sql.py`).

    Nad sqlite kostrou zůstávají cesty, které se rozhodnou dřív, než by ostrov něco zapisoval:
    filtr seznamu, kontroly vstupu a oprávnění (Q-05) a odmítnutí obsazené pozice.
    """

    ostrovy = OSTROVY

    def setUp(self):
        super().setUp()
        self.prihlas("DIL_CIST", "STAT_EDIT", "UPOZORNENI_UZAVRIT", role="TECH")

    def test_seznam_stat_mist(self):
        self.assertEqual(self.over_ok(self.klient.get("/api/sklad/stat-mista"))["celkem"], 2)
        vycerpana = self.over_ok(self.klient.get("/api/sklad/stat-mista?stavZasoby=VYCERPANO"))["polozky"]
        self.assertEqual([m["kod"] for m in vycerpana], ["BSTAT037-2"])

    def test_prirazeni_odmitne_velikost_dil_pozici_i_meze(self):
        nove = {"dilId": 12, "vnitrniPoziceId": 503, "minimalniKs": 5, "maximalniKs": 20}
        self.over_chybu(self.klient.post("/api/sklad/stat-mista", json=nove), 409, "SIZE_MISMATCH")
        self.over_chybu(self.klient.post("/api/sklad/stat-mista", json={**nove, "dilId": 14}), 409, "ALREADY_EXISTS")
        self.assertEqual(self.chybna_pole(self.klient.post("/api/sklad/stat-mista",
                                                           json={**nove, "vnitrniPoziceId": 101})), {"vnitrniPoziceId"})
        self.assertEqual(self.chybna_pole(self.klient.post("/api/sklad/stat-mista",
                                                           json={**nove, "minimalniKs": 30})), {"maximalniKs"})

    def test_prepsat_velikost_smijen_technolog(self):
        """Q-05: přepsání velikosti je do auditu i do oprávnění – operátor (role SKL) ho nedostane."""
        self.prihlas("DIL_CIST", "STAT_EDIT", "UPOZORNENI_UZAVRIT", role="SKL")
        self.over_chybu(self.klient.post("/api/sklad/stat-mista", json={
            "dilId": 12, "vnitrniPoziceId": 503, "minimalniKs": 5, "maximalniKs": 20, "prepsatVelikost": True,
            "duvod": "díl V1 v přihrádce V3 vědomě"}), 403, "NO_PERMISSION")

    def test_zmena_mezi_a_ukonceni_chcuji_udaje(self):
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/sklad/stat-mista/1",
                                                            json={"minimalniKs": None, "duvod": "test"})),
                         {"minimalniKs"})
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/sklad/stat-mista/1", json={"minimalniKs": 15})),
                         {"duvod"})
        self.over_chybu(self.klient.post("/api/sklad/stat-mista/1/ukoncit", json={"duvod": "konec dílu"}),
                        409, "NOT_EMPTY")                     # ve vzoru je na BSTAT037-1 obsah

    def test_upozorneni_se_uzavira_jen_s_poznamkou(self):
        self.assertEqual(self.chybna_pole(self.klient.post("/api/sklad/upozorneni/1/uzavrit", json={})),
                         {"poznamka"})


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
