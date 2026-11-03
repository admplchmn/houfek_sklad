"""Vzorová data ostrova B pro kostru rozhraní, kostru služeb a testy spotřebitelů.

Vzorové PINy jsou otevřeně jen tady (vývoj, jen_ve_vyvoji); databáze má jen hash (docs/adr/0007).
Přiřazení oprávnění rolím je návrh ze sekce 9.9 analýzy – rozhodne brána G4.
"""
from app.platforma.kostra import jen_ve_vyvoji

from .kontrakty import RoleRadek, TerminalRadek, UzivatelRadek
from .rozhrani import UzivatelInfo

jen_ve_vyvoji(__name__)  # v provozu vzorová data nikdy (app/platforma/kostra.py)

# Kódy z tabulky Opravneni (výchozí data migrací 001 a 002).
ZNAMA_OPRAVNENI = ("DIL_CIST", "SKLAD_PRIJEM", "SKLAD_VYDEJ", "SKLAD_PRESUN", "INVENTURA", "KOREKCE", "BOX_EDIT",
                   "UZIVATEL_EDIT", "BLOKACE", "RUCNI_POTVRZENI", "UPOZORNENI_UZAVRIT", "KMEN_EDIT", "STAT_EDIT",
                   "AUDIT_CIST")

_SKLAD = ["DIL_CIST", "SKLAD_PRIJEM", "SKLAD_VYDEJ", "SKLAD_PRESUN"]
ROLE = [
    RoleRadek(role_id=1, kod_role="OPER", nazev="Operátor",
              popis="Čtení, standardní příjem a výdej podle přidělených oprávnění.",
              opravneni=["DIL_CIST", "SKLAD_PRIJEM", "SKLAD_VYDEJ"], aktivni=True),
    RoleRadek(role_id=2, kod_role="SKL", nazev="Skladník", popis="Skladové operace a inventura.",
              opravneni=sorted(_SKLAD + ["INVENTURA", "BLOKACE"]), aktivni=True),
    RoleRadek(role_id=3, kod_role="MISTR", nazev="Mistr", popis="Rozšířený dohled a provozní přehledy.",
              opravneni=sorted(_SKLAD + ["INVENTURA", "KOREKCE", "BLOKACE", "UPOZORNENI_UZAVRIT"]), aktivni=True),
    RoleRadek(role_id=4, kod_role="TECH", nazev="Technolog",
              popis="Kmenová data související s technologií, min/max dle kompetence.",
              opravneni=["DIL_CIST", "KMEN_EDIT", "STAT_EDIT"], aktivni=True),
    RoleRadek(role_id=5, kod_role="ADMIN", nazev="Administrátor",
              popis="Struktura skladu, uživatelé, číselníky, systémová administrace.",
              opravneni=sorted(ZNAMA_OPRAVNENI), aktivni=True),
]


def _uzivatel(uzivatel_id: int, cislo: str, jmeno: str, prijmeni: str, role_id: int, *, ma_pin: bool = True,
              aktivni: bool = True) -> UzivatelRadek:
    role = next(r for r in ROLE if r.role_id == role_id)
    return UzivatelRadek(uzivatel_id=uzivatel_id, osobni_cislo=cislo, jmeno=jmeno, prijmeni=prijmeni,
                         cele_jmeno=f"{jmeno} {prijmeni}", role_id=role_id, kod_role=role.kod_role, ma_pin=ma_pin,
                         ma_kartu=False, aktivni=aktivni)


UZIVATELE = {u.uzivatel_id: u for u in (
    _uzivatel(1, "1001", "Jan", "Novák", 2),
    _uzivatel(2, "1002", "Petra", "Svobodová", 5),
    _uzivatel(3, "1003", "Karel", "Dvořák", 1, aktivni=False),
    _uzivatel(4, "1004", "Eva", "Malá", 4, ma_pin=False),
)}

PINY = {"1001": "1234", "1002": "4321", "1003": "1111"}   # jen vzorová data; 1004 PIN nemá

TERMINALY = [
    TerminalRadek(terminal_id=1, kod_terminalu="PDA-01", nazev="Chainway – plechotváření", pracoviste_id=1,
                  aktivni=True),
    TerminalRadek(terminal_id=2, kod_terminalu="PDA-02", nazev="Chainway – horní svařovna", pracoviste_id=2,
                  aktivni=True),
    TerminalRadek(terminal_id=3, kod_terminalu="PDA-09", nazev="Vyřazené PDA", pracoviste_id=None, aktivni=False),
]

UZIVATEL_NOVAK = UzivatelInfo(uzivatel_id=1, osobni_cislo="1001", cele_jmeno="Jan Novák", kod_role="SKL", aktivni=True)
