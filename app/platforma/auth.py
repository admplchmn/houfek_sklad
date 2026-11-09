"""Přihlášený uživatel a oprávnění (sekce 5.4 dokumentu Ostrovy, docs/adr/0007).

- Každý endpoint pod /api vyžaduje přihlášení, pokud nemá dekorátor @verejne.
- @vyzaduje("SKLAD_VYDEJ") navíc ověří oprávnění.
- Session plní jen ostrov Identita voláním `prihlas(kontext)`; ostatní ostrovy session nečtou,
  používají `kontext()`.
- Ostrov Identita může v `Ostrov(overeni_kontextu=…)` dodat funkci, která při každém požadavku
  ověří, že uživatel je stále aktivní, a vrátí jeho aktuální oprávnění. Odebrání práv nebo
  deaktivace pak platí okamžitě, ne až po vypršení session.
- Relace přihlášená z terminálu (PDA) navíc vyprší po 15 minutách nečinnosti (TD-06, D-34).
  Bez terminálu (PC) platí i nadále 12 h, limit na PC ještě rozhodnutý není.
"""
from __future__ import annotations

import functools
from datetime import datetime, timedelta
from typing import Any, Callable

from flask import Flask, current_app, g, request, session

from .chyby import AppError
from .kontrakty import teď
from .typy import Kontext

KLIC = "houfek_kontext"
OVERENI = "houfek_overeni_kontextu"
POSLEDNI = "houfek_posledni_aktivita"          # čas poslední přihlášené aktivity, ISO v UTC

NECINNOST_TERMINALU = timedelta(minutes=15)     # D-34: PDA se odhlásí po 15 minutách nečinnosti

OvereniKontextu = Callable[[Kontext], "Kontext | None"]


def prihlas(kdo: Kontext) -> None:
    session.clear()
    session[KLIC] = {
        "uzivatelId": kdo.uzivatel_id,
        "terminalId": kdo.terminal_id,
        "kodRole": kdo.kod_role,
        "opravneni": sorted(kdo.opravneni),
    }
    session[POSLEDNI] = teď().isoformat()
    session.permanent = True
    g.houfek_kontext = kdo


def odhlas() -> None:
    session.clear()
    g.pop("houfek_kontext", None)


def nastav_overeni_kontextu(app: Flask, overeni: OvereniKontextu) -> None:
    app.extensions[OVERENI] = overeni


def _overe_necinnost(data: dict) -> None:
    """Relace přihlášená z terminálu (PDA) nesmí nečinností přesáhnout 15 minut (TD-06, D-34).

    Čas poslední přihlášené aktivity držíme v session a obnovujeme ho tady, tedy na každém
    požadavku, který přihlášení vyžaduje – posuvně, jak stanoví D-34. Relace bez terminálu (PC)
    se řídí `PERMANENT_SESSION_LIFETIME` 12 h, ke které se limit na PC teprve doplní (D-34).
    """
    if data.get("terminalId") is None:
        return
    ted = teď()
    posledni = session.get(POSLEDNI)
    if posledni is not None and ted - datetime.fromisoformat(posledni) >= NECINNOST_TERMINALU:
        session.clear()
        raise AppError("NOT_AUTHENTICATED")
    session[POSLEDNI] = ted.isoformat()


def kontext() -> Kontext:
    """Přihlášený uživatel tohoto požadavku. Chyba NOT_AUTHENTICATED, když nikdo přihlášen není."""
    if "houfek_kontext" in g:
        return g.houfek_kontext
    data = session.get(KLIC)
    if not data:
        raise AppError("NOT_AUTHENTICATED")
    _overe_necinnost(data)
    kdo = Kontext(uzivatel_id=int(data["uzivatelId"]), terminal_id=data.get("terminalId"),
                  kod_role=data["kodRole"], opravneni=frozenset(data["opravneni"]))
    overeni = current_app.extensions.get(OVERENI)
    if overeni is not None:
        aktualni = overeni(kdo)
        if aktualni is None:
            session.clear()
            raise AppError("NOT_AUTHENTICATED", "Přihlášení už neplatí. Přihlaste se znovu.")
        kdo = aktualni
    g.houfek_kontext = kdo
    return kdo


def vyzaduje(*opravneni: str) -> Callable:
    def dekorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def obal(*args: Any, **kwargs: Any) -> Any:
            kdo = kontext()
            chybi = [o for o in opravneni if not kdo.ma(o)]
            if chybi:
                raise AppError("NO_PERMISSION", data={"chybiOpravneni": chybi})
            return fn(*args, **kwargs)

        obal.__houfek_opravneni__ = tuple(opravneni)  # type: ignore[attr-defined]
        return obal

    return dekorator


def verejne(fn: Callable) -> Callable:
    """Endpoint dostupný bez přihlášení (jen přihlášení, zdraví, dokumentace API)."""
    fn.__houfek_verejne__ = True  # type: ignore[attr-defined]
    return fn


def nastav_auth(app: Flask, vyvoj: bool) -> None:
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=not vyvoj,
        SESSION_COOKIE_NAME="houfek_sklad",
    )

    @app.before_request
    def _vyzaduj_prihlaseni() -> None:
        if not request.path.startswith("/api/") or request.endpoint is None:
            return
        pohled = current_app.view_functions.get(request.endpoint)
        if pohled is not None and getattr(pohled, "__houfek_verejne__", False):
            return
        kontext()  # vyvolá NOT_AUTHENTICATED
