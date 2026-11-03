"""Vzorová data ostrova E pro kostru rozhraní, kostru služeb a testy spotřebitelů.

Navazují na vzory ostrovů C (místa) a D (díly):

    BPLE037-A   (DYN, V1)  díl 12 AAR10044          30 ks
    BPLE039-A   (DYN, V1)  prázdná – cíl přesunu dílu 12
    BPLE038-I   (DYN, V3)  díl 14 BX500-21           8 ks; BPLE038-G, -H, -CH prázdné – cíle příjmu dílu 14
    BSTAT037-1  (STAT, V3) STAT místo dílu 14 BX500-21, min 10 / opt 25 / max 40, 12 ks (OK)
    BSTAT037-2  (STAT, V3) STAT místo dílu 13 CE21RA 10 100194, min 5 / max 20, 0 ks → otevřené upozornění
"""
from __future__ import annotations

from datetime import datetime

from app.platforma.kostra import jen_ve_vyvoji

from .kontrakty import UpozorneniRadek
from .rozhrani import ObsahInfo, StatMistoInfo

jen_ve_vyvoji(__name__)  # v provozu vzorová data nikdy (app/platforma/kostra.py)

OBSAH = {o.vnitrni_pozice_id: o for o in (ObsahInfo(101, 12, 30), ObsahInfo(384, 14, 8), ObsahInfo(501, 14, 12))}
OBSAH_101 = OBSAH[101]

STAT_MISTA = [StatMistoInfo(stat_umisteni_id=1, dil_id=14, vnitrni_pozice_id=501, minimalni_ks=10,
                            optimalni_ks=25, maximalni_ks=40),
              StatMistoInfo(stat_umisteni_id=2, dil_id=13, vnitrni_pozice_id=502, minimalni_ks=5,
                            optimalni_ks=None, maximalni_ks=20)]
STAT_MISTO_BX500 = STAT_MISTA[0]

UPOZORNENI = [
    UpozorneniRadek(upozorneni_id=1, stat_umisteni_id=2, dil_id=13, identifikacni_cislo="CE21RA 10 100194",
                    kod="BSTAT037-2", typ_stavu="VYCERPANO", stav_upozorneni="OTEVRENE", aktualni_pocet_ks=0,
                    minimalni_pocet_ks=5, datum_vzniku=datetime(2026, 10, 28, 7, 15), datum_uzavreni=None,
                    poznamka=None),
    UpozorneniRadek(upozorneni_id=2, stat_umisteni_id=1, dil_id=14, identifikacni_cislo="BX500-21",
                    kod="BSTAT037-1", typ_stavu="POD_MINIMEM", stav_upozorneni="UZAVRENE", aktualni_pocet_ks=8,
                    minimalni_pocet_ks=10, datum_vzniku=datetime(2026, 10, 20, 13, 40),
                    datum_uzavreni=datetime(2026, 10, 29, 13, 40), poznamka=None),   # uzavřel příjem 5003
]

# PohybID posledního pohybu na pozici (inventura, Q-16) – stejné pohyby má vzorová historie ostrova G
POSLEDNI_POHYBY = {101: 5001, 384: 5004, 501: 5003, 502: 4990}

TYPY_POHYBU = [(1, "PRIJEM", "Příjem"), (2, "VYDEJ", "Výdej"), (3, "PRESUN-OUT", "Přesun – odchozí"),
               (4, "PRESUN-IN", "Přesun – příchozí"), (5, "INVENTURA", "Inventura"), (6, "KOREKCE", "Korekce"),
               (7, "POCAT-STAV", "Počáteční stav")]
