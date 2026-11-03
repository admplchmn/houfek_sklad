"""SQL ostrova. Zápis jen do vlastních tabulek (P1), čtení cizích dat jen z pohledů v_* (P2).

Parametry vždy přes `?`, nikdy skládáním textu (SQL injection).
"""
from __future__ import annotations

from app.platforma.db import Spojeni


def vloz_polozku(spoj: Spojeni, kod: str, pocet_ks: int) -> int:
    return spoj.vloz("INSERT INTO dbo.SablonaPolozka (Kod, PocetKs) VALUES (?, ?)", kod, pocet_ks)


def nacti_polozku(spoj: Spojeni, polozka_id: int) -> dict | None:
    return spoj.jeden("SELECT PolozkaID, Kod, PocetKs, Zalozeno FROM dbo.SablonaPolozka WHERE PolozkaID = ?",
                      polozka_id)
