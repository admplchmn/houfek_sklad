# Příručka pro vývojáře – HOUFEK Sklad

**Pro:** programátory ostrovů B–H a Platformy · **Stav k:** 3. 11. 2026

**Cíl prvního dne:**
1. Aplikace běží u vás.
2. Projdete si šablonu ostrova.
3. Víte, co smíte měnit a koho se ptát.

**Odkud co je:**
- co dělá kdo a kdy je hotovo: [rozdeleni-prace.md](rozdeleni-prace.md);
- závazná pravidla práce a psaní kódu (lidé i agenti): [AGENTS.md](../AGENTS.md);
- pravidla P1–P11 a konvence API: sekce 3.9 a 4 níže, úplné znění v dokumentu „HOUFEK – Ostrovy aplikace a konvence API“;
- celkový obraz: [architektura.md](architektura.md);
- důvody rozhodnutí: [ADR](adr/README.md).

## 1. Prostředí (Windows, ~20 min)

**Potřeba:**
- Python 3.12+ (64 bit);
- [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server);
- git;
- Node.js 18+ (jen pro testy `api.js`, nepovinné);
- pro SQL ve fázi 1 [Docker Desktop](https://www.docker.com/products/docker-desktop/) s testovacím SQL Serverem (sekce 1.1). Jde i lokální SQL Server Express nebo Developer. **Nikdy ne PowerKey.**

```powershell
git clone <repozitář> houfek-sklad
cd houfek-sklad
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-vyvoj.txt
copy .env.priklad .env          # vyplnit HOUFEK_DB_UZIVATEL / HOUFEK_DB_HESLO; HOUFEK_VYVOJ=1
python -m nastroje.over_vse     # musí skončit „Všechny kontroly prošly.“
```

Testy proběhnou i bez databáze. **Bez databáze běží i aplikace:** s `HOUFEK_VYVOJ=1` a bez `HOUFEK_DB_SERVER` naběhne nad dočasnou sqlite (jen tabulky Platformy). Kostra ostrovů vrací vzorová data a skladové příkazy mají funkční `requestId`. Nic se ale neukládá.

```powershell
$env:HOUFEK_VYVOJ = "1"; flask --app app run --debug    # Swagger: http://localhost:5000/api/docs
```

Pro běh aplikace nad databází:

```powershell
flask --app app db stav         # co je v DB provedené
flask --app app db upgrade      # vlastní lokální databáze; sdílenou (PC vedoucího) jen po domluvě
flask --app app run --debug
```

**Vývojový uživatel.** Vývojové přihlášení potřebuje existující `UzivatelID`. Jednou na databázi:

```sql
INSERT INTO dbo.Uzivatel (OsobniCislo, Jmeno, Prijmeni, RoleID)
SELECT 'VYVOJ', N'Vývojář', N'Test', RoleID FROM dbo.Role WHERE KodRole = 'ADMIN';
```

**Adresy:**
- http://localhost:5000/ui/vyvoj – přihlášení bez PINu a volání libovolného API, odpověď v panelu;
- http://localhost:5000/api/docs – Swagger (jen `HOUFEK_VYVOJ=1`, potřebuje internet). Kontrakt je i v `/api/openapi.json`;
- http://localhost:5000/api/system/zdravi – stav aplikace a databáze.

### 1.1 Testovací SQL Server v Dockeru

Na integrační testy a zkoušky nad skutečnou databází stačí Docker Desktop. Server běží jen u vás a je v něm jen testovací databáze `HoufekSklad_TEST`. **PowerKey nikdy.**

1. V `.env` vyplňte blok „Testovací SQL Server“:
   - `HOUFEK_TEST_DB_SERVER=localhost`;
   - `HOUFEK_TEST_DB_HESLO`: aspoň 8 znaků, velká i malá písmena a číslice, bez `$`. Stejné heslo dostane účet `sa` v kontejneru.
2. Spusťte:

```powershell
docker compose up -d                 # SQL Server 2022 Developer na localhost:1433 (poprvé stahuje pár minut)
python -m nastroje.testovaci_db      # založí HoufekSklad_TEST (s RCSI) a provede migrace 001–004
python -m nastroje.over_vse          # teď proběhnou i integrační testy proti SQL Serveru
```

- **Prohlížení v SSMS:**
  - server `localhost,1433`, ověření SQL Server, účet `sa`;
  - v SSMS zaškrtněte „Trust server certificate“.
- **Aplikace nad stejnou databází:**
  - v `.env` nastavte `HOUFEK_DB_*` na stejné hodnoty: server, `HoufekSklad_TEST`, `sa`, heslo a `HOUFEK_DB_DUVEROVAT_CERTIFIKATU=1`;
  - spusťte `flask --app app run --debug`;
  - vývojového uživatele založte jako výše.
- **Od nuly:** `docker compose down -v` smaže server i data, další `testovaci_db` je založí znovu. Dokud 001 neběžela v provozu, dá se tak schéma během vývoje libovolně měnit (ADR-0003).
- **Port 1433 obsadil jiný SQL Server:**
  - v `docker-compose.yml` změňte levé číslo, např. `"14330:1433"`;
  - v `.env` pak nastavte server `localhost,14330`.

## 2. Jak to do sebe zapadá (5 min)

```
app/
  platforma/        A – transakce, chyby, obálka, přihlášení, DB, migrace, UI základ  (mění jen P1)
  ostrovy/
    __init__.py     OSTROVY = [...] – jediné místo spojení ostrovů                     (mění jen P1)
    _sablona/       vzor celé svislé cesty: endpoint → služba → doména → repozitář → tabulka
    identita/ struktura/ dily/ sklad/ inventura/ prehledy/ migrace/   ← váš ostrov
sql/migrace/        NNN_*.sql – schéma (slučuje jen P1)
kontrakty/          snímek OpenAPI a rozhraní (P10)
tests/              testy Platformy, pravidel ostrovů, kontraktů, migrací (statické), api.js
  integrace/        testy proti SQL Serveru (HOUFEK_TEST_DB_*), bez konfigurace se přeskočí
nastroje/           over_vse (všechny kontroly), kontrakty (snímek), iis (web.config)
docs/               architektura, ADR, provoz, technický dluh, revize
```

**Ostrov má vždy stejné soubory.** Kdo smí importovat co, hlídá test:

| Soubor | Obsah | Smí importovat |
|---|---|---|
| `__init__.py` | `OSTROV = Ostrov(...)`: prefix, tabulky, pohledy, chyby, oprávnění, menu | – |
| `kontrakty.py` | modely HTTP (`Vstup`/`SkladovyVstup`/`Parametry`/`Vystup`), `CHYBY`, `OPRAVNENI`, `MENU` | Platforma |
| `endpointy.py` | blueprint `api`: načti vstup → zavolej službu → vrať obálku | Platforma, vlastní moduly |
| `sluzby.py` | operace: `@transakce(...)` nebo `@cteni` | Platforma, vlastní moduly, **`rozhrani` jiných ostrovů** |
| `domena.py` | čistá pravidla bez DB a Flasku | Platforma (chyby, typy) |
| `repozitar.py` | SQL: zápis jen do vlastních tabulek, cizí data jen z `v_*` | Platforma (db) |
| `rozhrani.py` | **veřejné** funkce a neměnná DTO pro ostatní ostrovy, bez Flasku | Platforma (db, chyby, typy) |
| `ukazky.py` | vzorová data kostry (fáze 0); v provozním režimu selže; v hlavičce popis vzorku | vlastní `rozhrani`, `kontrakty`, `domena` |
| `pohledy.sql` | pohledy `v_*`, které ostrov publikuje | – |
| `stranky/` | obrazovky testovacího UI | Platforma (ui) |
| `testy/` | testy ostrova | cokoli vlastního; z cizích ostrovů `rozhrani` a `ukazky` (jen po mapě závislostí) |

## 3. Běžné úkoly

### 3.1 Nový skladový příkaz (POST, zapisuje)

Vzor je celý v `app/ostrovy/_sablona`. Na příkladu výdeje:

1. **`kontrakty.py`**:
   - vstup dědí ze `SkladovyVstup` (`requestId` je povinný), výstup z `Vystup`;
   - pole v snake_case, JSON je camelCase automaticky;
   - kusy `Ks`, milimetry `Mm`, čas `Cas`.
   ```python
   class VydejVstup(SkladovyVstup):
       zdroj_kod: str = Field(..., min_length=1, max_length=60)
       pocet_ks: Ks = Field(..., gt=0)

   class VydejVysledek(Vystup):
       pohyb_id: int
       zbyva_ks: int
   ```
2. **`sluzby.py`**. Název operace VELKÝMI písmeny, `skladova=True` zajistí `requestId` i hlavičku transakce (ADR-0004):
   ```python
   @transakce("VYDEJ", skladova=True)
   def vydej(spoj: Spojeni, vstup: VydejVstup, kdo: Kontext) -> VydejVysledek:
       misto = struktura.najdi_vnitrni_pozici(spoj, vstup.zdroj_kod)   # rozhraní C
       struktura.zamkni_mista(spoj, [misto.vnitrni_pozice_id])           # P8: zamknout PRVNÍ
       obsah = repozitar.nacti_obsah(spoj, misto.vnitrni_pozice_id)      # teprve teď číst
       domena.over_vydej(obsah, vstup.pocet_ks)                          # čisté pravidlo
       ...
   ```
   Volá se jen pojmenovanými argumenty: `sluzby.vydej(vstup=vstup, kdo=kontext())`.
3. **`repozitar.py`**: jen parametry `?`, nikdy hodnoty v textu SQL.
4. **`endpointy.py`**: tři kroky, žádná logika.
   ```python
   @api.post("/vydej")
   @vyzaduje("SKLAD_VYDEJ")
   @dokumentuj(vstup=VydejVstup, vystup=VydejVysledek, popis="Výdej kusů z místa.")
   def vydej():
       vysledek = sluzby.vydej(vstup=nacti_vstup(VydejVstup), kdo=kontext())
       return odpoved(vysledek, f"Vydáno. Na místě zbývá {vysledek.zbyva_ks} ks.")
   ```
5. **Testy:**
   - `domena` jednotkově;
   - službu přes testovacího klienta: `class TestVydej(ZakladTestuOstrova)` s `ostrovy = (…)` a pomocníky `prihlas`, `over_ok`, `over_chybu`, `chybna_pole` a `rid()` z `tests/pomocnik.py`;
   - SQL proti `HoufekSklad_TEST` (vrstva 3, ADR-0009): test dědí z `ZakladIntegrace` (`tests/integrace/zaklad.py`), funkci repozitáře předá `self.spoj` a leží v `testy/` ostrova. Bez `HOUFEK_TEST_DB_*` se přeskočí.

   **Ostrov, který volá jiné ostrovy, je musí v testu zaregistrovat:** `ostrovy = (struktura.OSTROV, dily.OSTROV, sklad.OSTROV)`. Jinak jejich chyby (`INVALID_BARCODE`, `WRONG_SCAN_LEVEL` …) přijdou jako `INTERNAL_ERROR`.

### 3.2 Nové čtení (GET)

- Filtry dědí z `Parametry` (ne z `Vstup`), stránkování ze `Strankovani`.
- Služba má `@cteni`, endpoint `nacti_parametry(Model)`.
- `@cteni` nikdy nezapisuje. `proved()` a `vloz()` v ní skončí chybou a pravidlo v testech to najde už v pull requestu (TD-09).
- Kořen kolekce = prázdná cesta: `@api.get("")` → `/api/dily`.
- Prázdná hodnota v query (`?materialId=`) = `null` = bez filtru, stejně jako volba „vše“ v HTML formuláři. Filtr aktivity je `aktivni: FiltrAktivni = True`, takže `?aktivni=` vrátí aktivní i vyřazené.
- Číselníky se odkazují ID (`materialId`), technické kódy s pevným seznamem jako text (`typBoxu: "DYN"`).

### 3.2a Změna kmenových dat (PATCH)

- Vstup dědí ze `Zmena`: posílají se jen měněná pole a povinný `duvod`. `vstup.zmenena_pole()` vrátí, co klient poslal (i `null`), pro update i audit.
- Povinné sloupce vyjmenujte v `NELZE_VYMAZAT = ("poradi", …)`. Poslané `null` u nich je `VALIDATION_ERROR` u pole.
- Prázdná změna (jen `duvod`) je chyba „Pošlete aspoň jedno pole…“.
- Identitu objektu (číslo dílu, osobní číslo, kódy v barcode) PATCH nemění.

### 3.3 Data jiného ostrova

| Potřebuji | Udělám |
|---|---|
| zapsat nebo zamknout | `from app.ostrovy.struktura import rozhrani as struktura` → `struktura.zamkni_mista(spoj, ids)`; volám v **mé** transakci (předám `spoj`) |
| jeden záznam | funkce `rozhrani` vlastníka, dostanu neměnné DTO |
| množinu pro přehled | `SELECT … FROM dbo.v_Misto …` v mém `repozitar.py` |
| něco, co rozhraní nemá | požádám vlastníka. Nové funkce a pole se přidávají, existující se nemění (P10) |

Směr závislostí (kdo smí volat koho) je v [architektuře, sekce 3.2](architektura.md). Opačný import neprojde testem.

### 3.4 Nahrazení kostry skutečnou implementací

Funkce s komentářem `KOSTRA (fáze 0)` vracejí data z `ukazky.py`. Co je ještě kostra, ukáže `grep -n ukazky app/ostrovy/<ostrov>/*.py`.

1. Implementace je **beze změny podpisu** (jména a pořadí parametrů, návratový typ). Kontrola kontraktů změnu jinak odmítne.
2. **Fáze 1:** SQL napište do `repozitar.py` a vlastní služby (`sluzby.py`) na něj napojte hned.
3. **Funkce v `rozhrani.py`, které volají jiné ostrovy, vracejí ve fázi 1 dál vzorová data.** Ve fázi 2 (po bráně K2) jejich tělo zavolá repozitář. Testy ostatních ostrovů tak celou fázi 1 běží nad stabilními vzorovými daty. Výjimka: funkce, které zatím vyvolají `NotImplementedError` (zápisy pro jiné ostrovy), se programují hned ([rozdeleni-prace.md](rozdeleni-prace.md), sekce 4).
4. Po nahrazení smažte import `ukazky` z funkce. `ukazky.py` nechte: spotřebitelé ho používají v testech.
5. V provozním režimu (`HOUFEK_VYVOJ=0`) volání kostry selže. Nikdo tak omylem neuvidí vzorová data jako skutečná (TD-19).

### 3.5 Změna schématu nebo pohledu

- **Nová tabulka nebo sloupec** → navrhněte T-SQL v pull requestu do `sql/migrace/` (číslo přidělí P1) a doplňte `OSTROV.tabulky`. Provedený skript se nikdy nemění (ADR-0003).
- **Pohled** → do `pohledy.sql` vašeho ostrova a do `OSTROV.pohledy`. Platforma z nich složí migraci. Sloupce pohledu jsou kontrakt (P10).
- `flask --app app platforma kontrola` ověří, že ostrovy odpovídají databázi.

### 3.6 Nový chybový kód

- Přidejte `Chyba("KOD", http, "Věta pro skladníka.")` do `kontrakty.CHYBY` vašeho ostrova.
- Kód je VELKÝMI písmeny ASCII, zpráva česky a srozumitelně.
- Kódy používané víc ostrovy patří Platformě (`app/platforma/chyby.py`).
- Duplicitní kód = aplikace nenastartuje.

### 3.7 Obrazovka testovacího UI

- Blueprint `stranky/` jako v `_sablona/stranky`, šablona dědí z `base.html`.
- Volání: `api.post("/api/sklad/vydej", {zdrojKod, pocetKs}, tlacitko)`. `api.js` sám přidá `requestId` a pošle ho znovu po nejistém výsledku.
- Sken + Enter řeší `sken.js`.

### 3.8 Před odevzdáním (pull request)

```powershell
python -m nastroje.over_vse
```

Spustí:
- testy,
- pravidla ostrovů P1–P4 a P6,
- kontrolu kontraktů P10,
- testy `api.js`,
- ruff.

Snímek kontraktů v `kontrakty/` obsahuje všechny ostrovy (kandidát pro bránu K1, 2. 11. 2026). Nový snímek (`python -m nastroje.kontrakty uloz`) jen se souhlasem P1, například po rozhodnutí otázek Q-xx pro E a F. Po zmrazení na bráně K1 se kontrakty jen přidávají (sekce 10.2 dokumentu „Ostrovy“).

### 3.9 Konvence API v kostce

Obálku, camelCase, převod chyb a `requestId` dělá Platforma sama. Na vás zbývá tohle:

- **Cesta** `/api/{ostrov}/{zdroj}`:
  - malými písmeny, česky bez diakritiky, slova oddělená pomlčkou;
  - kolekce v množném čísle;
  - ID v cestě jen celé číslo.
- **Metody:**
  - GET čte, filtry jsou v query v camelCase;
  - POST na kolekci zakládá;
  - PATCH mění jen poslaná pole a vyžaduje `duvod`;
  - akce nad objektem je `POST …/{id}/{akce}`;
  - vyřazení je `POST …/{id}/deaktivovat`;
  - DELETE ani PUT se nepoužívají.
- **Skladový příkaz** je POST se slovesem v cestě (`/api/sklad/vydej`) a povinným `requestId` (3.1).
- **JSON:**
  - klíče v camelCase (v Pythonu snake_case);
  - ID se jmenuje `{entita}Id`;
  - kusy jsou celé číslo s názvem končícím na `Ks`;
  - rozměry v mm jako číslo s nejvýše 2 desetinnými místy;
  - čas v ISO 8601 s posunem (Europe/Prague); **v databázi se ale ukládá UTC** (TD-11): aktuální čas
    berte jen z `platforma.kontrakty.teď()` a v SQL jen `SYSUTCDATETIME()` – `datetime.now()`,
    `SYSDATETIME()` ani `GETDATE()` do kódu nepatří, protože místní čas závisí na pásmu stroje
    a při přechodu na zimní čas je hodina 2:00–3:00 dvojznačná;
  - chybějící hodnota je `null`, klíč se nevynechává;
  - technické kódy VELKÝMI písmeny ASCII, texty pro lidi česky.
- **Odpověď** je vždy obálka `success, code, message, data, transakceId, varovani`. Chyba je kód z `CHYBY` vašeho ostrova (3.6) nebo z Platformy. Zveřejněný kód už nemění význam ani HTTP status.
- **Stránkování:** `?strana=1&velikost=50` (nejvýše 200) vrací `data.polozky`, `data.strana`, `data.velikost` a `data.celkem`.

Úplné znění s příklady je v dokumentu „HOUFEK – Ostrovy aplikace a konvence API“, sekce 4.

## 4. Pravidla v kostce

| | Pravidlo |
|---|---|
| P1 | Zapisuji jen do tabulek svého ostrova (`OSTROV.tabulky`) |
| P2 | Cizí data čtu jen přes `rozhrani` nebo z pohledů `v_*` |
| P3 | Z cizího ostrova importuji jen `rozhrani`, a jen ve směru závislostí |
| P4 | `rozhrani.py` nesmí používat Flask (`request`, `session`, `g`) |
| P5 | Transakci otevírá jen služba, která příkaz řídí (`@transakce`); rozhraní běží v transakci volajícího |
| P6 | DTO rozhraní jsou neměnná (`@dataclass(frozen=True)`) |
| P7 | Hranici ostrova přechází jen `AppError` s registrovaným kódem |
| P8 | Místa zamykám jen přes `struktura.zamkni_mista`, jednou, na začátku, před čtením obsahu |
| P9 | Žádný sdílený stav v paměti (globální proměnné, cache) |
| P10 | Kontrakty se po zmrazení jen přidávají |
| P11 | Schéma se mění jen migracemi Platformy |

## 5. Koho se ptát

| Téma | Kdo |
|---|---|
| Platforma, migrace, kontrakty, pravidla, CI | P1 (vlastník Platformy) |
| rozhraní a data konkrétního ostrova | jeho vlastník (`CODEOWNERS`) |
| zadání, otázky Q-xx, priority | vedoucí projektu |
| databáze, účty, výkon SQL | DBA HOUFEK |
| skladový proces („jak to ve skladu chodí“) | vlastník procesu skladu (přes vedoucího projektu) |
