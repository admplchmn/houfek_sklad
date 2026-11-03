"""Testy ostrova B: čistá pravidla (hotová) a HTTP kontrakt nad vzorovými daty (kostra fáze 0)."""
import importlib.util
import unittest

from app.ostrovy import identita
from app.ostrovy.identita import domena
from app.platforma.chyby import AppError
from tests.pomocnik import ZakladTestuOstrova

MA_ARGON2 = importlib.util.find_spec("argon2") is not None


def chybna_pole(funkce, *args, **kwargs) -> set[str]:
    try:
        funkce(*args, **kwargs)
    except AppError as chyba:
        assert chyba.kod == "VALIDATION_ERROR", chyba.kod
        return {c["pole"] for c in (chyba.data or {}).get("chyby", [])}
    raise AssertionError("čekala se chyba")


class TestPravidla(unittest.TestCase):
    def test_osobni_cislo_pin_terminal(self):
        self.assertEqual(domena.normalizuj_osobni_cislo(" 10 01 "), "1001")
        self.assertEqual(chybna_pole(domena.normalizuj_osobni_cislo, "Novák"), {"osobniCislo"})
        self.assertEqual(domena.over_pin("123456"), "123456")
        for pin in ["123", "123456789", "12a4", " 1234"]:
            self.assertEqual(chybna_pole(domena.over_pin, pin, pole="novyPin"), {"novyPin"}, pin)
        self.assertEqual(domena.normalizuj_kod_terminalu("pda-01"), "PDA-01")
        self.assertEqual(chybna_pole(domena.normalizuj_kod_terminalu, "PDA 01/2"), {"kodTerminalu"})

    def test_opravneni_a_pojistky(self):
        self.assertEqual(domena.over_opravneni(["dil_cist", "DIL_CIST", "BOX_EDIT"], ["DIL_CIST", "BOX_EDIT"]),
                         ["BOX_EDIT", "DIL_CIST"])
        self.assertEqual(chybna_pole(domena.over_opravneni, ["LETAT"], ["DIL_CIST"]), {"opravneni"})
        domena.over_zmenu_role("SKL", [])
        self.assertEqual(chybna_pole(domena.over_zmenu_role, "ADMIN", ["DIL_CIST"]), {"opravneni"})
        self.assertEqual(chybna_pole(domena.over_deaktivaci, 2, 2), set())
        domena.over_deaktivaci(3, 2)

    @unittest.skipUnless(MA_ARGON2, "argon2-cffi není nainstalované (requirements.txt)")
    def test_hash_pinu(self):
        pin_hash = domena.zahashuj_pin("1234")
        self.assertTrue(pin_hash.startswith("$argon2id$"))
        self.assertNotIn("1234", pin_hash)
        self.assertTrue(domena.pin_sedi("1234", pin_hash))
        self.assertFalse(domena.pin_sedi("1235", pin_hash))
        self.assertFalse(domena.pin_sedi("1234", None))          # bez PINu se nepřihlásí nikdy
        self.assertFalse(domena.pin_sedi("1234", "neplatny-hash"))


class TestPrihlaseni(ZakladTestuOstrova):
    ostrovy = (identita.OSTROV,)

    def prihlaseni(self, cislo, pin, terminal=None):
        telo = {"osobniCislo": cislo, "pin": pin}
        if terminal:
            telo["kodTerminalu"] = terminal
        return self.klient.post("/api/identita/prihlaseni", json=telo)

    def test_uspesne_prihlaseni_a_ja(self):
        data = self.over_ok(self.prihlaseni("1001", "1234", "pda-01"))
        self.assertEqual((data["celeJmeno"], data["kodRole"], data["kodTerminalu"], data["pracovisteId"]),
                         ("Jan Novák", "SKL", "PDA-01", 1))
        self.assertIn("SKLAD_VYDEJ", data["opravneni"])
        ja = self.over_ok(self.klient.get("/api/identita/ja"))
        self.assertEqual((ja["uzivatelId"], ja["terminalId"]), (1, 1))
        self.assertFalse({"pin", "pinHash", "kodKarty"} & set(ja))

    def test_chyba_neprozradi_proc(self):
        zpravy = set()
        for cislo, pin in [("1001", "9999"), ("9999", "1234"), ("1003", "1111"), ("1004", ""), ("Nov ák", "1")]:
            obalka = self.over_chybu(self.prihlaseni(cislo, pin or "0"), 401, "NOT_AUTHENTICATED")
            zpravy.add(obalka["message"])
            self.assertIsNone(obalka["data"])
        self.assertEqual(zpravy, {"Neplatné osobní číslo nebo PIN."})
        self.over_chybu(self.klient.get("/api/identita/ja"), 401, "NOT_AUTHENTICATED")

    def test_terminal_a_odhlaseni(self):
        self.assertEqual(self.chybna_pole(self.prihlaseni("1001", "1234", "PDA-09")), {"kodTerminalu"})
        self.over_ok(self.prihlaseni("1001", "1234"))
        self.over_ok(self.klient.post("/api/identita/odhlaseni"))
        self.over_chybu(self.klient.get("/api/identita/ja"), 401, "NOT_AUTHENTICATED")
        self.over_ok(self.klient.post("/api/identita/odhlaseni"))     # bez přihlášení nic nevadí

    def test_vyrazeny_uzivatel_prijde_o_session(self):
        self.prihlas("DIL_CIST", uzivatel_id=3)                         # 1003 je ve vzorových datech vyřazený
        obalka = self.over_chybu(self.klient.get("/api/identita/ja"), 401, "NOT_AUTHENTICATED")
        self.assertIn("už neplatí", obalka["message"])


class TestSprava(ZakladTestuOstrova):
    ostrovy = (identita.OSTROV,)

    def setUp(self):
        super().setUp()
        self.prihlas("UZIVATEL_EDIT", uzivatel_id=2)

    def test_seznam_bez_tajemstvi(self):
        data = self.over_ok(self.klient.get("/api/identita/uzivatele"))
        self.assertEqual(data["celkem"], 3)                              # vyřazený 1003 ve výchozím filtru není
        self.assertEqual(self.over_ok(self.klient.get("/api/identita/uzivatele?aktivni=&hledat=dvořák"))["celkem"], 1)
        klice = set(data["polozky"][0])
        self.assertTrue({"maPin", "maKartu"} <= klice)
        self.assertFalse({"pin", "pinHash", "kodKarty"} & klice)

    def test_zalozeni_a_zmena(self):
        novy = self.over_ok(self.klient.post("/api/identita/uzivatele", json={
            "osobniCislo": " 2001 ", "jmeno": "Ivana", "prijmeni": "Horáková", "roleId": 1, "pin": "2468"}))
        self.assertEqual((novy["osobniCislo"], novy["kodRole"], novy["maPin"]), ("2001", "OPER", True))
        self.over_chybu(self.klient.post("/api/identita/uzivatele", json={
            "osobniCislo": "1001", "jmeno": "X", "prijmeni": "Y", "roleId": 1}), 409, "ALREADY_EXISTS")
        self.assertEqual(self.chybna_pole(self.klient.post("/api/identita/uzivatele", json={
            "osobniCislo": "2002", "jmeno": "X", "prijmeni": "Y", "roleId": 1, "pin": "12"})), {"pin"})
        zmena = self.over_ok(self.klient.patch("/api/identita/uzivatele/1", json={
            "prijmeni": "Nový", "roleId": 3, "kodKarty": "04A2B9", "duvod": "povýšení na mistra"}))
        self.assertEqual((zmena["celeJmeno"], zmena["kodRole"], zmena["maKartu"]), ("Jan Nový", "MISTR", True))
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/identita/uzivatele/1", json={
            "roleId": None, "duvod": "oprava"})), {"roleId"})

    def test_deaktivace_a_pin(self):
        self.assertFalse(self.over_ok(self.klient.post("/api/identita/uzivatele/1/deaktivovat",
                                                       json={"duvod": "odchod z firmy"}))["aktivni"])
        self.over_chybu(self.klient.post("/api/identita/uzivatele/2/deaktivovat", json={"duvod": "omyl"}),
                        400, "VALIDATION_ERROR")
        self.assertTrue(self.over_ok(self.klient.post("/api/identita/uzivatele/4/reset-pinu",
                                                      json={"novyPin": "13579", "duvod": "nový PIN"}))["maPin"])
        self.assertEqual(self.chybna_pole(self.klient.post("/api/identita/uzivatele/4/reset-pinu",
                                                           json={"novyPin": "abc", "duvod": "nový PIN"})), {"novyPin"})

    def test_role(self):
        role = self.over_ok(self.klient.get("/api/identita/role"))["polozky"]
        self.assertEqual([r["kodRole"] for r in role], ["OPER", "SKL", "MISTR", "TECH", "ADMIN"])
        zmena = self.over_ok(self.klient.patch("/api/identita/role/1", json={
            "opravneni": ["dil_cist", "SKLAD_PRIJEM"], "duvod": "bez výdeje"}))
        self.assertEqual(zmena["opravneni"], ["DIL_CIST", "SKLAD_PRIJEM"])
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/identita/role/5", json={
            "opravneni": ["DIL_CIST"], "duvod": "test"})), {"opravneni"})
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/identita/role/1", json={
            "opravneni": ["LETAT"], "duvod": "test"})), {"opravneni"})
        obalka = self.over_chybu(self.klient.patch("/api/identita/role/1", json={
            "opravneni": ["DIL_CIST"] * 101, "duvod": "test"}), 400, "VALIDATION_ERROR")
        self.assertEqual(obalka["data"]["chyby"][0]["zprava"], "Nejvýše 100 položek.")

    def test_terminaly(self):
        self.assertEqual(len(self.over_ok(self.klient.get("/api/identita/terminaly"))["polozky"]), 3)
        self.assertEqual(self.over_ok(self.klient.post("/api/identita/terminaly", json={
            "kodTerminalu": "pda-03", "pracovisteId": 3}))["kodTerminalu"], "PDA-03")
        self.over_chybu(self.klient.post("/api/identita/terminaly", json={"kodTerminalu": "PDA-01"}),
                        409, "ALREADY_EXISTS")
        self.assertTrue(self.over_ok(self.klient.patch("/api/identita/terminaly/3", json={
            "aktivni": True, "duvod": "opravené PDA"}))["aktivni"])

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST", uzivatel_id=1)
        self.over_chybu(self.klient.get("/api/identita/uzivatele"), 403, "NO_PERMISSION")


if __name__ == "__main__":
    unittest.main()
