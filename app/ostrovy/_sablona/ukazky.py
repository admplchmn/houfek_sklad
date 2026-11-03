"""Vzorová data pro kostru rozhraní (fáze 0) a pro testy spotřebitelů."""
from __future__ import annotations

from app.platforma.kostra import jen_ve_vyvoji

from . import rozhrani

jen_ve_vyvoji(__name__)  # v provozu vzorová data nikdy (app/platforma/kostra.py)

POLOZKA_1 = rozhrani.PolozkaInfo(polozka_id=1, kod="VZOR", pocet_ks=30)
