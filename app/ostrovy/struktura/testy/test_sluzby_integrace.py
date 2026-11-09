"""Integrační testy služeb ostrova C nad SQL Serverem: služby, audit a kontrola integrity.

Služby se volí `__wrapped__`, tedy bez dekorátoru – tělo běží ve spojení a transakci testu a na
konci se vrátí zpět (@transakce i @cteni si otevírají vlastní spojení a potvrzují, takže by data
z testu neviděla). Strukturu zakládá `ZakladStruktury` přes `rozhrani.py`, aby test ověřil i to,
jak služby navazují na zakládání z kroku 1.

Obsah (dbo.ObsahPozice) a statická přiřazení (dbo.StatickeUmisteniDilu) vlastní ostrov E, ten do
nich nesmí sahat – proto si je test vkládá SQL přímo: potřebuje je kvůli NOT_EMPTY a pravidlům
kontroly integrity, která na ně navazují. Zásoba se vkládá i s pohybem, aby seděla na historii
(kap. 10) a kontrola nic nenamítala. Díl nechává velikost prázdnou, aby kontrola velikosti
pozice nic nepřepočítávala.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.ostrovy.struktura import rozhrani as struktura
from app.ostrovy.struktura import sluzby
from app.ostrovy.struktura.kontrakty import (
    BlokaceVstup,
    NovaUrovenVstup,
    NovePracovisteVstup,
    NovyBoxVstup,
    NovyRegalVstup,
    PoradiBoxuVstup,
    PracovisteFiltr,
    PresunBoxuVstup,
    RegalyFiltr,
    RekonfiguraceVstup,
    RozmerC7Vstup,
    UrovneFiltr,
    VymenaBoxuVstup,
    ZmenaPracovisteVstup,
    ZmenaRegaluVstup,
    ZmenaUrovneVstup,
)
from app.ostrovy.struktura.testy.test_repozitar_integrace import NEEXISTUJE, ZakladStruktury
from app.platforma.chyby import AppError
from app.platforma.kontrakty import DuvodVstup
from app.platforma.typy import Kontext

DUVOD_ZMENY = "změna údaje"
DUVOD_PRESUN = "nové uspořádání"


class ZakladSluzeb(ZakladStruktury):
    """Zázemí: služby přes `__wrapped__`, technický uživatel pro AuditZmen, zásoba a přiřazení ostrova E."""

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(self.uzivatel_testu(), None, "ADMIN", frozenset())
        self.cleneni_id = {r["KodCleneni"]: r["CleneniBoxuID"]
                           for r in self.spoj.dotaz("SELECT CleneniBoxuID, KodCleneni FROM dbo.CleneniBoxu")}

    # --- služby ---------------------------------------------------------------

    def pracoviste(self, kod: str, nazev: str | None = None):
        return sluzby.zaloz_pracoviste.__wrapped__(
            self.spoj, NovePracovisteVstup(kod_pracoviste=kod, nazev=nazev), self.kdo)

    def regal(self, pracoviste_id: int, kod: str, nazev: str | None = None):
        return sluzby.zaloz_regal.__wrapped__(
            self.spoj, NovyRegalVstup(pracoviste_id=pracoviste_id, kod_regalu=kod, nazev=nazev), self.kdo)

    def uroven(self, regal_id: int, kod: str, plocha=(2400, 800)):
        return sluzby.zaloz_uroven.__wrapped__(self.spoj, NovaUrovenVstup(
            regal_id=regal_id, kod_urovne=kod, delka_plochy_mm=Decimal(plocha[0]),
            hloubka_plochy_mm=Decimal(plocha[1])), self.kdo)

    def box(self, uroven_id: int, cleneni: str = "C4", rozmer=(400, 360), **pole):
        """Box službou (kontrakt NovyBoxVstup); `pole` = poradi, typ_boxu, cislo_boxu, cleneni_id."""
        zaklad = dict(typ_boxu="DYN", cleneni_id=self.cleneni_id[cleneni],
                      delka_mm=Decimal(rozmer[0]), hloubka_mm=Decimal(rozmer[1]))
        return sluzby.zaloz_box.__wrapped__(self.spoj, uroven_id, NovyBoxVstup(**(zaklad | pole)), self.kdo)

    def vymena(self, box_id: int, cleneni: str = "C4", rozmer=(400, 360), **pole):
        zaklad = dict(typ_boxu="DYN", cleneni_id=self.cleneni_id[cleneni], duvod="prasklý box",
                      delka_mm=Decimal(rozmer[0]), hloubka_mm=Decimal(rozmer[1]))
        return sluzby.vymen_box.__wrapped__(self.spoj, box_id, VymenaBoxuVstup(**(zaklad | pole)), self.kdo)

    def presun(self, box_id: int, cil_uroven_id: int, duvod: str = DUVOD_PRESUN, **pole):
        return sluzby.presun_box.__wrapped__(
            self.spoj, box_id, PresunBoxuVstup(cil_uroven_id=cil_uroven_id, duvod=duvod, **pole), self.kdo)

    def poradi(self, box_id: int, nove_poradi: int, duvod: str = "u uličky"):
        return sluzby.zmen_poradi_boxu.__wrapped__(
            self.spoj, box_id, PoradiBoxuVstup(nove_poradi=nove_poradi, duvod=duvod), self.kdo)

    def rekonfigurace(self, box_id: int, cleneni: str = "C2", duvod: str = "menší díly",
                      cleneni_id: int | None = None):
        """`cleneni_id` se pošle i tak, jak v číselníku není – testuje NOT_FOUND na členění."""
        return sluzby.rekonfiguruj_box.__wrapped__(
            self.spoj, box_id,
            RekonfiguraceVstup(cleneni_id=self.cleneni_id[cleneni] if cleneni_id is None else cleneni_id,
                               duvod=duvod), self.kdo)

    def deaktivuj_box(self, box_id: int, duvod: str = "vyřazen"):
        return sluzby.deaktivuj_box.__wrapped__(self.spoj, box_id, DuvodVstup(duvod=duvod), self.kdo)

    def deaktivuj(self, funkce, objekt_id: int, duvod: str = "zrušeno"):
        """Deaktivace pracoviště, regálu nebo úrovně (všechny berou jen důvod)."""
        return funkce.__wrapped__(self.spoj, objekt_id, DuvodVstup(duvod=duvod), self.kdo)

    def zmen(self, model, funkce, objekt_id: int, duvod: str = DUVOD_ZMENY, **pole):
        """PATCH kmenového údaje; `pole` jsou názvy polí kontraktu, důvod se povinný vždy."""
        return funkce.__wrapped__(self.spoj, objekt_id, model(duvod=duvod, **pole), self.kdo)

    def blokuj(self, kod: str, blokovat: bool = True, duvod: str = "poškozený box"):
        return sluzby.blokuj.__wrapped__(
            self.spoj, BlokaceVstup(kod=kod, blokovat=blokovat, duvod=duvod, request_id=uuid.uuid4()), self.kdo)

    def rozmer_c7(self, vnitrni_pozice_id: int, delka, hloubka, duvod: str = "přepážka"):
        return sluzby.nastav_rozmer_c7.__wrapped__(
            self.spoj, vnitrni_pozice_id,
            RozmerC7Vstup(delka_mm=Decimal(str(delka)), hloubka_mm=Decimal(str(hloubka)), duvod=duvod), self.kdo)

    def detail(self, box_id: int):
        return sluzby.detail_boxu.__wrapped__(self.spoj, box_id)

    def detail_pozice(self, vnitrni_pozice_id: int):
        return sluzby.detail_vnitrni_pozice.__wrapped__(self.spoj, vnitrni_pozice_id)

    def boxy(self, uroven_id: int):
        return sluzby.boxy_urovne.__wrapped__(self.spoj, uroven_id).polozky

    def urovne(self, regal_id: int, **filtr):
        return sluzby.seznam_urovni.__wrapped__(self.spoj, UrovneFiltr(regal_id=regal_id, **filtr)).polozky

    def jine_pracoviste(self) -> tuple[int, str]:
        """Regál R01 s úrovní U01 na jiném pracovišti (Q-30); vrací (UrovenID, kód pracoviště)."""
        _, _, uroven_id, kod = self.nova_uroven()
        return uroven_id, kod

    # --- zásoba a přiřazení (data ostrova E, vkládá je test) ----------------------------------------

    def novy_dil(self) -> int:
        """Díl jen jako cizí klíč obsahu; velikost má prázdnou, aby kontrola velikosti nic nenamítla."""
        return self.spoj.vloz("INSERT INTO dbo.Dil (IdentifikacniCislo, NazevDilu) VALUES (?, N'Zkušební díl')",
                              "ZKU " + uuid.uuid4().hex[:10].upper())

    def vloz_obsah(self, box_id: int, v_pozici: int = 0, ks: int = 1) -> int:
        """Zásoba na pozici a k ní i pohyb, aby obsah seděl na historii (OBSAH_NESEDI_S_HISTORII)."""
        dil, misto = self.novy_dil(), self.ids_boxu(box_id)[v_pozici]
        self.spoj.proved("INSERT INTO dbo.ObsahPozice (VnitrniPoziceID, DilID, PocetKs) VALUES (?, ?, ?)",
                         misto, dil, ks)
        self.spoj.proved("INSERT INTO dbo.SkladovyPohyb (TypPohybuID, DilID, VnitrniPoziceID, Mnozstvi,"
                         " StavPred, StavPo, UzivatelID) SELECT TypPohybuID, ?, ?, ?, 0, ?, ?"
                         " FROM dbo.TypPohybu WHERE KodPohybu = 'POCAT-STAV'", dil, misto, ks, ks,
                         self.kdo.uzivatel_id)
        return misto

    def vloz_pristazeni(self, box_id: int, v_pozici: int = 0) -> int:
        misto = self.ids_boxu(box_id)[v_pozici]
        self.spoj.proved("INSERT INTO dbo.StatickeUmisteniDilu (DilID, VnitrniPoziceID, MinimalniPocetKs)"
                         " VALUES (?, ?, 0)", self.novy_dil(), misto)
        return misto

    def obsah(self, box_id: int) -> list[tuple[int, int]]:
        """(VnitrniPoziceID, ks) zásoby boxu, jak ji vidí pohled ostrova E."""
        return [(r["VnitrniPoziceID"], r["PocetKs"]) for r in
                self.spoj.dotaz("SELECT o.VnitrniPoziceID, o.PocetKs FROM dbo.v_ObsahPozice AS o"
                                " WHERE o.VnitrniPoziceID IN (SELECT VnitrniPoziceID FROM dbo.v_Misto"
                                " WHERE BoxID = ?) ORDER BY o.VnitrniPoziceID", box_id)]

    def pocet_pohybu(self, box_id: int) -> int:
        return self.spoj.hodnota("SELECT COUNT(*) FROM dbo.SkladovyPohyb WHERE VnitrniPoziceID IN"
                                 " (SELECT VnitrniPoziceID FROM dbo.VnitrniPoziceBoxu WHERE BoxID = ?)", box_id)

    # --- zjištění stavu -------------------------------------------------------

    def audity(self, objekt_id: int, typ_objektu: str) -> list[tuple]:
        """Řádky auditu objektu (Pole, stará, nová, poznámka); hodnoty jsou v AuditZmen vždy text."""
        return [tuple(r.values()) for r in self.spoj.dotaz(
            "SELECT Pole, StaraHodnota, NovaHodnota, Poznamka FROM dbo.AuditZmen"
            " WHERE TypObjektu = ? AND ObjektID = ? ORDER BY AuditID", typ_objektu, objekt_id)]

    def kod_pozice(self, vnitrni_pozice_id: int) -> str:
        return self.spoj.hodnota("SELECT KodPozice FROM dbo.v_Misto WHERE VnitrniPoziceID = ?",
                                 vnitrni_pozice_id)

    def chyby_pole(self, chyba: AppError) -> set[str]:
        return {c["pole"] for c in chyba.data["chyby"]}

    def chyba(self, funkce, *args, kod: str, **pole) -> AppError:
        with self.assertRaises(AppError) as zachyceno:
            funkce(*args, **pole)
        self.assertEqual(zachyceno.exception.kod, kod, zachyceno.exception)
        return zachyceno.exception


class TestCteni(ZakladSluzeb):
    """Bod 1: čtení struktury službami – pracoviště, regály, úrovně, boxy úrovně, detail, členění."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.druha_uroven_id = self.uroven(self.regal_id, "U02").uroven_id
        self.prvni = self.box(self.uroven_id)
        self.druhy = self.box(self.uroven_id)

    def test_seznamy(self):
        pracoviste = {p.kod_pracoviste: p for p in
                      sluzby.seznam_pracovist.__wrapped__(self.spoj, PracovisteFiltr(aktivni=None)).polozky}[self.kod]
        self.assertEqual((pracoviste.pracoviste_id, pracoviste.nazev, pracoviste.aktivni),
                         (self.pracoviste_id, None, True))
        regaly = sluzby.seznam_regalu.__wrapped__(self.spoj, RegalyFiltr(pracoviste_id=self.pracoviste_id)).polozky
        self.assertEqual([(r.regal_id, r.kod_regalu, r.kod, r.aktivni) for r in regaly],
                         [(self.regal_id, "R01", f"HOUFEK-{self.kod}-R01", True)])
        self.assertEqual([(u.kod_urovne, u.poradi, u.pocet_boxu) for u in self.urovne(self.regal_id)],
                         [("U02", 2, 0), ("U01", 1, 2)])                               # shora dolů (Poradi DESC)
        self.over_integrity(self.uroven_id, self.druha_uroven_id)

    def test_boxy_urovne_detail_boxu_a_pozice(self):
        self.assertEqual([(b.kod_boxu, b.poradi, b.kod_pozice_urovne, b.typ_boxu, b.kod_cleneni, b.blokovany)
                          for b in self.boxy(self.uroven_id)],
                         [(f"B{self.kod}001", 1, "P01", "DYN", "C4", False),
                          (f"B{self.kod}002", 2, "P02", "DYN", "C4", False)])
        box = self.detail(self.prvni.box_id)
        self.assertEqual((box.kod_boxu, box.full_box_klic, box.delka_mm, box.hloubka_mm, box.uroven_id,
                          box.kod_urovne, box.regal_id, box.kod_regalu, box.pracoviste_id, box.aktivni),
                         (f"B{self.kod}001", f"HOUFEK-{self.kod}-R01-U01-B{self.kod}001", Decimal(400),
                          Decimal(360), self.uroven_id, "U01", self.regal_id, "R01", self.pracoviste_id, True))
        self.assertEqual([(p.kod, p.velikost, p.poradi_v_boxu, p.blokovana) for p in box.pozice],
                         [(f"B{self.kod}001-{k}", "V3", i + 1, False) for i, k in enumerate(("G", "H", "CH", "I"))])
        misto = self.detail_pozice(self.ids_boxu(self.prvni.box_id)[2])
        self.assertEqual((misto.kod, misto.adresa, misto.velikost, misto.box_id, misto.uroven_id,
                          misto.kod_pracoviste, misto.blokovano, misto.rozmer_c7_delka_mm),
                         (f"B{self.kod}001-CH", f"HOUFEK-{self.kod}-R01-U01-B{self.kod}001-CH", "V3",
                          self.prvni.box_id, self.uroven_id, self.kod, False, None))

    def test_cleneni_a_not_found(self):
        cleneni = sluzby.seznam_cleneni.__wrapped__(self.spoj).polozky
        self.assertEqual([c.kod_cleneni for c in cleneni], ["C1", "C2", "C3", "C4", "C5", "C6", "C7"])
        self.assertEqual([p.dyn_kod for p in cleneni[3].pozice], ["G", "H", "CH", "I"])     # šablona (Q-06)
        self.assertEqual((cleneni[6].kod_cleneni, cleneni[6].pocet_pozic), ("C7", 1))
        for funkce, hlaska in [(sluzby.detail_boxu, "Box"), (sluzby.boxy_urovne, "Úroveň"),
                               (sluzby.detail_vnitrni_pozice, "Pozice")]:
            chyba = self.chyba(funkce.__wrapped__, self.spoj, NEEXISTUJE, kod="NOT_FOUND")
            self.assertIn(f"{hlaska} {NEEXISTUJE}", chyba.zprava, funkce.__name__)


class TestKmenovaData(ZakladSluzeb):
    """Body 2 a 5: pracoviště, regály, úrovně – založení, změna, deaktivace; audit jen změn a vyřazení."""

    def test_pracoviste_a_regal(self):
        kod = self.novy_kod_pracoviste()
        pracoviste = self.pracoviste(f" {kod.lower()} ", "Lisovna")
        self.assertEqual((pracoviste.kod_pracoviste, pracoviste.nazev, pracoviste.aktivni), (kod, "Lisovna", True))
        self.assertEqual(self.audity(pracoviste.pracoviste_id, "PRACOVISTE"), [])          # vznik se neaudituje
        self.assertEqual(self.zmen(ZmenaPracovisteVstup, sluzby.zmen_pracoviste,
                                   pracoviste.pracoviste_id, nazev="Lisovna I").nazev, "Lisovna I")
        self.assertEqual(self.audity(pracoviste.pracoviste_id, "PRACOVISTE"),
                         [("NazevPracoviste", "Lisovna", "Lisovna I", DUVOD_ZMENY)])
        druhy = self.regal(pracoviste.pracoviste_id, "r2", None)
        self.assertEqual((druhy.kod_regalu, druhy.kod, druhy.nazev), ("R02", f"HOUFEK-{kod}-R02", None))
        self.assertEqual(self.zmen(ZmenaRegaluVstup, sluzby.zmen_regal, druhy.regal_id, nazev="U lisu").nazev,
                         "U lisu")
        self.assertEqual(self.audity(druhy.regal_id, "REGAL"),
                         [("NazevRegalu", None, "U lisu", DUVOD_ZMENY)])         # regál vznikl bez názvu
        self.zmen(ZmenaRegaluVstup, sluzby.zmen_regal, druhy.regal_id, nazev="U lisu")
        self.assertEqual(len(self.audity(druhy.regal_id, "REGAL")), 1)          # stejná hodnota nic nezapíše
        self.assertEqual(self.chyba(self.regal, NEEXISTUJE, "R09", kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual(self.chyba(self.deaktivuj, sluzby.deaktivuj_pracoviste, pracoviste.pracoviste_id,
                                    kod="NOT_EMPTY").kod, "NOT_EMPTY")           # stojí na něm regál
        self.assertEqual(self.chyba(self.deaktivuj, sluzby.deaktivuj_regal, NEEXISTUJE,
                                    kod="NOT_FOUND").kod, "NOT_FOUND")

    def test_duplikat_se_znovu_nezalozi(self):
        """Chyby služby přebírá repozitář: už vydaný kód je ALREADY_EXISTS, cizí objekt NOT_FOUND."""
        kod_pracoviste = self.novy_kod_pracoviste()
        pracoviste = self.pracoviste(kod_pracoviste)
        regal = self.regal(pracoviste.pracoviste_id, "R01")
        self.uroven(regal.regal_id, "U01")
        self.assertEqual(self.chyba(self.pracoviste, kod_pracoviste, kod="ALREADY_EXISTS").kod, "ALREADY_EXISTS")
        self.assertEqual(self.chyba(self.regal, pracoviste.pracoviste_id, "r1", kod="ALREADY_EXISTS").kod,
                         "ALREADY_EXISTS")
        self.assertEqual(self.chyba(self.uroven, regal.regal_id, "u1", kod="ALREADY_EXISTS").kod, "ALREADY_EXISTS")
        self.assertEqual(self.chyba(self.uroven, NEEXISTUJE, "U05", kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Uroven WHERE RegalID = ?", regal.regal_id), 1)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Regal WHERE PracovisteID = ?",
                                           pracoviste.pracoviste_id), 1)

    def test_deaktivace_prazdne_struktury(self):
        """Vyřadit se dá jen prázdný objekt; audit Aktivni True → False s důvodem (kap. 25)."""
        pracoviste_id, regal_id, uroven_id, _ = self.nova_uroven()
        druhe_urovne_id = self.uroven(regal_id, "U02").uroven_id
        box_id = self.box(uroven_id).box_id
        self.assertEqual(self.chyba(self.deaktivuj, sluzby.deaktivuj_uroven, uroven_id,
                                    kod="NOT_EMPTY").kod, "NOT_EMPTY")           # na úrovni stojí box
        self.assertEqual(self.chyba(self.deaktivuj, sluzby.deaktivuj_regal, regal_id,
                                    kod="NOT_EMPTY").kod, "NOT_EMPTY")           # regál má aktivní úrovně
        self.assertEqual(self.audity(uroven_id, "UROVEN"), [])                   # chybová volání neauditovala
        self.deaktivuj_box(box_id)
        self.assertEqual(self.deaktivuj(sluzby.deaktivuj_uroven, uroven_id).aktivni, False)
        self.assertEqual(self.audity(uroven_id, "UROVEN"), [("Aktivni", "True", "False", "zrušeno")])
        self.assertEqual([u.kod_urovne for u in self.urovne(regal_id)], ["U02"])             # jen aktivní
        self.assertEqual([u.kod_urovne for u in self.urovne(regal_id, aktivni=None)], ["U02", "U01"])
        self.assertEqual([u.kod_urovne for u in self.urovne(regal_id, aktivni=False)], ["U01"])
        self.deaktivuj(sluzby.deaktivuj_uroven, druhe_urovne_id)
        self.assertEqual(self.deaktivuj(sluzby.deaktivuj_regal, regal_id).aktivni, False)
        self.assertEqual(self.audity(regal_id, "REGAL"), [("Aktivni", "True", "False", "zrušeno")])
        self.assertEqual(self.deaktivuj(sluzby.deaktivuj_pracoviste, pracoviste_id).aktivni, False)
        self.assertEqual(self.audity(pracoviste_id, "PRACOVISTE"), [("Aktivni", "True", "False", "zrušeno")])
        self.over_integrity(uroven_id, druhe_urovne_id)

    def test_zmena_urovne(self):
        """Rozměr plochy je jen informace (17.1): změní se a zapíše do auditu, nic se nepřepočítává."""
        _, regal_id, uroven_id, _ = self.nova_uroven()
        druha = self.uroven(regal_id, "U02")
        zmena = self.zmen(ZmenaUrovneVstup, sluzby.zmen_uroven, uroven_id, poradi=7)
        self.assertEqual((zmena.poradi, zmena.delka_plochy_mm, zmena.hloubka_plochy_mm),
                         (7, Decimal(2400), Decimal(800)))
        self.assertEqual(self.audity(uroven_id, "UROVEN"), [("Poradi", "1", "7", DUVOD_ZMENY)])
        self.assertEqual([(u.kod_urovne, u.poradi) for u in self.urovne(regal_id)],
                         [("U01", 7), ("U02", 2)])                                # stále Poradi DESC
        self.assertEqual(self.zmen(ZmenaUrovneVstup, sluzby.zmen_uroven, uroven_id,
                                   delka_plochy_mm=Decimal(1800)).delka_plochy_mm, Decimal(1800))
        self.assertEqual([r[0] for r in self.audity(uroven_id, "UROVEN")], ["Poradi", "DelkaPlochyMM"])
        self.assertEqual(self.chyba(self.zmen, ZmenaUrovneVstup, sluzby.zmen_uroven, NEEXISTUJE, poradi=1,
                                    kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual(self.box(druha.uroven_id).kod_pozice_urovne, "P01")
        self.over_integrity(uroven_id, druha.uroven_id)


class TestBlokace(ZakladSluzeb):
    """Bod 3: blokace celého boxu i jedné pozice, zámky jako sklad, audit Blokovany s důvodem."""

    def setUp(self) -> None:
        super().setUp()
        _, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.box_id = self.box(self.uroven_id).box_id
        self.kod_b = self.kod_boxu(self.box_id)
        self.ids = self.ids_boxu(self.box_id)

    def test_blokace_boxu(self):
        vysledek = self.blokuj(self.kod_b)
        self.assertEqual((vysledek.typ, vysledek.kod, vysledek.box_id, vysledek.vnitrni_pozice_id,
                          vysledek.blokovano, vysledek.zmeneno),
                         ("BOX", self.kod_b, self.box_id, None, True, True))
        self.assertEqual(self.spoj.hodnota("SELECT Blokovany FROM dbo.Box WHERE BoxID = ?", self.box_id), True)
        self.assertEqual(self.audity(self.box_id, "BOX"), [("Blokovany", "False", "True", "poškozený box")])
        self.assertEqual(self.detail(self.box_id).blokovany, True)
        self.assertEqual(self.detail_pozice(self.ids[0]).blokovano, True)     # blokace boxu platí i pro pozice
        druhy = self.blokuj(self.kod_b)
        self.assertEqual((druhy.zmeneno, [v.kod for v in druhy.varovani]), (False, ["BEZ_ZMENY"]))
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.AuditZmen WHERE TypObjektu = 'BOX'"
                                           " AND ObjektID = ?", self.box_id), 1)   # varování nic nepíše
        self.assertEqual(self.blokuj(self.kod_b, blokovat=False).blokovano, False)
        self.assertEqual(self.spoj.hodnota("SELECT Blokovany FROM dbo.Box WHERE BoxID = ?", self.box_id), False)
        self.assertEqual(len(self.audity(self.box_id, "BOX")), 2)                   # odblokování se zapíše
        self.over_integrity(self.uroven_id)

    def test_blokace_pozice(self):
        kod = f"{self.kod_b}-CH"
        vysledek = self.blokuj(f"HOUFEK-{self.kod}-R01-U01-{kod}")            # dlouhý štítek (Q-02)
        self.assertEqual((vysledek.typ, vysledek.kod, vysledek.box_id, vysledek.vnitrni_pozice_id, vysledek.zmeneno),
                         ("POZICE", kod, self.box_id, self.ids[2], True))
        self.assertEqual(self.audity(self.ids[2], "VNITRNI_POZICE_BOXU"),
                         [("Blokovany", "False", "True", "poškozený box")])
        self.assertEqual(self.detail(self.box_id).blokovany, False)            # box sám zůstává odblokovaný
        self.assertEqual([p.blokovana for p in self.detail(self.box_id).pozice], [False, False, True, False])
        self.assertEqual(self.blokuj(kod).zmeneno, False)
        self.assertEqual(self.blokuj(kod, blokovat=False).blokovano, False)
        self.over_integrity(self.uroven_id)

    def test_chyby(self):
        for kod, ocekavana in [(f"B{self.kod}999", "NOT_FOUND"),               # box neexistuje
                               (f"B{self.kod}999-G", "NOT_FOUND"),
                               (f"{self.kod_b}-K", "NOT_FOUND"),               # T13: K v členění C4 není
                               ("AAR10044", "INVALID_BARCODE"),                # není kód skladu
                               (f"HOUFEK-{self.kod}-R99-U01-{self.kod_b}", "INVALID_BARCODE"),
                               (f"HOUFEK-{self.kod}-R02-U01-{self.kod_b}", "INVALID_BARCODE"),
                               (f"HOUFEK-{self.kod}-R01", "VALIDATION_ERROR")]:  # regál se blokovat nedá
            self.assertEqual(self.chyba(self.blokuj, kod, kod=ocekavana).kod, ocekavana, kod)
        self.assertEqual(self.spoj.hodnota("SELECT Blokovany FROM dbo.Box WHERE BoxID = ?", self.box_id), False)
        self.assertEqual(self.audity(self.box_id, "BOX"), [])                    # chybová volání nic nezměnila
        self.over_integrity(self.uroven_id)


class TestZalozeniBoxu(ZakladSluzeb):
    """Bod 4: založení boxu službou – pořadí na úrovni, vnitřní pozice ze šablony, FullBoxKlic."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()

    def test_zalozeni_a_poradi(self):
        prvni = self.box(self.uroven_id)
        druhy = self.box(self.uroven_id)
        treti = self.box(self.uroven_id, poradi=1)
        self.assertEqual((treti.kod_boxu, treti.poradi, treti.kod_pozice_urovne, treti.full_box_klic),
                         (f"B{self.kod}003", 1, "P01", f"HOUFEK-{self.kod}-R01-U01-B{self.kod}003"))
        self.assertEqual([(b.kod_boxu, b.poradi) for b in self.boxy(self.uroven_id)],
                         [(treti.kod_boxu, 1), (prvni.kod_boxu, 2), (druhy.kod_boxu, 3)])
        self.assertEqual(self.prihradky(treti.box_id), self.ocekavane_prihradky("C4", "DYN", (400, 360)))
        self.assertEqual(self.audity(treti.box_id, "BOX"), [])                   # vznik boxu se neaudituje (kap. 25)
        c7 = self.box(self.uroven_id, cleneni="C7", rozmer=(900, 450))
        self.assertEqual([(p.kod_pozice, p.velikost, p.rozmer_c7_delka_mm, p.rozmer_c7_hloubka_mm)
                          for p in c7.pozice], [("R", "V6", Decimal(900), Decimal(450))])       # Q-01
        self.over_integrity(self.uroven_id)

    def test_chyby(self):
        self.box(self.uroven_id)
        for ocekavana, prekvapeni in [
            ("NOT_FOUND", dict(uroven_id=NEEXISTUJE)),
            ("NOT_FOUND", dict(cleneni_id=self.cleneni_id["C7"] + 10)),
            ("ALREADY_EXISTS", dict(cislo_boxu=1)),                          # číslo už vydané v řadě pracoviště
            ("VALIDATION_ERROR", dict(poradi=9)),                            # pořadí za koncem úrovně
        ]:
            parametry = {"uroven_id": self.uroven_id} | prekvapeni
            self.assertEqual(self.chyba(self.box, kod=ocekavana, **parametry).kod, ocekavana, prekvapeni)
        self.assertEqual(self.chyby_pole(self.chyba(self.box, self.uroven_id, poradi=9,
                                                    kod="VALIDATION_ERROR")), {"poradi"})
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Pozice WHERE UrovenID = ?", self.uroven_id), 1)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Box WHERE PoziceID IN"
                                           " (SELECT PoziceID FROM dbo.Pozice WHERE UrovenID = ?)", self.uroven_id), 1)
        self.over_integrity(self.uroven_id)


class TestVymenaBoxu(ZakladSluzeb):
    """Bod 4 a „Hotovo, když“ T22: nový box na stejné pozici, starý vyřazený a dohledatelný."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.za_radem = self.box(self.uroven_id)                # na 1. místě, vyměněný box se má zachovat
        self.stary = self.box(self.uroven_id)                   # na 2. místě, vyměňovaný

    def test_vymena_zachova_pozici_i_poradi(self):
        pred = {r["BoxID"]: r for r in self.pozice_urovne(self.uroven_id)}
        novy = self.vymena(self.stary.box_id, cleneni="C2")
        po = {r["BoxID"]: r for r in self.pozice_urovne(self.uroven_id)}
        self.assertEqual(novy.kod_boxu, f"B{self.kod}003")                      # nové číslo řady (11.2.1)
        self.assertEqual((novy.poradi, novy.kod_pozice_urovne, novy.uroven_id),
                         (pred[self.stary.box_id]["Poradi"], pred[self.stary.box_id]["KodPozice"], self.uroven_id))
        self.assertEqual(po[novy.box_id]["PoziceID"], pred[self.stary.box_id]["PoziceID"])   # stejná Pozice
        self.assertEqual(po[self.za_radem.box_id]["PoziceID"], pred[self.za_radem.box_id]["PoziceID"])
        self.assertEqual(self.prihradky(novy.box_id), self.ocekavane_prihradky("C2", "DYN", (400, 360)))
        stary = self.detail(self.stary.box_id)                                  # dohledat podle starého kódu
        self.assertEqual((stary.box_id, stary.kod_boxu, stary.aktivni, stary.pozice),
                         (self.stary.box_id, self.stary.kod_boxu, False, []))
        self.assertEqual([b.box_id for b in self.boxy(self.uroven_id)], [self.za_radem.box_id, novy.box_id])
        self.assertEqual(self.audity(self.stary.box_id, "BOX"), [("Aktivni", "True", "False", "prasklý box")])
        self.assertEqual(self.audity(novy.box_id, "BOX"), [])                   # nové číslo se nezakládá (kap. 25)
        self.over_integrity(self.uroven_id)

    def test_vymena_neni_pro_obsazeny_box(self):
        misto = self.vloz_obsah(self.stary.box_id, v_pozici=1)
        chyba = self.chyba(self.vymena, self.stary.box_id, kod="NOT_EMPTY")
        self.assertIn(f"zásoba na {self.kod_boxu(self.stary.box_id)}-H", chyba.zprava)
        self.assertEqual(self.detail(self.stary.box_id).aktivni, True)
        self.assertEqual([r["BoxID"] for r in self.pozice_urovne(self.uroven_id)],
                         [self.za_radem.box_id, self.stary.box_id])              # žádný nový box nevznikl
        self.assertEqual(self.ids_boxu(self.stary.box_id)[1], misto)             # nic se nezapsalo
        self.assertEqual(self.audity(self.stary.box_id, "BOX"), [])
        self.over_integrity(self.uroven_id)

    def test_vymena_neni_pro_box_s_prirazenim(self):
        """Q-27 (čeká na potvrzení): ani STAT box s přiřazením se měnit nedá – dokud se přiřazení neukončí."""
        stat = self.box(self.uroven_id, typ_boxu="STAT")
        misto = self.vloz_pristazeni(stat.box_id)
        chyba = self.chyba(self.vymena, stat.box_id, typ_boxu="STAT", kod="NOT_EMPTY")
        self.assertIn(f"statické přiřazení na {self.kod_boxu(stat.box_id)}-{self.kod_pozice(misto)}", chyba.zprava)
        self.assertEqual(self.detail(stat.box_id).aktivni, True)
        self.over_integrity(self.uroven_id)


class TestPresunBoxu(ZakladSluzeb):
    """Bod 4: přesun i s obsahem bez skladového pohybu, přepočet FullBoxKlic, kódy pozic sedí (Q-02)."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.cil_id = self.uroven(self.regal_id, "U02").uroven_id
        self.cizina_id, self.kod_cizi = self.jine_pracoviste()
        self.presunovany = self.box(self.uroven_id)
        self.zustava = self.box(self.uroven_id)
        self.na_cili = self.box(self.cil_id)

    def test_presun_prepocita_adresu_a_necha_obsah(self):
        misto = self.vloz_obsah(self.presunovany.box_id)
        obsah_pred = self.obsah(self.presunovany.box_id)
        pohyby_pred = self.pocet_pohybu(self.presunovany.box_id)
        kody_pred = [(p.kod, p.vnitrni_pozice_id) for p in self.detail(self.presunovany.box_id).pozice]
        adresa_pred = self.detail(self.presunovany.box_id).full_box_klic
        stara_pozice = self.spoj.hodnota("SELECT PoziceID FROM dbo.Box WHERE BoxID = ?", self.presunovany.box_id)

        box = self.presun(self.presunovany.box_id, self.cil_id, poradi=1)

        self.assertEqual(box.full_box_klic, f"HOUFEK-{self.kod}-R01-U02-{box.kod_boxu}")   # Q-03
        self.assertEqual((box.uroven_id, box.kod_urovne, box.poradi, box.kod_pozice_urovne),
                         (self.cil_id, "U02", 1, "P01"))
        self.assertEqual([(p.kod, p.vnitrni_pozice_id) for p in box.pozice], kody_pred)     # Q-02: štítky sedí
        self.assertEqual(self.obsah(self.presunovany.box_id), obsah_pred)                   # obsah na pozicích
        self.assertEqual(self.pocet_pohybu(self.presunovany.box_id), pohyby_pred)           # žádný skladový pohyb
        self.assertEqual(self.spoj.hodnota("SELECT PocetKs FROM dbo.v_ObsahPozice WHERE VnitrniPoziceID = ?",
                                           misto), 1)
        self.assertEqual(self.audity(self.presunovany.box_id, "BOX"),
                         [("FullBoxKlic", adresa_pred, box.full_box_klic, DUVOD_PRESUN)])
        self.assertEqual([(b.kod_boxu, b.poradi) for b in self.boxy(self.cil_id)],
                         [(box.kod_boxu, 1), (self.na_cili.kod_boxu, 2)])
        self.assertEqual([(b.kod_boxu, b.poradi, b.kod_pozice_urovne) for b in self.boxy(self.uroven_id)],
                         [(self.zustava.kod_boxu, 1, "P01")])                               # vlevo se přečíslilo
        nova_pozice = self.spoj.hodnota("SELECT PoziceID FROM dbo.Box WHERE BoxID = ?", self.presunovany.box_id)
        self.assertNotEqual(nova_pozice, stara_pozice)
        self.assertEqual(self.spoj.hodnota("SELECT Aktivni FROM dbo.Pozice WHERE PoziceID = ?", nova_pozice), True)
        self.assertEqual(self.spoj.hodnota("SELECT Aktivni FROM dbo.Pozice WHERE PoziceID = ?", stara_pozice),
                         False)                                        # bez toho by byl nález POZICE_BEZ_BOXU
        self.over_integrity(self.uroven_id, self.cil_id)

    def test_presun_stat_boxu_mimo_pracoviste(self):
        """Q-30 (čeká na potvrzení): STAT box nemá v kódu pracoviště, takže smí stát kdekoli; DYN box nesmí."""
        stat = self.box(self.uroven_id, typ_boxu="STAT")
        self.assertEqual(self.presun(stat.box_id, self.cizina_id).full_box_klic,
                         f"HOUFEK-{self.kod_cizi}-R01-U01-{stat.kod_boxu}")
        self.assertEqual(self.detail(stat.box_id).kod_pracoviste, self.kod_cizi)
        for _ in range(2):                          # DYN box patří pracovišti ve svém kódu
            self.assertEqual(self.chyby_pole(self.chyba(self.presun, self.presunovany.box_id, self.cizina_id,
                                                        kod="VALIDATION_ERROR")), {"cilUrovenId"})
        self.over_integrity(self.uroven_id, self.cizina_id)

    def test_presun_chyby(self):
        for _ in range(2):                          # stejná úroveň = jiné volání (T23)
            self.assertEqual(self.chyby_pole(self.chyba(self.presun, self.presunovany.box_id, self.uroven_id,
                                                        kod="VALIDATION_ERROR")), {"cilUrovenId"})
        for cil, ocekavana in [(NEEXISTUJE, "NOT_FOUND"), (self.cil_id, "VALIDATION_ERROR")]:
            self.assertEqual(self.chyba(self.presun, self.presunovany.box_id, cil, poradi=9,
                                        kod=ocekavana).kod, ocekavana, cil)
        self.assertEqual(self.chyba(self.presun, NEEXISTUJE, self.cil_id, kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual([(b.kod_boxu, b.poradi) for b in self.boxy(self.uroven_id)],
                         [(self.presunovany.kod_boxu, 1), (self.zustava.kod_boxu, 2)])
        self.assertEqual([b.poradi for b in self.boxy(self.cil_id)], [1])       # chybová volání nic neposunula
        self.assertEqual(self.audity(self.presunovany.box_id, "BOX"), [])
        self.over_integrity(self.uroven_id, self.cil_id)


class TestPoradiBoxu(ZakladSluzeb):
    """Bod 4 a „Hotovo, když“ T23: služba přečísluje pořadí a rozložení úrovně vrací boxy v novém pořadí."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.prvni, self.druhy, self.treti = [self.box(self.uroven_id).box_id for _ in range(3)]

    def test_prevedeni_do_jineho_poradi(self):
        pred = {r["BoxID"]: r["PoziceID"] for r in self.pozice_urovne(self.uroven_id)}
        vracene = self.poradi(self.treti, 1).polozky
        self.assertEqual([(b.box_id, b.poradi, b.kod_pozice_urovne) for b in vracene],
                         [(self.treti, 1, "P01"), (self.prvni, 2, "P02"), (self.druhy, 3, "P03")])
        self.assertEqual([b.kod_boxu for b in vracene], [b.kod_boxu for b in self.boxy(self.uroven_id)])
        self.assertEqual([b.kod_boxu for b in struktura.rozlozeni_urovne(self.spoj, self.uroven_id).boxy],
                         [b.kod_boxu for b in vracene])                       # SVG vidí stejné pořadí (17.1)
        po = {r["BoxID"]: r for r in self.pozice_urovne(self.uroven_id)}
        self.assertEqual([po[b]["PoziceID"] for b in (self.prvni, self.druhy, self.treti)],
                         [pred[b] for b in (self.prvni, self.druhy, self.treti)])   # PoziceID zůstávají
        self.assertEqual([po[b]["Poradi"] for b in (self.prvni, self.druhy, self.treti)], [2, 3, 1])
        self.assertEqual(self.audity(self.treti, "BOX"), [("Poradi", "3", "1", "u uličky")])
        self.assertEqual([b.box_id for b in self.poradi(self.druhy, 2).polozky],
                         [self.treti, self.druhy, self.prvni])
        self.over_integrity(self.uroven_id)

    def test_poradi_mimo_uroven(self):
        self.assertEqual(self.chyby_pole(self.chyba(self.poradi, self.prvni, 9, kod="VALIDATION_ERROR")),
                         {"novePoradi"})
        self.assertEqual(self.chyba(self.poradi, NEEXISTUJE, 1, kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual([b.poradi for b in self.boxy(self.uroven_id)], [1, 2, 3])   # nic se neposunulo
        self.assertEqual(self.audity(self.prvni, "BOX"), [])
        self.over_integrity(self.uroven_id)


class TestRekonfiguraceBoxu(ZakladSluzeb):
    """Bod 4 a Q-27: nové členění jen u prázdného boxu bez přiřazení; staré pozice zůstávají v historii."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.box_id = self.box(self.uroven_id).box_id
        self.ids = self.ids_boxu(self.box_id)

    def test_rekonfigurace_na_jine_cleneni(self):
        box = self.rekonfigurace(self.box_id, "C2")
        self.assertEqual((box.kod_boxu, box.kod_cleneni, box.cleneni_id, box.aktivni),
                         (self.kod_boxu(self.box_id), "C2", self.cleneni_id["C2"], True))
        self.assertEqual(self.prihradky(self.box_id), self.ocekavane_prihradky("C2", "DYN", (400, 360)))
        self.assertEqual([p.kod_pozice for p in box.pozice], [p[0] for p in self.prihradky(self.box_id)])
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.VnitrniPoziceBoxu WHERE BoxID = ?"
                                           " AND Aktivni = 0", self.box_id), len(self.ids))  # historie zůstává
        self.assertEqual(self.audity(self.box_id, "BOX"),
                         [("CleneniBoxuID", str(self.cleneni_id["C4"]), str(self.cleneni_id["C2"]), "menší díly")])
        self.over_integrity(self.uroven_id)

    def test_rekonfigurace_na_c7_dostane_rozmer_boxu(self):
        """Q-01: nová variabilní pozice dostane rozměr boxu; upravení je až na POST /rozmer-c7."""
        box = self.rekonfigurace(self.box_id, "C7")
        self.assertEqual([(p.kod_pozice, p.velikost, p.rozmer_c7_delka_mm, p.rozmer_c7_hloubka_mm)
                          for p in box.pozice], [("R", "V6", Decimal(400), Decimal(360))])
        self.over_integrity(self.uroven_id)

    def test_rekonfigurace_neni_pro_obsazeny_box(self):
        """Q-27 (čeká na potvrzení): rekonfigurace se dělá jen u boxu bez zásoby a bez přiřazení."""
        self.vloz_obsah(self.box_id, v_pozici=2)
        chyba = self.chyba(self.rekonfigurace, self.box_id, "C2", kod="NOT_EMPTY")
        self.assertIn(f"zásoba na {self.kod_boxu(self.box_id)}-CH", chyba.zprava)
        self.assertEqual([p.kod_pozice for p in self.detail(self.box_id).pozice], ["G", "H", "CH", "I"])
        self.assertEqual(self.audity(self.box_id, "BOX"), [])
        self.over_integrity(self.uroven_id)

    def test_rekonfigurace_neni_pro_box_s_prirazenim(self):
        stat = self.box(self.uroven_id, typ_boxu="STAT")
        mista = [self.vloz_pristazeni(stat.box_id, 0), self.vloz_pristazeni(stat.box_id, 1)]
        chyba = self.chyba(self.rekonfigurace, stat.box_id, "C1", kod="NOT_EMPTY")
        for misto in mista:
            self.assertIn(f"{self.kod_boxu(stat.box_id)}-{self.kod_pozice(misto)}", chyba.zprava)
        self.assertEqual(self.spoj.hodnota("SELECT CleneniBoxuID FROM dbo.Box WHERE BoxID = ?", stat.box_id),
                         self.cleneni_id["C4"])
        self.over_integrity(self.uroven_id)

    def test_rekonfigurace_stejne_cleneni(self):
        self.assertEqual(self.chyby_pole(self.chyba(self.rekonfigurace, self.box_id, "C4",
                                                    kod="VALIDATION_ERROR")), {"cleneniId"})
        self.assertEqual(self.chyba(self.rekonfigurace, self.box_id, cleneni_id=self.cleneni_id["C7"] + 10,
                                    kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual(self.chyba(self.rekonfigurace, NEEXISTUJE, "C2", kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual([p.kod_pozice for p in self.detail(self.box_id).pozice], ["G", "H", "CH", "I"])
        self.assertEqual(self.audity(self.box_id, "BOX"), [])
        self.over_integrity(self.uroven_id)


class TestDeaktivaceBoxu(ZakladSluzeb):
    """Bod 4 a 5: vyprázdněný box i s jeho pozicí; box s obsahem nebo přiřazením jde vyřadit až NOT_EMPTY."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.prostredni = self.box(self.uroven_id)
        self.vpravo = self.box(self.uroven_id)
        self.vlevo = self.box(self.uroven_id, poradi=1)

    def test_deaktivace_posune_boxy_doleva(self):
        box = self.deaktivuj_box(self.prostredni.box_id, duvod="opotrebovaný")
        self.assertEqual((box.box_id, box.kod_boxu, box.aktivni, box.pozice),
                         (self.prostredni.box_id, self.kod_boxu(self.prostredni.box_id), False, []))
        self.assertEqual([(b.kod_boxu, b.poradi, b.kod_pozice_urovne) for b in self.boxy(self.uroven_id)],
                         [(self.vlevo.kod_boxu, 1, "P01"), (self.vpravo.kod_boxu, 2, "P02")])
        pozice = self.spoj.jeden("SELECT po.Aktivni, po.Poradi FROM dbo.Box AS b JOIN dbo.Pozice AS po"
                                 " ON po.PoziceID = b.PoziceID WHERE b.BoxID = ?", self.prostredni.box_id)
        self.assertEqual((pozice["Aktivni"], pozice["Poradi"]), (False, 2))   # bez toho by byl nález POZICE_BEZ_BOXU
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.v_Misto WHERE BoxID = ?",
                                           self.prostredni.box_id), 0)
        self.assertEqual(self.audity(self.prostredni.box_id, "BOX"),
                         [("Aktivni", "True", "False", "opotrebovaný")])
        self.over_integrity(self.uroven_id)

    def test_deaktivace_neni_pro_obsazeny_box(self):
        self.vloz_obsah(self.vpravo.box_id)
        chyba = self.chyba(self.deaktivuj_box, self.vpravo.box_id, kod="NOT_EMPTY")
        self.assertIn(f"zásoba na {self.kod_boxu(self.vpravo.box_id)}-", chyba.zprava)
        self.assertEqual(self.detail(self.vpravo.box_id).aktivni, True)
        self.assertEqual([b.poradi for b in self.boxy(self.uroven_id)], [1, 2, 3])
        self.assertEqual(self.audity(self.vpravo.box_id, "BOX"), [])
        self.over_integrity(self.uroven_id)

    def test_deaktivace_neni_pro_box_s_prirazenim(self):
        stat = self.box(self.uroven_id, typ_boxu="STAT")
        misto = self.vloz_pristazeni(stat.box_id)
        chyba = self.chyba(self.deaktivuj_box, stat.box_id, kod="NOT_EMPTY")
        self.assertIn(f"statické přiřazení na {self.kod_boxu(stat.box_id)}-{self.kod_pozice(misto)}", chyba.zprava)
        self.assertEqual(self.detail(stat.box_id).aktivni, True)
        self.over_integrity(self.uroven_id)


class TestRozmerC7(ZakladSluzeb):
    """Bod 4: rozměr variabilní pozice C7 (Q-01) – jen u V6, vejde se do boxu a jen u prázdné pozice."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.box_id = self.box(self.uroven_id, cleneni="C7", rozmer=(900, 450)).box_id
        self.misto = self.ids_boxu(self.box_id)[0]

    def test_nastaveni_rozmeru(self):
        pozice = self.rozmer_c7(self.misto, 800, "400.5")
        self.assertEqual((pozice.kod, pozice.velikost, pozice.rozmer_c7_delka_mm, pozice.rozmer_c7_hloubka_mm),
                         (f"{self.kod_boxu(self.box_id)}-R", "V6", Decimal(800), Decimal("400.5")))
        self.assertEqual(self.detail(self.box_id).pozice[0].rozmer_c7_hloubka_mm, Decimal("400.5"))
        self.assertEqual(self.prihradky(self.box_id)[0][3:], (Decimal(800), Decimal("400.5")))
        audity = self.audity(self.misto, "VNITRNI_POZICE_BOXU")
        self.assertEqual([(r[0], r[3]) for r in audity], [("DelkaMM", "přepážka"), ("HloubkaMM", "přepážka")])
        self.assertEqual([Decimal(r[1]) for r in audity], [Decimal(900), Decimal(450)])
        self.assertEqual([Decimal(r[2]) for r in audity], [Decimal(800), Decimal("400.5")])
        self.over_integrity(self.uroven_id)

    def test_rozmer_se_wejde_do_boxu(self):
        chyba = self.chyba(self.rozmer_c7, self.misto, 1200, 450, kod="VALIDATION_ERROR")
        self.assertEqual(self.chyby_pole(chyba), {"delkaMm"})
        self.assertIn("900", chyba.data["chyby"][0]["zprava"])                # mez je délka boxu (Q-01)
        self.assertEqual(self.detail_pozice(self.misto).rozmer_c7_delka_mm, Decimal(900))
        self.assertEqual(self.audity(self.misto, "VNITRNI_POZICE_BOXU"), [])
        self.over_integrity(self.uroven_id)

    def test_chyby(self):
        jine = self.box(self.uroven_id)                        # C4 – žádná variabilní pozice
        nepovoleny = self.ids_boxu(jine.box_id)[0]
        chyba = self.chyba(self.rozmer_c7, nepovoleny, 100, 100, kod="VALIDATION_ERROR")
        self.assertIsNone(chyba.data)                          # pravidlo se nevztahuje na konkrétní pole
        self.assertIn("C7", chyba.zprava)
        self.vloz_obsah(self.box_id)
        self.assertEqual(self.chyba(self.rozmer_c7, self.misto, 800, 400, kod="NOT_EMPTY").kod, "NOT_EMPTY")
        self.assertEqual(self.chyba(self.rozmer_c7, NEEXISTUJE, 100, 100, kod="NOT_FOUND").kod, "NOT_FOUND")
        self.assertEqual(self.detail_pozice(self.misto).rozmer_c7_delka_mm, Decimal(900))
        self.assertEqual(self.audity(self.misto, "VNITRNI_POZICE_BOXU"), [])
        self.over_integrity(self.uroven_id)
