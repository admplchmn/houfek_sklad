"""Vykreslení štítků do PDF s Code 128 (D-31) – papírování, ne pravidla.

Co je na štítku, rozhoduje `domena.sticky_boxu`; tenhle modul jen postaví stránku, napíše text a
nakreslí čáry. Rozměr štítku ani tiskárna nejsou rozhodnuté (otevřená otázka O-06), proto je tu
jeden rozměr provizorně, jedno PDF a jeden štítek na stránku – API rozměr nevolí.
"""
from __future__ import annotations

import io
from collections.abc import Sequence

from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .domena import Stitek

ROZMER_STRANKY = (60 * mm, 30 * mm)   # dočasně do rozhodnutí O-06 – rozměr štítku i tiskárna
OKRAJ = 2 * mm                        # na okraj se nikdy netiskne, patří k němu i tichá zóna čárového kódu
_VYSKA_CAR = 12 * mm
_SIRKA_PRUHU = 0.4 * mm               # přirozená šířka tenkého pruhu; celek se zmenší měřítkem
_MISTO_PRO_KOD = 4 * mm               # pod čáramy je na STAT štítku kód pozice
_PISMO = "Helvetica"
_PISMO_CISLO = "Helvetica-Bold"
_VELKOST_KODU = 9                     # kódy boxu a pozice v bodech
_VELKOST_CISLA = 16                   # číslo dílu; dlouhé číslo se zmenší, aby se vešlo na šířku


def kresli_pdf(stitky: Sequence[Stitek]) -> bytes:
    """Štítky jako jedno PDF, každý na vlastní stránku (řádí se podle zadaného pořadí)."""
    papir = io.BytesIO()
    platno = canvas.Canvas(papir, pagesize=ROZMER_STRANKY)
    for stitek in stitky:
        _nakresli(platno, stitek)
        platno.showPage()
    platno.save()
    return papir.getvalue()


def cara(kod: str, dostupna_sirka: float) -> tuple[Code128, float]:
    """Code 128 pro `kod` a měřítko, které ho vejme na dostupnou šířku.

    Hodnotu tiskneme vlastním textem (štítek ji má nad čárami nebo pod nimi), proto `humanReadable=0`
    – kód se na štítku opakuje právě jednou. Měřítko zmenší čáry, takže i nejdelší kód pozice
    (BSTAT037-12) zůstane na 60 mm štítku čitelný.
    """
    cary = Code128(kod, barWidth=_SIRKA_PRUHU, barHeight=_VYSKA_CAR, humanReadable=0)
    return cary, min(1.0, dostupna_sirka / cary.width)


def _nakresli(platno: canvas.Canvas, stitek: Stitek) -> None:
    sirka, vyska = ROZMER_STRANKY
    cary, meritko = cara(stitek.kod, sirka - 2 * OKRAJ)
    if stitek.velky_text is None:
        platno.setFont(_PISMO, _VELKOST_KODU)                     # box a DYN: kód jednou nad čárami
        platno.drawCentredString(sirka / 2, (vyska + _VYSKA_CAR) / 2 + OKRAJ, stitek.kod)
        spodek_car = (vyska - _VYSKA_CAR * meritko) / 2
    else:
        velkost = _velikost_cisla(stitek.velky_text, sirka - 2 * OKRAJ)
        platno.setFont(_PISMO_CISLO, velkost)                     # STAT: číslo dílu nahoře velkým písmem
        platno.drawCentredString(sirka / 2, vyska - OKRAJ - velkost, stitek.velky_text)
        platno.setFont(_PISMO, _VELKOST_KODU)                     # … a kód pozice dole
        platno.drawCentredString(sirka / 2, OKRAJ, stitek.kod)
        spodek_car = OKRAJ + _MISTO_PRO_KOD
    platno.saveState()
    platno.translate((sirka - cary.width * meritko) / 2, spodek_car)
    platno.scale(meritko, meritko)
    cary.drawOn(platno, 0, 0)
    platno.restoreState()


def _velikost_cisla(cislo: str, dostupna_sirka: float) -> float:
    """Velikost písma čísla dílu v bodech – zmenšené tak, aby se číslo vešlo na šířku štítku."""
    sirka = stringWidth(cislo, _PISMO_CISLO, _VELKOST_CISLA)
    return _VELKOST_CISLA if sirka <= dostupna_sirka else dostupna_sirka * _VELKOST_CISLA / sirka
