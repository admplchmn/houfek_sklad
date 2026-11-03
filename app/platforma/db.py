"""Přístup k SQL Serveru přes pyodbc (DB-API 2.0, parametry `?`). Rozhodnutí: docs/adr/0002.

`Spojeni` je tenký obal nad jedním připojením = jednou transakcí. Ostrovy ho dostávají
jako první parametr služeb a funkcí rozhraní (P4, P5); commit/rollback dělá jen Platforma.

Každé spojení na SQL Serveru má nastaveno (pyodbc_tovarna):
- SET XACT_ABORT ON      – jakákoli chyba zneplatní celou transakci, nic se nepotvrdí napůl,
- SET LOCK_TIMEOUT       – čekání na zámek je omezené (chyba 1222 → CONCURRENT_CHANGE),
- časový limit dotazu    – zaseknutý dotaz nezablokuje terminál natrvalo.

Testy Platformy běží nad sqlite3 (dialekt "sqlite"); SQL ostrovů je T-SQL a testuje se
proti SQL Serveru (docs/adr/0009).
"""
from __future__ import annotations

import functools
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Callable, Iterator

from flask import Flask, current_app

from .konfigurace import Konfigurace

ROZSIRENI = "houfek_db"
ROZSIRENI_MIGRACE = "houfek_db_migrace"


class Spojeni:
    """Jedna otevřená transakce. Ostrovy používají jen metody níže, nikdy commit/rollback."""

    def __init__(self, pripojeni: Any, dialekt: str = "mssql") -> None:
        self._pripojeni = pripojeni
        self.dialekt = dialekt
        self.transakce_id: uuid.UUID | None = None   # nastaví @transakce u skladových operací
        self.jen_cteni = False                        # nastaví @cteni: zápis by se tiše zahodil (TD-09)

    # --- dotazy -------------------------------------------------------------
    def dotaz(self, sql: str, *parametry: Any) -> list[dict[str, Any]]:
        """SELECT; vrací řádky první sady výsledků jako slovníky (název sloupce → hodnota)."""
        kurzor = self._proved(sql, parametry)
        radky: list[dict[str, Any]] = []
        if kurzor.description is not None:
            nazvy = [sloupec[0] for sloupec in kurzor.description]
            radky = [dict(zip(nazvy, radek, strict=True)) for radek in kurzor.fetchall()]
        _dober_vysledky(kurzor)
        return radky

    def jeden(self, sql: str, *parametry: Any) -> dict[str, Any] | None:
        radky = self.dotaz(sql, *parametry)
        return radky[0] if radky else None

    def hodnota(self, sql: str, *parametry: Any) -> Any:
        radek = self.jeden(sql, *parametry)
        return next(iter(radek.values())) if radek else None

    def proved(self, sql: str, *parametry: Any) -> int:
        """INSERT/UPDATE/DELETE nebo dávka příkazů; vrací počet řádků dotčených prvním příkazem."""
        self._over_zapis()
        kurzor = self._proved(sql, parametry)
        pocet = kurzor.rowcount
        _dober_vysledky(kurzor)
        return pocet

    def vloz(self, sql: str, *parametry: Any) -> int:
        """INSERT do tabulky s IDENTITY; vrací nové ID."""
        self._over_zapis()
        if self.dialekt == "mssql":
            # SCOPE_IDENTITY musí být ve stejné dávce jako INSERT; NOCOUNT se nemění,
            # aby `proved()` dál vracelo počty řádků (rowcount).
            kurzor = self._proved(f"{sql.rstrip().rstrip(';')}; SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS NoveID;",
                                  parametry)
            while kurzor.description is None:
                if not kurzor.nextset():
                    raise RuntimeError("INSERT nevrátil nové ID (tabulka bez IDENTITY?)")
            nove_id = kurzor.fetchone()[0]
            _dober_vysledky(kurzor)
            if nove_id is None:
                raise RuntimeError("INSERT nevrátil nové ID (tabulka bez IDENTITY?)")
            return int(nove_id)
        kurzor = self._proved(sql, parametry)
        return int(kurzor.lastrowid)

    def kurzor(self) -> Any:
        """Úniková cesta pro hromadné operace (executemany). Používat výjimečně."""
        return self._pripojeni.cursor()

    # --- jen pro Platformu --------------------------------------------------
    def _over_zapis(self) -> None:
        if self.jen_cteni:
            raise RuntimeError("Zápis ve službě @cteni: čtecí spojení se na konci vrací zpět, zápis by se "
                               "ztratil. Operaci, která zapisuje, označte @transakce (sekce 5.2).")

    def _commit(self) -> None:
        self._pripojeni.commit()

    def _rollback(self) -> None:
        try:
            self._pripojeni.rollback()
        except Exception:  # spojení už může být zavřené po chybě serveru
            pass

    def _zavri(self) -> None:
        try:
            self._pripojeni.close()
        except Exception:
            pass

    def _proved(self, sql: str, parametry: tuple[Any, ...]) -> Any:
        kurzor = self._pripojeni.cursor()
        kurzor.execute(sql, self._prevod(parametry))
        return kurzor

    def _prevod(self, parametry: tuple[Any, ...]) -> tuple[Any, ...]:
        prevedene = []
        for p in parametry:
            if isinstance(p, uuid.UUID):
                prevedene.append(str(p))        # SQL Server převede text na UNIQUEIDENTIFIER sám
            elif isinstance(p, Decimal) and self.dialekt == "sqlite":
                prevedene.append(str(p))
            else:
                prevedene.append(p)
        return tuple(prevedene)


def _dober_vysledky(kurzor: Any) -> None:
    """Projde zbylé sady výsledků dávky.

    pyodbc vyvolá chybu pozdějšího příkazu dávky až při `nextset()`; bez toho by se chyba
    (např. v migraci) ztratila a transakce by se mohla potvrdit napůl.
    """
    dalsi = getattr(kurzor, "nextset", None)
    if dalsi is None:          # sqlite3 více sad výsledků nemá
        return
    while dalsi():
        pass


MAX_PARAMETRU_V_DAVCE = 1000   # SQL Server přijme nejvýše 2100 parametrů v jednom dotazu


def po_davkach(hodnoty: list[Any], velikost: int = MAX_PARAMETRU_V_DAVCE) -> Iterator[list[Any]]:
    """Rozdělí seznam (např. ID pro `IN (…)`) na dávky; hromadné funkce rozhraní ji musí použít."""
    for zacatek in range(0, len(hodnoty), velikost):
        yield hodnoty[zacatek:zacatek + velikost]


Tovarna = Callable[[], Spojeni]


def pyodbc_tovarna(konfigurace: Konfigurace, *, migrace: bool = False) -> Tovarna:
    retezec_fn = konfigurace.pripojovaci_retezec_migrace if migrace else konfigurace.pripojovaci_retezec

    def otevri() -> Spojeni:
        import pyodbc  # import až zde: testy Platformy pyodbc nepotřebují

        pripojeni = pyodbc.connect(retezec_fn(), autocommit=False, timeout=konfigurace.db_limit_prihlaseni_s)
        kurzor = pripojeni.cursor()
        if migrace:   # migrace běží v údržbovém okně: bez limitu dotazu, na zámky se čeká
            pripojeni.timeout = 0
            kurzor.execute("SET XACT_ABORT ON;")
        else:
            pripojeni.timeout = konfigurace.db_limit_dotazu_s
            kurzor.execute(f"SET XACT_ABORT ON; SET LOCK_TIMEOUT {int(konfigurace.db_limit_zamku_ms)};")
        kurzor.close()
        return Spojeni(pripojeni, "mssql")

    return otevri


def nastav_db(app: Flask, tovarna: Tovarna, tovarna_migrace: Tovarna | None = None) -> None:
    app.extensions[ROZSIRENI] = tovarna
    app.extensions[ROZSIRENI_MIGRACE] = tovarna_migrace or tovarna


def otevri_spojeni() -> Spojeni:
    return current_app.extensions[ROZSIRENI]()


@contextmanager
def spojeni_pro_skript(*, migrace: bool = False) -> Iterator[Spojeni]:
    """Pro CLI a skripty mimo HTTP: commit při úspěchu, rollback při chybě.

    migrace=True použije účet pro migrace (HOUFEK_DB_UZIVATEL_MIGRACE), pokud je nastaven.
    """
    spoj = current_app.extensions[ROZSIRENI_MIGRACE]() if migrace else otevri_spojeni()
    try:
        yield spoj
        spoj._commit()
    except BaseException:
        spoj._rollback()
        raise
    finally:
        spoj._zavri()


def cteni(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Služba jen pro čtení: otevře spojení, předá ho jako první argument, nic nepotvrdí."""

    @functools.wraps(fn)
    def obal(*args: Any, **kwargs: Any) -> Any:
        spoj = otevri_spojeni()
        spoj.jen_cteni = True
        try:
            return fn(spoj, *args, **kwargs)
        finally:
            spoj._rollback()
            spoj._zavri()

    obal.__houfek_cteni__ = True  # type: ignore[attr-defined]
    return obal
