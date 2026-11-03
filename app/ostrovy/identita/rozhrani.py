"""VEŘEJNÉ ROZHRANÍ ostrova B – Identita (sekce 7.2).

Přihlášení plní session voláním app.platforma.auth.prihlas(Kontext(...)); ostatní ostrovy
session nečtou. Pro ostatní ostrovy je tu jen načtení jmen uživatelů (historie, audit).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.platforma.db import Spojeni


@dataclass(frozen=True)
class UzivatelInfo:
    uzivatel_id: int
    osobni_cislo: str
    cele_jmeno: str
    kod_role: str          # OPER | SKL | MISTR | TECH | ADMIN
    aktivni: bool


def nacti_uzivatele(spoj: Spojeni, uzivatel_ids: list[int]) -> dict[int, UzivatelInfo]:
    """Uživatelé podle ID (i neaktivní); neexistující ve výsledku chybí. PIN se nikdy nevrací."""
    from . import ukazky  # KOSTRA (fáze 0)

    return {i: UzivatelInfo(u.uzivatel_id, u.osobni_cislo, u.cele_jmeno, u.kod_role, u.aktivni)
            for i in uzivatel_ids if (u := ukazky.UZIVATELE.get(i)) is not None}
