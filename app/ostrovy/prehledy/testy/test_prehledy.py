"""Testy ostrova G bez databáze: HTTP kontrakt (400, 401, 403) a číselníky.

Přehledy se skládají jedním dotazem nad pohledy v_* (T-SQL), takže jejich testy jsou
`test_prehledy_sql.py` (SQL Server). Tady zůstává to, co databázi nepotřebuje – odpovědi, které
skončí dřív, než se dorazí do služby: neplatný vstup (400), nepřihlášený (401) a bez oprávnění
(403). Číselníky čtou přes rozhraní ostrovů C, D a E, proto stačí kostra. Pravidla z `domena.py`
testuje `test_domena.py`.
"""
import unittest
import uuid

from app.ostrovy import dily, identita, prehledy, sklad, struktura
from tests.pomocnik import ZakladTestuOstrova

OSTROVY = (identita.OSTROV, struktura.OSTROV, dily.OSTROV, sklad.OSTROV, prehledy.OSTROV)

# Každý endpoint ostrova G; samostatné cesty, aby šlo projít i bez databáze.
CESTY = ("/sken/BPLE038-I", "/hledat?q=bx", "/urovne/4/rozlozeni", "/dily/14/karta", "/zasoby", "/laser",
         "/pohyby", f"/transakce/{uuid.UUID(int=1)}", "/ciselniky")


class TestOdmitnuteVstupy(ZakladTestuOstrova):
    """400 z HTTP vrstvy – služba se zavolat ani nemusí, proto stačí sqlite kostry."""

    ostrovy = OSTROVY

    def setUp(self) -> None:
        super().setUp()
        self.prihlas("DIL_CIST")

    def test_hledani_vyzaduje_text(self):
        self.assertEqual(self.chybna_pole(self.klient.get("/api/prehledy/hledat")), {"q"})

    def test_neznamy_parametr(self):
        self.assertEqual(self.chybna_pole(self.klient.get("/api/prehledy/hledat?q=bx&barva=modra")), {"barva"})

    def test_technicke_kody_maji_nase_hodnoty(self):
        for cesta in ("/hledat?q=bx&typBoxu=VEDLE", "/hledat?q=bx&stavZasoby=ZAPORNY",
                      "/zasoby?stavZasoby=ZAPORNY", "/zasoby?jenProblemove=obcas"):
            with self.subTest(cesta=cesta):
                self.assertTrue(self.chybna_pole(self.klient.get(f"/api/prehledy{cesta}")))

    def test_strankovani_a_datum(self):
        self.assertEqual(self.chybna_pole(self.klient.get("/api/prehledy/zasoby?strana=0")), {"strana"})
        self.assertEqual(self.chybna_pole(self.klient.get("/api/prehledy/laser?velikost=500")), {"velikost"})
        self.assertEqual(self.chybna_pole(self.klient.get("/api/prehledy/pohyby?od=30.10.2026")), {"od"})


class TestOpravneni(ZakladTestuOstrova):
    """Ostrov G jen čte díly: všechny endpointy vyžadují DIL_CIST a přihlášení."""

    ostrovy = OSTROVY

    def test_bez_opravneni(self):
        self.prihlas("SKLAD_PRIJEM")
        for cesta in CESTY:
            with self.subTest(cesta=cesta):
                self.over_chybu(self.klient.get(f"/api/prehledy{cesta}"), 403, "NO_PERMISSION")

    def test_bez_prihlaseni(self):
        for cesta in CESTY:
            with self.subTest(cesta=cesta):
                self.over_chybu(self.klient.get(f"/api/prehledy{cesta}"), 401, "NOT_AUTHENTICATED")


class TestCiselniky(ZakladTestuOstrova):
    """7.7: číselníky přicházejí přes rozhraní ostrovů C, D a E – nad kostrou i bez SQL Serveru."""

    ostrovy = OSTROVY

    def setUp(self) -> None:
        super().setUp()
        self.prihlas("DIL_CIST")

    def test_ciselniky(self):
        data = self.over_ok(self.klient.get("/api/prehledy/ciselniky"))
        self.assertEqual((len(data["pracoviste"]), len(data["typyPohybu"]), data["typyBoxu"]), (8, 7, ["DYN", "STAT"]))
        self.assertEqual(data["stavyZasoby"], ["OK", "NA_MINIMU", "POD_MINIMEM", "VYCERPANO"])


if __name__ == "__main__":
    unittest.main()
