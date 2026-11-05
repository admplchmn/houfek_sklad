"""Zápis do AuditZmen (kap. 25 zadání). Tabulku vlastní Platforma; ostrovy zapisují jen přes `zapis`.

Audit se píše ve stejné transakci jako změna, takže se buď uloží obojí, nebo nic.
Množství se nikdy neaudituje – to je historie SkladovyPohyb.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .db import Spojeni
from .typy import Kontext


def _text(hodnota: Any) -> str | None:
    if hodnota is None:
        return None
    if isinstance(hodnota, (str, int)):
        return str(hodnota)
    if isinstance(hodnota, (Decimal, float)):
        return format(hodnota, "f") if isinstance(hodnota, Decimal) else repr(hodnota)
    if isinstance(hodnota, (datetime, date)):
        return hodnota.isoformat()
    return json.dumps(hodnota, ensure_ascii=False, default=str)


def zapis(spoj: Spojeni, kdo: Kontext, typ_objektu: str, objekt_id: int, pole: str,
          stara: Any, nova: Any, poznamka: str | None = None) -> int:
    """Zapíše jednu změnu jedné vlastnosti. Vrací AuditID.

    typ_objektu: ASCII VELKÁ_PÍSMENA, např. "DIL", "BOX", "STAT_UMISTENI".
    Bool: hodnota se předává jako bool (ne jako "1"/"0") a `_text` z ní sepíše "True"/"False".
    """
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", typ_objektu):
        raise ValueError(f"typ_objektu {typ_objektu!r} musí být VELKÁ_PÍSMENA ASCII")
    return spoj.vloz(
        "INSERT INTO dbo.AuditZmen (UzivatelID, TypObjektu, ObjektID, Pole, StaraHodnota, NovaHodnota, Poznamka)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        kdo.uzivatel_id, typ_objektu, objekt_id, pole, _text(stara), _text(nova), poznamka)
