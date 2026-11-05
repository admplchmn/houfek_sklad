"""SQL ostrova B – Identita. Zápis jen do vlastních tabulek (P1), čtení cizích dat jen z pohledů v_* (P2).

Tabulky ostrova: `Uzivatel`, `Role`, `Opravneni`, `RoleOpravneni`, `Terminal`. Pracoviště je
cizí tabulka (ostrov C) a ostrov C v této fázi ještě nedává pohled na číselník pracovišť –
neexistující pracoviště proto poznáme až porušením cizího klíče a `cizi_id` z něj udělá
VALIDATION_ERROR na dané pole (P7).

`PinHash` a `KodKarty` se nečtou nikdy spolu s výčtem uživatelů – najevo jdou jen `maPin`
a `maKartu`. Jediné čtení, které hash vidí, je `uzivatel_podle_cisla` při přihlášení.

Parametry vždy přes `?`, názvy tabulek i sloupců jsou pevné – nikdy se neskládají text do dotazu.
"""
from __future__ import annotations

from contextlib import contextmanager

from app.platforma.chyby import chyba_vstupu
from app.platforma.db import Spojeni
from app.platforma.sql_chyby import nativni_kody

FK_CIZI_OBJEKT = 547     # porušení cizího klíče (např. neexistující pracoviště)

_UZIVATEL = ("SELECT u.UzivatelID, u.OsobniCislo, u.Jmeno, u.Prijmeni, u.RoleID, r.KodRole,"
             " CAST(CASE WHEN u.PinHash IS NULL THEN 0 ELSE 1 END AS BIT) AS MaPin,"
             " CAST(CASE WHEN u.KodKarty IS NULL THEN 0 ELSE 1 END AS BIT) AS MaKartu, u.Aktivni"
             " FROM dbo.Uzivatel AS u JOIN dbo.Role AS r ON r.RoleID = u.RoleID")

_ROLE = ("SELECT r.RoleID, r.KodRole, r.NazevRole, r.Popis, r.Aktivni, o.KodOpravneni"
         " FROM dbo.Role AS r"
         " LEFT JOIN dbo.RoleOpravneni AS ro ON ro.RoleID = r.RoleID"
         " LEFT JOIN dbo.Opravneni AS o ON o.OpravneniID = ro.OpravneniID")

_TERMINAL = ("SELECT TerminalID, KodTerminalu, NazevTerminalu, PracovisteID, Aktivni"
             " FROM dbo.Terminal")

LIKE_ZAKAZY = {"%": "[%]", "_": "[_]", "[": "[[]"}


@contextmanager
def cizi_id(pole: str, popisek: str):
    """Příkaz odkazující na cizí tabulku: porušení cizího klíče je VALIDATION_ERROR na dané pole.

    Server zahodí celou transakci už sám (XACT_ABORT), proto se za tuto chybu nic nedokresluje.
    """
    try:
        yield
    except Exception as chyba:
        if FK_CIZI_OBJEKT not in nativni_kody(chyba):
            raise
        raise chyba_vstupu(f"{popisek} neexistuje.", {pole: "Neexistující záznam."}) from chyba


def _vzor_like(text: str) -> str:
    """Řetězec uživatele do LIKE: wildcardy se escapují, aby hledané „%“ hledalo procento."""
    return "%" + "".join(LIKE_ZAKAZY.get(znak, znak) for znak in text) + "%"


# --- přihlášení a session -------------------------------------------------------------------------


def uzivatel_podle_cisla(spoj: Spojeni, osobni_cislo: str) -> dict | None:
    """Uživatel pro přihlášení – jediné čtení, které vidí `PinHash` (a jen ho vrací dál doméně)."""
    return spoj.jeden(
        "SELECT u.UzivatelID, u.OsobniCislo, u.Jmeno, u.Prijmeni, u.RoleID, u.PinHash, u.Aktivni,"
        " r.KodRole, r.NazevRole"
        " FROM dbo.Uzivatel AS u JOIN dbo.Role AS r ON r.RoleID = u.RoleID"
        " WHERE u.OsobniCislo = ?", osobni_cislo)


def prihlaseny_uzivatel(spoj: Spojeni, uzivatel_id: int, terminal_id: int | None) -> list[dict]:
    """Jeden dotaz podle PK: údaje, role i AKTUÁLNÍ oprávnění role a terminál z přihlášení.

    Vrací jeden řádek na oprávnění (bez oprávnění jeden řádek s NULL) – seskupí služba.
    """
    return spoj.dotaz(
        "SELECT u.UzivatelID, u.OsobniCislo, u.Jmeno, u.Prijmeni, u.Aktivni,"
        " r.RoleID, r.KodRole, r.NazevRole, o.KodOpravneni,"
        " t.TerminalID, t.KodTerminalu, t.PracovisteID"
        " FROM dbo.Uzivatel AS u"
        " JOIN dbo.Role AS r ON r.RoleID = u.RoleID"
        " LEFT JOIN dbo.RoleOpravneni AS ro ON ro.RoleID = r.RoleID"
        " LEFT JOIN dbo.Opravneni AS o ON o.OpravneniID = ro.OpravneniID"
        " LEFT JOIN dbo.Terminal AS t ON t.TerminalID = ?"
        " WHERE u.UzivatelID = ?", terminal_id, uzivatel_id)


def kontext_uzivatele(spoj: Spojeni, uzivatel_id: int) -> list[dict]:
    """Hák Platformy: aktivita, kód role a aktuální oprávnění, jeden dotaz podle PK."""
    return spoj.dotaz(
        "SELECT u.Aktivni, r.KodRole, o.KodOpravneni"
        " FROM dbo.Uzivatel AS u"
        " JOIN dbo.Role AS r ON r.RoleID = u.RoleID"
        " LEFT JOIN dbo.RoleOpravneni AS ro ON ro.RoleID = r.RoleID"
        " LEFT JOIN dbo.Opravneni AS o ON o.OpravneniID = ro.OpravneniID"
        " WHERE u.UzivatelID = ?", uzivatel_id)


def opravneni_role(spoj: Spojeni, role_id: int) -> list[str]:
    return [radek["KodOpravneni"] for radek in spoj.dotaz(
        "SELECT o.KodOpravneni FROM dbo.RoleOpravneni AS ro"
        " JOIN dbo.Opravneni AS o ON o.OpravneniID = ro.OpravneniID"
        " WHERE ro.RoleID = ? ORDER BY o.KodOpravneni", role_id)]


# --- uživatelé ------------------------------------------------------------------------------------


def uzivatel_podle_id(spoj: Spojeni, uzivatel_id: int) -> dict | None:
    return spoj.jeden(_UZIVATEL + " WHERE u.UzivatelID = ?", uzivatel_id)


def seznam_uzivatelu(spoj: Spojeni, *, hledat: str | None, role_id: int | None, aktivni: bool | None,
                     strana: int, velikost: int) -> tuple[list[dict], int]:
    """Stránovaný výčet bez PINu a karty; vrací (řádky, celkem bez ohledu na stránkování)."""
    podminky = ["1 = 1"]
    parametry: list[object] = []
    if hledat:
        vzor = _vzor_like(hledat)
        podminky.append("(u.OsobniCislo LIKE ? OR CONCAT(u.Jmeno, N' ', u.Prijmeni) LIKE ?)")
        parametry += [vzor, vzor]
    if role_id is not None:
        podminky.append("u.RoleID = ?")
        parametry.append(role_id)
    if aktivni is not None:
        podminky.append("u.Aktivni = ?")
        parametry.append(1 if aktivni else 0)
    kde = " AND ".join(podminky)
    celkem = spoj.hodnota(f"SELECT COUNT(*) FROM dbo.Uzivatel AS u WHERE {kde}", *parametry)
    radky = spoj.dotaz(f"{_UZIVATEL} WHERE {kde}"
                       " ORDER BY u.Prijmeni, u.Jmeno, u.UzivatelID"
                       " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                       *parametry, (strana - 1) * velikost, velikost)
    return radky, int(celkem)


def existuje_osobni_cislo(spoj: Spojeni, osobni_cislo: str) -> bool:
    """Zjišťuje se před zápisem: duplicitu odhalí i UNIQUE, ale @transakce z ní má CONCURRENT_CHANGE."""
    return spoj.hodnota("SELECT 1 FROM dbo.Uzivatel WHERE OsobniCislo = ?", osobni_cislo) is not None


def existuje_karta(spoj: Spojeni, kod_karty: str, *, krome_id: int | None = None) -> bool:
    sql = "SELECT 1 FROM dbo.Uzivatel WHERE KodKarty = ?"
    parametry: list[object] = [kod_karty]
    if krome_id is not None:
        sql += " AND UzivatelID <> ?"
        parametry.append(krome_id)
    return spoj.hodnota(sql, *parametry) is not None


def pocet_activnich_spravcu(spoj: Spojeni, kod_role: str) -> int:
    """Pro pojistku domény: poslední aktivní správce nesmí zůstat sám (správa uživatelů)."""
    return int(spoj.hodnota("SELECT COUNT(*) FROM dbo.Uzivatel AS u JOIN dbo.Role AS r ON r.RoleID = u.RoleID"
                            " WHERE r.KodRole = ? AND u.Aktivni = 1", kod_role))


def vloz_uzivatele(spoj: Spojeni, *, osobni_cislo: str, jmeno: str, prijmeni: str, role_id: int,
                   pin_hash: str | None, kod_karty: str | None) -> int:
    return spoj.vloz("INSERT INTO dbo.Uzivatel (OsobniCislo, Jmeno, Prijmeni, RoleID, PinHash, KodKarty, Aktivni)"
                     " VALUES (?, ?, ?, ?, ?, ?, 1)", osobni_cislo, jmeno, prijmeni, role_id, pin_hash, kod_karty)


def zmen_kmenova_data(spoj: Spojeni, uzivatel_id: int, *, jmeno: str, prijmeni: str, role_id: int) -> None:
    """Jméno, příjmení a role; osobní číslo se po založení nemění a PIN má vlastní operaci."""
    spoj.proved("UPDATE dbo.Uzivatel SET Jmeno = ?, Prijmeni = ?, RoleID = ? WHERE UzivatelID = ?",
                jmeno, prijmeni, role_id, uzivatel_id)


def nastav_kartu(spoj: Spojeni, uzivatel_id: int, kod_karty: str | None) -> None:
    """`None` kartu odebere (smí, je nepovinná)."""
    spoj.proved("UPDATE dbo.Uzivatel SET KodKarty = ? WHERE UzivatelID = ?", kod_karty, uzivatel_id)


def nastav_pin_hash(spoj: Spojeni, uzivatel_id: int, pin_hash: str) -> None:
    spoj.proved("UPDATE dbo.Uzivatel SET PinHash = ? WHERE UzivatelID = ?", pin_hash, uzivatel_id)


def deaktivuj_uzivatele(spoj: Spojeni, uzivatel_id: int) -> None:
    """Kmenová data se jen deaktivují, nikdy nemažou – řádek musí zůstat (historie, audit)."""
    spoj.proved("UPDATE dbo.Uzivatel SET Aktivni = 0 WHERE UzivatelID = ?", uzivatel_id)


# --- role -----------------------------------------------------------------------------------------


def role_podle_id(spoj: Spojeni, role_id: int) -> list[dict]:
    return spoj.dotaz(_ROLE + " WHERE r.RoleID = ? ORDER BY o.KodOpravneni", role_id)


def seznam_roli(spoj: Spojeni) -> list[dict]:
    return spoj.dotaz(_ROLE + " ORDER BY r.RoleID, o.KodOpravneni")


def znama_opravneni(spoj: Spojeni) -> list[str]:
    """Kódy z číselníku `Opravneni` – jediný zdroj toho, co je „známé oprávnění“."""
    return [radek["KodOpravneni"] for radek in
            spoj.dotaz("SELECT KodOpravneni FROM dbo.Opravneni ORDER BY KodOpravneni")]


def zmen_roli(spoj: Spojeni, role_id: int, *, nazev: str, popis: str | None) -> None:
    spoj.proved("UPDATE dbo.Role SET NazevRole = ?, Popis = ? WHERE RoleID = ?", nazev, popis, role_id)


def nastav_opravneni_role(spoj: Spojeni, role_id: int, kodu: list[str]) -> None:
    """Oprávnění role se mění NÁHRAVOU řádků vazební tabulky.

    `RoleOpravneni` je čistá vazba bez příznaku aktivity – deaktivace v ní není co vyjádřit,
    a proto se tu jediná výjimka z pravidla „žádný DELETE“ probíhá v jedné transakci s INSERTy.
    """
    evidovana = {radek["KodOpravneni"]: radek["OpravneniID"] for radek in
                 spoj.dotaz("SELECT KodOpravneni, OpravneniID FROM dbo.Opravneni")}
    spoj.proved("DELETE FROM dbo.RoleOpravneni WHERE RoleID = ?", role_id)
    for kod in kodu:
        spoj.proved("INSERT INTO dbo.RoleOpravneni (RoleID, OpravneniID) VALUES (?, ?)", role_id, evidovana[kod])


# --- terminály ------------------------------------------------------------------------------------


def terminal_podle_id(spoj: Spojeni, terminal_id: int) -> dict | None:
    return spoj.jeden(_TERMINAL + " WHERE TerminalID = ?", terminal_id)


def terminal_podle_kodu(spoj: Spojeni, kod_terminalu: str) -> dict | None:
    return spoj.jeden(_TERMINAL + " WHERE KodTerminalu = ?", kod_terminalu)


def seznam_terminalu(spoj: Spojeni) -> list[dict]:
    return spoj.dotaz(_TERMINAL + " ORDER BY KodTerminalu")


def existuje_terminal(spoj: Spojeni, kod_terminalu: str) -> bool:
    return spoj.hodnota("SELECT 1 FROM dbo.Terminal WHERE KodTerminalu = ?", kod_terminalu) is not None


def vloz_terminal(spoj: Spojeni, *, kod_terminalu: str, nazev: str | None, pracoviste_id: int | None) -> int:
    return spoj.vloz("INSERT INTO dbo.Terminal (KodTerminalu, NazevTerminalu, PracovisteID, Aktivni)"
                     " VALUES (?, ?, ?, 1)", kod_terminalu, nazev, pracoviste_id)


def zmen_terminalu(spoj: Spojeni, terminal_id: int, *, nazev: str | None, pracoviste_id: int | None,
                   aktivni: bool) -> None:
    """Hodnoty už sloučené se stávajícím řádkem – `None` u názvu a pracoviště znamená „vymazat“."""
    spoj.proved("UPDATE dbo.Terminal SET NazevTerminalu = ?, PracovisteID = ?, Aktivni = ? WHERE TerminalID = ?",
                nazev, pracoviste_id, 1 if aktivni else 0, terminal_id)
