"""Čistá pravidla ostrova B – Identita: bez DB a bez Flasku.

Hotová ve fázi 0: tvar osobního čísla, PINu a kódu terminálu, celé jméno (stejně jako v_Uzivatel),
kontrola seznamu oprávnění a pojistky správy (ADMIN si nesmí odebrat správu uživatelů, nikdo
nevyřadí sám sebe). Hash PINu je argon2 podle docs/adr/0007 – knihovna argon2-cffi je
v requirements.txt a načítá se až při použití.

Fáze 1 (TD-07): zámek po opakovaných chybných pokusech – úložiště pokusů rozhodne bezpečnost HOUFEK.
"""
from __future__ import annotations

import functools
import re
from collections.abc import Iterable

from app.platforma.chyby import chyba_vstupu

MIN_DELKA_PINU = 4
MAX_DELKA_PINU = 8
ROLE_SPRAVCE = "ADMIN"
OPRAVNENI_SPRAVCE = "UZIVATEL_EDIT"   # bez něj by nikdo nemohl spravovat uživatele


def normalizuj_osobni_cislo(text: str, *, pole: str = "osobniCislo") -> str:
    """Osobní číslo bez mezer, velkými písmeny: znaky 0–9 A–Z . _ - (nejvýše 30)."""
    cislo = re.sub(r"\s+", "", text or "").upper()
    if not re.fullmatch(r"[0-9A-Z._-]{1,30}", cislo):
        raise chyba_vstupu("Osobní číslo smí obsahovat jen číslice, písmena bez diakritiky, tečku, "
                           "podtržítko a pomlčku.", {pole: "Neplatné osobní číslo."})
    return cislo


def over_pin(pin: str, *, pole: str = "pin") -> str:
    """PIN je 4–8 číslic. Vrací PIN beze změny (mezery se neodstraňují – co se zadá, to se hashuje)."""
    if not re.fullmatch(rf"\d{{{MIN_DELKA_PINU},{MAX_DELKA_PINU}}}", pin or ""):
        zprava = f"PIN musí mít {MIN_DELKA_PINU} až {MAX_DELKA_PINU} číslic."
        raise chyba_vstupu(zprava, {pole: zprava})
    return pin


def normalizuj_kod_terminalu(text: str) -> str:
    """Kód terminálu velkými písmeny: znaky 0–9 A–Z _ - (např. PDA-01)."""
    kod = re.sub(r"\s+", "", text or "").upper()
    if not re.fullmatch(r"[0-9A-Z_-]{1,50}", kod):
        raise chyba_vstupu("Kód terminálu smí obsahovat jen písmena bez diakritiky, číslice, pomlčku a podtržítko.",
                           {"kodTerminalu": "Neplatný kód terminálu."})
    return kod


def cele_jmeno(jmeno: str, prijmeni: str) -> str:
    """Stejně jako sloupec CeleJmeno pohledu v_Uzivatel: CONCAT(Jmeno, ' ', Prijmeni)."""
    return f"{jmeno} {prijmeni}"


def over_opravneni(pozadovana: Iterable[str], zname: Iterable[str]) -> list[str]:
    """Seznam oprávnění role: jen známé kódy (tabulka Opravneni), bez duplicit, seřazený."""
    pozadovana = [kod.strip().upper() for kod in pozadovana]
    nezname = sorted(set(pozadovana) - set(zname))
    if nezname:
        raise chyba_vstupu(f"Neznámá oprávnění: {', '.join(nezname)}.", {"opravneni": "Neznámý kód oprávnění."})
    return sorted(set(pozadovana))


def over_zmenu_role(kod_role: str, opravneni: Iterable[str]) -> None:
    """Role ADMIN si musí ponechat UZIVATEL_EDIT, jinak by nikdo nemohl spravovat uživatele a role."""
    if kod_role == ROLE_SPRAVCE and OPRAVNENI_SPRAVCE not in set(opravneni):
        raise chyba_vstupu(f"Roli {ROLE_SPRAVCE} nejde odebrat oprávnění {OPRAVNENI_SPRAVCE}.",
                           {"opravneni": f"{OPRAVNENI_SPRAVCE} musí u role {ROLE_SPRAVCE} zůstat."})


def over_deaktivaci(uzivatel_id: int, kdo_uzivatel_id: int) -> None:
    """Nikdo nevyřadí sám sebe (přišel by o přístup uprostřed práce). Poslední aktivní ADMIN: fáze 1."""
    if uzivatel_id == kdo_uzivatel_id:
        raise chyba_vstupu("Sami sebe vyřadit nemůžete. Požádejte jiného správce.")


# --- hash PINu (argon2, docs/adr/0007) ------------------------------------------------------------


def zahashuj_pin(pin: str) -> str:
    """Hash PINu do Uzivatel.PinHash (argon2id s výchozími parametry knihovny)."""
    from argon2 import PasswordHasher

    return PasswordHasher().hash(over_pin(pin))


def pin_sedi(pin: str, pin_hash: str | None) -> bool:
    """Ověří PIN proti uloženému hashi. Uživatel bez hashe (nebo neexistující) se ověří proti
    fiktivnímu hashi, aby odpověď trvala stejně dlouho a délka nic neprozradila."""
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError

    try:
        return PasswordHasher().verify(pin_hash or _fiktivni_hash(), pin) and pin_hash is not None
    except (VerificationError, InvalidHashError):
        return False


@functools.cache
def _fiktivni_hash() -> str:
    from argon2 import PasswordHasher

    return PasswordHasher().hash("fiktivni-pin-pro-stejny-cas")
