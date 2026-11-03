"""Čistá pravidla ostrova: bez DB, bez Flasku. Testují se nejsnáz a nejrychleji."""
from app.platforma.chyby import AppError

LIMIT_KS = 10_000


def over_pocet(pocet_ks: int) -> None:
    if pocet_ks > LIMIT_KS:
        raise AppError("SABLONA_PRILIS_MNOHO", f"Nejvýše {LIMIT_KS} ks.", data={"limitKs": LIMIT_KS})
