"""Generování /api/openapi.json z endpointů a jejich Pydantic modelů (@dokumentuj).

Vygenerovaný soubor je v repozitáři jako kontrakt (kontrakty/openapi.json) a CI hlídá,
že se po zmrazení mění jen přidáním (P10).
"""
from __future__ import annotations

import re
from typing import Any

from flask import Flask
from pydantic import BaseModel

REF = "#/components/schemas/{model}"


def _schema(model: type[BaseModel], rezim: str, komponenty: dict[str, Any]) -> dict[str, str]:
    schema = model.model_json_schema(by_alias=True, ref_template=REF, mode=rezim)
    for nazev, definice in schema.pop("$defs", {}).items():
        _pridej_komponentu(komponenty, nazev, definice, model)
    nazev = model.__name__
    _pridej_komponentu(komponenty, nazev, schema, model)
    return {"$ref": REF.format(model=nazev)}


def _pridej_komponentu(komponenty: dict[str, Any], nazev: str, schema: dict[str, Any],
                       model: type[BaseModel]) -> None:
    """Dva různé modely se stejným jménem by Swagger tiše slil do jednoho – to je chyba."""
    puvodni = komponenty.get(nazev)
    if puvodni is not None and puvodni != schema:
        raise RuntimeError(f"OpenAPI: dva různé modely se jménem {nazev!r} (naposledy z {model.__module__}). "
                           "Jména modelů v kontraktech musí být v celé aplikaci jedinečná – přidejte předponu ostrova.")
    komponenty[nazev] = schema


_TYP_CESTY = {"int": {"type": "integer"}, "float": {"type": "number"}, "uuid": {"type": "string", "format": "uuid"}}


def _parametry_cesty(pravidlo: str) -> list[dict[str, Any]]:
    """<int:dil_id> → integer, <kod> nebo <string:kod> → string."""
    return [{"name": nazev, "in": "path", "required": True, "schema": _TYP_CESTY.get(prevodnik, {"type": "string"})}
            for prevodnik, nazev in re.findall(r"<(?:([a-z]+):)?([A-Za-z_]+)>", pravidlo)]


def _parametry_dotazu(model: type[BaseModel]) -> list[dict[str, Any]]:
    """Query parametry se skutečnými typy z modelu (integer, date, enum…), ne vše jako string."""
    schema = model.model_json_schema(by_alias=True, mode="validation")
    povinne = set(schema.get("required", []))
    vysledek = []
    for nazev, vlastnosti in schema.get("properties", {}).items():
        vlastnosti = {k: v for k, v in vlastnosti.items() if k != "title"}
        vysledek.append({"name": nazev, "in": "query", "required": nazev in povinne, "schema": vlastnosti})
    return vysledek


def _obalka(data: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["success", "code", "message", "data", "transakceId", "varovani"],
        "properties": {
            "success": {"type": "boolean"},
            "code": {"type": "string"},
            "message": {"type": "string"},
            "data": data or {"type": "null"},
            "transakceId": {"type": ["string", "null"], "format": "uuid"},
            "varovani": {"type": "array", "items": {"$ref": REF.format(model="Varovani")}},
        },
    }


def vytvor_openapi(app: Flask) -> dict[str, Any]:
    komponenty: dict[str, Any] = {
        "Varovani": {"type": "object", "required": ["code", "message"],
                     "properties": {"code": {"type": "string"}, "message": {"type": "string"}}},
    }
    cesty: dict[str, Any] = {}
    for pravidlo in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if not pravidlo.rule.startswith("/api/") or pravidlo.endpoint == "static":
            continue
        pohled = app.view_functions[pravidlo.endpoint]
        doc = getattr(pohled, "__houfek_doc__", {})
        cesta = re.sub(r"<(?:[a-z]+:)?([A-Za-z_]+)>", r"{\1}", pravidlo.rule)
        for metoda in sorted((pravidlo.methods or set()) - {"HEAD", "OPTIONS"}):
            operace: dict[str, Any] = {
                "operationId": pravidlo.endpoint.replace(".", "_"),
                "tags": [pravidlo.rule.split("/")[2]],
                "summary": (doc.get("popis") or "").split("\n")[0],
            }
            opravneni = getattr(pohled, "__houfek_opravneni__", ())
            if opravneni:
                operace["description"] = "Oprávnění: " + ", ".join(opravneni)
            parametry = _parametry_cesty(pravidlo.rule)
            if doc.get("parametry"):
                parametry += _parametry_dotazu(doc["parametry"])
            if parametry:
                operace["parameters"] = parametry
            if doc.get("vstup"):
                operace["requestBody"] = {"required": True, "content": {
                    "application/json": {"schema": _schema(doc["vstup"], "validation", komponenty)}}}
            data = _schema(doc["vystup"], "serialization", komponenty) if doc.get("vystup") else None
            operace["responses"] = {"200": {"description": "Obálka odpovědi (sekce 4.3)",
                                            "content": {"application/json": {"schema": _obalka(data)}}}}
            cesty.setdefault(cesta, {})[metoda.lower()] = operace
    return {
        "openapi": "3.1.0",
        "info": {"title": "HOUFEK Sklad API", "version": "0.1.0",
                 "description": "Konvence: dokument „HOUFEK – Ostrovy aplikace a konvence API“."},
        "paths": cesty,
        "components": {"schemas": dict(sorted(komponenty.items()))},
    }
