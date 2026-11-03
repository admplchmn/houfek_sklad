# Provozní příručka – HOUFEK Sklad

**Pro:** IT HOUFEK (server aplikace), DBA (SQL Server), vedoucí projektu · **Stav k:** 26. 10. 2026 (fáze 0; postup zatím nevyzkoušený na provozu, TD-21)

**Kdy tuto příručku použít:**
- první instalace,
- nová verze,
- noční kontroly,
- výpadek nebo podezřelé chování,
- obnova ze zálohy.

Architektura a důvody rozhodnutí jsou v [architektura.md](architektura.md), vývojové prostředí ve [vyvoj.md](vyvoj.md).

> **Nikdy:**
> - nepoužívat databázi **PowerKey** (ani pro čtení, ani pro testy);
> - neměnit provedený migrační skript;
> - nespouštět provoz s `HOUFEK_VYVOJ=1` (přihlášení bez PINu).

## 1. Prostředí

| Prostředí | Databáze | `HOUFEK_VYVOJ` | Účel |
|---|---|---|---|
| vývoj | `HoufekSklad_DEV`, zatím na PC vedoucího projektu nebo lokálně u programátora (2. 11. 2026) | 1 | práce programátorů |
| test | `HoufekSklad_TEST`, zatím tamtéž | 1 | integrační testy, testy je smějí mazat |
| provoz | `HoufekSklad` (název podle DBA) | **0** | sklad |

**Složky na serveru aplikace (provoz):**

```
C:\houfek-sklad\
  app\                    kód vydání (git tag nebo rozbalený zip), .venv, web.config
  konfigurace\houfek.env  nastavení a hesla – práva jen Administrators + identita IIS + účet noční úlohy (čtení)
  logy\                   houfek.log (HOUFEK_LOG_SOUBOR), stdout*.log (start procesu)
```

## 2. Předpoklady a přístupy

- **Server aplikace:**
  - Windows Server s IIS a modulem **HttpPlatformHandler** (Microsoft);
  - certifikát pro HTTPS;
  - Python 3.12 nebo novější (64 bit), [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).
- **SQL Server SRVACC01:** šifrované spojení je povinné. Dokud klienti nedůvěřují interní certifikační autoritě, `HOUFEK_DB_DUVEROVAT_CERTIFIKATU=1` (TD-13).
- **Účty v SQL Serveru (zakládá DBA, krok 3.1):**

  | Účet | Práva | Kde je heslo |
  |---|---|---|
  | `houfek_app` | role `app_sklad` (čtení a zápis bez DDL, historie jen přidáním) | `houfek.env` |
  | `houfek_migrace` | `db_owner` **jen v databázi aplikace** | jen v relaci správce při `flask db upgrade`, **nikdy** v `houfek.env` |

- **Kdo co dělá:**
  - DBA: databáze, účty, RCSI, zálohy;
  - IT: server, IIS, certifikát, monitoring;
  - vedoucí projektu / P1: verze aplikace a migrace.

## 3. První instalace

### 3.1 DBA – databáze, účty, RCSI

```sql
CREATE DATABASE HoufekSklad;            -- umístění souborů podle standardu DBA
GO
ALTER DATABASE HoufekSklad SET RECOVERY FULL;
-- ADR-0005: čtení neblokuje zápisy. Potřebuje krátce výhradní přístup.
ALTER DATABASE HoufekSklad SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
-- CHECK_EXPIRATION OFF: vypršené heslo by zastavilo sklad; heslo se mění plánovaně (kap. 8).
CREATE LOGIN houfek_app     WITH PASSWORD = N'<silné heslo>', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF,
                                 DEFAULT_DATABASE = HoufekSklad;
CREATE LOGIN houfek_migrace WITH PASSWORD = N'<silné heslo>', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF,
                                 DEFAULT_DATABASE = HoufekSklad;
GO
USE HoufekSklad;
CREATE USER houfek_app     FOR LOGIN houfek_app;
CREATE USER houfek_migrace FOR LOGIN houfek_migrace;
ALTER ROLE db_owner ADD MEMBER houfek_migrace;
GO
-- Kontrola: is_read_committed_snapshot_on = 1, recovery_model_desc = FULL
SELECT name, is_read_committed_snapshot_on, recovery_model_desc FROM sys.databases WHERE name = N'HoufekSklad';
```

Stejně pro `HoufekSklad_DEV` a `HoufekSklad_TEST`. Ve vývoji může stačit jeden účet s `db_owner` a prázdné `HOUFEK_DB_UZIVATEL_MIGRACE`.

### 3.2 IT – server aplikace

```powershell
# Python 3.12+ a ODBC Driver 18 nainstalované; kód vydání v C:\houfek-sklad\app
cd C:\houfek-sklad\app
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
New-Item -ItemType Directory C:\houfek-sklad\konfigurace, C:\houfek-sklad\logy -Force
copy .env.priklad C:\houfek-sklad\konfigurace\houfek.env    # vyplnit podle kap. 4
# Systémová proměnná (jen cesta, ne heslo): najdou ji web, noční úloha i konzole správce
[Environment]::SetEnvironmentVariable("HOUFEK_KONFIGURACE_SOUBOR", "C:\houfek-sklad\konfigurace\houfek.env", "Machine")
```

**Práva NTFS:**
- `konfigurace\`: číst smí jen Administrators, `IIS AppPool\HoufekSklad` a účet noční úlohy;
- `logy\`: zapisuje identita IIS.

V `houfek.env` pro provoz:
- `HOUFEK_VYVOJ=0`;
- nový `HOUFEK_TAJNY_KLIC` (`python -c "import secrets; print(secrets.token_hex(32))"`);
- `HOUFEK_LOG_SOUBOR=C:\houfek-sklad\logy\houfek.log`.

### 3.3 Migrace schématu (správce, účet pro migrace)

```powershell
cd C:\houfek-sklad\app
.venv\Scripts\activate
$env:HOUFEK_DB_UZIVATEL_MIGRACE = "houfek_migrace"
$h = Read-Host "Heslo houfek_migrace" -AsSecureString
$env:HOUFEK_DB_HESLO_MIGRACE = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($h))
flask --app app db stav          # všechno „čeká“
flask --app app db upgrade       # každý skript v jedné transakci; chyba = nic z něj se nezapsalo
                                 # běží vždy jen jeden: druhý souběžný upgrade hned skončí (sp_getapplock, TD-15)
Remove-Item Env:HOUFEK_DB_HESLO_MIGRACE   # heslo nenechávat v relaci
```

**Pak DBA přidá aplikaci do role.** Roli `app_sklad` založí migrace 001:

```sql
USE HoufekSklad;
ALTER ROLE app_sklad ADD MEMBER houfek_app;
```

**Kontrola:** `flask --app app platforma kontrola` má vypsat „Ostrovy odpovídají databázi.“ Dokud neexistuje migrace 003 s pohledy ostrovů, hlásí chybějící pohledy `v_*`, což je zatím očekávané. Ze stejného důvodu nechte `HOUFEK_KONTROLA_DB_PRI_STARTU=0`, dokud 003 neproběhne.

### 3.4 IIS – web

1. Fond aplikací `HoufekSklad`: **No Managed Code**, identita `ApplicationPoolIdentity`.
2. Web `HoufekSklad`:
   - fyzická cesta `C:\houfek-sklad\app`;
   - vazba **HTTPS** s certifikátem;
   - HTTP přesměrovat na HTTPS nebo nevázat.
3. `copy nastroje\iis\web.config.priklad web.config` a zkontrolovat cesty. IIS spouští waitress (16 vláken) a po pádu ho znovu spustí.
4. Zkouška:
   - `https://<server>/api/system/zdravi` → HTTP 200, `"rezim": "PROVOZ"`, `"databaze": "OK"`;
   - přihlášení skladníka, jeden sken, jeden přehled.

> Bez HttpPlatformHandler: waitress jako služba Windows (NSSM, WinSW) na `127.0.0.1:8080` a IIS s ARR jako reverzní proxy. Proxy timeout ≥ 60 s.

### 3.5 Noční úlohy (Plánovač úloh Windows)

| Úloha | Kdy | Program / argumenty (spustit v `C:\houfek-sklad\app`) | Selhání |
|---|---|---|---|
| Kontrola integrity | denně 02:00 | `.venv\Scripts\flask.exe` / `--app app platforma integrita` | návratový kód 1 = nález `CHYBA` → e-mail správci |

Účet úlohy: služební, se čtením `houfek.env`. Úloha běží pod účtem aplikace (jen čtení pohledu).

## 4. Proměnné prostředí

Zdroj: soubor z `HOUFEK_KONFIGURACE_SOUBOR` (provoz) nebo `.env` (vývoj). Skutečná proměnná prostředí má vždy přednost.

| Proměnná | Provoz | Význam |
|---|---|---|
| `HOUFEK_KONFIGURACE_SOUBOR` | `C:\houfek-sklad\konfigurace\houfek.env` | cesta k souboru s ostatními proměnnými (systémová proměnná) |
| `HOUFEK_DB_SERVER` | `SRVACC01.houfek.local` | SQL Server |
| `HOUFEK_DB_NAZEV` | `HoufekSklad` | databáze aplikace (nikdy PowerKey) |
| `HOUFEK_DB_UZIVATEL` | `houfek_app` | účet aplikace (role `app_sklad`) |
| `HOUFEK_DB_HESLO` | tajné | heslo účtu aplikace |
| `HOUFEK_DB_UZIVATEL_MIGRACE` | jen v relaci správce | účet pro `flask db …` (`db_owner`); prázdné = účet aplikace |
| `HOUFEK_DB_HESLO_MIGRACE` | jen v relaci správce | heslo účtu pro migrace |
| `HOUFEK_DB_OVLADAC` | `ODBC Driver 18 for SQL Server` | ovladač ODBC |
| `HOUFEK_DB_SIFROVAT` | `1` | `Encrypt=yes` (na SRVACC01 povinné) |
| `HOUFEK_DB_DUVEROVAT_CERTIFIKATU` | `1`, po zavedení interní CA `0` | `TrustServerCertificate` (TD-13) |
| `HOUFEK_DB_LIMIT_PRIHLASENI_S` | `15` | limit připojení k DB (s) |
| `HOUFEK_DB_LIMIT_DOTAZU_S` | `30` | limit jednoho dotazu (s); překročení = `DATABASE_UNAVAILABLE` |
| `HOUFEK_DB_LIMIT_ZAMKU_MS` | `5000` | čekání na zámek místa (ms); překročení = `CONCURRENT_CHANGE` |
| `HOUFEK_TAJNY_KLIC` | tajné, ≥ 32 znaků | podpis session cookie; změna odhlásí všechny |
| `HOUFEK_VYVOJ` | **`0`** | `1` = přihlášení bez PINu a Swagger (jen vývoj a test); s `1` a bez `HOUFEK_DB_SERVER` běží kostra nad dočasnou sqlite (`/zdravi` → `"databaze": "KOSTRA"`) |
| `HOUFEK_KONTROLA_DB_PRI_STARTU` | `1` | při startu ověřit ostrovy proti DB (tabulky, pohledy, oprávnění) |
| `HOUFEK_LOG_SOUBOR` | `C:\houfek-sklad\logy\houfek.log` | log (rotace 10 × 10 MB) |

## 5. Nová verze (mimo směnu)

1. Ohlásit okno údržby skladu.
2. **DBA: záloha** `BACKUP DATABASE HoufekSklad TO DISK = N'…\HoufekSklad_pred_<verze>.bak' WITH COPY_ONLY, CHECKSUM;`
3. Zastavit web: `Stop-WebSite HoufekSklad`. Terminály dostanou chybu a později pošlou stejné `requestId` znovu.
4. Nasadit kód: `git checkout <tag>` nebo rozbalit zip do `C:\houfek-sklad\app` (bez `.venv`). Pak `.venv\Scripts\pip install -r requirements.txt`.
5. `flask --app app db stav` a `flask --app app db upgrade` podle kroku 3.3.
6. Spustit web: `Start-WebSite HoufekSklad`. Ověřit `/api/system/zdravi` (200, `PROVOZ`, nová `verze`), přihlášení a sken.
7. Zapsat do provozního deníku: verze, čas, kdo, výsledek.

**Návrat (rollback):**
- `db upgrade` selhal → z chybného skriptu se nic nezapsalo. Vrátit kód na předchozí tag, spustit web, nahlásit P1.
- Aplikace po upgradu nefunguje, migrace prošla → zastavit web, **obnovit zálohu z kroku 2**, vrátit kód na předchozí tag, spustit web. Provedený skript se neopravuje, oprava přijde jako nový skript.
- Pozor: bez zámku verzí závislostí (TD-05) nemusí `pip install` vrátit staré verze knihoven.

## 6. Monitoring

Co a s jakým prahem sledovat: [architektura.md, sekce 5.3](architektura.md). Minimum pro IT:
- `GET /api/system/zdravi` každou minutu, bez přihlášení:
  - HTTP 200 = vše v pořádku;
  - 503 = databáze nedostupná;
  - `rezim` musí být `PROVOZ`.
- Log `houfek.log`:
  - `ERROR` = neočekávaná chyba nebo nedostupná DB;
  - `WARNING Deadlock` / `Vypršelo čekání na zámek` = souběh na stejném místě.
- Každý požadavek má hlavičku `X-Pozadavek-Id`. Stejné ID je v logu u chyby. Uživatel ho najde v panelu odpovědi (vývojové UI) nebo ho IT dohledá podle času.
- **Čas v logu je místní čas serveru aplikace, čas v databázi je UTC** ([ADR-0012](adr/0012-casove-udaje-v-utc.md)). Při pátrání „co předcházelo této chybě" tedy log přepočítejte na UTC (v červenci a srpnu o -2 h, jinak o -1 h), nebo si nechte pomoci `X-Pozadavek-Id`, které časovou závislost nemá.

## 7. Incidenty – příznak → kontrola → akce

| Příznak | Kontrola | Akce |
|---|---|---|
| `/zdravi` = 503, terminály hlásí „Databáze teď neodpovídá“ | běží SQL Server? síť? `stdout.log` / `houfek.log`: `Login failed` (heslo, zamčený účet), `SSL` (certifikát) | DBA: služba, účet, certifikát. Po obnově terminály opakují se stejným `requestId` |
| Hodně „Místo právě zpracovává někdo jiný“ | DBA: `SELECT session_id, blocking_session_id, wait_time, command FROM sys.dm_exec_requests WHERE blocking_session_id <> 0;` | dlouhá otevřená transakce (často ručně v SSMS) → ukončit relaci. Opakuje se na stejném místě → nahlásit P1 (horké místo) |
| Všichni najednou „Přihlášení už neplatí“ | změnil se `HOUFEK_TAJNY_KLIC`? restart s jiným souborem konfigurace? | očekávané po výměně klíče; jinak vrátit správný soubor |
| `INTERNAL_ERROR` u konkrétní akce | v `houfek.log` najít `Neočekávaná chyba (požadavek <ID>)` | předat P1 výpis kolem ID; uživatel může akci zopakovat (stejné `requestId` je bezpečné) |
| Web nenaběhne (502.5 / 503 z IIS) | `C:\houfek-sklad\logy\stdout*.log`: `Ostrovy do sebe nezapadají`, `HOUFEK_TAJNY_KLIC musí mít…`, `Chybí konfigurace databáze`, `…KONFIGURACE_SOUBOR ukazuje na…` | opravit konfiguraci podle hlášky; chyby ostrovů → P1 |
| `/zdravi` vrací `"rezim": "VYVOJ"` na provozu | `HOUFEK_VYVOJ` v `houfek.env` | **okamžitě** `HOUFEK_VYVOJ=0` a restart webu (vývojové přihlášení je bez PINu) |
| `flask db stav` hlásí `ZMĚNĚNO!` | někdo upravil provedený skript | zastavit nasazení, nahlásit P1; **nepoužít** `db oznac` |
| Noční kontrola integrity vrátila kód 1 | výpis úlohy (kontrola, objekt, popis) | nahlásit P1 / vlastníkovi dat; opravu dělá aplikace, ne ruční `UPDATE` |

## 8. Zálohy a obnova (DBA)

- **Zálohy:** model obnovy FULL.
  - plná záloha denně v noci;
  - záloha logu každých **15 min** (RPO ≤ 15 min);
  - před každou novou verzí `COPY_ONLY`.
- **Retence:** podle standardu DBA. Zkušební obnova na test jednou za čtvrtletí.
- **Hesla účtů:** měnit plánovaně mimo směnu:
  1. `ALTER LOGIN … WITH PASSWORD`;
  2. hned upravit `houfek.env`;
  3. `Restart-WebAppPool HoufekSklad`.

**Obnova k času T:**
1. `Stop-WebSite HoufekSklad`.
2. `RESTORE DATABASE … WITH NORECOVERY`, logy `WITH STOPAT = 'T'`, poslední `WITH RECOVERY`.
3. Na jiném serveru znovu propojit účty: `ALTER USER houfek_app WITH LOGIN = houfek_app;` (totéž pro `houfek_migrace`). Ověřit `is_read_committed_snapshot_on = 1`.
4. `Start-WebSite HoufekSklad`, `/zdravi`, `flask --app app platforma integrita`.
5. **Sklad informovat:** operace po čase T v databázi nejsou. Místa, kde se po T pracovalo, ověřit inventurou (ostrov F).

## 9. Eskalace

| Úroveň | Kdo | Kdy | Kontakt |
|---|---|---|---|
| 1 | IT HOUFEK (server, IIS) | web nedostupný, certifikát, monitoring | doplnit |
| 2 | DBA HOUFEK | DB nedostupná, blokování, zálohy, obnova | doplnit |
| 3 | P1 – vlastník Platformy | `INTERNAL_ERROR`, migrace, startovní chyby ostrovů | doplnit |
| 4 | vedoucí projektu | rozhodnutí o návratu verze, výpadek > 1 h během směny | doplnit |
