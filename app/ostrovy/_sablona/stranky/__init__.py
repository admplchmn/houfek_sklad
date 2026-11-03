"""UI obrazovky ostrova (fáze 3). Šablony v templates/<prefix>/, dědí z "base.html"."""
from flask import Blueprint, render_template

ui = Blueprint("sablona_ui", __name__, template_folder="templates")


@ui.get("/ukazka")
def ukazka():
    return render_template("sablona/ukazka.html")
