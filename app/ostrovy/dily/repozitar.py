"""SQL ostrova D – Díly a číselníky. Zápis jen do vlastních tabulek (P1), cizí data jen z pohledů v_* (P2).

Identifikační číslo se ukládá i hledá normalizované (`rozhrani.normalizuj_identifikacni_cislo`),
kódy číselníků po `domena.normalizuj_kod_ciselniku` – kontrola duplicity tak proběhne se stejnou
normalizací jako zápis („3“ i „3,00“ je tloušťka 3.00).

Do SQL se skládají jen názvy tabulek a sloupců z pevných slovníků níže (žádný uživatelský vstup);
hodnoty jdou vždy jako parametry `?`.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from app.platforma.db import Spojeni, po_davkach

from .kontrakty import DilyFiltr

# Sloupce dílu včetně kódů číselníků (vlastní tabulky) a kódu velikosti (cizí pohled v_VelikostPozice, P2).
_DIL = """SELECT d.DilID,
       d.IdentifikacniCislo,
       d.NazevDilu,
       d.MaterialID,
       m.KodMaterialu,
       d.TloustkaID,
       t.TloustkaMM,
       d.PrvniOperaceID,
       o.KodOperace,
       d.StandardniDavkaKs,
       d.VelikostPoziceID,
       vp.KodVelikosti AS Velikost,
       d.PotrebnaDelkaMM,
       d.PotrebnaHloubkaMM,
       d.VaultVykresURL,
       d.Poznamka,
       d.Aktivni
FROM dbo.Dil AS d
LEFT JOIN dbo.Material            AS m  ON m.MaterialID        = d.MaterialID
LEFT JOIN dbo.TloustkaMaterialu   AS t  ON t.TloustkaID        = d.TloustkaID
LEFT JOIN dbo.PrvniVyrobniOperace AS o  ON o.PrvniOperaceID    = d.PrvniOperaceID
LEFT JOIN dbo.v_VelikostPozice    AS vp ON vp.VelikostPoziceID = d.VelikostPoziceID"""

# Popsání číselníků, které ostrov D vlastní: tabulka, sloupec ID, kód a název (None = název nemá).
_CISELNIK: dict[str, tuple[str, str, str, str | None]] = {
    "materialy": ("Material", "MaterialID", "KodMaterialu", None),
    "tloustky": ("TloustkaMaterialu", "TloustkaID", "TloustkaMM", None),
    "operace": ("PrvniVyrobniOperace", "PrvniOperaceID", "KodOperace", "NazevOperace"),
}


# --- díly ----------------------------------------------------------------------------------------


def nacti_dil(spoj: Spojeni, dil_id: int) -> dict[str, Any] | None:
    return spoj.jeden(f"{_DIL} WHERE d.DilID = ?", dil_id)


def nacti_dily_podle_id(spoj: Spojeni, dil_ids: Iterable[int]) -> list[dict[str, Any]]:
    """Hromadné načtení podle ID (i neaktivní); neexistující ID ve výsledku chybí."""
    radky: list[dict[str, Any]] = []
    for davka in po_davkach(list(dil_ids)):
        radky += spoj.dotaz(f"{_DIL} WHERE d.DilID IN ({', '.join('?' * len(davka))})", *davka)
    return radky


def najdi_dil_podle_cisla(spoj: Spojeni, identifikacni_cislo: str, *,
                          jen_aktivni: bool = False) -> dict[str, Any] | None:
    return spoj.jeden(f"{_DIL} WHERE d.IdentifikacniCislo = ?"
                      + (" AND d.Aktivni = 1" if jen_aktivni else ""), identifikacni_cislo)


def existuje_dil(spoj: Spojeni, identifikacni_cislo: str) -> bool:
    """True i pro vyřazený díl – číslo je unikátní bez ohledu na Aktivni a PATCH ho nemění."""
    return spoj.jeden("SELECT 1 AS Je FROM dbo.Dil WHERE IdentifikacniCislo = ?", identifikacni_cislo) is not None


def seznam_dilu(spoj: Spojeni, filtr: DilyFiltr) -> tuple[list[dict[str, Any]], int]:
    """Stránka výsledků a celkový počet odpovídající filtru. Filtry jsou ID, tedy přímo na Dil."""
    podminky = ["1 = 1"]
    parametry: list[Any] = []
    if filtr.hledat:
        podminky.append("(d.IdentifikacniCislo LIKE ? OR d.NazevDilu LIKE ?)")
        parametry += [_like(filtr.hledat), _like(filtr.hledat)]
    for pole, sloupec in (("material_id", "MaterialID"), ("tloustka_id", "TloustkaID"),
                          ("prvni_operace_id", "PrvniOperaceID"), ("velikost_pozice_id", "VelikostPoziceID")):
        if getattr(filtr, pole) is not None:
            podminky.append(f"d.{sloupec} = ?")
            parametry.append(getattr(filtr, pole))
    if filtr.aktivni is not None:
        podminky.append("d.Aktivni = ?")
        parametry.append(filtr.aktivni)
    kde = " AND ".join(podminky)

    celkem = spoj.hodnota(f"SELECT COUNT(*) FROM dbo.Dil AS d WHERE {kde}", *parametry) or 0
    radky = spoj.dotaz(f"{_DIL} WHERE {kde} ORDER BY d.IdentifikacniCislo"
                       " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                       *parametry, (filtr.strana - 1) * filtr.velikost, filtr.velikost)
    return radky, celkem


def hledani_dilu(spoj: Spojeni, text: str, *, material: str | None = None, tloustka_mm: Decimal | None = None,
                 prvni_operace: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Jen aktivní díly, jehož číslo nebo název obsahuje `text`; filtry jsou kódy číselníků."""
    podminky = ["d.Aktivni = 1", "(d.IdentifikacniCislo LIKE ? OR d.NazevDilu LIKE ?)"]
    parametry: list[Any] = [_like(text), _like(text)]
    for sloupec, hodnota in (("m.KodMaterialu", material), ("t.TloustkaMM", tloustka_mm),
                             ("o.KodOperace", prvni_operace)):
        if hodnota is not None:
            podminky.append(f"{sloupec} = ?")
            parametry.append(hodnota)
    return spoj.dotaz(f"{_DIL} WHERE {' AND '.join(podminky)} ORDER BY d.IdentifikacniCislo"
                      " OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY", *parametry, limit)


def vloz_dil(spoj: Spojeni, *, identifikacni_cislo: str, nazev: str | None, material_id: int | None,
             tloustka_id: int | None, prvni_operace_id: int | None, standardni_davka_ks: int | None,
             velikost_pozice_id: int | None, potrebna_delka_mm: Decimal | None,
             potrebna_hloubka_mm: Decimal | None, vault_url: str | None, poznamka: str | None) -> int:
    return spoj.vloz(
        "INSERT INTO dbo.Dil (IdentifikacniCislo, NazevDilu, MaterialID, TloustkaID, PrvniOperaceID,"
        " StandardniDavkaKs, VelikostPoziceID, PotrebnaDelkaMM, PotrebnaHloubkaMM, VaultVykresURL, Poznamka)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        identifikacni_cislo, nazev, material_id, tloustka_id, prvni_operace_id, standardni_davka_ks,
        velikost_pozice_id, potrebna_delka_mm, potrebna_hloubka_mm, vault_url, poznamka)


def nastav_pole_dilu(spoj: Spojeni, dil_id: int, sloupce: dict[str, Any]) -> None:
    """UPDATE jen poslaných sloupců; jejich názvy pocházejí z pevného mapování ve službě."""
    spoj.proved(f"UPDATE dbo.Dil SET {', '.join(f'{sloupec} = ?' for sloupec in sloupce)} WHERE DilID = ?",
                *sloupce.values(), dil_id)


# --- cizí data (pohledy ostrovů C a E, P2) ---------------------------------------------------------


def kod_velikosti(spoj: Spojeni, velikost_pozice_id: int) -> str | None:
    return spoj.hodnota("SELECT KodVelikosti FROM dbo.v_VelikostPozice WHERE VelikostPoziceID = ?",
                        velikost_pozice_id)


def id_velikosti_podle_kodu(spoj: Spojeni, kod_velikosti: str) -> int | None:
    return spoj.hodnota("SELECT VelikostPoziceID FROM dbo.v_VelikostPozice WHERE KodVelikosti = ?", kod_velikosti)


def ma_obsah(spoj: Spojeni, dil_id: int) -> bool:
    """Díl má na nějaké pozici alespoň 1 ks (obsah se při 0 ks maže, řádek tedy znamená obsah)."""
    return spoj.jeden("SELECT 1 AS Je FROM dbo.v_ObsahPozice WHERE DilID = ?", dil_id) is not None


def ma_obsah_v_dyn(spoj: Spojeni, dil_id: int) -> bool:
    return spoj.jeden(
        "SELECT 1 AS Je FROM dbo.v_ObsahPozice AS o"
        " JOIN dbo.v_Misto AS m ON m.VnitrniPoziceID = o.VnitrniPoziceID"
        " WHERE o.DilID = ? AND m.TypBoxu = 'DYN'", dil_id) is not None


# --- číselníky -----------------------------------------------------------------------------------


def polozky_ciselniku(spoj: Spojeni, typ: str) -> list[dict[str, Any]]:
    """Položky číselniku včetně vyřazených; řádky mají jednotné klíče id, kod, nazev, aktivni."""
    tabulka, id_sloupec, kod_sloupec, nazev_sloupec = _CISELNIK[typ]
    return [_kod_na_text(typ, radek) for radek in
            spoj.dotaz(f"SELECT {id_sloupec} AS id, {kod_sloupec} AS kod, {nazev_sloupec or 'NULL'} AS nazev,"
                       f" Aktivni AS aktivni FROM dbo.{tabulka} ORDER BY {id_sloupec}")]


def polozka_ciselniku(spoj: Spojeni, typ: str, polozka_id: int) -> dict[str, Any] | None:
    tabulka, id_sloupec, kod_sloupec, nazev_sloupec = _CISELNIK[typ]
    radek = spoj.jeden(f"SELECT {id_sloupec} AS id, {kod_sloupec} AS kod, {nazev_sloupec or 'NULL'} AS nazev,"
                       f" Aktivni AS aktivni FROM dbo.{tabulka} WHERE {id_sloupec} = ?", polozka_id)
    return _kod_na_text(typ, radek) if radek else None


def sloupce_ciselniku(typ: str) -> dict[str, str]:
    """Logické pole položky → název sloupce (název má jen první výrobní operace)."""
    _, _, kod_sloupec, nazev_sloupec = _CISELNIK[typ]
    return {"kod": kod_sloupec} | ({"nazev": nazev_sloupec} if nazev_sloupec else {})


def polozka_ciselniku_podle_kodu(spoj: Spojeni, typ: str, kod: str) -> dict[str, Any] | None:
    """Hledání duplicity normalizovaným kódem; u tlouštěk se porovnává číslo, tedy 3.00 i „3“ je totéž."""
    tabulka, id_sloupec, kod_sloupec, _ = _CISELNIK[typ]
    return spoj.jeden(f"SELECT {id_sloupec} AS id FROM dbo.{tabulka} WHERE {kod_sloupec} = ?",
                      _kod_na_hodnotu(typ, kod))


def vloz_polozku_ciselniku(spoj: Spojeni, typ: str, kod: str, nazev: str | None) -> int:
    tabulka, _, kod_sloupec, nazev_sloupec = _CISELNIK[typ]
    sloupce = [kod_sloupec, *([nazev_sloupec] if nazev_sloupec else [])]
    hodnoty = [_kod_na_hodnotu(typ, kod), *([nazev] if nazev_sloupec else [])]
    return spoj.vloz(f"INSERT INTO dbo.{tabulka} ({', '.join(sloupce)})"
                     f" VALUES ({', '.join('?' * len(hodnoty))})", *hodnoty)


def nastav_pole_polozky(spoj: Spojeni, typ: str, polozka_id: int, sloupce: dict[str, Any]) -> None:
    tabulka, id_sloupec, _, _ = _CISELNIK[typ]
    spoj.proved(f"UPDATE dbo.{tabulka} SET {', '.join(f'{sloupec} = ?' for sloupec in sloupce)}"
                f" WHERE {id_sloupec} = ?", *sloupce.values(), polozka_id)


# --- pomocné -------------------------------------------------------------------------------------


def _kod_na_hodnotu(typ: str, kod: str) -> Any:
    """Normalizovaný kód položky → hodnota sloupce (tloušťka je DECIMAL, ne text)."""
    return Decimal(kod) if typ == "tloustky" else kod


def _kod_na_text(typ: str, radek: dict[str, Any]) -> dict[str, Any]:
    """Tloušťka se navenek vrací jako kód „3.00“, ve sloupci je DECIMAL(5,2)."""
    if typ == "tloustky":
        radek["kod"] = format(radek["kod"], "f")
    return radek


def _like(text: str) -> str:
    """Řetězec pro LIKE; vodítka %, _ a [ se escapují, aby hledání znamenalo „obsahuje“.

    Volá se až po normalizaci, ve které z textu zmizí okolní i dvojité mezery.
    """
    return "%" + text.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]") + "%"
