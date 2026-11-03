"""Dekorátor @transakce (sekce 5.2 dokumentu Ostrovy, docs/adr/0004 a 0005).

    @transakce("VYDEJ", skladova=True)
    def vydej(spoj, vstup: VydejVstup, kdo: Kontext) -> VydejVysledek: ...

    sluzby.vydej(vstup=vstup, kdo=kontext())     # volající `spoj` nepředává

Co dělá:
- otevře spojení a předá ho jako první argument,
- u skladové operace (skladova=True) založí hlavičku v dbo.SkladovaTransakce s requestId;
  stejný requestId od stejného uživatele se stejným obsahem vrátí uložený výsledek a nic
  nezapíše (ochrana proti dvojímu odeslání z terminálu); jiný obsah nebo jiný uživatel = chyba,
- při úspěchu potvrdí, při chybě vrátí zpět,
- při deadlocku (1205) počká a zopakuje celou operaci nejvýše `max_opakovani`×, pak CONCURRENT_CHANGE,
- vypršení čekání na zámek (1222) a porušení UNIQUE převede na CONCURRENT_CHANGE (souběh,
  nic se nezapsalo); čeká-li se na hlavičku se stejným requestId, vrátí REQUEST_IN_PROGRESS.

Funkce v rozhrani.py tento dekorátor nikdy nemají – běží v transakci volajícího.
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import random
import time
import typing
import uuid
from typing import Any, Callable

from pydantic import BaseModel

from .chyby import AppError
from .db import Spojeni, otevri_spojeni
from .kontrakty import Varovani, Vystup
from .sql_chyby import je_deadlock, je_duplicita, je_limit_zamku

log = logging.getLogger("houfek.transakce")

ZPRAVA_ZAMEK = "Místo právě zpracovává někdo jiný. Zkuste to za chvíli znovu."
ZPRAVA_JINY_POZADAVEK = "Tento requestId už byl použit pro jiný požadavek."


class _Duplicita(Exception):
    """Souběžný požadavek se stejným requestId – zopakovat a přečíst uložený výsledek."""


def _pockej_pred_opakovanim(pokus: int) -> None:
    time.sleep(random.uniform(0.05, 0.15) * pokus)


def transakce(operace: str, *, skladova: bool = False, max_opakovani: int = 2) -> Callable:
    if not operace.replace("_", "").replace("-", "").isalnum() or operace.upper() != operace:
        raise ValueError(f"Název operace {operace!r} musí být VELKÁ_PÍSMENA ASCII.")

    def dekorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def obal(*args: Any, **kwargs: Any) -> Any:
            vstup = kwargs.get("vstup")
            kdo = kwargs.get("kdo")
            request_id = getattr(vstup, "request_id", None)
            if skladova and (kdo is None or request_id is None):
                raise TypeError(f"{fn.__qualname__}: skladová operace se volá jako "
                                "fn(vstup=…, kdo=…) a vstup musí mít request_id.")
            otisk = _otisk(vstup) if skladova else ""
            pokus = 0
            while True:
                spoj = otevri_spojeni()
                try:
                    if skladova:
                        ulozeny = _nacti_ulozeny(spoj, request_id, operace, kdo, otisk, fn)
                        if ulozeny is not None:
                            spoj._rollback()
                            return ulozeny
                        spoj.transakce_id = _zaloz_hlavicku(spoj, request_id, operace, kdo)
                    vysledek = fn(spoj, *args, **kwargs)
                    if skladova and isinstance(vysledek, Vystup):
                        vysledek = vysledek.model_copy(update={"transakce_id": spoj.transakce_id})
                        _uloz_vysledek(spoj, vysledek, otisk)
                    spoj._commit()
                    return vysledek
                except AppError:
                    spoj._rollback()
                    raise
                except _Duplicita:
                    spoj._rollback()
                    pokus += 1
                    if pokus > max_opakovani:
                        raise AppError("CONCURRENT_CHANGE") from None
                except Exception as chyba:
                    spoj._rollback()
                    if je_deadlock(chyba):
                        pokus += 1
                        log.warning("Deadlock v %s, pokus %s", operace, pokus)
                        if pokus > max_opakovani:
                            raise AppError("CONCURRENT_CHANGE") from chyba
                        _pockej_pred_opakovanim(pokus)
                        continue
                    if je_limit_zamku(chyba):
                        log.warning("Vypršelo čekání na zámek v %s", operace)
                        raise AppError("CONCURRENT_CHANGE", ZPRAVA_ZAMEK) from chyba
                    if je_duplicita(chyba):
                        log.warning("Porušení UNIQUE v %s: %s", operace, chyba)
                        raise AppError("CONCURRENT_CHANGE") from chyba
                    raise
                finally:
                    spoj._zavri()

        obal.__houfek_transakce__ = operace  # type: ignore[attr-defined]
        return obal

    return dekorator


# --- ochrana proti dvojímu odeslání (requestId) ------------------------------------

def _otisk(vstup: Any) -> str:
    """Otisk obsahu požadavku bez requestId – stejný requestId s jiným obsahem se odmítne."""
    if isinstance(vstup, BaseModel):
        data = vstup.model_dump(mode="json", exclude={"request_id"})
    else:
        data = repr(vstup)
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _zaloz_hlavicku(spoj: Spojeni, request_id: uuid.UUID, operace: str, kdo: Any) -> uuid.UUID:
    transakce_id = uuid.uuid4()
    try:
        spoj.proved(
            "INSERT INTO dbo.SkladovaTransakce (TransakceID, KlientRequestID, TypOperace, UzivatelID, TerminalID)"
            " VALUES (?, ?, ?, ?, ?)",
            transakce_id, request_id, operace, kdo.uzivatel_id, kdo.terminal_id)
    except Exception as chyba:
        if je_duplicita(chyba):
            raise _Duplicita() from chyba
        if je_limit_zamku(chyba):
            # Hlavičku se stejným requestId právě zapisuje jiná, ještě nepotvrzená transakce
            # (klient po timeoutu odeslal znovu). Její výsledek neznáme → klient opakuje se
            # stejným requestId, nesmí vygenerovat nový.
            raise AppError("REQUEST_IN_PROGRESS") from chyba
        raise
    return transakce_id


def _nacti_ulozeny(spoj: Spojeni, request_id: uuid.UUID, operace: str, kdo: Any, otisk: str,
                   fn: Callable) -> Any:
    radek = spoj.jeden(
        "SELECT TransakceID, TypOperace, UzivatelID, Vysledek FROM dbo.SkladovaTransakce"
        " WHERE KlientRequestID = ?", request_id)
    if radek is None:
        return None
    if radek["TypOperace"] != operace or int(radek["UzivatelID"]) != kdo.uzivatel_id:
        raise AppError("VALIDATION_ERROR", ZPRAVA_JINY_POZADAVEK)
    typ = typing.get_type_hints(fn).get("return")
    if radek["Vysledek"] is None or not (isinstance(typ, type) and issubclass(typ, Vystup)):
        raise AppError("CONCURRENT_CHANGE", "Operace se stejným requestId už proběhla.")
    ulozeno = json.loads(radek["Vysledek"])
    if ulozeno.get("otisk") != otisk:
        raise AppError("VALIDATION_ERROR", ZPRAVA_JINY_POZADAVEK)
    model = typ.model_validate(ulozeno["data"])
    return model.model_copy(update={
        "transakce_id": uuid.UUID(str(radek["TransakceID"])),
        "varovani": tuple(Varovani(v["kod"], v["zprava"]) for v in ulozeno["varovani"]),
    })


def _uloz_vysledek(spoj: Spojeni, vysledek: Vystup, otisk: str) -> None:
    obsah = json.dumps({
        "otisk": otisk,
        "data": vysledek.model_dump(mode="json"),
        "varovani": [{"kod": v.kod, "zprava": v.zprava} for v in vysledek.varovani],
    }, ensure_ascii=False)
    spoj.proved("UPDATE dbo.SkladovaTransakce SET Vysledek = ? WHERE TransakceID = ?",
                obsah, spoj.transakce_id)
