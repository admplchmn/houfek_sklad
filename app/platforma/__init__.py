"""Ostrov A – Platforma. Ostrovy ji používají, ale nemění (sekce 7.1).

Veřejné moduly pro ostrovy:
    app.platforma.db          Spojeni, cteni
    app.platforma.transakce   transakce
    app.platforma.chyby       AppError, Chyba
    app.platforma.http        nacti_vstup, nacti_parametry, odpoved, dokumentuj
    app.platforma.auth        vyzaduje, verejne, kontext, prihlas, odhlas
    app.platforma.audit       zapis
    app.platforma.kontrakty   Vstup, SkladovyVstup, Vystup, Varovani, Cas, Mm, Strankovani, Strana
    app.platforma.typy        Kontext, Rozmer, PotrebaMista
    app.platforma.ostrov      Ostrov, PolozkaMenu
"""
from __future__ import annotations

import atexit
import logging
import os
import secrets
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from typing import Iterable

from flask import Flask, jsonify

from .auth import nastav_auth, verejne
from .chyby import AppError, RegistrChyb
from .db import Tovarna, nastav_db, pyodbc_tovarna
from .http import nastav_http
from .konfigurace import Konfigurace
from .kostra import DocasnaSqlite
from .openapi import vytvor_openapi
from .ostrov import Ostrov, ZapojeneOstrovy, over_ostrovy, over_ostrovy_proti_db, zaregistruj_ostrov
from .system import PLATFORMA
from .ui import kontext_sablon, presmeruj_na_ui, ui

_SWAGGER = """<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><title>HOUFEK Sklad API</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"></head>
<body><div id="swagger"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url: "/api/openapi.json", dom_id: "#swagger"});</script>
<noscript>Swagger potřebuje JavaScript a přístup na cdn.jsdelivr.net; kontrakt je i v /api/openapi.json.</noscript>
</body></html>"""


_FORMAT_LOGU = "%(asctime)s %(levelname)s %(name)s: %(message)s"
log = logging.getLogger("houfek")


def _nastav_logovani(konfigurace: Konfigurace) -> None:
    """Logy aplikace jdou do loggeru „houfek“, ne do kořenového (TD-12).

    Kořenový logger patří tomu, kdo aplikaci spouští (waitress, testy, nástroje). Handlery se
    přidají jen jednou, takže víc instancí aplikace v jednom procesu (testy) logy nezdvojí;
    úroveň nastavenou předem (testy: CRITICAL) nastavení nepřepíše.
    """
    houfek = logging.getLogger("houfek")
    if houfek.level == logging.NOTSET:
        houfek.setLevel(logging.INFO)
    if not any(getattr(h, "_houfek", False) for h in houfek.handlers):
        konzole = logging.StreamHandler()
        konzole.setFormatter(logging.Formatter(_FORMAT_LOGU))
        konzole._houfek = True  # type: ignore[attr-defined]
        houfek.addHandler(konzole)
        houfek.propagate = False
    if konfigurace.log_soubor:
        cesta = os.path.abspath(konfigurace.log_soubor)
        if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == cesta for h in houfek.handlers):
            soubor = RotatingFileHandler(cesta, maxBytes=10_000_000, backupCount=10, encoding="utf-8")
            soubor.setFormatter(logging.Formatter(_FORMAT_LOGU))
            houfek.addHandler(soubor)


def vytvor_aplikaci(ostrovy: Iterable[Ostrov], konfigurace: Konfigurace | None = None,
                    tovarna_db: Tovarna | None = None, tovarna_migrace: Tovarna | None = None) -> Flask:
    """Sestaví aplikaci z Platformy a ostrovů. Volá ji `app.create_app()` a testy.

    tovarna_db / tovarna_migrace: jen pro testy; jinak pyodbc podle konfigurace
    (aplikační účet a účet pro migrace, docs/adr/0003).
    """
    konfigurace = konfigurace or Konfigurace.z_prostredi()
    konfigurace.over()
    _nastav_logovani(konfigurace)

    app = Flask("app", static_folder=None)
    app.config.update(
        # Ve vývoji bez HOUFEK_TAJNY_KLIC náhodný klíč pro každý start: cookie nejde podvrhnout
        # pevným klíčem z kódu; po restartu se jen všichni znovu přihlásí.
        SECRET_KEY=konfigurace.tajny_klic or secrets.token_hex(32),
        HOUFEK_VYVOJ=konfigurace.vyvoj,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=konfigurace.max_velikost_pozadavku,
    )
    if konfigurace.vyvoj:
        log.warning("VÝVOJOVÝ REŽIM (HOUFEK_VYVOJ=1): přihlášení bez PINu a Swagger jsou zapnuté. "
                    "V provozu nikdy.")
    app.extensions["houfek_chyby"] = RegistrChyb()
    app.extensions["houfek_ostrovy"] = ZapojeneOstrovy()

    nastav_http(app)
    nastav_auth(app, konfigurace.vyvoj)
    bez_databaze = tovarna_db is None and konfigurace.vyvoj and not konfigurace.db_server
    if tovarna_db is not None:
        nastav_db(app, tovarna_db, tovarna_migrace)
    elif bez_databaze:
        # Fáze 0 bez SQL Serveru (TD-04): Swagger a UI nad kostrou, requestId funguje, nic se neukládá.
        kostra = DocasnaSqlite()
        atexit.register(kostra.smaz)
        app.extensions["houfek_kostra_db"] = kostra
        nastav_db(app, kostra.tovarna())
        log.warning("BEZ DATABÁZE (HOUFEK_DB_SERVER není nastaven): ostrovy běží nad vzorovými daty "
                    "a dočasnou sqlite v %s. Pro skutečná data nastavte HOUFEK_DB_*.", kostra.adresar)
    else:
        nastav_db(app, pyodbc_tovarna(konfigurace), pyodbc_tovarna(konfigurace, migrace=True))

    app.register_blueprint(ui, url_prefix="/ui")
    app.context_processor(kontext_sablon)
    app.add_url_rule("/", "koren", presmeruj_na_ui)

    @verejne
    def openapi_json():
        return jsonify(vytvor_openapi(app))

    @verejne
    def swagger():
        # Swagger načítá skripty z CDN do stejného původu jako aplikace – proto jen ve vývoji.
        if not app.config["HOUFEK_VYVOJ"]:
            raise AppError("NOT_FOUND", "Taková adresa API neexistuje.")
        return _SWAGGER

    app.add_url_rule("/api/openapi.json", "openapi_json", openapi_json)
    app.add_url_rule("/api/docs", "swagger", swagger)

    vsechny = [PLATFORMA, *ostrovy]
    over_ostrovy(vsechny)
    for ostrov in vsechny:
        zaregistruj_ostrov(app, ostrov)

    if konfigurace.kontrola_db_pri_startu and not bez_databaze:
        with app.app_context():
            spoj = app.extensions["houfek_db"]()
            try:
                nalezy = over_ostrovy_proti_db(vsechny, spoj)
            finally:
                spoj._rollback()
                spoj._zavri()
        if nalezy:
            raise RuntimeError("Ostrovy neodpovídají databázi:\n- " + "\n- ".join(nalezy))
    return app
