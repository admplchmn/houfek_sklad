"""Testy ostrova C, které nepotřebují databázi: parser kódů v rozhraní a odmítnutí 400 a 403.

Chování služeb nad daty testují `test_sluzby_integrace.py` – služby čtou a mění skutečné tabulky
SQL Serveru, sqlite kostra jim žádnou z nich nedá. Zde zůstává rozhraní se `spoj=None` (vzorová
data fáze 0) a odmítnutí, ke kterému dojde dřív, než služba něco čte: neplatný kontrakt (chybné
pole, chybějící requestId, `null` u povinného údaje) a nedostatečné oprávnění. ID a kódy v cestě
proto odpovídají čemukoli – na dotaz do databáze se nedojde.
"""
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


class TestOdmity(ZakladTestuOstrova):
    """400 z kontraktu a 403 z oprávnění – obálka musí sedět, i když služba na databázi nedojde."""

    ostrovy = (struktura.OSTROV,)

    def post(self, cesta, **telo):
        return self.klient.post(f"/api/struktura{cesta}", json=telo)

    def test_odmitne_spatny_vstup(self):
        self.prihlas("DIL_CIST", "BOX_EDIT")
        self.assertEqual(self.chybna_pole(self.klient.get("/api/struktura/urovne")), {"regalId"})
        self.assertEqual(self.chybna_pole(self.post("/pracoviste", kodPracoviste="PLEX")),
                         {"kodPracoviste"})                                    # kód je součást barcode
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/struktura/pracoviste/999", json={
            "kodPracoviste": "PLX", "duvod": "kód je v barcode"})), {"kodPracoviste"})
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/struktura/urovne/999", json={
            "poradi": None, "duvod": "oprava"})), {"poradi"})                   # povinný údaj nelze vymazat
        self.assertEqual(self.chybna_pole(self.post("/urovne/999/boxy", typBoxu="MIX", cleneniId=1, delkaMm=0,
                                                    hloubkaMm=360)), {"typBoxu", "delkaMm"})

    def test_blokace_odmitne_spatny_kod(self):
        self.prihlas("BLOKACE")
        blokace = self.post("/blokace", requestId=rid(), kod="HOUFEK-PLE-R01", blokovat=True,
                            duvod="poškozený box")
        self.assertEqual(self.chybna_pole(blokace), {"kod"})                   # regál se blokovat nedá
        self.over_chybu(self.post("/blokace", requestId=rid(), kod="AAR10044", blokovat=True,
                                  duvod="poškozený box"), 400, "INVALID_BARCODE")
        self.assertEqual(self.chybna_pole(self.post("/blokace", kod="BPLE037", blokovat=True,
                                                    duvod="test")), {"requestId"})

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST")
        self.over_chybu(self.post("/blokace", requestId=rid(), kod="BPLE037", blokovat=True,
                                  duvod="poškozený box"), 403, "NO_PERMISSION")
        self.over_chybu(self.post("/boxy/999/deaktivovat", duvod="vyřazen"), 403, "NO_PERMISSION")


if __name__ == "__main__":
    unittest.main()
