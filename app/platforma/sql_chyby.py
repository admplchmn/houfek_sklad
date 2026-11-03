"""Rozpoznání chyb SQL Serveru z výjimek pyodbc (a sqlite v testech).

pyodbc vrací `args = (SQLSTATE, zpráva)`; nativní číslo chyby SQL Serveru je v závorce
na konci záznamu: "… deadlock victim. Rerun the transaction. (1205) (SQLExecDirectW)".
Hledá se jen tato pozice, ne libovolné číslo ve zprávě – zpráva duplicity obsahuje i
hodnotu klíče, např. "The duplicate key value is (1205). (2627)".
"""
from __future__ import annotations

import re

_NATIVNI_KOD = re.compile(r"\((\d{3,5})\)(?=\s*(?:\(SQL\w+\)|;|$))")
_SQLSTATE = re.compile(r"[0-9A-Z]{5}")

DEADLOCK = 1205
LIMIT_ZAMKU = 1222
DUPLICITA = {2601, 2627}
SQLSTATE_NEDOSTUPNOST = {"08001", "08004", "08S01", "HYT00", "HYT01"}


def sqlstate(chyba: BaseException) -> str | None:
    """SQLSTATE z výjimky ve tvaru pyodbc (args = (SQLSTATE, zpráva)); jinak None.

    Jiné výjimky (např. ValueError("08001")) se za chybu databáze nepovažují.
    """
    args = getattr(chyba, "args", ())
    if len(args) < 2 or not isinstance(args[0], str) or not isinstance(args[1], str):
        return None
    return args[0] if _SQLSTATE.fullmatch(args[0]) else None


def nativni_kody(chyba: BaseException) -> set[int]:
    return {int(kod) for kod in _NATIVNI_KOD.findall(str(chyba))}


def je_deadlock(chyba: BaseException) -> bool:
    return DEADLOCK in nativni_kody(chyba) or sqlstate(chyba) == "40001"


def je_limit_zamku(chyba: BaseException) -> bool:
    return LIMIT_ZAMKU in nativni_kody(chyba)


def je_duplicita(chyba: BaseException) -> bool:
    if DUPLICITA & nativni_kody(chyba):
        return True
    return type(chyba).__name__ == "IntegrityError" and "UNIQUE constraint failed" in str(chyba)


def je_nedostupnost(chyba: BaseException) -> bool:
    """Spojení s databází se nepodařilo nebo dotaz překročil časový limit."""
    return sqlstate(chyba) in SQLSTATE_NEDOSTUPNOST
