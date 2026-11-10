"""Integrační testy ostrova E nad SQL Serverem: skladové příkazy, upozornění a čtení rozhraní.

Služby se volí přes `__wrapped__`, tedy bez dekorátoru: tělo běží ve spojení a transakci testu a na
konci se vše vrátí zpět (@transakce si otevírá vlastní spojení a potvrzuje). Jedině
`TestOpakovanyRequest` a `TestSoubeh` pouštějí službu i s dekorátorem – oba potřebují potvrzená data
(T14, souběh dvou spojení T10 a T30).

Strukturu zakládáme rozhraním ostrova C a díly rozhraním ostrova D (P2); STAT místa zakládá služba
(`zaloz_stat`), `prirad_stat` je rychlé vložení přímo do tabulky pro testy, ve kterých nezáleží na
jeho auditu. Každý test má pracoviště s
jedinečným kódem: potvrzená data i data ostatních ostrovů v databázi zůstávají, proto netvrdíme nic
o počtech řádků obecně a kontrolu integrity vyhodnocujeme jen pro nálezy, které se týkají našich dat.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from app.ostrovy.dily import rozhrani as dily
from app.ostrovy.dily.rozhrani import NovyDil
from app.ostrovy.sklad import rozhrani as sklad
from app.ostrovy.sklad import sluzby
from app.ostrovy.sklad.kontrakty import (
    KandidatiFiltr,
    NoveStatMistoVstup,
    PresunVstup,
    PrijemDynVstup,
    PrijemStatVstup,
    SkladovyVysledek,
    UpozorneniFiltr,
    UzavreniUpozorneniVstup,
    VydejVstup,
    ZmenaStatMistaVstup,
)
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.db import Spojeni, spojeni_pro_skript
from app.platforma.kontrakty import DuvodVstup, Vstup
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


def nova_struktura(spoj: Spojeni, kdo: Kontext) -> dict:
    """Pracoviště + regál R01 a R02, každý s úrovní U01; na první úrovni box DYN a STAT členění C4."""
    pracoviste = struktura.zaloz_pracoviste(spoj, kdo, novy_kod_pracoviste(spoj), None)
    regal = struktura.zaloz_regal(spoj, kdo, pracoviste, "R01", None)
    druhy_regal = struktura.zaloz_regal(spoj, kdo, pracoviste, "R02", None)
    uroven = struktura.zaloz_uroven(spoj, kdo, regal, "U01", 1, 2400, 800)
    druha_uroven = struktura.zaloz_uroven(spoj, kdo, druhy_regal, "U01", 1, 2400, 800)
    return {"pracoviste": pracoviste, "regal": regal, "druhy_regal": druhy_regal, "urovne": [uroven, druha_uroven],
            "dyn": _pozice_boxu(spoj, struktura.zaloz_box(spoj, kdo, uroven, 1, "DYN", "C4", *ROZMER_C4)),
            "stat": _pozice_boxu(spoj, struktura.zaloz_box(spoj, kdo, uroven, 2, "STAT", "C4", *ROZMER_C4)),
            "dalsi_dyn": _pozice_boxu(spoj, struktura.zaloz_box(spoj, kdo, druha_uroven, 1, "DYN", "C4",
                                                                *ROZMER_C4))}


def _pozice_boxu(spoj: Spojeni, box_id: int) -> list[struktura.MistoInfo]:
    """Pozice boxu v pořadí šablony (poradiVBoxu), tak je vidí i/parser kódu a tisk štítků."""
    mista = struktura.nacti_mista(spoj, struktura.pozice_v_rozsahu(spoj, "BOX", box_id))
    return sorted(mista.values(), key=lambda m: m.poradi_v_boxu)


def novy_dil(spoj: Spojeni, kdo: Kontext, velikost: str | None = "V3") -> tuple[int, str]:
    """Díl přes rozhraní ostrova D (P2); číslo je jedinečné, protože potvrzená data v DB zůstávají."""
    cislo = f"ZKU {uuid.uuid4().hex[:8].upper()}"
    return dily.zaloz_dil(spoj, kdo, NovyDil(identifikacni_cislo=cislo,
                                            potreba=PotrebaMista(velikost) if velikost else None)), cislo


class ZakladSkladu(ZakladIntegrace):
    """Sklad pro jeden test: vlastní pracoviště, dva regály, boxy C4 a technický uživatel do hlavičky."""

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(self.uzivatel_testu(), None, "ADMIN", frozenset())
        self.svet = nova_struktura(self.spoj, self.kdo)
        self.dyn, self.stat, self.dalsi_dyn = self.svet["dyn"], self.svet["stat"], self.svet["dalsi_dyn"]
        self.pozice = [*self.dyn, *self.stat, *self.dalsi_dyn]
        self.cisla_dilu: list[str] = []

    # --- data ---------------------------------------------------------------------------------

    def dil(self, velikost: str | None = "V3") -> tuple[int, str]:
        """(dilId, číslo dílu) – číslo testy potřebují i tam, kde ověřují data přes cizí pohledy."""
        dil_id, cislo = novy_dil(self.spoj, self.kdo, velikost)
        self.cisla_dilu.append(cislo)
        return dil_id, cislo

    def prirad_stat(self, dil_id: int, misto: struktura.MistoInfo, *, minimalni_ks: int = 0,
                    maximalni_ks: int | None = None) -> int:
        """Přiřazení vložené přímo do tabulky – testy STAT míst používají službu `zaloz_stat`."""
        return self.spoj.vloz("INSERT INTO dbo.StatickeUmisteniDilu (DilID, VnitrniPoziceID, MinimalniPocetKs,"
                              " MaximalniPocetKs) VALUES (?, ?, ?, ?)", dil_id, misto.vnitrni_pozice_id,
                              minimalni_ks, maximalni_ks)

    def zaloz_stat(self, dil_id: int, misto: struktura.MistoInfo, *, minimalni_ks: int = 0,
                   maximalni_ks: int | None = None, prepsat_velikost: bool = False,
                   duvod: str | None = None, kdo: Kontext | None = None):
        """STAT místo založené službou `sluzby.zaloz_stat_misto` (v transakci testu, bez dekorátoru)."""
        return sluzby.zaloz_stat_misto.__wrapped__(self.spoj, NoveStatMistoVstup(
            dil_id=dil_id, vnitrni_pozice_id=misto.vnitrni_pozice_id, minimalni_ks=minimalni_ks,
            maximalni_ks=maximalni_ks, prepsat_velikost=prepsat_velikost, duvod=duvod), kdo or self.kdo)

    def zmen_stat(self, stat_id: int, duvod: str, **mez):
        return sluzby.zmen_stat_misto.__wrapped__(self.spoj, stat_id, ZmenaStatMistaVstup(**mez, duvod=duvod),
                                                  self.kdo)

    def ukonci_stat(self, stat_id: int, duvod: str):
        return sluzby.ukonci_stat_misto.__wrapped__(self.spoj, stat_id, DuvodVstup(duvod=duvod), self.kdo)

    def uzavri_upozorneni(self, upozorneni_id: int, poznamka: str, kdo: Kontext | None = None):
        return sluzby.uzavri_upozorneni.__wrapped__(self.spoj, upozorneni_id,
                                                    UzavreniUpozorneniVstup(poznamka=poznamka), kdo or self.kdo)

    def blokuj(self, misto: struktura.MistoInfo, *, box: bool = False) -> None:
        tabulka, sloupec = ("dbo.Box", "BoxID") if box else ("dbo.VnitrniPoziceBoxu", "VnitrniPoziceID")
        self.spoj.proved(f"UPDATE {tabulka} SET Blokovany = 1 WHERE {sloupec} = ?",
                         misto.box_id if box else misto.vnitrni_pozice_id)

    # --- příkazy (bez dekorátoru, tedy v transakci testu) ---------------------------------------

    def _hlavicka(self, operace: str) -> None:
        """Hlavičku SkladovaTransakce jinak zakládá @transakce; bez ní by pohyb padl na cizí klíč."""
        self.spoj.transakce_id = uuid.uuid4()
        self.spoj.proved("INSERT INTO dbo.SkladovaTransakce (TransakceID, KlientRequestID, TypOperace,"
                         " UzivatelID) VALUES (?, ?, ?, ?)", self.spoj.transakce_id, uuid.uuid4(), operace,
                         self.kdo.uzivatel_id)

    def prikaz(self, funkce, vstup):
        self._hlavicka(funkce.__houfek_transakce__)
        return funkce.__wrapped__(self.spoj, vstup=vstup, kdo=self.kdo)

    def korekce(self, misto: struktura.MistoInfo, dil_id: int, novy_stav_ks: int, typ_pohybu: str = "KOREKCE",
                poznamka: str | None = None):
        """Korekci volá jiný ostrov ve své transakci a se zamčenou pozicí – tady bez @transakce."""
        self._hlavicka(typ_pohybu)
        return sklad.zauctuj_korekci(self.spoj, self.kdo, misto.vnitrni_pozice_id, dil_id, novy_stav_ks, typ_pohybu,
                                     poznamka)

    def prijem(self, misto: struktura.MistoInfo, dil_id: int, pocet_ks: int = 10, **pole):
        return self.prikaz(sluzby.prijem_dyn, PrijemDynVstup(request_id=uuid.uuid4(), dil_id=dil_id,
                                                             cil_kod=misto.kod, pocet_ks=pocet_ks, **pole))

    def uskladni(self, misto: struktura.MistoInfo, dil_id: int, pocet_ks: int = 10, **pole):
        return self.prikaz(sluzby.prijem_stat, PrijemStatVstup(request_id=uuid.uuid4(), dil_id=dil_id,
                                                               cil_kod=misto.kod, pocet_ks=pocet_ks, **pole))

    def vydej(self, misto: struktura.MistoInfo, pocet_ks: int, **pole):
        return self.prikaz(sluzby.vydej, VydejVstup(request_id=uuid.uuid4(), zdroj_kod=misto.kod,
                                                    pocet_ks=pocet_ks, **pole))

    def presun(self, zdroj: struktura.MistoInfo, cil: struktura.MistoInfo, **pole):
        return self.prikaz(sluzby.presun, PresunVstup(request_id=uuid.uuid4(), zdroj_kod=zdroj.kod,
                                                      cil_kod=cil.kod, **pole))

    # --- zjištění stavu ------------------------------------------------------------------------

    @staticmethod
    def uid(hodnota) -> uuid.UUID:
        """ODBC vrací UNIQUEIDENTIFIER jako text – stejnou úpravu dělá i platforma (transakce.py)."""
        return uuid.UUID(str(hodnota))

    def obsah(self, misto: struktura.MistoInfo) -> tuple[int, int] | None:
        """(dilId, počet ks) čtené rozhraním ostrova E; prázdná pozice je None."""
        obsah = sklad.obsah_mist(self.spoj, [misto.vnitrni_pozice_id]).get(misto.vnitrni_pozice_id)
        return (obsah.dil_id, obsah.pocet_ks) if obsah else None

    def pohyby(self, *mista: struktura.MistoInfo) -> list[dict]:
        """Hýbání na pozicích – v historii zůstávají i po smazání řádku ObsahPozice."""
        znacky = ", ".join("?" for _ in mista)
        return self.spoj.dotaz(f"SELECT p.PohybID, t.KodPohybu, p.DilID, p.VnitrniPoziceID, p.Mnozstvi,"
                               f" p.StavPred, p.StavPo, p.TransakceID, p.UzivatelID, p.Poznamka, p.DatumCas,"
                               f" p.ZpusobPotvrzeni"
                               f" FROM dbo.SkladovyPohyb AS p"
                               f" JOIN dbo.TypPohybu AS t ON t.TypPohybuID = p.TypPohybuID"
                               f" WHERE p.VnitrniPoziceID IN ({znacky}) ORDER BY p.PohybID",
                               *[m.vnitrni_pozice_id for m in mista])

    def soucet_pohybu(self, misto: struktura.MistoInfo) -> int:
        """Součet podepsaných množství na pozici – musí sedět na její aktuální obsah (kap. 10, T32)."""
        return self.spoj.hodnota("SELECT SUM(Mnozstvi) FROM dbo.SkladovyPohyb WHERE VnitrniPoziceID = ?",
                                 misto.vnitrni_pozice_id) or 0

    def upozorneni(self, stat_umisteni_id: int) -> list[dict]:
        return self.spoj.dotaz("SELECT UpozorneniID, TypStavu, StavUpozorneni, AktualniPocetKs, MinimalniPocetKs,"
                               " DatumUzavreni, UzavrelUzivatelID, Poznamka FROM dbo.UpozorneniZasoby"
                               " WHERE StatickeUmisteniID = ? ORDER BY UpozorneniID", stat_umisteni_id)

    def audit(self, typ_objektu: str, objekt_id: int) -> list[dict]:
        """Změny jednoho objektu v AuditZmen (tabulku vlastní Platforma, test ji čte přímo)."""
        return self.spoj.dotaz("SELECT Pole, StaraHodnota, NovaHodnota, Poznamka, UzivatelID FROM dbo.AuditZmen"
                               " WHERE TypObjektu = ? AND ObjektID = ? ORDER BY AuditID", typ_objektu, objekt_id)

    def over_integrity(self) -> None:
        """v_KontrolaIntegrity nesmí hlásit nic, co se týká našich boxů, úrovní, pozic a dílů.

        Každý nález se ve slupci Popis jmenuje vlastním objektem (kód boxu, číslo dílu,
        `VnitrniPoziceID …`, `(UrovenID …)`), proto z celého pohledu vyhodnocujeme jen ty,
        které se týkají dat, která test založil.
        """
        kody_boxu = [r["KodBoxu"] for r in self.spoj.dotaz(
            "SELECT b.KodBoxu FROM dbo.Box AS b JOIN dbo.Pozice AS po ON po.PoziceID = b.PoziceID"
            " JOIN dbo.Uroven AS u ON u.UrovenID = po.UrovenID WHERE u.RegalID IN (?, ?)",
            self.svet["regal"], self.svet["druhy_regal"])]
        znacky = kody_boxu + self.cisla_dilu + [f"VnitrniPoziceID {m.vnitrni_pozice_id}," for m in self.pozice]
        znacky += [f"(UrovenID {u})" for u in self.svet["urovne"]]
        nalezy = self.spoj.dotaz("SELECT Kontrola, Popis FROM dbo.v_KontrolaIntegrity")
        self.assertEqual([n for n in nalezy if any(z in n["Popis"] for z in znacky)], [])

    def chyba(self, funkce, *args, kod: str, **pole) -> AppError:
        with self.assertRaises(AppError) as zachyceno:
            funkce(*args, **pole)
        self.assertEqual(zachyceno.exception.kod, kod, zachyceno.exception)
        return zachyceno.exception


class TestPrijemDyn(ZakladSkladu):
    """T03, T17, T19, T27: příjem dávky do prázdné DYN pozice."""

    def test_prijem_zapise_obsah_i_pohyb(self):
        dil_id, cislo = self.dil()
        vysledek = self.prijem(self.dyn[0], dil_id, 20, poznamka="dávka z laseru")
        self.assertEqual(vysledek.identifikacni_cislo, cislo)
        self.assertEqual([(p.typ_pohybu, p.mnozstvi, p.stav_pred_ks, p.stav_po_ks, p.kod) for p in vysledek.pohyby],
                         [("PRIJEM", 20, 0, 20, self.dyn[0].kod)])
        self.assertEqual((vysledek.cil.stav_ks, vysledek.cil.dil_id, vysledek.cil.stav_boxu),
                         (20, dil_id, "OBSAZENY"))
        self.assertEqual((vysledek.stav_zasoby, vysledek.upozorneni), (None, None))     # DYN místo zásoby nemá
        radek = self.pohyby(self.dyn[0])[0]
        self.assertEqual((radek["PohybID"], radek["KodPohybu"], radek["DilID"]),
                         (vysledek.pohyby[0].pohyb_id, "PRIJEM", dil_id))               # odpověď nese skutečné ID
        self.assertEqual((radek["StavPred"], radek["StavPo"], radek["Mnozstvi"]), (0, 20, 20))
        self.assertEqual((self.uid(radek["TransakceID"]), radek["UzivatelID"]),
                         (self.spoj.transakce_id, self.kdo.uzivatel_id))
        self.assertEqual(radek["Poznamka"], "dávka z laseru")   # způsob potvrzení se nikam neukládá (brána G2)
        self.assertEqual(self.obsah(self.dyn[0]), (dil_id, 20))
        self.assertEqual(sklad.posledni_pohyby(self.spoj, [self.dyn[0].vnitrni_pozice_id,
                                                           self.dyn[1].vnitrni_pozice_id]),
                         {self.dyn[0].vnitrni_pozice_id: vysledek.pohyby[0].pohyb_id,
                          self.dyn[1].vnitrni_pozice_id: None})

    def test_cil_neni_volna_dyn_pozice(self):
        dil_id, _ = self.dil()
        self.prijem(self.dyn[0], dil_id, 5)
        self.chyba(self.prijem, self.dyn[0], dil_id, 5, kod="POSITION_OCCUPIED")
        self.blokuj(self.dyn[1])                                          # T19: blokovaná pozice (Q-09)
        self.chyba(self.prijem, self.dyn[1], dil_id, 5, kod="POSITION_BLOCKED")
        self.blokuj(self.dyn[2], box=True)                                 # blokovaný celý box
        self.chyba(self.prijem, self.dyn[2], dil_id, 5, kod="POSITION_BLOCKED")
        self.chyba(self.prijem, self.stat[0], dil_id, 5, kod="VALIDATION_ERROR")   # STAT cíl = uskladnění
        self.assertEqual([self.obsah(m) for m in self.dyn[1:3]], [None, None])

    def test_velikost_dilu_a_dil_bez_velikosti(self):
        """T17: díl se do pozice musí vejít (Q-26: bez velikosti do DYN vůbec nemíří)."""
        dil_id, _ = self.dil()
        mala, _ = self.dil("V1")
        bez_velikosti, _ = self.dil(None)
        self.chyba(self.prijem, self.dyn[0], mala, 5, kod="SIZE_MISMATCH")
        self.chyba(self.prijem, self.dyn[0], bez_velikosti, 5, kod="PART_HAS_NO_SIZE")
        self.assertEqual(self.obsah(self.dyn[0]), None)
        self.assertEqual(self.pohyby(self.dyn[0]), [])

    def test_naskenovany_box_nepozice(self):
        """T27: štítek celého boxu místo přihrádky rozkládá ostrov C a odmítne ho."""
        dil_id, _ = self.dil()
        kod_boxu = self.spoj.hodnota("SELECT KodBoxu FROM dbo.Box WHERE BoxID = ?", self.dyn[0].box_id)
        self.chyba(self.prikaz, sluzby.prijem_dyn, kod="WRONG_SCAN_LEVEL",
                   vstup=PrijemDynVstup(request_id=uuid.uuid4(), dil_id=dil_id, cil_kod=kod_boxu, pocet_ks=5))
        self.assertEqual(self.obsah(self.dyn[0]), None)

    def test_dlouhy_kod_pozice(self):
        """Celá adresa ze štítku (HOUFEK-…-R01-U01-BOX-G) je týž cíl jako krátký kód B…-G (Q-02)."""
        dil_id, _ = self.dil()
        self.prikaz(sluzby.prijem_dyn, PrijemDynVstup(request_id=uuid.uuid4(), dil_id=dil_id,
                                                      cil_kod=self.dyn[0].adresa, pocet_ks=4))
        self.assertEqual(self.obsah(self.dyn[0]), (dil_id, 4))


class TestVydej(ZakladSkladu):
    """T04, T07, T15: výdej z DYN i STAT pozice, nikdy záporný sklad."""

    def test_vydej_z_dyn_na_nulu(self):
        dil_id, _ = self.dil()
        self.prijem(self.dyn[0], dil_id, 30)
        vysledek = self.vydej(self.dyn[0], 30)
        self.assertEqual([(p.typ_pohybu, p.mnozstvi, p.stav_po_ks) for p in vysledek.pohyby], [("VYDEJ", -30, 0)])
        self.assertEqual((vysledek.zdroj.stav_ks, vysledek.zdroj.dil_id, vysledek.zdroj.stav_boxu),
                         (0, None, "VOLNY"))                                        # pozice je volná, box taky
        self.assertEqual(self.obsah(self.dyn[0]), None)                             # řádek ObsahPozice smazán
        self.assertEqual([(r["Mnozstvi"], r["StavPred"], r["StavPo"]) for r in self.pohyby(self.dyn[0])],
                         [(30, 0, 30), (-30, 30, 0)])                               # historie zůstává
        self.assertEqual(self.soucet_pohybu(self.dyn[0]), 0)

    def test_vydej_ze_stat_zustava_pozice_dilu(self):
        """T07: po vyprázdnění zůstává STAT pozice dílu vyhrazená a hlídá svoje minimum."""
        dil_id, _ = self.dil()
        stat_id = self.prirad_stat(dil_id, self.stat[0], minimalni_ks=0)
        self.uskladni(self.stat[0], dil_id, 6)
        vysledek = self.vydej(self.stat[0], 6)
        self.assertEqual((vysledek.stav_zasoby, vysledek.upozorneni), ("VYCERPANO", "ZALOZENO"))   # N-08
        self.assertEqual(self.obsah(self.stat[0]), None)
        mista = sklad.stat_mista(self.spoj, vnitrni_pozice_ids=[self.stat[0].vnitrni_pozice_id])
        self.assertEqual([s.stat_umisteni_id for s in mista], [stat_id])
        self.assertEqual([(r["TypStavu"], r["StavUpozorneni"], r["AktualniPocetKs"])
                          for r in self.upozorneni(stat_id)], [("VYCERPANO", "OTEVRENE", 0)])

    def test_vydej_nad_zasobu_se_nezapije(self):
        """T15: nedostatek kusů i souběžná změna nic nezmění (žádný pohyb, žádný nový obsah)."""
        dil_id, _ = self.dil()
        self.prijem(self.dyn[0], dil_id, 10)
        self.chyba(self.vydej, self.dyn[0], 11, kod="INSUFFICIENT_STOCK")
        self.chyba(self.vydej, self.dyn[1], 1, kod="INSUFFICIENT_STOCK")
        self.chyba(self.vydej, self.dyn[0], 1, kod="CONCURRENT_CHANGE", ocekavany_stav_ks=9)
        self.blokuj(self.dyn[0])
        self.chyba(self.vydej, self.dyn[0], 1, kod="POSITION_BLOCKED")
        self.assertEqual(self.obsah(self.dyn[0]), (dil_id, 10))
        self.assertEqual(len(self.pohyby(self.dyn[0])), 1)

    def test_castecny_vydej_ponecha_obsah(self):
        dil_id, _ = self.dil()
        self.prijem(self.dyn[0], dil_id, 10)
        vysledek = self.vydej(self.dyn[0], 4, ocekavany_stav_ks=10)
        self.assertEqual((vysledek.zdroj.stav_ks, vysledek.zdroj.stav_boxu), (6, "OBSAZENY"))
        self.assertEqual(self.obsah(self.dyn[0]), (dil_id, 6))


class TestPresun(ZakladSkladu):
    """T05, T16: přesun celé dávky DYN → DYN se dvěma pohyby se stejným TransakceID."""

    def test_presun_cele_davky(self):
        dil_id, _ = self.dil()
        self.prijem(self.dyn[0], dil_id, 12)
        presunuty = self.presun(self.dyn[0], self.dyn[1])
        self.assertEqual([(p.typ_pohybu, p.kod, p.mnozstvi) for p in presunuty.pohyby],
                         [("PRESUN-OUT", self.dyn[0].kod, -12), ("PRESUN-IN", self.dyn[1].kod, 12)])
        self.assertEqual((presunuty.zdroj.stav_ks, presunuty.cil.stav_ks), (0, 12))
        radky = self.pohyby(self.dyn[0], self.dyn[1])
        self.assertEqual([r["KodPohybu"] for r in radky], ["PRIJEM", "PRESUN-OUT", "PRESUN-IN"])
        self.assertEqual([self.uid(r["TransakceID"]) for r in radky[-2:]],
                         [self.spoj.transakce_id] * 2)                                       # T05
        self.assertEqual(self.obsah(self.dyn[0]), None)
        self.assertEqual(self.obsah(self.dyn[1]), (dil_id, 12))
        self.assertEqual([self.soucet_pohybu(m) for m in self.dyn[:2]], [0, 12])

    def test_presun_se_posle_cela_davka(self):
        """T16: množství se v příkazu neposílá – poslané pocetKs odmítne kontrakt (WHOLE_BATCH_ONLY)."""
        self.chyba(PresunVstup, kod="WHOLE_BATCH_ONLY", zdrojKod=self.dyn[0].kod, cilKod=self.dyn[1].kod,
                   pocetKs=5)

    def test_presun_odmitne_spatny_zdroj_cil_a_pracoviste(self):
        """Q-07: přesun je jen DYN → DYN v rámci pracoviště; prázdný zdroj je nedostatek kusů."""
        self.chyba(self.presun, self.stat[0], self.dyn[0], kod="VALIDATION_ERROR")
        self.chyba(self.presun, self.dyn[0], self.dyn[1], kod="INSUFFICIENT_STOCK")
        jine_pracoviste = nova_struktura(self.spoj, self.kdo)
        self.chyba(self.prikaz, sluzby.presun, kod="VALIDATION_ERROR",
                   vstup=PresunVstup(request_id=uuid.uuid4(), zdroj_kod=self.dyn[0].kod,
                                     cil_kod=jine_pracoviste["dyn"][0].kod))
        self.assertEqual(self.pohyby(self.dyn[0]), [])


class TestUskladneniStat(ZakladSkladu):
    """T06, T08, T20, Q-08, Q-11, Q-14: uskladnění do STAT místa dílu a upozornění zásoby."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id, _ = self.dil()
        self.stat_id = self.prirad_stat(self.dil_id, self.stat[0], minimalni_ks=10, maximalni_ks=40)

    def test_uskladneni_z_vyroby_se_pricte(self):
        """T06: uskladnění bez zdroje je PRIJEM a množství se přičte k tomu, co už na pozici je."""
        prvni = self.uskladni(self.stat[0], self.dil_id, 15)
        self.assertEqual([(p.typ_pohybu, p.mnozstvi, p.stav_pred_ks, p.stav_po_ks) for p in prvni.pohyby],
                         [("PRIJEM", 15, 0, 15)])
        druhy = self.uskladni(self.stat[0], self.dil_id, 5)
        self.assertEqual([(p.typ_pohybu, p.stav_pred_ks, p.stav_po_ks) for p in druhy.pohyby], [("PRIJEM", 15, 20)])
        self.assertEqual(self.obsah(self.stat[0]), (self.dil_id, 20))
        self.assertEqual((druhy.stav_zasoby, druhy.upozorneni, druhy.varovani), ("OK", None, ()))

    def test_uskladneni_z_dyn_pozice(self):
        """Q-08: ze DYN pozice jsou dva pohyby (OUT + IN) se stejným TransakceID, zdroj se ztenčí."""
        self.prijem(self.dyn[0], self.dil_id, 8)
        vysledek = self.uskladni(self.stat[0], self.dil_id, 3, zdroj_kod=self.dyn[0].kod)
        self.assertEqual([(p.typ_pohybu, p.kod, p.mnozstvi) for p in vysledek.pohyby],
                         [("PRESUN-OUT", self.dyn[0].kod, -3), ("PRESUN-IN", self.stat[0].kod, 3)])
        radky = self.pohyby(self.dyn[0], self.stat[0])
        self.assertEqual([self.uid(r["TransakceID"]) for r in radky[-2:]], [self.spoj.transakce_id] * 2)
        self.assertEqual((self.obsah(self.dyn[0]), self.obsah(self.stat[0])), ((self.dil_id, 5), (self.dil_id, 3)))
        cela = self.uskladni(self.stat[0], self.dil_id, 5, zdroj_kod=self.dyn[0].kod)
        self.assertEqual((cela.zdroj.stav_ks, cela.zdroj.stav_boxu, self.obsah(self.dyn[0])), (0, "VOLNY", None))
        self.assertEqual(self.obsah(self.stat[0]), (self.dil_id, 8))

    def test_uskladneni_patri_jen_svuj_dil(self):
        jiny_dil, _ = self.dil()
        self.chyba(self.uskladni, self.stat[0], jiny_dil, 5, kod="WRONG_PART")
        self.chyba(self.uskladni, self.stat[1], self.dil_id, 5, kod="WRONG_PART")   # pozice bez přiřazení
        self.prijem(self.dyn[0], jiny_dil, 5)
        self.chyba(self.uskladni, self.stat[0], self.dil_id, 5, kod="WRONG_PART", zdroj_kod=self.dyn[0].kod)
        self.blokuj(self.stat[0])
        self.chyba(self.uskladni, self.stat[0], self.dil_id, 5, kod="POSITION_BLOCKED")   # Q-14: bez náhrady
        self.assertEqual(self.obsah(self.stat[0]), None)

    def test_uskladneni_nad_maximum_jen_varuje(self):
        """Q-11: maximum je měkké – operace proběhne a odpověď nese varování."""
        vysledek = self.uskladni(self.stat[0], self.dil_id, 45)
        self.assertEqual(self.obsah(self.stat[0]), (self.dil_id, 45))
        self.assertEqual([v.kod for v in vysledek.varovani], ["NAD_MAXIMEM"])
        self.assertEqual(vysledek.stav_zasoby, "OK")

    def test_pod_minimem_vznikne_jedno_upozorneni(self):
        """T08: pod minimem se založí jedno otevřené upozornění; další výdej beze změny stavu nic nepřidá."""
        self.uskladni(self.stat[0], self.dil_id, 12)
        prvni = self.vydej(self.stat[0], 5)
        self.assertEqual((prvni.stav_zasoby, prvni.upozorneni), ("POD_MINIMEM", "ZALOZENO"))
        druhy = self.vydej(self.stat[0], 1)
        self.assertEqual((druhy.stav_zasoby, druhy.upozorneni), ("POD_MINIMEM", None))   # žádný spam (Q-13)
        # snímek platí od okamžiku vzniku – výdej beze změny stavu upozornění nepřepisuje
        self.assertEqual([(r["TypStavu"], r["StavUpozorneni"], r["AktualniPocetKs"], r["MinimalniPocetKs"])
                          for r in self.upozorneni(self.stat_id)], [("POD_MINIMEM", "OTEVRENE", 7, 10)])

    def test_opakovane_vydeje_pod_minimem_a_doplneni(self):
        """T20: stále jedno otevřené upozornění, po doplnění nad minimum uzavřené; nový pokles = nové."""
        self.uskladni(self.stat[0], self.dil_id, 12)
        for ocekavane, pocet in (("ZALOZENO", 2), ("AKTUALIZOVANO", 2)):   # 10 = NA_MINIMU, pak POD_MINIMEM
            self.assertEqual(self.vydej(self.stat[0], pocet).upozorneni, ocekavane)
        self.assertEqual(self.vydej(self.stat[0], 1).upozorneni, None)      # 7 ks, stav se nemění → žádný spam
        self.assertEqual(len(self.upozorneni(self.stat_id)), 1)
        doplneni = self.uskladni(self.stat[0], self.dil_id, 10)
        self.assertEqual((doplneni.stav_zasoby, doplneni.upozorneni), ("OK", "UZAVRENO"))
        prvni, = self.upozorneni(self.stat_id)
        self.assertEqual((prvni["StavUpozorneni"], prvni["TypStavu"], prvni["AktualniPocetKs"]),
                         ("UZAVRENE", "POD_MINIMEM", 8))                    # snímek naposledy změněného stavu
        self.assertIsNotNone(prvni["DatumUzavreni"])
        self.assertEqual(prvni["UzavrelUzivatelID"], self.kdo.uzivatel_id)
        self.assertEqual(self.vydej(self.stat[0], 10).upozorneni, "ZALOZENO")   # nový pokles = nové upozornění
        self.assertEqual([(r["StavUpozorneni"], r["TypStavu"]) for r in self.upozorneni(self.stat_id)],
                         [("UZAVRENE", "POD_MINIMEM"), ("OTEVRENE", "POD_MINIMEM")])

    def test_klesnuti_na_minimum_aktualizuje_stejne_upozorneni(self):
        self.uskladni(self.stat[0], self.dil_id, 12)
        self.assertEqual(self.vydej(self.stat[0], 2).upozorneni, "ZALOZENO")   # 10 ks = přesně minimum
        self.assertEqual([(r["TypStavu"], r["AktualniPocetKs"]) for r in self.upozorneni(self.stat_id)],
                         [("NA_MINIMU", 10)])
        self.assertEqual(self.vydej(self.stat[0], 1).upozorneni, "AKTUALIZOVANO")
        self.assertEqual([(r["TypStavu"], r["AktualniPocetKs"]) for r in self.upozorneni(self.stat_id)],
                         [("POD_MINIMEM", 9)])                                 # pořád jedno řádku
        self.assertEqual(len(self.upozorneni(self.stat_id)), 1)


class TestCteniRozhrani(ZakladSkladu):
    """Čtecí funkce rozhraní (obsah, poslední pohyby, STAT místa, číselníky) nad SQL Serverem."""

    def test_obsah_mist_a_posledni_pohyby(self):
        dil_id, _ = self.dil()
        for poradi, misto in enumerate(self.dyn[:3]):
            self.prijem(misto, dil_id, 3 + poradi)
        obsazene = sklad.obsah_mist(self.spoj, [m.vnitrni_pozice_id for m in self.dyn])
        self.assertEqual({m: o.pocet_ks for m, o in obsazene.items()},
                         {self.dyn[i].vnitrni_pozice_id: 3 + i for i in range(3)})      # prázdná pozice chybí
        posledni = sklad.posledni_pohyby(self.spoj, [m.vnitrni_pozice_id for m in self.dyn])
        self.assertEqual(posledni[self.dyn[3].vnitrni_pozice_id], None)
        self.assertTrue(all(posledni[self.dyn[i].vnitrni_pozice_id] is not None for i in range(3)))
        self.assertEqual(sklad.obsah_mist(self.spoj, []), {})

    def test_stat_mista_podle_pozice_a_dilu(self):
        dil_id, _ = self.dil()
        misto = self.stat[2]
        stat_id = self.prirad_stat(dil_id, misto, minimalni_ks=5, maximalni_ks=50)
        ocekavane = [sklad.StatMistoInfo(stat_id, dil_id, misto.vnitrni_pozice_id, 5, None, 50)]
        self.assertEqual(sklad.stat_mista(self.spoj, vnitrni_pozice_ids=[misto.vnitrni_pozice_id]), ocekavane)
        self.assertEqual(sklad.stat_mista(self.spoj, dil_ids=[dil_id]), ocekavane)
        self.assertEqual(sklad.stat_mista(self.spoj, dil_ids=[self.dil()[0]]), [])
        self.assertIn(stat_id, [s.stat_umisteni_id for s in sklad.stat_mista(self.spoj)])
        self.spoj.proved("UPDATE dbo.StatickeUmisteniDilu SET Aktivni = 0 WHERE StatickeUmisteniID = ?", stat_id)
        self.assertEqual(sklad.stat_mista(self.spoj, vnitrni_pozice_ids=[misto.vnitrni_pozice_id]), [])

    def test_ciselnik_typu_pohybu(self):
        polozky = sklad.nacti_ciselniky(self.spoj)["typyPohybu"]
        self.assertLessEqual({"PRIJEM", "VYDEJ", "PRESUN-OUT", "PRESUN-IN"}, {p.kod for p in polozky})
        for polozka in polozky:
            self.assertEqual(polozka.id, self.spoj.hodnota("SELECT TypPohybuID FROM dbo.TypPohybu"
                                                           " WHERE KodPohybu = ?", polozka.kod))


class TestKandidati(ZakladSkladu):
    """21.1.3: volné DYN pozice pro díl nad SQL Serverem, včetně ostatních regálů pracoviště (Q-10)."""

    def kandidati(self, dil_id: int, **filtr) -> list:
        """Položky odpovědi – `Seznam` sám o sobě položky neprochází (iteruje pole modelu)."""
        return sluzby.kandidati_dyn.__wrapped__(self.spoj, KandidatiFiltr(dil_id=dil_id,
                                                                         regal_id=self.svet["regal"],
                                                                         **filtr)).polozky

    def test_volne_pozice_podle_velikosti(self):
        dil_id, _ = self.dil()
        self.prijem(self.dyn[0], dil_id, 5)
        self.assertEqual([k.kod for k in self.kandidati(dil_id)], [m.kod for m in self.dyn[1:]])
        self.assertTrue(all(not k.jiny_regal for k in self.kandidati(dil_id)))
        self.assertEqual({(k.velikost, k.regal_id, k.box_id) for k in self.kandidati(dil_id)},
                         {("V3", self.svet["regal"], self.dyn[1].box_id)})

    def test_kandidati_i_z_druheho_regalu(self):
        dil_id, _ = self.dil()
        self.prijem(self.dyn[0], dil_id, 5)
        self.assertEqual([k.kod for k in self.kandidati(dil_id, vcetne_ostatnich_regalu=True)],
                         [m.kod for m in self.dyn[1:] + self.dalsi_dyn])               # nejdřív zvolený regál
        self.assertEqual([k.jiny_regal for k in self.kandidati(dil_id, vcetne_ostatnich_regalu=True)],
                         [False] * 3 + [True] * 4)
        self.assertNotIn(self.dalsi_dyn[0].kod, [k.kod for k in self.kandidati(dil_id)])   # jen zvolený regál

    def test_kandidati_podle_naskenovaneho_regalu_a_chyby(self):
        dil_id, _ = self.dil()
        kod_regalu = self.spoj.hodnota(
            "SELECT CONCAT(f.KodFirmy, '-', p.KodPracoviste, '-', r.KodRegalu) FROM dbo.Regal AS r"
            " JOIN dbo.Pracoviste AS p ON p.PracovisteID = r.PracovisteID"
            " JOIN dbo.Firma AS f ON f.FirmaID = p.FirmaID WHERE r.RegalID = ?", self.svet["regal"])
        kandidati = sluzby.kandidati_dyn.__wrapped__(self.spoj,
                                                    KandidatiFiltr(dil_id=dil_id, kod_regalu=kod_regalu)).polozky
        self.assertEqual([k.kod for k in kandidati], [m.kod for m in self.dyn])
        bez_velikosti, _ = self.dil(None)
        self.chyba(self.kandidati, bez_velikosti, kod="PART_HAS_NO_SIZE")
        self.chyba(sluzby.kandidati_dyn.__wrapped__, self.spoj,
                   KandidatiFiltr(dil_id=dil_id, regal_id=2_000_000_000), kod="NOT_FOUND")


class TestSeznamUpozorneni(ZakladSkladu):
    """Upozornění zásoby přes službu: číslo dílu a kód pozice doplňují rozhraní ostrovů D a C."""

    def seznam(self, **filtr):
        return sluzby.seznam_upozorneni.__wrapped__(self.spoj, UpozorneniFiltr(**filtr))

    def test_radek_obsahuje_i_udaje_jinych_ostrova(self):
        dil_id, cislo = self.dil()
        stat_id = self.prirad_stat(dil_id, self.stat[0], minimalni_ks=10)
        self.uskladni(self.stat[0], dil_id, 12)
        self.vydej(self.stat[0], 8)
        stranka = self.seznam(dil_id=dil_id)
        self.assertEqual((stranka.celkem, len(stranka.polozky)), (1, 1))
        radek = stranka.polozky[0]
        self.assertEqual((radek.upozorneni_id, radek.stat_umisteni_id, radek.dil_id),
                         (self.upozorneni(stat_id)[0]["UpozorneniID"], stat_id, dil_id))
        self.assertEqual((radek.identifikacni_cislo, radek.kod), (cislo, self.stat[0].kod))
        self.assertEqual((radek.typ_stavu, radek.stav_upozorneni), ("POD_MINIMEM", "OTEVRENE"))
        self.assertEqual((radek.aktualni_pocet_ks, radek.minimalni_pocet_ks), (4, 10))
        self.assertEqual((radek.datum_uzavreni, radek.poznamka), (None, None))

    def test_filtry_stavu_a_typu(self):
        dil_id, _ = self.dil()
        self.prirad_stat(dil_id, self.stat[0], minimalni_ks=10)
        self.uskladni(self.stat[0], dil_id, 12)
        self.vydej(self.stat[0], 8)
        otevrene = self.seznam(dil_id=dil_id).polozky                       # výchozí filtr = jen otevřená
        self.assertEqual([r.stav_upozorneni for r in otevrene], ["OTEVRENE"])
        self.assertEqual(self.seznam(dil_id=dil_id, stav="UZAVRENE").polozky, [])
        self.assertEqual([r.typ_stavu for r in self.seznam(dil_id=dil_id, typ_stavu="POD_MINIMEM").polozky],
                         ["POD_MINIMEM"])
        self.assertEqual(self.seznam(dil_id=dil_id, typ_stavu="VYCERPANO").polozky, [])
        self.uskladni(self.stat[0], dil_id, 10)                             # doplnění nad minimum → uzavřené
        uzavrene = self.seznam(dil_id=dil_id, stav="UZAVRENE").polozky
        self.assertEqual([r.stav_upozorneni for r in uzavrene], ["UZAVRENE"])
        self.assertIsNotNone(uzavrene[0].datum_uzavreni)
        self.assertEqual(self.seznam(dil_id=dil_id).polozky, [])            # žádné otevřené (Q-13)
        self.assertEqual(self.seznam(dil_id=dil_id, stav=None).celkem, 1)   # bez filtru stavu i historie


class TestHistorieACelistvi(ZakladSkladu):
    """T32: součet pohybů na pozici sedí na její obsah; kontrola integrity je za našich dat čistá.

    Běh obsahuje skladové příkazy, STAT místo ze služby, korekci i ruční uzavření upozornění,
    takže prověří najednou všechny zápisové cesty ostrova.
    """

    def test_beh_skladem(self):
        dil_id, _ = self.dil()
        stat_id = self.zaloz_stat(dil_id, self.stat[0], minimalni_ks=25).stat_umisteni_id
        self.prijem(self.dyn[0], dil_id, 20, poznamka="příjem z výroby")
        self.presun(self.dyn[0], self.dyn[1])
        self.uskladni(self.stat[0], dil_id, 20, zdroj_kod=self.dyn[1].kod)
        self.vydej(self.stat[0], 2)
        self.korekce(self.dyn[2], dil_id, 7, "POCAT-STAV")
        self.uzavri_upozorneni(self.upozorneni(stat_id)[0]["UpozorneniID"], "doplňuje se průběžně")
        for misto in self.pozice:
            stav = self.obsah(misto)
            self.assertEqual(self.soucet_pohybu(misto), stav[1] if stav else 0, misto.kod)   # T32
            for radek in self.pohyby(misto):
                self.assertEqual(radek["StavPo"], radek["StavPred"] + radek["Mnozstvi"], radek)
                self.assertNotEqual(radek["Mnozstvi"], 0)
                self.assertIsNotNone(radek["TransakceID"])                # každá změna má svou transakci
                self.assertEqual(radek["UzivatelID"], self.kdo.uzivatel_id)
                self.assertIsNotNone(radek["DatumCas"])
        self.assertEqual(self.obsah(self.dyn[1]), None)
        self.assertEqual(self.obsah(self.stat[0]), (dil_id, 18))
        self.over_integrity()


class TestStatMistaZalozeni(ZakladSkladu):
    """Bod 1: služba založí STAT místo, pohlídá jedno místo na díl (Q-12) a volnost pozice, zapíše audit."""

    def test_zalozeni_zapise_prirazeni_a_audit(self):
        dil_id, _ = self.dil()
        radek = self.zaloz_stat(dil_id, self.stat[0], minimalni_ks=5, maximalni_ks=20, duvod="nový díl na lince")
        self.assertGreater(radek.stat_umisteni_id, 0)                      # IDENTITY, ne vzorové NOVE_ID
        self.assertEqual((radek.dil_id, radek.kod, radek.aktivni), (dil_id, self.stat[0].kod, True))
        self.assertEqual((radek.minimalni_ks, radek.maximalni_ks, radek.stav_ks, radek.stav_zasoby),
                         (5, 20, 0, "VYCERPANO"))
        mista = sklad.stat_mista(self.spoj, dil_ids=[dil_id])
        self.assertEqual([(m.stat_umisteni_id, m.vnitrni_pozice_id, m.minimalni_ks, m.maximalni_ks) for m in mista],
                         [(radek.stat_umisteni_id, self.stat[0].vnitrni_pozice_id, 5, 20)])
        self.assertEqual([(a["Pole"], a["StaraHodnota"], a["NovaHodnota"], a["Poznamka"], a["UzivatelID"])
                          for a in self.audit("STAT_UMISTENI", radek.stat_umisteni_id)],
                         [("DilID", None, str(dil_id), "nový díl na lince", self.kdo.uzivatel_id)])
        self.assertEqual(self.upozorneni(radek.stat_umisteni_id), [])   # při založení se upozornění nezakládá

    def test_druhe_misto_tehoz_dilu_a_obsazena_pozice(self):
        dil_id, _ = self.dil()
        druhy_dil, _ = self.dil()
        self.zaloz_stat(dil_id, self.stat[0])
        self.chyba(self.zaloz_stat, dil_id, self.stat[1], kod="ALREADY_EXISTS")     # Q-12: nejvýš jedno místo
        self.chyba(self.zaloz_stat, druhy_dil, self.stat[0], kod="ALREADY_EXISTS")  # pozice už je přiřazená
        self.assertEqual(len(sklad.stat_mista(self.spoj, dil_ids=[dil_id])), 1)
        self.assertEqual(self.obsah(self.stat[0]), None)                            # ani obsah se nezměnil

    def test_odmitne_pozici_mimo_stat_chybejici_data_a_spatne_meze(self):
        dil_id, _ = self.dil()
        self.chyba(self.zaloz_stat, dil_id, self.dyn[0], kod="VALIDATION_ERROR")            # ne STAT pozice
        self.chyba(self.zaloz_stat, dil_id, self.stat[0], minimalni_ks=30, maximalni_ks=20,
                   kod="VALIDATION_ERROR")                                                  # max < min
        self.chyba(self.zaloz_stat, 2_000_000_000, self.stat[0], kod="NOT_FOUND")           # neznámý díl
        self.chyba(sluzby.zaloz_stat_misto.__wrapped__, self.spoj, NoveStatMistoVstup(
            dil_id=dil_id, vnitrni_pozice_id=2_000_000_000, minimalni_ks=0), self.kdo, kod="NOT_FOUND")
        self.assertEqual(sklad.stat_mista(self.spoj, vnitrni_pozice_ids=[m.vnitrni_pozice_id for m in self.stat]), [])

    def test_dil_bez_velikosti_se_na_stat_pozici_priradi(self):
        """Q-26: díl bez velikosti se do STAT přiřadit smí – jde o aktivní přiřazení, ne o DYN pozici."""
        bez_velikosti, _ = self.dil(None)
        radek = self.zaloz_stat(bez_velikosti, self.stat[0], minimalni_ks=1)
        self.assertEqual(sklad.stat_mista(self.spoj, dil_ids=[bez_velikosti])[0].stat_umisteni_id,
                         radek.stat_umisteni_id)


class TestRozhraniPriradStatMisto(ZakladSkladu):
    """Migrační cesta `rozhrani.prirad_stat_misto`: stejné kontroly, ale přepsání velikosti nikdy."""

    def test_priradi_se_shodnou_velikosti_a_odmitne_jinou(self):
        dil_id, _ = self.dil()
        stat_id = sklad.prirad_stat_misto(self.spoj, self.kdo, dil_id, self.stat[0].vnitrni_pozice_id, 3, None, 30)
        self.assertEqual([(a["Pole"], a["NovaHodnota"], a["Poznamka"])
                          for a in self.audit("STAT_UMISTENI", stat_id)], [("DilID", str(dil_id), None)])
        self.assertEqual(sklad.stat_mista(self.spoj, dil_ids=[dil_id])[0].stat_umisteni_id, stat_id)
        mala, _ = self.dil("V1")
        self.chyba(sklad.prirad_stat_misto, self.spoj, self.kdo, mala, self.stat[1].vnitrni_pozice_id, 0, None, None,
                   kod="SIZE_MISMATCH")
        self.chyba(sklad.prirad_stat_misto, self.spoj, self.kdo, dil_id, self.stat[2].vnitrni_pozice_id, 0, None,
                   None, kod="ALREADY_EXISTS")                       # ten samý díl podruhé (Q-12)


class TestPrepsatVelikost(ZakladSkladu):
    """Q-05: jiná velikost na STAT pozici jen vědomé přepsání – TECH/ADMIN s důvodem, důvod jde do auditu."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id, self.cislo = self.dil("V1")      # STAT box C4 má přihrádky V3

    def test_operater_prepsani_nesmí_a_technolog_bez_duvodu(self):
        self.chyba(self.zaloz_stat, self.dil_id, self.stat[0], prepsat_velikost=True, duvod="vejde se",
                   kdo=Kontext(self.kdo.uzivatel_id, None, "SKL", frozenset()), kod="NO_PERMISSION")
        self.chyba(self.zaloz_stat, self.dil_id, self.stat[0], prepsat_velikost=True,
                   kdo=Kontext(self.kdo.uzivatel_id, None, "TECH", frozenset()), kod="VALIDATION_ERROR")
        self.assertEqual(sklad.stat_mista(self.spoj, vnitrni_pozice_ids=[self.stat[0].vnitrni_pozice_id]), [])

    def test_technolog_s_duvodem_prepsani_zapise(self):
        radek = self.zaloz_stat(self.dil_id, self.stat[0], prepsat_velikost=True, duvod="křížová příprava V1/V3",
                                kdo=Kontext(self.kdo.uzivatel_id, None, "TECH", frozenset()))
        self.assertEqual(radek.kod, self.stat[0].kod)
        self.assertEqual([(a["Pole"], a["StaraHodnota"], a["NovaHodnota"], a["Poznamka"])
                          for a in self.audit("STAT_UMISTENI", radek.stat_umisteni_id)],
                         [("DilID", None, str(self.dil_id), "křížová příprava V1/V3"),
                          ("VelikostPoziceID", "V3", "V1", "křížová příprava V1/V3")])
        # přepsaná velikost je v kontrole integrity hlášená výslovně (Q-05: „ověřte důvod v auditu“),
        # proto tenhle test volá jen nálezy za svým dílem – `over_integrity()` by čekal čistý list
        self.assertEqual([n["Kontrola"] for n in self.spoj.dotaz(
            "SELECT Kontrola FROM dbo.v_KontrolaIntegrity WHERE Popis LIKE ?", f"%{self.cislo}%")],
                         ["STAT_VELIKOST_PREPSANA"])


class TestZmenaStatMista(ZakladSkladu):
    """Bod 2: změna mezí píše audit měněných polí a přehodnotí upozornění zásoby stejnými pravidly (5.8)."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id, _ = self.dil()
        self.stat_id = self.zaloz_stat(self.dil_id, self.stat[0], minimalni_ks=5, maximalni_ks=40).stat_umisteni_id
        self.uskladni(self.stat[0], self.dil_id, 8)

    def test_zvysseni_minima_zalozi_upozorneni(self):
        radek = self.zmen_stat(self.stat_id, "vyšší spotřeba", minimalni_ks=15)
        self.assertEqual((radek.minimalni_ks, radek.maximalni_ks, radek.stav_ks, radek.stav_zasoby),
                         (15, 40, 8, "POD_MINIMEM"))
        self.assertEqual([v.kod for v in radek.varovani], ["UPOZORNENI"])
        self.assertEqual([(r["TypStavu"], r["StavUpozorneni"], r["AktualniPocetKs"], r["MinimalniPocetKs"])
                          for r in self.upozorneni(self.stat_id)], [("POD_MINIMEM", "OTEVRENE", 8, 15)])
        self.assertEqual([(a["Pole"], a["StaraHodnota"], a["NovaHodnota"], a["Poznamka"])
                          for a in self.audit("STAT_UMISTENI", self.stat_id)],
                         [("DilID", None, str(self.dil_id), None),
                          ("MinimalniPocetKs", "5", "15", "vyšší spotřeba")])

    def test_snizeni_minima_upozorneni_uzavre(self):
        self.zmen_stat(self.stat_id, "vyšší spotřeba", minimalni_ks=20)
        self.assertEqual([r["StavUpozorneni"] for r in self.upozorneni(self.stat_id)], ["OTEVRENE"])
        radek = self.zmen_stat(self.stat_id, "oprava minima", minimalni_ks=5)
        self.assertEqual((radek.stav_ks, radek.stav_zasoby), (8, "OK"))
        uzavrene = self.upozorneni(self.stat_id)[0]
        self.assertEqual(uzavrene["StavUpozorneni"], "UZAVRENE")
        self.assertIsNotNone(uzavrene["DatumUzavreni"])
        self.assertEqual(uzavrene["UzavrelUzivatelID"], self.kdo.uzivatel_id)
        self.assertEqual(self.zmen_stat(self.stat_id, "stejné minimum", minimalni_ks=5).varovani, ())

    def test_zmeni_se_jen_poslana_pole(self):
        radek = self.zmen_stat(self.stat_id, "optimum a žádné maximum", optimalni_ks=20, maximalni_ks=None)
        self.assertEqual((radek.minimalni_ks, radek.optimalni_ks, radek.maximalni_ks), (5, 20, None))
        self.assertEqual(radek.varovani, ())                                      # na stavu se nic nezměnilo
        self.assertEqual([(a["Pole"], a["StaraHodnota"], a["NovaHodnota"]) for a in self.audit("STAT_UMISTENI",
                                                                                               self.stat_id)],
                         [("DilID", None, str(self.dil_id)), ("OptimalniPocetKs", None, "20"),
                          ("MaximalniPocetKs", "40", None)])

    def test_meze_v_rozporu_se_nezapijou(self):
        self.chyba(self.zmen_stat, self.stat_id, "kaukaz", minimalni_ks=50, kod="VALIDATION_ERROR")
        self.assertEqual(self.spoj.hodnota("SELECT MinimalniPocetKs FROM dbo.StatickeUmisteniDilu"
                                           " WHERE StatickeUmisteniID = ?", self.stat_id), 5)
        self.assertEqual([a["Pole"] for a in self.audit("STAT_UMISTENI", self.stat_id)], ["DilID"])
        self.assertEqual(self.upozorneni(self.stat_id), [])


class TestUkonceniStatMista(ZakladSkladu):
    """Bod 3: přiřazení se ukončí jen u prázdné pozice; audit s důvodem, otevřené upozornění i s poznámkou."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id, _ = self.dil()
        self.stat_id = self.zaloz_stat(self.dil_id, self.stat[0], minimalni_ks=5).stat_umisteni_id

    def test_obsazenou_pozici_ukoncit_nejde(self):
        self.uskladni(self.stat[0], self.dil_id, 4)
        self.chyba(self.ukonci_stat, self.stat_id, "přestavba regálu", kod="NOT_EMPTY")
        self.assertEqual(self.spoj.hodnota("SELECT Aktivni FROM dbo.StatickeUmisteniDilu"
                                           " WHERE StatickeUmisteniID = ?", self.stat_id), True)
        self.assertEqual([a["Pole"] for a in self.audit("STAT_UMISTENI", self.stat_id)], ["DilID"])

    def test_ukonceni_prazdne_pozice_uzavre_upozorneni(self):
        self.uskladni(self.stat[0], self.dil_id, 12)
        self.vydej(self.stat[0], 12)                                        # 0 ks → VYCERPANO, otevřené
        radek = self.ukonci_stat(self.stat_id, "díl se nevyrábí")
        self.assertFalse(radek.aktivni)
        self.assertEqual([v.kod for v in radek.varovani], ["UPOZORNENI"])
        self.assertEqual(self.spoj.hodnota("SELECT Aktivni FROM dbo.StatickeUmisteniDilu"
                                           " WHERE StatickeUmisteniID = ?", self.stat_id), False)
        self.assertEqual(sklad.stat_mista(self.spoj, dil_ids=[self.dil_id]), [])
        upozorneni = self.upozorneni(self.stat_id)[0]
        self.assertEqual((upozorneni["StavUpozorneni"], upozorneni["Poznamka"], upozorneni["UzavrelUzivatelID"]),
                         ("UZAVRENE", "díl se nevyrábí", self.kdo.uzivatel_id))
        self.assertEqual([(a["Pole"], a["StaraHodnota"], a["NovaHodnota"], a["Poznamka"])
                          for a in self.audit("STAT_UMISTENI", self.stat_id)][-1],
                         ("Aktivni", "True", "False", "díl se nevyrábí"))
        self.chyba(self.ukonci_stat, self.stat_id, "podruhé", kod="NOT_FOUND")   # aktivní místo už není

    def test_ukonceni_bez_upozorneni_bez_varovani(self):
        radek = self.ukonci_stat(self.stat_id, "omylem přiřazený díl")
        self.assertEqual((radek.aktivni, radek.varovani), (False, ()))
        self.assertEqual(self.upozorneni(self.stat_id), [])


class TestRucniUzavreniUpozorneni(ZakladSkladu):
    """Bod 4: ruční uzavření nad databází – poznámka, kdo zavřel; podruhé CONCURRENT_CHANGE, netrefené NOT_FOUND."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id, self.cislo = self.dil()
        self.stat_id = self.prirad_stat(self.dil_id, self.stat[0], minimalni_ks=10)
        self.uskladni(self.stat[0], self.dil_id, 12)
        self.vydej(self.stat[0], 8)                                                     # 4 ks → POD_MINIMEM
        self.id_upozorneni = self.upozorneni(self.stat_id)[0]["UpozorneniID"]

    def test_uzavreni_zapise_uzivatele_a_poznamku(self):
        radek = self.uzavri_upozorneni(self.id_upozorneni, "díl vyrábíme jiným postupem")
        self.assertEqual((radek.upozorneni_id, radek.stav_upozorneni, radek.poznamka, radek.typ_stavu),
                         (self.id_upozorneni, "UZAVRENE", "díl vyrábíme jiným postupem", "POD_MINIMEM"))
        self.assertEqual((radek.identifikacni_cislo, radek.kod, radek.minimalni_pocet_ks),
                         (self.cislo, self.stat[0].kod, 10))
        self.assertIsNotNone(radek.datum_uzavreni)
        z_databaze = self.upozorneni(self.stat_id)[0]
        self.assertEqual((z_databaze["StavUpozorneni"], z_databaze["UzavrelUzivatelID"], z_databaze["Poznamka"]),
                         ("UZAVRENE", self.kdo.uzivatel_id, "díl vyrábíme jiným postupem"))
        self.assertEqual(sluzby.seznam_upozorneni.__wrapped__(self.spoj, UpozorneniFiltr(dil_id=self.dil_id)).polozky,
                         [])                                                             # otevřená nezbývají

    def test_druhe_uzavreni_a_neexistujici_upozorneni(self):
        self.uzavri_upozorneni(self.id_upozorneni, "díl rušíme")
        self.chyba(self.uzavri_upozorneni, self.id_upozorneni, "podruhé", kod="CONCURRENT_CHANGE")
        self.chyba(self.uzavri_upozorneni, 2_000_000_000, "nic takového", kod="NOT_FOUND")
        self.assertEqual(self.upozorneni(self.stat_id)[0]["Poznamka"], "díl rušíme")      # odmítnutí nic nepřepíše


class TestKorekce(ZakladSkladu):
    """Bod 5: `zauctuj_korekci` nastaví stav pozice a zapíše rozdíl jako pohyb (volá ho ostrov F)."""

    def setUp(self) -> None:
        super().setUp()
        self.dil_id, _ = self.dil()
        self.stat_id = self.prirad_stat(self.dil_id, self.stat[0], minimalni_ks=10)

    def test_korekce_zvysi_stav_a_prehodnoti_upozorneni(self):
        self.uskladni(self.stat[0], self.dil_id, 4)
        self.assertEqual(self.upozorneni(self.stat_id)[0]["TypStavu"], "POD_MINIMEM")
        korekce = self.korekce(self.stat[0], self.dil_id, 12, "INVENTURA", "inventurní stav 12 ks")
        self.assertEqual((korekce.typ_pohybu, korekce.mnozstvi, korekce.stav_pred_ks, korekce.stav_po_ks),
                         ("INVENTURA", 8, 4, 12))
        self.assertEqual(korekce.transakce_id, self.spoj.transakce_id)      # pohyb patří do transakce volajícího
        self.assertEqual(self.obsah(self.stat[0]), (self.dil_id, 12))
        self.assertEqual([(r["KodPohybu"], r["Mnozstvi"], r["StavPred"], r["StavPo"], r["Poznamka"],
                           r["ZpusobPotvrzeni"]) for r in self.pohyby(self.stat[0])][-1],
                         ("INVENTURA", 8, 4, 12, "inventurní stav 12 ks", None))
        self.assertEqual([(r["StavUpozorneni"], r["TypStavu"]) for r in self.upozorneni(self.stat_id)],
                         [("UZAVRENE", "POD_MINIMEM")])                                   # nad minimem (5.8)

    def test_korekce_na_nulu_smaze_radek_obsahu(self):
        self.uskladni(self.stat[0], self.dil_id, 4)
        korekce = self.korekce(self.stat[0], self.dil_id, 0)
        self.assertEqual((korekce.mnozstvi, korekce.stav_pred_ks, korekce.stav_po_ks), (-4, 4, 0))
        self.assertEqual(self.obsah(self.stat[0]), None)
        self.assertEqual(self.soucet_pohybu(self.stat[0]), 0)                             # T32
        self.assertEqual([(r["TypStavu"], r["StavUpozorneni"]) for r in self.upozorneni(self.stat_id)],
                         [("VYCERPANO", "OTEVRENE")])

    def test_pocatecni_stav_na_prazdne_pozici(self):
        korekce = self.korekce(self.dyn[0], self.dil_id, 25, "POCAT-STAV")
        self.assertEqual((korekce.stav_pred_ks, korekce.mnozstvi, korekce.stav_po_ks), (0, 25, 25))
        self.assertEqual((self.obsah(self.dyn[0]), self.soucet_pohybu(self.dyn[0])), ((self.dil_id, 25), 25))

    def test_korekce_na_blokovane_pozici_projde(self):
        """Q-09: blokace zastaví příjem, výdej a přesun – inventuru a její korekce ne."""
        self.blokuj(self.stat[0])
        self.chyba(self.uskladni, self.stat[0], self.dil_id, 5, kod="POSITION_BLOCKED")
        self.assertEqual(self.korekce(self.stat[0], self.dil_id, 5).stav_po_ks, 5)

    def test_odmitne_cizi_dil_a_obsazenou_pozici(self):
        jiny_dil, _ = self.dil()
        self.chyba(self.korekce, self.stat[0], jiny_dil, 5, kod="WRONG_PART")             # STAT jiného dílu
        self.chyba(self.korekce, self.stat[1], self.dil_id, 5, kod="WRONG_PART")          # STAT bez přiřazení
        self.prijem(self.dyn[0], jiny_dil, 3)
        self.chyba(self.korekce, self.dyn[0], self.dil_id, 5, kod="POSITION_OCCUPIED")
        self.assertEqual(self.obsah(self.dyn[0]), (jiny_dil, 3))

    def test_bez_rozdilu_a_spatne_zadani_se_nezapije(self):
        """Rozdíl 0 ks kontrakt ani schema nepouští – inventura volá korekci jen při rozdílu."""
        self.uskladni(self.stat[0], self.dil_id, 6)
        self.chyba(self.korekce, self.stat[0], self.dil_id, 6, kod="VALIDATION_ERROR")
        self.chyba(self.korekce, self.stat[0], self.dil_id, 5, typ_pohybu="VYDEJ", kod="VALIDATION_ERROR")
        self.chyba(self.korekce, self.stat[0], self.dil_id, -1, kod="VALIDATION_ERROR")
        self.chyba(sklad.zauctuj_korekci, self.spoj, self.kdo, 2_000_000_000, self.dil_id, 5, "KOREKCE",
                   kod="NOT_FOUND")
        self.assertEqual(self.obsah(self.stat[0]), (self.dil_id, 6))
        self.assertEqual(len(self.pohyby(self.stat[0])), 1)


class TestZpusobPotvrzeniCile(ZakladSkladu):
    """D-18: pohyb do cíle nese ověřený způsob potvrzení (SKEN/RUCNE), ostatní mají NULL."""

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(self.kdo.uzivatel_id, None, "ADMIN", frozenset({"RUCNI_POTVRZENI"}))
        self.dil_id, _ = self.dil()
        self.prirad_stat(self.dil_id, self.stat[0], minimalni_ks=0)

    def test_prijem_do_dyn_uklada_sken_i_rucni_potvrzeni(self):
        self.prijem(self.dyn[0], self.dil_id, 5)                                          # výchozí SKEN
        self.prijem(self.dyn[1], self.dil_id, 5, zpusob_potvrzeni="RUCNE")
        self.assertEqual([r["ZpusobPotvrzeni"] for r in self.pohyby(self.dyn[0], self.dyn[1])], ["SKEN", "RUCNE"])

    def test_potvrzeni_nese_cilovy_pohyb(self):
        self.prijem(self.dyn[0], self.dil_id, 6)
        self.uskladni(self.stat[0], self.dil_id, 6, zdroj_kod=self.dyn[0].kod, zpusob_potvrzeni="RUCNE")
        self.assertEqual([(r["KodPohybu"], r["ZpusobPotvrzeni"]) for r in self.pohyby(self.dyn[0], self.stat[0])],
                         [("PRIJEM", "SKEN"), ("PRESUN-OUT", None), ("PRESUN-IN", "RUCNE")])
        self.uskladni(self.stat[0], self.dil_id, 2)                                       # z výroby = PRIJEM
        self.prijem(self.dyn[1], self.dil_id, 4)
        self.presun(self.dyn[1], self.dyn[2], zpusob_potvrzeni="SKEN")
        self.assertEqual([(r["KodPohybu"], r["ZpusobPotvrzeni"]) for r in self.pohyby(self.stat[0])],
                         [("PRESUN-IN", "RUCNE"), ("PRIJEM", "SKEN")])
        self.assertEqual([(r["KodPohybu"], r["ZpusobPotvrzeni"]) for r in self.pohyby(self.dyn[2])],
                         [("PRESUN-IN", "SKEN")])

    def test_vydej_presun_out_a_korekce_maji_null(self):
        self.prijem(self.dyn[0], self.dil_id, 10)
        self.uskladni(self.stat[0], self.dil_id, 10)
        self.vydej(self.stat[0], 4)
        self.korekce(self.stat[0], self.dil_id, 3)
        self.assertEqual([(r["KodPohybu"], r["ZpusobPotvrzeni"]) for r in self.pohyby(self.stat[0])],
                         [("PRIJEM", "SKEN"), ("VYDEJ", None), ("KOREKCE", None)])


class TestOpakovanyRequest(ZakladIntegrace):
    """T14: stejný requestId dvakrát skutečnou službu s @transakce – jeden pohyb, stejná odpověď.

    Dekorátor si otevírá vlastní spojení a potvrzuje, proto jsou díl i box založené nastálo a
    v databázi zůstanou (stejně jako v provozu). Výsledek se ověřuje na druhém spojení, které
    potvrzená data vidí – spojení testu je uvnitř transakce, která je ještě nezačala.
    """

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(self.uzivatel_testu(), None, "ADMIN", frozenset())
        with spojeni_pro_skript() as spoj:
            self.cil = nova_struktura(spoj, self.kdo)["dyn"][0]
            self.dil_id, self.cislo = novy_dil(spoj, self.kdo)
        self.vstup = PrijemDynVstup(request_id=uuid.uuid4(), dil_id=self.dil_id, cil_kod=self.cil.kod, pocet_ks=5)

    def test_druhy_pozadavek_vrati_ulozeny_vysledek(self):
        prvni = sluzby.prijem_dyn(vstup=self.vstup, kdo=self.kdo)
        druhy = sluzby.prijem_dyn(vstup=self.vstup, kdo=self.kdo)
        self.assertEqual(druhy.model_dump(), prvni.model_dump())                  # stejné PohybID i data
        self.assertEqual(druhy.transakce_id, prvni.transakce_id)
        druhy_spojeni = self.druhe_spojeni()
        self.assertEqual([r["Mnozstvi"] for r in druhy_spojeni.dotaz(
            "SELECT Mnozstvi FROM dbo.SkladovyPohyb WHERE TransakceID = ?", prvni.transakce_id)], [5])
        self.assertEqual(len(druhy_spojeni.dotaz("SELECT PohybID FROM dbo.SkladovyPohyb"
                                                 " WHERE VnitrniPoziceID = ?", self.cil.vnitrni_pozice_id)), 1)
        self.assertEqual(sklad.obsah_mist(druhy_spojeni, [self.cil.vnitrni_pozice_id])[
            self.cil.vnitrni_pozice_id].pocet_ks, 5)

    def test_jiny_obsah_se_stejnym_request_idem(self):
        """Stejný requestId s jiným obsahem je jiný požadavek – služba ho odmítne a nic nezapíše."""
        sluzby.prijem_dyn(vstup=self.vstup, kdo=self.kdo)
        druhy_dil, _ = novy_dil(self.spoj, self.kdo)
        with self.assertRaises(AppError) as zachyceno:
            sluzby.prijem_dyn(vstup=PrijemDynVstup(request_id=self.vstup.request_id, dil_id=druhy_dil,
                                                   cil_kod=self.cil.kod, pocet_ks=5), kdo=self.kdo)
        self.assertEqual(zachyceno.exception.kod, "VALIDATION_ERROR")
        self.assertEqual(len(self.druhe_spojeni().dotaz("SELECT PohybID FROM dbo.SkladovyPohyb"
                                                        " WHERE VnitrniPoziceID = ?", self.cil.vnitrni_pozice_id)), 1)


class TestSoubeh(ZakladIntegrace):
    """T10 a T30: dvě skladové operace běžící naráz se seřadí na zámku pozic, žádný deadlock.

    Data musí být potvrzená, jinak je druhé spojení pod RCSI nevidí: strukturu i díly proto zakládá
    `spojeni_pro_skript()` a počáteční zásobu skutečná služba s dekorátorem – vše v databázi zůstává
    (stejně jako v provozu). Spojení testu si před startem vláken zamkne dotčená místa, takže obě
    operace stojí na stejném prvním zámku; `zamkni_mista` bere pozice vzestupně podle ID, takže se
    seřadí za sebe a nikdy na sebe nenarazí křížově. Rollback spojení testu je pustí.
    """

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(self.uzivatel_testu(), None, "ADMIN", frozenset())
        with spojeni_pro_skript() as spoj:
            self.dyn = nova_struktura(spoj, self.kdo)["dyn"]
            self.dil_1, _ = novy_dil(spoj, self.kdo)
            self.dil_2, _ = novy_dil(spoj, self.kdo)

    # --- příkazy --------------------------------------------------------------------------------

    @staticmethod
    def vstup_prijem(cil: struktura.MistoInfo, dil_id: int, pocet_ks: int) -> PrijemDynVstup:
        """Každé volání vlastní requestId, aby se obě vlákna netvařila jako dvojité odeslání (T14)."""
        return PrijemDynVstup(request_id=uuid.uuid4(), dil_id=dil_id, cil_kod=cil.kod, pocet_ks=pocet_ks)

    @staticmethod
    def vstup_presun(zdroj: struktura.MistoInfo, cil: struktura.MistoInfo) -> PresunVstup:
        return PresunVstup(request_id=uuid.uuid4(), zdroj_kod=zdroj.kod, cil_kod=cil.kod)

    def pust_vlakna(self, *prikazy: tuple[Callable[..., Any], Vstup]) -> list[Any]:
        """Každý příkaz (služba, vstup) ve vlastním vlákně a app contextu; výsledek, nebo AppError.

        Po půl sekundě obě vlákna čekají na zámek, který drží spojení testu (čekací limit
        `db_limit_zamku_ms` je 5 s); rollback spojení testu zámek uvolní a operace se seřadí za sebe.
        Jinou výjimku než `AppError` vypíše samo vlákno a test padne na chybějícím výsledku.
        """
        def volat(poradi: int, sluzba: Callable[..., Any], vstup: Vstup) -> None:
            with self.app.app_context():
                try:
                    vysledky[poradi] = sluzba(vstup=vstup, kdo=self.kdo)
                except AppError as chyba:
                    vysledky[poradi] = chyba

        vysledky: list[Any] = [None] * len(prikazy)
        vlakna = [threading.Thread(target=volat, args=(poradi, sluzba, vstup))
                  for poradi, (sluzba, vstup) in enumerate(prikazy)]
        for vlakno in vlakna:
            vlakno.start()
        time.sleep(0.5)              # obě vlákna už stojí na zámku
        self.spoj._rollback()        # uvolní zámky pozic, na kterých obě vlákna čekají
        for vlakno in vlakna:
            vlakno.join(timeout=20)
            self.assertFalse(vlakno.is_alive(), "Souběžná operace nedoběhla")
        return vysledky

    # --- zjištění stavu na druhém spojení (spojení testu potvrzená data nevidí) ---------------------

    @staticmethod
    def obsah(spoj: Spojeni, misto: struktura.MistoInfo) -> tuple[int, int] | None:
        """(dilId, počet ks) čtené rozhraním ostrova E; prázdná pozice je None."""
        obsah = sklad.obsah_mist(spoj, [misto.vnitrni_pozice_id]).get(misto.vnitrni_pozice_id)
        return (obsah.dil_id, obsah.pocet_ks) if obsah else None

    @staticmethod
    def pohyby(spoj: Spojeni, *mista: struktura.MistoInfo) -> list[dict]:
        """Historie pohybů na pozicích – pro jejich počet i součet množství (T32)."""
        znacky = ", ".join("?" for _ in mista)
        return spoj.dotaz(f"SELECT t.KodPohybu, p.VnitrniPoziceID, p.Mnozstvi FROM dbo.SkladovyPohyb AS p"
                          f" JOIN dbo.TypPohybu AS t ON t.TypPohybuID = p.TypPohybuID"
                          f" WHERE p.VnitrniPoziceID IN ({znacky}) ORDER BY p.PohybID",
                          *[m.vnitrni_pozice_id for m in mista])

    def test_prijem_do_stejne_pozice_naraz(self):
        """T10: dva příjmy do jedné volné DYN pozice – projde právě jeden, druhý POSITION_OCCUPIED."""
        cil = self.dyn[0]
        struktura.zamkni_mista(self.spoj, [cil.vnitrni_pozice_id])
        with self.assertNoLogs("houfek.transakce", level="WARNING"):     # žádný deadlock ani vypršení zámku
            vysledky = self.pust_vlakna((sluzby.prijem_dyn, self.vstup_prijem(cil, self.dil_1, 5)),
                                        (sluzby.prijem_dyn, self.vstup_prijem(cil, self.dil_2, 7)))

        self.assertEqual(sorted(v.kod if isinstance(v, AppError) else type(v).__name__ for v in vysledky),
                         ["POSITION_OCCUPIED", "SkladovyVysledek"])
        [uspesny] = [v for v in vysledky if isinstance(v, SkladovyVysledek)]
        druhe = self.druhe_spojeni()
        self.assertEqual(self.obsah(druhe, cil), (uspesny.dil_id, uspesny.pocet_ks))    # zvítězivší dávka
        self.assertEqual([(r["KodPohybu"], r["Mnozstvi"]) for r in self.pohyby(druhe, cil)],
                         [("PRIJEM", uspesny.pocet_ks)])                                # na pozici je jeden pohyb

    def test_presun_teziste_sem_a_zpet_naraz(self):
        """T30: přesun A → B a B → A naráz – oba skončí bezpečně, jako by proběhly za sebou."""
        a, b = self.dyn[:2]
        sluzby.prijem_dyn(vstup=self.vstup_prijem(a, self.dil_1, 7), kdo=self.kdo)      # zásoba na A
        struktura.zamkni_mista(self.spoj, [m.vnitrni_pozice_id for m in (a, b)])
        with self.assertNoLogs("houfek.transakce", level="WARNING"):
            dopredu, zpet = self.pust_vlakna((sluzby.presun, self.vstup_presun(a, b)),
                                             (sluzby.presun, self.vstup_presun(b, a)))

        # B → A skončí chybou jen tehdy, že začalo první (z prázdné B se nedalo brát); jinak už na B
        # dávka z přesunu A → B byla a oba přesuny proběhly za sebou
        if isinstance(zpet, AppError):
            self.assertEqual(zpet.kod, "INSUFFICIENT_STOCK")     # B → A šlo první a B byla prázdná
            self.assertIsInstance(dopredu, SkladovyVysledek)
            kde, ruchu_navic = b, 2                              # dávka zůstala na B
        else:
            self.assertIsInstance(dopredu, SkladovyVysledek)     # A → B první, B → A vrátilo dávku zpět
            self.assertIsInstance(zpet, SkladovyVysledek)
            kde, ruchu_navic = a, 4

        druhe = self.druhe_spojeni()
        radky = self.pohyby(druhe, a, b)
        self.assertEqual(len(radky), 1 + ruchu_navic, [r["KodPohybu"] for r in radky])   # 1 = příjem
        self.assertEqual({self.obsah(druhe, a), self.obsah(druhe, b)}, {(self.dil_1, 7), None})
        self.assertEqual(self.obsah(druhe, kde), (self.dil_1, 7))
        for misto in (a, b):                                      # T32: součet pohybů = obsah pozice
            hnuti = [r["Mnozstvi"] for r in radky if r["VnitrniPoziceID"] == misto.vnitrni_pozice_id]
            stav = self.obsah(druhe, misto)
            self.assertEqual(sum(hnuti), stav[1] if stav else 0, misto.kod)
