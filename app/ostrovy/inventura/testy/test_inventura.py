"""Testy ostrova F: čistá pravidla inventury (D-26, D-27) a HTTP kontrakt nad sqlite.

Nad SQL Serverem (test_inventura_sql.py) je založení, zápis, stavy položek, zrušení i dokončení.
Tady zůstávají pravidla bez DB a HTTP případy, které se rozhodnou dřív, než služba sáhne do
databáze (400 ze vstupu a pravidla rozsahu, 403 z oprávnění).
"""
import unittest
from dataclasses import replace

from app.ostrovy import dily, inventura, sklad, struktura
from app.ostrovy.inventura import domena
from app.ostrovy.sklad.rozhrani import ObsahInfo, StatMistoInfo
from app.ostrovy.struktura import ukazky as mista
from app.platforma.chyby import AppError
from app.platforma.typy import PotrebaMista
from tests.pomocnik import ZakladTestuOstrova, rid

# Chyby ostrovů C, D a E projdou endpointy F – aplikace je musí znát.
OSTROVY = (struktura.OSTROV, dily.OSTROV, sklad.OSTROV, inventura.OSTROV)

V1, V3 = PotrebaMista("V1"), PotrebaMista("V3")
DYN_VOLNA = mista.MISTA[391]                    # BPLE039-A, DYN V1
STAT_POZICE = mista.MISTA[501]                  # BSTAT037-1, STAT V3


def polozka(pozice=1, typ="DYN", ocekavany=(12, 30), skutecny=(12, 30), stav="ZAPSANO", aktualni=None):
    """Položka pro pravidla. `aktualni` = aktuální počet očekávaného dílu na pozici; None znamená,
    že od zápisu se na pozici nic nepřepsalo, tedy že je tam stále očekávaný stav."""
    zapsano = skutecny is not None
    return domena.Polozka(pozice, f"P{pozice}", typ, ocekavany[0], ocekavany[1],
                          skutecny[0] if zapsano else None, skutecny[1] if zapsano else None,
                          ocekavany[1] if aktualni is None else aktualni, stav)


def pohyb(dil_id, stav_po_ks):
    return domena.Pohyb(dil_id, stav_po_ks)


def kod_chyby(funkce, *args, **kwargs) -> str:
    try:
        funkce(*args, **kwargs)
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

    def test_rozsah(self):
        domena.over_rozsah("FULL", None)
        for typ, cil in [("FULL", 1), ("BOX", None)]:
            self.assertEqual(kod_chyby(domena.over_rozsah, typ, cil), "VALIDATION_ERROR")

    def test_zapis(self):
        domena.over_zapis(None, 0)
        domena.over_zapis(12, 1)
        self.assertEqual(kod_chyby(domena.over_zapis, None, 5), "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(domena.over_zapis, 12, 0), "VALIDATION_ERROR")


class TestStavPolozky(unittest.TestCase):
    """D-26: pohyb po zápisu nikdy nepřepíše zjištěný díl ani počet; dopočítá se jen jednoznačná
    změna téhož dílu, jinak se pozice vrací k fyzické kontrole."""

    def stav(self, *, zapsano=True, dil_id=12, vysledek="ROZDIL", rozdil_ks=-2, aktualni=30, pohyby=(),
             aktivni=True, uzavrena=False):
        return domena.stav_polozky(zapsano=zapsano, dil_id=dil_id, vysledek=vysledek, rozdil_ks=rozdil_ks,
                                   aktualni_pocet_ks=aktualni, pohyby=pohyby, aktivni=aktivni, uzavrena=uzavrena)

    def test_nezapsana_polozka_ceka(self):
        self.assertEqual(self.stav(zapsano=False), "CEKA")

    def test_bez_pohybu_zustava_zapsano(self):
        self.assertEqual(self.stav(), "ZAPSANO")

    def test_pohyb_tehož_dilu_se_dopocita(self):
        self.assertEqual(self.stav(pohyby=(pohyb(12, 26),)), "ZAPSANO")

    def test_vic_pohybu_tehož_dilu_se_dopocita(self):
        self.assertEqual(self.stav(pohyby=(pohyb(12, 26), pohyb(12, 24))), "ZAPSANO")

    def test_pohyb_jineho_dilu_vrati_pozici_k_prepoctu(self):
        self.assertEqual(self.stav(pohyby=(pohyb(14, 5),)), "PREPOCITAT")

    def test_vyprazdeni_a_nove_obsazeni_vrati_pozici_k_prepoctu(self):
        self.assertEqual(self.stav(pohyby=(pohyb(12, 0), pohyb(12, 7))), "PREPOCITAT")

    def test_prazdna_pozice_na_konci_se_dopocita(self):
        # našlo se 5 ks navíc, pak se pozice vybrala celá: nový stav je 0 + 5
        self.assertEqual(self.stav(vysledek="ROZDIL", rozdil_ks=5, aktualni=0,
                                   pohyby=(pohyb(12, 20), pohyb(12, 0))), "ZAPSANO")

    def test_zaporny_dopocet_vrati_pozici_k_prepoctu(self):
        self.assertEqual(self.stav(aktualni=0, pohyby=(pohyb(12, 0),)), "PREPOCITAT")

    def test_jakykoli_pohyb_u_jineho_dilu_vrati_pozici_k_prepoctu(self):
        self.assertEqual(self.stav(vysledek="JINY_DIL", dil_id=14, rozdil_ks=-9, pohyby=(pohyb(12, 3),)),
                         "PREPOCITAT")

    def test_jiny_dil_bez_pohybu_zustava_zapsano(self):
        self.assertEqual(self.stav(vysledek="JINY_DIL", dil_id=14, rozdil_ks=-9), "ZAPSANO")

    def test_pohyb_na_pozice_ktera_mela_byt_prazdna(self):
        self.assertEqual(self.stav(dil_id=None, vysledek="SHODA", rozdil_ks=0, aktualni=0,
                                   pohyby=(pohyb(12, 4),)), "PREPOCITAT")

    def test_neaktivni_pozice_po_rekonfiguraci(self):
        self.assertEqual(self.stav(aktivni=False), "PREPOCITAT")

    def test_uzavrena_inventura_se_neprepocitava(self):
        """Dokončená ani zrušená inventura se nepřepočítává – vlastní korekce i každý další pohyb
        by ji jinak ukázal jako PREPOCITAT."""
        self.assertEqual(self.stav(pohyby=(pohyb(14, 5),), uzavrena=True), "ZAPSANO")
        self.assertEqual(self.stav(aktualni=0, pohyby=(pohyb(12, 0),), uzavrena=True), "ZAPSANO")
        self.assertEqual(self.stav(aktivni=False, uzavrena=True), "ZAPSANO")
        self.assertEqual(self.stav(zapsano=False, uzavrena=True), "CEKA")


class TestCilJinyDil(unittest.TestCase):
    """D-27 (S-22): cílem nalezeného jiného dílu je volná neblokovaná DYN, do které se díl vejde,
    nebo aktivní STAT místo nalezeného dílu. Současná pozice je cílem až po odúčtování očekávaného
    dílu – posílá se už jako volná (obsah None)."""

    def over(self, cil, *, potreba=V1, obsah=None, stat=None, dil_id=12):
        domena.over_cil_jiny_dil(cil, nalezeny_dil_id=dil_id, potreba=potreba, obsah_cilu=obsah,
                                 stat_misto_cilu=stat, kod_pozice="BSTAT037-1")

    def test_volna_dyn_same_velikosti(self):
        self.over(DYN_VOLNA, potreba=V1)

    def test_blokovana_dyn_neni_cil(self):
        self.assertEqual(kod_chyby(self.over, replace(DYN_VOLNA, blokovano=True)), "VALIDATION_ERROR")

    def test_obsazena_dyn_neni_cil(self):
        self.assertEqual(kod_chyby(self.over, DYN_VOLNA, obsah=ObsahInfo(391, 14, 2)), "VALIDATION_ERROR")

    def test_dyn_spatne_velikosti_neni_cil(self):
        self.assertEqual(kod_chyby(self.over, DYN_VOLNA, potreba=V3), "VALIDATION_ERROR")

    def test_dil_bez_velikosti_nema_cil_v_dyn(self):
        self.assertEqual(kod_chyby(self.over, DYN_VOLNA, potreba=None), "VALIDATION_ERROR")

    def test_stat_misto_nalezeneho_dilu(self):
        self.over(STAT_POZICE, stat=StatMistoInfo(1, 12, 501, 0, None, None))

    def test_stat_misto_jineho_dilu_neni_cil(self):
        self.assertEqual(kod_chyby(self.over, STAT_POZICE, stat=StatMistoInfo(1, 14, 501, 0, None, None)),
                         "VALIDATION_ERROR")

    def test_stat_pozice_bez_mista_neni_cil(self):
        self.assertEqual(kod_chyby(self.over, STAT_POZICE), "VALIDATION_ERROR")

    def test_blokovany_stat_neni_cil(self):
        self.assertEqual(kod_chyby(self.over, replace(STAT_POZICE, blokovano=True),
                                   stat=StatMistoInfo(1, 12, 501, 0, None, None)), "VALIDATION_ERROR")


class TestDokonceniAPlan(unittest.TestCase):
    def test_dokonceni(self):
        self.assertEqual(kod_chyby(domena.over_dokonceni, [polozka(skutecny=None, stav="CEKA")], {}),
                         "VALIDATION_ERROR")
        self.assertEqual(kod_chyby(domena.over_dokonceni, [polozka(stav="PREPOCITAT")], {}), "INVENTORY_RECOUNT")

    def test_jiny_dil_ve_stat_vyzele_cil(self):
        self.assertEqual(kod_chyby(domena.over_dokonceni, [polozka(5, "STAT", (14, 12), (12, 3))], {}),
                         "VALIDATION_ERROR")

    def test_jiny_dil_v_dyn_vyzele_cil(self):
        # S-22: cíl potřebuje i dynamická pozice – bez něj nelze inventuru dokončit
        self.assertEqual(kod_chyby(domena.over_dokonceni, [polozka(6, "DYN", (14, 12), (12, 3))], {}),
                         "VALIDATION_ERROR")

    def test_dokonceni_s_cili_projde(self):
        domena.over_dokonceni([polozka(5, "STAT", (14, 12), (12, 3)), polozka(6, "DYN", (14, 12), (12, 3)),
                               polozka(7, ocekavany=(12, 30), skutecny=(12, 28))],
                              {5: "BSTAT037-2", 6: "BPLE039-A"})

    def test_plan_korekci(self):
        plan = domena.planuj_korekce([
            polozka(1),                                                    # shoda – nic
            polozka(2, ocekavany=(12, 30), skutecny=(12, 28)),              # rozdíl – nový stav 30 − 2
            polozka(3, ocekavany=(14, 5), skutecny=(12, 4)),                # jiný díl v DYN – odúčtovat + cíl
            polozka(4, "STAT", (14, 12), (12, 3)),                          # jiný díl ve STAT – odúčtovat + cíl
            polozka(5, ocekavany=(None, 0), skutecny=None, stav="CEKA"),
        ], {3: 391, 4: 392})
        self.assertEqual(plan, [domena.Korekce(2, 12, 28), domena.Korekce(3, 14, 0),
                                domena.Korekce(391, 12, None, pricist_ks=4), domena.Korekce(4, 14, 0),
                                domena.Korekce(392, 12, None, pricist_ks=3)])

    def test_plan_dopocita_pohyby_po_zapisu(self):
        # očekávaných 30, nalezených 28 (rozdíl −2), po zápisu ještě výdej 6 ks → aktuálně 24, nový stav 22
        plan = domena.planuj_korekce([polozka(2, ocekavany=(12, 30), skutecny=(12, 28), aktualni=24)], {})
        self.assertEqual(plan, [domena.Korekce(2, 12, 22)])

    def test_plan_jiny_dil_na_prazdne_pozici(self):
        # pozice měla být prázdná → nic se neodúčtovává, nalezený díl jde rovnou na cíl
        plan = domena.planuj_korekce([polozka(7, ocekavany=(None, 0), skutecny=(12, 3))], {7: 391})
        self.assertEqual(plan, [domena.Korekce(391, 12, None, pricist_ks=3)])

    def test_plan_jiny_dil_na_vlastni_pozici(self):
        # D-27: cílem může být i současná pozice – po odúčtování očekávaného dílu se na ni přičte nález
        plan = domena.planuj_korekce([polozka(3, ocekavany=(14, 5), skutecny=(12, 4))], {3: 3})
        self.assertEqual(plan, [domena.Korekce(3, 14, 0), domena.Korekce(3, 12, None, pricist_ks=4)])

    def test_souhrn(self):
        self.assertEqual(domena.souhrn([polozka(1), polozka(2, ocekavany=(12, 30), skutecny=(12, 28)),
                                        polozka(3, ocekavany=(14, 5), skutecny=(12, 4)),
                                        polozka(4, ocekavany=(None, 0), skutecny=None, stav="CEKA")]),
                         {"SHODA": 1, "ROZDIL": 1, "JINY_DIL": 1})


class TestInventuraHttp(ZakladTestuOstrova):
    """Případy, které se rozhodnou před přístupem k databázi (testy nad SQL Serverem jsou
    v test_inventura_sql.py)."""

    ostrovy = OSTROVY

    def setUp(self):
        super().setUp()
        self.prihlas("INVENTURA", "KOREKCE")

    def test_chybna_pole_vstupu(self):
        self.assertEqual(self.chybna_pole(self.klient.post("/api/inventura", json={"typRozsahu": "BOX"})), {"cilId"})
        self.assertEqual(self.chybna_pole(self.klient.post("/api/inventura", json={"typRozsahu": "JINY"})),
                         {"typRozsahu"})
        self.assertEqual(self.chybna_pole(self.klient.post("/api/inventura/1/polozky/382", json={})),
                         {"skutecnyPocetKs"})

    def test_dokonceni_vyzele_opravneni_korekce(self):
        self.prihlas("INVENTURA")
        self.over_chybu(self.klient.post("/api/inventura/1/dokoncit", json={"requestId": rid()}), 403,
                        "NO_PERMISSION")


if __name__ == "__main__":
    unittest.main()
