"""HTTP vrstva: načtení vstupu, jednotná obálka odpovědi (sekce 4.3) a převod chyb.

Endpoint ostrova dělá vždy jen tři kroky:
    vstup = nacti_vstup(Model)  →  vysledek = sluzby.x(vstup=vstup, kdo=kontext())  →  return odpoved(vysledek)
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, TypeVar

from flask import Flask, current_app, g, jsonify, request
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import HTTPException

from .chyby import AppError, RegistrChyb
from .kontrakty import Varovani, Vystup
from .sql_chyby import je_nedostupnost

log = logging.getLogger("houfek.http")
M = TypeVar("M", bound=BaseModel)


def registr_chyb() -> RegistrChyb:
    return current_app.extensions["houfek_chyby"]


# --- vstup ---------------------------------------------------------------------------

# Zprávy validace česky (skladník je čte na terminálu). Neznámý typ chyby = původní text Pydantic.
_ZPRAVY_VALIDACE = {
    "missing": "Povinný údaj.",
    "extra_forbidden": "Neznámé pole.",
    "greater_than": "Musí být větší než {gt}.",
    "greater_than_equal": "Musí být aspoň {ge}.",
    "less_than": "Musí být menší než {lt}.",
    "less_than_equal": "Smí být nejvýše {le}.",
    "string_too_short": "Musí mít aspoň {min_length} znaků.",
    "string_too_long": "Smí mít nejvýše {max_length} znaků.",
    "string_type": "Musí být text.",
    "string_pattern_mismatch": "Neplatný formát.",
    "int_type": "Musí být celé číslo.",
    "int_parsing": "Musí být celé číslo.",
    "int_from_float": "Musí být celé číslo.",
    "decimal_type": "Musí být číslo.",
    "decimal_parsing": "Musí být číslo.",
    "decimal_max_places": "Nejvýše {decimal_places} desetinná místa.",
    "decimal_max_digits": "Číslo je příliš dlouhé.",
    "float_parsing": "Musí být číslo.",
    "bool_type": "Musí být true nebo false.",
    "bool_parsing": "Musí být true nebo false.",
    "uuid_type": "Musí být UUID.",
    "uuid_parsing": "Musí být UUID.",
    "date_type": "Musí být datum RRRR-MM-DD.",
    "date_parsing": "Musí být datum RRRR-MM-DD.",
    "date_from_datetime_parsing": "Musí být datum RRRR-MM-DD.",
    "literal_error": "Povolené hodnoty: {expected}.",
    "enum": "Povolené hodnoty: {expected}.",
    "list_type": "Musí být seznam.",
    "too_long": "Nejvýše {max_length} položek.",
    "too_short": "Aspoň {min_length} položek.",
    "model_type": "Musí být objekt.",
    "dict_type": "Musí být objekt.",
}


def _zprava_validace(chyba: dict[str, Any]) -> str:
    sablona = _ZPRAVY_VALIDACE.get(chyba["type"])
    if sablona is None:
        # ValueError z validátoru modelu nese text už česky, jen bez předpony Pydantic
        return str(chyba["msg"]).removeprefix("Value error, ")
    try:
        return sablona.format(**chyba.get("ctx", {}))
    except (KeyError, IndexError):
        return str(chyba["msg"])


def _chyby_validace(chyba: ValidationError) -> list[dict[str, str]]:
    return [{"pole": ".".join(str(c) for c in e["loc"]) or "telo", "zprava": _zprava_validace(e), "typ": e["type"]}
            for e in chyba.errors(include_url=False)]


def nacti_vstup(model: type[M]) -> M:
    """Tělo požadavku (JSON) → model. Chyba = VALIDATION_ERROR se seznamem chyb podle polí."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AppError("VALIDATION_ERROR", "Tělo požadavku musí být JSON objekt.")
    try:
        return model.model_validate(data)
    except ValidationError as chyba:
        raise AppError("VALIDATION_ERROR", data={"chyby": _chyby_validace(chyba)}) from None


def nacti_parametry(model: type[M]) -> M:
    """Query parametry (GET filtry, camelCase) → model.

    Prázdná hodnota (?materialId=) = null = bez filtru – tak ji posílá HTML formulář s volbou „vše“.
    Opakovaný parametr (?typ=A&typ=B) = seznam.
    """
    data: dict[str, Any] = {}
    for klic in request.args:
        hodnoty = [h for h in request.args.getlist(klic) if h != ""]
        data[klic] = hodnoty if len(hodnoty) > 1 else (hodnoty[0] if hodnoty else None)
    try:
        return model.model_validate(data)
    except ValidationError as chyba:
        raise AppError("VALIDATION_ERROR", data={"chyby": _chyby_validace(chyba)}) from None


# --- výstup ---------------------------------------------------------------------------

def obalka(success: bool, code: str, message: str, data: Any = None,
           transakce_id: uuid.UUID | None = None, varovani: tuple[Varovani, ...] = ()) -> dict[str, Any]:
    return {
        "success": success,
        "code": code,
        "message": message,
        "data": data,
        "transakceId": str(transakce_id) if transakce_id else None,
        "varovani": [{"code": v.kod, "message": v.zprava} for v in varovani],
    }


def odpoved(vysledek: Vystup | None = None, zprava: str = "Hotovo.") -> Any:
    if vysledek is None:
        return jsonify(obalka(True, "OK", zprava)), 200
    data = vysledek.model_dump(mode="json", by_alias=True)
    return jsonify(obalka(True, "OK", zprava, data, vysledek.transakce_id, vysledek.varovani)), 200


def odpoved_chyby(kod: str, zprava: str | None = None, data: Any = None) -> Any:
    registr = registr_chyb()
    chyba = registr.najdi(kod)
    if chyba is None or kod == "OK":
        log.error("Neregistrovaný chybový kód %s (požadavek %s)", kod, g.get("pozadavek_id"))
        chyba = registr.najdi("INTERNAL_ERROR")
        kod, zprava, data = chyba.kod, None, None
    return jsonify(obalka(False, kod, zprava or chyba.vychozi_zprava, data)), chyba.http


# --- dokumentace pro Swagger ---------------------------------------------------------------

def dokumentuj(vstup: type[BaseModel] | None = None, vystup: type[BaseModel] | None = None,
               parametry: type[BaseModel] | None = None, popis: str = "") -> Callable:
    """Připojí k endpointu modely pro /api/openapi.json."""

    def dekorator(fn: Callable) -> Callable:
        fn.__houfek_doc__ = {"vstup": vstup, "vystup": vystup, "parametry": parametry,  # type: ignore[attr-defined]
                             "popis": popis or (fn.__doc__ or "").strip()}
        return fn

    return dekorator


# --- registrace do aplikace ------------------------------------------------------------------

BEZPECNOSTNI_HLAVICKY = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
    "Referrer-Policy": "same-origin",
}


def nastav_http(app: Flask) -> None:
    app.json.ensure_ascii = False  # type: ignore[attr-defined]
    app.json.sort_keys = False     # type: ignore[attr-defined]  # pořadí polí obálky podle sekce 4.3

    @app.before_request
    def _pozadavek_id() -> None:
        g.pozadavek_id = uuid.uuid4().hex[:12]

    @app.after_request
    def _hlavicky(odpoved_: Any) -> Any:
        odpoved_.headers["X-Pozadavek-Id"] = g.get("pozadavek_id", "")
        for nazev, hodnota in BEZPECNOSTNI_HLAVICKY.items():
            odpoved_.headers.setdefault(nazev, hodnota)
        if request.path.startswith("/api/"):
            odpoved_.headers["Cache-Control"] = "no-store"   # sdílené PDA ani proxy nesmí držet data skladu
        return odpoved_

    @app.errorhandler(AppError)
    def _app_error(chyba: AppError) -> Any:
        return odpoved_chyby(chyba.kod, chyba.zprava, chyba.data)

    @app.errorhandler(HTTPException)
    def _http_error(chyba: HTTPException) -> Any:
        if not request.path.startswith("/api/"):
            return chyba
        if chyba.code == 404:
            return odpoved_chyby("NOT_FOUND", "Taková adresa API neexistuje.")
        if chyba.code == 405:
            return odpoved_chyby("VALIDATION_ERROR", f"Metoda {request.method} tu není povolená.")
        if chyba.code == 413:
            return odpoved_chyby("PAYLOAD_TOO_LARGE")
        return odpoved_chyby("VALIDATION_ERROR", chyba.description)

    @app.errorhandler(Exception)
    def _neocekavana(chyba: Exception) -> Any:
        if je_nedostupnost(chyba):
            log.error("Databáze nedostupná (požadavek %s): %s", g.get("pozadavek_id"), chyba)
            return odpoved_chyby("DATABASE_UNAVAILABLE")
        log.exception("Neočekávaná chyba (požadavek %s)", g.get("pozadavek_id"))
        return odpoved_chyby("INTERNAL_ERROR")
