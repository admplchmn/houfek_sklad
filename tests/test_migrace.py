"""Statická kontrola migrací (SQL Server tu není – T-SQL se poprvé spustí až při `flask db upgrade`).

Hlídá, co by jinak spadlo až na databázi nebo se tiše rozešlo:
- číslování a hlavička skriptů (XACT_ABORT, žádné USE),
- každý pohled deklarovaný ostrovem (Ostrov.pohledy) vzniká v migraci,
- pohledy.sql ostrova = poslední definice pohledu v migracích (návrh se nerozejde s nasazeným),
- pohled čte jen pohledy založené dřív (pořadí C → D → B → E),
- každý sloupec `alias.Sloupec` v pohledu existuje v tabulce nebo pohledu, na který alias ukazuje.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.ostrovy import OSTROVY
from app.platforma.migrace_db import rozdel_na_davky
from app.platforma.system import PLATFORMA

KOREN = Path(__file__).resolve().parents[1]
MIGRACE = sorted((KOREN / "sql" / "migrace").glob("[0-9][0-9][0-9]_*.sql"))
_POHLED = re.compile(r"CREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+dbo\.(\w+)\s+AS\s+(.*)", re.IGNORECASE | re.DOTALL)
_TABULKA = re.compile(r"CREATE\s+TABLE\s+dbo\.(\w+)\s*\((.*?)\n\);", re.IGNORECASE | re.DOTALL)
_ZDROJ = re.compile(r"\b(?:FROM|JOIN)\s+dbo\.(\w+)(?:\s+AS)?\s+(\w+)", re.IGNORECASE)
_KLICOVA = {"ON", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS", "GROUP", "ORDER", "UNION"}


def _bez_komentaru(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def _normalizuj(sql: str) -> str:
    return re.sub(r"\s+", " ", _bez_komentaru(sql)).strip().rstrip(";").strip()


def _pohledy_v(sql: str) -> list[tuple[str, str]]:
    """[(název, tělo)] pohledů ze skriptu, po dávkách oddělených GO."""
    vysledek = []
    for davka in rozdel_na_davky(sql):
        nalez = _POHLED.search(_bez_komentaru(davka))
        if nalez:
            vysledek.append((nalez[1], nalez[2]))
    return vysledek


def _tabulky() -> dict[str, set[str]]:
    sloupce: dict[str, set[str]] = {}
    for skript in MIGRACE:
        for nazev, telo in _TABULKA.findall(_bez_komentaru(skript.read_text(encoding="utf-8"))):
            sloupce[nazev] = {r.split()[0] for r in telo.splitlines()
                              if r.strip() and not r.strip().upper().startswith(("CONSTRAINT", "PRIMARY", "INDEX"))
                              and re.match(r"\s+\w+\s", r)}
    for skript in MIGRACE:   # ALTER TABLE … ADD Sloupec
        for nazev, sloupec in re.findall(r"ALTER\s+TABLE\s+dbo\.(\w+)\s+ADD\s+(\w+)\s+(?!CONSTRAINT)",
                                         _bez_komentaru(skript.read_text(encoding="utf-8")), re.IGNORECASE):
            if sloupec.upper() != "CONSTRAINT":
                sloupce.setdefault(nazev, set()).add(sloupec)
    return sloupce


def _vystupni_sloupce(telo: str) -> set[str]:
    """Názvy sloupců, které pohled vrací (SELECT … FROM nejvyšší úrovně, i za WITH …)."""
    hloubka, hlavni = 0, telo
    for slovo in re.finditer(r"\(|\)|\bSELECT\b", telo, re.IGNORECASE):
        if slovo[0] == "(":
            hloubka += 1
        elif slovo[0] == ")":
            hloubka -= 1
        elif hloubka == 0:          # první SELECT mimo závorky = hlavní dotaz (i po WITH … AS (…))
            hlavni = telo[slovo.start():]
            break
    seznam = re.search(r"SELECT\s+(.*?)\s+FROM\s", hlavni, re.IGNORECASE | re.DOTALL)[1]
    polozky, hloubka, aktualni = [], 0, ""
    for znak in seznam:
        hloubka += znak == "("
        hloubka -= znak == ")"
        if znak == "," and hloubka == 0:
            polozky.append(aktualni)
            aktualni = ""
        else:
            aktualni += znak
    polozky.append(aktualni)
    nazvy = set()
    for polozka in polozky:
        alias = re.search(r"\bAS\s+(\w+)\s*$", polozka.strip(), re.IGNORECASE)
        nazvy.add(alias[1] if alias else re.findall(r"\w+", polozka)[-1])
    return nazvy


class TestMigrace(unittest.TestCase):
    def setUp(self):
        self.pohledy: dict[str, str] = {}          # poslední definice z migrací
        self.poradi: list[str] = []
        for skript in MIGRACE:
            for nazev, telo in _pohledy_v(skript.read_text(encoding="utf-8")):
                self.pohledy[nazev] = telo
                self.poradi.append(nazev)

    def test_cislovani_a_hlavicka(self):
        cisla = [int(s.name[:3]) for s in MIGRACE]
        self.assertEqual(cisla, list(range(1, len(cisla) + 1)), "migrace se číslují 001, 002 … bez mezer")
        for skript in MIGRACE:
            text = _bez_komentaru(skript.read_text(encoding="utf-8"))
            self.assertIn("SET XACT_ABORT ON", text, skript.name)
            self.assertNotRegex(text, r"(?im)^\s*USE\s", f"{skript.name}: databázi určuje připojení, ne skript")
            self.assertTrue(all(d.strip() for d in rozdel_na_davky(skript.read_text(encoding="utf-8"))), skript.name)

    def test_casove_defaulty_jsou_utc(self):
        """TD-11: DATETIME2 drží UTC. Místní čas (`SYSDATETIME()`, `GETDATE()`) závisí na pásmu stroje."""
        for skript in [*MIGRACE, KOREN / "app" / "platforma" / "migrace_db.py"]:
            self.assertNotRegex(_bez_komentaru(skript.read_text(encoding="utf-8")),
                                r"(?i)\b(SYSDATETIME|GETDATE)\s*\(\s*\)",
                                f"{skript.name}: DEFAULT z místního času stroje – použij SYSUTCDATETIME()")

    def test_kazdy_deklarovany_pohled_vznika_v_migraci(self):
        for ostrov in [PLATFORMA, *OSTROVY]:
            for pohled in ostrov.pohledy:
                self.assertIn(pohled, self.pohledy, f"{ostrov.nazev}: pohled {pohled} není v žádné migraci")
        self.assertEqual(len(self.poradi), len(set(self.poradi)), "CREATE VIEW dvakrát – změna = CREATE OR ALTER")

    def test_pohledy_sql_odpovida_migracim(self):
        for ostrov in OSTROVY:
            slozka = KOREN / "app" / "ostrovy" / ostrov.api.import_name.split(".")[2] if ostrov.api else None
            if slozka is None or not (slozka / "pohledy.sql").exists():
                continue
            navrh = dict(_pohledy_v((slozka / "pohledy.sql").read_text(encoding="utf-8")))
            self.assertEqual(set(navrh), set(ostrov.pohledy), f"{ostrov.nazev}: pohledy.sql ≠ Ostrov.pohledy")
            for nazev, telo in navrh.items():
                self.assertEqual(_normalizuj(telo), _normalizuj(self.pohledy[nazev]),
                                 f"{nazev}: pohledy.sql ostrova {ostrov.nazev} se liší od migrace – změna pohledu "
                                 "= nová migrace s CREATE OR ALTER VIEW")

    def test_pohled_cte_jen_drive_zalozene_pohledy(self):
        for i, nazev in enumerate(self.poradi):
            for zdroj, _ in _ZDROJ.findall(self.pohledy[nazev]):
                if zdroj.startswith("v_"):
                    self.assertIn(zdroj, self.poradi[:i], f"{nazev} čte {zdroj}, který vzniká až později")

    def test_sloupce_v_pohledech_existuji(self):
        tabulky = _tabulky()
        objekty = {**tabulky, **{n: _vystupni_sloupce(t) for n, t in self.pohledy.items()}}
        chyby = []
        for nazev, telo in self.pohledy.items():
            for cast in re.split(r"\bUNION\s+ALL\b", _bez_komentaru(telo), flags=re.IGNORECASE):
                # aliasy platí v každé části UNION zvlášť (v_KontrolaIntegrity používá „s“ pro různé tabulky)
                aliasy = {alias: zdroj for zdroj, alias in _ZDROJ.findall(cast) if alias.upper() not in _KLICOVA}
                for alias, sloupec in re.findall(r"\b(\w+)\.(\w+)\b", cast):
                    if alias == "dbo" or alias not in aliasy:
                        continue   # CTE nebo poddotaz – jejich sloupce tu nekontrolujeme
                    if sloupec not in objekty.get(aliasy[alias], set()):
                        chyby.append(f"{nazev}: {alias}.{sloupec} – sloupec není v dbo.{aliasy[alias]}")
        self.assertEqual(chyby, [], "\n".join(chyby))

    def test_kontrola_sama_najde_preklep(self):
        """Pojistka testu: překlep ve sloupci se opravdu ohlásí."""
        tabulky = _tabulky()
        self.assertIn("KodBoxu", tabulky["Box"])
        self.assertNotIn("KodBoxuX", tabulky["Box"])
        self.assertEqual(_vystupni_sloupce("SELECT a.X, b.Y AS Z, CAST(1 AS BIT) AS W FROM dbo.T AS a"),
                         {"X", "Z", "W"})


if __name__ == "__main__":
    unittest.main()
