"""ŠABLONA OSTROVA – zkopírujte celou složku pod novým názvem (sekce 6.3).

1. Zkopírovat app/ostrovy/_sablona → app/ostrovy/<nazev>
2. Vyplnit OSTROV níže (název, prefix, tabulky, pohledy, chyby, oprávnění, menu)
3. Přidat import a položku do app/ostrovy/__init__.py (seznam OSTROVY)
4. pytest app/ostrovy/<nazev>

Šablona sama v OSTROVY není; běží jen v testech a ukazuje celou svislou cestu:
endpointy → sluzby (@transakce) → domena → repozitar → vlastní tabulka.
"""
from app.platforma.ostrov import Ostrov

from .endpointy import api
from .kontrakty import CHYBY, MENU, OPRAVNENI
from .stranky import ui

OSTROV = Ostrov(
    nazev="Šablona",
    prefix="sablona",                 # → /api/sablona/… a /ui/sablona/…
    api=api,
    ui=ui,
    tabulky=["SablonaPolozka"],       # tabulky, do kterých smí zapisovat jen tento ostrov (P1)
    pohledy=[],                       # pohledy v_*, které ostrov publikuje ostatním (P2)
    chyby=CHYBY,
    opravneni=OPRAVNENI,
    menu=MENU,
)
