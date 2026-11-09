"""Testy ostrova B: čistá pravidla a chyby, které ostrov pozná bez databáze (400, 401, 403).

Data z SQL Serveru (přihlášení, správa uživatelů, rolí a terminálů) testuje
`test_identita_sql.py` – T-SQL se testuje proti skutečnému serveru (docs/adr/0009).
"""
import importlib.util
import unittest
from datetime import datetime, timedelta

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

    def test_posledni_spravce(self):
        domena.over_posledniho_spravce(2)          # vyřadit lze, jeden zůstane
        self.assertEqual(chybna_pole(domena.over_posledniho_spravce, 1), set())
        self.assertEqual(chybna_pole(domena.over_posledniho_spravce, 0), set())

    @unittest.skipUnless(MA_ARGON2, "argon2-cffi není nainstalované (requirements.txt)")
    def test_hash_pinu(self):
        pin_hash = domena.zahashuj_pin("1234")
        self.assertTrue(pin_hash.startswith("$argon2id$"))
        self.assertNotIn("1234", pin_hash)
        self.assertTrue(domena.pin_sedi("1234", pin_hash))
        self.assertFalse(domena.pin_sedi("1235", pin_hash))
        self.assertFalse(domena.pin_sedi("1234", None))          # bez PINu se nepřihlásí nikdy
        self.assertFalse(domena.pin_sedi("1234", "neplatny-hash"))


class TestZamekPinu(unittest.TestCase):
    """Pravidlo zámku po chybných PINech (TD-07, D-33): každý případ zvlášť, bez databáze."""

    TED = datetime(2026, 11, 9, 10, 0)
    ZAMCENO = TED + timedelta(minutes=15)     # zámek, který právě nastal

    def pokus(self, **pole: object) -> tuple:
        """Účet bez předchozích pokusů a bez zámku, podle toho, co test řekne."""
        parametry: dict[str, object] = dict(existuje=True, aktivni=True, zamceno_do=None, pin_plati=True,
                                            chybne_pokusy=0, ted=self.TED)
        parametry.update(pole)
        return domena.vyhodnot_pokus(**parametry)

    def test_nezname_osobni_cislo(self):
        self.assertEqual(self.pokus(existuje=False, pin_plati=False), ("NEZNAMY", 0, None))

    def test_vyrazeny_uzivatel_se_nezamyka(self):
        """Vyřazený účet se nepřihlásí nikdy, takže počítadlo ani zámek nemá co řešit."""
        self.assertEqual(self.pokus(aktivni=False, pin_plati=False, chybne_pokusy=4), ("NEAKTIVNI", 4, None))

    def test_zamceny_ucet_se_neprihlasi_a_zamek_se_neprodlouzi(self):
        """Správný PIN během zámku nepustí a další pokusy zámek neposouvají."""
        for poradi in range(3):
            self.assertEqual(self.pokus(zamceno_do=self.ZAMCENO, pin_plati=poradi % 2 == 0),
                             ("ZAMCENO", 0, self.ZAMCENO))

    def test_uplynuty_zamek_jiz_neplati(self):
        """Ve chvíli, kdy `zamceno_do` nastal, se zkouší dál; pátá chyba zamkne znovu."""
        self.assertEqual(self.pokus(zamceno_do=self.TED), ("USPECH", 0, None))
        self.assertEqual(self.pokus(zamceno_do=self.TED, pin_plati=False, chybne_pokusy=4),
                         ("CHYBNY_PIN", 0, self.ZAMCENO))

    def test_chybne_piny_se_pocitaji(self):
        for poradi in range(1, domena.LIMIT_CHYBNYCH_POKUSU):
            self.assertEqual(self.pokus(pin_plati=False, chybne_pokusy=poradi - 1),
                             ("CHYBNY_PIN", poradi, None))

    def test_patym_chybnym_pinu_se_ucet_zamkne(self):
        """Pátá chyba účet zamkne a počítadlo nechá na nule – řádek pokusu je pořád CHYBNY_PIN."""
        self.assertEqual(self.pokus(pin_plati=False, chybne_pokusy=4), ("CHYBNY_PIN", 0, self.ZAMCENO))

    def test_uspesne_prihlaseni_vynuluje_pocitadlo_i_zamek(self):
        self.assertEqual(self.pokus(chybne_pokusy=3), ("USPECH", 0, None))


class TestChybyBezDatabaze(ZakladTestuOstrova):
    """Chyby, které ostrov pozná dřív, než sáhne do tabulek: formát vstupu a oprávnění."""

    ostrovy = (identita.OSTROV,)

    def test_neprihlaseny_se_nedostane_daleko(self):
        self.over_chybu(self.klient.get("/api/identita/ja"), 401, "NOT_AUTHENTICATED")
        self.over_chybu(self.klient.get("/api/identita/uzivatele"), 401, "NOT_AUTHENTICATED")
        self.over_ok(self.klient.post("/api/identita/odhlaseni"))     # odhlásit se dá i bez přihlášení

    def test_bez_opravneni(self):
        self.prihlas("DIL_CIST", uzivatel_id=1)
        for cesta in ("/api/identita/uzivatele", "/api/identita/role", "/api/identita/terminaly"):
            self.over_chybu(self.klient.get(cesta), 403, "NO_PERMISSION")
        self.over_chybu(self.klient.post("/api/identita/uzivatele/1/odemknout", json={"duvod": "zkusebni"}),
                        403, "NO_PERMISSION")

    def test_spatny_vstup_se_odmi_drive_nez_z_dotazu(self):
        self.prihlas("UZIVATEL_EDIT", uzivatel_id=2)
        self.assertEqual(self.chybna_pole(self.klient.post("/api/identita/uzivatele", json={
            "osobniCislo": "2002", "jmeno": "X", "prijmeni": "Y", "roleId": 1, "pin": "12"})), {"pin"})
        self.assertEqual(self.chybna_pole(self.klient.post("/api/identita/uzivatele", json={
            "osobniCislo": "2002", "jmeno": "X", "prijmeni": "Y", "roleId": 1, "novyPin": "1234"})), {"novyPin"})
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/identita/uzivatele/1", json={
            "roleId": None, "duvod": "oprava"})), {"roleId"})
        self.assertEqual(self.chybna_pole(self.klient.patch("/api/identita/role/1", json={
            "nazev": None, "duvod": "test"})), {"nazev"})
        self.assertEqual(self.chybna_pole(self.klient.post("/api/identita/prihlaseni", json={
            "osobniCislo": "1001", "pin": ""})), {"pin"})
        obalka = self.over_chybu(self.klient.patch("/api/identita/role/1", json={
            "opravneni": ["DIL_CIST"] * 101, "duvod": "test"}), 400, "VALIDATION_ERROR")
        self.assertEqual(obalka["data"]["chyby"][0]["zprava"], "Nejvýše 100 položek.")


if __name__ == "__main__":
    unittest.main()
