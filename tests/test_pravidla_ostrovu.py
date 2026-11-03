"""Automatická kontrola pravidel ostrovů (sekce 3.2 a 10.1 dokumentu Ostrovy).

Hlídá P1 (zápis jen do vlastních tabulek), P2 (cizí data jen z pohledů v_*), P3 (z cizího
ostrova jen rozhrani a jen ve směru mapy závislostí), P4 (rozhraní bez Flasku) a P6 (DTO jsou
neměnná). Mapu ZAVISLOSTI mění jen P1 (vedoucí) po dohodě – je to architektura.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import re
import typing
import unittest
from pathlib import Path

from app.ostrovy import OSTROVY

KOREN = Path(__file__).resolve().parents[1]
OSTROVY_DIR = KOREN / "app" / "ostrovy"

# Kdo smí volat koho (mapa ostrovů, sekce 2). Platformu smí volat každý.
ZAVISLOSTI: dict[str, set[str]] = {
    "_sablona": set(),
    "identita": set(),
    "struktura": set(),
    "dily": set(),
    "sklad": {"struktura", "dily"},
    "inventura": {"struktura", "dily", "sklad"},
    "prehledy": {"identita", "struktura", "dily", "sklad"},
    "migrace": {"struktura", "dily", "sklad"},
}
POVINNE_SOUBORY = ["__init__.py", "rozhrani.py", "kontrakty.py", "sluzby.py", "domena.py", "repozitar.py",
                   "ukazky.py", "pohledy.sql", "testy/__init__.py"]
ZAKAZANE_V_ROZHRANI = {"flask", "app.platforma.auth", "app.platforma.http"}

_ZAPIS = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE(?:\s+INTO)?)\s+dbo\.(\w+)", re.IGNORECASE)
_CTENI = re.compile(r"\b(?:FROM|JOIN)\s+dbo\.(\w+)", re.IGNORECASE)


def _slozky() -> list[Path]:
    return sorted(p for p in OSTROVY_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists())


def _soubory_py(slozka: Path) -> list[Path]:
    return [p for p in slozka.rglob("*.py") if "__pycache__" not in p.parts]


def _ostrov_modulu(slozka: Path):
    return importlib.import_module(f"app.ostrovy.{slozka.name}").OSTROV


def _importy(soubor: Path) -> list[tuple[str, int]]:
    """Plné názvy importovaných modulů (from X import Y → X.Y i X)."""
    strom = ast.parse(soubor.read_text(encoding="utf-8"))
    vysledek = []
    for uzel in ast.walk(strom):
        if isinstance(uzel, ast.Import):
            vysledek += [(a.name, uzel.lineno) for a in uzel.names]
        elif isinstance(uzel, ast.ImportFrom) and uzel.level == 0 and uzel.module:
            vysledek.append((uzel.module, uzel.lineno))
            vysledek += [(f"{uzel.module}.{a.name}", uzel.lineno) for a in uzel.names]
    return vysledek


def _retezce(soubor: Path) -> list[tuple[str, int]]:
    strom = ast.parse(soubor.read_text(encoding="utf-8"))
    return [(u.value, u.lineno) for u in ast.walk(strom) if isinstance(u, ast.Constant) and isinstance(u.value, str)]


class TestStruktura(unittest.TestCase):
    def test_vsechny_ostrovy_maji_povinne_soubory(self):
        for slozka in _slozky():
            for soubor in POVINNE_SOUBORY:
                self.assertTrue((slozka / soubor).exists(), f"{slozka.name}: chybí {soubor}")

    def test_ostrovy_jsou_v_mape_a_v_seznamu(self):
        nazvy = {s.name for s in _slozky()}
        self.assertEqual(nazvy, set(ZAVISLOSTI), "nový ostrov doplňte do ZAVISLOSTI (schvaluje P1)")
        zapojene = {o.prefix for o in OSTROVY}
        for slozka in _slozky():
            if slozka.name != "_sablona":
                self.assertIn(_ostrov_modulu(slozka).prefix, zapojene, f"{slozka.name} chybí v OSTROVY")


class TestImporty(unittest.TestCase):
    def test_p3_jen_rozhrani_a_jen_po_mape(self):
        chyby = []
        for slozka in _slozky():
            for soubor in _soubory_py(slozka):
                for modul, radek in _importy(soubor):
                    nalez = re.fullmatch(r"app\.ostrovy\.(\w+)(?:\.(\w+))?(?:\..*)?", modul)
                    if not nalez or nalez[1] == slozka.name:
                        continue
                    cizi, podmodul = nalez[1], nalez[2]
                    if podmodul is None:
                        continue   # "from app.ostrovy.x import rozhrani" se kontroluje přes x.rozhrani
                    misto = f"{soubor.relative_to(KOREN)}:{radek}"
                    # Testy spotřebitele smějí použít vzorová data dodavatele (ukazky), ale jen po mapě.
                    povolene = ("rozhrani", "ukazky") if "testy" in soubor.parts else ("rozhrani",)
                    if podmodul not in povolene:
                        chyby.append(f"{misto}: import {modul} – z cizího ostrova jen rozhrani (P3)")
                    elif cizi not in ZAVISLOSTI[slozka.name]:
                        chyby.append(f"{misto}: {slozka.name} nesmí volat {cizi} (mapa závislostí)")
        self.assertEqual(chyby, [], "\n".join(chyby))

    def test_p4_rozhrani_bez_flasku(self):
        chyby = []
        for slozka in _slozky():
            for modul, radek in _importy(slozka / "rozhrani.py"):
                if any(modul == z or modul.startswith(z + ".") for z in ZAKAZANE_V_ROZHRANI):
                    chyby.append(f"{slozka.name}/rozhrani.py:{radek}: import {modul} (P4)")
        self.assertEqual(chyby, [], "\n".join(chyby))


class TestSql(unittest.TestCase):
    def test_p1_p2_vlastni_tabulky_a_cizi_pohledy(self):
        chyby = []
        for slozka in _slozky():
            ostrov = _ostrov_modulu(slozka)
            vlastni = set(ostrov.tabulky) | set(ostrov.pohledy)
            for soubor in _soubory_py(slozka):
                if "testy" in soubor.parts:
                    continue
                for text, radek in _retezce(soubor):
                    misto = f"{soubor.relative_to(KOREN)}:{radek}"
                    for tabulka in _ZAPIS.findall(text):
                        if tabulka not in ostrov.tabulky:
                            chyby.append(f"{misto}: zápis do dbo.{tabulka} – patří jinému ostrovu (P1)")
                    for tabulka in _CTENI.findall(text):
                        if tabulka not in vlastni and not tabulka.startswith("v_"):
                            chyby.append(f"{misto}: čtení dbo.{tabulka} – cizí data jen z pohledů v_* (P2)")
        self.assertEqual(chyby, [], "\n".join(chyby))


class TestCteni(unittest.TestCase):
    """TD-09: služba @cteni nezapisuje – čtecí spojení se na konci vrací zpět a zápis by se ztratil.

    Za běhu to hlídá i Spojeni.jen_cteni; tohle pravidlo chybu najde dřív, už v pull requestu.
    """

    def test_cteni_bez_zapisu(self):
        chyby = []
        soubory = [p for s in _slozky() for p in _soubory_py(s) if "testy" not in p.parts]
        soubory += sorted((KOREN / "app" / "platforma").glob("*.py"))
        for soubor in soubory:
            strom = ast.parse(soubor.read_text(encoding="utf-8"))
            for fn in ast.walk(strom):
                if not isinstance(fn, ast.FunctionDef) or not any(
                        (isinstance(d, ast.Name) and d.id == "cteni")
                        or (isinstance(d, ast.Attribute) and d.attr == "cteni") for d in fn.decorator_list):
                    continue
                misto = f"{soubor.relative_to(KOREN)}:{fn.lineno} {fn.name}"
                for uzel in ast.walk(fn):
                    if isinstance(uzel, ast.Call) and isinstance(uzel.func, ast.Attribute) \
                            and uzel.func.attr in ("proved", "vloz"):
                        chyby.append(f"{misto}: volá {uzel.func.attr}() – zápis patří do @transakce")
                    if isinstance(uzel, ast.Constant) and isinstance(uzel.value, str) and _ZAPIS.search(uzel.value):
                        chyby.append(f"{misto}: SQL se zápisem v @cteni")
        self.assertEqual(chyby, [], "\n".join(chyby))


class TestDto(unittest.TestCase):
    def _tridy(self, typ) -> list[type]:
        if dataclasses.is_dataclass(typ) and isinstance(typ, type):
            return [typ]
        return [t for arg in typing.get_args(typ) for t in self._tridy(arg)]

    def test_p6_rozhrani_vraci_nemenna_dto(self):
        chyby = []
        for slozka in _slozky():
            modul = importlib.import_module(f"app.ostrovy.{slozka.name}.rozhrani")
            for nazev, funkce in vars(modul).items():
                if nazev.startswith("_") or not callable(funkce) or getattr(funkce, "__module__", "") != modul.__name__:
                    continue
                if isinstance(funkce, type):
                    if dataclasses.is_dataclass(funkce) and not funkce.__dataclass_params__.frozen:
                        chyby.append(f"{slozka.name}.{nazev}: DTO musí být @dataclass(frozen=True)")
                    continue
                navrat = typing.get_type_hints(funkce).get("return")
                for trida in self._tridy(navrat):
                    if not trida.__dataclass_params__.frozen:
                        chyby.append(f"{slozka.name}.{nazev}: vrací {trida.__name__}, které není frozen (P6)")
        self.assertEqual(chyby, [], "\n".join(chyby))


if __name__ == "__main__":
    unittest.main()
