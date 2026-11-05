"""Logika repozitáře ostrova C bez SQL Serveru: co repozitář posílá do databáze.

T-SQL jako takové prověřují integrační testy (test_repozitar_integrace.py); tady bez databáze
ověřujeme hodnoty, které repozitář skládá – dva kroky přepočtu pořadí (Δ2, T23), číselnou řadu
boxů, výchozí rozměr C7 a to, že u každého dotazu sedí počet parametrů k počtu `?`.
"""
from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from app.ostrovy.struktura import repozitar, ukazky
from app.platforma.chyby import AppError

UROVEN = {"KodUrovne": "U03", "KodRegalu": "R01", "KodPracoviste": "PLE"}


class FalesiveSpojeni:
    """Nahradí spojení: čtení odpovídá podle úryvku SQL, zápisy se jen zaznamenají.

    Hlídá i počet parametrů – prohozené nebo chybějící `?` by jinak odhalil až server v CI.
    """

    def __init__(self, *, jeden: dict[str, Any] | None = None, dotaz: dict[str, list] | None = None,
                 hodnota: dict[str, Any] | None = None, dalsi_id: int = 500) -> None:
        self._jeden, self._dotaz, self._hodnota = jeden or {}, dotaz or {}, hodnota or {}
        self.volani: list[tuple[str, tuple]] = []      # všechna zavolaná SQL, v pořadí
        self.zapisy: list[tuple[str, tuple]] = []      # z nich jen INSERT a UPDATE
        self._dalsi_id = dalsi_id

    def _odpoved(self, odpovedi: dict[str, Any], sql: str, metoda: str) -> Any:
        for ryba, odpoved in odpovedi.items():
            if ryba in sql:
                return odpoved
        raise AssertionError(f"{metoda} bez odpovědi na: {sql}")

    def _zavolej(self, sql: str, parametry: tuple) -> None:
        if sql.count("?") != len(parametry):
            raise AssertionError(f"{len(parametry)} parametrů pro {sql.count('?')} `?`: {sql}")
        self.volani.append((sql, parametry))

    def jeden(self, sql: str, *parametry: Any) -> Any:
        self._zavolej(sql, parametry)
        return self._odpoved(self._jeden, sql, "jeden")

    def dotaz(self, sql: str, *parametry: Any) -> list[dict]:
        self._zavolej(sql, parametry)
        return list(self._odpoved(self._dotaz, sql, "dotaz"))

    def hodnota(self, sql: str, *parametry: Any) -> Any:
        self._zavolej(sql, parametry)
        return self._odpoved(self._hodnota, sql, "hodnota")

    def proved(self, sql: str, *parametry: Any) -> int:
        self._zavolej(sql, parametry)
        self.zapisy.append((sql, parametry))
        return 1

    def vloz(self, sql: str, *parametry: Any) -> int:
        self._zavolej(sql, parametry)
        self.zapisy.append((sql, parametry))
        self._dalsi_id += 1
        return self._dalsi_id

    def zapis(self, ryba: str) -> tuple[str, tuple]:
        """Zápis, jehož SQL obsahuje úryvek; chyba, když repozitář nic takového nenapsal."""
        for sql, parametry in self.zapisy:
            if ryba in sql:
                return sql, parametry
        raise AssertionError(f"žádný zápis neobsahuje {ryba!r}: {[s for s, _ in self.zapisy]}")


def spoj_s_urovni(poradi_boxu: tuple[int, ...] = (), cisla_boxu: tuple[int, ...] = (), cleneni: str = "C4",
                  kod_boxu_uz_existuje: bool = False, **jeden_jine) -> FalesiveSpojeni:
    """Úroveň s boxy na pořadí 1…n (PoziceID 11, 12, …), šablonou členění a obsazenou řadou čísel.

    `jeden_jine` přepíše odpověď na dotaz, který vrací jeden řádek (např. chybějící úroveň).
    """
    sablona = [{"SablonaCleneniID": p.sablona_cleneni_id, "DynKod": p.dyn_kod, "StatKod": p.stat_kod,
                "Poradi": p.poradi, "VelikostPoziceID": int(p.velikost[1]), "KodVelikosti": p.velikost}
               for p in ukazky.PRIHRADKY[cleneni]]
    jeden = {"FROM dbo.Uroven AS u": UROVEN, "FROM dbo.CleneniBoxu": {"CleneniBoxuID": ukazky.CLENENI_ID[cleneni]}}
    jeden.update(jeden_jine)
    return FalesiveSpojeni(
        jeden=jeden,
        dotaz={"FROM dbo.Pozice WHERE UrovenID": [{"PoziceID": 10 + p, "Poradi": p} for p in poradi_boxu],
               "FROM dbo.SablonaCleneni AS s": sablona,
               "AS Cislo FROM dbo.Box": [{"Cislo": cislo} for cislo in cisla_boxu]},
        hodnota={"TypBoxuID FROM dbo.TypBoxu": 2, "COUNT(*) FROM dbo.Box": 1 if kod_boxu_uz_existuje else 0},
    )


def vnitrni_pozice_zapisu(spoj: FalesiveSpojeni) -> list[tuple]:
    """(KodPozice, VelikostPoziceID, DelkaMM, HloubkaMM) z INSERTŮ vnitřních pozic, v pořadí zápisů."""
    return [p[2:] for sql, p in spoj.zapisy if "INSERT INTO dbo.VnitrniPoziceBoxu" in sql]


class TestZalozBox(unittest.TestCase):
    def test_vlozeni_doprostred_posune_boxy_vpravo(self):
        """T23: vložení na 2. místo – boxy 12 a 13 jsou na 3. a 4., jejich PoziceID zůstávají (Δ2, dva kroky)."""
        spoj = spoj_s_urovni(poradi_boxu=(1, 2, 3))
        box_id = repozitar.zaloz_box(spoj, 7, 2, "DYN", "C4", Decimal(400), Decimal(360))
        self.assertEqual(box_id, 502)                                       # vloz() vrací ID z SCOPE_IDENTITY
        sql, parametry = spoj.zapis("Poradi = Poradi + ")                   # 1. krok: posun dozadu
        self.assertIn(f"Poradi + {repozitar._PROVISORNI_POSUN}", sql)
        self.assertEqual(parametry, (12, 13))
        self.assertEqual([p for sql, p in spoj.zapisy if "SET Poradi = ?" in sql],
                         [(3, 12), (4, 13)])                                # 2. krok: cílová pořadí
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Pozice")[1], (7, 2))   # nová Pozice (UrovenID, Poradi)

    def test_pridani_na_konec_bez_prectani(self):
        spoj = spoj_s_urovni(poradi_boxu=(1, 2, 3))
        repozitar.zaloz_box(spoj, 7, None, "DYN", "C4", Decimal(400), Decimal(360))
        self.assertEqual([sql for sql, _ in spoj.zapisy if "UPDATE" in sql], [])
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Pozice")[1], (7, 4))

    def test_box_a_adresa(self):
        spoj = spoj_s_urovni(cisla_boxu=(1, 37))
        repozitar.zaloz_box(spoj, 7, None, "DYN", "C4", Decimal(400), Decimal(360))
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Box")[1],
                         (501, "BPLE038", 2, ukazky.CLENENI_ID["C4"], Decimal(400), Decimal(360),
                          "HOUFEK-PLE-R01-U03-BPLE038"))

    def test_stat_rada_a_ciselne_kody_prihradek(self):
        """STAT box: řada BSTAT, kódy přihrádek jsou číslice ze šablony, velikost zůstává ze šablony (Q-05)."""
        spoj = spoj_s_urovni(cisla_boxu=(1,))
        repozitar.zaloz_box(spoj, 7, None, "STAT", "C4", Decimal(400), Decimal(360))
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Box")[1][1], "BSTAT002")
        self.assertEqual(vnitrni_pozice_zapisu(spoj), [("4", 3, None, None), ("3", 3, None, None),
                                                       ("1", 3, None, None), ("2", 3, None, None)])

    def test_dyn_kody_prihradek_c4(self):
        """DYN box C4 má přihrádky G, H, CH, I – písmena ze šablony, ne abeceda od A (Q-06)."""
        spoj = spoj_s_urovni()
        repozitar.zaloz_box(spoj, 7, None, "DYN", "C4", Decimal(400), Decimal(360))
        self.assertEqual(vnitrni_pozice_zapisu(spoj),
                         [("G", 3, None, None), ("H", 3, None, None), ("CH", 3, None, None), ("I", 3, None, None)])

    def test_rozmer_c7_vychozi_rozmer_boxu(self):
        """Q-01: C7 (V6) je jediná pozice s rozměrem – nový box dostane rozměr boxu, ostatní NULL."""
        spoj = spoj_s_urovni(cleneni="C7")
        repozitar.zaloz_box(spoj, 7, None, "DYN", "C7", Decimal(900), Decimal(450))
        self.assertEqual(vnitrni_pozice_zapisu(spoj), [("R", 6, Decimal(900), Decimal(450))])

    def test_dalsi_volne_cislo_rady(self):
        """Řada počítá i vyřazené boxy (dotaz je bez filtru Aktivni) – nejvyšší číslo + 1."""
        spoj = spoj_s_urovni(cisla_boxu=(1, 2, 3, 37, 52))
        repozitar.zaloz_box(spoj, 7, None, "DYN", "C1", Decimal(400), Decimal(360))
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Box")[1][1], "BPLE053")

    def test_zadany_kod_se_normalizuje(self):
        spoj = spoj_s_urovni()
        repozitar.zaloz_box(spoj, 7, None, "DYN", "C1", Decimal(400), Decimal(360), kod_boxu=" bple 007 ")
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Box")[1][1], "BPLE007")

    def kod_chyby(self, *args, **kwargs) -> str:
        """Spojení, ve kterém už každý kód boxu existuje – kolizi tak test odhalí i bez dat."""
        spoj = spoj_s_urovni(kod_boxu_uz_existuje=True)
        with self.assertRaises(AppError) as zachyceno:
            repozitar.zaloz_box(spoj, *args, **kwargs)
        self.assertEqual(spoj.zapisy, [], "před chybou se nic zapsat nemá")
        return zachyceno.exception.kod

    def test_chyby(self):
        self.assertEqual(self.kod_chyby(7, None, "DYN", "C1", Decimal(400), Decimal(360), kod_boxu="BPLE037"),
                         "ALREADY_EXISTS")                                  # jistí se podotazem před zápisem
        self.assertEqual(self.kod_chyby(7, None, "DYN", "C1", Decimal(400), Decimal(360), kod_boxu="BSTAT037"),
                         "VALIDATION_ERROR")                                 # cizí řada nebo pracoviště
        self.assertEqual(self.kod_chyby(7, 9, "DYN", "C4", Decimal(400), Decimal(360)), "VALIDATION_ERROR")
        self.assertEqual(self.kod_chyby(7, None, "MIX", "C1", Decimal(400), Decimal(360)), "VALIDATION_ERROR")
        self.assertEqual(self.kod_chyby(7, None, "DYN", "C1", Decimal(0), Decimal(360)), "VALIDATION_ERROR")

    def test_not_found(self):
        for prekvapeni in ({"FROM dbo.Uroven AS u": None}, {"FROM dbo.CleneniBoxu": None}):
            spoj = spoj_s_urovni(**prekvapeni)
            with self.assertRaises(AppError) as zachyceno:
                repozitar.zaloz_box(spoj, 7, None, "DYN", "C1", Decimal(400), Decimal(360))
            self.assertEqual(zachyceno.exception.kod, "NOT_FOUND")
            self.assertEqual(spoj.zapisy, [])


class TestZalozeniStruktury(unittest.TestCase):
    def test_pracoviste(self):
        spoj = FalesiveSpojeni(hodnota={"COUNT(*) FROM dbo.Pracoviste": 0})
        self.assertEqual(repozitar.zaloz_pracoviste(spoj, " 3mo ", None), 501)
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Pracoviste")[1], ("HOUFEK", "3MO", None))

    def test_regal(self):
        spoj = FalesiveSpojeni(jeden={"FROM dbo.Pracoviste": {"KodPracoviste": "3MO"}},
                               hodnota={"COUNT(*) FROM dbo.Regal": 0})
        self.assertEqual(repozitar.zaloz_regal(spoj, 9, "r3", "U lisu"), 501)
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Regal")[1], (9, "R03", "U lisu"))

    def test_regal_chyby(self):
        spoj = FalesiveSpojeni(jeden={"FROM dbo.Pracoviste": {"KodPracoviste": "3MO"}},
                               hodnota={"COUNT(*) FROM dbo.Regal": 1})
        with self.assertRaises(AppError) as zachyceno:
            repozitar.zaloz_regal(spoj, 9, "R03", None)
        self.assertEqual(zachyceno.exception.kod, "ALREADY_EXISTS")
        self.assertEqual(spoj.zapisy, [])
        bez_pracoviste = FalesiveSpojeni(jeden={"FROM dbo.Pracoviste": None},
                                         hodnota={"COUNT(*) FROM dbo.Regal": 0})
        with self.assertRaises(AppError) as zachyceno:
            repozitar.zaloz_uroven(bez_pracoviste, 9, "U01", 1, Decimal(2400), Decimal(800))
        self.assertEqual(zachyceno.exception.kod, "NOT_FOUND")

    def test_uroven(self):
        spoj = FalesiveSpojeni(hodnota={"COUNT(*) FROM dbo.Regal": 1, "COUNT(*) FROM dbo.Uroven": 0})
        self.assertEqual(repozitar.zaloz_uroven(spoj, 9, "u5", 5, Decimal(2400), Decimal(800)), 501)
        self.assertEqual(spoj.zapis("INSERT INTO dbo.Uroven")[1], (9, "U05", 5, Decimal(2400), Decimal(800)))

    def test_uroven_plocha_musi_mit_rozmer(self):
        """Nulovou plochu by odmítl až CHECK v tabulce – přes hranici ostrova má jít AppError (P7)."""
        spoj = FalesiveSpojeni(hodnota={"COUNT(*) FROM dbo.Regal": 1, "COUNT(*) FROM dbo.Uroven": 0})
        with self.assertRaises(AppError) as zachyceno:
            repozitar.zaloz_uroven(spoj, 9, "u5", 5, Decimal(2400), Decimal(0))
        self.assertEqual(zachyceno.exception.kod, "VALIDATION_ERROR")
        self.assertEqual({c["pole"] for c in zachyceno.exception.data["chyby"]}, {"hloubkaMm"})
        self.assertEqual(spoj.zapisy, [])


class TestCteni(unittest.TestCase):
    def test_misto_z_radku_se_cte_vse(self):
        radek = {"VnitrniPoziceID": 101, "BoxID": 37, "KodMista": "BPLE037-A", "KodBoxu": "BPLE037",
                 "KodPozice": "A", "TypBoxu": "DYN", "Velikost": "V1", "RozmerC7DelkaMM": None,
                 "RozmerC7HloubkaMM": None, "Blokovano": True, "PoradiVBoxu": 1, "KodPracoviste": "PLE",
                 "RegalID": 1, "UrovenID": 3, "Adresa": "HOUFEK-PLE-R01-U03-BPLE037-A", "BoxBlokovany": True}
        misto = repozitar._misto(radek)
        self.assertEqual((misto.kod, misto.velikost, misto.blokovano, misto.box_blokovany, misto.rozmer_c7),
                         ("BPLE037-A", "V1", True, True, None))
        radek.update(RozmerC7DelkaMM=Decimal(800), RozmerC7HloubkaMM=Decimal(400))
        self.assertEqual(repozitar._misto(radek).rozmer_c7.delka_mm, Decimal(800))

    def test_nacti_mista_prazdny_vstup_nespusti_dotaz(self):
        spoj = FalesiveSpojeni()
        self.assertEqual(repozitar.nacti_mista(spoj, []), {})
        self.assertEqual(spoj.volani, [])

    def test_kandidati_se_radi_podle_cisla_boxu_a_poradi_v_boxu(self):
        spoj = FalesiveSpojeni(hodnota={"PracovisteID FROM dbo.Regal": 4}, dotaz={"FROM dbo.v_Misto AS m": []})
        repozitar.kandidatni_mista_dyn(spoj, 3, "V3")
        sql, parametry = spoj.volani[-1]
        self.assertEqual(parametry, ("V3", 3))
        self.assertIn("ORDER BY CAST(RIGHT(m.KodBoxu, 3) AS INT), m.PoradiVBoxu", sql)
        repozitar.kandidatni_mista_dyn(spoj, 3, "V3", cele_pracoviste=True)
        sql, parametry = spoj.volani[-1]
        self.assertEqual(parametry, ("V3", 3, 4))                            # velikost, regál, pracoviště
        self.assertIn("(m.RegalID = ? OR m.PracovisteID = ?)", sql)

    def test_rozsah_inventury(self):
        for typ, sloupec in [("PRAC", "m.PracovisteID"), ("REGAL", "m.RegalID"), ("UROVEN", "m.UrovenID"),
                             ("BOX", "m.BoxID"), ("POZICE", "m.VnitrniPoziceID")]:
            spoj = FalesiveSpojeni(dotaz={"FROM dbo.v_Misto AS m": [{"VnitrniPoziceID": 5},
                                                                    {"VnitrniPoziceID": 7}]})
            self.assertEqual(repozitar.pozice_v_rozsahu(spoj, typ, 1), [5, 7])
            self.assertIn(f"WHERE {sloupec} = ?", spoj.volani[-1][0], typ)
        spoj = FalesiveSpojeni(dotaz={"FROM dbo.v_Misto AS m": [{"VnitrniPoziceID": 5}]})
        self.assertEqual(repozitar.pozice_v_rozsahu(spoj, "FULL", None), [5])
        self.assertNotIn("WHERE", spoj.volani[-1][0])

    def test_rozsah_chyby(self):
        spoj = FalesiveSpojeni(dotaz={"FROM dbo.v_Misto AS m": []})
        for typ, cil in [("SVET", None), ("FULL", 1), ("REGAL", None)]:
            with self.assertRaises(AppError) as zachyceno:
                repozitar.pozice_v_rozsahu(spoj, typ, cil)
            self.assertEqual(zachyceno.exception.kod, "VALIDATION_ERROR", f"{typ} {cil}")
        with self.assertRaises(AppError) as zachyceno:
            repozitar.pozice_v_rozsahu(spoj, "UROVEN", 9)
        self.assertEqual(zachyceno.exception.kod, "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
