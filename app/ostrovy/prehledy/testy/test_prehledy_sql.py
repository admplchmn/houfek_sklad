"""Integrační testy ostrova G nad SQL Serverem: přehledy jedním dotazem nad pohledy (S-18).

Služby se volí `__wrapped__`, tedy bez dekorátoru @cteni – tělo běží ve spojení a transakci testu,
proto se na konci vše vrátí zpět. Strukturu zakládáme rozhraním ostrova C (`zaloz_*`), díly rozhraním
ostrova D (`zaloz_dil`); obsah, STAT přiřazení, pohyby a hlavičku transakce vkládáme přímo do tabulek
ostrova E a Platformy, protože jejich rozhraní na to zatím funkci nemá (`prirad_stat_misto` i
`zauctuj_korekci` jsou `NotImplementedError`).

Testy tvrdí jen o datech, která samy založily: monitoring omezují na vlastní pracoviště a laser na
tloušťku vlastní řady dílů (laser filtr pracoviště nemá), aby do výsledků nezasáhla potvrzená data
ostatních testů (jistky harnessu `tests/integrace/zaklad.py`). Kódy i ID se čtou z databáze.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.dily import sluzby as dily_sluzby
from app.ostrovy.prehledy import domena, sluzby
from app.ostrovy.prehledy.kontrakty import (
    HledaniFiltr,
    LaserFiltr,
    PohybyFiltr,
    ZasobyFiltr,
)
from app.ostrovy.prehledy.sluzby import POCET_POHYBU_NA_KARTE
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.kontrakty import DuvodVstup
from app.platforma.typy import Kontext, PotrebaMista
from tests.integrace.zaklad import ZakladIntegrace


class ZakladPrehledu(ZakladIntegrace):
    """Zázemí: vlastní pracoviště (kvůli jedinečným kódům), díly, místa s obsahem, pohyby, STAT."""

    def setUp(self) -> None:
        super().setUp()
        self.uzivatel_id = self.uzivatel_testu()
        self.kdo = Kontext(self.uzivatel_id, None, "ADMIN", frozenset())
        self.cele_jmeno = self.spoj.hodnota("SELECT CeleJmeno FROM dbo.v_Uzivatel WHERE UzivatelID = ?",
                                            self.uzivatel_id)
        self.pracoviste, self.pracoviste_id = self.nove_pracoviste()
        self._urovne = 0
        ciselniky = sluzby.ciselniky.__wrapped__(self.spoj)
        self.materialy = self._podle_kodu(ciselniky.materialy)
        self.tloustky = self._podle_kodu(ciselniky.tloustky)
        self.operace = self._podle_kodu(ciselniky.operace)

    @staticmethod
    def _podle_kodu(polozky) -> dict[str, int]:
        """Číselník ostrova G (přes rozhraní C, D, E) jako kód → ID; filtry přehledů jsou ID."""
        return {polozka.kod: polozka.id for polozka in polozky}

    # --- struktura (rozhraní ostrova C) -----------------------------------------------------------

    def nove_pracoviste(self) -> tuple[str, int]:
        """Pracoviště s kódem, který nikdo nepoužívá – kódy boxů i adresy míst jsou pak jedinečné."""
        dane = {polozka.kod for polozka in struktura.nacti_ciselniky(self.spoj)["pracoviste"]}
        while True:
            kod = "G" + uuid.uuid4().hex[:2].upper()
            if kod not in dane:
                return kod, struktura.zaloz_pracoviste(self.spoj, self.kdo, kod, None)

    def uroven(self) -> int:
        """Další regál na našem pracovišti s jednou úrovní (2400 × 800 mm); vrací UrovenID."""
        self._urovne += 1
        regal = struktura.zaloz_regal(self.spoj, self.kdo, self.pracoviste_id, f"R{self._urovne:02d}", None)
        return struktura.zaloz_uroven(self.spoj, self.kdo, regal, "U01", self._urovne, 2400, 800)

    def box(self, uroven_id: int, *, typ_boxu: str = "DYN", poradi: int | None = None) -> int:
        """Box s jedinou přihrádkou (členění C1, 600 × 400 mm); kód i FullBoxKlic doplní ostrov C."""
        return struktura.zaloz_box(self.spoj, self.kdo, uroven_id, poradi, typ_boxu, "C1",
                                   Decimal("600"), Decimal("400"))

    def misto(self, box_id: int) -> dict:
        """Jediná přihrádka boxu tak, jak ji vidí pohled v_Misto (z něj vychází i zvýraznění)."""
        return self.spoj.jeden("SELECT VnitrniPoziceID, KodMista, KodBoxu, TypBoxu, Adresa,"
                               " BoxID, UrovenID, RegalID FROM dbo.v_Misto WHERE BoxID = ?", box_id)

    def misto_s_obsahem(self, dil_id: int, *, uroven_id: int | None = None, typ_boxu: str = "DYN",
                        pocet_ks: int = 1) -> dict:
        """Místo s obsahem dílu; bez uvedené úrovni na vlastní nové úrovni. Vrací řádek z v_Misto."""
        misto = self.misto(self.box(uroven_id or self.uroven(), typ_boxu=typ_boxu))
        self.obsah(misto["VnitrniPoziceID"], dil_id, pocet_ks)
        return misto

    # --- díly (rozhraní ostrova D), obsah a STAT (tabulky E) --------------------------------------

    def dil(self, cislo: str, **pole) -> int:
        """Díl rozhraním ostrova D; výchozí číselníky jsou semena z migrace 001."""
        zaklad = {"nazev": f"Díl {cislo}", "material": "S235", "tloustka_mm": Decimal("3.00"),
                  "prvni_operace": "LASER", "standardni_davka_ks": 20, "potreba": PotrebaMista("V1")}
        return dily.zaloz_dil(self.spoj, self.kdo, dily.NovyDil(identifikacni_cislo=cislo, **(zaklad | pole)))

    def obsah(self, vnitrni_pozice_id: int, dil_id: int, pocet_ks: int) -> None:
        """Obsah pozice; nula v tabulce E neexistuje (při 0 ks se řádek maže), proto `pocet_ks` > 0."""
        self.spoj.proved("INSERT INTO dbo.ObsahPozice (VnitrniPoziceID, DilID, PocetKs) VALUES (?, ?, ?)",
                         vnitrni_pozice_id, dil_id, pocet_ks)

    def prirad_stat(self, dil_id: int, vnitrni_pozice_id: int, minimalni_ks: int,
                    maximalni_ks: int | None = None) -> int:
        """Statické přiřazení s min/max (OptimalniPocetKs přehledy nevyhodnocují)."""
        return self.spoj.vloz("INSERT INTO dbo.StatickeUmisteniDilu (DilID, VnitrniPoziceID,"
                              " MinimalniPocetKs, MaximalniPocetKs) VALUES (?, ?, ?, ?)",
                              dil_id, vnitrni_pozice_id, minimalni_ks, maximalni_ks)

    # --- pohyby a transakce (tabulky E a Platformy) -----------------------------------------------

    def pohyb(self, dil_id: int, misto: dict, typ_pohybu: str, *, cas: datetime, mnozstvi: int,
              stav_pred: int, transakce_id: uuid.UUID | None = None,
              poznamka: str | None = None) -> int:
        """Pohyb v UTC (ADR-0012); StavPo počítáme stejně, jak ho hlídá CHECK tabulky E."""
        return self.spoj.vloz(
            "INSERT INTO dbo.SkladovyPohyb (DatumCas, TypPohybuID, DilID, VnitrniPoziceID, Mnozstvi,"
            " StavPred, StavPo, UzivatelID, TransakceID, Poznamka)"
            " SELECT ?, TypPohybuID, ?, ?, ?, ?, ?, ?, ?, ? FROM dbo.TypPohybu WHERE KodPohybu = ?",
            cas, dil_id, misto["VnitrniPoziceID"], mnozstvi, stav_pred, stav_pred + mnozstvi,
            self.uzivatel_id, transakce_id, poznamka, typ_pohybu)

    def hlavicka_transakce(self, typ_operace: str = "PRESUN", *,
                           cas: datetime | None = None) -> uuid.UUID:
        """Hlavička skladové transakce (Platforma); za uživatele je technický uživatel testů."""
        transakce_id = uuid.uuid4()
        self.spoj.proved("INSERT INTO dbo.SkladovaTransakce (TransakceID, KlientRequestID, TypOperace,"
                         " UzivatelID, DatumCas) VALUES (?, ?, ?, ?, ?)",
                         transakce_id, uuid.uuid4(), typ_operace, self.uzivatel_id,
                         cas or datetime(2026, 10, 30, 9, 0))
        return transakce_id

    # --- volání služeb a ověřování ----------------------------------------------------------------

    def chyba(self, funkce, *args, kod_chyby: str, **pole) -> AppError:
        with self.assertRaises(AppError) as zachyceno:
            funkce(*args, **pole)
        self.assertEqual(zachyceno.exception.kod, kod_chyby, zachyceno.exception)
        return zachyceno.exception

    def sken(self, kod: str):
        return sluzby.sken.__wrapped__(self.spoj, kod)

    def hledej(self, **filtr):
        return sluzby.hledej.__wrapped__(self.spoj, HledaniFiltr(**filtr))

    def karta(self, dil_id: int):
        return sluzby.karta_dilu.__wrapped__(self.spoj, dil_id)

    def zasoby(self, **filtr):
        return sluzby.zasoby.__wrapped__(self.spoj, ZasobyFiltr(**filtr))

    def laser(self, **filtr):
        return sluzby.laser.__wrapped__(self.spoj, LaserFiltr(**filtr))

    def pohyby(self, **filtr):
        return sluzby.pohyby.__wrapped__(self.spoj, PohybyFiltr(**filtr))

    def transakce(self, transakce_id: uuid.UUID):
        return sluzby.transakce.__wrapped__(self.spoj, transakce_id)


class TestSkenAHledani(ZakladPrehledu):
    """Kap. 16 a 21.1.2: kód skladu, číslo dílu a filtry podle dílu i umístění – každý jedním dotazem."""

    def setUp(self) -> None:
        super().setUp()
        self.uroven_id = self.uroven()
        self.dil_lezici = self.dil("PREHLED 1", nazev="Bok levý ke hledání")
        self.stat = self.misto_s_obsahem(self.dil_lezici, uroven_id=self.uroven_id, typ_boxu="STAT", pocet_ks=8)
        self.dyn = self.misto_s_obsahem(self.dil_lezici, uroven_id=self.uroven_id, pocet_ks=4)
        self.dil_bez_ciselniku = self.dil("PREHLED 2", material=None, tloustka_mm=None, prvni_operace=None)
        self.dyn_druheho = self.misto_s_obsahem(self.dil_bez_ciselniku, pocet_ks=2)

    def test_sken_kodu_mista_vidi_obsah_a_vysvetli_prazdnou_pozici(self):
        """Zadání 12.2: po skenu pozice obsluha vidí díl a stav; zvýrazní se celá cesta k pozici."""
        naskenovana = self.sken(self.dyn["KodMista"]).polozky[0]
        self.assertEqual((naskenovana.typ, naskenovana.id, naskenovana.kod),
                         ("POZICE", self.dyn["VnitrniPoziceID"], self.dyn["KodMista"]))
        self.assertEqual((naskenovana.popis, naskenovana.adresa), ("PREHLED 1 · 4 ks", self.dyn["Adresa"]))
        self.assertEqual((naskenovana.obsah.dil_id, naskenovana.obsah.identifikacni_cislo,
                          naskenovana.obsah.pocet_ks), (self.dil_lezici, "PREHLED 1", 4))
        self.assertEqual((naskenovana.zvyrazneni.regal_id, naskenovana.zvyrazneni.uroven_id,
                          naskenovana.zvyrazneni.box_id, naskenovana.zvyrazneni.vnitrni_pozice_id),
                         (self.dyn["RegalID"], self.dyn["UrovenID"], self.dyn["BoxID"],
                          self.dyn["VnitrniPoziceID"]))
        prazdna = self.misto(self.box(self.uroven_id))
        self.assertEqual((self.sken(prazdna["KodMista"]).polozky[0].popis,
                          self.sken(prazdna["KodMista"]).polozky[0].obsah), ("prázdná", None))

    def test_sken_kodu_regalu_staci_rozhrani_c(self):
        """Regál žádný obsah nemá – vyhledává ho ostrov C, dotaz přehledů se u něj nedělá."""
        kod_regalu = self.spoj.hodnota("SELECT KodRegalu FROM dbo.v_Misto WHERE RegalID = ?",
                                       self.stat["RegalID"])
        naskenovany = self.sken(f"HOUFEK-{self.pracoviste}-{kod_regalu}").polozky[0]
        self.assertEqual((naskenovany.typ, naskenovany.id, naskenovany.popis, naskenovany.obsah),
                         ("REGAL", self.stat["RegalID"], None, None))
        self.assertEqual(naskenovany.adresa, naskenovany.kod)
        self.assertIsNone(naskenovany.zvyrazneni.vnitrni_pozice_id)

    def test_sken_cisla_dilu_presny_a_nepriny(self):
        self.assertEqual(self.sken("bok levý ke").polozky[0].id, self.dil_lezici)        # hledá i v názvu
        self.assertEqual(self.sken("PREHLED 9").polozky, [])
        presny = self.sken(" prehled  1 ")                                               # ořez, velká písmena
        self.assertTrue(presny.presny)
        self.assertEqual([(v.typ, v.id, v.popis) for v in presny.polozky],
                         [("DIL", self.dil_lezici, "Bok levý ke hledání")])
        # adresa výsledku dílu je jeho první umístění, tedy STAT místo (kap. 16); obsah se neukazuje
        self.assertEqual(presny.polozky[0].adresa, self.stat["Adresa"])
        self.assertIsNone(presny.polozky[0].obsah)
        nepriny = self.sken("PREHLED")
        self.assertFalse(nepriny.presny)
        self.assertEqual([v.id for v in nepriny.polozky], [self.dil_lezici, self.dil_bez_ciselniku])

    def test_hledani_s_filtry_dilu_a_umisteni(self):
        self.assertEqual([v.id for v in self.hledej(q="PREHLED").polozky],
                         [self.dil_lezici, self.dil_bez_ciselniku])
        self.assertEqual([v.id for v in self.hledej(q="prehled", typ_boxu="STAT").polozky], [self.dil_lezici])
        self.assertEqual([v.id for v in self.hledej(q="PREHLED", typ_boxu="DYN").polozky],
                         [self.dil_lezici, self.dil_bez_ciselniku])
        self.assertEqual([v.id for v in self.hledej(q="PREHLED", material_id=self.materialy["S235"]).polozky],
                         [self.dil_lezici])
        self.assertEqual([v.id for v in self.hledej(q="PREHLED", tloustka_id=self.tloustky["3.00"]).polozky],
                         [self.dil_lezici])
        self.assertEqual([v.id for v in
                          self.hledej(q="PREHLED", prvni_operace_id=self.operace["LASER"]).polozky],
                         [self.dil_lezici])
        self.assertEqual([v.id for v in self.hledej(q="PREHLED", pracoviste_id=self.pracoviste_id).polozky],
                         [self.dil_lezici, self.dil_bez_ciselniku])
        _, jine_pracoviste = self.nove_pracoviste()
        self.assertEqual(self.hledej(q="PREHLED", pracoviste_id=jine_pracoviste).polozky, [])

    def test_hledani_podle_zasoboveho_stavu(self):
        """Filtr zásobového stavu je součástí dotazu (21.1.2); díl bez STAT místa stav nemá."""
        self.prirad_stat(self.dil_lezici, self.stat["VnitrniPoziceID"], minimalni_ks=12, maximalni_ks=40)
        self.assertEqual([v.id for v in self.hledej(q="PREHLED", stav_zasoby="POD_MINIMEM").polozky],
                         [self.dil_lezici])
        self.assertEqual(self.hledej(q="PREHLED", stav_zasoby="OK").polozky, [])

    def test_hledani_nevidi_vyrazeny_dil_karta_ano(self):
        """Vyřazuje ostrov D: hledání i sken pracují jen s aktivními díly, karta ukáže i vyřazený."""
        # vyřazujeme díl bez umístění – ostrov D nenechá vyřadit díl, na kterém něco leží (NOT_EMPTY)
        vyrazeneho = self.dil("PREHLED 3")
        dily_sluzby.deaktivuj_dil.__wrapped__(self.spoj, vyrazeneho, DuvodVstup(duvod="konec výroby"), self.kdo)
        self.assertEqual([v.id for v in self.hledej(q="PREHLED").polozky],
                         [self.dil_lezici, self.dil_bez_ciselniku])
        self.assertEqual(self.sken("PREHLED 3").polozky, [])
        self.assertEqual(self.karta(vyrazeneho).identifikacni_cislo, "PREHLED 3")
        prvni = self.hledej(q="PREHLED").polozky[0]          # výsledek odkazuje na první umístění dílu
        self.assertEqual((prvni.zvyrazneni.vnitrni_pozice_id, prvni.adresa),
                         (self.stat["VnitrniPoziceID"], self.stat["Adresa"]))


class TestRozlozeniUrovne(ZakladPrehledu):
    """Kap. 17: geometrie z ostrova C, obsah a barva boxu; vyhodnocuje `domena.py` (7.2, Q-31)."""

    def setUp(self) -> None:
        super().setUp()
        self.uroven_id = self.uroven()
        self.dil_modra = self.dil("PREHLED 4", vault_url="https://vault.example/vykres-4.pdf")
        self.dil_seda = self.dil("PREHLED 5")
        self.box_prazdny = self.misto(self.box(self.uroven_id, poradi=1))
        self.box_dyn = self.misto(self.box(self.uroven_id, poradi=2))
        self.obsah(self.box_dyn["VnitrniPoziceID"], self.dil_modra, 8)
        self.box_stat = self.misto(self.box(self.uroven_id, typ_boxu="STAT", poradi=3))
        self.obsah(self.box_stat["VnitrniPoziceID"], self.dil_seda, 3)

    def test_barvy_boxu_obsah_a_vault(self):
        vystup = sluzby.rozlozeni.__wrapped__(self.spoj, self.uroven_id)
        self.assertEqual((vystup.uroven_id, vystup.kod_urovne, vystup.regal_id, vystup.pracoviste),
                         (self.uroven_id, "U01", self.box_dyn["RegalID"], self.pracoviste))
        self.assertEqual([b.kod_pozice_urovne for b in vystup.boxy], ["P01", "P02", "P03"])
        self.assertEqual({b.kod_boxu: (b.stav_boxu, b.barva) for b in vystup.boxy},
                         {self.box_prazdny["KodBoxu"]: ("VOLNY", "ZELENA"),
                          self.box_dyn["KodBoxu"]: ("OBSAZENY", "MODRA"),        # DYN s obsahem (Q-31)
                          self.box_stat["KodBoxu"]: ("OBSAZENY", "SEDA")})      # STAT s obsahem (7.2)
        modry = next(b for b in vystup.boxy if b.kod_boxu == self.box_dyn["KodBoxu"])
        self.assertEqual([(p.dil_id, p.identifikacni_cislo, p.pocet_ks, p.vault_url) for p in modry.pozice],
                         [(self.dil_modra, "PREHLED 4", 8, "https://vault.example/vykres-4.pdf")])
        prazdna = vystup.boxy[0].pozice[0]
        self.assertEqual((prazdna.dil_id, prazdna.identifikacni_cislo, prazdna.pocet_ks, prazdna.vault_url),
                         (None, None, 0, None))
        self.assertEqual((prazdna.vnitrni_pozice_id, prazdna.kod, prazdna.velikost, prazdna.blokovana),
                         (self.box_prazdny["VnitrniPoziceID"], self.box_prazdny["KodMista"], "V1", False))

    def test_rozmery_a_poradi_boxu_zleva_prebirame_z_ostrova_c(self):
        """Geometrii počítá ostrov C (17.1); G ji jen předává – ověřujeme, že boxy jdou za sebou."""
        vystup = sluzby.rozlozeni.__wrapped__(self.spoj, self.uroven_id)
        self.assertEqual([b.delka_mm for b in vystup.boxy], [600.0, 600.0, 600.0])
        self.assertEqual([b.hloubka_mm for b in vystup.boxy], [400.0, 400.0, 400.0])
        self.assertEqual([b.x_mm for b in vystup.boxy], sorted(b.x_mm for b in vystup.boxy))
        self.assertLess(vystup.boxy[0].x_mm, vystup.boxy[2].x_mm)

    def test_blokovany_box_je_cerveny(self):
        """Blokaci drží ostrov C; barvu z ní počítá `domena.barva_boxu` – červená je pro oba typy boxu."""
        self.spoj.proved("UPDATE dbo.Box SET Blokovany = 1 WHERE BoxID = ?", self.box_dyn["BoxID"])
        vystup = sluzby.rozlozeni.__wrapped__(self.spoj, self.uroven_id)
        self.assertEqual(next(b.barva for b in vystup.boxy if b.kod_boxu == self.box_dyn["KodBoxu"]), "CERVENA")

    def test_neznama_uroven(self):
        self.chyba(sluzby.rozlozeni.__wrapped__, self.spoj, 2_000_000_000, kod_chyby="NOT_FOUND")


class TestKartaDilu(ZakladPrehledu):
    """Kap. 15 / T01: kmenová data, STAT místo s min/max, všechna umístění a poslední pohyby."""

    def setUp(self) -> None:
        super().setUp()
        self.uroven_id = self.uroven()
        self.dil_id = self.dil("PREHLED 6", nazev="Bok levý", standardni_davka_ks=20,
                               vault_url="https://vault.example/vykres.pdf")
        self.stat = self.misto_s_obsahem(self.dil_id, uroven_id=self.uroven_id, typ_boxu="STAT", pocet_ks=8)
        self.dyn1 = self.misto_s_obsahem(self.dil_id, uroven_id=self.uroven_id, pocet_ks=4)
        self.dyn2 = self.misto_s_obsahem(self.dil_id, pocet_ks=3)
        self.stat_prirazeni = self.prirad_stat(self.dil_id, self.stat["VnitrniPoziceID"], 12, 40)

    def test_kmenova_data(self):
        karta = self.karta(self.dil_id)
        self.assertEqual((karta.dil_id, karta.identifikacni_cislo, karta.nazev, karta.material,
                          karta.tloustka_mm, karta.prvni_operace, karta.standardni_davka_ks, karta.velikost),
                         (self.dil_id, "PREHLED 6", "Bok levý", "S235", Decimal("3.00"), "LASER", 20, "V1"))
        self.assertEqual(karta.vault_url, "https://vault.example/vykres.pdf")

    def test_stat_misto_se_stavem_zasoby(self):
        """Stav zásoby počítá pohled v_ZasobaDilu (ostrov E); G z něj čte i počet chybějící do maxima."""
        stat = self.karta(self.dil_id).stat
        self.assertEqual((stat.stat_umisteni_id, stat.kod, stat.kod_boxu),
                         (self.stat_prirazeni, self.stat["KodMista"], self.stat["KodBoxu"]))
        self.assertEqual((stat.stav_ks, stat.minimalni_ks, stat.optimalni_ks, stat.maximalni_ks),
                         (8, 12, None, 40))
        self.assertEqual((stat.stav_zasoby, stat.chybi_do_maxima_ks), ("POD_MINIMEM", 32))

    def test_umisteni_stat_prvni_pak_dyn_podle_cisla_boxu(self):
        karta = self.karta(self.dil_id)
        self.assertEqual([u.kod for u in karta.umisteni],
                         [self.stat["KodMista"], self.dyn1["KodMista"], self.dyn2["KodMista"]])
        self.assertEqual([u.pocet_ks for u in karta.umisteni], [8, 4, 3])
        self.assertEqual([u.typ_boxu for u in karta.umisteni], ["STAT", "DYN", "DYN"])
        self.assertEqual([u.adresa for u in karta.umisteni],
                         [self.stat["Adresa"], self.dyn1["Adresa"], self.dyn2["Adresa"]])
        self.assertEqual(karta.umisteni[1].zvyrazneni.vnitrni_pozice_id, self.dyn1["VnitrniPoziceID"])
        self.assertEqual((karta.dyn_ks, karta.celkem_ks), (7, 15))

    def test_posledni_pohyby_nejvyssi_prvni(self):
        self.pohyb(self.dil_id, self.dyn1, "PRIJEM", cas=datetime(2026, 10, 26, 8, 0), mnozstvi=4,
                   stav_pred=0, poznamka="příjem do DYN")
        self.pohyb(self.dil_id, self.stat, "KOREKCE", cas=datetime(2026, 10, 28, 10, 30), mnozstvi=-2,
                   stav_pred=10)
        nejnovejsi = [self.pohyb(self.dil_id, self.stat, "VYDEJ", cas=datetime(2026, 10, 30, 7, 0),
                                 mnozstvi=-4, stav_pred=12) for _ in range(POCET_POHYBU_NA_KARTE)]
        karta = self.karta(self.dil_id)
        self.assertEqual([p.pohyb_id for p in karta.posledni_pohyby], list(reversed(nejnovejsi)))
        self.assertEqual(len(karta.posledni_pohyby), POCET_POHYBU_NA_KARTE)
        pohyb = karta.posledni_pohyby[0]
        self.assertEqual((pohyb.datum_cas, pohyb.typ_pohybu, pohyb.identifikacni_cislo, pohyb.kod),
                         (datetime(2026, 10, 30, 7, 0), "VYDEJ", "PREHLED 6", self.stat["KodMista"]))
        self.assertEqual((pohyb.mnozstvi, pohyb.stav_pred_ks, pohyb.stav_po_ks), (-4, 12, 8))
        self.assertEqual((pohyb.uzivatel_id, pohyb.cele_jmeno, pohyb.terminal_id),
                         (self.uzivatel_id, self.cele_jmeno, None))
        self.assertIsNone(pohyb.skladova_transakce_id)
        self.assertIsNone(karta.posledni_pohyby[-1].poznamka)

    def test_transakce_se_v_history_prenasi(self):
        transakce_id = self.hlavicka_transakce("PRIJEM_STAT", cas=datetime(2026, 10, 27, 6, 0))
        pohyb_id = self.pohyb(self.dil_id, self.stat, "PRIJEM", cas=datetime(2026, 10, 27, 6, 0),
                              mnozstvi=8, stav_pred=0, transakce_id=transakce_id)
        posledni = self.karta(self.dil_id).posledni_pohyby[0]
        self.assertEqual((posledni.pohyb_id, posledni.skladova_transakce_id), (pohyb_id, transakce_id))

    def test_dil_bez_stat_a_nezname_id(self):
        druhy = self.dil("PREHLED 7")
        dyn = self.misto_s_obsahem(druhy, pocet_ks=5)
        karta = self.karta(druhy)
        self.assertIsNone(karta.stat)
        self.assertEqual((karta.dyn_ks, karta.celkem_ks), (5, 5))
        self.assertEqual([(u.kod, u.adresa, u.typ_boxu) for u in karta.umisteni],
                         [(dyn["KodMista"], dyn["Adresa"], "DYN")])
        self.chyba(self.karta, 2_000_000_000, kod_chyby="NOT_FOUND")


class TestZasobyAZasobovychStavu(ZakladPrehledu):
    """Kap. 13.1: STAT a DYN zvlášť, stav podle STAT, souhrn za celý filtr, řazení nejhorší první."""

    def setUp(self) -> None:
        super().setUp()
        self.uroven_id = self.uroven()
        self.dil_vycerpany = self.dil("PREHLED 11", nazev="Sestava")
        self.stat_vycerpany = self.misto(self.box(self.uroven_id, typ_boxu="STAT"))   # STAT bez obsahu
        self.prirad_stat(self.dil_vycerpany, self.stat_vycerpany["VnitrniPoziceID"], 5, 50)
        self.dyn_vycerpany = self.misto_s_obsahem(self.dil_vycerpany, pocet_ks=3)
        self.dil_pod_minimem = self.dil("PREHLED 12")
        self.stat_pod_minimem = self.misto_s_obsahem(self.dil_pod_minimem, uroven_id=self.uroven_id,
                                                    typ_boxu="STAT", pocet_ks=4)
        self.prirad_stat(self.dil_pod_minimem, self.stat_pod_minimem["VnitrniPoziceID"], 10, 40)
        self.dil_na_minimu = self.dil("PREHLED 13")
        self.stat_na_minimu = self.misto_s_obsahem(self.dil_na_minimu, uroven_id=self.uroven_id,
                                                  typ_boxu="STAT", pocet_ks=10)
        self.prirad_stat(self.dil_na_minimu, self.stat_na_minimu["VnitrniPoziceID"], 10, 40)
        self.dil_ok = self.dil("PREHLED 14", material="S355")
        self.stat_ok = self.misto_s_obsahem(self.dil_ok, uroven_id=self.uroven_id, typ_boxu="STAT", pocet_ks=30)
        self.prirad_stat(self.dil_ok, self.stat_ok["VnitrniPoziceID"], 10, 40)
        self.dil_jen_dyn = self.dil("PREHLED 15", prvni_operace="PILA")
        self.dyn_jen_dyn = self.misto_s_obsahem(self.dil_jen_dyn, pocet_ks=7)

    def zasoby(self, **filtr):
        """Monitoring jen na našem pracovišti – potvrzená data ostatních testů do výsledků nepatří."""
        return super().zasoby(pracoviste_id=filtr.pop("pracoviste_id", self.pracoviste_id), **filtr)

    def test_vypocteni_stavu_jen_dily_se_stat(self):
        vystup = self.zasoby()
        self.assertEqual([r.identifikacni_cislo for r in vystup.polozky],
                         ["PREHLED 11", "PREHLED 12", "PREHLED 13", "PREHLED 14"])   # nejhorší stav první
        self.assertEqual((vystup.celkem, vystup.strana, vystup.velikost), (4, 1, 50))
        self.assertEqual((vystup.souhrn.sledovane, vystup.souhrn.vycerpano, vystup.souhrn.pod_minimem,
                          vystup.souhrn.na_minimu, vystup.souhrn.ok), (4, 1, 1, 1, 1))

    def test_stat_a_dyn_zvlast_a_kazde_umisteni_zvlast(self):
        radek = next(r for r in self.zasoby().polozky if r.identifikacni_cislo == "PREHLED 11")
        self.assertEqual((radek.nazev, radek.material, radek.tloustka_mm, radek.prvni_operace),
                         ("Sestava", "S235", Decimal("3.00"), "LASER"))
        self.assertEqual((radek.stat_ks, radek.dyn_ks, radek.celkem_ks), (0, 3, 3))
        self.assertEqual((radek.minimalni_ks, radek.maximalni_ks, radek.stav_zasoby), (5, 50, "VYCERPANO"))
        self.assertEqual(radek.umisteni, "STAT + DYN")
        self.assertEqual([m.kod for m in radek.mista], [self.dyn_vycerpany["KodMista"]])
        self.assertEqual(radek.zvyrazneni.vnitrni_pozice_id, self.stat_vycerpany["VnitrniPoziceID"])

    def test_jensestat_false_prida_dily_jen_v_dyn_nakonec(self):
        vystup = self.zasoby(jen_se_stat=False)
        self.assertEqual([r.identifikacni_cislo for r in vystup.polozky],
                         ["PREHLED 11", "PREHLED 12", "PREHLED 13", "PREHLED 14", "PREHLED 15"])
        self.assertEqual(vystup.souhrn.sledovane, 4)                         # souhrn jen za díly se STAT
        radek = vystup.polozky[-1]
        self.assertEqual((radek.stat_ks, radek.dyn_ks, radek.celkem_ks), (0, 7, 7))
        self.assertEqual((radek.minimalni_ks, radek.maximalni_ks, radek.stav_zasoby), (None, None, None))
        self.assertEqual(radek.umisteni, "DYN")
        self.assertEqual([m.kod for m in radek.mista], [self.dyn_jen_dyn["KodMista"]])
        self.assertEqual(radek.zvyrazneni.vnitrni_pozice_id, self.dyn_jen_dyn["VnitrniPoziceID"])

    def test_jen_problemove_nemeni_souhrn(self):
        vystup = self.zasoby(jen_problemove=True)
        self.assertEqual([r.identifikacni_cislo for r in vystup.polozky],
                         ["PREHLED 11", "PREHLED 12", "PREHLED 13"])
        self.assertEqual((vystup.celkem, vystup.souhrn.sledovane), (3, 4))
        self.assertEqual([r.identifikacni_cislo for r in self.zasoby(stav_zasoby="OK").polozky], ["PREHLED 14"])
        self.assertEqual([r.identifikacni_cislo for r in self.zasoby(stav_zasoby="NA_MINIMU").polozky],
                         ["PREHLED 13"])

    def test_filtry_a_strankovani_v_sql(self):
        self.assertEqual([r.identifikacni_cislo for r in self.zasoby(material_id=self.materialy["S355"]).polozky],
                         ["PREHLED 14"])
        self.assertEqual([r.identifikacni_cislo for r in
                          self.zasoby(jen_se_stat=False,
                                      prvni_operace_id=self.operace["PILA"]).polozky], ["PREHLED 15"])
        _, jine_pracoviste = self.nove_pracoviste()
        self.assertEqual(self.zasoby(pracoviste_id=jine_pracoviste).polozky, [])
        self.assertEqual(self.zasoby(jen_se_stat=False, pracoviste_id=jine_pracoviste).polozky, [])
        druha_strana = self.zasoby(velikost=1, strana=2)
        self.assertEqual(([r.identifikacni_cislo for r in druha_strana.polozky], druha_strana.celkem,
                          druha_strana.strana, druha_strana.velikost), (["PREHLED 12"], 4, 2, 1))
        self.assertEqual(self.zasoby(velikost=1, strana=5).polozky, [])


class TestLaser(ZakladPrehledu):
    """Kap. 14 / T09: díly s maximem ve STAT, první operace LASER, doporučení v obou režimech Q-22."""

    TLOUSTKA = Decimal("4.00")

    def setUp(self) -> None:
        super().setUp()
        self.tloustka_id = self.tloustky["4.00"]
        self.dil_chybi = self.dil("PREHLED 21", tloustka_mm=self.TLOUSTKA)              # max 40, STAT 12, DYN 8
        self.stat_chybi = self.misto_s_obsahem(self.dil_chybi, typ_boxu="STAT", pocet_ks=12)
        self.prirad_stat(self.dil_chybi, self.stat_chybi["VnitrniPoziceID"], 10, 40)
        self.misto_s_obsahem(self.dil_chybi, pocet_ks=8)
        self.dil_plny = self.dil("PREHLED 22", tloustka_mm=self.TLOUSTKA, material="S355")   # max 20, STAT 20
        self.stat_plny = self.misto_s_obsahem(self.dil_plny, typ_boxu="STAT", pocet_ks=20)
        self.prirad_stat(self.dil_plny, self.stat_plny["VnitrniPoziceID"], 5, 20)
        self.dil_pila = self.dil("PREHLED 23", tloustka_mm=self.TLOUSTKA, prvni_operace="PILA")
        self.stat_pila = self.misto_s_obsahem(self.dil_pila, typ_boxu="STAT", pocet_ks=1)
        self.prirad_stat(self.dil_pila, self.stat_pila["VnitrniPoziceID"], 1, 100)
        self.dil_bez_maxima = self.dil("PREHLED 24", tloustka_mm=self.TLOUSTKA)
        self.stat_bez_maxima = self.misto_s_obsahem(self.dil_bez_maxima, typ_boxu="STAT", pocet_ks=1)
        self.prirad_stat(self.dil_bez_maxima, self.stat_bez_maxima["VnitrniPoziceID"], 1)

    def laser(self, **filtr):
        """Laser nemá filtr pracoviště – řadu našich dílů odděluje tloušťka (viz doklad třídy)."""
        return super().laser(tloustka_id=filtr.pop("tloustka_id", self.tloustka_id), **filtr)

    def test_jen_laser_podle_filtru_a_pod_maximem(self):
        vystup = self.laser()
        self.assertEqual([(r.identifikacni_cislo, r.prvni_operace, r.chybi_ve_stat_ks) for r in vystup.polozky],
                         [("PREHLED 21", "LASER", 28)])         # PILA i díl bez maxima ven, STAT pod maximem
        self.assertEqual(vystup.celkem, 1)
        radek = vystup.polozky[0]
        self.assertEqual((radek.stat_ks, radek.dyn_ks, radek.maximalni_ks, radek.standardni_davka_ks),
                         (12, 8, 40, 20))
        self.assertEqual([r.identifikacni_cislo for r in self.laser(jen_pod_maximem=False).polozky],
                         ["PREHLED 21", "PREHLED 22"])          # nulové chybí se objeví až bez filtru
        self.assertEqual([r.identifikacni_cislo for r in
                          self.laser(prvni_operace_id=self.operace["PILA"], jen_pod_maximem=False).polozky],
                         ["PREHLED 23"])

    def test_odecitat_dyn_obdva_rezimy(self):
        """Q-22: přepínač mění jen doporučený počet, „chybí ve STAT“ je definované zadáním (kap. 14)."""
        self.assertEqual([(r.chybi_ve_stat_ks, r.doporuceno_ks) for r in self.laser().polozky], [(28, 40)])
        self.assertEqual([(r.chybi_ve_stat_ks, r.doporuceno_ks) for r in
                          self.laser(odecitat_dyn=True).polozky], [(28, 20)])

    def test_radi_se_podle_nejvetsiho_chybeni(self):
        druhy = self.dil("PREHLED 25", tloustka_mm=self.TLOUSTKA, standardni_davka_ks=None)   # max 50, STAT 1
        stat = self.misto_s_obsahem(druhy, typ_boxu="STAT", pocet_ks=1)
        self.prirad_stat(druhy, stat["VnitrniPoziceID"], 1, 50)
        self.assertEqual([(r.identifikacni_cislo, r.chybi_ve_stat_ks, r.doporuceno_ks) for r in self.laser().polozky],
                         [("PREHLED 25", 49, 49), ("PREHLED 21", 28, 40)])    # bez dávky se nezaokrouhluje

    def test_filtry_materialu_a_tloustky(self):
        self.assertEqual([r.identifikacni_cislo for r in
                          self.laser(material_id=self.materialy["S355"], tloustka_id=self.tloustka_id,
                                     jen_pod_maximem=False).polozky], ["PREHLED 22"])
        self.assertEqual(self.laser(material_id=self.materialy["ALMG3"]).polozky, [])
        self.assertEqual(self.laser(tloustka_id=self.tloustky["5.00"]).polozky, [])


class TestPohyby(ZakladPrehledu):
    """Kap. 9 a 17: historie nejnovější první, stránkování v SQL, období ve dnech Europe/Prague."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id = self.dil("PREHLED 31")
        self.pozice = self.misto_s_obsahem(self.dil_id, pocet_ks=1)
        # říjen 2026: do 25. 10. letní čas (UTC+2), pak zimní (UTC+1); časy v DB jsou UTC (ADR-0012)
        self.pred_prechodem = self.pohyb(self.dil_id, self.pozice, "KOREKCE", cas=datetime(2026, 10, 24, 21, 30),
                                         mnozstvi=1, stav_pred=0)
        self.po_prechodu = self.pohyb(self.dil_id, self.pozice, "KOREKCE", cas=datetime(2026, 10, 25, 22, 30),
                                      mnozstvi=1, stav_pred=1)
        self.vecer_29 = self.pohyb(self.dil_id, self.pozice, "VYDEJ", cas=datetime(2026, 10, 29, 22, 59),
                                   mnozstvi=-1, stav_pred=2)
        self.rano_30 = self.pohyb(self.dil_id, self.pozice, "PRIJEM", cas=datetime(2026, 10, 29, 23, 30),
                                  mnozstvi=1, stav_pred=1)
        self.vecer_30 = self.pohyb(self.dil_id, self.pozice, "VYDEJ", cas=datetime(2026, 10, 30, 22, 59),
                                   mnozstvi=-1, stav_pred=2)
        self.noci_31 = self.pohyb(self.dil_id, self.pozice, "PRIJEM", cas=datetime(2026, 10, 30, 23, 0),
                                  mnozstvi=1, stav_pred=1)

    def pohyby(self, **filtr):
        """Historie vždy jen pro náš díl – potvrzená data ostatních testů do výsledků nepatří."""
        return super().pohyby(dil_id=filtr.pop("dil_id", self.dil_id), **filtr)

    def test_obdobi_vcele_okraju_dne(self):
        """Od i do jsou dny včetně okrajů; hranice leží v UTC, proto 29. 10. 23:30 patří na 30. 10."""
        self.assertEqual([p.pohyb_id for p in self.pohyby(od=date(2026, 10, 30), do=date(2026, 10, 30)).polozky],
                         [self.vecer_30, self.rano_30])
        self.assertEqual([p.pohyb_id for p in self.pohyby(od=date(2026, 10, 31)).polozky], [self.noci_31])
        self.assertEqual([p.pohyb_id for p in self.pohyby(do=date(2026, 10, 29)).polozky],
                         [self.vecer_29, self.po_prechodu, self.pred_prechodem])

    def test_obdobi_pres_prechod_na_zimni_cas(self):
        """Den 25. 10. 2026 má 25 hodin – hranice se počítají ze zóny, ne z pevného posunu."""
        self.assertEqual([p.pohyb_id for p in self.pohyby(od=date(2026, 10, 25), do=date(2026, 10, 25)).polozky],
                         [self.po_prechodu])
        self.assertEqual([p.pohyb_id for p in self.pohyby(od=date(2026, 10, 24), do=date(2026, 10, 24)).polozky],
                         [self.pred_prechodem])
        self.assertEqual(self.pohyby(od=date(2026, 10, 24), do=date(2026, 10, 31)).celkem, 6)

    def test_filtry_a_strankovani(self):
        self.assertEqual(self.pohyby().celkem, 6)
        self.assertEqual(self.pohyby(dil_id=2_000_000_000).polozky, [])
        self.assertEqual([p.pohyb_id for p in self.pohyby(kod=self.misto["KodMista"]).polozky][0], self.noci_31)
        self.assertEqual(self.pohyby(vnitrni_pozice_id=self.misto["VnitrniPoziceID"]).celkem, 6)
        self.assertEqual([p.pohyb_id for p in self.pohyby(typ_pohybu="KOREKCE").polozky],
                         [self.po_prechodu, self.pred_prechodem])
        self.assertEqual([p.pohyb_id for p in self.pohyby(uzivatel_id=self.uzivatel_id).polozky][0], self.noci_31)
        self.assertEqual(self.pohyby(uzivatel_id=2_000_000_000).polozky, [])
        druha_strana = self.pohyby(velikost=2, strana=2)
        self.assertEqual(([p.pohyb_id for p in druha_strana.polozky], druha_strana.celkem, druha_strana.strana,
                          druha_strana.velikost), ([self.rano_30, self.vecer_29], 6, 2, 2))

    def test_pohyb_bez_transakce_a_neznamy_kod(self):
        self.assertIsNone(self.pohyby().polozky[0].skladova_transakce_id)
        self.chyba(self.pohyby, kod="BZZZ999-A", kod_chyby="NOT_FOUND")


class TestTransakce(ZakladPrehledu):
    """Kap. 9: PRESUN-OUT + PRESUN-IN mají stejné TransakceID; typ, čas a uživatel jsou z hlavičky."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id = self.dil("PREHLED 32")
        self.uroven_id = self.uroven()
        self.odkud = self.misto_s_obsahem(self.dil_id, uroven_id=self.uroven_id, pocet_ks=6)
        self.kam = self.misto(self.box(self.uroven_id))
        self.transakce_id = self.hlavicka_transakce("PRESUN", cas=datetime(2026, 10, 28, 14, 15))
        self.pohyb_out = self.pohyb(self.dil_id, self.odkud, "PRESUN-OUT", cas=datetime(2026, 10, 28, 14, 15),
                                    mnozstvi=-6, stav_pred=6, transakce_id=self.transakce_id)
        self.pohyb_in = self.pohyb(self.dil_id, self.kam, "PRESUN-IN", cas=datetime(2026, 10, 28, 14, 15),
                                   mnozstvi=6, stav_pred=0, transakce_id=self.transakce_id,
                                   poznamka="presun do DYN")

    def test_pohyby_se_spolecnym_id(self):
        detail = self.transakce(self.transakce_id)
        self.assertEqual(detail.skladova_transakce_id, self.transakce_id)
        self.assertEqual((detail.typ_operace, detail.datum_cas), ("PRESUN", datetime(2026, 10, 28, 14, 15)))
        self.assertEqual((detail.uzivatel_id, detail.cele_jmeno, detail.terminal_id),
                         (self.uzivatel_id, self.cele_jmeno, None))
        self.assertEqual([(p.pohyb_id, p.typ_pohybu, p.kod, p.mnozstvi) for p in detail.pohyby],
                         [(self.pohyb_out, "PRESUN-OUT", self.odkud["KodMista"], -6),
                          (self.pohyb_in, "PRESUN-IN", self.kam["KodMista"], 6)])
        self.assertEqual({p.skladova_transakce_id for p in detail.pohyby}, {self.transakce_id})
        self.assertEqual(detail.pohyby[1].poznamka, "presun do DYN")

    def test_hlavicka_bez_pohybu(self):
        detail = self.transakce(self.hlavicka_transakce("BLOKACE"))
        self.assertEqual((detail.typ_operace, detail.pohyby), ("BLOKACE", []))

    def test_nezname_id(self):
        self.chyba(self.transakce, uuid.uuid4(), kod_chyby="NOT_FOUND")


class TestCiselniky(ZakladPrehledu):
    """7.7: všechny hodnoty pro filtry najednou – číselníky ostrovů C, D, E a pevné technické kódy."""

    def test_ciselniky_obsahuji_data_z_databaze(self):
        vystup = sluzby.ciselniky.__wrapped__(self.spoj)
        self.assertIn((self.pracoviste, True), [(r.kod, r.aktivni) for r in vystup.pracoviste])
        self.assertIn("S235", {r.kod for r in vystup.materialy})
        self.assertIn("3.00", {r.kod for r in vystup.tloustky})
        self.assertIn("LASER", {r.kod for r in vystup.operace})
        self.assertIn("V1", {r.kod for r in vystup.velikosti})
        self.assertTrue(vystup.typy_pohybu)
        self.assertEqual(vystup.typy_boxu, ["DYN", "STAT"])
        self.assertEqual(vystup.stavy_zasoby, list(domena.STAVY_ZASOBY))


if __name__ == "__main__":
    unittest.main()
