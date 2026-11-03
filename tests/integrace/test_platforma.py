"""Integrační testy Platformy proti SQL Serveru (TD-01): migrace, pohledy, zámky, requestId."""
from __future__ import annotations

import uuid

from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.db import spojeni_pro_skript
from app.platforma.kontrakty import SkladovyVstup, Vystup
from app.platforma.sql_chyby import je_limit_zamku
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext
from tests.integrace.zaklad import ZakladIntegrace
from tests.test_migrace import MIGRACE, _pohledy_v, _vystupni_sloupce


class ZkusebniVstup(SkladovyVstup):
    poznamka: str


class ZkusebniVysledek(Vystup):
    poznamka: str


@transakce("ZKOUSKA_INTEGRACE", skladova=True)
def _zkusebni_operace(spoj, vstup: ZkusebniVstup, kdo: Kontext) -> ZkusebniVysledek:
    return ZkusebniVysledek(poznamka=vstup.poznamka)


class TestSchema(ZakladIntegrace):
    def test_vsechny_migrace_provedene(self):
        provedene = {r["Soubor"] for r in self.spoj.dotaz("SELECT Soubor FROM dbo.MigraceSchema")}
        self.assertEqual(provedene, {s.name for s in MIGRACE})

    def test_pohledy_vraceji_sloupce_kontraktu(self):
        for skript in MIGRACE:
            for nazev, telo in _pohledy_v(skript.read_text(encoding="utf-8")):
                kurzor = self.spoj.kurzor()
                kurzor.execute(f"SELECT TOP 0 * FROM dbo.{nazev}")
                self.assertEqual({s[0] for s in kurzor.description}, _vystupni_sloupce(telo), nazev)
                kurzor.close()

    def test_kontrola_integrity_na_vychozich_datech(self):
        self.assertEqual(self.spoj.dotaz("SELECT Kontrola, Popis FROM dbo.v_KontrolaIntegrity"), [])

    def test_vychozi_data_sablony(self):
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.SablonaCleneni"), 19)
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.Opravneni"), 14)


class TestZamky(ZakladIntegrace):
    def test_zamek_neexistujici_pozice(self):
        with self.assertRaises(AppError) as zachyceno:
            struktura.zamkni_mista(self.spoj, [2_000_000_000])
        self.assertEqual(zachyceno.exception.kod, "NOT_FOUND")

    def test_vyprseni_zamku_je_chyba_1222(self):
        """Druhé spojení na zamčený řádek po LOCK_TIMEOUT dostane 1222 → CONCURRENT_CHANGE (ADR-0005)."""
        self.spoj.jeden("SELECT FirmaID FROM dbo.Firma WITH (UPDLOCK, HOLDLOCK) WHERE KodFirmy = 'HOUFEK'")
        druhe = self.druhe_spojeni()
        druhe.proved("SET LOCK_TIMEOUT 200;")
        with self.assertRaises(Exception) as zachyceno:
            druhe.jeden("SELECT FirmaID FROM dbo.Firma WITH (UPDLOCK) WHERE KodFirmy = 'HOUFEK'")
        self.assertTrue(je_limit_zamku(zachyceno.exception), zachyceno.exception)


class TestRequestId(ZakladIntegrace):
    def uzivatel_testu(self) -> int:
        """Neaktivní technický uživatel pro FK SkladovaTransakce.UzivatelID (potvrdí se, přihlásit se nedá)."""
        with spojeni_pro_skript() as spoj:
            uzivatel_id = spoj.hodnota("SELECT UzivatelID FROM dbo.Uzivatel WHERE OsobniCislo = 'TEST-INTEGRACE'")
            if uzivatel_id is None:
                uzivatel_id = spoj.vloz(
                    "INSERT INTO dbo.Uzivatel (OsobniCislo, Jmeno, Prijmeni, RoleID, Aktivni) "
                    "SELECT 'TEST-INTEGRACE', N'Integrační', N'Test', RoleID, 0 FROM dbo.Role WHERE KodRole = 'ADMIN'")
        return int(uzivatel_id)

    def test_stejny_request_id_vrati_ulozeny_vysledek(self):
        kdo = Kontext(self.uzivatel_testu(), None, "ADMIN", frozenset())
        vstup = ZkusebniVstup(request_id=uuid.uuid4(), poznamka="integrace")
        prvni = _zkusebni_operace(vstup=vstup, kdo=kdo)
        druhy = _zkusebni_operace(vstup=vstup, kdo=kdo)
        self.assertEqual((druhy.transakce_id, druhy.poznamka), (prvni.transakce_id, "integrace"))
        with self.assertRaises(AppError) as zachyceno:
            _zkusebni_operace(vstup=vstup.model_copy(update={"poznamka": "jiný obsah"}), kdo=kdo)
        self.assertEqual(zachyceno.exception.kod, "VALIDATION_ERROR")
