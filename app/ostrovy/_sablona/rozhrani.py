"""VEŘEJNÉ ROZHRANÍ ostrova – jediný soubor, který smí importovat jiný ostrov (P3).

Pravidla (sekce 5.1):
- první parametr je vždy `spoj` (transakce volajícího), funkce, která zapisuje, dostane i `kdo`;
- vrací se jen neměnná DTO (@dataclass(frozen=True)), jejich seznam nebo dict ID → DTO (P6);
- žádný Flask (request, session, g) (P4), žádný commit/rollback (P5);
- docstring uvádí jednotky a všechny chybové kódy, které funkce může vyvolat.
Ve fázi 0 vrací funkce vzorová data z ukazky.py (import uvnitř funkce); podpis se pak už nemění.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.platforma.db import Spojeni


@dataclass(frozen=True)
class PolozkaInfo:
    polozka_id: int
    kod: str
    pocet_ks: int


def nacti_polozky(spoj: Spojeni, polozka_ids: list[int]) -> dict[int, PolozkaInfo]:
    """Načte položky podle ID; neexistující ID ve výsledku chybí. Chyby: žádné."""
    from . import ukazky  # KOSTRA (fáze 0) – nahradit skutečnou implementací

    return {i: ukazky.POLOZKA_1 for i in polozka_ids}
