"""Integrační testy ostrova B proti SQL Serveru (fáze 1): přihlášení, uživatelé, role, terminály.

Testovací databázi sdílejí všechny testy a rollback platí jen na to, co test nezapsal přes
`spojeni_pro_skript()`: proto si test vkládá sám, co potřebuje, osobní čísla, kódy terminálů i
hledaná jména jsou unikátní podle náhodné značky a ověřuje jen data, která sám nastavil – takže se
testy navzájem nerazí ani po opakovaném běhu nad stejnou databází.

Tělo služby se volá přes `__wrapped__`, aby běželo na spojení testu (a rollback ho zrušilo).
Dekorovaná funkce se volí tam, kde je potřeba vlastní transakce: porušení cizího klíče serverem
(XACT_ABORT) by zahodilo i transakci testu. Přes HTTP se testuje to, co platí až příštím
požadavkem – k tomu data potvrzujeme přes `spojeni_pro_skript()`.
"""
from __future__ import annotations

import itertools
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from app.ostrovy import OSTROVY
from app.ostrovy.identita import domena, repozitar, rozhrani, sluzby
from app.ostrovy.identita.kontrakty import (
    NovyTerminalVstup,
    NovyUzivatelVstup,
    ResetPinuVstup,
    UzivateleFiltr,
    UzivatelRadek,
    ZmenaRoleVstup,
    ZmenaTerminaluVstup,
    ZmenaUzivateleVstup,
)
from app.ostrovy.identita.testy.test_identita import chybna_pole
from app.platforma import vytvor_aplikaci
from app.platforma.chyby import AppError
from app.platforma.db import spojeni_pro_skript
from app.platforma.kontrakty import DuvodVstup
from app.platforma.typy import Kontext
from tests.integrace.zaklad import KONFIGURACE, ZakladIntegrace

PIN = "1234"
BEZ_PRACOVISTE = 2_000_000_000      # takové pracoviště nemůže existovat → FK 547 → VALIDATION_ERROR
ZMENENO = sluzby.ZMENENO


class ZakladIdentit(ZakladIntegrace):
    """Výchozí data: jedinečná osobní čísla a správce, který smí něco měnit."""

    aplikace_http = None        # vlastní instance aplikace – vytvoří se jednou a sdílí ji všechny testy

    def setUp(self) -> None:
        super().setUp()
        self.znacka = uuid.uuid4().hex[:6].upper()
        self._dalsi = itertools.count(1)
        # HTTP testy běží nad vlastní instancí aplikace, ne nad `self.app` z harnessu: ten v setUp drží
        # pushnutý app context a Flask pro požadavky jeho test klienta použije tentýž – `g.houfek_kontext`
        # z prvního požadavku (přihlášení) pak platí i pro další a hák over_kontext se zavolá jen jednou.
        # Vlastní instance má na každý požadavek vlastní kontext, takže ověření session a oprávnění
        # probíhá při každém požadavku jako v provozu. Až po super().setUp(): harness do té doby
        # založí testovací databázi a dorovná schéma migracemi.
        if ZakladIdentit.aplikace_http is None:
            ZakladIdentit.aplikace_http = vytvor_aplikaci(OSTROVY, KONFIGURACE)
        self.klient = ZakladIdentit.aplikace_http.test_client()
        self.cisla: dict[int, str] = {}
        self.puvodni_opravneni: dict[str, list[str]] = {}
        self.role = {radek["KodRole"]: int(radek["RoleID"]) for radek in
                     self.spoj.dotaz("SELECT RoleID, KodRole FROM dbo.Role")}
        self.pracoviste = int(self.spoj.hodnota("SELECT MIN(PracovisteID) FROM dbo.Pracoviste"))
        # prvního správce vkládáme SQL příkazem: audit i @transakce potřebují existující UzivatelID
        self.spravce = self._vloz("ADMIN", "Integracni", "Spravce")
        self.kdo = Kontext(self.spravce, None, "ADMIN", frozenset({"UZIVATEL_EDIT"}))

    def tearDown(self) -> None:
        """Role se vrátí do stavu, v jakém ji test našel (dělá to `_opravneni_role`).

        Až po rollbacku testu: ten může držet zámky nad `RoleOpravneni` a zápis z druhého spojení
        by na nich visel do konce testu. app context ještě žije, proto `spojeni_pro_skript` funguje.
        """
        self.spoj._rollback()
        for kod_role, kodu in self.puvodni_opravneni.items():
            self._opravneni_role(kod_role, *kodu)
        super().tearDown()

    # --- pomocná data ------------------------------------------------------------------------

    def _cislo(self) -> str:
        return f"TEST-{self.znacka}-{next(self._dalsi):02d}"

    def _vloz(self, kod_role: str, jmeno: str, prijmeni: str, *, pin: str | None = None,
              aktivni: bool = True) -> int:
        """Uživatel potvrzený do databáze (vidí ho i HTTP); vrací UzivatelID."""
        cislo = self._cislo()
        with spojeni_pro_skript() as spoj:
            uzivatel_id = int(spoj.vloz(
                "INSERT INTO dbo.Uzivatel (OsobniCislo, Jmeno, Prijmeni, RoleID, PinHash, Aktivni)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                cislo, jmeno, prijmeni, self.role[kod_role],
                domena.zahashuj_pin(pin) if pin is not None else None, 1 if aktivni else 0))
        self.cisla[uzivatel_id] = cislo
        return uzivatel_id

    def _vloz_terminal(self, pripona: str, *, pracoviste: int | None = None,
                       aktivni: bool = True) -> tuple[int, str]:
        """Terminál potvrzený do databáze; vrací (id, kód), jak ho posílá PDA."""
        kod = f"PDA-{self.znacka}-{pripona}"
        with spojeni_pro_skript() as spoj:
            terminal_id = int(spoj.vloz(
                "INSERT INTO dbo.Terminal (KodTerminalu, NazevTerminalu, PracovisteID, Aktivni)"
                " VALUES (?, ?, ?, ?)", kod, f"Integracni PDA {pripona}", pracoviste, 1 if aktivni else 0))
        return terminal_id, kod

    def _opravneni_role(self, kod_role: str, *kodu: str) -> None:
        """Role dostane jen kódy, které test potřebuje; po testu se vrátí to, co v ní bylo předtím.

        Matice G4 je v databázi od migrace 005 – role tedy žádná prázdná nejsou. Zápis se potvrzuje
        do databáze, kterou sdílejí všechny ostrovy, proto si helper pamatuje původní stav od prvního
        zásahu do role a `tearDown` ho vrátí zpátky; jinak by další test našel roli připravenou pro
        ten předchozí. Při druhém volání v témže testu se původní stav už nepřepisuje.
        """
        if kod_role not in self.puvodni_opravneni:
            self.puvodni_opravneni[kod_role] = [radek["KodOpravneni"] for radek in self.spoj.dotaz(
                "SELECT o.KodOpravneni FROM dbo.RoleOpravneni AS ro"
                " JOIN dbo.Opravneni AS o ON o.OpravneniID = ro.OpravneniID WHERE ro.RoleID = ?",
                self.role[kod_role])]
        with spojeni_pro_skript() as spoj:
            spoj.proved("DELETE FROM dbo.RoleOpravneni WHERE RoleID = ?", self.role[kod_role])
            for kod in kodu:
                spoj.proved("INSERT INTO dbo.RoleOpravneni (RoleID, OpravneniID)"
                            " SELECT ?, OpravneniID FROM dbo.Opravneni WHERE KodOpravneni = ?",
                            self.role[kod_role], kod)

    def zaloz(self, *, cislo: str | None = None, jmeno: str = "Jan", prijmeni: str = "Novak",
              role: str = "OPER", role_id: int | None = None, pin: str | None = PIN,
              karta: str | None = None) -> UzivatelRadek:
        return sluzby.zaloz_uzivatele.__wrapped__(
            self.spoj,
            vstup=NovyUzivatelVstup(osobni_cislo=cislo or self._cislo(), jmeno=jmeno, prijmeni=prijmeni,
                                    role_id=role_id if role_id is not None else self.role[role],
                                    pin=pin, kod_karty=karta),
            kdo=self.kdo)

    def zmen(self, uzivatel_id: int, **pole: object) -> UzivatelRadek:
        return sluzby.zmen_uzivatele.__wrapped__(self.spoj, uzivatel_id=uzivatel_id, kdo=self.kdo,
                                                 vstup=ZmenaUzivateleVstup(duvod="zkusebni zmena", **pole))

    # --- měření a odpovědi -------------------------------------------------------------------

    def audit_zacatek(self) -> int:
        """Hladina auditů před operací – test pak vyhodnocuje jen řádky, které napsal on."""
        return int(self.spoj.hodnota("SELECT ISNULL(MAX(AuditID), 0) FROM dbo.AuditZmen"))

    def audity(self, typ_objektu: str, objekt_id: int, od: int = 0) -> list[tuple]:
        """Řádky auditu objektu (Pole, stará, nová, poznámka) od hladiny `od` – i z transakce testu."""
        return [tuple(radek[hodnota] for hodnota in ("Pole", "StaraHodnota", "NovaHodnota", "Poznamka"))
                for radek in self.spoj.dotaz(
                    "SELECT Pole, StaraHodnota, NovaHodnota, Poznamka FROM dbo.AuditZmen"
                    " WHERE TypObjektu = ? AND ObjektID = ? AND AuditID > ? ORDER BY AuditID",
                    typ_objektu, objekt_id, od)]

    def pin_hash(self, uzivatel_id: int) -> str | None:
        return self.spoj.hodnota("SELECT PinHash FROM dbo.Uzivatel WHERE UzivatelID = ?", uzivatel_id)

    def cekej_chybu(self, kod: str, funkce, *args, **kwargs) -> AppError:
        with self.assertRaises(AppError) as zachyceno:
            funkce(*args, **kwargs)
        self.assertEqual(zachyceno.exception.kod, kod, zachyceno.exception.zprava)
        return zachyceno.exception

    def ok(self, odpoved) -> dict:
        self.assertEqual((odpoved.status_code, odpoved.json["code"]), (200, "OK"), odpoved.json)
        return odpoved.json["data"]

    def chybnou(self, odpoved, http: int, kod: str) -> dict:
        self.assertEqual((odpoved.status_code, odpoved.json["code"]), (http, kod), odpoved.json)
        return odpoved.json

    def pole_chyby(self, odpoved) -> set[str]:
        obalka = self.chybnou(odpoved, 400, "VALIDATION_ERROR")
        return {chyba["pole"] for chyba in (obalka["data"] or {}).get("chyby", [])}

    def prihlaseni(self, cislo: str, pin: str, terminal: str | None = None):
        telo: dict[str, str] = {"osobniCislo": cislo, "pin": pin}
        if terminal:
            telo["kodTerminalu"] = terminal
        return self.klient.post("/api/identita/prihlaseni", json=telo)


class TestPrihlaseni(ZakladIdentit):
    def setUp(self) -> None:
        super().setUp()
        self._opravneni_role("SKL", "DIL_CIST", "SKLAD_VYDEJ")
        self.uzivatel = self._vloz("SKL", "Jan", "Novak", pin="1234")
        self.bez_pinu = self._vloz("SKL", "Eva", "Mala")
        self.neaktivni = self._vloz("SKL", "Karel", "Dvorak", pin="1111", aktivni=False)

    def test_prihlaseni_z_databaze_a_ja(self):
        data = self.ok(self.prihlaseni(self.cisla[self.uzivatel], "1234"))
        self.assertEqual((data["uzivatelId"], data["celeJmeno"], data["kodRole"], data["nazevRole"]),
                         (self.uzivatel, "Jan Novak", "SKL", "Skladník"))
        self.assertEqual(data["opravneni"], ["DIL_CIST", "SKLAD_VYDEJ"])
        self.assertEqual((data["terminalId"], data["kodTerminalu"], data["pracovisteId"]), (None, None, None))
        self.assertFalse({"pin", "pinHash", "kodKarty"} & set(data))
        ja = self.ok(self.klient.get("/api/identita/ja"))
        self.assertEqual(ja["uzivatelId"], self.uzivatel)
        self.assertFalse({"pin", "pinHash", "kodKarty"} & set(ja))

    def test_prihlaseni_z_terminalu(self):
        _, kod = self._vloz_terminal("01", pracoviste=self.pracoviste)
        data = self.ok(self.prihlaseni(self.cisla[self.uzivatel], "1234", kod.lower()))
        self.assertEqual((data["kodTerminalu"], data["pracovisteId"]), (kod, self.pracoviste))
        self.assertEqual(data["terminalId"], self.ok(self.klient.get("/api/identita/ja"))["terminalId"])
        self.assertEqual(self.pole_chyby(self.prihlaseni(self.cisla[self.uzivatel], "1234", "PDA-9999")),
                         {"kodTerminalu"})

    def test_vyrazeny_terminal_se_neprihlasi(self):
        _, kod = self._vloz_terminal("09", aktivni=False)
        obalka = self.chybnou(self.prihlaseni(self.cisla[self.uzivatel], "1234", kod), 400, "VALIDATION_ERROR")
        self.assertIn("není evidovaný", obalka["message"])
        self.assertIn("kodTerminalu", {chyba["pole"] for chyba in obalka["data"]["chyby"]})

    def test_ctyri_selhani_maji_stejnou_zpravu(self):
        zpravy = set()
        for cislo, pin in [(self.cisla[self.uzivatel], "9999"),   # špatný PIN
                           (self._cislo(), "1234"),               # neznámé osobní číslo
                           (self.cisla[self.bez_pinu], "1234"),   # uživatel bez PINu
                           (self.cisla[self.neaktivni], "1111"),  # vyřazený uživatel
                           ("Nov ak", "1234")]:                   # osobní číslo, které nelze normalizovat
            obalka = self.chybnou(self.prihlaseni(cislo, pin), 401, "NOT_AUTHENTICATED")
            self.assertIsNone(obalka["data"])
            zpravy.add(obalka["message"])
        self.assertEqual(zpravy, {sluzby.ZPRAVA_NEPLATNE})

    def test_pin_se_ulozi_jako_argon2_hash(self):
        hash_ = self.pin_hash(self.uzivatel)
        self.assertTrue(hash_.startswith("$argon2id$"), hash_[:20])
        self.assertNotIn("1234", hash_)
        self.assertIsNone(self.pin_hash(self.bez_pinu))

    def test_odhlaseni(self):
        self.ok(self.prihlaseni(self.cisla[self.uzivatel], "1234"))
        self.ok(self.klient.post("/api/identita/odhlaseni"))
        self.chybnou(self.klient.get("/api/identita/ja"), 401, "NOT_AUTHENTICATED")


class TestZamekPinu(ZakladIdentit):
    """Zámek po pěti chybných PINech (TD-07, D-33): počítadlo, zámek, historie pokusů, odemknutí.

    Přihlášení i odemknutí běží přes HTTP, takže se potvrzují vlastní transakcí – přesně to, čím se
    liší od ostatních testů: počítadlo, zámek i řádek pokusu musí v databázi zůstat i po chybném
    přihlášení. `teď()` služba se mění na pevný čas, aby test na patnáct minut nečekal.
    """

    TED = datetime(2026, 11, 9, 10, 0)
    ZA_15 = TED + timedelta(minutes=15)      # zámek, který právě nastal

    def setUp(self) -> None:
        super().setUp()
        self._opravneni_role("SKL", "DIL_CIST")
        self._opravneni_role("ADMIN", "UZIVATEL_EDIT")
        self.uzivatel = self._vloz("SKL", "Jan", "Novak", pin=PIN)
        self.cislo = self.cisla[self.uzivatel]

    # --- jak si test připraví čas a na co se dívá ------------------------------------------------

    @contextmanager
    def ted(self, hodinu: datetime):
        """Služba vidí `teď()` jako `hodinu` – patnáct minut se počká slovy, ne během testu."""
        with patch("app.ostrovy.identita.sluzby.teď", return_value=hodinu):
            yield

    def zamkni(self) -> None:
        """Pět chybných PINů po sobě: účet je zamčený a počítadlo už od páté chyby zase od nuly."""
        for _ in range(domena.LIMIT_CHYBNYCH_POKUSU):
            self.chybnou(self.prihlaseni(self.cislo, "9999"), 401, "NOT_AUTHENTICATED")
        self.assertEqual(self.stav(self.uzivatel), (0, self.ZA_15))

    def prihlas_admina(self) -> None:
        """Session se správcem: endpoint odemknutí vyžaduje UZIVATEL_EDIT."""
        spravce = self._vloz("ADMIN", "Druhy", "Spravce", pin=PIN)
        self.ok(self.prihlaseni(self.cisla[spravce], PIN))

    def stav(self, uzivatel_id: int) -> tuple[int, datetime | None]:
        """Počítadlo a zámek v databázi – přihlášení je píše vlastním spojením a potvrzuje je."""
        radek = self.spoj.jeden("SELECT ChybnePokusy, ZamcenoDo FROM dbo.Uzivatel WHERE UzivatelID = ?",
                                uzivatel_id)
        return int(radek["ChybnePokusy"]), radek["ZamcenoDo"]

    def pokusy(self, osobni_cislo: str) -> list[str]:
        """Výsledky pokusů o přihlášení v pořadí, v jakém k sobě přišly."""
        return [radek["Vysledek"] for radek in self.spoj.dotaz(
            "SELECT Vysledek FROM dbo.PrihlaseniPokus WHERE OsobniCislo = ? ORDER BY PokusID", osobni_cislo)]

    # --- pravidlo (D-33) -------------------------------------------------------------------------

    def test_pet_chybnych_pinu_ucet_zamkne(self):
        with self.ted(self.TED):
            for poradi in range(1, domena.LIMIT_CHYBNYCH_POKUSU):
                self.chybnou(self.prihlaseni(self.cislo, "9999"), 401, "NOT_AUTHENTICATED")
                self.assertEqual(self.stav(self.uzivatel), (poradi, None))
            self.chybnou(self.prihlaseni(self.cislo, "9999"), 401, "NOT_AUTHENTICATED")
            self.assertEqual(self.stav(self.uzivatel), (0, self.ZA_15))
            self.assertEqual(self.pokusy(self.cislo), ["CHYBNY_PIN"] * domena.LIMIT_CHYBNYCH_POKUSU)

    def test_behem_zamku_se_neprihlasi_a_zamek_zusta(self):
        """Správný PIN během zámku nepustí a žádný pokus zámek neposouvá – počká se patnáct minut."""
        with self.ted(self.TED):
            self.zamkni()
            for _ in range(2):
                self.chybnou(self.prihlaseni(self.cislo, PIN), 401, "NOT_AUTHENTICATED")
                self.chybnou(self.prihlaseni(self.cislo, "9999"), 401, "NOT_AUTHENTICATED")
            self.assertEqual(self.stav(self.uzivatel), (0, self.ZA_15))
            self.assertEqual(self.pokusy(self.cislo),
                             ["CHYBNY_PIN"] * domena.LIMIT_CHYBNYCH_POKUSU + ["ZAMCENO"] * 4)

    def test_po_uplynuti_zamku_se_prihlasi(self):
        with self.ted(self.TED):
            self.zamkni()
        with self.ted(self.ZA_15):        # chvíle, kdy už zámek plynul
            self.ok(self.prihlaseni(self.cislo, PIN))
        self.assertEqual(self.stav(self.uzivatel), (0, None))
        self.assertEqual(self.pokusy(self.cislo), ["CHYBNY_PIN"] * domena.LIMIT_CHYBNYCH_POKUSU + ["USPECH"])

    def test_uspesne_prihlaseni_vynuluje_pocitadlo(self):
        """Tři chyby a správný PIN: účet se nezamkne a počítadlo se rozbíhá znovu od nuly."""
        with self.ted(self.TED):
            for _ in range(3):
                self.chybnou(self.prihlaseni(self.cislo, "9999"), 401, "NOT_AUTHENTICATED")
            self.assertEqual(self.stav(self.uzivatel), (3, None))
            self.ok(self.prihlaseni(self.cislo, PIN))
            self.assertEqual(self.stav(self.uzivatel), (0, None))
            self.chybnou(self.prihlaseni(self.cislo, "9999"), 401, "NOT_AUTHENTICATED")
            self.assertEqual(self.stav(self.uzivatel), (1, None))
        self.assertEqual(self.pokusy(self.cislo), ["CHYBNY_PIN"] * 3 + ["USPECH", "CHYBNY_PIN"])

    def test_nezname_cislo_a_vyrazeny_uzivatel_pisou_vysledek(self):
        """Stejná chyba jako u pokusu s PINem; v historii se liší výsledek a chybějící uživatel."""
        neaktivni = self._vloz("SKL", "Karel", "Dvorak", pin=PIN, aktivni=False)
        nezname = self._cislo()
        zpravy = set()
        for cislo in (nezname, self.cisla[neaktivni]):
            obalka = self.chybnou(self.prihlaseni(cislo, "9999"), 401, "NOT_AUTHENTICATED")
            self.assertIsNone(obalka["data"])
            zpravy.add(obalka["message"])
        self.assertEqual(zpravy, {sluzby.ZPRAVA_NEPLATNE})
        self.assertEqual(self.pokusy(nezname), ["NEZNAMY"])
        self.assertEqual(self.pokusy(self.cisla[neaktivni]), ["NEAKTIVNI"])
        self.assertEqual(self.spoj.jeden("SELECT UzivatelID, TerminalID FROM dbo.PrihlaseniPokus"
                                         " WHERE OsobniCislo = ?", nezname),
                         {"UzivatelID": None, "TerminalID": None})
        self.assertEqual(self.stav(neaktivni), (0, None))     # vyřazený účet se nepočítá ani nezamyká

    def test_pokus_se_pise_bez_pinu(self):
        """Řádek pokusu má jen to, co smí mít: čas, číslo, uživatele, terminál a výsledek (D-33)."""
        terminal, kod = self._vloz_terminal("31", pracoviste=self.pracoviste)
        with self.ted(self.TED):
            self.chybnou(self.prihlaseni(self.cislo, "9999", kod), 401, "NOT_AUTHENTICATED")
            self.ok(self.prihlaseni(self.cislo, PIN, kod))
        radky = self.spoj.dotaz("SELECT * FROM dbo.PrihlaseniPokus WHERE OsobniCislo = ? ORDER BY PokusID",
                                self.cislo)
        self.assertEqual([radek["Vysledek"] for radek in radky], ["CHYBNY_PIN", "USPECH"])
        self.assertEqual({(radek["UzivatelID"], radek["TerminalID"]) for radek in radky},
                         {(self.uzivatel, terminal)})
        self.assertEqual(set(radky[0]),
                         {"PokusID", "DatumCas", "OsobniCislo", "UzivatelID", "TerminalID", "Vysledek"})
        self.assertNotIn("argon2", str(radky))     # otevřený PIN ani hash se nikde nedočítají

    def test_vyprsimy_zamek_se_v_radeku_nevraci(self):
        """`zamcenoDo` říká správci, koho odemknout, jen dokud zámek trvá – po 15 minutách null (D-33).

        Ve sloupci zůstává: přihlašování o zámku rozhoduje z jeho hodnoty, ne z toho, co viděl správce.
        """
        vyprsel = self.TED - timedelta(minutes=1)
        with self.ted(self.TED):
            self.zamkni()
            radky = sluzby.seznam_uzivatelu.__wrapped__(self.spoj, UzivateleFiltr(hledat=self.cislo))
            self.assertEqual(radky.polozky[0].zamceno_do, self.ZA_15)     # běžící zámek vidí
            repozitar.nastav_zamek(self.spoj, self.uzivatel, chybne_pokusy=0, zamceno_do=vyprsel)
            radky = sluzby.seznam_uzivatelu.__wrapped__(self.spoj, UzivateleFiltr(hledat=self.cislo))
            self.assertIsNone(radky.polozky[0].zamceno_do)
            self.assertIsNone(self.zmen(self.uzivatel, jmeno="Jan").zamceno_do)   # výstup jednoho uživatele
            self.assertEqual(self.stav(self.uzivatel), (0, vyprsel))

    # --- odemknutí správcem ------------------------------------------------------------------------

    def test_odemknout_vynuluje_pocitadlo_i_zamek(self):
        """ADMIN uvolní účet dřív, než uplyne 15 minut; výstup je `UzivatelRadek` jako u deaktivace."""
        with spojeni_pro_skript() as spoj:      # stav, který si přihlášení připraví až po páté chybě
            spoj.proved("UPDATE dbo.Uzivatel SET ChybnePokusy = 3, ZamcenoDo = ? WHERE UzivatelID = ?",
                        self.ZA_15, self.uzivatel)
        with self.ted(self.TED):
            spravce = sluzby.seznam_uzivatelu.__wrapped__(self.spoj, UzivateleFiltr(hledat=self.cislo))
            self.assertEqual(spravce.polozky[0].zamceno_do, self.ZA_15)     # ADMIN vidí, koho odemknout
            self.prihlas_admina()
            od = self.audit_zacatek()
            data = self.ok(self.klient.post(f"/api/identita/uzivatele/{self.uzivatel}/odemknout",
                                            json={"duvod": "oznameni na podrzi"}))
            self.assertEqual((data["uzivatelId"], data["celeJmeno"], data["aktivni"], data["zamcenoDo"]),
                             (self.uzivatel, "Jan Novak", True, None))
            self.assertEqual(self.audity("UZIVATEL", self.uzivatel, od),
                             [("ChybnePokusy", "3", "0", "oznameni na podrzi"),
                              ("ZamcenoDo", self.ZA_15.isoformat(), None, "oznameni na podrzi")])
            self.assertEqual(self.stav(self.uzivatel), (0, None))
            self.ok(self.prihlaseni(self.cislo, PIN))        # uvolněný účet se přihlásí hned
        self.assertEqual(self.pokusy(self.cislo)[-1], "USPECH")

    def test_reset_pinu_neodemkne_aniz_zkratil_zamek(self):
        """Reset PINu se od odemknutí liší: zámek ani počítadlo nepřepíše (D-33), přístup vrátí až odemknutí."""
        with self.ted(self.TED):
            self.zamkni()
            self.prihlas_admina()
            data = self.ok(self.klient.post(f"/api/identita/uzivatele/{self.uzivatel}/reset-pinu",
                                            json={"novyPin": "1357", "duvod": "novy PIN"}))
            self.assertEqual((data["uzivatelId"], data["maPin"]), (self.uzivatel, True))
            self.assertIsNotNone(data["zamcenoDo"])                             # výstup pořád ukazuje zámek
            self.assertEqual(self.stav(self.uzivatel), (0, self.ZA_15))         # sloupce zámku se nepřepsaly
            obalka = self.chybnou(self.prihlaseni(self.cislo, "1357"), 401, "NOT_AUTHENTICATED")
            self.assertEqual(obalka["message"], sluzby.ZPRAVA_NEPLATNE)         # stejná odpověď jako chybný PIN
            self.assertEqual(self.pokusy(self.cislo)[-1], "ZAMCENO")
            self.ok(self.klient.post(f"/api/identita/uzivatele/{self.uzivatel}/odemknout",
                                     json={"duvod": "volal na podrzi"}))
            self.ok(self.prihlaseni(self.cislo, "1357"))                        # novým PINem až po odemknutí
        self.assertEqual(self.pokusy(self.cislo)[-1], "USPECH")

    def test_odemknuti_bez_zamku_se_neaudituje(self):
        """Účet bez pokusů se nepřepisuje; cizí ID je NOT_FOUND jako u ostatních operací."""
        self.prihlas_admina()
        od = self.audit_zacatek()
        data = self.ok(self.klient.post(f"/api/identita/uzivatele/{self.uzivatel}/odemknout",
                                        json={"duvod": "volal na podrzi"}))
        self.assertIsNone(data["zamcenoDo"])
        self.assertEqual(self.audity("UZIVATEL", self.uzivatel, od), [])
        self.chybnou(self.klient.post("/api/identita/uzivatele/999999/odemknout", json={"duvod": "test"}),
                     404, "NOT_FOUND")


class TestUzivatele(ZakladIdentit):
    def test_seznam_filter_strankovani_a_zadavani(self):
        # hledá se i ve jméně a v příjmení, takže hledaná jména nesou značku testu – jinak test narazí
        # na potvrzené uživatele jiného testu (osobní číslo značku má vždy)
        jmeno, vanek = f"Petr{self.znacka}", f"Vanek-{self.znacka}"
        self.zaloz(prijmeni=vanek)
        self.zaloz(jmeno=jmeno, prijmeni="Adams")
        self.zaloz(prijmeni="Novak")
        self._vloz("OPER", "Pavla", "Kralova", aktivni=False)
        filtr = dict(hledat=self.znacka, role_id=self.role["OPER"])
        prvni = sluzby.seznam_uzivatelu.__wrapped__(self.spoj, UzivateleFiltr(**filtr))
        self.assertEqual((prvni.celkem, [radek.prijmeni for radek in prvni.polozky]),
                         (3, ["Adams", "Novak", vanek]))
        self.assertEqual(prvni.velikost, 50)
        druha = sluzby.seznam_uzivatelu.__wrapped__(self.spoj, UzivateleFiltr(strana=2, velikost=2, **filtr))
        self.assertEqual((druha.celkem, [radek.prijmeni for radek in druha.polozky]), (3, [vanek]))
        self.assertEqual(sluzby.seznam_uzivatelu.__wrapped__(
            self.spoj, UzivateleFiltr(aktivni=None, **filtr)).celkem, 4)
        self.assertEqual([radek.prijmeni for radek in
                          sluzby.seznam_uzivatelu.__wrapped__(self.spoj,
                                                              UzivateleFiltr(aktivni=False, **filtr)).polozky],
                         ["Kralova"])
        # hledá se i ve jméně a `%` v hledaném řetězci není wildcard
        self.assertEqual(sluzby.seznam_uzivatelu.__wrapped__(
            self.spoj, UzivateleFiltr(hledat=jmeno, role_id=self.role["OPER"])).celkem, 1)
        self.assertEqual(sluzby.seznam_uzivatelu.__wrapped__(
            self.spoj, UzivateleFiltr(hledat=vanek, role_id=self.role["OPER"])).celkem, 1)
        self.assertEqual(sluzby.seznam_uzivatelu.__wrapped__(
            self.spoj, UzivateleFiltr(hledat=f"{self.znacka}%", role_id=self.role["OPER"])).celkem, 0)
        self.assertFalse({"pin", "pinHash", "kodKarty"} & set(prvni.polozky[0].model_dump()))

    def test_zalozeni_ulozi_hash_a_pise_audit(self):
        od = self.audit_zacatek()
        novy = self.zaloz(role="SKL", pin="2468")
        self.assertEqual((novy.jmeno, novy.prijmeni, novy.cele_jmeno, novy.kod_role, novy.ma_pin,
                          novy.ma_kartu, novy.aktivni), ("Jan", "Novak", "Jan Novak", "SKL", True, False, True))
        self.assertTrue(novy.osobni_cislo.startswith(f"TEST-{self.znacka}-"))
        self.assertTrue(self.pin_hash(novy.uzivatel_id).startswith("$argon2id$"))
        self.assertNotIn("2468", self.pin_hash(novy.uzivatel_id))
        self.assertEqual({radek[0] for radek in self.audity("UZIVATEL", novy.uzivatel_id, od)},
                         {"Jmeno", "Prijmeni", "RoleID", "PinHash"})
        # jméno s diakritikou se uloží i vrátí beze změny (NVARCHAR)
        self.assertEqual(self.zaloz(jmeno="Božena", prijmeni="Dvořáková").cele_jmeno, "Božena Dvořáková")

    def test_duplicita_a_chybejici_role(self):
        existence = self.zaloz(prijmeni="Adams")
        self.cekej_chybu("ALREADY_EXISTS", self.zaloz, cislo=existence.osobni_cislo)
        self.zaloz(prijmeni="Novak", karta="04A2B9")
        self.cekej_chybu("ALREADY_EXISTS", self.zaloz, karta="04A2B9")
        self.cekej_chybu("NOT_FOUND", self.zaloz, role_id=999_999)
        self.assertEqual(chybna_pole(self.zaloz, pin="12"), {"pin"})

    def test_zmena_jmena_role_a_karty(self):
        novy = self.zaloz(prijmeni="Adams", karta="04A2B9")
        druhy = self.zaloz(prijmeni="Novak")
        od = self.audit_zacatek()
        zmena = self.zmen(novy.uzivatel_id, prijmeni="Novy", role_id=self.role["MISTR"], kod_karty="0C3D11")
        self.assertEqual((zmena.cele_jmeno, zmena.kod_role, zmena.ma_kartu, zmena.osobni_cislo),
                         ("Jan Novy", "MISTR", True, novy.osobni_cislo))
        radky = dict((radek[0], radek[1:3]) for radek in self.audity("UZIVATEL", novy.uzivatel_id, od))
        self.assertEqual((radky["Prijmeni"], radky["RoleID"]), (("Adams", "Novy"), ("OPER", "MISTR")))
        self.assertEqual(radky["KodKarty"], (ZMENENO, ZMENENO))        # kód karty se do auditu nedostane
        self.assertNotIn("04A2B9", str(list(radky.values())))
        self.cekej_chybu("ALREADY_EXISTS", self.zmen, druhy.uzivatel_id, kod_karty="0C3D11")
        self.assertFalse(self.zmen(novy.uzivatel_id, kod_karty=None).ma_kartu)
        self.cekej_chybu("NOT_FOUND", self.zmen, 999_999, jmeno="X")

    def test_deaktivace(self):
        cil = self.zaloz(prijmeni="Adams", role="SKL")
        self.cekej_chybu("VALIDATION_ERROR", sluzby.deaktivuj_uzivatele.__wrapped__, self.spoj,
                         uzivatel_id=self.spravce, vstup=DuvodVstup(duvod="omyl"), kdo=self.kdo)  # sám sebe
        self._vloz("ADMIN", "Druhy", "Spravce")                        # ať nejde o posledního správce
        od = self.audit_zacatek()
        self.assertFalse(sluzby.deaktivuj_uzivatele.__wrapped__(
            self.spoj, uzivatel_id=cil.uzivatel_id, vstup=DuvodVstup(duvod="odchod z firmy"),
            kdo=self.kdo).aktivni)
        self.assertEqual(self.audity("UZIVATEL", cil.uzivatel_id, od),
                         [("Aktivni", "True", "False", "odchod z firmy")])
        self.assertIs(self.spoj.hodnota("SELECT Aktivni FROM dbo.Uzivatel WHERE UzivatelID = ?", cil.uzivatel_id),
                      False)
        self.cekej_chybu("NOT_FOUND", sluzby.deaktivuj_uzivatele.__wrapped__, self.spoj, uzivatel_id=999_999,
                         vstup=DuvodVstup(duvod="omyl"), kdo=self.kdo)

    def test_posledni_aktivni_spravce_se_vyradit_neda(self):
        with spojeni_pro_skript() as spoj:      # testovací databázi sdílejí i předchozí testy
            spoj.proved("UPDATE dbo.Uzivatel SET Aktivni = 0 WHERE Aktivni = 1 AND RoleID = ?", self.role["ADMIN"])
        spravce = self._vloz("ADMIN", "Posledni", "Spravce")
        kolega = self._vloz("OPER", "Kolega", "Druhy")
        kdo = Kontext(kolega, None, "OPER", frozenset({"UZIVATEL_EDIT"}))
        self.cekej_chybu("VALIDATION_ERROR", sluzby.deaktivuj_uzivatele.__wrapped__, self.spoj,
                         uzivatel_id=spravce, vstup=DuvodVstup(duvod="chci taky"), kdo=kdo)
        druhy = self._vloz("ADMIN", "Druhy", "Spravce")
        self.assertFalse(sluzby.deaktivuj_uzivatele.__wrapped__(
            self.spoj, uzivatel_id=druhy, vstup=DuvodVstup(duvod="prestal pracovat"), kdo=kdo).aktivni)

    def test_reset_pinu(self):
        novy = self.zaloz(prijmeni="Adams", pin=None)
        self.assertIsNone(self.pin_hash(novy.uzivatel_id))
        od = self.audit_zacatek()
        sluzby.nastav_pin.__wrapped__(self.spoj, uzivatel_id=novy.uzivatel_id, kdo=self.kdo,
                                      vstup=ResetPinuVstup(novy_pin="13579", duvod="novy PIN"))
        self.assertTrue(self.pin_hash(novy.uzivatel_id).startswith("$argon2id$"))
        self.assertNotIn("13579", self.pin_hash(novy.uzivatel_id))
        self.assertEqual(self.audity("UZIVATEL", novy.uzivatel_id, od), [("PinHash", None, ZMENENO, "novy PIN")])
        stary = self.pin_hash(novy.uzivatel_id)
        self.assertTrue(sluzby.nastav_pin.__wrapped__(
            self.spoj, uzivatel_id=novy.uzivatel_id, kdo=self.kdo,
            vstup=ResetPinuVstup(novy_pin="2468", duvod="ztrácení PINu")).ma_pin)
        self.assertNotEqual(self.pin_hash(novy.uzivatel_id), stary)
        self.assertEqual(chybna_pole(sluzby.nastav_pin.__wrapped__, self.spoj, uzivatel_id=novy.uzivatel_id,
                                     kdo=self.kdo, vstup=ResetPinuVstup(novy_pin="abc", duvod="spatny PIN")),
                         {"novyPin"})
        self.cekej_chybu("NOT_FOUND", sluzby.nastav_pin.__wrapped__, self.spoj, uzivatel_id=999_999,
                         kdo=self.kdo, vstup=ResetPinuVstup(novy_pin="1234", duvod="někdo jiný"))


class TestRole(ZakladIdentit):
    def test_seznam_roli_je_z_databaze(self):
        self._opravneni_role("OPER", "SKLAD_VYDEJ", "DIL_CIST")
        self._opravneni_role("MISTR")
        radky = sluzby.seznam_roli.__wrapped__(self.spoj).polozky
        self.assertEqual([radek.kod_role for radek in radky], ["OPER", "SKL", "MISTR", "TECH", "ADMIN"])
        self.assertTrue(all(radek.aktivni for radek in radky))
        role = {radek.kod_role: radek for radek in radky}
        self.assertEqual((role["OPER"].nazev, role["OPER"].popis),
                         ("Operátor", "Čtení, standardní příjem a výdej podle přidělených oprávnění."))
        # oprávnění ověřuje jen u rolí, které si v tomto testu nastavil – RoleOpravneni mění i jiné testy
        self.assertEqual((role["OPER"].opravneni, role["MISTR"].opravneni), (["DIL_CIST", "SKLAD_VYDEJ"], []))

    def test_zmena_opravneni_nahradi_radky_a_pise_audit(self):
        self._opravneni_role("OPER", "DIL_CIST", "SKLAD_PRIJEM")
        od = self.audit_zacatek()
        role = sluzby.zmen_roli.__wrapped__(self.spoj, role_id=self.role["OPER"], kdo=self.kdo,
                                            vstup=ZmenaRoleVstup(opravneni=["dil_cist", "SKLAD_VYDEJ"],
                                                                 duvod="bez prijmu"))
        self.assertEqual(role.opravneni, ["DIL_CIST", "SKLAD_VYDEJ"])
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.RoleOpravneni WHERE RoleID = ?",
                                           self.role["OPER"]), 2)
        self.assertEqual(self.audity("ROLE", self.role["OPER"], od),
                         [("RoleOpravneni", None, "SKLAD_VYDEJ", "bez prijmu"),
                          ("RoleOpravneni", "SKLAD_PRIJEM", None, "bez prijmu")])
        od = self.audit_zacatek()       # stejný seznam se nepřepisuje ani neaudituje
        sluzby.zmen_roli.__wrapped__(self.spoj, role_id=self.role["OPER"], kdo=self.kdo,
                                     vstup=ZmenaRoleVstup(opravneni=["SKLAD_VYDEJ", "DIL_CIST"], duvod="stejne"))
        self.assertEqual(self.audity("ROLE", self.role["OPER"], od), [])

    def test_zmena_nazvu_a_popisu(self):
        od = self.audit_zacatek()
        role = sluzby.zmen_roli.__wrapped__(self.spoj, role_id=self.role["TECH"], kdo=self.kdo,
                                            vstup=ZmenaRoleVstup(nazev="Technologie", popis=None,
                                                                 duvod="prejmenovani"))
        self.assertEqual((role.nazev, role.popis), ("Technologie", None))
        self.assertEqual(self.audity("ROLE", self.role["TECH"], od),
                         [("NazevRole", "Technolog", "Technologie", "prejmenovani"),
                          ("Popis", "Kmenová data související s technologií, min/max dle kompetence.", None,
                           "prejmenovani")])

    def test_pojistky_role(self):
        self.assertEqual(chybna_pole(sluzby.zmen_roli.__wrapped__, self.spoj, role_id=self.role["OPER"],
                                     kdo=self.kdo, vstup=ZmenaRoleVstup(opravneni=["LETAT"], duvod="test")),
                         {"opravneni"})
        self.assertEqual(chybna_pole(sluzby.zmen_roli.__wrapped__, self.spoj, role_id=self.role["ADMIN"],
                                     kdo=self.kdo, vstup=ZmenaRoleVstup(opravneni=["DIL_CIST"], duvod="test")),
                         {"opravneni"})
        self.cekej_chybu("NOT_FOUND", sluzby.zmen_roli.__wrapped__, self.spoj, role_id=999_999, kdo=self.kdo,
                         vstup=ZmenaRoleVstup(nazev="X", duvod="test"))
        self._opravneni_role("ADMIN", "UZIVATEL_EDIT", "DIL_CIST")
        sluzby.zmen_roli.__wrapped__(self.spoj, role_id=self.role["ADMIN"], kdo=self.kdo,
                                     vstup=ZmenaRoleVstup(opravneni=["UZIVATEL_EDIT"], duvod="uzsi kompetence"))
        self.assertEqual(self.spoj.hodnota("SELECT COUNT(*) FROM dbo.RoleOpravneni WHERE RoleID = ?",
                                           self.role["ADMIN"]), 1)


class TestTerminaly(ZakladIdentit):
    def test_evidence_terminalu(self):
        _, kod_druhy = self._vloz_terminal("02", pracoviste=self.pracoviste)
        novy = sluzby.zaloz_terminal.__wrapped__(self.spoj, kdo=self.kdo, vstup=NovyTerminalVstup(
            kod_terminalu=f"pda-{self.znacka}-11", nazev="Nove PDA", pracoviste_id=self.pracoviste))
        self.assertEqual((novy.kod_terminalu, novy.nazev, novy.pracoviste_id, novy.aktivni),
                         (f"PDA-{self.znacka}-11", "Nove PDA", self.pracoviste, True))
        kody = [radek.kod_terminalu for radek in sluzby.seznam_terminalu.__wrapped__(self.spoj).polozky]
        self.assertIn(kod_druhy, kody)
        self.assertLess(kody.index(kod_druhy), kody.index(novy.kod_terminalu))    # řazeno podle kódu
        self.assertEqual({radek[0] for radek in self.audity("TERMINAL", novy.terminal_id)},
                         {"KodTerminalu", "NazevTerminalu", "PracovisteID"})
        self.cekej_chybu("ALREADY_EXISTS", sluzby.zaloz_terminal.__wrapped__, self.spoj, kdo=self.kdo,
                         vstup=NovyTerminalVstup(kod_terminalu=novy.kod_terminalu))
        self.cekej_chybu("NOT_FOUND", sluzby.zmen_terminal.__wrapped__, self.spoj, terminal_id=999_999,
                         kdo=self.kdo, vstup=ZmenaTerminaluVstup(nazev="X", duvod="zkusebni zmena"))

    def test_zmena_terminalu_vcetne_vyrazeni(self):
        terminal, kod = self._vloz_terminal("12")
        od = self.audit_zacatek()
        sluzby.zmen_terminal.__wrapped__(self.spoj, terminal_id=terminal, kdo=self.kdo,
                                         vstup=ZmenaTerminaluVstup(pracoviste_id=self.pracoviste,
                                                                   duvod="presun"))
        druhy = sluzby.zmen_terminal.__wrapped__(self.spoj, terminal_id=terminal, kdo=self.kdo,
                                                 vstup=ZmenaTerminaluVstup(aktivni=False, nazev=None,
                                                                           duvod="srot"))
        self.assertEqual((druhy.kod_terminalu, druhy.nazev, druhy.pracoviste_id, druhy.aktivni),
                         (kod, None, self.pracoviste, False))
        self.assertEqual({radek[0] for radek in self.audity("TERMINAL", terminal, od)},
                         {"PracovisteID", "NazevTerminalu", "Aktivni"})
        self.assertIn("srot", [radek[3] for radek in self.audity("TERMINAL", terminal, od)])

    def test_neexistujici_pracoviste_je_validacni_chyba(self):
        """Přes dekorovanou službu: cizí klíč zahodí transakci vlastního spojení, ne tu testovou."""
        self.assertEqual(chybna_pole(sluzby.zaloz_terminal, kdo=self.kdo, vstup=NovyTerminalVstup(
            kod_terminalu=f"PDA-{self.znacka}-99", pracoviste_id=BEZ_PRACOVISTE)), {"pracovisteId"})
        terminal, _ = self._vloz_terminal("21", pracoviste=self.pracoviste)
        self.assertEqual(chybna_pole(sluzby.zmen_terminal, terminal_id=terminal, kdo=self.kdo,
                                     vstup=ZmenaTerminaluVstup(pracoviste_id=BEZ_PRACOVISTE,
                                                               duvod="presun na nic")), {"pracovisteId"})


class TestPlatnostPrihlaseni(ZakladIdentit):
    """Vyřazení uživatele i odebraná práva platí už příštím požadavkem (hák over_kontext, docs/adr/0007)."""

    def test_vyrazeny_uzivatel_prijde_o_session(self):
        self._opravneni_role("SKL", "UZIVATEL_EDIT")
        uzivatel = self._vloz("SKL", "Honza", "Novak", pin="1234")
        self.ok(self.prihlaseni(self.cisla[uzivatel], "1234"))
        self.assertEqual(self.ok(self.klient.get("/api/identita/ja"))["uzivatelId"], uzivatel)
        sluzby.deaktivuj_uzivatele(uzivatel_id=uzivatel, vstup=DuvodVstup(duvod="odchod z firmy"), kdo=self.kdo)
        obalka = self.chybnou(self.klient.get("/api/identita/ja"), 401, "NOT_AUTHENTICATED")
        self.assertIn("už neplatí", obalka["message"])
        self.chybnou(self.prihlaseni(self.cisla[uzivatel], "1234"), 401, "NOT_AUTHENTICATED")

    def test_opravneni_se_meni_za_behu(self):
        self._opravneni_role("OPER", "DIL_CIST")
        uzivatel = self._vloz("OPER", "Vitek", "Vanek", pin="1234")
        self.ok(self.prihlaseni(self.cisla[uzivatel], "1234"))
        self.chybnou(self.klient.get("/api/identita/uzivatele"), 403, "NO_PERMISSION")
        sluzby.zmen_roli(role_id=self.role["OPER"], kdo=self.kdo,
                         vstup=ZmenaRoleVstup(opravneni=["DIL_CIST", "UZIVATEL_EDIT"], duvod="potrebuje spravovat"))
        self.assertIn("polozky", self.ok(self.klient.get("/api/identita/uzivatele")))
        self.assertEqual(self.ok(self.klient.get("/api/identita/ja"))["opravneni"],
                         ["DIL_CIST", "UZIVATEL_EDIT"])
        sluzby.zmen_roli(role_id=self.role["OPER"], kdo=self.kdo,
                         vstup=ZmenaRoleVstup(opravneni=["DIL_CIST"], duvod="hotovo"))
        self.chybnou(self.klient.get("/api/identita/uzivatele"), 403, "NO_PERMISSION")
        self.assertEqual(self.ok(self.klient.get("/api/identita/ja"))["opravneni"], ["DIL_CIST"])


class TestRozhrani(ZakladIdentit):
    """`nacti_uzivatele` – jediné, co z identity čtou ostatní ostrovy (historie, audit)."""

    def test_nacti_uzivatele_vraci_i_neaktivni(self):
        aktivni = self.zaloz(jmeno="Petr", prijmeni="Adams", role="SKL")
        neaktivni = self.zaloz(jmeno="Eva", prijmeni="Kralova", role="OPER")
        sluzby.deaktivuj_uzivatele.__wrapped__(self.spoj, uzivatel_id=neaktivni.uzivatel_id,
                                               vstup=DuvodVstup(duvod="odchod z firmy"), kdo=self.kdo)

        nacti = rozhrani.nacti_uzivatele(self.spoj, [aktivni.uzivatel_id, neaktivni.uzivatel_id, 999_999])

        self.assertEqual(sorted(nacti), sorted([aktivni.uzivatel_id, neaktivni.uzivatel_id]))
        self.assertEqual(nacti[aktivni.uzivatel_id],
                         rozhrani.UzivatelInfo(aktivni.uzivatel_id, aktivni.osobni_cislo, "Petr Adams", "SKL", True))
        self.assertEqual(nacti[neaktivni.uzivatel_id], rozhrani.UzivatelInfo(
            neaktivni.uzivatel_id, neaktivni.osobni_cislo, "Eva Kralova", "OPER", False))
