"""Testy k nálezům code review fáze 0 (CR-xx, záznam jiz_nepotrebne/revize/2026-10-26-code-review.md)
a ke splacenému technickému dluhu (docs/technicky-dluh.md, TD-xx).

Každá třída odpovídá jednomu nálezu, aby se oprava nemohla potichu vrátit. Testy dokumentace
hlídají, že příručky drží krok s kódem (proměnné prostředí, odkazy).
"""
from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
import tempfile
import unittest
import uuid
from collections import Counter
from pathlib import Path
from unittest import mock

from flask import Blueprint
from pydantic import BaseModel

from app.ostrovy import OSTROVY
from app.platforma import vytvor_aplikaci
from app.platforma.auth import kontext
from app.platforma.db import Spojeni, po_davkach
from app.platforma.http import dokumentuj, nacti_vstup, odpoved
from app.platforma.konfigurace import Konfigurace
from app.platforma.kontrakty import SkladovyVstup, Vystup
from app.platforma.openapi import vytvor_openapi
from app.platforma.ostrov import Ostrov
from app.platforma.sql_chyby import je_deadlock, je_duplicita, je_limit_zamku, je_nedostupnost
from app.platforma.transakce import transakce
from app.platforma.typy import Kontext
from tests.pomocnik import PLATFORMA_SQLITE, TestovaciDatabaze, prihlas, testovaci_aplikace


class ChybaOdbc(Exception):
    """Napodobí výjimku pyodbc: args = (SQLSTATE, zpráva)."""


def odbc(sqlstate: str, zprava: str) -> ChybaOdbc:
    return ChybaOdbc(sqlstate, zprava)


# --- CR-05: přesné rozpoznání chyb SQL Serveru -----------------------------------------------

class TestRozpoznaniChyb(unittest.TestCase):
    def test_deadlock(self):
        self.assertTrue(je_deadlock(odbc("40001", "[SQL Server]Transaction (Process ID 52) was deadlocked "
                                                 "on lock resources. Rerun the transaction. (1205) (SQLExecDirectW)")))

    def test_hodnota_klice_neni_kod_chyby(self):
        chyba = odbc("23000", "[SQL Server]Violation of UNIQUE KEY constraint 'UQ_Dil'. Cannot insert duplicate "
                              "key in object 'dbo.Dil'. The duplicate key value is (1205). (2627) (SQLExecDirectW)")
        self.assertFalse(je_deadlock(chyba))
        self.assertTrue(je_duplicita(chyba))

    def test_limit_zamku_a_nedostupnost(self):
        self.assertTrue(je_limit_zamku(odbc("HY000", "[SQL Server]Lock request time out period exceeded. (1222) "
                                                     "(SQLExecDirectW)")))
        self.assertTrue(je_nedostupnost(odbc("08001", "[Microsoft][ODBC Driver 18]TCP Provider: timeout")))
        self.assertTrue(je_nedostupnost(odbc("HYT00", "[Microsoft][ODBC Driver 18]Query timeout expired")))
        self.assertFalse(je_nedostupnost(ValueError("08001")))


# --- CR-01: chyba pozdějšího příkazu dávky se nesmí ztratit ------------------------------------

class FalesnyKurzor:
    """Napodobí pyodbc: druhá sada výsledků dávky vyvolá chybu až při nextset()."""

    def __init__(self, sady):
        self.sady = list(sady)
        self.description = None
        self.rowcount = 1
        self._nastav()

    def _nastav(self):
        sada = self.sady[0]
        if isinstance(sada, Exception):
            raise sada
        self.description = [("NoveID",)] if sada is not None else None
        self._radky = [(sada,)] if sada is not None else []

    def execute(self, sql, parametry):
        self.sql = sql

    def fetchall(self):
        return self._radky

    def fetchone(self):
        return self._radky[0] if self._radky else None

    def nextset(self):
        self.sady.pop(0)
        if not self.sady:
            return False
        self._nastav()
        return True


class FalesnePripojeni:
    def __init__(self, kurzor):
        self.k = kurzor

    def cursor(self):
        return self.k


class TestDavky(unittest.TestCase):
    def test_proved_vyvola_chybu_pozdejsiho_prikazu(self):
        kurzor = FalesnyKurzor([None, ChybaOdbc("42000", "Incorrect syntax (102)")])
        with self.assertRaises(ChybaOdbc):
            Spojeni(FalesnePripojeni(kurzor), "mssql").proved("CREATE TABLE …; CREATE INDEX …")

    def test_vloz_najde_nove_id_az_v_dalsi_sade(self):
        kurzor = FalesnyKurzor([None, 42])   # 1. sada = počet řádků INSERTu, 2. = SELECT SCOPE_IDENTITY()
        nove_id = Spojeni(FalesnePripojeni(kurzor), "mssql").vloz("INSERT INTO dbo.X (A) VALUES (?);", 1)
        self.assertEqual(nove_id, 42)
        self.assertNotIn("NOCOUNT", kurzor.sql)

    def test_po_davkach(self):
        self.assertEqual([len(d) for d in po_davkach(list(range(2500)))], [1000, 1000, 500])


# --- CR-03, CR-07, CR-08, CR-17: bezpečnost -----------------------------------------------------

class TestBezpecnost(unittest.TestCase):
    def setUp(self):
        self.db = TestovaciDatabaze()

    def tearDown(self):
        self.db.smaz()

    def test_vyvoj_ma_nahodny_klic(self):
        a = testovaci_aplikace([], self.db)
        b = testovaci_aplikace([], self.db)
        self.assertNotEqual(a.config["SECRET_KEY"], b.config["SECRET_KEY"])
        self.assertGreaterEqual(len(a.config["SECRET_KEY"]), 64)

    def test_bezpecnostni_hlavicky_a_cache(self):
        odpoved_ = testovaci_aplikace([], self.db).test_client().get("/api/system/zdravi")
        self.assertEqual(odpoved_.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(odpoved_.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(odpoved_.headers["Cache-Control"], "no-store")
        self.assertEqual(odpoved_.json["data"]["rezim"], "VYVOJ")

    def test_prilis_velky_pozadavek(self):
        klient = testovaci_aplikace([], self.db).test_client()
        odpoved_ = klient.post("/api/system/vyvojove-prihlaseni", data="x" * 1_100_000,
                               content_type="application/json")
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (413, "PAYLOAD_TOO_LARGE"))

    def test_swagger_jen_ve_vyvoji(self):
        provoz = vytvor_aplikaci([], Konfigurace(vyvoj=False, tajny_klic="k" * 40), tovarna_db=self.db.tovarna())
        self.assertEqual(provoz.test_client().get("/api/docs").status_code, 404)
        self.assertEqual(testovaci_aplikace([], self.db).test_client().get("/api/docs").status_code, 200)

    def test_odbc_hodnoty_nerozbiji_retezec(self):
        konf = Konfigurace(db_server="srv;Trusted_Connection=yes", db_nazev="Sklad", db_uzivatel="app",
                           db_heslo="x", db_uzivatel_migrace="owner", db_heslo_migrace="y")
        self.assertIn("SERVER={srv;Trusted_Connection=yes};", konf.pripojovaci_retezec())
        self.assertIn("UID=owner;", konf.pripojovaci_retezec_migrace())
        bez_uctu_migrace = Konfigurace(db_server="s", db_nazev="d", db_uzivatel="app")
        self.assertIn("UID=app;", bez_uctu_migrace.pripojovaci_retezec_migrace())


# --- provoz: soubor konfigurace pro web, noční úlohu i správce ----------------------------------

class TestSouborKonfigurace(unittest.TestCase):
    def setUp(self):
        self.adresar = tempfile.mkdtemp(prefix="houfek_konf_")
        self.soubor = os.path.join(self.adresar, "houfek.env")
        with open(self.soubor, "w", encoding="utf-8") as f:
            f.write("HOUFEK_DB_SERVER=SRVACC01.houfek.local\nHOUFEK_DB_NAZEV=HoufekSklad\nHOUFEK_DB_HESLO=a;b\n")

    def tearDown(self):
        shutil.rmtree(self.adresar, ignore_errors=True)

    def test_soubor_se_nacte_a_prostredi_ma_prednost(self):
        prostredi = {"HOUFEK_KONFIGURACE_SOUBOR": self.soubor, "HOUFEK_DB_NAZEV": "HoufekSklad_DEV"}
        with mock.patch.dict(os.environ, prostredi, clear=True):
            konf = Konfigurace.z_prostredi()
        self.assertEqual((konf.db_server, konf.db_nazev, konf.db_heslo),
                         ("SRVACC01.houfek.local", "HoufekSklad_DEV", "a;b"))

    def test_chybejici_soubor_je_chyba(self):
        with mock.patch.dict(os.environ, {"HOUFEK_KONFIGURACE_SOUBOR": self.soubor + ".x"}, clear=True):
            with self.assertRaises(RuntimeError):
                Konfigurace.z_prostredi()


class TestDokumentaceKonfigurace(unittest.TestCase):
    """Dokumentace drží krok s kódem: každá proměnná je v .env.priklad i v provozní příručce."""

    def test_promenne_jsou_zdokumentovane(self):
        koren = Path(__file__).resolve().parents[1]
        kod = (koren / "app/platforma/konfigurace.py").read_text(encoding="utf-8")
        ctene = set(re.findall(r'p\.get\("(HOUFEK_[A-Z_]+)"', kod))
        priklad = set(re.findall(r"^(HOUFEK_[A-Z_]+)=", (koren / ".env.priklad").read_text(encoding="utf-8"), re.M))
        provoz = (koren / "docs/provoz.md").read_text(encoding="utf-8")
        testovaci = {v for v in priklad if v.startswith("HOUFEK_TEST_DB_")}   # čte harness tests/integrace
        self.assertEqual(ctene, priklad - testovaci, ".env.priklad neodpovídá Konfigurace.z_prostredi")
        self.assertEqual({v.replace("HOUFEK_TEST_DB_", "HOUFEK_DB_") for v in testovaci} - ctene, set(),
                         "HOUFEK_TEST_DB_X musí odpovídat proměnné HOUFEK_DB_X")
        self.assertEqual(sorted(v for v in ctene | {"HOUFEK_KONFIGURACE_SOUBOR"} if v not in provoz), [],
                         "proměnné chybí v docs/provoz.md")

    def test_odkazy_v_dokumentaci_vedou_na_existujici_soubory(self):
        koren = Path(__file__).resolve().parents[1]
        rozbite = []
        for md in [koren / "README.md", koren / "AGENTS.md", *(koren / "docs").rglob("*.md")]:
            for odkaz in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
                if not odkaz.startswith(("http://", "https://", "mailto:")) and not (md.parent / odkaz).exists():
                    rozbite.append(f"{md.relative_to(koren)} → {odkaz}")
        self.assertEqual(rozbite, [])


class TestDokumentacePoctu(unittest.TestCase):
    """CR-33: počty endpointů v README odpovídají aplikaci – u každého ostrova i dohromady."""

    def test_pocty_endpointu_v_readme(self):
        app = vytvor_aplikaci(OSTROVY, Konfigurace(vyvoj=True))
        try:
            cesty = vytvor_openapi(app)["paths"]
        finally:
            app.extensions["houfek_kostra_db"].smaz()
        pocty = Counter(cesta.split("/")[2] for cesta, metody in cesty.items()
                        for metoda in metody if metoda in {"get", "post", "put", "patch", "delete"})
        ostrovy = {prefix: pocet for prefix, pocet in pocty.items() if prefix not in {"system", "docs", "openapi.json"}}

        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        uvedene = {slozka: int(pocet) for slozka, pocet in
                   re.findall(r"\| `app/ostrovy/(\w+)` \|[^|\n]*\| kontrakt (\d+) endpoint", readme)}
        self.assertEqual(uvedene, ostrovy, "tabulka Ostrovy v README neodpovídá endpointům aplikace")
        celkem = re.search(r"HTTP kontrakt: (\d+) endpoint", readme)
        self.assertIsNotNone(celkem, "README neuvádí celkový počet endpointů ostrovů")
        self.assertEqual(int(celkem[1]), sum(ostrovy.values()))


# --- CR-09: databáze nedostupná ---------------------------------------------------------------

class TestNedostupnaDatabaze(unittest.TestCase):
    def test_zdravi_vrati_503(self):
        def nedostupna():
            raise odbc("08001", "[Microsoft][ODBC Driver 18]Login timeout expired")
        app = vytvor_aplikaci([], Konfigurace(vyvoj=True), tovarna_db=nedostupna)
        odpoved_ = app.test_client().get("/api/system/zdravi")
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (503, "DATABASE_UNAVAILABLE"))
        self.assertEqual(odpoved_.json["data"]["databaze"], "NEDOSTUPNA")


# --- CR-06: requestId – stejný obsah, stejný uživatel --------------------------------------------

class Vstup1(SkladovyVstup):
    kod: str


class Vysledek1(Vystup):
    kod: str


@transakce("TEST_IDEM", skladova=True)
def _operace(spoj: Spojeni, vstup: Vstup1, kdo: Kontext) -> Vysledek1:
    if vstup.kod == "ZAMEK":
        raise odbc("HY000", "[SQL Server]Lock request time out period exceeded. (1222) (SQLExecDirectW)")
    return Vysledek1(kod=vstup.kod)


api = Blueprint("revize_api", __name__)


@api.post("/operace")
def operace():
    return odpoved(_operace(vstup=nacti_vstup(Vstup1), kdo=kontext()))


REVIZE = Ostrov(nazev="Revize", prefix="revize", api=api)


class TestRequestId(unittest.TestCase):
    def setUp(self):
        self.db = TestovaciDatabaze()
        self.app = testovaci_aplikace([REVIZE], self.db)
        self.klient = self.app.test_client()

    def tearDown(self):
        self.db.smaz()

    def test_stejny_request_id_s_jinym_obsahem(self):
        prihlas(self.klient)
        rid = str(uuid.uuid4())
        prvni = self.klient.post("/api/revize/operace", json={"requestId": rid, "kod": "A"})
        self.assertEqual(prvni.json["code"], "OK")
        odpoved_ = self.klient.post("/api/revize/operace", json={"requestId": rid, "kod": "B"})
        self.assertEqual(odpoved_.json["code"], "VALIDATION_ERROR")

    def test_stejny_request_id_jiny_uzivatel(self):
        prihlas(self.klient, uzivatel_id=1)
        rid = str(uuid.uuid4())
        self.klient.post("/api/revize/operace", json={"requestId": rid, "kod": "A"})
        prihlas(self.klient, uzivatel_id=2)
        odpoved_ = self.klient.post("/api/revize/operace", json={"requestId": rid, "kod": "A"})
        self.assertEqual(odpoved_.json["code"], "VALIDATION_ERROR")

    def test_vyprseni_zamku(self):
        prihlas(self.klient)
        odpoved_ = self.klient.post("/api/revize/operace", json={"requestId": str(uuid.uuid4()), "kod": "ZAMEK"})
        self.assertEqual(odpoved_.json["code"], "CONCURRENT_CHANGE")
        self.assertIn("někdo jiný", odpoved_.json["message"])
        self.assertEqual(self.db.hodnota("SELECT COUNT(*) FROM dbo.SkladovaTransakce"), 0)


class TestRequestIdSeZpracovava(unittest.TestCase):
    """CR-18: první požadavek se stejným requestId ještě běží (drží zámek na hlavičce)."""

    def setUp(self):
        self.db = TestovaciDatabaze()
        self.klient = testovaci_aplikace([REVIZE], self.db).test_client()

    def tearDown(self):
        self.db.smaz()

    def test_cekani_na_hlavicku_vrati_request_in_progress(self):
        puvodni = Spojeni.proved

        def proved(spoj, sql, *parametry):
            if sql.startswith("INSERT INTO dbo.SkladovaTransakce"):
                raise odbc("HY000", "[SQL Server]Lock request time out period exceeded. (1222) (SQLExecDirectW)")
            return puvodni(spoj, sql, *parametry)

        prihlas(self.klient)
        with mock.patch.object(Spojeni, "proved", proved):
            odpoved_ = self.klient.post("/api/revize/operace", json={"requestId": str(uuid.uuid4()), "kod": "A"})
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (409, "REQUEST_IN_PROGRESS"))


# --- CR-15: migrace pod účtem pro migrace --------------------------------------------------------

class TestMigraceUctem(unittest.TestCase):
    def test_prikazy_db_pouzivaji_ucet_pro_migrace(self):
        db = TestovaciDatabaze()
        volano = []

        def migracni():
            volano.append("migrace")
            raise RuntimeError("účet pro migrace")

        try:
            app = vytvor_aplikaci([], Konfigurace(vyvoj=True), tovarna_db=db.tovarna(), tovarna_migrace=migracni)
            for prikaz in (["db", "stav"], ["db", "upgrade"], ["db", "oznac", "001_schema_g1.sql"]):
                vysledek = app.test_cli_runner().invoke(args=prikaz)
                self.assertIsInstance(vysledek.exception, RuntimeError, prikaz)
            self.assertEqual(volano, ["migrace"] * 3)
        finally:
            db.smaz()


# --- CR-16: typy query parametrů v OpenAPI ---------------------------------------------------------

class TestOpenApiParametry(unittest.TestCase):
    def test_parametry_maji_skutecne_typy(self):
        db = TestovaciDatabaze()
        try:
            spec = vytvor_openapi(testovaci_aplikace([], db))
        finally:
            db.smaz()
        parametry = {p["name"]: p for p in spec["paths"]["/api/system/audit"]["get"]["parameters"]}
        self.assertNotIn("requestId", parametry)
        self.assertEqual(parametry["strana"]["schema"]["type"], "integer")
        self.assertIn({"type": "string", "format": "date"}, parametry["od"]["schema"]["anyOf"])


# --- TD-10: noční kontrola integrity z Plánovače úloh ---------------------------------------------

class TestIntegritaCli(unittest.TestCase):
    def spust(self, select: str):
        db = TestovaciDatabaze(PLATFORMA_SQLITE + f"CREATE VIEW dbo.v_KontrolaIntegrity AS {select};")
        try:
            return testovaci_aplikace([], db).test_cli_runner().invoke(args=["platforma", "integrita"])
        finally:
            db.smaz()

    def test_chyba_vrati_navratovy_kod_1(self):
        vysledek = self.spust("SELECT 'FULLBOXKLIC_NESEDI' AS Kontrola, 'CHYBA' AS Zavaznost, 5 AS ObjektID,"
                              " 'Uloženo X, adresa je Y' AS Popis")
        self.assertEqual(vysledek.exit_code, 1, vysledek.output)
        self.assertIn("FULLBOXKLIC_NESEDI", vysledek.output)

    def test_bez_nalezu(self):
        vysledek = self.spust("SELECT 'X' AS Kontrola, 'CHYBA' AS Zavaznost, 1 AS ObjektID, 'x' AS Popis WHERE 0")
        self.assertEqual((vysledek.exit_code, vysledek.output.strip()), (0, "Bez nálezů."))


# --- TD-19: vzorová data kostry se nedostanou do provozu ---------------------------------------------

class TestKostraVProvozu(unittest.TestCase):
    MODUL = "app.ostrovy.identita.ukazky"

    def setUp(self):
        self.db = TestovaciDatabaze()
        # Pojistka běží při prvním importu. `from . import ukazky` vrací i atribut balíčku,
        # proto se kromě sys.modules odebere i ten (jinak by test závisel na pořadí testů).
        self.balik = importlib.import_module("app.ostrovy.identita")
        self.puvodni = sys.modules.pop(self.MODUL, None)
        self.puvodni_atribut = self.balik.__dict__.pop("ukazky", None)

    def tearDown(self):
        sys.modules.pop(self.MODUL, None)
        self.balik.__dict__.pop("ukazky", None)
        if self.puvodni is not None:
            sys.modules[self.MODUL] = self.puvodni
        if self.puvodni_atribut is not None:
            self.balik.ukazky = self.puvodni_atribut
        self.db.smaz()

    def test_kostra_v_provozu_selze(self):
        from app.ostrovy.identita import rozhrani
        from app.platforma.kostra import KostraVProvozu

        provoz = vytvor_aplikaci([], Konfigurace(vyvoj=False, tajny_klic="k" * 40), tovarna_db=self.db.tovarna())
        with provoz.app_context(), self.assertRaises(KostraVProvozu):
            rozhrani.nacti_uzivatele(None, [1])

    def test_kostra_ve_vyvoji_vrati_vzorova_data(self):
        from app.ostrovy.identita import rozhrani

        with testovaci_aplikace([], self.db).app_context():
            self.assertEqual(list(rozhrani.nacti_uzivatele(None, [1, 7])), [1])   # 7 ve vzorových datech není


# --- CR-10: odebrání práv platí hned ------------------------------------------------------------

class TestOvereniKontextu(unittest.TestCase):
    def setUp(self):
        self.db = TestovaciDatabaze()
        self.stav = {"aktivni": True, "opravneni": frozenset({"X"})}

        def over(kdo: Kontext):
            if not self.stav["aktivni"]:
                return None
            return Kontext(kdo.uzivatel_id, kdo.terminal_id, kdo.kod_role, self.stav["opravneni"])

        identita = Ostrov(nazev="Identita", prefix="identita", api=Blueprint("i_api", __name__), overeni_kontextu=over)
        self.app = testovaci_aplikace([identita, REVIZE], self.db)
        self.klient = self.app.test_client()

    def tearDown(self):
        self.db.smaz()

    def test_deaktivace_plati_okamzite(self):
        prihlas(self.klient, "X")
        rid = str(uuid.uuid4())
        self.assertEqual(self.klient.post("/api/revize/operace", json={"requestId": rid, "kod": "A"}).status_code, 200)
        self.stav["aktivni"] = False
        odpoved_ = self.klient.post("/api/revize/operace", json={"requestId": str(uuid.uuid4()), "kod": "B"})
        self.assertEqual((odpoved_.status_code, odpoved_.json["code"]), (401, "NOT_AUTHENTICATED"))

    def test_jen_jeden_ostrov_smi_overovat(self):
        druhy = Ostrov(nazev="Druhy", prefix="druhy", api=Blueprint("d_api", __name__), overeni_kontextu=lambda k: k)
        jiny = Ostrov(nazev="Jiny", prefix="jiny", api=Blueprint("j_api", __name__), overeni_kontextu=lambda k: k)
        with self.assertRaises(RuntimeError):
            vytvor_aplikaci([druhy, jiny], Konfigurace(vyvoj=True), tovarna_db=self.db.tovarna())


# --- CR-11: jména modelů v OpenAPI ---------------------------------------------------------------

class TestKolizeModelu(unittest.TestCase):
    def test_dva_ruzne_modely_se_stejnym_jmenem(self):
        class Detail(Vystup):
            a: int

        prvni = Detail

        class Detail(Vystup):  # noqa: F811 – záměrně stejné jméno
            b: str

        bp = Blueprint("kolize_api", __name__)
        bp.add_url_rule("/a", "a", dokumentuj(vystup=prvni)(lambda: None))
        bp.add_url_rule("/b", "b", dokumentuj(vystup=Detail)(lambda: None))
        db = TestovaciDatabaze()
        try:
            app = testovaci_aplikace([Ostrov(nazev="K", prefix="kolize", api=bp)], db)
            with self.assertRaises(RuntimeError):
                vytvor_openapi(app)
        finally:
            db.smaz()


class TestParametryBezRequestId(unittest.TestCase):
    def test_get_filtr_nema_request_id(self):
        from app.platforma.kontrakty import Strankovani
        self.assertNotIn("request_id", Strankovani.model_fields)
        self.assertTrue(issubclass(Strankovani, BaseModel))


if __name__ == "__main__":
    unittest.main()
