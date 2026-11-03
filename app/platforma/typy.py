"""Sdílené hodnotové typy. Přidává a mění je jen Platforma (pravidlo P11 obdobně pro kód).

Typy jsou neměnné (frozen), takže je lze bezpečně předávat přes hranice ostrovů (P6).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Kontext:
    """Kdo provádí operaci. Plní ho ostrov Identita při přihlášení, čte Platforma."""

    uzivatel_id: int
    terminal_id: int | None
    kod_role: str
    opravneni: frozenset[str]

    def ma(self, kod_opravneni: str) -> bool:
        return kod_opravneni in self.opravneni


@dataclass(frozen=True)
class Rozmer:
    """Rozměr v milimetrech."""

    delka_mm: Decimal
    hloubka_mm: Decimal


@dataclass(frozen=True)
class PotrebaMista:
    """Co díl potřebuje za místo. Vyrábí ostrov Díly, vyhodnocuje ostrov Struktura."""

    velikost: str                 # "V1" … "V6"
    rozmer: Rozmer | None = None  # jen u V6 (variabilní C7)


@dataclass(frozen=True)
class PolozkaCiselniku:
    """Položka číselníku předávaná mezi ostrovy (rozhraní), např. pro filtry ostrova Přehledy."""

    id: int
    kod: str
    nazev: str | None
    aktivni: bool
