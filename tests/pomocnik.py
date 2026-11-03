"""Pomůcky pro testy: aplikace nad dočasnou sqlite databází a přihlášení klienta.

sqlite slouží jen pro testy Platformy a šablony. SQL ostrovů je T-SQL a jejich integrační
testy běží proti SQL Serveru (proměnná HOUFEK_TEST_DB_* – doplní Platforma ve fázi 0).
"""
from __future__ import annotations

import logging
import os
import unittest
import uuid
from typing import Any, Iterable

from flask import Flask
from flask.testing import FlaskClient

from app.platforma import vytvor_aplikaci
from app.platforma.auth import KLIC
from app.platforma.konfigurace import Konfigurace
from app.platforma.kostra import SQLITE_PLATFORMY, DocasnaSqlite
from app.platforma.ostrov import Ostrov

PLATFORMA_SQLITE = SQLITE_PLATFORMY

# Logy testované aplikace (varování vývojového režimu, simulované deadlocky) jen zahlcují výstup.
# HOUFEK_TEST_LOG=1 je zapne; assertLogs funguje i bez toho.
if os.environ.get("HOUFEK_TEST_LOG") != "1":
    logging.getLogger("houfek").setLevel(logging.CRITICAL)


class TestovaciDatabaze(DocasnaSqlite):
    """Dočasná sqlite databáze pro testy (stejná jako kostra bez SQL Serveru, app/platforma/kostra.py)."""


def testovaci_aplikace(ostrovy: Iterable[Ostrov], db: TestovaciDatabaze) -> Flask:
    app = vytvor_aplikaci(list(ostrovy), Konfigurace(vyvoj=True), tovarna_db=db.tovarna())
    app.testing = True
    return app


def prihlas(klient: FlaskClient, *opravneni: str, uzivatel_id: int = 1, terminal_id: int | None = None,
            role: str = "ADMIN") -> None:
    with klient.session_transaction() as session:
        session[KLIC] = {"uzivatelId": uzivatel_id, "terminalId": terminal_id, "kodRole": role,
                         "opravneni": sorted(opravneni)}


def rid() -> str:
    """Nový requestId pro skladový příkaz v testu."""
    return str(uuid.uuid4())


class ZakladTestuOstrova(unittest.TestCase):
    """Základ testů endpointů ostrova: dočasná DB, aplikace jen s danými ostrovy, klient.

        class TestDily(ZakladTestuOstrova):
            ostrovy = (dily.OSTROV,)
    """

    ostrovy: tuple[Ostrov, ...] = ()

    def setUp(self) -> None:
        self.db = TestovaciDatabaze()
        self.app = testovaci_aplikace(self.ostrovy, self.db)
        self.klient = self.app.test_client()

    def tearDown(self) -> None:
        self.db.smaz()

    def prihlas(self, *opravneni: str, **kwargs: Any) -> None:
        prihlas(self.klient, *opravneni, **kwargs)

    def over_ok(self, odpoved: Any) -> Any:
        """HTTP 200 + code OK; vrací data z obálky."""
        self.assertEqual((odpoved.status_code, odpoved.json["code"]), (200, "OK"), odpoved.json)
        return odpoved.json["data"]

    def over_chybu(self, odpoved: Any, http: int, kod: str) -> dict:
        """Chybová obálka s daným HTTP statusem a kódem; vrací celou obálku."""
        self.assertEqual((odpoved.status_code, odpoved.json["code"]), (http, kod), odpoved.json)
        self.assertFalse(odpoved.json["success"])
        return odpoved.json

    def chybna_pole(self, odpoved: Any) -> set[str]:
        """Pole označená ve VALIDATION_ERROR (data.chyby[].pole)."""
        obalka = self.over_chybu(odpoved, 400, "VALIDATION_ERROR")
        return {chyba["pole"] for chyba in (obalka["data"] or {}).get("chyby", [])}
