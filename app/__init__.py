"""HOUFEK Sklad – vstupní bod aplikace (Platforma; programátor ostrova sem nesahá).

    flask --app app run          vývojový server
    waitress-serve --call app:create_app      provoz na Windows
"""
from __future__ import annotations

from flask import Flask

from app.platforma import vytvor_aplikaci
from app.platforma.konfigurace import Konfigurace


def create_app(konfigurace: Konfigurace | None = None) -> Flask:
    from app.ostrovy import OSTROVY  # jediné místo, kde se ostrovy spojují

    return vytvor_aplikaci(OSTROVY, konfigurace)
