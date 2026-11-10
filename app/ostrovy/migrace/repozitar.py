"""SQL migrace: jen schéma stg (Davka, Bunka – migrace 007). Do dbo se zapisuje přes rozhraní C, D, E."""
from __future__ import annotations

from typing import Any

from app.platforma.db import Spojeni


def zaloz_davku(spoj: Spojeni, soubor: str) -> int:
    """Nová dávka = jedno načtení. NactenoKdy dává default SYSUTCDATETIME(), NacetlUzivatelID zůstává
    NULL (z CLI nikdo přihlášený není)."""
    return spoj.vloz("INSERT INTO stg.Davka (Soubor) VALUES (?)", soubor)


def pridej_bunky(spoj: Spojeni, davka_id: int, bunky: list[tuple[str, int, int, str]]) -> None:
    """Buňky 1:1; souřadnice (list, řádek, sloupec) jsou primární klíč, takže žádná dvakrát nevznikne."""
    for list_, radek, sloupec, hodnota in bunky:
        spoj.proved("INSERT INTO stg.Bunka (DavkaID, List, Radek, Sloupec, Hodnota) VALUES (?, ?, ?, ?, ?)",
                    davka_id, list_, radek, sloupec, hodnota)


def davka(spoj: Spojeni, davka_id: int) -> dict[str, Any] | None:
    return spoj.jeden("SELECT DavkaID, Soubor, NactenoKdy FROM stg.Davka WHERE DavkaID = ?", davka_id)


def nejvyssi_davka_id(spoj: Spojeni) -> int | None:
    """Nejnovější dávka = největší DavkaID (aplikační účet má ve stg jen SELECT a INSERT, nic se
    nepřepisuje)."""
    return spoj.hodnota("SELECT MAX(DavkaID) FROM stg.Davka")


def bunky_listu(spoj: Spojeni, davka_id: int, list_: str) -> list[dict[str, Any]]:
    """Buňky jednoho listu setříděné po řádcích a sloupcích."""
    return spoj.dotaz("SELECT Radek, Sloupec, Hodnota FROM stg.Bunka"
                      " WHERE DavkaID = ? AND List = ? ORDER BY Radek, Sloupec", davka_id, list_)
