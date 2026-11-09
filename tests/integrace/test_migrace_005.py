"""Integrační test migrace 005 – rozhodnutí vedoucího projektu z 9. 11. (D-18, D-23, D-26).

Ověřuje, co v migračním skriptu bez SQL Serveru lokálně nepoznáme: že seed rolí odpovídá
matici G4, že CHECK nepustí jiný způsob potvrzení cíle než SKEN a RUCNE a že položka
inventury odkazuje jen na skutečný pohyb.

Seed se testuje uvnitř transakce testu: test si oprávnění smaže a sám je založí ze souboru
005, proto nezávisí na pořadí testů ani na tom, co v databázi zanechaly (testy ostrova B si
rolím oprávnění přiřazují samy a potvrzují je přes `spojeni_pro_skript()`). Porušení omezení
zahodí celou transakci spojení (XACT_ABORT), proto test, který chybu čeká, už pak nic nedělá.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.platforma.migrace_db import rozdel_na_davky
from tests.integrace.zaklad import ZakladIntegrace
from tests.test_migrace import _bez_komentaru

SOUBOR_005 = Path(__file__).resolve().parents[2] / "sql" / "migrace" / "005_rozhodnuti_9_11.sql"
NEEXISTUJE = 2_000_000_000        # takové PohybID nemůže existovat → FK 547

# matice G4 (D-23, docs/soulad-se-zadanim.md): oprávnění → role, které k nim patří
MATICE_G4 = {
    "DIL_CIST": ("OPER", "SKL", "MISTR", "TECH", "ADMIN"),
    "SKLAD_PRIJEM": ("OPER", "SKL", "MISTR", "ADMIN"),
    "SKLAD_VYDEJ": ("OPER", "SKL", "MISTR", "ADMIN"),
    "SKLAD_PRESUN": ("SKL", "MISTR", "ADMIN"),
    "INVENTURA": ("SKL", "MISTR", "ADMIN"),
    "KOREKCE": ("MISTR", "ADMIN"),
    "BOX_EDIT": ("ADMIN",),
    "UZIVATEL_EDIT": ("ADMIN",),
    "BLOKACE": ("SKL", "MISTR", "ADMIN"),
    "RUCNI_POTVRZENI": ("MISTR", "ADMIN"),
    "UPOZORNENI_UZAVRIT": ("MISTR", "ADMIN"),
    "KMEN_EDIT": ("TECH", "ADMIN"),
    "STAT_EDIT": ("TECH", "ADMIN"),
    "AUDIT_CIST": ("MISTR", "TECH", "ADMIN"),
}
OPRAVNENI_ROLI = {(role, kod) for kod in MATICE_G4 for role in MATICE_G4[kod]}


def _davka_seedu() -> str:
    """Dávka seedu RoleOpravneni ze souboru 005 – přesně ta, kterou migrace spustí (dávky podle GO)."""
    for davka in rozdel_na_davky(SOUBOR_005.read_text(encoding="utf-8-sig")):
        if _bez_komentaru(davka).lstrip().startswith("INSERT INTO dbo.RoleOpravneni"):
            return davka
    raise AssertionError(f"{SOUBOR_005.name} neobsahuje dávku seedu dbo.RoleOpravneni")


SEED_G4 = _davka_seedu()


class TestMigrace005(ZakladIntegrace):
    # --- pomocná data ------------------------------------------------------------------------

    def _opravneni_roli(self) -> set[tuple[str, str]]:
        """[(kód role, kód oprávnění)] tak, jak je má databáze."""
        return {(radek["KodRole"], radek["KodOpravneni"]) for radek in self.spoj.dotaz(
            "SELECT r.KodRole, o.KodOpravneni FROM dbo.RoleOpravneni AS ro "
            "JOIN dbo.Role AS r ON r.RoleID = ro.RoleID "
            "JOIN dbo.Opravneni AS o ON o.OpravneniID = ro.OpravneniID")}

    def _misto_a_dil(self) -> tuple[int, int]:
        """Prázdné místo (regál → úroveň → pozice → box → vnitřní pozice) a díl pro pohyby.

        Kódy jsou jedinečné podle náhodné značky, aby data, která v databázi potvrdily jiné
        testy, nepřekážela. Vrací (VnitrniPoziceID, DilID).
        """
        znak = uuid.uuid4().hex[:5].upper()
        kod_boxu = f"BSTAT{uuid.uuid4().int % 10_000_000:07d}"
        regal = self.spoj.vloz("INSERT INTO dbo.Regal (PracovisteID, KodRegalu) "
                               "VALUES ((SELECT MIN(PracovisteID) FROM dbo.Pracoviste), ?)", f"R{znak}")
        uroven = self.spoj.vloz("INSERT INTO dbo.Uroven (RegalID, KodUrovne, Poradi, DelkaPlochyMM, "
                                "HloubkaPlochyMM) VALUES (?, ?, 1, 1000, 500)", regal, f"U{znak}")
        pozice = self.spoj.vloz("INSERT INTO dbo.Pozice (UrovenID, Poradi) VALUES (?, 1)", uroven)
        box = self.spoj.vloz("INSERT INTO dbo.Box (PoziceID, KodBoxu, TypBoxuID, CleneniBoxuID, DelkaMM, "
                             "HloubkaMM, FullBoxKlic) VALUES (?, ?, "
                             "(SELECT TypBoxuID FROM dbo.TypBoxu WHERE KodTypu = 'STAT'), "
                             "(SELECT CleneniBoxuID FROM dbo.CleneniBoxu WHERE KodCleneni = 'C1'), 100, 100, ?)",
                             pozice, kod_boxu, f"TEST-{znak}-{kod_boxu}")
        misto = self.spoj.vloz("INSERT INTO dbo.VnitrniPoziceBoxu (BoxID, SablonaCleneniID, KodPozice, "
                               "VelikostPoziceID) SELECT ?, s.SablonaCleneniID, s.StatKod, s.VelikostPoziceID "
                               "FROM dbo.Box AS b JOIN dbo.SablonaCleneni AS s ON s.CleneniBoxuID = b.CleneniBoxuID "
                               "WHERE b.BoxID = ? AND s.StatKod = '1'", box, box)
        dil = self.spoj.vloz("INSERT INTO dbo.Dil (IdentifikacniCislo) VALUES (?)", f"TEST-{znak}")
        return misto, dil

    def _pohyb(self, vnitrni_pozice_id: int, dil_id: int, zpusob_potvrzeni: str | None) -> int:
        """Příjem 1 ks s udaným způsobem potvrzení cíle; sloupec se plní jen při INSERT (D-18)."""
        return self.spoj.vloz(
            "INSERT INTO dbo.SkladovyPohyb (TypPohybuID, DilID, VnitrniPoziceID, Mnozstvi, StavPred, StavPo, "
            "UzivatelID, ZpusobPotvrzeni) VALUES ((SELECT TypPohybuID FROM dbo.TypPohybu WHERE KodPohybu = "
            "'PRIJEM'), ?, ?, 1, 0, 1, ?, ?)",
            dil_id, vnitrni_pozice_id, self.uzivatel_testu(), zpusob_potvrzeni)

    def _inventura(self) -> int:
        """Rozpracovaná inventura celého skladu; vrací InventuraID."""
        return self.spoj.vloz("INSERT INTO dbo.Inventura (TypRozsahu, StavInventury, ZalozilUzivatelID) "
                              "VALUES ('FULL', 'ROZPRACOVANA', ?)", self.uzivatel_testu())

    # --- seed oprávnění rolí (D-23) ----------------------------------------------------------

    def test_seed_roleopravneni_odpovida_matici_g4(self):
        self.spoj.proved("DELETE FROM dbo.RoleOpravneni")
        self.spoj.proved(SEED_G4)
        self.assertEqual(self._opravneni_roli(), OPRAVNENI_ROLI)
        self.spoj.proved(SEED_G4)     # „jen chybějící řádky“: podruhý nepřidá nic, aby nenarazil na PK
        self.assertEqual(self._opravneni_roli(), OPRAVNENI_ROLI)

    # --- způsob potvrzení cíle (D-18) --------------------------------------------------------

    def test_zpusob_potvrzeni_se_ulozi(self):
        """SKEN i RUCNE se uloží; NULL je pohyb, který cíl nepotvrzuje (výdej, korekce, počáteční stav)."""
        misto, dil = self._misto_a_dil()
        for zpusob in ("SKEN", "RUCNE", None):
            pohyb = self._pohyb(misto, dil, zpusob)
            self.assertEqual(self.spoj.hodnota(
                "SELECT ZpusobPotvrzeni FROM dbo.SkladovyPohyb WHERE PohybID = ?", pohyb), zpusob)

    def test_zpusob_potvrzeni_jiny_kod_server_odmitne(self):
        misto, dil = self._misto_a_dil()
        with self.assertRaises(Exception) as zachyceno:
            self._pohyb(misto, dil, "POTVRZENO")
        self.assertIn("CK_SkladovyPohyb_ZpusobPotvrzeni", str(zachyceno.exception))

    # --- inventura za provozu (D-26, TD-25) --------------------------------------------------

    def test_posledni_pohyb_id_odkazuje_na_pohyb(self):
        """Položka si při fyzické kontrole uloží poslední pohyb pozice, podle něj pozná změny."""
        misto, dil = self._misto_a_dil()
        polozka = self.spoj.vloz("INSERT INTO dbo.InventuraPolozka (InventuraID, VnitrniPoziceID, "
                                 "OcekavanyPocetKs) VALUES (?, ?, 0)", self._inventura(), misto)
        pohyb = self._pohyb(misto, dil, "SKEN")
        self.spoj.proved("UPDATE dbo.InventuraPolozka SET PosledniPohybID = ? WHERE InventuraPolozkaID = ?",
                         pohyb, polozka)
        self.assertEqual(self.spoj.hodnota(
            "SELECT PosledniPohybID FROM dbo.InventuraPolozka WHERE InventuraPolozkaID = ?", polozka), pohyb)

    def test_posledni_pohyb_id_musi_existovat(self):
        inventura = self._inventura()
        misto, _ = self._misto_a_dil()
        with self.assertRaises(Exception) as zachyceno:
            self.spoj.proved("INSERT INTO dbo.InventuraPolozka (InventuraID, VnitrniPoziceID, OcekavanyPocetKs, "
                             "PosledniPohybID) VALUES (?, ?, 0, ?)", inventura, misto, NEEXISTUJE)
        self.assertIn("FK_InventuraPolozka_SkladovyPohyb", str(zachyceno.exception))
