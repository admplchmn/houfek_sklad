# Code review: fáze 0 – Platforma, kostry ostrovů, migrace 001–002, `api.js`

**Datum:** 26. 10. 2026 · **Rozsah:** `app/platforma` (celá), `app/ostrovy/*` (kostry a hotové čisté funkce), `sql/migrace/001–002`, `app/platforma/ui/static/api.js`, `nastroje/` · **Velikost:** ~3 200 řádků aplikace, ~1 000 řádků testů

**Ověřeno:** `python -m nastroje.over_vse`:
- 83 testů Pythonu (75 po opravách revize + 8 k splacenému dluhu a dokumentaci),
- 7 testů `api.js` v Node,
- kontrola kontraktů P10,
- ruff.

Všechno prošlo. T-SQL zatím **neběželo proti SQL Serveru**. Prostředí revize nemělo SQL Server, ten je k dispozici až s vývojovou databází. Schéma G1 prošlo jen strukturální kontrolou. Tento rozdíl je v tabulce níže jako S-01 a je nejvyšší položkou technického dluhu (TD-01).

## Shrnutí

Kostra je architektonicky v pořádku:
- hranice ostrovů hlídá automatický test (P1–P4, P6);
- transakce, ochranu `requestId` a převod chyb dělá jen Platforma;
- SQL je všude parametrizované.

Revize našla **21 nálezů**. Čtyři z nich jsou kritické. Tři mohly vést ke **dvojímu skladovému pohybu** nebo k **napůl provedené migraci** a čtvrtý k **podvržení přihlášení**. Všech 21 nálezů je opraveno a kromě CR-12, CR-13 a CR-19 má každý vlastní regresní test. CR-12 a CR-13 potřebují SQL Server a CR-19 hlídá test snímku kontraktů. Doporučení, která zbývají (S-01…S-14), jsou zapsaná v [registru technického dluhu](../../docs/technicky-dluh.md).

## Kritické a závažné nálezy (všechny opraveno)

Závažnost: 🔴 kritická · 🟠 vysoká · 🟡 střední · 🟢 nízká

| # | Soubor | Řádek | Problém → oprava | Závažnost | Test |
|---|---|---|---|---|---|
| CR-01 | `app/platforma/db.py` | 119 | pyodbc vyvolá chybu pozdějšího příkazu dávky až při `nextset()`. Bez dočtení sad výsledků se chyba ztratila a migrace se mohla **potvrdit napůl**. → `_dober_vysledky()` po každém příkazu. | 🔴 | `TestDavky` |
| CR-03 | `app/platforma/__init__.py` | 75 | Pevný vývojový `SECRET_KEY` v kódu. Kdo zná repozitář, mohl si podepsat cookie s rolí ADMIN. → Ve vývoji náhodný klíč, v provozu povinný klíč ≥ 32 znaků (`Konfigurace.over`). | 🔴 | `test_vyvoj_ma_nahodny_klic` |
| CR-04 | `app/platforma/ui/static/api.js` | 82 | Po výpadku sítě, timeoutu proxy (504) nebo odpovědi bez obálky posílal další klik **nový** `requestId`. Server pak výdej zapsal **dvakrát**. → Při nejistém výsledku se opakuje stejný `requestId`. | 🔴 | `api.test.mjs` 1, 2, 4 |
| CR-18 | `app/platforma/transakce.py` | 137 | Totéž jako CR-04 na serveru. Druhý požadavek se stejným `requestId` čekal na zámek hlavičky prvního a po vypršení dostal `CONCURRENT_CHANGE`. Klient to bral jako jistý výsledek a vygeneroval nový `requestId`. → Nový kód `REQUEST_IN_PROGRESS` (409), na který `api.js` drží stejný `requestId`. | 🔴 | `TestRequestIdSeZpracovava`, `api.test.mjs` 6 |
| CR-02 | `app/platforma/db.py` | 69 | `vloz()` zapínal `SET NOCOUNT ON` pro celé spojení. Další `proved()` pak vracel `rowcount = -1`, takže kontrola „změněn 0 řádků = souběh“ by nefungovala. → `SCOPE_IDENTITY()` se čte přes `nextset()` a NOCOUNT se nemění. | 🟠 | `test_vloz_najde_nove_id_az_v_dalsi_sade` |
| CR-05 | `app/platforma/sql_chyby.py` | 12 | Deadlock a duplicita se poznávaly podle podřetězce „1205“ nebo „2627“ kdekoli ve zprávě. Zpráva „duplicate key value is (1205)“ se proto opakovala jako deadlock. → Čte se jen nativní kód na konci záznamu a SQLSTATE. | 🟠 | `TestRozpoznaniChyb` |
| CR-06 | `app/platforma/transakce.py` | 118 | Stejný `requestId` s **jiným obsahem** nebo od **jiného uživatele** vrátil uložený výsledek cizí operace. → Otisk těla (SHA-256 bez `requestId`) se ukládá s výsledkem a kontroluje se i uživatel a typ operace. Nesoulad vrací `VALIDATION_ERROR`. | 🟠 | `TestRequestId` |
| CR-10 | `app/platforma/auth.py` | 57 | Oprávnění jsou v podepsané cookie. Deaktivovaný uživatel nebo odebrané právo proto platily až do vypršení session (12 h). → Hák `Ostrov(overeni_kontextu=…)` pro ostrov Identita ověří uživatele při každém požadavku a smí ho dodat jen jeden ostrov. | 🟠 | `TestOvereniKontextu` |
| CR-12 | `app/platforma/db.py` | 157 | Spojení nemělo `LOCK_TIMEOUT`, časový limit dotazu ani `XACT_ABORT`. Terminál na blokované pozici čekal donekonečna a chyba uprostřed dávky nezrušila transakci. → `SET XACT_ABORT ON; SET LOCK_TIMEOUT 5000` a limit dotazu 30 s, obojí nastavitelné. Chyba 1222 se mapuje na `CONCURRENT_CHANGE`. | 🟠 | mapování 1222: `test_vyprseni_zamku`; SET příkazy: S-01 |
| CR-13 | `app/ostrovy/struktura/rozhrani.py` | 195 | `zamkni_mista` zamykal přes `IN (…)`. Pořadí zámků tak určoval plán dotazu, což vedlo k deadlockům při přesunech A→B a B→A. Nad 2 100 ID dotaz navíc selhal na limitu parametrů. → Do 20 pozic se zamyká po jedné vzestupně, nad 20 po dávkách `po_davkach()` a zbytkové riziko pokryje opakování v `@transakce`. | 🟠 | `test_po_davkach`; pořadí zámků: S-01 |
| CR-15 | `app/platforma/migrace_db.py` | 67 | Migrace běžely pod účtem aplikace, takže aplikace by potřebovala `db_owner`. `DENY UPDATE/DELETE` na `SkladovyPohyb` by tím ztratilo smysl. → Samostatný účet a připojení pro `flask db …` (`HOUFEK_DB_UZIVATEL_MIGRACE`). | 🟠 | `TestMigraceUctem` |
| CR-07 | `app/platforma/http.py` | 105 | Chyběly hlavičky `nosniff` a `frame-ancestors`. API nemělo `Cache-Control: no-store`, takže sdílené PDA nebo proxy mohly držet data skladu. Velikost požadavku nebyla omezená. → Hlavičky doplněny, limit 1 MB a `PAYLOAD_TOO_LARGE` (413). | 🟡 | `test_bezpecnostni_hlavicky_a_cache`, `test_prilis_velky_pozadavek` |
| CR-08 | `app/platforma/__init__.py` | 102 | Swagger načítal skripty z CDN do stejného původu jako přihlášená aplikace i v provozu. → `/api/docs` jen ve vývoji, kontrakt zůstává v `/api/openapi.json`. | 🟡 | `test_swagger_jen_ve_vyvoji` |
| CR-09 | `app/platforma/system.py` | 102 | Při výpadku DB vracela aplikace `INTERNAL_ERROR` 500 a `/zdravi` vracelo 200, takže monitoring výpadek neviděl. → `DATABASE_UNAVAILABLE` 503 v API i v `/zdravi`. | 🟡 | `TestNedostupnaDatabaze` |
| CR-17 | `app/platforma/konfigurace.py` | 27 | Hodnoty ODBC se neescapovaly. Heslo se středníkem rozbilo připojení a hodnota jako `srv;Trusted_Connection=yes` přidala atribut. → `{…}` pro hodnoty se zvláštními znaky, u `DRIVER` a `PWD` vždy. | 🟡 | `test_odbc_hodnoty_nerozbiji_retezec` |
| CR-21 | `app/platforma/ui/static/api.js` | 9 | `api.js` bral obálku s HTTP 500 jako jistý výsledek. Chyba po potvrzení transakce (např. při sestavení odpovědi) by tak při dalším kliknutí vedla k novému `requestId` a dvojímu zápisu. → 500 je mezi nejistými výsledky. | 🟡 | `api.test.mjs` 7 |
| CR-11 | `app/platforma/openapi.py` | 26 | Dva různé modely se stejným jménem z různých ostrovů se v OpenAPI tiše slily do jednoho, takže kontrakt byl špatně. → Při kolizi `RuntimeError` s návodem přidat předponu ostrova. | 🟢 | `TestKolizeModelu` |
| CR-14 | `app/platforma/kontrakty.py` | 38 | Modely GET filtrů dědily `requestId` z `Vstup` a ten se objevil jako query parametr. → Nová základní třída `Parametry`. | 🟢 | `TestParametryBezRequestId` |
| CR-16 | `app/platforma/openapi.py`, `nastroje/kontrakty.py` | 45, 101 | Všechny query parametry byly v OpenAPI typu `string`. Kontrola P10 nehlídala parametry ani nová povinná pole vstupů, takže **nekompatibilní změna by prošla**. → Skutečné typy z modelu. Kontrola hlásí odebraný parametr, nový povinný parametr a nové povinné pole v `requestBody`. | 🟢 | `TestOpenApiParametry`, `test_kontrola_odhali_nove_povinne_vstupy` |
| CR-19 | `nastroje/kontrakty.py` | 37 | Balík ostrova se odvozoval z `import_name` blueprintu a rozbil by se, kdyby blueprint ležel v podmodulu. → Balíky se hledají podle objektu `OSTROV`. | 🟢 | `test_aktualni_stav_je_kompatibilni_se_snimkem` |
| CR-20 | `app/platforma/sql_chyby.py` | 21 | Jakákoli výjimka s pětiznakovým prvním argumentem se brala jako chyba DB (např. `ValueError("08001")` jako výpadek). → Uznává se jen tvar pyodbc `(SQLSTATE, zpráva)`. | 🟢 | `test_limit_zamku_a_nedostupnost` |

**Poznámka k CR-04 a CR-18:** dohromady tvoří jedno pravidlo pro všechny obrazovky a terminály. Klient smí vygenerovat nový `requestId` jen tehdy, když od serveru dostal **jistý** výsledek:
- **jistý:** obálka s HTTP 200 nebo 4xx, kromě `REQUEST_IN_PROGRESS`;
- **nejistý (opakovat se stejným `requestId`):** výpadek sítě, 500, 502, 503, 504, odpověď bez obálky, `REQUEST_IN_PROGRESS`.

HTTP 500 je mezi nejistými, protože chyba mohla nastat až po potvrzení transakce (při sestavení odpovědi). Doplněno při psaní architektury jako CR-21.

Pravidlo je zapsané v [ADR-0004](../../docs/adr/0004-requestid-a-skladova-transakce.md) a platí i pro budoucí klienty, například nativní aplikaci pro PDA.

## Doporučení (zatím neprovedeno → technický dluh)

| # | Soubor | Řádek | Doporučení | Kategorie | Dluh |
|---|---|---|---|---|---|
| S-01 | `tests/` | – | Integrační testy proti SQL Serveru: migrace 001–002, `zamkni_mista` (pořadí zámků, 1222), `vloz`/`SCOPE_IDENTITY`, `SET XACT_ABORT`/`LOCK_TIMEOUT`, pohledy `v_*`. Bez nich je T-SQL Platformy ověřené jen strukturálně. | Testy | TD-01 |
| S-02 | – | – | CI: `python -m nastroje.over_vse` na každý pull request a povinné schválení podle `CODEOWNERS`. | Infrastruktura | TD-02 |
| S-03 | `requirements*.txt` | – | Zamknout přesné verze závislostí (lock soubor). Teď jsou jen spodní meze. | Závislosti | TD-05 |
| S-04 | `app/platforma/db.py` | 190 | `@cteni` nevynucuje jen čtení. Služba by v něm mohla zapsat a zápis by se tiše zahodil (rollback). Navrhuji AST pravidlo v `test_pravidla_ostrovu`: v `@cteni` žádné `proved`/`vloz`. | Kód | TD-09 |
| S-05 | `app/platforma/auth.py` | 90 | Neaktivní relace na sdíleném PDA platí 12 h. Doplnit časový limit nečinnosti (např. 15 min pro role terminálů). Rozhodnutí patří ostrovu B a provozu. | Bezpečnost | TD-06 |
| S-06 | ostrov B | – | Ochrana PINu proti zkoušení (zámek po N pokusech) a argon2 hash. Patří do zadání ostrova B ve fázi 1. | Bezpečnost | TD-07 |
| S-07 | `app/platforma/__init__.py` | 48 | `_nastav_logovani` nastavuje kořenový logger z továrny aplikace. Při více instancích (testy) se handlery sčítají jen díky kontrole. Přesunout do vstupního bodu (`waitress`, `flask`). | Kód | TD-12 |
| S-08 | `app/platforma/kontrakty.py` | 20 | `DATETIME2` bez zóny se čte jako Praha. V hodině přechodu na zimní čas je posun nejednoznačný, pořadí pohybů ale drží `PohybID`. Zvážit `DATETIMEOFFSET` u `SkladovyPohyb.DatumCas`, dokud se schéma nezmrazí. | Kód | TD-11 |
| S-09 | `001_schema_g1.sql` | – | `v_KontrolaIntegrity` prochází celou historii. Spouštět v noci nebo mimo směnu a sledovat dobu běhu. | Výkon | TD-10 |
| S-10 | `001_schema_g1.sql` | – | Role `app_sklad` má `DELETE` na celé `dbo` kromě výjimek. Povolit ho jen u tabulek, kde ho logika potřebuje (kmenová data se deaktivují, nemažou). | Bezpečnost | TD-08 |
| S-11 | `.env.priklad` | – | `TrustServerCertificate=yes` vypnout po rozdání interní certifikační autority na klienty a server aplikace. | Bezpečnost | TD-13 |
| S-12 | `app/platforma/migrace_db.py` | 80 | Dva souběžné `flask db upgrade` dnes ochrání jen PK na `MigraceSchema`. Doplnit `sp_getapplock`. | Kód | TD-15 |
| S-13 | `app/platforma/system.py` | 86 | `/api/system/zdravi` je veřejné a vrací verzi a režim. Uvnitř sítě je to v pořádku. Při publikaci mimo síť omezit na IIS. | Bezpečnost | TD-16 |
| S-14 | `app/platforma/__init__.py` | 34 | Swagger ve vývoji z CDN. Pro vývoj bez internetu přibalit `swagger-ui-dist` do statických souborů. | Závislosti | TD-17 |

## Co je dobře

- **Pravidla jsou spustitelná, ne jen napsaná.** `test_pravidla_ostrovu.py` z AST hlídá zápis jen do vlastních tabulek, čtení cizích dat jen z `v_*`, importy jen z `rozhrani` a ve směru mapy závislostí. Šest programátorů tak může pracovat souběžně bez ručního hlídání hranic.
- **Ochrana proti dvojímu zápisu je v Platformě, ne v ostrovech.** Ostrov napíše `@transakce("VYDEJ", skladova=True)` a nemusí řešit `requestId`, opakování po deadlocku ani převod chyb.
- **SQL je všude parametrizované.** Do textu dotazu se skládají jen pevné části (`IN (?, ?, …)`, pevné podmínky filtru), žádné hodnoty od uživatele.
- **Selhání je hlasité a brzké.** Startovní kontroly odhalí duplicitní prefixy, chybové kódy, vlastníky tabulek i kolize jmen modelů. Neregistrovaný chybový kód skončí jako `INTERNAL_ERROR` se zápisem do logu, ne jako tichá chyba.
- **Kontrakty mají snímek a kontrolu jen přidáním.** Kontrola po CR-16 sama odhalila záměrné odebrání `requestId` z GET parametrů. Snímek byl obnoven před zmrazením, kdy je to ještě povolené.
- **Testy jsou rychlé a bez infrastruktury.** Celá sada proběhne za ~1,3 s, takže ji vývojář spustí před každým odevzdáním.

## Verdikt

**Schváleno pro předání ostrovům (fáze 0 → 1)** s dvěma podmínkami:

1. **S-01:** integrační testy proti SQL Serveru musí běžet dřív, než ostrov E zapíše první skladový pohyb. Bez nich nejsou ověřené zámky, migrace ani `SCOPE_IDENTITY`.
2. **S-02:** CI s `python -m nastroje.over_vse` musí běžet dřív, než začne souběžný vývoj víc programátorů. Pravidla ostrovů chrání jen tehdy, když se spouštějí automaticky.

Další revize: po dokončení prvního svislého řezu ostrova E (příjem a výdej) a znovu před branou G2.
