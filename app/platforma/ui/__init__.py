"""UI kostra Platformy (sekce 6.5): /ui/ menu, /ui/vyvoj vývojářský panel, statické soubory.

Obrazovky ostrovů dědí z "base.html" a volají API přes `api.js`.
"""
from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, url_for

from ..auth import kontext
from ..chyby import AppError

ui = Blueprint("platforma_ui", __name__, template_folder="templates", static_folder="static",
               static_url_path="/static")


def _prihlaseny():
    try:
        return kontext()
    except AppError:
        return None


def kontext_sablon() -> dict:
    """Proměnné dostupné ve všech šablonách: prihlaseny, menu (podle oprávnění), vyvoj."""
    kdo = _prihlaseny()
    polozky = current_app.extensions["houfek_ostrovy"].menu
    menu = [p for p in polozky if kdo and (p.opravneni is None or kdo.ma(p.opravneni))]
    return {"prihlaseny": kdo, "menu": menu, "vyvoj": bool(current_app.config.get("HOUFEK_VYVOJ"))}


@ui.get("/")
def index():
    return render_template("index.html")


@ui.get("/vyvoj")
def vyvoj():
    return render_template("vyvoj.html")


def presmeruj_na_ui():
    return redirect(url_for("platforma_ui.index"))
