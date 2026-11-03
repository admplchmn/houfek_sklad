"""Čistá pravidla ostrova D – Díly a číselníky: bez DB a bez Flasku.

Hotová ve fázi 0, protože nezávisí na otevřených otázkách:
- potřeba místa dílu (velikost + rozměr V6, Q-01, Q-26),
- normalizace kódů číselníků (materiál, tloušťka, první operace).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.platforma.chyby import AppError, chyba_vstupu
from app.platforma.typy import PotrebaMista, Rozmer

VELIKOST_C7 = "V6"   # variabilní prostor C7: díl nese požadovaný rozměr (Q-01)
_MAX_TLOUSTKA = Decimal("999.99")   # TloustkaMaterialu.TloustkaMM DECIMAL(5,2)


def potreba_mista(velikost: str | None, delka_mm: Decimal | None, hloubka_mm: Decimal | None) -> PotrebaMista | None:
    """Co díl potřebuje za místo (vstup pro struktura.vejde_se).

    - bez velikosti → None (díl nejde do DYN, Q-26); rozměr se pak neposílá,
    - V1–V5 → jen velikost; rozměr se neposílá,
    - V6 → velikost a oba rozměry > 0 (Q-01).
    Chyby: VALIDATION_ERROR s polem, které je špatně.
    """
    ma_rozmer = delka_mm is not None or hloubka_mm is not None
    if velikost != VELIKOST_C7:
        if ma_rozmer:
            duvod = "Díl bez velikosti nemá rozměr." if velikost is None else f"Velikost {velikost} rozměr nemá."
            raise chyba_vstupu("Rozměr se zadává jen u velikosti V6.", {"potrebnaDelkaMm": duvod})
        return PotrebaMista(velikost) if velikost is not None else None
    chybi = {pole: "Povinný údaj u V6, větší než 0." for pole, hodnota
             in (("potrebnaDelkaMm", delka_mm), ("potrebnaHloubkaMm", hloubka_mm)) if hodnota is None or hodnota <= 0}
    if chybi:
        raise chyba_vstupu("Díl velikosti V6 potřebuje délku i hloubku v mm.", chybi)
    return PotrebaMista(velikost, Rozmer(delka_mm, hloubka_mm))


def normalizuj_kod_ciselniku(typ: str, kod: str) -> str:
    """Kanonický kód položky číselníku; stejný pro založení, změnu i import (kontrola duplicity).

    materialy: velká písmena, znaky 0–9 A–Z . - /   (S235, 1.4301, ALMG3)
    tloustky:  tloušťka v mm s 2 desetinnými místy, čárka i tečka (3 → 3.00, "2,5" → 2.50)
    operace:   velká písmena, znaky 0–9 A–Z _       (LASER, AUTOGEN)
    Chyby: VALIDATION_ERROR, NOT_FOUND (neznámý typ číselníku).
    """
    text = re.sub(r"\s+", "", kod or "").upper()
    if typ == "materialy":
        if not re.fullmatch(r"[0-9A-Z][0-9A-Z./-]*", text):
            raise _chybny_kod("Kód materiálu smí mít jen písmena bez diakritiky, číslice, tečku, pomlčku a lomítko.")
        return text
    if typ == "tloustky":
        try:
            hodnota = Decimal(text.replace(",", "."))
        except InvalidOperation:
            raise _chybny_kod("Tloušťka musí být číslo v mm, např. 3 nebo 2,5.") from None
        mimo_rozsah = not hodnota.is_finite() or hodnota <= 0 or hodnota > _MAX_TLOUSTKA
        if mimo_rozsah or hodnota != hodnota.quantize(Decimal("0.01")):
            raise _chybny_kod("Tloušťka musí být větší než 0, nejvýše 999,99 mm a mít nejvýše 2 desetinná místa.")
        return str(hodnota.quantize(Decimal("0.01")))
    if typ == "operace":
        if not re.fullmatch(r"[0-9A-Z_]+", text):
            raise _chybny_kod("Kód operace smí obsahovat jen písmena bez diakritiky, číslice a podtržítko.")
        return text
    raise AppError("NOT_FOUND", f"Číselník {typ!r} neexistuje. Povolené: materialy, tloustky, operace.")


def over_nazev_ciselniku(typ: str, nazev: str | None, *, zakladani: bool) -> None:
    """Název má jen první výrobní operace (NazevOperace NOT NULL); materiál a tloušťka ho nemají."""
    if typ == "operace":
        if zakladani and not nazev:
            raise _chybny_nazev("Operace musí mít název.")
        if not zakladani and nazev is None:
            raise _chybny_nazev("Název operace nejde vymazat.")
        return
    if nazev is not None:
        raise _chybny_nazev("Materiál a tloušťka název nemají, zadává se jen kód.")


def _chybny_kod(zprava: str) -> AppError:
    return chyba_vstupu(zprava, {"kod": zprava})


def _chybny_nazev(zprava: str) -> AppError:
    return chyba_vstupu(zprava, {"nazev": zprava})
