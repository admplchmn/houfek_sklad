"""Integrační testy ostrova F nad SQL Serverem: inventura za provozu (D-26) a plán korekcí (D-27).

Služby se volí `__wrapped__`, tedy bez dekorátoru: tělo běží ve spojení a transakci testu, takže se
na konci vše vrátí zpět (@transakce si otevírá vlastní spojení a potvrzuje).

Strukturu zakládáme rozhraním ostrova C a díly rozhraním ostrova D; obsah pozic, pohyby a STAT
přiřazení píše test přímo do tabulek ostrova E, protože z cizího ostrova smí test importovat jen
`rozhrani` a `ukazky` (P3) a `zauctuj_korekci` ani `prirad_stat_misto` ostrov E ještě neumí.
Vypnutí pozice (výsledek rekonfigurace) píše test do `dbo.VnitrniPoziceBoxu`, to ostrov C umí až ve
fázi 2. Každý test má pracoviště s jedinečným kódem a tvrdí něco jen o datech, která sám založil –
potvrzená data ostatních ostrovů v databázi zůstávají.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.dily.rozhrani import NovyDil
from app.ostrovy.inventura import sluzby
from app.ostrovy.inventura.kontrakty import DokonceniVstup, InventuryFiltr, NovaInventuraVstup, ZapisPolozkyVstup
from app.ostrovy.sklad import rozhrani as sklad
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.db import Spojeni
from app.platforma.kontrakty import DuvodVstup
from app.platforma.typy import Kontext, PotrebaMista
from tests.integrace.zaklad import ZakladIntegrace

# krátká krabice C4 = čtyři přihrádky V3 (DYN štěrby G, H, CH, I / STAT 4, 3, 1, 2)
ROZMER_C4 = (Decimal(400), Decimal(360))


def novy_kod_pracoviste(spoj: Spojeni) -> str:
    """Kód pracoviště (3 znaky 0–9A–Z), který ještě nikdo nepoužil – potvrzená data v DB zůstávají."""
    while True:
        kod = "T" + uuid.uuid4().hex[:2].upper()
        if not spoj.hodnota("SELECT COUNT(*) FROM dbo.Pracoviste WHERE KodPracoviste = ?", kod):
            return kod


def _pozice_boxu(spoj: Spojeni, box_id: int) -> list[struktura.MistoInfo]:
    return sorted(struktura.nacti_mista(spoj, struktura.pozice_v_rozsahu(spoj, "BOX", box_id)).values(),
                  key=lambda m: m.poradi_v_boxu)


class ZakladInventury(ZakladIntegrace):
    """Vlastní pracoviště s regálem: box DYN C4 a box STAT C4, tedy osm pozic V3."""

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(self.uzivatel_testu(), None, "ADMIN", frozenset())
        pracoviste = struktura.zaloz_pracoviste(self.spoj, self.kdo, novy_kod_pracoviste(self.spoj), None)
        self.regal = struktura.zaloz_regal(self.spoj, self.kdo, pracoviste, "R01", None)
        uroven = struktura.zaloz_uroven(self.spoj, self.kdo, self.regal, "U01", 1, 2400, 800)
        self.dyn_box = struktura.zaloz_box(self.spoj, self.kdo, uroven, 1, "DYN", "C4", *ROZMER_C4)
        self.dyn = _pozice_boxu(self.spoj, self.dyn_box)
        self.stat = _pozice_boxu(self.spoj, struktura.zaloz_box(self.spoj, self.kdo, uroven, 2, "STAT", "C4",
                                                                *ROZMER_C4))
        self.pozice = [*self.dyn, *self.stat]
        self.dil_a = self.novy_dil()
        self.dil_b = self.novy_dil()

    # --- struktura a díly (rozhraní C, D) ---------------------------------------------------------

    def novy_dil(self) -> int:
        """Díl V3 přes rozhraní ostrova D; číslo je jedinečné, protože potvrzená data v DB zůstávají."""
        return dily.zaloz_dil(self.spoj, self.kdo, NovyDil(identifikacni_cislo=f"ZKU {uuid.uuid4().hex[:8].upper()}",
                                                          potreba=PotrebaMista("V3")))

    def prirad_stat(self, dil_id: int, misto: struktura.MistoInfo) -> None:
        self.spoj.proved("INSERT INTO dbo.StatickeUmisteniDilu (DilID, VnitrniPoziceID, MinimalniPocetKs)"
                         " VALUES (?, ?, 0)", dil_id, misto.vnitrni_pozice_id)

    def blokuj(self, misto: struktura.MistoInfo) -> None:
        self.spoj.proved("UPDATE dbo.VnitrniPoziceBoxu SET Blokovany = 1 WHERE VnitrniPoziceID = ?",
                         misto.vnitrni_pozice_id)

    def vypni(self, misto: struktura.MistoInfo) -> None:
        """Pozice zmizí z pohledu v_Misto – přesně to inventura zažije po rekonfiguraci skladu."""
        self.spoj.proved("UPDATE dbo.VnitrniPoziceBoxu SET Aktivni = 0 WHERE VnitrniPoziceID = ?",
                         misto.vnitrni_pozice_id)

    # --- obsah a pohyby (tabulky E) ---------------------------------------------------------------

    def prijem(self, misto: struktura.MistoInfo, dil_id: int, pocet_ks: int = 10) -> None:
        soucasny = self.obsah(misto)
        if soucasny:
            self.spoj.proved("UPDATE dbo.ObsahPozice SET PocetKs = PocetKs + ? WHERE VnitrniPoziceID = ?",
                             pocet_ks, misto.vnitrni_pozice_id)
        else:
            self.spoj.proved("INSERT INTO dbo.ObsahPozice (VnitrniPoziceID, DilID, PocetKs) VALUES (?, ?, ?)",
                             misto.vnitrni_pozice_id, dil_id, pocet_ks)
        self.pohyb(misto, dil_id, "PRIJEM", pocet_ks, soucasny[1] if soucasny else 0)

    def vydej(self, misto: struktura.MistoInfo, pocet_ks: int) -> None:
        """Při nule se řádek ObsahPozice maže (stejně to dělá ostrov E) – na tom stav D-26 stojí."""
        dil_id, stav_pred = self.obsah(misto)
        if stav_pred == pocet_ks:
            self.spoj.proved("DELETE FROM dbo.ObsahPozice WHERE VnitrniPoziceID = ?", misto.vnitrni_pozice_id)
        else:
            self.spoj.proved("UPDATE dbo.ObsahPozice SET PocetKs = PocetKs - ? WHERE VnitrniPoziceID = ?",
                             pocet_ks, misto.vnitrni_pozice_id)
        self.pohyb(misto, dil_id, "VYDEJ", -pocet_ks, stav_pred)

    def pohyb(self, misto: struktura.MistoInfo, dil_id: int, kod_pohybu: str, mnozstvi: int,
              stav_pred: int) -> None:
        """Čas necháváme na SYSUTCDATETIME() (UTC, ADR-0012); StavPo = StavPred + Mnozstvi hlídá CHECK."""
        self.spoj.proved("INSERT INTO dbo.SkladovyPohyb (TypPohybuID, DilID, VnitrniPoziceID, Mnozstvi, StavPred,"
                         " StavPo, UzivatelID) SELECT TypPohybuID, ?, ?, ?, ?, ?, ? FROM dbo.TypPohybu"
                         " WHERE KodPohybu = ?", dil_id, misto.vnitrni_pozice_id, mnozstvi, stav_pred,
                         stav_pred + mnozstvi, self.kdo.uzivatel_id, kod_pohybu)

    # --- služby ostrova F (bez dekorátoru, tedy v transakci testu) ------------------------------------

    def inventura(self, typ_rozsahu: str, cil_id: int | None = None, *, slepa: bool = False, **pole):
        return sluzby.zaloz_inventuru.__wrapped__(self.spoj, vstup=NovaInventuraVstup(typ_rozsahu=typ_rozsahu,
                                                                                     cil_id=cil_id, slepa=slepa,
                                                                                     **pole),
                                                  kdo=self.kdo)

    def zapis(self, inventura_id: int, misto: struktura.MistoInfo, dil_id: int | None = None, pocet_ks: int = 0):
        return sluzby.zapis_polozku.__wrapped__(self.spoj, inventura_id=inventura_id,
                                                vnitrni_pozice_id=misto.vnitrni_pozice_id,
                                                vstup=ZapisPolozkyVstup(skutecny_dil_id=dil_id,
                                                                        skutecny_pocet_ks=pocet_ks),
                                                kdo=self.kdo)

    def zrus(self, inventura_id: int, duvod: str = "počítá se znovu"):
        return sluzby.zrus_inventuru.__wrapped__(self.spoj, inventura_id=inventura_id,
                                                 vstup=DuvodVstup(duvod=duvod), kdo=self.kdo)

    def dokonci(self, inventura_id: int, **pole):
        return sluzby.dokonci_inventuru.__wrapped__(self.spoj, inventura_id=inventura_id,
                                                    vstup=DokonceniVstup(request_id=uuid.uuid4(), **pole),
                                                    kdo=self.kdo)

    def inventura_na_pozici(self, misto: struktura.MistoInfo, dil_id: int | None = None, pocet_ks: int = 10, *,
                            nalezeny: tuple[int | None, int] | None = None):
        """Naplní pozici, založí inventuru přes rozsah POZICE a zapíše nález (výchozí = shoda).

        Vrací (inventuraId, zapsaná položka). Bez dílu pozice prázdná zůstává a zápis hlásí prázdnou.
        """
        if dil_id is None:
            pocet_ks = 0        # bez dílu je pozice prázdná, tudíž i očekávaný počet je 0
        else:
            self.prijem(misto, dil_id, pocet_ks)
        inventura_id = self.inventura("POZICE", misto.vnitrni_pozice_id).inventura_id
        return inventura_id, self.zapis(inventura_id, misto, *(nalezeny or (dil_id, pocet_ks)))

    # --- zjištění stavu -------------------------------------------------------------------------

    def detail(self, inventura_id: int):
        return sluzby.detail_inventury.__wrapped__(self.spoj, inventura_id=inventura_id)

    def polozka(self, inventura_id: int, misto: struktura.MistoInfo):
        """Položka z odpovědi služby, tedy včetně stavu D-26."""
        return next(p for p in self.detail(inventura_id).polozky
                    if p.vnitrni_pozice_id == misto.vnitrni_pozice_id)

    def radek_polozky(self, inventura_id: int, misto: struktura.MistoInfo) -> dict:
        """Řádek vlastní tabulky, tak jak ho vidí repozitář, ne upravený pro klienta."""
        return self.spoj.jeden("SELECT OcekavanyDilID, OcekavanyPocetKs, SkutecnyDilID, SkutecnyPocetKs, RozdilKs,"
                               " Vyhodnoceni, DatumKontroly, UzivatelID, PosledniPohybID FROM dbo.InventuraPolozka"
                               " WHERE InventuraID = ? AND VnitrniPoziceID = ?", inventura_id,
                               misto.vnitrni_pozice_id)

    def obsah(self, misto: struktura.MistoInfo) -> tuple[int, int] | None:
        """(dilId, počet ks) z rozhraní ostrova E; prázdná pozice ve výsledku chybí."""
        obsah = sklad.obsah_mist(self.spoj, [misto.vnitrni_pozice_id]).get(misto.vnitrni_pozice_id)
        return (obsah.dil_id, obsah.pocet_ks) if obsah else None

    def pocet_pohybu(self) -> int:
        """Pohyby na všech pozicích testu – inventura jich nesmí přidat ani jeden."""
        znacky = ", ".join("?" for _ in self.pozice)
        return self.spoj.hodnota(f"SELECT COUNT(*) FROM dbo.SkladovyPohyb WHERE VnitrniPoziceID IN ({znacky})",
                                 *[m.vnitrni_pozice_id for m in self.pozice])

    def over_chybu(self, operace, kod: str, pole: set[str] | None = None) -> AppError:
        """AppError z služby; vrací ji, aby test ověřil i `data`."""
        with self.assertRaises(AppError) as zachyceno:
            operace()
        self.assertEqual(zachyceno.exception.kod, kod)
        if pole is not None:
            self.assertEqual({chyba["pole"] for chyba in zachyceno.exception.data["chyby"]}, pole)
        return zachyceno.exception


class TestZalozeni(ZakladInventury):
    def test_položky_pro_vsechny_pozice_rozsahu_i_prazdne(self):
        self.prijem(self.dyn[0], self.dil_a, 10)
        self.prirad_stat(self.dil_b, self.stat[0])
        self.prijem(self.stat[0], self.dil_b, 5)

        inventura = self.inventura("REGAL", self.regal)

        self.assertEqual((inventura.stav_inventury, inventura.typ_rozsahu, inventura.cil_id, inventura.slepa),
                         ("ROZPRACOVANA", "REGAL", self.regal, False))
        self.assertEqual([(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.stav_polozky) for p in inventura.polozky],
                         [(self.dil_a, 10, "CEKA")] + [(None, 0, "CEKA")] * 3
                         + [(self.dil_b, 5, "CEKA")] + [(None, 0, "CEKA")] * 3)
        radek = self.spoj.jeden("SELECT PracovisteID, RegalID, UrovenID, BoxID, VnitrniPoziceID, DatumDokonceni,"
                                " ZalozilUzivatelID FROM dbo.Inventura WHERE InventuraID = ?",
                                inventura.inventura_id)
        self.assertEqual(radek["RegalID"], self.regal)
        self.assertEqual([radek[k] for k in ("PracovisteID", "UrovenID", "BoxID", "VnitrniPoziceID")], [None] * 4,
                         "vyplněný má být jediný sloupec rozsahu (CK_Inventura_Rozsah)")
        self.assertIsNone(radek["DatumDokonceni"])
        self.assertEqual(radek["ZalozilUzivatelID"], self.kdo.uzivatel_id)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.InventuraPolozka WHERE InventuraID = ?"
                                           " AND PosledniPohybID IS NOT NULL", inventura.inventura_id), 0)

    def test_pozice_uz_v_rozpracovane_inventure(self):
        prvni = self.inventura("BOX", self.dyn_box)

        druhe = self.over_chybu(lambda: self.inventura("REGAL", self.regal), "ALREADY_EXISTS")

        self.assertIn(self.dyn[0].kod, druhe.zprava)
        self.assertIn(str(prvni.inventura_id), druhe.zprava)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Inventura WHERE ZalozilUzivatelID = ?",
                                           self.kdo.uzivatel_id), 1)

    def test_po_zruseni_se_pozice_da_inventarizovat_znovu(self):
        prvni = self.inventura("BOX", self.dyn_box)
        self.assertEqual(self.zrus(prvni.inventura_id).stav_inventury, "ZRUSENA")

        self.assertEqual(self.inventura("BOX", self.dyn_box).stav_inventury, "ROZPRACOVANA")

    def test_seznam_inventur_najde_svoji_a_vynecha_zrusenou(self):
        inventura = self.inventura("BOX", self.dyn_box)
        radek = next(r for r in sluzby.seznam_inventur.__wrapped__(self.spoj, filtr=InventuryFiltr()).polozky
                     if r.inventura_id == inventura.inventura_id)
        self.assertEqual((radek.pocet_polozek, radek.pocet_zapsanych, radek.pocet_k_prepoctu), (4, 0, 0))

        self.zrus(inventura.inventura_id)

        self.assertNotIn(inventura.inventura_id,
                         [r.inventura_id for r in sluzby.seznam_inventur.__wrapped__(
                             self.spoj, filtr=InventuryFiltr()).polozky])


class TestSlepaInventura(ZakladInventury):
    """T24: slepá inventura nesmí ukázat očekávaný stav, dokud obsluha nic nezapíše."""

    def test_ocekavany_stav_se_neukaze_pred_zapisem(self):
        self.prijem(self.dyn[0], self.dil_a, 10)
        inventura = self.inventura("BOX", self.dyn_box, slepa=True)

        self.assertTrue(inventura.slepa)
        self.assertEqual([(p.ocekavany_dil_id, p.ocekavany_pocet_ks, p.stav_polozky) for p in inventura.polozky],
                         [(None, None, "CEKA")] * 4)

        zapsana = self.zapis(inventura.inventura_id, self.dyn[0], self.dil_a, 10)

        self.assertEqual((zapsana.ocekavany_dil_id, zapsana.ocekavany_pocet_ks, zapsana.vyhodnoceni),
                         (self.dil_a, 10, "SHODA"))
        nezapsana = self.polozka(inventura.inventura_id, self.dyn[1])
        self.assertEqual((nezapsana.ocekavany_dil_id, nezapsana.ocekavany_pocet_ks), (None, None))


class TestZapis(ZakladInventury):
    def test_ulozi_nalez_obnovi_ocekavany_stav_a_vodoznak(self):
        misto = self.dyn[0]
        self.prijem(misto, self.dil_a, 10)
        inventura_id = self.inventura("POZICE", misto.vnitrni_pozice_id).inventura_id
        self.vydej(misto, 3)          # mezi založením a počítáním se na pozici hýbalo

        polozka = self.zapis(inventura_id, misto, self.dil_a, 7)

        self.assertEqual((polozka.vyhodnoceni, polozka.rozdil_ks, polozka.stav_polozky), ("SHODA", 0, "ZAPSANO"))
        self.assertEqual((polozka.ocekavany_dil_id, polozka.ocekavany_pocet_ks), (self.dil_a, 7))
        radek = self.radek_polozky(inventura_id, misto)
        self.assertEqual((radek["OcekavanyDilID"], radek["OcekavanyPocetKs"], radek["SkutecnyDilID"],
                          radek["SkutecnyPocetKs"], radek["RozdilKs"], radek["Vyhodnoceni"]),
                         (self.dil_a, 7, self.dil_a, 7, 0, "SHODA"))
        self.assertEqual(radek["PosledniPohybID"],
                         sklad.posledni_pohyby(self.spoj, [misto.vnitrni_pozice_id])[misto.vnitrni_pozice_id])
        self.assertIsNotNone(radek["DatumKontroly"])
        self.assertEqual(radek["UzivatelID"], self.kdo.uzivatel_id)

    def test_prazdnou_pozici_zapise_beze_dilu(self):
        _, polozka = self.inventura_na_pozici(self.dyn[1])
        self.assertEqual((polozka.skutecny_dil_id, polozka.skutecny_pocet_ks, polozka.vyhodnoceni),
                         (None, 0, "SHODA"))

    def test_opakovany_zapis_prepa_predchozi_nalez(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10)

        druhy = self.zapis(inventura_id, misto, self.dil_a, 8)

        self.assertEqual((druhy.vyhodnoceni, druhy.rozdil_ks, druhy.skutecny_pocet_ks), ("ROZDIL", -2, 8))
        self.assertEqual(self.radek_polozky(inventura_id, misto)["SkutecnyPocetKs"], 8)

    def test_zapis_se_zastavi_u_spatne_pozice_dilu_a_stavu(self):
        misto = self.dyn[0]
        inventura_id = self.inventura("POZICE", misto.vnitrni_pozice_id).inventura_id
        self.over_chybu(lambda: self.zapis(inventura_id, self.dyn[1], self.dil_a, 1), "NOT_FOUND")
        self.over_chybu(lambda: self.zapis(inventura_id, misto, 999999, 1), "NOT_FOUND")
        self.zrus(inventura_id)
        self.over_chybu(lambda: self.zapis(inventura_id, misto, self.dil_a, 1), "CONCURRENT_CHANGE")


class TestStavPolozkyPoZapisu(ZakladInventury):
    """D-26: pohyb po zápisu nikdy nepřepíše zjištěný díl ani počet; spočítá se jen jednoznačná
    změna téhož dílu, jinak se pozice vrací k fyzické kontrole."""

    def test_bez_pohybu_zustava_zapsana(self):
        misto = self.dyn[0]
        inventura_id, polozka = self.inventura_na_pozici(misto, self.dil_a, 10)
        vodoznak = self.radek_polozky(inventura_id, misto)["PosledniPohybID"]

        druha = self.polozka(inventura_id, misto)

        self.assertEqual(druha.stav_polozky, "ZAPSANO")
        self.assertEqual((druha.skutecny_dil_id, druha.skutecny_pocet_ks, druha.rozdil_ks),
                         (polozka.skutecny_dil_id, polozka.skutecny_pocet_ks, 0))
        self.assertEqual(self.radek_polozky(inventura_id, misto)["PosledniPohybID"], vodoznak)

    def test_vydej_tehož_dilu_se_dopocita(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10, nalezeny=(self.dil_a, 8))

        self.vydej(misto, 3)

        polozka = self.polozka(inventura_id, misto)
        self.assertEqual(polozka.stav_polozky, "ZAPSANO")
        self.assertEqual((polozka.skutecny_dil_id, polozka.skutecny_pocet_ks, polozka.rozdil_ks),
                         (self.dil_a, 8, -2))                            # pohyb nález nepřepsal
        self.assertEqual(self.dokonci(inventura_id).pocet_rozdilu, 1)    # a dokončit jde bez přepočítání

    def test_pohyb_jineho_dilu_vrati_pozici_k_prepoctu(self):
        misto = self.dyn[1]                                   # pozice, která měla být prázdná
        inventura_id, _ = self.inventura_na_pozici(misto)

        self.prijem(misto, self.dil_b, 4)

        self.assertEqual(self.polozka(inventura_id, misto).stav_polozky, "PREPOCITAT")

    def test_vyprazdeni_a_nove_obsazeni_vrati_pozici_k_prepoctu(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10)

        self.vydej(misto, 10)                                 # vyprázdněno
        self.prijem(misto, self.dil_a, 6)                     # … a znovu obsazeno týmiž dílem

        self.assertEqual(self.polozka(inventura_id, misto).stav_polozky, "PREPOCITAT")

    def test_zaporny_dopocet_vrati_pozici_k_prepoctu(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10, nalezeny=(self.dil_a, 8))

        self.vydej(misto, 9)                                  # zbývá 1 ks, doúčtovat -2 by šlo pod nulu

        self.assertEqual(self.polozka(inventura_id, misto).stav_polozky, "PREPOCITAT")

    def test_pohyb_u_položky_s_jinym_dilem_vzdy_vrati_pozici_k_prepoctu(self):
        misto = self.dyn[0]
        inventura_id, polozka = self.inventura_na_pozici(misto, self.dil_a, 5, nalezeny=(self.dil_b, 3))
        self.assertEqual(polozka.vyhodnoceni, "JINY_DIL")

        self.vydej(misto, 2)                                  # pohyb očekávaného dílu, ne toho nalezeného

        druha = self.polozka(inventura_id, misto)
        self.assertEqual((druha.stav_polozky, druha.skutecny_dil_id, druha.skutecny_pocet_ks),
                         ("PREPOCITAT", self.dil_b, 3))

    def test_neaktivni_pozice_po_rekonfiguraci(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10)

        self.vypni(misto)

        polozka = self.polozka(inventura_id, misto)
        self.assertEqual(polozka.stav_polozky, "PREPOCITAT")
        self.assertEqual(polozka.kod, str(misto.vnitrni_pozice_id))    # štítek už neznáme, položka je bez jména


class TestZruseni(ZakladInventury):
    def test_zruseni_prepise_stav_a_nezauctuje_zadny_pohyb(self):
        misto = self.dyn[0]
        self.prijem(misto, self.dil_a, 10)
        inventura_id = self.inventura("BOX", self.dyn_box).inventura_id
        self.zapis(inventura_id, misto, self.dil_a, 8)        # rozdíl -2, který se nikdy nezaúčtuje
        pred_zrusenim = self.pocet_pohybu()

        radek = self.zrus(inventura_id, duvod="počítala špatná úroveň")

        self.assertEqual((radek.stav_inventury, radek.poznamka), ("ZRUSENA", "počítala špatná úroveň"))
        self.assertEqual(self.spoj.hodnota("SELECT Poznamka FROM dbo.Inventura WHERE InventuraID = ?",
                                           inventura_id), "počítala špatná úroveň")
        self.assertEqual(self.pocet_pohybu(), pred_zrusenim)
        self.assertEqual(self.obsah(misto), (self.dil_a, 10))          # obsah zůstal nedotčený

    def test_zrusena_inventura_se_dat_neda(self):
        inventura_id = self.inventura("BOX", self.dyn_box).inventura_id
        self.zrus(inventura_id)
        self.over_chybu(lambda: self.zrus(inventura_id), "CONCURRENT_CHANGE")
        self.over_chybu(lambda: self.zapis(inventura_id, self.dyn[0], self.dil_a, 1), "CONCURRENT_CHANGE")
        self.over_chybu(lambda: self.dokonci(inventura_id), "CONCURRENT_CHANGE")


class TestDokonceni(ZakladInventury):
    def test_nezapsane_pozice_brani_dokonceni(self):
        self.prijem(self.dyn[0], self.dil_a, 10)
        inventura_id = self.inventura("BOX", self.dyn_box).inventura_id
        self.zapis(inventura_id, self.dyn[0], self.dil_a, 10)

        chyba = self.over_chybu(lambda: self.dokonci(inventura_id), "VALIDATION_ERROR")
        self.assertIn(self.dyn[1].kod, chyba.zprava)

    def test_pozice_k_prepoctu_brani_dokonceni(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10)
        self.vydej(misto, 10)
        self.prijem(misto, self.dil_a, 6)

        chyba = self.over_chybu(lambda: self.dokonci(inventura_id), "INVENTORY_RECOUNT")
        self.assertEqual(chyba.data["pozice"], [misto.kod])

    def test_jiny_dil_potrebuje_cil_i_v_dyn(self):
        """S-22: cíl je potřeba i na dynamické pozici – bez něj inventuru dokončit nelze."""
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 5, nalezeny=(self.dil_b, 3))

        self.over_chybu(lambda: self.dokonci(inventura_id), "VALIDATION_ERROR", {"cileJinyDil"})

    def test_cil_se_zadá_jen_pro_položku_s_jinym_dilem(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10)

        self.over_chybu(lambda: self.dokonci(inventura_id, cile_jiny_dil={misto.vnitrni_pozice_id: self.dyn[1].kod}),
                        "VALIDATION_ERROR", {"cileJinyDil"})

    def test_nevhodny_cil_jineho_dilu(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 5, nalezeny=(self.dil_b, 3))
        self.prijem(self.dyn[1], self.dil_a, 1)          # obsazená pozice
        self.blokuj(self.dyn[2])                         # volná, ale blokovaná
        self.prirad_stat(self.dil_a, self.stat[0])       # STAT místo jiného dílu

        for cil in (*self.dyn[1:3], self.stat[0]):
            self.over_chybu(lambda c=cil: self.dokonci(inventura_id, cile_jiny_dil={
                misto.vnitrni_pozice_id: c.kod}), "VALIDATION_ERROR", {"cileJinyDil"})

    def test_dokonceni_s_cilem_pripravi_plan_bez_zauctovani(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 5, nalezeny=(self.dil_b, 3))
        self.prirad_stat(self.dil_b, self.stat[0])

        vysledek = self.dokonci(inventura_id, cile_jiny_dil={misto.vnitrni_pozice_id: self.stat[0].kod})

        self.assertEqual((vysledek.pocet_shod, vysledek.pocet_rozdilu, vysledek.pocet_jinych_dilu), (0, 0, 1))
        self.assertEqual(len(vysledek.pohyby), 2)         # odúčtovat očekávaný díl + zaúčtovat nález na cíl
        self.assertEqual(self.detail(inventura_id).stav_inventury, "ROZPRACOVANA")
        self.assertEqual(self.obsah(misto), (self.dil_a, 5))
        self.assertIsNone(self.obsah(self.stat[0]))
        self.assertEqual(self.pocet_pohybu(), 1)          # krok 1 nezaúčtoval ani jeden pohyb

    def test_cilem_muze_byt_i_soucasna_pozice_po_oductovani(self):
        """D-27: současná pozice je cíl, jen když po odúčtování očekávaného dílu splňuje stejná pravidla."""
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 5, nalezeny=(self.dil_b, 3))

        vysledek = self.dokonci(inventura_id, cile_jiny_dil={misto.vnitrni_pozice_id: misto.kod})

        self.assertEqual((vysledek.pocet_jinych_dilu, len(vysledek.pohyby)), (1, 2))
        self.assertEqual(self.obsah(misto), (self.dil_a, 5))   # i tak se účtuje až v kroku 2

    def test_dokonceni_se_stavem_a_rozdilem(self):
        misto = self.dyn[0]
        inventura_id, _ = self.inventura_na_pozici(misto, self.dil_a, 10, nalezeny=(self.dil_a, 8))
        self.vydej(misto, 3)                               # aktuálně 5 ks → nový stav 5 − 2

        vysledek = self.dokonci(inventura_id)

        self.assertEqual((vysledek.pocet_shod, vysledek.pocet_rozdilu, len(vysledek.pohyby)), (0, 1, 1))
