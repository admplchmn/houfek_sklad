"""Testy čistých pravidel migrace (docs/migrace-xlsm.md, sekce 2 a 3) – bez databáze."""
import unittest

from app.ostrovy.migrace import domena


class TestTextBunky(unittest.TestCase):
    def test_cislo_se_ulozi_desetinnou_teckou(self):
        self.assertEqual(domena.text_bunky(300), "300")
        self.assertEqual(domena.text_bunky(300.0), "300")        # Excel číslo uloží jako 300.0
        self.assertEqual(domena.text_bunky(26.5), "26.5")
        self.assertEqual(domena.text_bunky(True), "True")

    def test_text_se_ne_prepisuje(self):
        self.assertEqual(domena.text_bunky(" Volný box. "), " Volný box. ")
        self.assertEqual(domena.text_bunky("BPLE01"), "BPLE01")


class TestKodBoxu(unittest.TestCase):
    def test_dve_cislice_se_doplni_na_tri(self):
        self.assertEqual(domena.kod_na_tri_cislice("BPLE01"), "BPLE001")     # D-02
        self.assertEqual(domena.kod_na_tri_cislice(" bple1 "), "BPLE001")
        self.assertEqual(domena.kod_na_tri_cislice("BSTAT29"), "BSTAT029")

    def test_tri_cislice_a_jiny_tvar_zustava(self):
        self.assertEqual(domena.kod_na_tri_cislice("BPLE001"), "BPLE001")
        self.assertEqual(domena.kod_na_tri_cislice("1234"), "1234")          # bez předpony nedoplníme
        self.assertEqual(domena.kod_na_tri_cislice("BPLE"), "BPLE")
        self.assertEqual(domena.kod_na_tri_cislice("U01/P01"), "U01/P01")    # adresa, ne kód boxu


class TestIdentifikacniCislo(unittest.TestCase):
    def test_volny_box_a_volny_slot_nejsou_dil(self):
        for text in ["Volný box.", "Volný slot.", " volný BOX. ", "VOLNÝ SLOT."]:
            self.assertTrue(domena.neni_dil(text), text)
        for text in ["", "CE21RA 10 100194", "ABR31036_1", "Volný"]:
            self.assertFalse(domena.neni_dil(text), text)


class TestRozmer(unittest.TestCase):
    def test_ciselny_rozmer(self):
        self.assertTrue(domena.je_rozmer("300"))
        self.assertTrue(domena.je_rozmer(" 1200 "))
        self.assertTrue(domena.je_rozmer("26,5"))

    def test_chybejici_nebo_textovy_rozmer(self):
        for text in ["", " ", "cca 300", "300 mm", "3 0 0"]:
            self.assertFalse(domena.je_rozmer(text), text)


class TestMinimumAPoznamka(unittest.TestCase):
    def test_minimum_je_prvni_cislo_a_zavorka_jde_do_poznamky(self):
        self.assertEqual(domena.minimum_a_poznamka("50 kusů (1 kus na stroj)", None), (50, "1 kus na stroj"))
        self.assertEqual(domena.minimum_a_poznamka("20", None), (20, None))
        self.assertEqual(domena.minimum_a_poznamka("50 kusů (1 kus na stroj)", "Používat jen na servis"),
                         (50, "1 kus na stroj; Používat jen na servis"))

    def test_bez_minima(self):
        self.assertEqual(domena.minimum_a_poznamka(None, "Musí být 1 mm"), (None, "Musí být 1 mm"))
        self.assertEqual(domena.minimum_a_poznamka("", ""), (None, None))
        self.assertEqual(domena.minimum_a_poznamka("kusů", "Zelený box."), (None, "Zelený box."))


class TestStavBoxu(unittest.TestCase):
    def test_stavy_ktere_se_prevadeji(self):
        self.assertIn("blokovan", domena.vyznam_stavu("BLOK"))
        self.assertIn("členěn", domena.vyznam_stavu("multi"))

    def test_stavy_které_se_neprevadeji(self):
        self.assertEqual(domena.STAVY_BEZ_PREVODU, ("0", "OPER", "MEOP", "POL"))
        for kod in domena.STAVY_BEZ_PREVODU:
            self.assertIsNone(domena.vyznam_stavu(kod), kod)

    def test_neznama_hodnota(self):
        for kod in ["", "Zelená", "OPER › BLOK", "BLOKOVANÝ"]:
            self.assertIsNone(domena.vyznam_stavu(kod), kod)


class TestCleneni(unittest.TestCase):
    def test_navrh_podle_poctu_dilu(self):
        self.assertEqual(domena.navrh_cleneni(2), "C2 nebo C5")
        self.assertEqual(domena.navrh_cleneni(3), "C3")
        self.assertEqual(domena.navrh_cleneni(4), "C4")
        self.assertEqual(domena.navrh_cleneni(6), "C6")

    def test_bez_voditka(self):
        for pocet in [0, 1, 5, 7]:
            self.assertIsNone(domena.navrh_cleneni(pocet), pocet)


class TestVault(unittest.TestCase):
    def test_server_z_odkazu(self):
        self.assertEqual(domena.vault_server("http://srvvault2401.houfek.local/Vault/2/DILY/123.pdf"),
                         "srvvault2401.houfek.local")
        self.assertEqual(domena.vault_server("srvvault2401/Vault/2/DILY/123.pdf"), "srvvault2401")
        self.assertEqual(domena.vault_server(" SRVVAULT2401/123 "), "srvvault2401")
        self.assertEqual(domena.vault_server(""), "")


if __name__ == "__main__":
    unittest.main()
