# ADR-0012: Časové údaje v databázi v UTC

**Stav:** Navrženo (implementováno v kódu, čeká na potvrzení)
**Datum:** 2026-11-03
**Rozhodují:** vedoucí projektu (navrhl a implementoval); potvrdí s vlastníkem procesu skladu a IT, protože z toho čtou i reporty a import z XLSM/PowerKey

## Kontext

Všechny časové sloupce jsou `DATETIME2` bez informace o pásmu (Schéma G1, zadání kap. 23). Dovnitř se psal místní čas z Pythonu (`datetime.now(Europe/Prague)`), `DEFAULT` v migracích ale používá čas stroje (`SYSDATETIME()`). Testovací i produkční SQL Server přitom může běžet v jiném pásmu než aplikace – v Dockeru a v CI je to UTC. Ve stejné tabulce (a dokonce ve stejném sloupci) tak vznikají dva různé časové základy. Druhý problém (TD-11, S-08): při přechodu na zimní čas je místní hodina 2:00–3:00 dvojznačná, takže dva skladové pohyby v ní mají stejné `DatumCas` a jejich časovou řadu nelze spolehlivě seřadit podle času (pořadí drží jen `PohybID`).

Rozhodnutí bylo potřeba před prvním spuštěním migrace 001, jinak by si firma nesla dvojí základ v historicích datech.

## Rozhodnutí

`DATETIME2` ukládá **UTC**. Aplikace bere aktuální čas jedině z `app.platforma.kontrakty.teď()` (naive UTC, protože naive vrací i čtení z `DATETIME2`), databázové `DEFAULT` používá `SYSUTCDATETIME()`. Do JSON se čas serializuje pražským časem s posunem, takže se navenek nic nemění.

## Zvažované možnosti

### Možnost A: UTC v `DATETIME2` (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká – jeden převod v `_cas_iso`, jeden pomocník `teď()` |
| Náklady | Nulové, dokud neběhla migrace 001; potom migrační skript a převod dat |
| Škálovatelnost | Bez omezení; porovnávání a agregace fungují bez ohledu na pásmo stroje |
| Znalost týmu | Všechno důležité dělá Platforma, ostrovy jen zavolají `teď()` |

**Pro:** žádná dvojznačná hodina; nezávislé na pásmu serveru i klienta; seřazení pohybů podle času je vždy správné; import z cizích zdrojů má jednoznačný výchozí bod.
**Proti:** reporty a UI musí převádět na místní čas (dělá `_cas_iso`, ne ostrovy); při importu historie z XLSM/PowerKey se místní časy musí převést – a u dvojznačné hodiny rozhodneme podle pořadí záznamů.

### Možnost B: Místní čas (Praha) v `DATETIME2`

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká pro zápis, vysoká pro čtení (každý dotaz přes hranice dne) |
| Náklady | Odstranění `DEFAULT` z databáze, protože místní čas stroje není místní čas skladu |
| Škálovatelnost | Křehké: záleží na nastavení každého stroje |
| Znalost týmu | Intuitivní, ale právě kvůli té intuici se na to dá zapomenout |

**Pro:** data v databázi odpovídají tomu, co vidí skladník; žádný převod při importu.
**Proti:** TD-11 zůstává otevřený; dvojí základ, který jsme právě řešili, je potřeba hlídat ručně; SQL Server v UTC by psal jiný čas než aplikace.

### Možnost C: `DATETIMEOFFSET`

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – typ v kódu i v kontraktu, pyodbc posun nepřenáší |
| Náklady | Přepis schématu, srovnávání a indexy těžší, 10 bajtů na řádek |
| Škálovatelnost | Dobrá, ale pro jednu firmu a jedno skladové místo zbytečná |
| Znalost týmu | Netypické, cizí ruce by na to narazily |

**Pro:** posun je součástí hodnoty, žádná konvence.
**Proti:** řeší problém, který u jednoho pásma nenastává, a komplikuje všechno ostatní.

## Rozbor kompromisů

Rozhodl dvojí důsledek místního času: dvojznačná hodina (TD-11) a závislost na pásmu stroje, který jsme sami způsobili `DEFAULT (SYSDATETIME())` proti času z Pythonu. UTC obojí zavírá a navenek se nic nemění, protože `_cas_iso` dodává pražský posun. Vzdáváme se „databáze vypadá jako displej" a povinnost převést importovanou historii.

## Důsledky

- Ostrovy nepoužijí `datetime.now()`, `SYSDATETIME()` ani `GETDATE()`; hlídá to test `test_casove_defaulty_jsou_utc` a kódová konvence.
- `Cas` v JSON zůstává „ISO 8601 s posunem", jen se hodnota počítá z UTC.
- Import z XLSM (ostrov H) dodá místní čas → převede se na UTC při importu, ne po něm.
- UI a tisky (G, štítky) ukazují místní čas; převod dělá Platforma, ne ostrov.
- **Filtr „od–do“ podle dne nesmí porovnávat `CAST(DatumCas AS DATE)`** – pohyby mezi půlnocí a
  02:00 místního času by spadly do špatného dne. Správně se zadaný den převede na rozmezí
  `[00:00 místního času, 00:00 následujícího dne)` a to se **v Pythonu** převede na UTC
  (`datetime.den, tzinfo=CASOVA_ZONA` → `.astimezone(timezone.utc)`) a teprve v té podobě se předá
  jako parametr do T-SQL. Převod dnu v T-SQL (`AT TIME ZONE`, `DATEADD`) se záměrně nedoporučuje,
  je na omyl. Trápí to hlavně přehledy (G); v ukázkových datech kostry to nevyleze, protože tam
  žádný převod neexistuje – ostrov to pozná až s repozitářem.
- Přehodnotit, kdyby přibyla provozovna v jiném pásmu (pak se pásma ukládá per pracoviště, stále s UTC v datech).

## Úkoly

1. [x] `DEFAULT (SYSUTCDATETIME())` v migracích 001, 002 a v `migrace_db.py`
2. [x] `platforma.kontrakty.teď()` a `_cas_iso` (testy `TestCasovaKonvence`)
3. [x] Statický test, že se místní čas do SQL nevrátil
4. [ ] Potvrdit s vlastníkem procesu (TD-11/S-08) a s IT, že SQL Server poběží v UTC
5. [ ] Při importu XLSM ošetřit převod místního času na UTC (ostrov H, `docs/migrace-xlsm.md`)
