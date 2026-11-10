"""Testy vykreslení štítků do PDF: hlavička, jeden štítek na stránku, čárový kód na šířku štítku.

Obsah štítků (co se na nich tiskne) testuje `test_domena.TestStitky`; tady jde jen o papír.
"""
import re
import unittest

from reportlab.lib.units import mm

from app.ostrovy.struktura import stitky
from app.ostrovy.struktura.domena import Stitek


def pocet_stranek(pdf: bytes) -> int:
    """Počet stránek PDF bez dalších knihoven – reportlab píše /Type /Page pro každou stránku."""
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf))


class TestPdf(unittest.TestCase):
    def test_jeden_stitek_na_stranku(self):
        """Odpověď začíná %PDF a počet stránek se rovná počtu štítků."""
        for sada in ([Stitek("BOX", "BPLE037")],
                     [Stitek("BOX", "BSTAT037"), Stitek("POZICE_STAT", "BSTAT037-1", "1234567890123"),
                      Stitek("POZICE_STAT", "BSTAT037-2")]):
            pdf = stitky.kresli_pdf(sada)
            self.assertTrue(pdf.startswith(b"%PDF"))
            self.assertEqual(pocet_stranek(pdf), len(sada))

    def test_nejdelsi_kod_se_vejde_na_sirku(self):
        """Nejdelší kód pozice se vejde na 60 mm i s tichou zónou – zmenší se čáry, ne štítek (O-06)."""
        for kod in ("BSTAT037-12", "B1SV037-CH", "BSTAT037-1", "BPLE037"):
            cary, meritko = stitky.cara(kod, stitky.ROZMER_STRANKY[0] - 2 * stitky.OKRAJ)
            self.assertLessEqual(cary.width * meritko, stitky.ROZMER_STRANKY[0] - 2 * stitky.OKRAJ, kod)

    def test_stranka_60_x_30_mm(self):
        """Jeden rozměr stránky pro všechny typy štítků, bez parametru v API (do rozhodnutí O-06)."""
        self.assertEqual(stitky.ROZMER_STRANKY, (60 * mm, 30 * mm))


if __name__ == "__main__":
    unittest.main()
