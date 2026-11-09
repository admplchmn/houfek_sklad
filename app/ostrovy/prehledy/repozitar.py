"""SQL ostrova G – Přehledy a navigace: každý přehled jedním dotazem nad pohledy (S-18).

Ostrov G nic nevlastní – žádné vlastní tabulky, jen čtení cizích dat z pohledů (P2): v_Dil (D),
v_Misto (C), v_ObsahPozice, v_ZasobaDilu a v_PohybDetail (E), v_Uzivatel (B) a v_SkladovaTransakce
(Platforma). Přehledy se dřív skládaly z desítek volání rozhraní (N+1); teď je každý přehled
jeden dotaz, k tomu nejvýš jeden hromadný dotaz na umístění (`umisteni_dilu`).

Pravidla zůstávají v `domena.py` – SQL vrací řádky a Python je vyhodnotí (`poradi_umisteni`,
`doporuceni_laser`, `souhrn_zasob`), proto se monitoring a laser řadí a stránkují v Pythonu:
v SQL by se pravidla musela opsat. Historie je neomezená, ta stránkuje v SQL.

Časy se v DB drží v UTC (ADR-0012), období pohybů se zadává ve dnech Europe/Prague včetně
okrajů – proto `_den_v_utc` a porovnání `>= od` a `< následující den`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.platforma.db import Spojeni, po_davkach

from .kontrakty import HledaniFiltr, LaserFiltr, PohybyFiltr, ZasobyFiltr

PRAHA = ZoneInfo("Europe/Prague")

# Kmenová data dílu pro přehledy: kódy číselníků (ne ID) – filtry se vyhodnocují v SQL.
_DIL_SLOUPCE = ("DilID", "IdentifikacniCislo", "NazevDilu", "KodMaterialu", "TloustkaMM", "KodPrvniOperace",
                "StandardniDavkaKs", "Velikost", "VaultVykresURL")
_DIL = ", ".join(f"d.{sloupec}" for sloupec in _DIL_SLOUPCE)

# Sloupce pohybu a jejich doplnění – stejné pro historii i pro pohyby náležející do transakce.
_POHYB = """p.PohybID, p.DatumCas, p.TypPohybu, p.DilID, d.IdentifikacniCislo, p.VnitrniPoziceID,
       m.KodMista, p.Mnozstvi, p.StavPred, p.StavPo, p.UzivatelID, pu.CeleJmeno, p.TerminalID,
       p.TransakceID, p.Poznamka"""

_POHYB_SPOJENI = """LEFT JOIN dbo.v_Dil AS d       ON d.DilID           = p.DilID
LEFT JOIN dbo.v_Misto AS m     ON m.VnitrniPoziceID = p.VnitrniPoziceID
LEFT JOIN dbo.v_Uzivatel AS pu ON pu.UzivatelID     = p.UzivatelID"""

# Statistika „zásoba podle typu boxu“: STAT řádek z v_ZasobaDilu, DYN řádek sečtený z obsahu.
_ZASOBA_STAT = (f"SELECT {_DIL}, z.StatickeUmisteniID, z.VnitrniPoziceID AS StatVnitrniPoziceID,"
                " z.StatKs, z.DynKs, z.MinimalniPocetKs, z.OptimalniPocetKs, z.MaximalniPocetKs,"
                " z.StavZasoby, m.KodMista AS StatKod, m.KodBoxu AS StatKodBoxu,"
                " m.RegalID AS StatRegalID, m.UrovenID AS StatUrovenID, m.BoxID AS StatBoxID"
                " FROM dbo.v_ZasobaDilu AS z"
                " JOIN dbo.v_Dil AS d ON d.DilID = z.DilID"
                " LEFT JOIN dbo.v_Misto AS m ON m.VnitrniPoziceID = z.VnitrniPoziceID")

_ZASOBA_DYN = (f"SELECT {_DIL}, NULL AS StatickeUmisteniID, NULL AS StatVnitrniPoziceID, 0 AS StatKs,"
               " SUM(CASE WHEN m.TypBoxu = 'DYN' THEN o.PocetKs ELSE 0 END) AS DynKs,"
               " NULL AS MinimalniPocetKs, NULL AS OptimalniPocetKs, NULL AS MaximalniPocetKs,"
               " NULL AS StavZasoby, NULL AS StatKod, NULL AS StatKodBoxu, NULL AS StatRegalID,"
               " NULL AS StatUrovenID, NULL AS StatBoxID"
               " FROM dbo.v_ObsahPozice AS o"
               " JOIN dbo.v_Misto AS m ON m.VnitrniPoziceID = o.VnitrniPoziceID"
               " JOIN dbo.v_Dil AS d ON d.DilID = o.DilID")


# --- díly, hledání, umístění ------------------------------------------------------------------------


def dil(spoj: Spojeni, dil_id: int) -> dict[str, Any] | None:
    """Kmenová data dílu (i vyřazeného – karta dílu ho zobrazuje)."""
    return spoj.jeden(f"SELECT {_DIL} FROM dbo.v_Dil AS d WHERE d.DilID = ?", dil_id)


def hledani(spoj: Spojeni, text: str, filtr: HledaniFiltr, limit: int) -> list[dict[str, Any]]:
    """Díly podle části čísla nebo názvu s filtry dílu i umístění (21.1.2), nejvýš `limit`.

    `text` je už normalizovaný (`struktura.rozloz_kod`); filtry dílu jsou ID přímo na v_Dil (4.2),
    umístění se filtruje EXISTS nad v_Misto a zásobový stav nad v_ZasobaDilu. Hledá se jen mezi
    aktivními díly a řadí se podle čísla – stejně jako to dělá rozhraní ostrova D.
    """
    podminky = ["d.Aktivni = 1", "(d.IdentifikacniCislo LIKE ? OR d.NazevDilu LIKE ?)"]
    parametry: list[Any] = [_like(text), _like(text)]
    filtry, hodnoty = _filtry_dilu(filtr)
    podminky += filtry
    parametry += hodnoty
    if filtr.typ_boxu:
        podminky.append(_exists_umisteni("mi.TypBoxu = ?"))
        parametry.append(filtr.typ_boxu)
    if filtr.pracoviste_id:
        podminky.append(_exists_umisteni("mi.PracovisteID = ?"))
        parametry.append(filtr.pracoviste_id)
    if filtr.stav_zasoby:
        podminky.append("EXISTS (SELECT 1 FROM dbo.v_ZasobaDilu AS z"
                        " WHERE z.DilID = d.DilID AND z.StavZasoby = ?)")
        parametry.append(filtr.stav_zasoby)
    return spoj.dotaz(f"SELECT {_DIL} FROM dbo.v_Dil AS d WHERE {' AND '.join(podminky)}"
                      " ORDER BY d.IdentifikacniCislo OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY",
                      *parametry, limit)


def umisteni_dilu(spoj: Spojeni, dil_ids: list[int]) -> list[dict[str, Any]]:
    """Všechna aktivní místa s obsahem dílů – jeden hromadný dotaz, seřadí `domena.poradi_umisteni`.

    Karta dílu z řádků staví `umisteni`, monitoring `mista` a výsledek hledání adresu a zvýraznění
    prvního místa – proto na něj stačí jeden dotaz za celý přehled.
    """
    return _po_davkach(spoj, "SELECT o.DilID, o.PocetKs, m.VnitrniPoziceID, m.KodMista, m.KodBoxu, m.TypBoxu,"
                             " m.PoradiVBoxu, m.RegalID, m.UrovenID, m.BoxID, m.Adresa"
                             " FROM dbo.v_ObsahPozice AS o"
                             " JOIN dbo.v_Misto AS m ON m.VnitrniPoziceID = o.VnitrniPoziceID",
                       "o.DilID", dil_ids)


def obsah_pozic(spoj: Spojeni, vnitrni_pozice_ids: list[int]) -> list[dict[str, Any]]:
    """Obsah pozic včetně čísla dílu a odkazu do Vaultu (SVG úrovně, sken pozice)."""
    return _po_davkach(spoj, "SELECT o.VnitrniPoziceID, o.DilID, o.PocetKs, d.IdentifikacniCislo,"
                             " d.VaultVykresURL"
                             " FROM dbo.v_ObsahPozice AS o"
                             " JOIN dbo.v_Dil AS d ON d.DilID = o.DilID",
                       "o.VnitrniPoziceID", vnitrni_pozice_ids)


# --- zásoby, laser ----------------------------------------------------------------------------------


def stat_zasoba(spoj: Spojeni, dil_id: int) -> dict[str, Any] | None:
    """Aktivní STAT místo dílu se stavem zásoby (v_ZasobaDilu); bez přiřazení None.

    Místo se pojí LEFT JOIN – přiřazení na vyřazené pozici nemá v_Misto a karta dílu pak ukáže
    kód boxu otazníkem, jako to dělala kostra.
    """
    return spoj.jeden("SELECT z.StatickeUmisteniID, z.VnitrniPoziceID, z.StatKs, z.MinimalniPocetKs,"
                      " z.OptimalniPocetKs, z.MaximalniPocetKs, z.StavZasoby,"
                      " m.KodMista AS StatKod, m.KodBoxu AS StatKodBoxu, m.RegalID AS StatRegalID,"
                      " m.UrovenID AS StatUrovenID, m.BoxID AS StatBoxID"
                      " FROM dbo.v_ZasobaDilu AS z"
                      " LEFT JOIN dbo.v_Misto AS m ON m.VnitrniPoziceID = z.VnitrniPoziceID"
                      " WHERE z.DilID = ? ORDER BY z.StatickeUmisteniID", dil_id)


def zasoby(spoj: Spojeni, filtr: ZasobyFiltr) -> list[dict[str, Any]]:
    """Řádky monitoringu (13.1): díly se STAT místem z v_ZasobaDilu, při jenSeStat=false i díly jen v DYN.

    Filtr pracoviště se vztahuje ke STAT místu, u dílů bez STAT k kterémukoli umístění (přesně
    jak to v kostře dělal ostrov E a C). Stav zásoby ani „jen problémové“ do dotazu nepatří –
    souhrn platí za všechny díly filtru, takže se filtruje a řadí v Pythonu.
    """
    filtry, hodnoty = _filtry_dilu(filtr)
    kde_dilu = "".join(f" AND {podminka}" for podminka in filtry)
    pracoviste_stat = " AND m.PracovisteID = ?" if filtr.pracoviste_id else ""
    pracoviste_dyn = ""
    if filtr.pracoviste_id:
        pracoviste_dyn = (" AND EXISTS (SELECT 1 FROM dbo.v_ObsahPozice AS o2"
                          " JOIN dbo.v_Misto AS m2 ON m2.VnitrniPoziceID = o2.VnitrniPoziceID"
                          " WHERE o2.DilID = o.DilID AND m2.PracovisteID = ?)")
    group_by = " GROUP BY " + ", ".join(f"d.{sloupec}" for sloupec in _DIL_SLOUPCE)
    stat = f"{_ZASOBA_STAT} WHERE 1 = 1{kde_dilu}{pracoviste_stat}"
    parametry = list(hodnoty) + [filtr.pracoviste_id] * bool(filtr.pracoviste_id)
    if filtr.jen_se_stat:
        return spoj.dotaz(stat, *parametry)
    dyn = (f"{_ZASOBA_DYN} WHERE NOT EXISTS (SELECT 1 FROM dbo.v_ZasobaDilu AS z"
           f" WHERE z.DilID = o.DilID){pracoviste_dyn}{kde_dilu}{group_by}")
    parametry_dyn = [filtr.pracoviste_id] * bool(filtr.pracoviste_id) + list(hodnoty)
    return spoj.dotaz(f"{stat} UNION ALL {dyn}", *parametry, *parametry_dyn)


def laser(spoj: Spojeni, filtr: LaserFiltr) -> list[dict[str, Any]]:
    """Díly s maximem ve STAT (kap. 14), první operace LASER nebo ta z filtru podle ID.

    Doporučený počet (Q-22) počítá `domena.doporuceni_laser`, proto se tu nedoporučení filtruje,
    nesečítá ani neřadí – SQL by muselo zopakovat zaokrouhlení na standardní dávku.
    """
    filtry, parametry = _filtry_dilu(filtr)          # filtr podle operace je už v nich (ID)
    if filtr.prvni_operace_id is None:
        filtry.append("d.KodPrvniOperace = 'LASER'")
    kde = " AND ".join(["z.MaximalniPocetKs IS NOT NULL", *filtry])
    return spoj.dotaz(f"SELECT {_DIL}, z.StatKs, z.DynKs, z.MaximalniPocetKs"
                      " FROM dbo.v_ZasobaDilu AS z"
                      " JOIN dbo.v_Dil AS d ON d.DilID = z.DilID"
                      f" WHERE {kde}", *parametry)


# --- historie ---------------------------------------------------------------------------------------


def stranka_pohybu(spoj: Spojeni, filtr: PohybyFiltr, vnitrni_pozice_id: int | None) -> tuple[list[dict], int]:
    """Stránka pohybů (nejnovější první) a jejich celkový počet.

    `vnitrni_pozice_id` je pozice rozložená ze scanovaného kódu filtru (služba ji překládá
    rozhraní ostrova C); období od–do jsou dny v Praze včetně okrajů, v DB je UTC.
    """
    podminky, parametry = ["1 = 1"], []
    for pole, sloupec in (("dil_id", "p.DilID"), ("typ_pohybu", "p.TypPohybu"), ("uzivatel_id", "p.UzivatelID")):
        if getattr(filtr, pole) is not None:
            podminky.append(f"{sloupec} = ?")
            parametry.append(getattr(filtr, pole))
    pozice_id = vnitrni_pozice_id if vnitrni_pozice_id is not None else filtr.vnitrni_pozice_id
    if pozice_id is not None:
        podminky.append("p.VnitrniPoziceID = ?")
        parametry.append(pozice_id)
    if filtr.od:
        podminky.append("p.DatumCas >= ?")
        parametry.append(_den_v_utc(filtr.od))
    if filtr.do:
        podminky.append("p.DatumCas < ?")
        parametry.append(_den_v_utc(filtr.do, dalsi_den=True))
    kde = " AND ".join(podminky)
    celkem = spoj.hodnota(f"SELECT COUNT(*) FROM dbo.v_PohybDetail AS p WHERE {kde}", *parametry) or 0
    radky = spoj.dotaz(f"SELECT {_POHYB} FROM dbo.v_PohybDetail AS p {_POHYB_SPOJENI} WHERE {kde}"
                       " ORDER BY p.DatumCas DESC, p.PohybID DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                       *parametry, (filtr.strana - 1) * filtr.velikost, filtr.velikost)
    return radky, celkem


def pohyby_dilu(spoj: Spojeni, dil_id: int, limit: int) -> list[dict[str, Any]]:
    """Poslední pohyby dílu pro kartu dílu (kap. 15)."""
    return spoj.dotaz(f"SELECT {_POHYB} FROM dbo.v_PohybDetail AS p {_POHYB_SPOJENI} WHERE p.DilID = ?"
                      " ORDER BY p.DatumCas DESC, p.PohybID DESC OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY",
                      dil_id, limit)


def transakce(spoj: Spojeni, transakce_id: Any) -> list[dict[str, Any]]:
    """Hlavička skladové transakce a její pohyby v jednom dotazu (PRESUN = OUT + IN mají stejné ID).

    Hlavička je závazná pro typ operace, čas a uživatele a opakuje se na každém řádku; transakce
    bez pohybů má jeden řádek s prázdnými sloupci pohybů. Pohyby mají stejné sloupce jako historie.
    """
    return spoj.dotaz("SELECT t.TypOperace AS TransakceTypOperace, t.DatumCas AS TransakceDatumCas,"
                      " t.UzivatelID AS TransakceUzivatelID, t.TerminalID AS TransakceTerminalID,"
                      f" uh.CeleJmeno AS TransakceCeleJmeno, {_POHYB}"
                      " FROM dbo.v_SkladovaTransakce AS t"
                      " LEFT JOIN dbo.v_PohybDetail AS p ON p.TransakceID = t.TransakceID"
                      " LEFT JOIN dbo.v_Uzivatel AS uh ON uh.UzivatelID = t.UzivatelID"
                      f" {_POHYB_SPOJENI} WHERE t.TransakceID = ? ORDER BY p.PohybID", transakce_id)


# --- pomocné ----------------------------------------------------------------------------------------


def _filtry_dilu(filtr: Any) -> tuple[list[str], list[Any]]:
    """Shodné filtry dílu pro hledání, monitoring i laser (filtry jsou ID, tedy sloupce v_Dil)."""
    podminky, parametry = [], []
    for pole, sloupec in (("material_id", "d.MaterialID"), ("tloustka_id", "d.TloustkaID"),
                          ("prvni_operace_id", "d.PrvniOperaceID")):
        if getattr(filtr, pole) is not None:
            podminky.append(f"{sloupec} = ?")
            parametry.append(getattr(filtr, pole))
    return podminky, parametry


def _exists_umisteni(podminka: str) -> str:
    """Podmínka „díl leží na nějakém místě splňujícím …“ (filtry umístění v hledání)."""
    return ("EXISTS (SELECT 1 FROM dbo.v_ObsahPozice AS o JOIN dbo.v_Misto AS mi"
            f" ON mi.VnitrniPoziceID = o.VnitrniPoziceID WHERE o.DilID = d.DilID AND {podminka})")


def _po_davkach(spoj: Spojeni, select: str, sloupec: str, hodnoty: list[int]) -> list[dict[str, Any]]:
    """Hromadný dotaz `WHERE sloupec IN (…)` po dávkách (SQL Server má limit na počet parametrů)."""
    radky: list[dict[str, Any]] = []
    for davka in po_davkach(list(hodnoty)):
        radky += spoj.dotaz(f"{select} WHERE {sloupec} IN ({', '.join('?' * len(davka))})", *davka)
    return radky


def _den_v_utc(den: date, *, dalsi_den: bool = False) -> datetime:
    """Půlnoc pražského dne jako naive UTC (DATETIME2 je UTC, ADR-0012).

    `dalsi_den=True` je půlnoc následujícího dne – horní hranice období, která má zahrnout celý den.
    """
    den = den + timedelta(days=1) if dalsi_den else den
    return datetime.combine(den, time.min, PRAHA).astimezone(timezone.utc).replace(tzinfo=None)


def _like(text: str) -> str:
    """Řetězec pro LIKE „obsahuje“; vodítka %, _ a [ se escapují (stejně jako v ostrově D)."""
    return "%" + text.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]") + "%"
