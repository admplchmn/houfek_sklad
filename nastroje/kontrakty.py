"""Snímek kontraktů a kontrola, že se po zmrazení mění jen přidáním (P10, sekce 10.1).

    python -m nastroje.kontrakty uloz     uloží kontrakty/openapi.json a kontrakty/rozhrani.json
    python -m nastroje.kontrakty over     porovná aktuální stav se snímkem (CI); chyba = exit 1

Nekompatibilní je:
- HTTP: odebraná cesta nebo metoda, odebraný parametr, nový povinný parametr, odebrané pole
  schématu, nové povinné pole ve vstupu (requestBody),
- rozhraní: odebraná funkce nebo DTO, odebrané pole DTO, změna pořadí či názvu parametru,
  nový povinný parametr, změna návratového typu.
Přidání čehokoli nepovinného je v pořádku.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import pkgutil
import sys
import typing
from pathlib import Path

KOREN = Path(__file__).resolve().parents[1]
SLOZKA = KOREN / "kontrakty"


def _openapi() -> dict:
    from app import create_app
    from app.platforma.konfigurace import Konfigurace
    from app.platforma.openapi import vytvor_openapi

    app = create_app(Konfigurace(vyvoj=True))
    return vytvor_openapi(app)


def _baliky_ostrovu() -> dict[str, str]:
    """prefix ostrova → balík Pythonu. Hledá balík, jehož `OSTROV` je zapojený v OSTROVY,
    takže nezáleží na tom, kde je definovaný blueprint ani jak se balík jmenuje."""
    import app.ostrovy as ostrovy_balik
    from app.ostrovy import OSTROVY

    zapojene = {id(o): o.prefix for o in OSTROVY}
    baliky: dict[str, str] = {}
    for info in pkgutil.iter_modules(ostrovy_balik.__path__, prefix=f"{ostrovy_balik.__name__}."):
        if not info.ispkg:
            continue
        ostrov = getattr(importlib.import_module(info.name), "OSTROV", None)
        if ostrov is not None and id(ostrov) in zapojene:
            baliky[zapojene[id(ostrov)]] = info.name
    chybi = sorted(set(zapojene.values()) - set(baliky))
    if chybi:
        raise RuntimeError(f"Ostrovy bez balíku v app/ostrovy: {', '.join(chybi)}")
    return baliky


def _rozhrani() -> dict:
    vysledek: dict = {}
    for prefix, balik in sorted(_baliky_ostrovu().items()):
        try:
            modul = importlib.import_module(f"{balik}.rozhrani")
        except ModuleNotFoundError as chyba:
            if chyba.name != f"{balik}.rozhrani":
                raise
            vysledek[prefix] = {"funkce": {}, "dto": {}}   # ostrov bez rozhraní (jen HTTP/CLI)
            continue
        funkce, dto = {}, {}
        for nazev, objekt in sorted(vars(modul).items()):
            if nazev.startswith("_") or getattr(objekt, "__module__", "") != modul.__name__:
                continue
            if isinstance(objekt, type) and dataclasses.is_dataclass(objekt):
                dto[nazev] = [p.name for p in dataclasses.fields(objekt)]
            elif inspect.isfunction(objekt):
                podpis = inspect.signature(objekt)
                navrat = typing.get_type_hints(objekt).get("return")
                funkce[nazev] = {
                    "parametry": [{"nazev": p.name, "vychozi": p.default is not inspect.Parameter.empty}
                                  for p in podpis.parameters.values()],
                    "vraci": str(navrat).replace("typing.", ""),
                }
        vysledek[prefix] = {"funkce": funkce, "dto": dto}
    return vysledek


def aktualni() -> dict[str, dict]:
    return {"openapi.json": _openapi(), "rozhrani.json": _rozhrani()}


def _vstupni_schemata(api: dict) -> set[str]:
    """Jména schémat, která klient posílá (requestBody) – u nich je nové povinné pole nekompatibilní."""
    nazvy = set()
    for metody in api.get("paths", {}).values():
        for operace in metody.values():
            ref = (operace.get("requestBody", {}).get("content", {}).get("application/json", {})
                   .get("schema", {}).get("$ref", ""))
            if ref:
                nazvy.add(ref.rsplit("/", 1)[-1])
    return nazvy


def _porovnej_parametry(metoda: str, cesta: str, stare: list[dict], nove: list[dict]) -> list[str]:
    stare_k = {(p["name"], p["in"]): p for p in stare}
    nove_k = {(p["name"], p["in"]): p for p in nove}
    chyby = [f"HTTP: {metoda.upper()} {cesta}: odebrán parametr {n}" for (n, _) in stare_k if (n, _) not in nove_k]
    for klic, parametr in nove_k.items():
        if parametr.get("required") and not stare_k.get(klic, {}).get("required"):
            chyby.append(f"HTTP: {metoda.upper()} {cesta}: nový povinný parametr {klic[0]}")
    return chyby


def porovnej(ulozeny: dict[str, dict], novy: dict[str, dict]) -> list[str]:
    chyby: list[str] = []
    stary_api, novy_api = ulozeny["openapi.json"], novy["openapi.json"]
    for cesta, metody in stary_api.get("paths", {}).items():
        for metoda, operace in metody.items():
            nova = novy_api.get("paths", {}).get(cesta, {}).get(metoda)
            if nova is None:
                chyby.append(f"HTTP: odebráno {metoda.upper()} {cesta}")
                continue
            chyby += _porovnej_parametry(metoda, cesta, operace.get("parameters", []), nova.get("parameters", []))
    nove_schemata = novy_api.get("components", {}).get("schemas", {})
    vstupni = _vstupni_schemata(novy_api)
    for nazev, schema in stary_api.get("components", {}).get("schemas", {}).items():
        if nazev not in nove_schemata:
            chyby.append(f"HTTP: odebráno schéma {nazev}")
            continue
        for pole in schema.get("properties", {}):
            if pole not in nove_schemata[nazev].get("properties", {}):
                chyby.append(f"HTTP: ze schématu {nazev} odebráno pole {pole}")
        if nazev in vstupni:
            for pole in set(nove_schemata[nazev].get("required", [])) - set(schema.get("required", [])):
                chyby.append(f"HTTP: vstup {nazev} má nové povinné pole {pole}")

    for ostrov, stary in ulozeny["rozhrani.json"].items():
        aktualni_ = novy["rozhrani.json"].get(ostrov, {"funkce": {}, "dto": {}})
        for nazev, pole in stary["dto"].items():
            nova_pole = aktualni_["dto"].get(nazev)
            if nova_pole is None:
                chyby.append(f"{ostrov}.rozhrani: odebráno DTO {nazev}")
                continue
            chyby += [f"{ostrov}.rozhrani: z {nazev} odebráno pole {p}" for p in pole if p not in nova_pole]
        for nazev, podpis in stary["funkce"].items():
            novy_podpis = aktualni_["funkce"].get(nazev)
            if novy_podpis is None:
                chyby.append(f"{ostrov}.rozhrani: odebrána funkce {nazev}")
                continue
            stare_p, nove_p = podpis["parametry"], novy_podpis["parametry"]
            if [p["nazev"] for p in nove_p[:len(stare_p)]] != [p["nazev"] for p in stare_p]:
                chyby.append(f"{ostrov}.rozhrani.{nazev}: změněné parametry")
            chyby += [f"{ostrov}.rozhrani.{nazev}: nový povinný parametr {p['nazev']}"
                      for p in nove_p[len(stare_p):] if not p["vychozi"]]
            if podpis["vraci"] != novy_podpis["vraci"]:
                chyby.append(f"{ostrov}.rozhrani.{nazev}: změněný návratový typ")
    return chyby


def main(argv: list[str]) -> int:
    prikaz = argv[1] if len(argv) > 1 else "over"
    novy = aktualni()
    if prikaz == "uloz":
        SLOZKA.mkdir(exist_ok=True)
        for soubor, obsah in novy.items():
            (SLOZKA / soubor).write_text(json.dumps(obsah, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Snímek kontraktů uložen do {SLOZKA}")
        return 0
    ulozeny = {s: json.loads((SLOZKA / s).read_text(encoding="utf-8")) for s in novy}
    chyby = porovnej(ulozeny, novy)
    for chyba in chyby:
        print(f"- {chyba}")
    print("Kontrakty jsou kompatibilní." if not chyby else f"Nekompatibilních změn: {len(chyby)}")
    return 1 if chyby else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
