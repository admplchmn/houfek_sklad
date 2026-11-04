"""Integrační testy ostrova D nad SQL Serverem: služby, audit a SQL, které se zapojí ve fázi 2.

Služby se volí `__wrapped__`, tedy bez dekorátoru, takže tělo běží ve spojení a transakci testu a
na konci se vrátí zpět (dekorátor @transakce/@cteni si otevírá vlastní spojení a potvrzuje).
Přes HTTP se tady netestuje – ověření uživatele a oprávnění po sloučení ostrovu B sahá do DB.
Pozice a obsah patří jiným ostrovům (D je nesmí číst ani do nich psát), proto si test vkládá SQL.
"""
from __future__ import annotations

from decimal import Decimal

from app.ostrovy.dily import repozitar, rozhrani, sluzby, ukazky
from app.ostrovy.dily.kontrakty import (
    DilyFiltr,
    NovyCiselnikVstup,
    NovyDilVstup,
    ZmenaCiselnikuVstup,
    ZmenaDiluVstup,
    ZmenaVelikostiVstup,
)
from app.ostrovy.dily.rozhrani import NovyDil
from app.platforma.chyby import AppError
from app.platforma.db import spojeni_pro_skript
from app.platforma.kontrakty import DuvodVstup
from app.platforma.typy import Kontext, PotrebaMista, Rozmer
from tests.integrace.zaklad import ZakladIntegrace


class ZakladDilu(ZakladIntegrace):
    """Zázemí: technický uživatel pro AuditZmen, ID seedů a vložení místa s obsahem."""

    def setUp(self) -> None:
        super().setUp()
        self.kdo = Kontext(self._uzivatel_testu(), None, "ADMIN", frozenset())
        self.materialy = {r["KodMaterialu"]: r["MaterialID"] for r in
                          self.spoj.dotaz("SELECT MaterialID, KodMaterialu FROM dbo.Material")}
        self.tloustky = {format(r["TloustkaMM"], "f"): r["TloustkaID"] for r in
                         self.spoj.dotaz("SELECT TloustkaID, TloustkaMM FROM dbo.TloustkaMaterialu")}
        self.operace = {r["KodOperace"]: r["PrvniOperaceID"] for r in
                        self.spoj.dotaz("SELECT PrvniOperaceID, KodOperace FROM dbo.PrvniVyrobniOperace")}
        self.velikosti = {r["KodVelikosti"]: r["VelikostPoziceID"] for r in
                          self.spoj.dotaz("SELECT VelikostPoziceID, KodVelikosti FROM dbo.v_VelikostPozice")}
        self._pocet_mistu = 0

    def _uzivatel_testu(self) -> int:
        """Neaktivní technický uživatel (FK AuditZmen.UzivatelID); potvrdí se, přihlásit se za něj nedá."""
        with spojeni_pro_skript() as spoj:
            uzivatel_id = spoj.hodnota("SELECT UzivatelID FROM dbo.Uzivatel WHERE OsobniCislo = 'TEST-INTEGRACE'")
            if uzivatel_id is None:
                uzivatel_id = spoj.vloz(
                    "INSERT INTO dbo.Uzivatel (OsobniCislo, Jmeno, Prijmeni, RoleID, Aktivni) "
                    "SELECT 'TEST-INTEGRACE', N'Integrační', N'Test', RoleID, 0 FROM dbo.Role WHERE KodRole = 'ADMIN'")
        return int(uzivatel_id)

    def zaloz(self, cislo: str, **pole):
        """Založí díl službou; výchozí číselníky jsou seed z migrace 001."""
        zaklad = {"material_id": self.materialy["S235"], "tloustka_id": self.tloustky["3.00"],
                  "prvni_operace_id": self.operace["LASER"]}
        return sluzby.zaloz_dil.__wrapped__(self.spoj, NovyDilVstup(identifikacni_cislo=cislo, **(zaklad | pole)),
                                            self.kdo)

    def detail(self, dil_id: int):
        return sluzby.detail_dilu.__wrapped__(self.spoj, dil_id)

    def stranka(self, **filtr):
        return sluzby.seznam_dilu.__wrapped__(self.spoj, DilyFiltr(**filtr))

    def zmen(self, dil_id: int, **pole):
        return sluzby.zmen_dil.__wrapped__(self.spoj, dil_id, ZmenaDiluVstup(**pole), self.kdo)

    def velikost(self, dil_id: int, **pole):
        return sluzby.zmen_velikost.__wrapped__(self.spoj, dil_id, ZmenaVelikostiVstup(**pole), self.kdo)

    def deaktivuj(self, dil_id: int, duvod: str = "konec výroby"):
        return sluzby.deaktivuj_dil.__wrapped__(self.spoj, dil_id, DuvodVstup(duvod=duvod), self.kdo)

    def vloz_misto_s_obsahem(self, dil_id: int, *, typ_boxu: str) -> None:
        """Regál s jedním boxem C1 (jedna přihrádka) a jednou ks dílu; kódy sedí na CHECK ze schématu."""
        self._pocet_mistu += 1
        pracoviste = self.spoj.hodnota("SELECT PracovisteID FROM dbo.Pracoviste WHERE KodPracoviste = 'PLE'")
        regal = self.spoj.vloz("INSERT INTO dbo.Regal (PracovisteID, KodRegalu) VALUES (?, ?)",
                               pracoviste, f"ZKU{self._pocet_mistu:03d}")
        uroven = self.spoj.vloz("INSERT INTO dbo.Uroven (RegalID, KodUrovne, Poradi, DelkaPlochyMM,"
                                " HloubkaPlochyMM) VALUES (?, 'U01', 1, 1000, 500)", regal)
        pozice = self.spoj.vloz("INSERT INTO dbo.Pozice (UrovenID, Poradi) VALUES (?, 1)", uroven)
        kod_boxu = f"BZK{self._pocet_mistu:03d}"                     # KodBoxu = B…###
        box = self.spoj.vloz(
            "INSERT INTO dbo.Box (PoziceID, KodBoxu, TypBoxuID, CleneniBoxuID, DelkaMM, HloubkaMM, FullBoxKlic)"
            " SELECT ?, ?, tb.TypBoxuID, cb.CleneniBoxuID, 1000, 500, ?"
            " FROM dbo.TypBoxu AS tb CROSS JOIN dbo.CleneniBoxu AS cb"
            " WHERE tb.KodTypu = ? AND cb.KodCleneni = 'C1'",
            pozice, kod_boxu, f"HOUFEK-PLE-ZKU{self._pocet_mistu:03d}-U01-{kod_boxu}", typ_boxu)
        sablona = "DynKod" if typ_boxu == "DYN" else "StatKod"        # štítek přihrádky podle typu boxu
        misto = self.spoj.vloz(
            f"INSERT INTO dbo.VnitrniPoziceBoxu (BoxID, SablonaCleneniID, KodPozice, VelikostPoziceID)"
            f" SELECT ?, sc.SablonaCleneniID, sc.{sablona}, sc.VelikostPoziceID FROM dbo.SablonaCleneni AS sc"
            f" JOIN dbo.CleneniBoxu AS cb ON cb.CleneniBoxuID = sc.CleneniBoxuID WHERE cb.KodCleneni = 'C1'", box)
        self.spoj.proved("INSERT INTO dbo.ObsahPozice (VnitrniPoziceID, DilID, PocetKs) VALUES (?, ?, 1)",
                         misto, dil_id)

    def audity(self, objekt_id: int, typ_objektu: str = "DIL") -> list[dict]:
        """Řádky auditu objektu od toho prvního; hodnoty jsou v AuditZmen vždy text."""
        return self.spoj.dotaz("SELECT Pole, StaraHodnota, NovaHodnota, Poznamka, UzivatelID FROM dbo.AuditZmen"
                               " WHERE TypObjektu = ? AND ObjektID = ? ORDER BY AuditID", typ_objektu, objekt_id)

    def chyba(self, funkce, *args, kod: str, **pole) -> AppError:
        with self.assertRaises(AppError) as zachyceno:
            funkce(*args, **pole)
        self.assertEqual(zachyceno.exception.kod, kod, zachyceno.exception)
        return zachyceno.exception


class TestRozhraniZalozDil(ZakladDilu):
    """Úkol 1: ostrov H zakládí díly přes rozhraní – překládá kódy na ID, nekommituje a audituje."""

    def dil(self, **pole) -> NovyDil:
        zaklad = {"identifikacni_cislo": "CE21RA 10 100194", "nazev": "Bok levý", "material": "S235",
                  "tloustka_mm": Decimal("3"), "prvni_operace": "LASER", "standardni_davka_ks": 10,
                  "potreba": PotrebaMista("V2"), "poznamka": "Zavést až po otvorování"}
        return NovyDil(**(zaklad | pole))

    def test_prelozi_kody_a_zapise_audit(self):
        dil_id = rozhrani.zaloz_dil(self.spoj, self.kdo, self.dil())
        radek = repozitar.nacti_dil(self.spoj, dil_id)
        self.assertEqual(radek["IdentifikacniCislo"], "CE21RA 10 100194")
        self.assertEqual(radek["NazevDilu"], "Bok levý")
        self.assertEqual(radek["KodMaterialu"], "S235")
        self.assertEqual(radek["TloustkaMM"], Decimal("3.00"))                 # „3“ je tloušťka 3.00
        self.assertEqual(radek["KodOperace"], "LASER")
        self.assertEqual(radek["Velikost"], "V2")
        self.assertEqual(radek["Poznamka"], "Zavést až po otvorování")
        self.assertEqual([(r["Pole"], r["StaraHodnota"], r["NovaHodnota"], r["UzivatelID"])
                          for r in self.audity(dil_id)],
                         [("IdentifikacniCislo", None, "CE21RA 10 100194", self.kdo.uzivatel_id)])

    def test_zapis_zůstane_v_transakci_volajiciho(self):
        """P5: transakci otevírá i uzavírá volající – D nic nepotvrdí, takže druhé spojení nic nevidí."""
        dil_id = rozhrani.zaloz_dil(self.spoj, self.kdo, self.dil())
        self.assertIsNotNone(repozitar.nacti_dil(self.spoj, dil_id))
        self.assertIsNone(self.druhe_spojeni().jeden("SELECT DilID FROM dbo.Dil WHERE DilID = ?", dil_id))

    def test_duplicitni_cislo_po_normalizaci(self):
        self.zaloz("AAR10044")
        self.chyba(rozhrani.zaloz_dil, self.spoj, self.kdo, self.dil(identifikacni_cislo=" aar10044 "),
                   kod="ALREADY_EXISTS")

    def test_neznamy_kod_ciselniku(self):
        for pole in ({"material": "OCEL C"}, {"prvni_operace": "BRUSKA"}, {"tloustka_mm": Decimal("7.77")}):
            with self.subTest(**pole):
                self.chyba(rozhrani.zaloz_dil, self.spoj, self.kdo, self.dil(**pole), kod="NOT_FOUND")

    def test_neznamna_velikost(self):
        self.chyba(rozhrani.zaloz_dil, self.spoj, self.kdo, self.dil(potreba=PotrebaMista("V9")),
                   kod="NOT_FOUND")

    def test_v6_bez_rozmeru_se_nevlozi(self):
        chyba = self.chyba(rozhrani.zaloz_dil, self.spoj, self.kdo, self.dil(potreba=PotrebaMista("V6")),
                           kod="VALIDATION_ERROR")
        self.assertEqual({c["pole"] for c in chyba.data["chyby"]}, {"potrebnaDelkaMm", "potrebnaHloubkaMm"})
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Dil WHERE IdentifikacniCislo ="
                                           " 'CE21RA 10 100194'"), 0)

    def test_v6_s_rozmarem(self):
        dil_id = rozhrani.zaloz_dil(self.spoj, self.kdo,
                                    self.dil(potreba=PotrebaMista("V6", Rozmer(Decimal("800"),
                                                                               Decimal("400.5")))))
        radek = repozitar.nacti_dil(self.spoj, dil_id)
        self.assertEqual((radek["Velikost"], radek["PotrebnaDelkaMM"], radek["PotrebnaHloubkaMM"]),
                         ("V6", Decimal("800.00"), Decimal("400.50")))

    def test_dil_bez_velikosti(self):
        """Díl bez velikosti (Q-26) založit jde – do DYN ho nepustí ostrov Struktura."""
        dil_id = rozhrani.zaloz_dil(self.spoj, self.kdo, self.dil(potreba=None))
        self.assertIsNone(repozitar.nacti_dil(self.spoj, dil_id)["Velikost"])


class TestSeznamADetail(ZakladDilu):
    def setUp(self) -> None:
        super().setUp()
        self.s355 = self.materialy["S355"]
        self.tlusta = self.tloustky["5.00"]
        self.autogen = self.operace["AUTOGEN"]
        self.v2 = self.velikosti["V2"]
        self.prvni = self.zaloz("ZKSTR 1")
        self.druhy = self.zaloz("ZKSTR 2", material_id=self.s355)
        self.treti = self.zaloz("ZKSTR 3", tloustka_id=self.tlusta, velikost_pozice_id=self.v2,
                                nazev="Zkouška bok")
        self.ctvrty = self.zaloz("ZKSTR 4", prvni_operace_id=self.autogen)
        self.deaktivuj(self.ctvrty.dil_id)

    def test_filtry_a_strankovani_podle_aktivnich_dilu(self):
        for filtr, ocekavani in (
                ({}, [self.prvni, self.druhy, self.treti]),                              # jen aktivní
                ({"hledat": "zkstr 3"}, [self.treti]),
                ({"hledat": "zkouška bok"}, [self.treti]),                               # hledá i v názvu
                ({"material_id": self.s355}, [self.druhy]),
                ({"tloustka_id": self.tlusta}, [self.treti]),
                ({"prvni_operace_id": self.autogen}, []),                                # ten je vyřazený
                ({"velikost_pozice_id": self.v2}, [self.treti]),
                ({"aktivni": False}, [self.ctvrty]),
                ({"aktivni": None}, [self.prvni, self.druhy, self.treti, self.ctvrty]),
        ):
            with self.subTest(**filtr):
                stranka = self.stranka(**{"hledat": "ZKSTR", **filtr})
                self.assertEqual([d.dil_id for d in stranka.polozky], [d.dil_id for d in ocekavani])
                self.assertEqual(stranka.celkem, len(ocekavani))

    def test_strankovani(self):
        self.assertEqual(([d.identifikacni_cislo for d in self.stranka(hledat="ZKSTR", velikost=2).polozky],
                          self.stranka(hledat="ZKSTR", velikost=2, strana=2).celkem),
                         (["ZKSTR 1", "ZKSTR 2"], 4))
        self.assertEqual([d.identifikacni_cislo for d in self.stranka(hledat="ZKSTR", velikost=2,
                                                                     strana=2).polozky],
                         ["ZKSTR 3", "ZKSTR 4"])
        stranka = self.stranka(hledat="ZKSTR", velikost=2, strana=3)
        self.assertEqual((stranka.polozky, stranka.celkem, stranka.strana, stranka.velikost), ([], 4, 3, 2))

    def test_voditko_v_hledani_je_text(self):
        self.zaloz("ZK%LIK 1")
        self.zaloz("ZKALIK 2")
        self.assertEqual([d.identifikacni_cislo for d in self.stranka(hledat="K%LIK").polozky], ["ZK%LIK 1"])

    def test_detail_vrati_kody_ciselniku(self):
        dil = self.zaloz("ZKDETAIL 1", nazev="Bok levý", velikost_pozice_id=self.velikosti["V1"],
                         standardni_davka_ks=25, vault_url="https://vault/d/1",
                         poznamka="Používat jen na servis.")
        detail = self.detail(dil.dil_id)
        self.assertEqual((detail.dil_id, detail.identifikacni_cislo, detail.nazev, detail.material,
                          detail.tloustka_mm, detail.prvni_operace, detail.velikost),
                         (dil.dil_id, "ZKDETAIL 1", "Bok levý", "S235", Decimal("3.00"), "LASER", "V1"))
        self.assertEqual((detail.standardni_davka_ks, detail.vault_url, detail.poznamka, detail.aktivni),
                         (25, "https://vault/d/1", "Používat jen na servis.", True))
        self.assertEqual((detail.potrebna_delka_mm, detail.potrebna_hloubka_mm), (None, None))
        self.chyba(sluzby.detail_dilu.__wrapped__, self.spoj, 2_000_000_000, kod="NOT_FOUND")

    def test_ciselnik_obsahuje_i_vyradene_polozky(self):
        material = sluzby.zaloz_polozku_ciselniku.__wrapped__(self.spoj, "materialy",
                                                              NovyCiselnikVstup(kod="ZKVYBOTEST"), self.kdo)
        sluzby.deaktivuj_polozku_ciselniku.__wrapped__(self.spoj, "materialy", material.id,
                                                       DuvodVstup(duvod="nepoužívá se"), self.kdo)
        materialy = sluzby.ciselnik.__wrapped__(self.spoj, "materialy").polozky
        self.assertTrue({"S235", "1.4301", "ALMG3"} <= {m.kod for m in materialy})
        self.assertIn((material.id, "ZKVYBOTEST", None, False),
                      [(m.id, m.kod, m.nazev, m.aktivni) for m in materialy])       # název má jen operace
        self.assertTrue({"1.00", "3.00", "60.00"}
                        <= {t.kod for t in sluzby.ciselnik.__wrapped__(self.spoj, "tloustky").polozky})
        laser = next(o for o in sluzby.ciselnik.__wrapped__(self.spoj, "operace").polozky if o.kod == "LASER")
        self.assertEqual(laser.nazev, "Laser")
        self.chyba(sluzby.ciselnik.__wrapped__, self.spoj, "barvy", kod="NOT_FOUND")


class TestZalozeniDilu(ZakladDilu):
    def test_duplikat_i_s_jinymi_mezerami_a_pismeny(self):
        dil = self.zaloz("ZKDIL 2")
        self.assertEqual(dil.identifikacni_cislo, "ZKDIL 2")
        self.chyba(self.zaloz, " zkdil  2 ", kod="ALREADY_EXISTS")

    def test_neznamy_ciselnik_nebo_velikost(self):
        self.zaloz("ZKDIL 3")
        for pole in ({"material_id": 2_000_000_000}, {"tloustka_id": 2_000_000_000},
                     {"prvni_operace_id": 2_000_000_000}, {"velikost_pozice_id": 2_000_000_000}):
            with self.subTest(**pole):
                self.chyba(self.zaloz, "ZKDIL 4", kod="NOT_FOUND", **pole)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Dil WHERE IdentifikacniCislo ="
                                           " 'ZKDIL 4'"), 0)

    def test_rozmer_patri_jen_velikosti_v6(self):
        self.chyba(self.zaloz, "ZKDIL 5", kod="VALIDATION_ERROR", velikost_pozice_id=self.velikosti["V1"],
                   potrebna_delka_mm=Decimal("10"), potrebna_hloubka_mm=Decimal("10"))
        self.chyba(self.zaloz, "ZKDIL 6", kod="VALIDATION_ERROR", velikost_pozice_id=self.velikosti["V6"])
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Dil WHERE IdentifikacniCislo LIKE"
                                           " 'ZKDIL %'"), 0)

    def test_zalozeni_audituje_pres_uniq_hlidak(self):
        """ALREADY_EXISTS se zjišťuje dotazem, ne až porušením UNIQUE – jinak by @transakce hlásila souběh."""
        self.zaloz("ZKDIL 5")
        try:
            self.zaloz("ZKDIL 5")
        except AppError as chyba:
            self.assertEqual(chyba.kod, "ALREADY_EXISTS")
        else:
            self.fail("Druhý zápis stejného čísla neměl projít.")
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Dil WHERE IdentifikacniCislo ="
                                           " 'ZKDIL 5'"), 1)

    def test_v6_s_rozmarem_se_zapise(self):
        dil = self.zaloz("ZKDIL 7", velikost_pozice_id=self.velikosti["V6"], potrebna_delka_mm=Decimal("800"),
                         potrebna_hloubka_mm=Decimal("400.5"))
        self.assertEqual((dil.velikost, dil.potrebna_delka_mm, dil.potrebna_hloubka_mm),
                         ("V6", Decimal("800.00"), Decimal("400.50")))
        self.assertEqual([(r["Pole"], r["StaraHodnota"], r["NovaHodnota"]) for r in self.audity(dil.dil_id)],
                         [("IdentifikacniCislo", None, "ZKDIL 7")])


class TestZmenaDilu(ZakladDilu):
    def test_kazde_zmenene_pole_ma_radek_auditu(self):
        dil = self.zaloz("ZKZMENA 1", nazev="Původní název", standardni_davka_ks=10)
        druhy = self.zmen(dil.dil_id, duvod="oprava kmenových dat", nazev="Bok levý",
                          material_id=self.materialy["S355"], standardni_davka_ks=None)
        self.assertEqual((druhy.nazev, druhy.material, druhy.standardni_davka_ks), ("Bok levý", "S355", None))
        self.assertEqual([(r["Pole"], r["StaraHodnota"], r["NovaHodnota"], r["Poznamka"])
                          for r in self.audity(dil.dil_id)][1:],
                         [("MaterialID", str(self.materialy["S235"]), str(self.materialy["S355"]),
                           "oprava kmenových dat"),
                          ("NazevDilu", "Původní název", "Bok levý", "oprava kmenových dat"),
                          ("StandardniDavkaKs", "10", None, "oprava kmenových dat")])

    def test_stejna_hodnota_se_neaudituje(self):
        dil = self.zaloz("ZKZMENA 2", nazev="Bok levý")
        self.assertEqual(self.zmen(dil.dil_id, duvod="kontrola", nazev="Bok levý",
                                   poznamka="Nový pokyn").nazev, "Bok levý")
        self.assertEqual([r["Pole"] for r in self.audity(dil.dil_id)], ["IdentifikacniCislo", "Poznamka"])

    def test_nezname_id(self):
        self.chyba(self.zmen, 2_000_000_000, duvod="oprava", nazev="X", kod="NOT_FOUND")
        dil = self.zaloz("ZKZMENA 3", nazev="Bok levý")
        self.chyba(self.zmen, dil.dil_id, duvod="oprava", material_id=2_000_000_000, kod="NOT_FOUND")
        self.assertEqual(self.detail(dil.dil_id).nazev, "Bok levý")                 # nic se neepsalo

    def test_deaktivace(self):
        dil = self.zaloz("ZKZMENA 4")
        self.assertFalse(self.deaktivuj(dil.dil_id, "konec výroby").aktivni)
        self.assertEqual([(r["Pole"], r["StaraHodnota"], r["NovaHodnota"], r["Poznamka"])
                          for r in self.audity(dil.dil_id)][1:], [("Aktivni", "1", "0", "konec výroby")])
        self.chyba(sluzby.deaktivuj_dil.__wrapped__, self.spoj, 2_000_000_000, DuvodVstup(duvod="konec"),
                   kod="NOT_FOUND")

    def test_dil_s_obsahem_nejde_vyradit(self):
        for typ_boxu in ("DYN", "STAT"):
            with self.subTest(typ_boxu=typ_boxu):
                dil = self.zaloz(f"ZKOBSAH {typ_boxu}")
                self.vloz_misto_s_obsahem(dil.dil_id, typ_boxu=typ_boxu)
                self.chyba(self.deaktivuj, dil.dil_id, "konec", kod="NOT_EMPTY")
                self.assertTrue(self.detail(dil.dil_id).aktivni)
                self.assertEqual([r["Pole"] for r in self.audity(dil.dil_id)], ["IdentifikacniCislo"])


class TestZmenaVelikosti(ZakladDilu):
    def test_zmeni_velikost_i_rozmer_a_audituje_je(self):
        dil = self.zaloz("ZKVEL 1", velikost_pozice_id=self.velikosti["V1"])
        druhy = self.velikost(dil.dil_id, velikost_pozice_id=self.velikosti["V6"], duvod="nový přípravek",
                              potrebna_delka_mm=Decimal("800"), potrebna_hloubka_mm=Decimal("400.5"))
        self.assertEqual((druhy.velikost, druhy.potrebna_delka_mm, druhy.potrebna_hloubka_mm),
                         ("V6", Decimal("800.00"), Decimal("400.50")))
        self.assertEqual([(r["Pole"], r["StaraHodnota"], r["NovaHodnota"], r["Poznamka"])
                          for r in self.audity(dil.dil_id)][1:],
                         [("VelikostPoziceID", str(self.velikosti["V1"]), str(self.velikosti["V6"]),
                           "nový přípravek"),
                          ("PotrebnaDelkaMM", None, "800.00", "nový přípravek"),
                          ("PotrebnaHloubkaMM", None, "400.50", "nový přípravek")])

    def test_stejna_velikost_se_neaudituje(self):
        dil = self.zaloz("ZKVEL 2", velikost_pozice_id=self.velikosti["V2"])
        self.velikost(dil.dil_id, velikost_pozice_id=self.velikosti["V2"], duvod="potvrzení stejného stavu")
        self.assertEqual([r["Pole"] for r in self.audity(dil.dil_id)], ["IdentifikacniCislo"])

    def test_obsah_v_dyn_zmenu_velikosti_zabrani(self):
        """Q-28 je otevřená; kontrakt popisuje navržené řešení – DYN s obsahem velikost nemění."""
        dil = self.zaloz("ZKVEL 3", velikost_pozice_id=self.velikosti["V1"])
        self.vloz_misto_s_obsahem(dil.dil_id, typ_boxu="DYN")
        self.chyba(self.velikost, dil.dil_id, velikost_pozice_id=self.velikosti["V2"], duvod="přeplánování",
                   kod="NOT_EMPTY")
        self.assertEqual(self.detail(dil.dil_id).velikost, "V1")
        self.assertEqual([r["Pole"] for r in self.audity(dil.dil_id)], ["IdentifikacniCislo"])

    def test_obsah_jen_v_stat_zmenu_pusti(self):
        dil = self.zaloz("ZKVEL 4", velikost_pozice_id=self.velikosti["V1"])
        self.vloz_misto_s_obsahem(dil.dil_id, typ_boxu="STAT")
        self.assertEqual(self.velikost(dil.dil_id, velikost_pozice_id=self.velikosti["V3"],
                                       duvod="přestavba regálu").velikost, "V3")

    def test_chyby_vstupu(self):
        dil = self.zaloz("ZKVEL 5", velikost_pozice_id=self.velikosti["V1"])
        self.chyba(self.velikost, dil.dil_id, velikost_pozice_id=self.velikosti["V6"],
                   duvod="větší přípravek", kod="VALIDATION_ERROR")
        self.chyba(self.velikost, dil.dil_id, velikost_pozice_id=2_000_000_000, duvod="nesmysl",
                   kod="NOT_FOUND")
        self.assertEqual(self.detail(dil.dil_id).velikost, "V1")


class TestCiselniky(ZakladDilu):
    def material(self, kod: str):
        return sluzby.zaloz_polozku_ciselniku.__wrapped__(self.spoj, "materialy",
                                                          NovyCiselnikVstup(kod=kod), self.kdo)

    def test_zalozeni_normalizuje_kod(self):
        material = self.material(" zku-1 ")
        self.assertEqual((material.kod, material.nazev, material.aktivni), ("ZKU-1", None, True))
        self.assertIn(material.id, [m.id for m in sluzby.ciselnik.__wrapped__(self.spoj, "materialy").polozky])
        self.assertEqual(sluzby.zaloz_polozku_ciselniku.__wrapped__(self.spoj, "tloustky",
                                                                    NovyCiselnikVstup(kod="2,75"),
                                                                    self.kdo).kod, "2.75")
        operace = sluzby.zaloz_polozku_ciselniku.__wrapped__(self.spoj, "operace",
                                                             NovyCiselnikVstup(kod="bruska", nazev="Bruska"),
                                                             self.kdo)
        self.assertEqual((operace.kod, operace.nazev), ("BRUSKA", "Bruska"))

    def test_duplicita_kodu_po_normalizaci(self):
        """Materiál zakládáme tady, operace a tloušťka jsou seed z migrace 001."""
        sluzby.zaloz_polozku_ciselniku.__wrapped__(self.spoj, "materialy", NovyCiselnikVstup(kod="ZKU.1"), self.kdo)
        for typ, kod in (("materialy", " zku.1 "), ("operace", "laser"), ("tloustky", "3.00")):
            with self.subTest(typ=typ):
                self.chyba(sluzby.zaloz_polozku_ciselniku.__wrapped__, self.spoj, typ, NovyCiselnikVstup(kod=kod),
                           kod="ALREADY_EXISTS")

    def test_tloustka_tri_a_tri_tecky_00_je_totez(self):
        """Kontrola duplicity používá stejnou normalizaci jako zápis („3“ i „3,00“ je tloušťka 3.00)."""
        for kod in ("3", "3,00", " 3.00 "):
            with self.subTest(kod=kod):
                self.chyba(sluzby.zaloz_polozku_ciselniku.__wrapped__, self.spoj, "tloustky",
                           NovyCiselnikVstup(kod=kod), kod="ALREADY_EXISTS")

    def test_validace_kodu_a_nazvu(self):
        for typ, vstup in (("tloustky", NovyCiselnikVstup(kod="0")), ("operace", NovyCiselnikVstup(kod="bruska")),
                           ("materialy", NovyCiselnikVstup(kod="ZKU2", nazev="Ocel"))):
            with self.subTest(typ=typ, kod=vstup.kod):
                self.chyba(sluzby.zaloz_polozku_ciselniku.__wrapped__, self.spoj, typ, vstup,
                           kod="VALIDATION_ERROR")
        self.chyba(sluzby.zaloz_polozku_ciselniku.__wrapped__, self.spoj, "barvy", NovyCiselnikVstup(kod="RAL"),
                   kod="NOT_FOUND")

    def test_zmena_kodu_a_nazvu_audituje(self):
        operace = sluzby.zaloz_polozku_ciselniku.__wrapped__(self.spoj, "operace",
                                                             NovyCiselnikVstup(kod="ZKOPER", nazev="Původní"),
                                                             self.kdo)
        zmenena = sluzby.zmen_polozku_ciselniku.__wrapped__(
            self.spoj, "operace", operace.id,
            ZmenaCiselnikuVstup(duvod="přejmenování", kod=" zkoper2 ", nazev="Druhý název"), self.kdo)
        self.assertEqual((zmenena.kod, zmenena.nazev, zmenena.aktivni), ("ZKOPER2", "Druhý název", True))
        self.assertEqual([(r["Pole"], r["StaraHodnota"], r["NovaHodnota"], r["Poznamka"])
                          for r in self.audity(operace.id, "PRVNI_VYROBNI_OPERACE")],
                         [("KodOperace", "ZKOPER", "ZKOPER2", "přejmenování"),
                          ("NazevOperace", "Původní", "Druhý název", "přejmenování")])
        self.chyba(sluzby.zmen_polozku_ciselniku.__wrapped__, self.spoj, "operace", operace.id,
                   ZmenaCiselnikuVstup(duvod="srazka", kod="laser"), kod="ALREADY_EXISTS")
        self.chyba(sluzby.zmen_polozku_ciselniku.__wrapped__, self.spoj, "operace", operace.id,
                   ZmenaCiselnikuVstup(duvod="vymazani", nazev=None), kod="VALIDATION_ERROR")

    def test_stejna_hodnota_se_neaudituje_a_nezname_id(self):
        material = self.material("ZKSTEJNA")
        sluzby.zmen_polozku_ciselniku.__wrapped__(self.spoj, "materialy", material.id,
                                                  ZmenaCiselnikuVstup(duvod="kontrola", kod="zkstejna"), self.kdo)
        self.assertEqual(self.audity(material.id, "MATERIAL"), [])
        self.chyba(sluzby.zmen_polozku_ciselniku.__wrapped__, self.spoj, "materialy", 2_000_000_000,
                   ZmenaCiselnikuVstup(duvod="kontrola", kod="X"), kod="NOT_FOUND")

    def test_deaktivace_položky(self):
        """Vyřazená položka zůstane u existujících dílů; služba ji zkontrolovala na existenci, ne na Aktivni."""
        material = self.material("ZKVYR")
        self.assertFalse(sluzby.deaktivuj_polozku_ciselniku.__wrapped__(
            self.spoj, "materialy", material.id, DuvodVstup(duvod="nepoužívá se"), self.kdo).aktivni)
        self.assertEqual([(r["Pole"], r["StaraHodnota"], r["NovaHodnota"], r["Poznamka"])
                          for r in self.audity(material.id, "MATERIAL")],
                         [("Aktivni", "1", "0", "nepoužívá se")])
        dil = self.zaloz("ZKVYRITY", material_id=material.id)
        self.assertEqual(self.zmen(dil.dil_id, duvod="oprava", nazev="Bok levý").material, "ZKVYR")
        self.chyba(sluzby.deaktivuj_polozku_ciselniku.__wrapped__, self.spoj, "materialy", 2_000_000_000,
                   DuvodVstup(duvod="nepoužívá se"), kod="NOT_FOUND")


class TestSqlProRozhrani(ZakladDilu):
    """Dotazy pro `rozhrani` jsou hotové a otestované; ve fázi 1 do nich rozhraní ještě nesahá."""

    def test_najdi_dil_podle_cisla(self):
        dil = self.zaloz("ZKROZR 1", velikost_pozice_id=self.velikosti["V1"])
        self.assertEqual(repozitar.najdi_dil_podle_cisla(self.spoj, "  zkroZR  1 ")["DilID"], dil.dil_id)
        self.assertIsNone(repozitar.najdi_dil_podle_cisla(self.spoj, "ZKROZR 9"))
        self.assertIsNotNone(repozitar.najdi_dil_podle_cisla(self.spoj, "ZKROZR 1", jen_aktivni=True))
        self.deaktivuj(dil.dil_id)
        self.assertIsNone(repozitar.najdi_dil_podle_cisla(self.spoj, "ZKROZR 1", jen_aktivni=True))
        self.assertIsNotNone(repozitar.najdi_dil_podle_cisla(self.spoj, "ZKROZR 1"))
        self.assertTrue(repozitar.existuje_dil(self.spoj, "ZKROZR 1"))                # najde i vyřazený

    def test_nacti_dily_podle_id(self):
        prvni = self.zaloz("ZKHROM 1")
        druhy = self.zaloz("ZKHROM 2")
        nactene = repozitar.nacti_dily_podle_id(self.spoj, [prvni.dil_id, 2_000_000_000, druhy.dil_id])
        self.assertEqual({r["DilID"] for r in nactene}, {prvni.dil_id, druhy.dil_id})
        self.assertEqual({r["KodMaterialu"] for r in nactene}, {"S235"})
        self.assertEqual(repozitar.nacti_dily_podle_id(self.spoj, []), [])

    def test_hledani_dilu(self):
        dil = self.zaloz("ZKHULED 1", nazev="Levý bok ke hledání", velikost_pozice_id=self.velikosti["V1"])
        druhy = self.zaloz("ZKHULED 2", material_id=self.materialy["S355"], tloustka_id=self.tloustky["5.00"],
                           prvni_operace_id=self.operace["PILA"])
        self.assertEqual({r["DilID"] for r in repozitar.hledani_dilu(self.spoj, "zkhuLED")},
                         {dil.dil_id, druhy.dil_id})
        for filtr, ocekavani in (({"material": "S355"}, [druhy]), ({"tloustka_mm": Decimal("5.00")}, [druhy]),
                                 ({"prvni_operace": "PILA"}, [druhy]),
                                 ({"material": "S235"}, [dil])):
            with self.subTest(**filtr):
                self.assertEqual([r["DilID"] for r in repozitar.hledani_dilu(self.spoj, "ZK", **filtr)],
                                 [d.dil_id for d in ocekavani])
        self.assertEqual([r["DilID"] for r in repozitar.hledani_dilu(self.spoj, "ke hledání")], [dil.dil_id])
        self.assertEqual([r["DilID"] for r in repozitar.hledani_dilu(self.spoj, "ZKHULED",
                                                                    limit=1)], [dil.dil_id])
        self.deaktivuj(dil.dil_id)
        self.assertEqual([r["DilID"] for r in repozitar.hledani_dilu(self.spoj, "ZKHULED")], [druhy.dil_id])

    def test_rozhrani_ve_fazi_1_zůstává_na_vzorových_datech(self):
        """Úkol 3: skutečná SQL jsou v repozitáři, rozhraní se přepne až ve fázi 2.

        Test pozná, že čtecí funkce do databáze ještě nesahají: díl založený tady přes
        rozhraní najde a vzorový svět naopak nezná.
        """
        dil = self.zaloz("ZKROZR 2")
        self.assertEqual(rozhrani.najdi_dil(self.spoj, " aar10044 ").identifikacni_cislo, "AAR10044")
        self.assertEqual([d.identifikacni_cislo for d in rozhrani.hledej_dily(self.spoj, "aar")], ["AAR10044"])
        self.assertEqual(set(rozhrani.nacti_dily(self.spoj, [12, 2_000_000_000])), {12})    # id ze vzoru
        self.chyba(rozhrani.najdi_dil, self.spoj, "ZKROZR 2", kod="NOT_FOUND")               # DB nezná
        self.assertEqual(repozitar.nacti_dil(self.spoj, dil.dil_id)["IdentifikacniCislo"], "ZKROZR 2")
        self.assertEqual({p.kod for p in rozhrani.nacti_ciselniky(self.spoj)["materialy"]},
                         {p.kod for p in ukazky.CISELNIKY["materialy"]})
