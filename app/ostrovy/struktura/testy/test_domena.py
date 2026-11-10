"""Testy čistých pravidel ostrova C a shody vzorové šablony členění s výchozími daty migrace 001."""
import itertools
import re
import unittest
from decimal import Decimal
from pathlib import Path

from app.ostrovy.struktura import domena, ukazky
from app.ostrovy.struktura import rozhrani as struktura
from app.platforma.chyby import AppError
from app.platforma.typy import Rozmer

MIGRACE_001 = Path(__file__).resolve().parents[4] / "sql" / "migrace" / "001_schema_g1.sql"
CESKA_ABECEDA = ["A", "B", "C", "D", "E", "F", "G", "H", "CH", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R"]


def chybna_pole(funkce, *args) -> set[str]:
    try:
        funkce(*args)
    except AppError as chyba:
        assert chyba.kod == "VALIDATION_ERROR", chyba.kod
        return {c["pole"] for c in (chyba.data or {}).get("chyby", [])}
    raise AssertionError("čekala se chyba")


class TestKody(unittest.TestCase):
    def test_pracoviste_regal_uroven(self):
        self.assertEqual(domena.normalizuj_kod_pracoviste(" 1sv "), "1SV")
        self.assertEqual(domena.normalizuj_kod_regalu("r1"), "R01")
        self.assertEqual(domena.normalizuj_kod_regalu("R 12"), "R12")
        self.assertEqual(domena.normalizuj_kod_urovne("u0"), "U00")
        self.assertEqual(domena.poradi_z_kodu_urovne("U03"), 3)
        for funkce, kod, pole in [(domena.normalizuj_kod_pracoviste, "PL", "kodPracoviste"),
                                  (domena.normalizuj_kod_pracoviste, "PLÉ", "kodPracoviste"),
                                  (domena.normalizuj_kod_regalu, "R00", "kodRegalu"),
                                  (domena.normalizuj_kod_regalu, "R100", "kodRegalu"),
                                  (domena.normalizuj_kod_urovne, "X03", "kodUrovne")]:
            self.assertEqual(chybna_pole(funkce, kod), {pole}, kod)

    def test_co_se_vytiskne_jde_precist(self):
        """Adresa a kódy z domény musí parser rozložit zpět na stejné části (7.3 „pohromadě, protože“)."""
        for typ, pracoviste, cislo in [("DYN", "PLE", 37), ("DYN", "1SV", 1), ("STAT", "OBR", 999)]:
            kod = domena.kod_boxu(typ, pracoviste, cislo)
            adresa = domena.full_box_klic(pracoviste, "R07", "U00", kod)
            for text in (kod, adresa):
                r = struktura.rozloz_kod(text)
                self.assertEqual((r.typ, r.typ_boxu, r.kod_boxu), ("BOX", typ, kod), text)
            self.assertEqual(struktura.rozloz_kod(adresa).kod_urovne, "U00")
            regal = struktura.rozloz_kod(domena.kod_regalu_barcode(pracoviste, "R07"))
            self.assertEqual((regal.typ, regal.kod_pracoviste, regal.kod_regalu), ("REGAL", pracoviste, "R07"))
        for c in ukazky.CLENENI:
            for p in c.pozice:
                for typ, kod_pozice in (("DYN", p.dyn_kod), ("STAT", p.stat_kod)):
                    kod = domena.kod_boxu(typ, "PLE", 5) + "-" + kod_pozice
                    self.assertEqual(struktura.rozloz_kod(kod).kod_mista, kod)

    def test_rady_boxu(self):
        self.assertEqual(domena.kod_boxu("DYN", "PLE", 37), "BPLE037")
        self.assertEqual(domena.kod_boxu("STAT", "PLE", 7), "BSTAT007")
        self.assertEqual(domena.cislo_boxu("BSTAT037"), 37)
        self.assertEqual(domena.dalsi_cislo_boxu([]), 1)
        self.assertEqual(domena.dalsi_cislo_boxu({1, 2, 40}), 41)          # mezery se samy nedoplňují
        self.assertEqual(chybna_pole(domena.kod_boxu, "DYN", "PLE", 1000), {"cisloBoxu"})
        with self.assertRaises(AppError) as zachyceno:
            domena.dalsi_cislo_boxu([999])
        self.assertEqual(zachyceno.exception.kod, "BOX_SERIES_FULL")

    def test_over_kod_boxu(self):
        """Kód ze štítku musí patřit do řady typu a pracoviště – jinak je to neplatný kód, ne kolize."""
        self.assertEqual(domena.over_kod_boxu("DYN", "PLE", " bple 037 "), "BPLE037")
        self.assertEqual(domena.over_kod_boxu("STAT", "PLE", "bstat001"), "BSTAT001")
        for typ, pracoviste, kod in [("DYN", "PLE", "BSTAT037"), ("DYN", "1SV", "BPLE037"),     # cizí řada
                                     ("DYN", "PLE", "BPLE37"), ("DYN", "PLE", "BPLE1000"),      # špatný počet číslic
                                     ("STAT", "PLE", "BPLE037"), ("DYN", "PLE", "BPLE03A")]:
            self.assertEqual(chybna_pole(domena.over_kod_boxu, typ, pracoviste, kod), {"kodBoxu"}, kod)
        self.assertEqual(chybna_pole(domena.over_kod_boxu, "DYN", "PLE", "BPLE000"), {"cisloBoxu"})


class TestPoradi(unittest.TestCase):
    def test_vlozeni(self):
        self.assertEqual(domena.vloz_do_poradi([11, 12], 99, None), [11, 12, 99])
        self.assertEqual(domena.vloz_do_poradi([11, 12], 99, 1), [99, 11, 12])
        self.assertEqual(domena.vloz_do_poradi([], 99, 1), [99])
        self.assertEqual(chybna_pole(domena.vloz_do_poradi, [11, 12], 99, 4), {"poradi"})

    def test_presun_odebrani_a_zmeny(self):
        self.assertEqual(domena.presun_v_poradi([11, 12, 13], 13, 1), [13, 11, 12])
        self.assertEqual(chybna_pole(domena.presun_v_poradi, [11, 12], 11, 3), {"novePoradi"})
        self.assertEqual(domena.odeber_z_poradi([11, 12, 13], 12), [11, 13])
        self.assertEqual(domena.zmeny_poradi([13, 11, 12], {11: 1, 12: 2, 13: 3}), {13: 1, 11: 2, 12: 3})
        self.assertEqual(domena.zmeny_poradi([11, 13], {11: 1, 12: 2, 13: 3}), {13: 2})
        self.assertEqual(domena.zmeny_poradi([11, 99], {11: 1}), {99: 2})
        self.assertEqual(domena.kod_pozice_urovne(3), "P03")
        self.assertEqual(domena.kod_pozice_urovne(12), "P12")


class TestSablona(unittest.TestCase):
    def test_shoda_s_migraci_001(self):
        """Vzorová šablona = výchozí data SablonaCleneni a CleneniBoxu v migraci 001 (Q-06)."""
        sql = MIGRACE_001.read_text(encoding="utf-8")
        radek = re.compile(r"\('(C\d)',\s*'(\w+)',\s*'(\d)',\s*(\d+),\s*(\d+),\s*(\d+),\s*'(V\d)',\s*"
                           r"([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\)")
        ze_sql = [(r[0], r[1], r[2], int(r[3]), int(r[4]), int(r[5]), r[6], r[7], r[8], r[9], r[10])
                  for r in radek.findall(sql)]
        self.assertEqual(ze_sql, ukazky.SABLONA)
        pocty = dict(re.findall(r"\('(C\d)', (\d+)\)", sql))
        self.assertEqual({k: int(v) for k, v in pocty.items()}, ukazky.POCET_POZIC)

    def test_invarianty_sablony(self):
        for c in ukazky.CLENENI:
            pozice = c.pozice
            self.assertEqual(len(pozice), c.pocet_pozic, c.kod_cleneni)
            # pořadí kandidátů = česká abeceda DYN kódu (CH po H)
            podle_poradi = [p.dyn_kod for p in sorted(pozice, key=lambda p: p.poradi)]
            self.assertEqual(podle_poradi, sorted(podle_poradi, key=CESKA_ABECEDA.index), c.kod_cleneni)
            # STAT čísla 1…n po řadách od zadní řady, zleva doprava
            podle_mrizky = [p.stat_kod for p in sorted(pozice, key=lambda p: (p.rada, p.sloupec))]
            self.assertEqual(podle_mrizky, [str(i) for i in range(1, len(pozice) + 1)], c.kod_cleneni)
            # přihrádky pokryjí celý box a nepřekrývají se
            plocha = sum(Decimal(str(p.rel_sirka)) * Decimal(str(p.rel_hloubka)) for p in pozice)
            self.assertAlmostEqual(float(plocha), 1.0, places=3, msg=c.kod_cleneni)
            for a, b in itertools.combinations(pozice, 2):
                prekryv_x = min(a.rel_x + a.rel_sirka, b.rel_x + b.rel_sirka) - max(a.rel_x, b.rel_x)
                prekryv_y = min(a.rel_y + a.rel_hloubka, b.rel_y + b.rel_hloubka) - max(a.rel_y, b.rel_y)
                self.assertFalse(prekryv_x > 1e-6 and prekryv_y > 1e-6, (c.kod_cleneni, a.dyn_kod, b.dyn_kod))

    def test_pozice_ze_sablony(self):
        dyn = domena.pozice_ze_sablony("DYN", ukazky.PRIHRADKY["C4"])
        self.assertEqual([(p.kod_pozice, p.velikost, p.poradi_v_boxu) for p in dyn],
                         [("G", "V3", 1), ("H", "V3", 2), ("CH", "V3", 3), ("I", "V3", 4)])
        stat = domena.pozice_ze_sablony("STAT", ukazky.PRIHRADKY["C4"])
        self.assertEqual([p.kod_pozice for p in stat], ["4", "3", "1", "2"])
        self.assertEqual([(p.kod_pozice, p.velikost) for p in domena.pozice_ze_sablony("STAT", ukazky.PRIHRADKY["C7"])],
                         [("1", "V6")])

    def test_vzorove_boxy_odpovidaji_sablone(self):
        for box in ukazky.BOXY.values():
            ocekavane = domena.pozice_ze_sablony(box.typ_boxu, ukazky.PRIHRADKY[box.kod_cleneni])
            self.assertEqual([(p.kod_pozice, p.velikost, p.poradi_v_boxu) for p in box.pozice],
                             [(p.kod_pozice, p.velikost, p.poradi_v_boxu) for p in ocekavane], box.kod_boxu)
            self.assertEqual(box.full_box_klic, domena.full_box_klic(box.kod_pracoviste, box.kod_regalu,
                                                                     box.kod_urovne, box.kod_boxu))


class TestPravidlaBoxu(unittest.TestCase):
    def test_presun_dyn_jen_na_svem_pracovisti(self):
        domena.over_presun_boxu("DYN", "BPLE037", "PLE")
        domena.over_presun_boxu("STAT", "BSTAT037", "1SV")
        self.assertEqual(chybna_pole(domena.over_presun_boxu, "DYN", "BPLE037", "1SV"), {"cilUrovenId"})

    def test_rekonfigurace_a_c7(self):
        self.assertEqual(chybna_pole(domena.over_rekonfiguraci, "C4", "C4"), {"cleneniId"})
        box = Rozmer(Decimal("1000"), Decimal("500"))
        self.assertEqual(domena.over_rozmer_c7("V6", Rozmer(Decimal("1000"), Decimal("1")), box).delka_mm, 1000)
        self.assertEqual(chybna_pole(domena.over_rozmer_c7, "V6", Rozmer(Decimal("1000.5"), Decimal("501")), box),
                         {"delkaMm", "hloubkaMm"})
        self.assertEqual(chybna_pole(domena.over_rozmer_c7, "V3", Rozmer(Decimal("10"), Decimal("10")), box), set())

    def test_blokace_a_adresa(self):
        self.assertEqual(domena.cil_blokace("BOX"), "BOX")
        self.assertEqual(domena.cil_blokace("POZICE"), "POZICE")
        self.assertEqual(chybna_pole(domena.cil_blokace, "REGAL"), {"kod"})
        with self.assertRaises(AppError) as zachyceno:
            domena.cil_blokace("TEXT")
        self.assertEqual(zachyceno.exception.kod, "INVALID_BARCODE")
        domena.over_adresu("PLE", "R01", "U03", "BPLE037", "HOUFEK-PLE-R01-U03-BPLE037")
        with self.assertRaises(AppError) as zachyceno:
            domena.over_adresu("PLE", "R01", "U03", "BPLE037", "HOUFEK-PLE-R02-U01-BPLE037")
        self.assertIn("HOUFEK-PLE-R02-U01-BPLE037", zachyceno.exception.zprava)


class TestSvg(unittest.TestCase):
    def test_vzorec_17_1(self):
        souradnice, sirka, vyska = domena.rozmisteni_boxu(
            [Rozmer(Decimal(1000), Decimal(500)), Rozmer(Decimal(400), Decimal(360))])
        self.assertEqual(souradnice, [(20, 20), (1040, 90)])     # druhý box svisle na středové ose
        self.assertEqual((sirka, vyska), (1460, 540))
        self.assertEqual(domena.rozmisteni_boxu([]), ([], 40, 40))
        okraje = domena.OkrajeSvg(levy=Decimal(5), pravy=Decimal(7), horni=Decimal(1), dolni=Decimal(2),
                                  mezera=Decimal(10))
        self.assertEqual(domena.rozmisteni_boxu([Rozmer(Decimal(100), Decimal(50))] * 3, okraje),
                         ([(5, 1), (115, 1), (225, 1)], 332, 53))

    def test_rozlozeni_vzorove_urovne(self):
        self.assertEqual(struktura.rozlozeni_urovne(None, 3), ukazky.ROZLOZENI_U03)
        u04 = struktura.rozlozeni_urovne(None, 4)
        self.assertEqual([(b.kod_boxu, b.x_mm, b.y_mm) for b in u04.boxy], [("BPLE052", 20, 20), ("BPLE038", 1040, 90)])
        self.assertEqual([p.kod_pozice for p in u04.boxy[1].pozice], ["G", "H", "CH", "I"])
        ch = u04.boxy[1].pozice[2]
        self.assertEqual((ch.rel_x, ch.rel_y, ch.rel_sirka, ch.rel_hloubka), (0.0, 0.0, 0.5, 0.5))  # zadní řada vlevo


class TestStitky(unittest.TestCase):
    """Obsah štítků (11.1, 11.2.2, 11.3, D-31): box i vnitřní pozice zvlášť, čárový kód vždy kód místa."""

    @staticmethod
    def podklady(cleneni: str, *, typ_boxu: str = "DYN", cisla: dict[str, str] | None = None):
        """Podklad pro každou pozici šablony v pořadí boxu (stejné pořadí vrátí repozitář).

        `cisla` je {kód pozice: číslo dílu} – tak je pozice načte z aktivního STAT přiřazení.
        """
        prihradky = next(c for c in ukazky.CLENENI if c.kod_cleneni == cleneni).pozice
        return [domena.PodkladStitku(p.dyn_kod if typ_boxu == "DYN" else p.stat_kod,
                                     (cisla or {}).get(p.dyn_kod if typ_boxu == "DYN" else p.stat_kod))
                for p in prihradky]

    def test_dyn_box_c1(self):
        """Box s jedinou pozicí má oba štítky – hlavní i poziční (11.3)."""
        self.assertEqual([(s.typ, s.kod, s.velky_text)
                          for s in domena.sticky_boxu("BPLE037", "DYN", self.podklady("C1"))],
                         [("BOX", "BPLE037", None), ("POZICE_DYN", "BPLE037-A", None)])

    def test_dyn_box_c7(self):
        self.assertEqual([s.kod for s in domena.sticky_boxu("BPLE037", "DYN", self.podklady("C7"))],
                         ["BPLE037", "BPLE037-R"])

    def test_dyn_box_c4(self):
        """Hlavní štítek a za ním pozice v pořadí boxu (šablona C4: G, H, CH, I), bez čísla dílu."""
        stitky = domena.sticky_boxu("BPLE037", "DYN", self.podklady("C4"))
        self.assertEqual([s.kod for s in stitky],
                         ["BPLE037", "BPLE037-G", "BPLE037-H", "BPLE037-CH", "BPLE037-I"])
        self.assertEqual([s.typ for s in stitky], ["BOX"] + ["POZICE_DYN"] * 4)
        self.assertEqual([s.velky_text for s in stitky], [None] * 5)   # obsah DYN pozice se mění (11.1)

    def test_stat_pozice_s_prirazenim(self):
        """STAT štítek tiskne číslo dílu z aktivního přiřazení; na DYN pozici se neuplatní (11.1)."""
        stitky = domena.sticky_boxu("BSTAT037", "STAT", self.podklady("C5", typ_boxu="STAT",
                                                                     cisla={"2": "12345-678"}))
        self.assertEqual([(s.typ, s.kod, s.velky_text) for s in stitky],
                         [("BOX", "BSTAT037", None), ("POZICE_STAT", "BSTAT037-2", "12345-678"),
                          ("POZICE_STAT", "BSTAT037-1", None)])
        self.assertEqual([s.velky_text for s in domena.sticky_boxu("BPLE005", "DYN",
                                                                  self.podklady("C5", cisla={"K": "1234"}))],
                         [None] * 3)

    def test_stat_pozice_bez_prirazeni(self):
        """STAT bez aktivního přiřazení se tiskne bez čísla dílu (výklad dispečera, ne rozhodnutí vedoucího)."""
        self.assertEqual([s.velky_text for s in
                          domena.sticky_boxu("BSTAT037", "STAT", self.podklady("C6", typ_boxu="STAT"))],
                         [None] * 7)

    def test_stitek_jde_precist_zpet(self):
        """Čárový kód obsahuje vždy kód boxu nebo pozice – parser ho přečte zpět na tentýž objekt."""
        for typ, kod_boxu in (("DYN", "BPLE037"), ("STAT", "BSTAT037")):
            for cleneni in ukazky.CLENENI:
                for stitek in domena.sticky_boxu(kod_boxu, typ,
                                                 self.podklady(cleneni.kod_cleneni, typ_boxu=typ)):
                    rozlozeny = struktura.rozloz_kod(stitek.kod)
                    self.assertEqual(rozlozeny.typ, "BOX" if stitek.typ == "BOX" else "POZICE", stitek.kod)
                    self.assertEqual((rozlozeny.typ_boxu, rozlozeny.kod_boxu), (typ, kod_boxu), stitek.kod)
                    self.assertEqual(rozlozeny.kod_mista, None if stitek.typ == "BOX" else stitek.kod)


if __name__ == "__main__":
    unittest.main()
