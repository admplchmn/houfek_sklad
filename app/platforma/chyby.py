"""Chybové kódy a výjimka AppError (sekce 4.4 dokumentu Ostrovy).

Jediná výjimka, která smí projít hranicí ostrova, je AppError s registrovaným kódem (P7).
Kódy používané více ostrovy patří Platformě; ostatní deklaruje vlastník v `kontrakty.CHYBY`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Chyba:
    kod: str
    http: int
    vychozi_zprava: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.kod):
            raise ValueError(f"Chybový kód {self.kod!r} musí být VELKÁ_PÍSMENA ASCII.")
        if not 100 <= self.http <= 599:
            raise ValueError(f"Chybový kód {self.kod}: neplatný HTTP status {self.http}.")


# Kódy Platformy. OK, VALIDATION_ERROR, NO_PERMISSION, NOT_FOUND, POSITION_BLOCKED
# a CONCURRENT_CHANGE jsou ze zadání (kap. 21.1.1 a 21.1.9), ostatní z analýzy.
ZAKLADNI_CHYBY: tuple[Chyba, ...] = (
    Chyba("OK", 200, "Hotovo."),
    Chyba("VALIDATION_ERROR", 400, "Zkontrolujte zadané hodnoty."),
    Chyba("NOT_AUTHENTICATED", 401, "Přihlaste se."),
    Chyba("NO_PERMISSION", 403, "Na tuto akci nemáte oprávnění."),
    Chyba("NOT_FOUND", 404, "Hledaný objekt neexistuje nebo není aktivní."),
    Chyba("ALREADY_EXISTS", 409, "Záznam se stejným kódem už existuje."),
    Chyba("POSITION_BLOCKED", 409, "Box nebo pozice je blokovaná."),
    Chyba("NOT_EMPTY", 409, "Nejdřív je potřeba místo vyprázdnit."),
    Chyba("CONCURRENT_CHANGE", 409, "Stav se mezitím změnil, nic se nezapsalo. Načtěte ho znovu."),
    # Stejný requestId právě zpracovává jiný požadavek; výsledek ještě není známý, klient
    # musí opakovat se STEJNÝM requestId (docs/adr/0004).
    Chyba("REQUEST_IN_PROGRESS", 409, "Stejný požadavek se právě zpracovává. Počkejte chvíli a odešlete ho znovu."),
    Chyba("PAYLOAD_TOO_LARGE", 413, "Požadavek je příliš velký."),
    Chyba("INTERNAL_ERROR", 500, "Nastala neočekávaná chyba. Zkuste to znovu nebo kontaktujte správce."),
    Chyba("DATABASE_UNAVAILABLE", 503, "Databáze teď neodpovídá. Zkuste to za chvíli znovu."),
)


class AppError(Exception):
    """Očekávaná chyba aplikace. `kod` musí být registrovaný, jinak se vrátí INTERNAL_ERROR."""

    def __init__(self, kod: str, zprava: str | None = None, data: dict[str, Any] | None = None):
        super().__init__(zprava or kod)
        self.kod = kod
        self.zprava = zprava
        self.data = data


def chyba_vstupu(zprava: str, pole: dict[str, str] | None = None) -> AppError:
    """VALIDATION_ERROR z pravidla ostrova ve stejném tvaru jako chyby validace Pydantic:
    `data.chyby = [{pole, zprava, typ: "pravidlo"}]`, aby klient zvýraznil pole stejně.

        raise chyba_vstupu("Díl V6 potřebuje rozměr.", {"potrebnaDelkaMm": "Povinný údaj u V6."})
    """
    chyby = [{"pole": nazev, "zprava": text, "typ": "pravidlo"} for nazev, text in (pole or {}).items()]
    return AppError("VALIDATION_ERROR", zprava, data={"chyby": chyby} if chyby else None)


class RegistrChyb:
    """Všechny chybové kódy aplikace. Duplicita = aplikace nenastartuje (sekce 6.4)."""

    def __init__(self) -> None:
        self._chyby: dict[str, tuple[Chyba, str]] = {}

    def pridej(self, chyby: Iterable[Chyba], vlastnik: str) -> None:
        for chyba in chyby:
            if chyba.kod in self._chyby:
                puvodni = self._chyby[chyba.kod][1]
                raise ValueError(f"Chybový kód {chyba.kod} deklaruje {vlastnik} i {puvodni}.")
            self._chyby[chyba.kod] = (chyba, vlastnik)

    def najdi(self, kod: str) -> Chyba | None:
        nalez = self._chyby.get(kod)
        return nalez[0] if nalez else None

    def vlastnik(self, kod: str) -> str | None:
        nalez = self._chyby.get(kod)
        return nalez[1] if nalez else None

    def vsechny(self) -> list[tuple[Chyba, str]]:
        return sorted(self._chyby.values(), key=lambda p: (p[0].http, p[0].kod))
