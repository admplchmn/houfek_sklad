# ADR-0002: Databáze přes pyodbc a ruční T-SQL, bez ORM

**Stav:** Přijato (vedoucí projektu, 2. 11. 2026)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu
**Mění:** analýzu, sekce 8.1, řádek „Přístup k DB“ (SQLAlchemy 2 Core + ORM pro administraci)

## Kontext

- Databáze je dané Microsoft SQL Server (SRVACC01), šifrované spojení přes ODBC Driver 18.
- Na množstvích závisí **explicitní zámky** (`UPDLOCK, HOLDLOCK`, pořadí podle ID, ADR-0005). Ty musí být v SQL vidět a jít zkontrolovat v revizi.
- Pravidla vlastnictví dat P1/P2 hlídá test **nad textem SQL** (regulární výraz na `INSERT INTO / UPDATE / DELETE FROM / FROM / JOIN dbo.X`). Ostrov smí zapisovat jen do svých tabulek a číst cizí data jen z `v_*`.
- Čtecí kontrakty mezi ostrovy jsou pohledy `v_*` (ADR-0006), tedy SQL, ne modely.
- Tým zná SQL ze SSMS a z provozu PowerKey.

## Rozhodnutí

pyodbc (DB-API 2.0) s tenkým obalem `app.platforma.db.Spojeni`:
- metody `dotaz`, `jeden`, `hodnota`, `proved`, `vloz` a `kurzor` pro hromadné operace;
- SQL píše ručně vlastník ostrova v `repozitar.py`;
- hodnoty jen jako parametry `?`;
- řádky se převádějí na DTO a modely ručně.

Commit a rollback smí volat jen Platforma (`@transakce`, `@cteni`, `spojeni_pro_skript`). Každé spojení má `XACT_ABORT ON`, `LOCK_TIMEOUT` a časový limit dotazu (`pyodbc_tovarna`).

## Zvažované možnosti

### Možnost A: pyodbc + ruční T-SQL (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká – jedna knihovna, žádná vrstva mezi kódem a SQL |
| Náklady | Víc ručního kódu (mapování řádků na DTO) |
| Škálovatelnost | Plná kontrola nad dotazy, indexy a zámky |
| Znalost týmu | Vysoká – SQL ze SSMS |

**Pro:** zámky a pořadí zámků jsou v textu dotazu, revize je vidí. Pravidla P1/P2 se dají kontrolovat strojově. Žádná skrytá líná načítání ani N+1 z ORM.
**Proti:** opakující se mapování řádků. SQL je vázané na SQL Server, což je přijatelné, protože je daný. Migrace nejdou generovat automaticky (ADR-0003).

### Možnost B: SQLAlchemy 2 Core (původní návrh analýzy) + ORM pro administraci

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – dvě API (Core, ORM), session, unit of work |
| Náklady | Méně mapovacího kódu, víc konfigurace |
| Škálovatelnost | Dobrá; zámky přes `with_for_update()` jsou omezenější než hinty T-SQL |
| Znalost týmu | Střední |

**Pro:** typové sestavování dotazů, Alembic k dispozici.
**Proti:**
- hinty `UPDLOCK, HOLDLOCK` a pořadí zámků jsou schované v generovaném SQL;
- ORM modely by si ostrovy sdílely přes hranice, což oslabí P1/P2;
- dvě cesty k témuž (Core i ORM) u 4–6 lidí vedou k nejednotnosti.

### Možnost C: Plné ORM (SQLAlchemy ORM všude)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední na začátku, vysoká u souběhu a výkonu |
| Náklady | Nejméně kódu pro CRUD |
| Škálovatelnost | Riziko N+1 v přehledech, těžko čitelné plány |
| Znalost týmu | Střední |

**Pro:** rychlý CRUD kmenových dat.
**Proti:** skladové operace jsou hlavně zámky a podmíněné zápisy, ne CRUD. Přehledy jsou hromadné dotazy nad pohledy.

## Rozbor kompromisů

Píšeme víc řádků mapování, a za to máme SQL, které jde přečíst a zkontrolovat. U skladu, kde chyba v zámku znamená špatný stav zásoby, je čitelnost zámků důležitější než pohodlí CRUD. Kmenová data (díly, uživatelé) jsou malá a jejich ruční SQL je krátké.

## Důsledky

- **Snazší:** revize zámků a dotazů, kontrola P1/P2 testem, ladění v SSMS (dotaz z kódu jde zkopírovat a spustit).
- **Těžší:** testy T-SQL potřebují SQL Server, sqlite stačí jen na Platformu (ADR-0009). Mapování řádků je ruční, zvykne se na vzor ze `_sablona`.
- **Pravidla pro kód:**
  - do textu SQL se skládají jen pevné části (`IN (?, ?, …)` přes `po_davkach`, pevné podmínky filtru), nikdy hodnoty;
  - dynamické názvy tabulek jsou zakázané, protože by obešly kontrolu P1/P2.
- **Přehodnotit:** kdyby administrace kmenových dat narostla na desítky formulářů, zvážit SQLAlchemy Core jen pro ni.

## Úkoly

1. [x] `Spojeni`, `pyodbc_tovarna`, `@cteni`, `po_davkach`; dočítání sad výsledků (CR-01), `vloz` bez NOCOUNT (CR-02).
2. [ ] Integrační testy T-SQL proti SQL Serveru (TD-01).
3. [x] Analýza 8.1: odkaz na toto ADR (TD-18, 26. 10. 2026).
