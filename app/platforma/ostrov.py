"""Popis ostrova a jeho zapojení do aplikace (sekce 6).

Každý ostrov má v `__init__.py` jeden objekt `OSTROV = Ostrov(...)`. Platforma z něj zaregistruje
cesty /api/{prefix} a /ui/{prefix}, chybové kódy, menu a příkazy CLI a při startu ověří,
že do sebe ostrovy zapadají (sekce 6.4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

import click
from flask import Blueprint, Flask

from .auth import nastav_overeni_kontextu
from .chyby import Chyba, RegistrChyb
from .typy import Kontext


@dataclass(frozen=True)
class PolozkaMenu:
    nazev: str
    cesta: str                       # /ui/{prefix}/…
    opravneni: str | None = None     # bez oprávnění = vidí každý přihlášený


@dataclass(frozen=True)
class Ostrov:
    nazev: str
    prefix: str
    api: Blueprint | None = None
    ui: Blueprint | None = None
    prikazy: Sequence[click.Command] = ()
    tabulky: Sequence[str] = ()
    pohledy: Sequence[str] = ()
    chyby: Sequence[Chyba] = ()
    opravneni: Sequence[str] = ()
    menu: Sequence[PolozkaMenu] = ()
    # Jen ostrov Identita: ověření přihlášeného uživatele při každém požadavku (auth.kontext).
    overeni_kontextu: Callable[[Kontext], Kontext | None] | None = None

    def __post_init__(self) -> None:
        for nazev in ("prikazy", "tabulky", "pohledy", "chyby", "opravneni", "menu"):
            object.__setattr__(self, nazev, tuple(getattr(self, nazev)))


@dataclass
class ZapojeneOstrovy:
    ostrovy: list[Ostrov] = field(default_factory=list)

    @property
    def menu(self) -> list[PolozkaMenu]:
        return [p for o in self.ostrovy for p in o.menu]


def zaregistruj_ostrov(app: Flask, ostrov: Ostrov) -> None:
    if ostrov.api is not None:
        app.register_blueprint(ostrov.api, url_prefix=f"/api/{ostrov.prefix}")
    if ostrov.ui is not None:
        app.register_blueprint(ostrov.ui, url_prefix=f"/ui/{ostrov.prefix}")
    registr: RegistrChyb = app.extensions["houfek_chyby"]
    registr.pridej(ostrov.chyby, ostrov.nazev)
    for prikaz in ostrov.prikazy:
        app.cli.add_command(prikaz)
    if ostrov.overeni_kontextu is not None:
        nastav_overeni_kontextu(app, ostrov.overeni_kontextu)
    app.extensions["houfek_ostrovy"].ostrovy.append(ostrov)


def over_ostrovy(ostrovy: Iterable[Ostrov]) -> None:
    """Startovní kontroly bez databáze. Chyba = aplikace nenastartuje."""
    chyby: list[str] = []
    prefixy: dict[str, str] = {}
    tabulky: dict[str, str] = {}
    pohledy: dict[str, str] = {}
    overovatele: list[str] = []
    for o in ostrovy:
        if o.overeni_kontextu is not None:
            overovatele.append(o.nazev)
        if not re.fullmatch(r"[a-z][a-z0-9-]*", o.prefix):
            chyby.append(f"{o.nazev}: prefix {o.prefix!r} musí být malá písmena bez diakritiky")
        if o.prefix in prefixy:
            chyby.append(f"prefix {o.prefix!r} mají {prefixy[o.prefix]} i {o.nazev}")
        prefixy[o.prefix] = o.nazev
        if o.api is None and not o.prikazy:
            chyby.append(f"{o.nazev}: ostrov nemá api ani prikazy")
        for t in o.tabulky:
            if t in tabulky:
                chyby.append(f"tabulku {t} deklaruje {tabulky[t]} i {o.nazev} (P1: vlastník je jeden)")
            tabulky[t] = o.nazev
        for v in o.pohledy:
            if not v.startswith("v_"):
                chyby.append(f"{o.nazev}: pohled {v} musí začínat v_")
            if v in pohledy:
                chyby.append(f"pohled {v} deklaruje {pohledy[v]} i {o.nazev}")
            pohledy[v] = o.nazev
        for kod in o.opravneni:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", kod):
                chyby.append(f"{o.nazev}: oprávnění {kod!r} musí být VELKÁ_PÍSMENA ASCII")
        for polozka in o.menu:
            if not polozka.cesta.startswith(f"/ui/{o.prefix}"):
                chyby.append(f"{o.nazev}: položka menu {polozka.nazev} vede mimo /ui/{o.prefix}")
    if len(overovatele) > 1:
        chyby.append("overeni_kontextu smí dodat jen jeden ostrov (Identita), dodávají: " + ", ".join(overovatele))
    if chyby:
        raise RuntimeError("Ostrovy do sebe nezapadají:\n- " + "\n- ".join(chyby))


def over_ostrovy_proti_db(ostrovy: Iterable[Ostrov], spoj: Any) -> list[str]:
    """Kontroly proti databázi (flask platforma kontrola). Vrací seznam nálezů."""
    ostrovy = list(ostrovy)
    nalezy: list[str] = []
    v_db = {r["TABLE_NAME"]: r["TABLE_TYPE"] for r in spoj.dotaz(
        "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo'")}
    deklarovane = {t for o in ostrovy for t in o.tabulky}
    for tabulka, typ in sorted(v_db.items()):
        if typ == "BASE TABLE" and tabulka not in deklarovane:
            nalezy.append(f"tabulka dbo.{tabulka} nemá vlastníka (doplňte ji do OSTROV.tabulky)")
    for o in ostrovy:
        for t in o.tabulky:
            if v_db.get(t) != "BASE TABLE":
                nalezy.append(f"{o.nazev}: tabulka dbo.{t} v databázi neexistuje")
        for v in o.pohledy:
            if v_db.get(v) != "VIEW":
                nalezy.append(f"{o.nazev}: pohled dbo.{v} v databázi neexistuje")
    if v_db.get("Opravneni") == "BASE TABLE":
        existujici = {r["KodOpravneni"] for r in spoj.dotaz("SELECT KodOpravneni FROM dbo.Opravneni")}
        for o in ostrovy:
            for kod in o.opravneni:
                if kod not in existujici:
                    nalezy.append(f"{o.nazev}: oprávnění {kod} chybí v tabulce Opravneni")
    return nalezy
