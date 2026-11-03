"""Ostrov H – Migrace XLSM (sekce 7.8 dokumentu Ostrovy). Příkazová řádka, žádné HTTP.

Do ostrých tabulek zapisuje jen přes rozhraní vlastníků (C, D, E); vlastní tabulky má ve schématu stg.
"""
from app.platforma.ostrov import Ostrov

from .prikazy import migrace_cli

OSTROV = Ostrov(
    nazev="Migrace",
    prefix="migrace",
    prikazy=[migrace_cli],
)
