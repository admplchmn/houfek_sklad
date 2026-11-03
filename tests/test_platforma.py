"""Testy Platformy (ostrov A): obálka, chyby, přihlášení, transakce, requestId, startovní kontroly."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from flask import Blueprint

from app.ostrovy import OSTROVY
from app.platforma import vytvor_aplikaci
from app.platforma.audit import zapis
from app.platforma.auth import kontext, vyzaduje
from app.platforma.chyby import AppError, Chyba
from app.platforma.db import Spojeni
from app.platforma.http import dokumentuj, nacti_vstup, odpoved
from app.platforma.konfigurace import Konfigurace
from app.platforma.kontrakty import Cas, Mm, SkladovyVstup, Varovani, Vystup, teď
from app.platforma.migrace_db import ADRESAR, rozdel_na_davky
from app.platforma.ostrov import Ostrov
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext
from tests.pomocnik import TestovaciDatabaze, prihlas, testovaci_aplikace

# --- testovací ostrov --------------------------------------------------------------------

POKUSY = {"pocet": 0, "deadlocku": 0}


class PrikazVstup(SkladovyVstup):
    kod: str
    pocet_ks: int


class PrikazVysledek(Vystup):
    polozka_id: int
    kod: str


class CasVystup(Vystup):
    kdy: Cas
    delka_mm: Mm


@transakce("TEST_PRIKAZ", skladova=True)
def _prikaz(spoj: Spojeni, vstup: PrikazVstup, kdo: Kontext) -> PrikazVysledek:
    POKUSY["pocet"] += 1
    if POKUSY["deadlocku"] > 0:
        POKUSY["deadlocku"] -= 1
        raise RuntimeError("Transaction (Process ID 61) was deadlocked ... (1205)")
    polozka_id = spoj.vloz("INSERT INTO dbo.SablonaPolozka (Kod, PocetKs) VALUES (?, ?)", vstup.kod, vstup.pocet_ks)
    if vstup.pocet_ks == 13:
        raise AppError("NEZNAMY_KOD")            # neregistrovaný kód → INTERNAL_ERROR, nic se nezapíše
    vysledek = PrikazVysledek(polozka_id=polozka_id, kod=vstup.kod)
    if vstup.pocet_ks > 100:
        vysledek = vysledek.model_copy(update={"varovani": (Varovani("ABOVE_MAXIMUM", "Nad maximem."),)})
    return vysledek


@transakce("TEST_JINY", skladova=True)
def _jiny(spoj: Spojeni, vstup: PrikazVstup, kdo: Kontext) -> PrikazVysledek:
    return PrikazVysledek(polozka_id=0, kod="X")


api = Blueprint("test_api", __name__)


@api.post("/prikaz")
@vyzaduje("TEST_ZAPIS")
@dokumentuj(vstup=PrikazVstup, vystup=PrikazVysledek)
def prikaz():
    vstup = nacti_vstup(PrikazVstup)
    return odpoved(_prikaz(vstup=vstup, kdo=kontext()))


@api.post("/jiny")
def jiny():
    return odpoved(_jiny(vstup=nacti_vstup(PrikazVstup), kdo=kontext()))


@api.get("/cas")
def cas():
    return odpoved(CasVystup(kdy=datetime(2026, 10, 26, 16, 59), delka_mm=Decimal("412.50")))


@api.get("/pad")
def pad():
    raise ZeroDivisionError("tajný detail")


TEST_OSTROV = Ostrov(nazev="Test", prefix="test", api=api, tabulky=["SablonaPolozka"], opravneni=["TEST_ZAPIS"],
                     chyby=[Chyba("TEST_CHYBA", 409, "Testovací chyba.")])


class ZakladTestu(unittest.TestCase):
    def setUp(self):
        POKUSY.update(pocet=0, deadlocku=0)
        self.db = TestovaciDatabaze()
        self.app = testovaci_aplikace([TEST_OSTROV], self.db)
        self.klient = self.app.test_client()

    def tearDown(self):
        self.db.smaz()

    def post(self, cesta, **telo):
        return self.klient.post(cesta, json=telo)


class TestObalkaAChyby(ZakladTestu):
    def test_zdravi_je_verejne_a_ma_obalku(self):
        odpoved_ = self.klient.get("/api/system/zdravi")
        self.assertEqual(odpoved_.status_code, 200)
        self.assertEqual(set(odpoved_.json), {"success", "code", "message", "data", "transakceId", "varovani"})
        self.assertEqual(odpoved_.json["data"]["databaze"], "OK")

    def test_neznama_cesta(self):
        odpoved_ = self.klient.get("/api/nic")
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (404, "NOT_FOUND"))

    def test_bez_prihlaseni(self):
        odpoved_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=1)
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (401, "NOT_AUTHENTICATED"))

    def test_bez_opravneni(self):
        prihlas(self.klient)
        odpoved_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=1)
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (403, "NO_PERMISSION"))
        self.assertEqual(odpoved_.json["data"]["chybiOpravneni"], ["TEST_ZAPIS"])

    def test_validace_podle_poli(self):
        prihlas(self.klient, "TEST_ZAPIS")
        odpoved_ = self.post("/api/test/prikaz", kod="A", pocetKs="x", navic=1)
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (400, "VALIDATION_ERROR"))
        pole = {c["pole"] for c in odpoved_.json["data"]["chyby"]}
        self.assertEqual(pole, {"requestId", "pocetKs", "navic"})

    def test_neocekavana_chyba_neprozradi_detail(self):
        prihlas(self.klient)
        odpoved_ = self.klient.get("/api/test/pad")
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (500, "INTERNAL_ERROR"))
        self.assertNotIn("tajný", json.dumps(odpoved_.json, ensure_ascii=False))

    def test_cas_a_milimetry(self):
        prihlas(self.klient)
        data = self.klient.get("/api/test/cas").json["data"]
        # DATETIME2 je UTC (TD-11), najevo jde místní čas s posunem: 16:59 UTC = 17:59 v Praze
        self.assertEqual(data["kdy"], "2026-10-26T17:59:00+01:00")
        self.assertEqual(data["delkaMm"], 412.5)


class TestCasovaKonvence(unittest.TestCase):
    """TD-11: DATETIME2 drží UTC, najevo se vždy místní čas s posunem (nikoli dvojznačný čas)."""

    @staticmethod
    def _json(hodnota: datetime) -> str:
        return CasVystup(kdy=hodnota, delka_mm=Decimal("1")).model_dump(mode="json")["kdy"]

    def test_utc_se_ukazuje_prazskym_casem(self):
        letni = self._json(datetime(2026, 6, 1, 12, 0))
        zimni = self._json(datetime(2026, 1, 1, 12, 0))
        self.assertEqual((letni, zimni), ("2026-06-01T14:00:00+02:00", "2026-01-01T13:00:00+01:00"))

    def test_prechod_na_zimni_cas_neni_dvojzceny(self):
        """Dva pohyby se stejným místním časem při přechodu na zimní čas mají různé UTC i posun."""
        pred, po = self._json(datetime(2026, 10, 25, 0, 30)), self._json(datetime(2026, 10, 25, 1, 30))
        self.assertEqual((pred, po), ("2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"))

    def test_ted_vraci_naivni_utc(self):
        """Naive, protože naive vrací i čtení z DATETIME2; UTC, protože bázi nesmí určovat stroj."""
        self.assertIsNone(teď().tzinfo)
        odpocet = abs((datetime.now(timezone.utc).replace(tzinfo=None) - teď()).total_seconds())
        self.assertLess(odpocet, 5)


class TestTransakce(ZakladTestu):
    def test_uspech_vraci_transakci_a_uklada_hlavicku(self):
        prihlas(self.klient, "TEST_ZAPIS")
        odpoved_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=150)
        self.assertEqual(odpoved_.json["code"], "OK", odpoved_.json)
        self.assertIsNotNone(odpoved_.json["transakceId"])
        self.assertEqual(odpoved_.json["varovani"], [{"code": "ABOVE_MAXIMUM", "message": "Nad maximem."}])
        self.assertEqual(self.db.hodnota("SELECT COUNT(*) FROM dbo.SkladovaTransakce"), 1)

    def test_stejny_request_id_nezapise_dvakrat(self):
        prihlas(self.klient, "TEST_ZAPIS")
        request_id = str(uuid.uuid4())
        prvni = self.post("/api/test/prikaz", requestId=request_id, kod="A", pocetKs=150)
        druhy = self.post("/api/test/prikaz", requestId=request_id, kod="A", pocetKs=150)
        self.assertEqual(druhy.json, prvni.json)
        self.assertEqual(POKUSY["pocet"], 1)
        self.assertEqual(self.db.hodnota("SELECT COUNT(*) FROM dbo.SablonaPolozka"), 1)

    def test_request_id_jine_operace(self):
        prihlas(self.klient, "TEST_ZAPIS")
        request_id = str(uuid.uuid4())
        self.post("/api/test/prikaz", requestId=request_id, kod="A", pocetKs=1)
        odpoved_ = self.post("/api/test/jiny", requestId=request_id, kod="A", pocetKs=1)
        self.assertEqual(odpoved_.json["code"], "VALIDATION_ERROR")

    def test_chyba_vrati_vse_zpet(self):
        prihlas(self.klient, "TEST_ZAPIS")
        odpoved_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=13)
        self.assertEqual(odpoved_.json["code"], "INTERNAL_ERROR")   # neregistrovaný kód
        self.assertEqual(self.db.hodnota("SELECT COUNT(*) FROM dbo.SablonaPolozka"), 0)
        self.assertEqual(self.db.hodnota("SELECT COUNT(*) FROM dbo.SkladovaTransakce"), 0)

    def test_deadlock_se_zopakuje(self):
        prihlas(self.klient, "TEST_ZAPIS")
        POKUSY["deadlocku"] = 2
        odpoved_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=1)
        self.assertEqual(odpoved_.json["code"], "OK")
        self.assertEqual(POKUSY["pocet"], 3)

    def test_trvaly_deadlock(self):
        prihlas(self.klient, "TEST_ZAPIS")
        POKUSY["deadlocku"] = 5
        odpoved_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=1)
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (409, "CONCURRENT_CHANGE"))
        self.assertEqual(self.db.hodnota("SELECT COUNT(*) FROM dbo.SablonaPolozka"), 0)

    def test_porušeni_unique_je_soubeh(self):
        prihlas(self.klient, "TEST_ZAPIS")
        self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=1)
        odpoved_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="A", pocetKs=1)
        self.assertEqual(odpoved_.json["code"], "CONCURRENT_CHANGE")


class TestAuditAPrihlaseni(ZakladTestu):
    def test_audit_zapis(self):
        spoj = Spojeni(self.db.pripoj(), "sqlite")
        kdo = Kontext(1, None, "ADMIN", frozenset())
        audit_id = zapis(spoj, kdo, "DIL", 12, "VelikostPoziceID", 1, 2, "Změna dávky")
        spoj._commit()
        spoj._zavri()
        self.assertGreater(audit_id, 0)
        self.assertEqual(self.db.hodnota("SELECT NovaHodnota FROM dbo.AuditZmen WHERE AuditID = ?", audit_id), "2")
        spoj = Spojeni(self.db.pripoj(), "sqlite")
        try:
            with self.assertRaises(ValueError):
                zapis(spoj, kdo, "díl", 1, "x", None, None)
        finally:
            spoj._zavri()

    def test_vyvojove_prihlaseni(self):
        odpoved_ = self.post("/api/system/vyvojove-prihlaseni", uzivatelId=1)
        self.assertEqual(odpoved_.json["code"], "OK")
        self.assertIn("TEST_ZAPIS", odpoved_.json["data"]["opravneni"])
        zapis_ = self.post("/api/test/prikaz", requestId=str(uuid.uuid4()), kod="B", pocetKs=1)
        self.assertEqual(zapis_.json["code"], "OK")

    def test_vyvojove_prihlaseni_v_provozu_neexistuje(self):
        app = vytvor_aplikaci([TEST_OSTROV], Konfigurace(vyvoj=False, tajny_klic="k" * 40),
                              tovarna_db=self.db.tovarna())
        odpoved_ = app.test_client().post("/api/system/vyvojove-prihlaseni", json={"uzivatelId": 1})
        self.assertEqual(odpoved_.json["code"], "NOT_FOUND")


class TestStartovniKontroly(unittest.TestCase):
    def test_skutecne_ostrovy_do_sebe_zapadaji(self):
        db = TestovaciDatabaze()
        try:
            app = testovaci_aplikace(OSTROVY, db)
            self.assertEqual(len(app.extensions["houfek_ostrovy"].ostrovy), 1 + len(OSTROVY))
            vlastnici = [t for o in app.extensions["houfek_ostrovy"].ostrovy for t in o.tabulky]
            self.assertEqual(len(vlastnici), 30)   # 28 ze schématu G1 + SkladovaTransakce + MigraceSchema
            self.assertEqual(len(set(vlastnici)), 30)
        finally:
            db.smaz()

    def over_selhani(self, *ostrovy, text):
        with self.assertRaises((RuntimeError, ValueError)) as chyba:
            vytvor_aplikaci(list(ostrovy), Konfigurace(vyvoj=True), tovarna_db=lambda: None)
        self.assertIn(text, str(chyba.exception))

    def test_duplicitni_prefix(self):
        self.over_selhani(TEST_OSTROV, Ostrov("Druhy", "test", api=Blueprint("b2", __name__)), text="prefix")

    def test_dva_vlastnici_tabulky(self):
        druhy = Ostrov("Druhy", "druhy", api=Blueprint("b3", __name__), tabulky=["SablonaPolozka"])
        self.over_selhani(TEST_OSTROV, druhy, text="SablonaPolozka")

    def test_duplicitni_chybovy_kod(self):
        self.over_selhani(Ostrov("Druhy", "druhy", api=Blueprint("b4", __name__),
                                 chyby=[Chyba("NOT_FOUND", 404, "x")]), text="NOT_FOUND")


class TestKonfiguraceAMigrace(unittest.TestCase):
    def test_pripojovaci_retezec(self):
        konf = Konfigurace.z_prostredi({
            "HOUFEK_DB_SERVER": "SRVACC01.houfek.local", "HOUFEK_DB_NAZEV": "HoufekSklad_DEV",
            "HOUFEK_DB_UZIVATEL": "houfek_sklad", "HOUFEK_DB_HESLO": "a}b;c",
            "HOUFEK_DB_DUVEROVAT_CERTIFIKATU": "ano"})
        retezec = konf.pripojovaci_retezec()
        self.assertIn("SERVER=SRVACC01.houfek.local;", retezec)
        self.assertIn("PWD={a}}b;c};", retezec)
        self.assertIn("Encrypt=yes;TrustServerCertificate=yes;", retezec)

    def test_provoz_vyzaduje_tajny_klic(self):
        with self.assertRaises(RuntimeError):
            Konfigurace(vyvoj=False, tajny_klic="kratky").over()

    def test_davky_schematu_g1(self):
        text = (ADRESAR / "001_schema_g1.sql").read_text(encoding="utf-8")
        davky = rozdel_na_davky(text)
        self.assertEqual(len(davky), 9)
        self.assertIn("CREATE VIEW dbo.v_KontrolaIntegrity", davky[5])

    def test_go_v_komentari_nedeli(self):
        davky = rozdel_na_davky("SELECT 1\n/*\nGO\n*/\nSELECT 2\nGO\nSELECT 3\ngo -- konec\n")
        self.assertEqual(len(davky), 2)

    def test_migrace_jsou_cislovane(self):
        nazvy = sorted(p.name for p in Path(ADRESAR).glob("*.sql"))
        self.assertEqual(nazvy[:2], ["001_schema_g1.sql", "002_skladova_transakce.sql"])


if __name__ == "__main__":
    unittest.main()
