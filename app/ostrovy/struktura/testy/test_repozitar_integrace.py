"""Integrační testy repozitáře ostrova C proti SQL Serveru (docs/adr/0009, vrstva 3).

Zakládání se testuje přes `rozhrani.py` – to je to, co volají ostatní ostrovy. Čtecí funkce se
testují přímo na `repozitar.py`, protože funkce rozhraní vracejí po celou fázi 1 vzorová data
(docs/vyvoj.md 3.4) a přes rozhraní by nad databází nic neověříme.

Data si test zakládá vlastní a s unikátními kódy: v testovací databázi zůstávají potvrzená data
z předchozích běhů i data ostatních ostrovů (tests/integrace/zaklad.py), proto nic netvrdíme
o počtech řádků obecně a kontrolu integrity vyhodnocujeme jen pro nálezy, které se týkají testu.
"""
from __future__ import annotations

import unittest
import uuid
from decimal import Decimal

from app.ostrovy.struktura import domena, repozitar, ukazky
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.typy import Kontext
from tests.integrace.zaklad import ZakladIntegrace

NEEXISTUJE = 2_000_000_000


class ZakladStruktury(ZakladIntegrace):
    """Strukturu si test zakládá přes rozhraní (stejně jako to udělá ostrov H při migraci).

    `kdo` rozhraní nikde nepoužívá – transakci otevírá volající (self.spoj) a audit doplní služba.
    """

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(1, None, "TEST", frozenset())

    # --- zakládání ---------------------------------------------------------------

    def novy_kod_pracoviste(self) -> str:
        """Unikátní kód pracoviště (T + 2 hex znaky) – kódy z předchozích běhů v databázi zůstávají."""
        while True:
            kod = "T" + uuid.uuid4().hex[:2].upper()
            if not self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Pracoviste WHERE KodPracoviste = ?", kod):
                return kod

    def nova_uroven(self, kod_urovne: str = "U01") -> tuple[int, int, int, str]:
        """Pracoviště + regál R01 + úroveň; vrací (PracovisteID, RegalID, UrovenID, KodPracoviste)."""
        kod_pracoviste = self.novy_kod_pracoviste()
        pracoviste_id = struktura.zaloz_pracoviste(self.spoj, self.kdo, kod_pracoviste, None)
        regal_id = struktura.zaloz_regal(self.spoj, self.kdo, pracoviste_id, "R01", None)
        uroven_id = struktura.zaloz_uroven(self.spoj, self.kdo, regal_id, kod_urovne,
                                           domena.poradi_z_kodu_urovne(kod_urovne), 2400, 800)
        return pracoviste_id, regal_id, uroven_id, kod_pracoviste

    def zaloz(self, uroven_id: int, poradi: int | None = None, typ_boxu: str = "DYN", cleneni: str = "C4",
              kod_boxu: str | None = None, rozmer: tuple[int, int] = (400, 360)) -> int:
        return struktura.zaloz_box(self.spoj, self.kdo, uroven_id, poradi, typ_boxu, cleneni,
                                   Decimal(rozmer[0]), Decimal(rozmer[1]), kod_boxu)

    def vyraz(self, box_id: int) -> None:
        """Vyřazení boxu jako v provozu: box i jeho pozice na úrovni přestanou být aktivní."""
        self.spoj.proved("UPDATE dbo.Pozice SET Aktivni = 0 WHERE PoziceID ="
                         " (SELECT PoziceID FROM dbo.Box WHERE BoxID = ?)", box_id)
        self.spoj.proved("UPDATE dbo.Box SET Aktivni = 0 WHERE BoxID = ?", box_id)

    # --- zjištění stavu ----------------------------------------------------------

    def pozice_urovne(self, uroven_id: int) -> list[dict]:
        """Boxy na úrovni v pořadí zleva doprava (Pozice.Poradi)."""
        return self.spoj.dotaz("SELECT po.PoziceID, po.Poradi, po.KodPozice, b.BoxID FROM dbo.Pozice AS po"
                               " JOIN dbo.Box AS b ON b.PoziceID = po.PoziceID"
                               " WHERE po.UrovenID = ? AND po.Aktivni = 1 AND b.Aktivni = 1 ORDER BY po.Poradi",
                               uroven_id)

    def prihradky(self, box_id: int) -> list[tuple]:
        """(kód, velikost, pořadí v boxu, rozměr C7) z pohledu v_Misto, tak jak je uložené."""
        return [(r["KodPozice"], r["Velikost"], r["PoradiVBoxu"], r["RozmerC7DelkaMM"], r["RozmerC7HloubkaMM"])
                for r in self.spoj.dotaz("SELECT KodPozice, Velikost, PoradiVBoxu, RozmerC7DelkaMM,"
                                         " RozmerC7HloubkaMM FROM dbo.v_Misto WHERE BoxID = ?"
                                         " ORDER BY PoradiVBoxu", box_id)]

    def ocekavane_prihradky(self, cleneni: str, typ_boxu: str, rozmer: tuple[int, int]) -> list[tuple]:
        """Očekávání ze šablony členění (shodu vzoru s výchozími daty migrace 001 hlídá test_domena)."""
        return [(p.dyn_kod if typ_boxu == "DYN" else p.stat_kod, p.velikost, p.poradi,
                 Decimal(rozmer[0]) if p.velikost == domena.VELIKOST_C7 else None,
                 Decimal(rozmer[1]) if p.velikost == domena.VELIKOST_C7 else None)
                for p in sorted(ukazky.PRIHRADKY[cleneni], key=lambda p: p.poradi)]

    def ids_boxu(self, box_id: int) -> list[int]:
        return [r["VnitrniPoziceID"] for r in self.spoj.dotaz(
            "SELECT VnitrniPoziceID FROM dbo.v_Misto WHERE BoxID = ? ORDER BY PoradiVBoxu", box_id)]

    def kod_boxu(self, box_id: int) -> str:
        return self.spoj.hodnota("SELECT KodBoxu FROM dbo.Box WHERE BoxID = ?", box_id)

    def over_integrity(self, *urovne_ids: int) -> None:
        """v_KontrolaIntegrity nesmí po založení hlásit nic – i uvnitř nezapsané transakce.

        Z celého pohledu vyhodnocujeme nálezy, které se jmenují náš box nebo naši úroveň:
        o datech, která test nezaložil, tvrdit nic nechceme (sdílená testovací databáze).
        """
        znacky = ", ".join("?" for _ in urovne_ids)
        kody = [r["KodBoxu"] for r in self.spoj.dotaz(
            f"SELECT b.KodBoxu FROM dbo.Box AS b JOIN dbo.Pozice AS po ON po.PoziceID = b.PoziceID"
            f" WHERE po.UrovenID IN ({znacky})", *urovne_ids)]
        nalezy = self.spoj.dotaz("SELECT Kontrola, Popis FROM dbo.v_KontrolaIntegrity")
        vlastni = [n for n in nalezy if any(k in n["Popis"] for k in kody)
                   or any(f"(UrovenID {u})" in n["Popis"] for u in urovne_ids)]
        self.assertEqual(vlastni, [])

    def kod_chyby(self, funkce, *parametry, **pravem) -> str:
        try:
            funkce(*parametry, **pravem)
        except AppError as chyba:
            return chyba.kod
        raise AssertionError("čekala se AppError")


class TestZalozeniStruktury(ZakladStruktury):
    def test_pracoviste_normalizuje_kod_a_odlasi_duplicitu(self):
        kod = self.novy_kod_pracoviste()
        pracoviste_id = struktura.zaloz_pracoviste(self.spoj, self.kdo, f" {kod.lower()} ", "Dílna")
        radek = self.spoj.jeden("SELECT KodPracoviste, NazevPracoviste, FirmaID FROM dbo.Pracoviste"
                                " WHERE PracovisteID = ?", pracoviste_id)
        self.assertEqual((radek["KodPracoviste"], radek["NazevPracoviste"]), (kod, "Dílna"))
        self.assertEqual(radek["FirmaID"], self.spoj.hodnota("SELECT FirmaID FROM dbo.Firma"
                                                             " WHERE KodFirmy = 'HOUFEK'"))
        self.assertEqual(self.kod_chyby(struktura.zaloz_pracoviste, self.spoj, self.kdo, kod.lower(), None),
                         "ALREADY_EXISTS")
        self.assertEqual(self.kod_chyby(struktura.zaloz_pracoviste, self.spoj, self.kdo, "PLE", None),
                         "ALREADY_EXISTS")                                      # seed migrace 001
        self.assertEqual(self.kod_chyby(struktura.zaloz_pracoviste, self.spoj, self.kdo, "PLÉ", None),
                         "VALIDATION_ERROR")

    def test_regal_a_uroven(self):
        pracoviste_id, regal_id, _, _ = self.nova_uroven()
        druhy_regal = struktura.zaloz_regal(self.spoj, self.kdo, pracoviste_id, "r2", "Regál 2")
        self.assertEqual(self.spoj.hodnota("SELECT KodRegalu FROM dbo.Regal WHERE RegalID = ?", druhy_regal), "R02")
        uroven_id = struktura.zaloz_uroven(self.spoj, self.kdo, druhy_regal, "u7", 7, 1800, 600)
        uroven = self.spoj.jeden("SELECT KodUrovne, Poradi, DelkaPlochyMM FROM dbo.Uroven WHERE UrovenID = ?",
                                 uroven_id)
        self.assertEqual((uroven["KodUrovne"], uroven["Poradi"], uroven["DelkaPlochyMM"]),
                         ("U07", 7, Decimal(1800)))
        for chyba, funkce, parametry in [
            ("NOT_FOUND", struktura.zaloz_regal, (self.spoj, self.kdo, NEEXISTUJE, "R01", None)),
            ("ALREADY_EXISTS", struktura.zaloz_regal, (self.spoj, self.kdo, pracoviste_id, "r1", None)),
            ("NOT_FOUND", struktura.zaloz_uroven, (self.spoj, self.kdo, NEEXISTUJE, "U01", 1, 1800, 600)),
            ("ALREADY_EXISTS", struktura.zaloz_uroven, (self.spoj, self.kdo, regal_id, "U01", 1, 1800, 600)),
            ("VALIDATION_ERROR", struktura.zaloz_uroven, (self.spoj, self.kdo, regal_id, "X9", 1, 1800, 600)),
            ("VALIDATION_ERROR", struktura.zaloz_uroven, (self.spoj, self.kdo, regal_id, "U02", 2, 0, 800)),
        ]:
            self.assertEqual(self.kod_chyby(funkce, *parametry), chyba, parametry)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Regal WHERE PracovisteID = ?", pracoviste_id),
                         2)                                                      # chybová volání nic nezapsala
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Uroven WHERE RegalID = ?", druhy_regal), 1)

    def test_zaloz_box_vsechna_cleneni_obou_typu(self):
        """C1–C7 × DYN/STAT: kódy přihrádek, velikosti i výchozí rozměr C7 sedí na šablonu (Q-01, Q-05, Q-06)."""
        _, _, uroven_id, kod_pracoviste = self.nova_uroven()
        for cleneni in ukazky.POCET_POZIC:
            for typ_boxu in ("DYN", "STAT"):
                box_id = self.zaloz(uroven_id, typ_boxu=typ_boxu, cleneni=cleneni, rozmer=(900, 450))
                self.assertEqual(self.prihradky(box_id), self.ocekavane_prihradky(cleneni, typ_boxu, (900, 450)),
                                 f"{cleneni} {typ_boxu}")
                self.assertEqual(len(self.prihradky(box_id)), ukazky.POCET_POZIC[cleneni])
                box = self.spoj.jeden("SELECT KodBoxu, FullBoxKlic, DelkaMM, HloubkaMM FROM dbo.Box"
                                      " WHERE BoxID = ?", box_id)
                self.assertEqual((box["DelkaMM"], box["HloubkaMM"]), (Decimal(900), Decimal(450)))
                self.assertEqual(box["FullBoxKlic"],
                                 domena.full_box_klic(kod_pracoviste, "R01", "U01", box["KodBoxu"]))
        dyn = self.pozice_urovne(uroven_id)[::2]                                 # zakládám DYN, STAT, DYN, …
        self.assertEqual([self.kod_boxu(r["BoxID"]) for r in dyn],
                         [f"B{kod_pracoviste}{i:03d}" for i in range(1, len(dyn) + 1)])
        self.over_integrity(uroven_id)

    def test_vlozeni_do_poradi_posune_zbytek(self):
        """T23: box na 2. místě dostane pozici P02, stávající boxy P03 a P04 – bez změny PoziceID."""
        _, _, uroven_id, _ = self.nova_uroven()
        boxy = [self.zaloz(uroven_id) for _ in range(3)]
        predem = {r["BoxID"]: r["PoziceID"] for r in self.pozice_urovne(uroven_id)}
        novy = self.zaloz(uroven_id, poradi=2)
        self.assertEqual([(r["Poradi"], r["KodPozice"]) for r in self.pozice_urovne(uroven_id)],
                         [(1, "P01"), (2, "P02"), (3, "P03"), (4, "P04")])
        po = {r["BoxID"]: r for r in self.pozice_urovne(uroven_id)}
        self.assertEqual([po[b]["PoziceID"] for b in boxy], [predem[b] for b in boxy])
        self.assertEqual([po[b]["Poradi"] for b in boxy], [1, 3, 4])              # identita pořadí zůstává
        self.assertEqual(po[novy]["Poradi"], 2)
        pridany = self.zaloz(uroven_id)                                          # bez pořadí = na konec
        self.assertEqual(self.pozice_urovne(uroven_id)[-1]["BoxID"], pridany)
        self.assertEqual({r["Poradi"] for r in self.pozice_urovne(uroven_id)}, {1, 2, 3, 4, 5})
        self.assertEqual(self.kod_chyby(self.zaloz, uroven_id, 9), "VALIDATION_ERROR")
        self.over_integrity(uroven_id)

    def test_rady_a_cislovani_boxu(self):
        """11.2.1: DYN řada patří pracovišti, STAT má jednu řadu pro sklad, další číslo = nejvyšší + 1."""
        _, _, uroven_a, kod_a = self.nova_uroven()
        _, _, uroven_b, kod_b = self.nova_uroven()
        sedmy = self.zaloz(uroven_a, kod_boxu=f"B{kod_a}007")                     # volné číslo ze štítku
        self.assertEqual(self.kod_boxu(self.zaloz(uroven_a)), f"B{kod_a}008")     # mezery se samy nedoplňují
        self.vyraz(sedmy)
        self.assertEqual(self.kod_boxu(self.zaloz(uroven_a)), f"B{kod_a}009")     # vyřazené číslo neopakuje
        self.assertEqual(self.kod_boxu(self.zaloz(uroven_b)), f"B{kod_b}001")     # řada patří pracovišti
        stat_1, stat_2 = self.zaloz(uroven_a, typ_boxu="STAT"), self.zaloz(uroven_b, typ_boxu="STAT")
        self.assertEqual([self.kod_boxu(i)[:5] for i in (stat_1, stat_2)], ["BSTAT", "BSTAT"])
        self.assertEqual(domena.cislo_boxu(self.kod_boxu(stat_2)), domena.cislo_boxu(self.kod_boxu(stat_1)) + 1)
        self.assertEqual(self.kod_chyby(self.zaloz, uroven_a, None, "DYN", "C4", f"B{kod_a}007"),
                         "ALREADY_EXISTS")                                       # kód ze štítku už byl vydán
        self.assertEqual(self.kod_chyby(self.zaloz, uroven_a, None, "DYN", "C4", f"B{kod_b}005"),
                         "VALIDATION_ERROR")                                     # cizí řada není kolize
        self.over_integrity(uroven_a, uroven_b)

    def test_zaloz_box_chyby(self):
        _, _, uroven_id, kod = self.nova_uroven()
        self.zaloz(uroven_id)
        stavy = self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Pozice WHERE UrovenID = ?", uroven_id)
        for chyba, prepsat in [
            ("NOT_FOUND", dict(uroven_id=NEEXISTUJE)),
            ("NOT_FOUND", dict(cleneni="C8")),
            ("VALIDATION_ERROR", dict(typ_boxu="MIX")),
            ("VALIDATION_ERROR", dict(rozmer=(0, -1))),
            ("VALIDATION_ERROR", dict(kod_boxu=f"B{kod}002", typ_boxu="STAT")),   # cizí řada
            ("ALREADY_EXISTS", dict(kod_boxu=f"B{kod}001")),
            ("VALIDATION_ERROR", dict(poradi=9)),
        ]:
            parametry = {"uroven_id": uroven_id} | prepsat
            self.assertEqual(self.kod_chyby(self.zaloz, **parametry), chyba, prepsat)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Pozice WHERE UrovenID = ?", uroven_id), stavy)
        with self.assertRaises(AppError) as zachyceno:
            self.zaloz(uroven_id, rozmer=(0, -1))
        self.assertEqual({c["pole"] for c in zachyceno.exception.data["chyby"]}, {"delkaMm", "hloubkaMm"})
        self.over_integrity(uroven_id)

    def test_rollback_nic_nenecha_ve_druhem_spojeni(self):
        """Zakládání běží v transakci volajícího (P5) – bez potvrzení v databázi nezůstane nic."""
        pracoviste_id, _, uroven_id, kod_pracoviste = self.nova_uroven()
        self.zaloz(uroven_id)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.v_Misto WHERE KodPracoviste = ?",
                                           kod_pracoviste), 4)
        druhe = self.druhe_spojeni()
        self.assertEqual(druhe.hodnota("SELECT COUNT(*) FROM dbo.Pracoviste WHERE PracovisteID = ?", pracoviste_id),
                         0)
        self.assertEqual(druhe.hodnota("SELECT COUNT(*) FROM dbo.v_Misto WHERE KodPracoviste = ?", kod_pracoviste),
                         0)
        self.assertEqual(druhe.hodnota("SELECT COUNT(*) FROM dbo.Pozice WHERE UrovenID = ?", uroven_id), 0)


class TestCteni(ZakladStruktury):
    """Čtecí funkce se testují na repozitáři – rozhraní ještě po celou fázi 1 vrací vzorová data."""

    def setUp(self) -> None:
        super().setUp()
        self.pracoviste_id, self.regal_id, self.uroven_id, self.kod = self.nova_uroven()
        self.kod_boxu = f"B{self.kod}001"
        self.adresa = domena.full_box_klic(self.kod, "R01", "U01", self.kod_boxu)
        self.box = self.zaloz(self.uroven_id)                                     # B…001, členění C4
        self.druhy_box = self.zaloz(self.uroven_id)                                # B…002

    def test_najdi_objekt(self):
        barcode = f"HOUFEK-{self.kod}-R01"
        regal = repozitar.najdi_objekt(self.spoj, barcode)
        self.assertEqual((regal.typ, regal.kod, regal.adresa, regal.regal_id, regal.box_id),
                         ("REGAL", barcode, barcode, self.regal_id, None))
        box = repozitar.najdi_objekt(self.spoj, f" {self.kod_boxu.lower()} ")
        self.assertEqual((box.typ, box.kod, box.adresa, box.regal_id, box.uroven_id, box.vnitrni_pozice_id),
                         ("BOX", self.kod_boxu, self.adresa, self.regal_id, self.uroven_id, None))
        misto = repozitar.najdi_objekt(self.spoj, f"{self.kod_boxu}-CH")
        self.assertEqual((misto.typ, misto.kod, misto.adresa, misto.uroven_id, misto.box_id),
                         ("POZICE", f"{self.kod_boxu}-CH", f"{self.adresa}-CH", self.uroven_id, self.box))
        self.assertEqual(misto.vnitrni_pozice_id, self.ids_boxu(self.box)[2])
        druhy_regal = struktura.zaloz_regal(self.spoj, self.kdo, self.pracoviste_id, "R02", None)
        struktura.zaloz_uroven(self.spoj, self.kdo, druhy_regal, "U05", 5, 1800, 600)
        self.assertEqual(repozitar.najdi_objekt(self.spoj, f" houfek-{self.kod}-R02 ").regal_id, druhy_regal)

    def test_najdi_vnitrni_pozici(self):
        misto = repozitar.najdi_vnitrni_pozici(self.spoj, f" {self.kod_boxu.lower()}-ch ")
        self.assertEqual((misto.vnitrni_pozice_id, misto.box_id, misto.kod, misto.kod_boxu, misto.kod_pozice),
                         (self.ids_boxu(self.box)[2], self.box, f"{self.kod_boxu}-CH", self.kod_boxu, "CH"))
        self.assertEqual((misto.typ_boxu, misto.velikost, misto.pracoviste, misto.regal_id, misto.uroven_id),
                         ("DYN", "V3", self.kod, self.regal_id, self.uroven_id))
        self.assertEqual((misto.rozmer_c7, misto.blokovano, misto.box_blokovany, misto.poradi_v_boxu),
                         (None, False, False, 3))
        self.assertEqual(misto.adresa, f"{self.adresa}-CH")
        self.assertEqual(repozitar.najdi_vnitrni_pozici(self.spoj, f"{self.adresa}-CH").vnitrni_pozice_id,
                         misto.vnitrni_pozice_id)                                 # dlouhý kód (Q-02)
        self.spoj.proved("UPDATE dbo.Box SET Blokovany = 1 WHERE BoxID = ?", self.box)
        blok = repozitar.najdi_vnitrni_pozici(self.spoj, f"{self.kod_boxu}-CH")
        self.assertEqual((blok.blokovano, blok.box_blokovany), (True, True))       # blokace boxu platí pro všechy

    def test_chyby_skeneru(self):
        stary_stitek = f"HOUFEK-{self.kod}-R09-U01-{self.kod_boxu}-CH"             # box leží jinde (Q-02)
        for kod, chyba in [("AAR10044", "INVALID_BARCODE"),                         # není kód skladu
                           (stary_stitek, "INVALID_BARCODE"),
                           (f"B{self.kod}999-CH", "NOT_FOUND"),                     # box neexistuje
                           (f"{self.kod_boxu}-K", "NOT_FOUND")]:                    # T13: K v členění C4 není
            self.assertEqual(self.kod_chyby(repozitar.najdi_objekt, self.spoj, kod), chyba, kod)
            self.assertEqual(self.kod_chyby(repozitar.najdi_vnitrni_pozici, self.spoj, kod), chyba, kod)
        self.assertEqual(self.kod_chyby(repozitar.najdi_objekt, self.spoj, f"HOUFEK-{self.kod}-R99"), "NOT_FOUND")
        for kod in (self.kod_boxu, f"HOUFEK-{self.kod}-R01"):                       # box a regál nejsou pozice
            self.assertEqual(self.kod_chyby(repozitar.najdi_vnitrni_pozici, self.spoj, kod),
                             "WRONG_SCAN_LEVEL", kod)

    def test_nacti_mista(self):
        ids = self.ids_boxu(self.box)
        druhe_ids = self.ids_boxu(self.druhy_box)
        mista = repozitar.nacti_mista(self.spoj, ids + [ids[0], NEEXISTUJE])
        self.assertEqual(sorted(mista), sorted(ids))                # duplicita se sloučí, neexistující chybí
        misto = mista[ids[0]]
        self.assertEqual((misto.kod, misto.kod_boxu, misto.typ_boxu, misto.velikost, misto.adresa),
                         (f"{self.kod_boxu}-G", self.kod_boxu, "DYN", "V3", f"{self.adresa}-G"))
        self.assertEqual(repozitar.nacti_mista(self.spoj, []), {})
        self.vyraz(self.druhy_box)
        self.assertEqual(sorted(repozitar.nacti_mista(self.spoj, ids + druhe_ids)), sorted(ids))

    def test_kandidatni_mista_dyn(self):
        def kandidati(velikost: str = "V3", **prava) -> list[str]:
            return [m.kod for m in repozitar.kandidatni_mista_dyn(self.spoj, self.regal_id, velikost, **prava)]

        prihradky = ("G", "H", "CH", "I")
        vsechny = [f"{self.kod_boxu}-{p}" for p in prihradky] + [f"B{self.kod}002-{p}" for p in prihradky]
        self.assertEqual(kandidati(), vsechny)                      # číslo boxu, pak pořadí v boxu (21.1.3)
        self.assertEqual(kandidati("V6"), [])                       # jiná velikost se neuchází
        self.assertEqual(self.kod_chyby(repozitar.kandidatni_mista_dyn, self.spoj, NEEXISTUJE, "V3"), "NOT_FOUND")
        self.spoj.proved("UPDATE dbo.Box SET Blokovany = 1 WHERE BoxID = ?", self.druhy_box)
        self.assertEqual(kandidati(), vsechny[:4])                  # blokovaný box se neuchází
        self.spoj.proved("UPDATE dbo.Box SET Blokovany = 0 WHERE BoxID = ?", self.druhy_box)
        self.spoj.proved("UPDATE dbo.VnitrniPoziceBoxu SET Blokovany = 1 WHERE VnitrniPoziceID = ?",
                         self.ids_boxu(self.box)[1])
        self.assertEqual(kandidati(), [f"{self.kod_boxu}-G", f"{self.kod_boxu}-CH", f"{self.kod_boxu}-I"]
                         + [f"B{self.kod}002-{p}" for p in ("G", "H", "CH", "I")])

    def test_kandidati_z_celeho_pracoviste(self):
        """Q-10: cele_pracoviste=True přidá i ostatní regály pracoviště; bez flagu zůstává jen zvolený regál."""
        druhy_regal = struktura.zaloz_regal(self.spoj, self.kdo, self.pracoviste_id, "R02", None)
        druha_uroven = struktura.zaloz_uroven(self.spoj, self.kdo, druhy_regal, "U01", 1, 1800, 600)
        c7 = self.zaloz(druha_uroven, cleneni="C7", rozmer=(1000, 500))
        self.assertEqual([m.kod for m in repozitar.kandidatni_mista_dyn(self.spoj, self.regal_id, "V3")],
                         [f"{self.kod_boxu}-{p}" for p in ("G", "H", "CH", "I")]
                         + [f"B{self.kod}002-{p}" for p in ("G", "H", "CH", "I")])
        self.assertEqual([m.kod for m in repozitar.kandidatni_mista_dyn(self.spoj, self.regal_id, "V6")], [])
        self.assertEqual([m.kod for m in repozitar.kandidatni_mista_dyn(self.spoj, self.regal_id, "V6",
                                                                       cele_pracoviste=True)],
                         [f"B{self.kod}003-R"])
        misto = repozitar.kandidatni_mista_dyn(self.spoj, druhy_regal, "V6")[0]
        self.assertEqual((misto.kod, misto.regal_id, misto.rozmer_c7.delka_mm, misto.rozmer_c7.hloubka_mm),
                         (f"B{self.kod}003-R", druhy_regal, Decimal(1000), Decimal(500)))
        self.assertEqual(c7, misto.box_id)

    def test_pozice_v_rozsahu(self):
        vsechny = self.ids_boxu(self.box) + self.ids_boxu(self.druhy_box)
        self.assertEqual(repozitar.pozice_v_rozsahu(self.spoj, "BOX", self.box), self.ids_boxu(self.box))
        self.assertEqual(repozitar.pozice_v_rozsahu(self.spoj, "POZICE", vsechny[0]), [vsechny[0]])
        for typ, cil in [("UROVEN", self.uroven_id), ("REGAL", self.regal_id), ("PRAC", self.pracoviste_id)]:
            self.assertEqual(repozitar.pozice_v_rozsahu(self.spoj, typ, cil), sorted(vsechny), typ)
        full = repozitar.pozice_v_rozsahu(self.spoj, "FULL", None)
        self.assertEqual(full, sorted(full))
        self.assertTrue(set(vsechny) <= set(full))                  # FULL je celá databáze, jen podmnožina
        for typ, cil in [("BOX", NEEXISTUJE), ("UROVEN", NEEXISTUJE), ("PRAC", NEEXISTUJE)]:
            self.assertEqual(self.kod_chyby(repozitar.pozice_v_rozsahu, self.spoj, typ, cil), "NOT_FOUND", typ)
        for typ, cil in [("SVET", None), ("FULL", self.uroven_id), ("BOX", None)]:
            self.assertEqual(self.kod_chyby(repozitar.pozice_v_rozsahu, self.spoj, typ, cil),
                             "VALIDATION_ERROR", (typ, cil))

    def test_rozlozeni_urovne(self):
        """Boxy se řadí podle Pozice.Poradi, poloha přihrádek pochází ze šablony, souřadnice boxů z 17.1."""
        treti = self.zaloz(self.uroven_id, cleneni="C1", rozmer=(400, 360))
        rozlozeni = repozitar.rozlozeni_urovne(self.spoj, self.uroven_id)
        self.assertEqual((rozlozeni.uroven_id, rozlozeni.kod_urovne, rozlozeni.regal_id, rozlozeni.kod_regalu,
                          rozlozeni.pracoviste, rozlozeni.delka_plochy_mm, rozlozeni.hloubka_plochy_mm),
                         (self.uroven_id, "U01", self.regal_id, "R01", self.kod, 2400.0, 800.0))
        self.assertEqual([(b.box_id, b.kod_boxu, b.kod_cleneni, b.typ_boxu, b.kod_pozice_urovne, b.blokovany,
                           float(b.delka_mm)) for b in rozlozeni.boxy],
                         [(self.box, f"B{self.kod}001", "C4", "DYN", "P01", False, 400.0),
                          (self.druhy_box, f"B{self.kod}002", "C4", "DYN", "P02", False, 400.0),
                          (treti, f"B{self.kod}003", "C1", "DYN", "P03", False, 400.0)])
        self.assertEqual([(float(b.x_mm), float(b.y_mm)) for b in rozlozeni.boxy],
                         [(20.0, 20.0), (440.0, 20.0), (860.0, 20.0)])
        self.assertEqual((rozlozeni.sirka_svg_mm, rozlozeni.vyska_svg_mm), (1280.0, 400.0))
        self.assertEqual([(p.kod_pozice, p.velikost, float(p.rel_x), float(p.rel_sirka))
                          for p in rozlozeni.boxy[0].pozice],
                         [("G", "V3", 0.5, 0.5), ("H", "V3", 0.0, 0.5), ("CH", "V3", 0.0, 0.5),
                          ("I", "V3", 0.5, 0.5)])
        self.assertEqual([p.kod_pozice for p in rozlozeni.boxy[2].pozice], ["A"])
        self.assertEqual(self.kod_chyby(repozitar.rozlozeni_urovne, self.spoj, NEEXISTUJE), "NOT_FOUND")

    def test_ciselniky(self):
        ciselniky = repozitar.nacti_ciselniky(self.spoj)
        pracoviste = {p.kod: p for p in ciselniky["pracoviste"]}[self.kod]
        self.assertEqual((pracoviste.id, pracoviste.aktivni), (self.pracoviste_id, True))
        self.assertEqual([p.kod for p in ciselniky["velikosti"]], ["V1", "V2", "V3", "V4", "V5", "V6"])
        self.assertEqual([p.id for p in ciselniky["velikosti"]], [1, 2, 3, 4, 5, 6])                 # seed 001
        self.assertTrue(all(p.nazev for p in ciselniky["velikosti"]))


if __name__ == "__main__":
    unittest.main()
