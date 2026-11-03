"""Ostrovy aplikace. Seznam OSTROVY je JEDINÉ místo, kde se ostrovy spojují (sekce 6.1).

Nový ostrov: zkopírovat _sablona, vyplnit OSTROV, přidat sem import a položku.
"""
from app.ostrovy import dily, identita, inventura, migrace, prehledy, sklad, struktura

OSTROVY = [
    identita.OSTROV,
    struktura.OSTROV,
    dily.OSTROV,
    sklad.OSTROV,
    inventura.OSTROV,
    prehledy.OSTROV,
    migrace.OSTROV,
]
