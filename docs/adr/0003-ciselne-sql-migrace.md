# ADR-0003: Migrace schématu jako číslované T-SQL skripty pod samostatným účtem

**Stav:** Přijato (vedoucí projektu, 2. 11. 2026)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu, DBA HOUFEK
**Mění:** analýzu, sekce 8.1, řádek „Migrace schématu“ (Alembic)

## Kontext

- Bez ORM (ADR-0002) není co porovnávat a Alembic by neuměl migrace generovat. Psaly by se ručně, jen v Pythonu.
- Schéma G1 je jeden velký T-SQL skript: tabulky, filtrované indexy, pohledy, role `app_sklad`, `DENY UPDATE/DELETE` na historii a výchozí data.
- DBA a vývojáři pracují v SSMS. Skript musí jít spustit i ručně přes `sqlcmd`.
- Na schéma sahá 4–6 lidí, takže je potřeba jedno pořadí změn a ochrana před úpravou už provedeného skriptu.
- Aplikace má běžet s nejmenšími právy. Účet, který mění schéma, nesmí být účet aplikace (CR-15).

## Rozhodnutí

- **Formát skriptů.** Skripty `sql/migrace/NNN_nazev.sql` se dělí podle řádků `GO`, stejně jako v `sqlcmd`. Každý skript běží v **jedné transakci** s `XACT_ABORT ON`, takže buď projde celý, nebo nic.
- **Evidence provedených skriptů.** Provedené skripty eviduje `dbo.MigraceSchema` (soubor, SHA-256, čas). Provedený skript se nikdy nemění a oprava je nový skript s vyšším číslem. Změněný otisk = `flask db upgrade` odmítne pokračovat.
- **Příkazy:**
  - `flask db stav` vypíše stav skriptů,
  - `flask db upgrade` provede chybějící skripty,
  - `flask db oznac NNN_…sql` označí skript provedený ručně.
- **Účet pro migrace.** Migrace běží pod **účtem pro migrace** (`HOUFEK_DB_UZIVATEL_MIGRACE`, `db_owner` jen v databázi aplikace). Aplikace běží pod účtem v roli `app_sklad`.
- **Kdo skripty slučuje.** Skripty slučuje jen vlastník Platformy (P11). Ostrovy navrhují změny schématu pull requestem do `sql/migrace` a pohledy ve svém `pohledy.sql`, z kterého Platforma skládá migraci.
- **Ruční kroky DBA.** Co nejde v transakci, dělá DBA ručně podle [provozní příručky](../provoz.md), například `ALTER DATABASE … SET READ_COMMITTED_SNAPSHOT ON`.

## Zvažované možnosti

### Možnost A: Číslované T-SQL skripty + `MigraceSchema` (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká – ~100 řádků kódu (`migrace_db.py`) |
| Náklady | Žádné nástroje navíc; skript jde spustit i přes `sqlcmd` |
| Škálovatelnost | Stovky skriptů bez problému |
| Znalost týmu | Vysoká – čisté T-SQL |

**Pro:** DBA čte přesně to, co poběží. Pohledy, role, `DENY` i data jsou v jednom jazyce.
**Proti:** stav schématu se nepočítá (state-based), správnost drží pořadí skriptů. Dva vývojáři si můžou vzít stejné číslo, což se řeší před sloučením.

### Možnost B: Alembic s ručními `op.execute(...)`

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – Python obal nad T-SQL |
| Náklady | Závislost navíc, `env.py`, revize s hashi |
| Škálovatelnost | Dobrá, umí větvení revizí |
| Znalost týmu | Střední |

**Pro:** downgrade skripty, větvení a slučování revizí.
**Proti:** bez ORM nic negeneruje, takže jde jen o T-SQL v řetězcích Pythonu. DBA nemůže skript spustit v SSMS. Downgrade u skladových dat stejně nejde bezpečně (ztráta historie).

### Možnost C: SSDT / DACPAC (deklarativní schéma)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední až vysoká – Visual Studio / SqlPackage, publikační profily |
| Náklady | Nástroje na build a nasazení |
| Škálovatelnost | Dobrá pro velká schémata |
| Znalost týmu | Nízká až střední |

**Pro:** cílový stav schématu na jednom místě, automatický rozdíl.
**Proti:** datové migrace (výchozí data, přepočty) jsou těžkopádné. Vyžaduje Windows build. Vygenerovaný rozdíl je potřeba stejně číst.

### Možnost D: Flyway / Liquibase

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká (Flyway) – stejný princip jako A |
| Náklady | Java runtime na serveru, licence pro některé funkce |
| Škálovatelnost | Dobrá |
| Znalost týmu | Nízká |

**Pro:** hotový nástroj se stejným principem jako A.
**Proti:** JVM jen kvůli migracím. Proti ~100 řádkům vlastního kódu nepřináší nic, co teď potřebujeme.

## Rozbor kompromisů

A a D jsou stejný princip. A vyhrává tím, že nepřidává runtime ani nástroj a běží stejným příkazem `flask` jako zbytek. B by dala downgrade, ale u skladu se nevrací schéma, vrací se záloha. C se hodí pro velká schémata s DBA týmem, tady by přidala build krok bez užitku.

## Důsledky

- **Snazší:** DBA reviduje čisté T-SQL. Instalace na prázdnou databázi = `flask db upgrade`. Ruční nasazení přes `sqlcmd` + `flask db oznac` zůstává možné.
- **Těžší:**
  - číslo skriptu přiděluje vlastník Platformy; souběžné pull requesty se přečíslují před sloučením, nikdy po provedení;
  - příkazy mimo transakci jsou ruční kroky v provozní příručce.
- **Rollback:** obnova zálohy pořízené před `upgrade` ([provoz.md](../provoz.md)), ne „downgrade“ skript.
- **Přehodnotit:** až bude nasazování z CI, zvážit `--dry-run`. Zámek `sp_getapplock` proti souběžnému upgradu je od 1. 11. 2026 hotový (TD-15).

## Úkoly

1. [x] `migrace_db.py`, `001_schema_g1.sql`, `002_skladova_transakce.sql`; migrace pod účtem pro migrace (CR-15).
2. [x] `003_pohledy_ostrovu.sql` složený z `pohledy.sql` ostrovů a `004_prava_app_sklad.sql` (1. 11. 2026; shodu s ostrovy hlídá `tests/test_migrace.py`).
3. [ ] DBA: účet pro migrace a účet aplikace v roli `app_sklad` ([provoz.md](../provoz.md)).
4. [x] `sp_getapplock` v `upgrade` (TD-15, 1. 11. 2026).
