"""Integrační testy ostrova H nad SQL Serverem: `flask migrace nacti` do schématu stg a report.

Služby se volí bez dekorátoru přes `__wrapped__`, takže běží ve spojení a transakci testu a na konci
se vše vrátí zpět (@transakce i @cteni si otevírají vlastní spojení). Druhé spojení a potvrzená data
potřebuje jen `TestPrikazy`: `flask migrace nacti` si otevírá spojení sám, takže dávka v databázi
zůstane i po rollbacku testu (CI běží všechny ostrovy nad jednou databází). Test proto počítá s
největším DavkaID, ne s počtem dávek, a report bez `--davka` se kontroluje až po samotném načtení.

Sešit si staví test sám (openpyxl do dočasného souboru) – v repozitáři nesmí ležet skutečný XLSM ani
data firmy. Řádky níže jsou vymyšlené a pokrývají každou chybu i každé upozornění, které report umí
(docs/migrace-xlsm.md, sekce 3 a 4).
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import openpyxl

from app.ostrovy.migrace import sluzby
from app.platforma.chyby import AppError
from tests.integrace.zaklad import ZakladIntegrace

NAZEV_SESITU = "vymysleny-sestit-migrace.xlsm"

HLAVICKA = ("PRACOVIŠTĚ", "REGÁL", "ÚROVEŇ", "POZICE", "BOX_ID", "STAV_BOXU", "IDENTIFIKAČNÍ_ČÍSLO",
            "MINIMÁLNÍ POČET KUSŮ V BOXU", "JINÉ INFORMACE", "VAULT PDF", "DÉLKA_BOXU_(mm)",
            "HLOUBKA_BOXU_(mm)")

# řádek 1 je titulek, aby hlavička nebyla jako první; prázdné řádky oddělují úrovně jako v sešitu
DATABAZE: list[tuple[Any, ...]] = [
    ("Databáze boxů plechotvárení",),                                                      # ř. 1
    HLAVICKA,                                                                              # ř. 2
    ("PLE", "R01", "U01", "P01", "BPLE01", "OPER", "CE21RA 10 100194", "50 kusů (1 kus na stroj)",
     "Používat jen na servis", "http://srvvault2401.houfek.local/Vault/2/DILY/123.pdf", 300.0, 500),  # ř. 3
    ("PLE", "R01", "U01", "P01", "BPLE01", "OPER", "ABR31036_1", "", "",
     "srvvault2401/Vault/2/DILY/124.pdf", 300.0, 500),                                     # ř. 4
    (),                                                                                    # ř. 5
    ("PLE", "R01", "U02", "P01", "BPLE02", "MEOP", "PN1005", "", "díl musí být ohnutý dle výkresu",
     "", 460, 500),                                                                         # ř. 6
    ("PLE", "R01", "U02", "P02", "BPLE03", "POL", "CE21RA 10 100194", "", "", "", 300, 500),  # ř. 7
    (),                                                                                    # ř. 8
    ("PLE", "R01", "U03", "P01", "BPLE04", "OPER", "D111", "", "", "", 300, 500),           # ř. 9
    ("PLE", "R01", "U03", "P01", "BPLE04", "OPER", "D222", "", "", "", 300, 500),           # ř. 10
    ("PLE", "R01", "U03", "P01", "BPLE04", "OPER", "D333", "", "", "", 300, 500),           # ř. 11
    (),                                                                                    # ř. 12
    ("PLE", "R01", "U03", "P02", "BPLE05", "0", "Volný box.", "20 kusů", "", "", 300, 500),  # ř. 13
    (),                                                                                    # ř. 14
    ("PLE", "R01", "U03", "P03", "BPLE06", "BLOK", "D444", "", "", "", 300, 500),           # ř. 15
    (),                                                                                    # ř. 16
    ("PLE", "R01", "U04", "P01", "BPLE07", "MULTI", "Volný slot.", "", "", "", 300, 500),   # ř. 17
    ("PLE", "R01", "U04", "P01", "BPLE07", "MULTI", "D555", "", "", "", 300, 500),          # ř. 18
    (),                                                                                    # ř. 19
    ("PLE", "R01", "U04", "P02", "BPLE08", "OPER › BLOK", "D666", "", "", "", 300, 500),    # ř. 20
    (),                                                                                    # ř. 21
    ("PLE", "R01", "U01", "P05", "BPLE11", "OPER", "D777", "", "", "", 300, 500),           # ř. 22
    ("PLE", "R01", "U05", "P01", "BPLE011", "OPER", "D888", "", "", "", 300, 500),          # ř. 23
    (),                                                                                    # ř. 24
    ("PLE", "R01", "U05", "P02", "BSTAT2", "OPER", "D999", "", "", "", 300, 500),           # ř. 25 STAT
    (),                                                                                    # ř. 26
    ("PLE", "R01", "U05", "P03", "KRAB21", "OPER", "DA100", "", "", "", 300, 500),          # ř. 27 cizí tvar
    (),                                                                                    # ř. 28
    ("1SV", "R01", "U05", "P04", "BPLE12", "OPER", "DA110", "", "", "", 300, 500),          # ř. 29
    (),                                                                                    # ř. 30
    ("NEZ", "R01", "U05", "P05", "BNEZ13", "OPER", "DA120", "", "", "", 300, 500),          # ř. 31 neznámé
    (),                                                                                    # ř. 32
    ("PLE", "R01", "U05", "P06", "BPLE14", "OPER", "DA130", "", "", "", None, 500),         # ř. 33 bez délky
    (),                                                                                    # ř. 34
    ("PLE", "R01", "U05", "P07", "BPLE15", "OPER", "DA140", "", "", "", "cca 300", 500),    # ř. 35
    (),                                                                                    # ř. 36
    ("PLE", "R01", "U00", "P01", "BPLE28", "MULTI", "DA150", "", "", "", 1200, 800),        # ř. 37
    ("PLE", "R01", "U00", "P01", "BPLE29", "OPER", "DA160", "", "", "", 600, 800),          # ř. 38
]

PUDORYS = [("Regál R01",), ("", "P01", "P02"), ("U01", "BPLE001", "BPLE003")]
NAPOVEDA = [("STAV_BOXU",), ("OPER", "operační díl"), ("MULTI", "více přihrádek v jednom boxu")]

LISTY = {"Databáze": DATABAZE, "Půdorys_regálu": PUDORYS, "Nápověda": NAPOVEDA}

# kolik má který list neprázdných buněk – přesně tolik musí ležet ve stg.Bunka
POCTY = {nazev: sum(1 for radek in radky for hodnota in radek if hodnota not in (None, ""))
         for nazev, radky in LISTY.items()}

# výsledek reportu nad sešitem výše: 18 boxů, 20 dílů („Volný box.“ a „Volný slot.“ díl nejsou)
SOUCET = "Součet – boxy: 18, díly: 20, chyby: 7, upozornění: 11"


def sestav_sesit(adresar: Path, listy: dict[str, list[tuple[Any, ...]]] | None = None,
                 nazev: str = NAZEV_SESITU) -> Path:
    """Vymyšlený sešit na disku; buňky se pisou na svou pozici, aby souřadnice ve stg.Bunka sedly."""
    sek = openpyxl.Workbook()
    sek.remove(sek.active)
    for nazev_listu, radky in (listy or LISTY).items():
        list_ = sek.create_sheet(nazev_listu)
        for cislo_radku, radek in enumerate(radky, start=1):
            for cislo_sloupce, hodnota in enumerate(radek, start=1):
                if hodnota not in (None, ""):
                    list_.cell(row=cislo_radku, column=cislo_sloupce, value=hodnota)
    soubor = adresar / nazev
    sek.save(soubor)
    return soubor


class ZakladMigrace(ZakladIntegrace):
    """Spojení v transakci a vymyšlený sešit ve dočasné složce."""

    def setUp(self) -> None:
        super().setUp()
        do_casu = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, do_casu, True)
        self.sesit = sestav_sesit(do_casu)

    def nacti(self) -> int:
        davka_id, _ = sluzby.nacti.__wrapped__(self.spoj, str(self.sesit))
        return davka_id

    def bunky(self, davka_id: int, nazev_listu: str) -> list[dict[str, Any]]:
        return self.spoj.dotaz("SELECT Radek, Sloupec, Hodnota FROM stg.Bunka"
                               " WHERE DavkaID = ? AND List = ? ORDER BY Radek, Sloupec", davka_id, nazev_listu)

    def pocty_listu(self, davka_id: int) -> dict[str, int]:
        return {nazev: self.spoj.hodnota("SELECT COUNT(*) FROM stg.Bunka WHERE DavkaID = ? AND List = ?",
                                         davka_id, nazev)
                for nazev in LISTY}


class TestNacti(ZakladMigrace):
    def test_nacti_davku_a_bunky_vsech_listu(self):
        davka_id, po_listech = sluzby.nacti.__wrapped__(self.spoj, str(self.sesit))

        davka = self.spoj.jeden("SELECT Soubor, NactenoKdy, NacetlUzivatelID FROM stg.Davka WHERE DavkaID = ?",
                                davka_id)
        self.assertEqual(davka["Soubor"], NAZEV_SESITU)      # název souboru bez cesty
        self.assertIsNotNone(davka["NactenoKdy"])            # výchozí SYSUTCDATETIME()
        self.assertIsNone(davka["NacetlUzivatelID"])         # z CLI nikdo přihlášený není

        self.assertEqual(po_listech, POCTY)                  # počty, které služba vrátí a příkaz vytiskne
        self.assertEqual(self.pocty_listu(davka_id), POCTY)  # a přesně tolik buněk leží ve stg.Bunka

    def test_cela_cisla_se_ulozi_bez_desetine_tecky(self):
        davka_id = self.nacti()
        # DÉLKA_BOXU_(mm) na ř. 3: Excel ji drží jako 300,0, do stagingu patří „300“
        hodnota = self.spoj.hodnota("SELECT Hodnota FROM stg.Bunka"
                                    " WHERE DavkaID = ? AND List = ? AND Radek = 3 AND Sloupec = 11",
                                    davka_id, "Databáze")
        self.assertEqual(hodnota, "300")

    def test_druhe_nacteni_nezmeni_tu_predchozi_davku(self):
        prvni, _ = sluzby.nacti.__wrapped__(self.spoj, str(self.sesit))
        druha, _ = sluzby.nacti.__wrapped__(self.spoj, str(self.sesit))

        self.assertNotEqual(prvni, druha)
        self.assertEqual(self.pocty_listu(prvni), POCTY)
        self.assertEqual(self.bunky(prvni, "Databáze"), self.bunky(druha, "Databáze"))

    def test_soubor_ktery_sestitem_neni(self):
        smeti = self.sesit.parent / "textovy-soubor.xlsm"
        smeti.write_text("tohle sešit rozhodně není", encoding="utf-8")
        davku_pred = self.spoj.hodnota("SELECT COUNT(*) FROM stg.Davka")

        with self.assertRaises(AppError) as volska:
            sluzby.nacti.__wrapped__(self.spoj, str(smeti))

        self.assertIn("není sešit", volska.exception.zprava)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM stg.Davka"), davku_pred)  # nic se neuložilo


class TestReport(ZakladMigrace):
    def setUp(self) -> None:
        super().setUp()
        self.hlaska = sluzby.report.__wrapped__(self.spoj, self.nacti())

    def nalezy(self, nadpis: str) -> list[str]:
        """Řádky sekce „Chyby:“ nebo „Upozornění:“; prázdnou sekci hlásí služba slovem „žádná/žádné“."""
        sekce = self.hlaska.split(f"{nadpis}\n")[1].split("\n\n")[0]
        return [radek for radek in sekce.splitlines() if not radek.strip().startswith(("žádná", "žádné"))]

    def test_seznam_importu_po_boxech(self):
        for radek in ("ř. 3 BPLE001 – PLE / R01 / U01 / P01, 300 × 500 mm, STAV_BOXU OPER",
                      "ř. 3: díl CE21RA 10 100194, minimum 50 ks, poznámka 1 kus na stroj; "
                      "Používat jen na servis, Vault http://srvvault2401.houfek.local/Vault/2/DILY/123.pdf",
                      "ř. 4: díl ABR31036_1, Vault srvvault2401/Vault/2/DILY/124.pdf",
                      "ř. 6: díl PN1005, poznámka díl musí být ohnutý dle výkresu",
                      "ř. 13 BPLE005 – PLE / R01 / U03 / P02, 300 × 500 mm, STAV_BOXU 0",
                      "ř. 17 BPLE007 – PLE / R01 / U04 / P01, 300 × 500 mm, STAV_BOXU MULTI",
                      "ř. 37 BPLE028 – PLE / R01 / U00 / P01, 1200 × 800 mm, STAV_BOXU MULTI"):
            self.assertIn(radek, self.hlaska)

        self.assertIn("díl D111", self.hlaska)                          # díly, které nic nehlásí, taky musí být
        self.assertEqual(len(re.findall(r"^  ř\. ", self.hlaska, re.MULTILINE)), 18)     # 18 boxů
        self.assertEqual(len(re.findall(r"^    ř\. ", self.hlaska, re.MULTILINE)), 20)   # 20 dílů
        self.assertIn(SOUCET, self.hlaska)

    def test_chyby_ktere_by_import_zastavily(self):
        for radek in ("ř. 22: kód BPLE011 po převodu používá více BOX_ID (BPLE11, BPLE011)",
                      "ř. 25: kód BSTAT002 není kód DYN boxu (parser ho vidí jako BOX)",     # statický box
                      "ř. 27: kód KRAB021 není kód DYN boxu (parser ho vidí jako TEXT)",     # cizí tvar kódu
                      "ř. 29: kód BPLE012 patří pracovišti PLE, řádek má 1SV",
                      "ř. 31: pracoviště NEZ není mezi aktivními pracovišti",
                      "ř. 33: box BPLE014 nemá rozměr délka",
                      "ř. 35: rozměr délka boxu BPLE015 není číslo (cca 300)"):
            self.assertIn(radek, self.hlaska)

    def test_upozorneni_pro_sklad(self):
        for radek in ("ř. 3: box BPLE001 bez členění a s 2 díly – návrh C2 nebo C5",
                      "ř. 9: box BPLE004 bez členění a s 3 díly – návrh C3",
                      "ř. 4: číslo dílu ABR31036_1 má podtržítko",
                      "ř. 3, 7: díl CE21RA 10 100194 je ve více boxech – založí se jednou",
                      "ř. 13: volný box BPLE005 má minimum",
                      "ř. 15: STAV_BOXU BLOK – box bude blokovaný (box BPLE006)",
                      "ř. 17: STAV_BOXU MULTI – box s více přihrádkami, členění nastaví sklad (box BPLE007)",
                      "ř. 20: STAV_BOXU OPER › BLOK není v seznamu 0, OPER, MEOP, POL, BLOK, MULTI",
                      "ř. 37: na pozici PLE / R01 / U00 / P01 stojí více boxů (BPLE028, BPLE029)",
                      "srvvault2401.houfek.local (ř. 3), srvvault2401 (ř. 4)"):
            self.assertIn(radek, self.hlaska)

    def test_kazdy_nalez_uzije_radek_listu(self):
        for nadpis in ("Chyby:", "Upozornění:"):
            for radek in self.nalezy(nadpis):
                self.assertIn("ř. ", radek, f"{nadpis} {radek}")

    def test_sezit_beze_hlavicky(self):
        soubor = sestav_sesit(self.sesit.parent, {"Databáze": [("Databáze boxů",), ("BOX", "ČÍSLO", "POZICE")]},
                              nazev="bez-hlavicky.xlsm")
        davka_id, _ = sluzby.nacti.__wrapped__(self.spoj, str(soubor))

        with self.assertRaises(AppError) as volska:
            sluzby.report.__wrapped__(self.spoj, davka_id)

        self.assertIn("není řádek hlavičky", volska.exception.zprava)
        # vypíše názvy, které na listu našel (nejširší řádek, tedy ř. 2 – ne titulek)
        self.assertIn("ř. 2: BOX, ČÍSLO, POZICE", volska.exception.zprava)

    def test_chybejici_sloupec(self):
        bez_rozmeru = [radek[:10] if cislo >= 1 else radek for cislo, radek in enumerate(DATABAZE)]
        soubor = sestav_sesit(self.sesit.parent, {"Databáze": bez_rozmeru}, nazev="bez-rozmeru.xlsm")
        davka_id, _ = sluzby.nacti.__wrapped__(self.spoj, str(soubor))

        with self.assertRaises(AppError) as volska:
            sluzby.report.__wrapped__(self.spoj, davka_id)

        self.assertIn("Řádek 2 nemá sloupce DÉLKA_BOXU_(mm), HLOUBKA_BOXU_(mm)", volska.exception.zprava)
        self.assertIn("VAULT PDF", volska.exception.zprava)

    def test_davka_ktera_neexistuje(self):
        with self.assertRaises(AppError) as volska:
            sluzby.report.__wrapped__(self.spoj, 999_999)
        self.assertEqual(volska.exception.kod, "NOT_FOUND")
        self.assertIn("999999", volska.exception.zprava)


class TestPrikazy(ZakladMigrace):
    """Jediný test, který pouští službu i s dekorátorem: `flask migrace` si otevírá vlastní spojení,
    takže dávka zůstane potvrzená i po rollbacku testu. Report bez `--davka` se proto kontroluje až po
    něm – nejnovější dávka musí být ta z příkazu, i když v téže databázi mají jiné ostrovy svá data.
    """

    def test_flask_migrace_nacti_a_report(self):
        nacteni = self.app.test_cli_runner().invoke(args=["migrace", "nacti", str(self.sesit)])
        self.assertEqual(nacteni.exit_code, 0, nacteni.output)
        self.assertIn(f"{sum(POCTY.values())} buněk", nacteni.output)
        self.assertIn(f"Databáze: {POCTY['Databáze']} buněk", nacteni.output)
        davka_id = int(re.search(r"Dávka (\d+)", nacteni.output)[1])

        hlaseni = self.app.test_cli_runner().invoke(args=["migrace", "report"])
        self.assertEqual(hlaseni.exit_code, 0, hlaseni.output)
        self.assertIn(f"Report dávky {davka_id} – soubor {NAZEV_SESITU}", hlaseni.output)
        self.assertIn(SOUCET, hlaseni.output)

    def test_prikaz_se_souborem_ktery_sestitem_neni(self):
        """AppError je chyba příkazu – ClickException bez tracebacku a bez uložené dávky."""
        smeti = self.sesit.parent / "textovy-soubor.xlsm"
        smeti.write_text("tohle sešit rozhodně není", encoding="utf-8")

        nacteni = self.app.test_cli_runner().invoke(args=["migrace", "nacti", str(smeti)])

        self.assertEqual(nacteni.exit_code, 1)
        self.assertIn("není sešit", nacteni.output)
