"""HTTP kontrakty ostrova B – Identita (sekce 7.2 dokumentu Ostrovy, analýza 9.7, docs/adr/0007).

Kontrakt je hotový (fáze 0); služby zatím vracejí vzorová data (KOSTRA). Po zmrazení na
bráně K1 se tu jen přidává (P10).

- PIN a kód karty jsou jen vstupy (`SecretStr`): v odpovědi, logu ani otisku požadavku se nikdy
  neobjeví; výstup říká jen `maPin` / `maKartu`.
- Chybné přihlášení vrací vždy stejné NOT_AUTHENTICATED – neprozradí, zda osobní číslo existuje,
  zda je uživatel aktivní, ani zda má PIN.
- Osobní číslo se po založení nemění (jiné číslo = jiný člověk), kód role taky ne.
"""
from __future__ import annotations

from pydantic import Field, SecretStr

from app.platforma.kontrakty import Cas, Duvod, FiltrAktivni, Strankovani, Vstup, Vystup, Zmena

# --- výstupy ------------------------------------------------------------------------------------


class PrihlasenyUzivatel(Vystup):
    uzivatel_id: int
    osobni_cislo: str
    cele_jmeno: str
    kod_role: str                    # OPER | SKL | MISTR | TECH | ADMIN
    nazev_role: str
    opravneni: list[str]             # aktuální oprávnění role (seřazená)
    terminal_id: int | None          # PDA, ze kterého se uživatel přihlásil
    kod_terminalu: str | None
    pracoviste_id: int | None        # pracoviště terminálu – výchozí filtr na PDA


class UzivatelRadek(Vystup):
    uzivatel_id: int
    osobni_cislo: str
    jmeno: str
    prijmeni: str
    cele_jmeno: str
    role_id: int
    kod_role: str
    ma_pin: bool
    ma_kartu: bool
    aktivni: bool
    zamceno_do: Cas | None = None      # D-33: dokud trvá zámek, správa podle toho pozná, koho odemknout


class RoleRadek(Vystup):
    role_id: int
    kod_role: str
    nazev: str
    popis: str | None
    opravneni: list[str]
    aktivni: bool


class TerminalRadek(Vystup):
    terminal_id: int
    kod_terminalu: str               # "PDA-01" – nastavený v PDA, posílá se při přihlášení
    nazev: str | None
    pracoviste_id: int | None        # kód pracoviště si spotřebitel připojí z ostrova C
    aktivni: bool


# --- přihlášení (veřejné) -------------------------------------------------------------------------


class PrihlaseniVstup(Vstup):
    osobni_cislo: str = Field(..., min_length=1, max_length=30)
    pin: SecretStr = Field(..., min_length=1, max_length=50)    # formát se tu neověřuje (obecná chyba)
    kod_terminalu: str | None = Field(None, max_length=50)       # PDA posílá svůj kód; PC nic


# --- správa (UZIVATEL_EDIT) -----------------------------------------------------------------------


class UzivateleFiltr(Strankovani):
    hledat: str | None = Field(None, max_length=100, description="Část osobního čísla, jména nebo příjmení")
    role_id: int | None = None
    aktivni: FiltrAktivni = True


class NovyUzivatelVstup(Vstup):
    osobni_cislo: str = Field(..., min_length=1, max_length=30)
    jmeno: str = Field(..., min_length=1, max_length=100)
    prijmeni: str = Field(..., min_length=1, max_length=100)
    role_id: int
    pin: SecretStr | None = None                                 # 4–8 číslic; bez PINu se nepřihlásí
    kod_karty: SecretStr | None = Field(None, max_length=100)    # volitelná karta / čip (Δ12)


class ZmenaUzivateleVstup(Zmena):
    """Jméno, role a karta. Osobní číslo se nemění; PIN mění jen reset-pinu. `kodKarty: null` kartu odebere."""

    NELZE_VYMAZAT = ("jmeno", "prijmeni", "role_id")

    jmeno: str | None = Field(None, min_length=1, max_length=100)
    prijmeni: str | None = Field(None, min_length=1, max_length=100)
    role_id: int | None = None
    kod_karty: SecretStr | None = Field(None, max_length=100)


class ResetPinuVstup(Vstup):
    novy_pin: SecretStr
    duvod: Duvod


class ZmenaRoleVstup(Zmena):
    """`opravneni` je celý nový seznam kódů (nahradí stávající); prázdný seznam = role bez oprávnění."""

    NELZE_VYMAZAT = ("nazev", "opravneni")

    nazev: str | None = Field(None, min_length=1, max_length=100)
    popis: str | None = Field(None, max_length=300)
    opravneni: list[str] | None = Field(None, max_length=100)


class NovyTerminalVstup(Vstup):
    kod_terminalu: str = Field(..., min_length=1, max_length=50)
    nazev: str | None = Field(None, max_length=100)
    pracoviste_id: int | None = None


class ZmenaTerminaluVstup(Zmena):
    """Název, pracoviště a aktivita (vyřazený terminál se nepřihlásí; jde znovu aktivovat)."""

    NELZE_VYMAZAT = ("aktivni",)

    nazev: str | None = Field(None, max_length=100)
    pracoviste_id: int | None = None
    aktivni: bool | None = None


CHYBY: list = []   # NOT_AUTHENTICATED, NO_PERMISSION, VALIDATION_ERROR … jsou kódy Platformy

OPRAVNENI = ["UZIVATEL_EDIT"]

MENU: list = []    # fáze 3: Přihlášení (1), Uživatelé a terminály (21)
