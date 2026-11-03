# Code review: fáze 0 – HTTP kontrakty ostrovů B–G, migrace 003–004, splacený dluh

**Datum:** 1. 11. 2026 · **Rozsah:** `app/ostrovy/{identita,struktura,dily,sklad,inventura,prehledy}` (kontrakty, čistá pravidla, kostra služeb, endpointy, vzorová data), `app/platforma` (změny), `sql/migrace/003–004`, `tests/` (nové vrstvy) · **Velikost:** ~9 900 řádků aplikace a testů v `app/`, 73 endpointů ostrovů B–G a 4 Platformy

**Ověřeno:** `python -m nastroje.over_vse`:
- 205 testů Pythonu (8 přeskočených: 7 integračních bez `HOUFEK_TEST_DB_*`, 1 bez knihovny argon2),
- 7 testů `api.js` v Node,
- kontrola kontraktů P10 (jen přidáno, nic odebráno),
- ruff.

Všechno prošlo. T-SQL pořád **neběželo proti SQL Serveru** (TD-04). Nově ho ale hlídá statická kontrola migrací: shoda `pohledy.sql` s migrací, pořadí pohledů a existence každého sloupce `alias.Sloupec` v tabulce (`tests/test_migrace.py`). Pojistka testu ověřuje, že úmyslný překlep opravdu najde.

## Shrnutí

Všech šest ostrovů s HTTP rozhraním má hotový kontrakt pro bránu K1:
- Pydantic modely vstupů a výstupů,
- endpointy s oprávněními,
- čistá pravidla (testovaná),
- kostra služeb nad vzorovými daty.

Vzorová data na sebe navazují napříč ostrovy C–G a jejich shodu hlídá test. Operace se dají proklikat v Swaggeru i **bez SQL Serveru**: ve vývoji bez `HOUFEK_DB_SERVER` aplikace běží nad dočasnou sqlite. Skladové příkazy přitom mají funkční `requestId`.

Revize našla **11 nálezů** a všechny jsou opravené:
- 4 vysoké, z toho 2 mohly v provozu tiše ztratit data (CR-29) nebo zablokovat filtr (CR-22);
- 4 střední;
- 3 nízké.

**8 doporučení** zůstává otevřených. Patří do fáze 1 nebo čekají na rozhodnutí vlastníka procesu. Nejdůležitější je S-15: zakládací POST bez přirozeného klíče se při dvojkliku provede dvakrát.

## Nálezy (všechny opraveno)

Závažnost: 🔴 kritická · 🟠 vysoká · 🟡 střední · 🟢 nízká

| # | Soubor | Řádek | Problém → oprava | Závažnost | Test |
|---|---|---|---|---|---|
| CR-22 | `app/platforma/http.py` | 94 | Filtr `aktivni: bool \| None = True` nešel z query nastavit na `null`. Volba „aktivní i vyřazené“ byla nedosažitelná v D a v každém dalším filtru. → Prázdná hodnota (`?aktivni=`, volba „vše“ v HTML formuláři) = `null`. Typ `FiltrAktivni` v Platformě. | 🟠 | `test_pracoviste_regaly_urovne`, `test_seznam_bez_tajemstvi`, `test_upozorneni` |
| CR-24 | `app/ostrovy/dily/pohledy.sql` | 10 | `v_Dil` neměl `MaterialID`, `TloustkaID`, `PrvniOperaceID` ani `VelikostPoziceID`. Filtry ostrova G jsou podle 4.2 ID, takže by je fáze 1 v SQL neuměla. → Sloupce doplněny před prvním provedením 003. | 🟠 | `test_pohledy_sql_odpovida_migracim`, `test_sloupce_v_pohledech_existuji` |
| CR-29 | `app/platforma/db.py` | 90 | (TD-09) Zápis ve službě `@cteni` se tiše zahodil rollbackem. Programátor by si myslel, že uložil. → `Spojeni.jen_cteni`: `proved()` a `vloz()` v `@cteni` skončí chybou. AST pravidlo totéž najde už v pull requestu. | 🟠 | `TestCteniNezapisuje`, `TestCteni` |
| CR-32 | `app/ostrovy/sklad/testy` | – | Chyby ostrova C (`INVALID_BARCODE`, `WRONG_SCAN_LEVEL`) procházejí endpointy E. Test ostrova, který zaregistroval jen sám sebe, je dostal jako `INTERNAL_ERROR`. V celé aplikaci to fungovalo, test ale lhal. → Testy E, F a G registrují i ostrovy, na kterých závisí; vzor je v `vyvoj.md`. | 🟠 | `test_prijem_dyn` (WRONG_SCAN_LEVEL) |
| CR-23 | `app/platforma/kontrakty.py` | 87 | PATCH povinného údaje na `null` prošel validací. Úroveň s `poradi: null` by na `NOT NULL` skončila chybou SQL. D to řešil ručně jen u kódu číselníku. → `Zmena.NELZE_VYMAZAT` deklaruje povinná pole a vrací chybu u pole. Ruční kontrola v D odstraněna. | 🟡 | `test_regal_a_uroven`, `test_zalozeni_a_zmena`, `test_zmena_minima_a_ukonceni` |
| CR-25 | `tests/test_platforma_revize.py` | 371 | `TestKostraVProvozu` závisel na pořadí testů. `from . import ukazky` vrátí atribut balíčku i po odebrání ze `sys.modules`, takže pojistka po dřívějším importu neběžela. → Test odebere i atribut balíčku a vrátí ho zpět. | 🟡 | `test_kostra_v_provozu_selze` |
| CR-27 | `app/ostrovy/prehledy/kontrakty.py` | 243 | Pole `transakce_id` v detailu transakce by Platforma přesunula do obálky `transakceId` u GET. Klient by to četl jako „požadavek něco zapsal“. → Pole se jmenuje `skladovaTransakceId`, obálka GET má `transakceId: null`. | 🟡 | `test_historie_a_transakce` |
| CR-31 | `app/platforma/migrace_db.py` | 64 | (TD-15) Dva souběžné `flask db upgrade` chránil jen PK `MigraceSchema` a druhý spadl uprostřed. → `zamek_upgrade()`: `sp_getapplock` na relaci, druhý upgrade hned skončí srozumitelnou chybou. | 🟡 | `TestZamekUpgradu` |
| CR-26 | `tests/test_pravidla_ostrovu.py` | 100 | Pravidlo P3 zakazovalo testům spotřebitele vzorová data dodavatele (`ukazky`), i když k tomu podle dokumentace jsou. → Povoleno jen v `testy/` a jen po mapě závislostí. | 🟢 | `test_p3_jen_rozhrani_a_jen_po_mape` |
| CR-28 | `app/platforma/http.py` | 60 | Délka seznamu (`too_long`, `too_short`) vracela anglickou zprávu Pydantic. → Česky: „Nejvýše 100 položek.“ | 🟢 | `test_role` |
| CR-30 | `app/platforma/__init__.py` | 51 | (TD-12) Továrna aplikace nastavovala kořenový logger, takže víc instancí v jednom procesu zdvojovalo logy. → Jen logger `houfek`, handler jednou, úroveň nastavenou předem nepřepíše. | 🟢 | `TestLogovani` |

## Doporučení (otevřená)

| # | Soubor | Doporučení | Kategorie | Kdy / kdo |
|---|---|---|---|---|
| S-15 | `app/ostrovy/*/sluzby.py` | **Zakládací POST nejsou idempotentní** (`skladova=False`, `requestId` se ignoruje). Většinu chrání přirozený klíč, takže druhý klik vrátí `ALREADY_EXISTS`. Bez něj se ale provede dvakrát `POST /urovne/{id}/boxy` (bez `cisloBoxu` = další číslo řady) a `POST /api/inventura`. Návrh: tyto dvě operace na `@transakce(…, skladova=True)`, UI posílá `requestId` u každého POST už teď. | Správnost | fáze 1, P1 + vlastníci C a F |
| S-16 | `app/ostrovy/inventura/sluzby.py` | Kontrola „pozice nejvýš v jedné rozpracované inventuře“ musí ve fázi 1 běžet až po `zamkni_mista(ids)`. Jinak dvě souběžná založení překryv neuvidí. Poznámka je v kódu. | Souběh | fáze 1, vlastník F |
| S-17 | `app/ostrovy/identita/sluzby.py` | Zámek po chybných pokusech (TD-07) potřebuje zápis, takže přihlášení se stane `@transakce("PRIHLASENI")`. Pojistka CR-29 na to upozorní, pokud se zapomene. | Bezpečnost | fáze 1, vlastník B |
| S-18 | `app/ostrovy/prehledy/sluzby.py` | Kostra G skládá přehledy přes rozhraní a u každého dílu prochází celý sklad. Fáze 1 = jeden dotaz nad `v_*` na přehled. Indexy na to v 001 jsou (`IX_ObsahPozice_DilID`, `IX_SkladovyPohyb_Pozice`). | Výkon | fáze 1, vlastník G |
| S-19 | `app/ostrovy/inventura/domena.py` | Inventura potřebuje `InventuraPolozka.PosledniPohybID` (D8). Stav položky CEKA / ZAPSANO / PREPOCITAT se z něj **odvozuje**, sloupec `StavPolozky` netřeba. Migrace až po rozhodnutí Q-16, protože `flask db upgrade` by ji spustil hned. | Schéma | po Q-16, P1 |
| S-20 | `app/ostrovy/struktura/endpointy.py` | `GET /stitky` (PDF) čeká na vzhled štítku (Q-19). Kódy a adresy už generuje `domena` a parser je přečte zpět – hlídá to test „co se vytiskne, jde přečíst“. | Funkce | pilot, vlastník C |
| S-21 | `app/ostrovy/struktura/kontrakty.py` | Kódy pracoviště, regálu a úrovně jsou v barcode, proto je PATCH nemění. Přejmenování by znamenalo přetisk štítků a přepočet `FullBoxKlic`. Rozhodne vlastník procesu, zda je vůbec potřeba. | Proces | otevřený bod |
| S-22 | `app/ostrovy/inventura/domena.py` | JINY_DIL v **DYN** pozici zaúčtuje nalezený díl na stejnou pozici, i když nesedí velikost (fyzicky tam leží). Nesoulad pak ukáže `v_KontrolaIntegrity`. Rozhodnout, zda Q-17 (povinný cíl) platí i pro DYN. | Proces | Q-17 |

## Co je dobře

- **Pravidla mimo HTTP.** Všechna doménová pravidla jsou čisté funkce v `domena.py` a testují se bez Flasku a databáze. Kostra služeb je jen tenká vrstva, kterou fáze 1 nahradí repozitářem. Podpisy se přitom nemění.
- **Co se vytiskne, jde přečíst.** Kódy boxů, adresy a štítky regálů z `domena` projdou zpět parserem `rozloz_kod` (test pro všech 7 členění i obě řady). Vzorová šablona C1–C7 se porovnává s výchozími daty migrace 001 a hlídají se i invarianty šablony: česká abeceda s CH, číslování STAT po řadách, přihrádky bez překryvu.
- **SQL = Python.** Výraz `CASE` zásobového stavu z `v_ZasobaDilu` se spustí v sqlite a porovná se s `domena.stav_zasoby` pro všechny kombinace.
- **Bezpečnost.** PIN a kód karty jsou jen `SecretStr` vstupy. Výstup říká jen `maPin` / `maKartu`. Chybné přihlášení má jednu zprávu bez dat. Session se při přihlášení maže a vyřazený uživatel přijde o session při dalším požadavku. Přepsání velikosti STAT místa smí jen TECH/ADMIN s důvodem. Role ADMIN si nemůže odebrat správu uživatelů.
- **Souběh a idempotence.** Všechny skladové příkazy (příjem, uskladnění, výdej, přesun, blokace, dokončení inventury) mají povinné `requestId` a test opakování.
- **Výdej s `ocekavanyStavKs`.** Výdej ověří stav, který obsluha viděla. Jiný stav vrátí `CONCURRENT_CHANGE` místo výdeje z cizího stavu.
- **Srozumitelné chyby.** Chyby validace jsou česky a u pole. Doménové chyby mají kód i větu pro skladníka, např. „Box BPLE038 není volný: zásoba na BPLE038-I.“
- **Dluh podle plánu.** Splaceno TD-08 (migrace 004), TD-09, TD-12 a TD-15. TD-01 má harness (`tests/integrace`) se 7 testy, které se spustí, jakmile bude `HoufekSklad_TEST`. Pojistky: název musí obsahovat TEST a PowerKey je zakázaný.

## Verdikt

**Schváleno pro bránu K1** (zmrazení kontraktů) s podmínkou, že vlastníci ostrovů projdou svou sekci 7.x a potvrdí výchozí řešení označená Q-xx. S-15 rozhodnout před fází 1, protože mění dekorátor dvou operací, ne kontrakt.

## Doplněk (2. 11. 2026)

Při srovnání dokumentů s kódem se našel jeden nesoulad v dokumentaci. Kód se neměnil.

| # | Soubor | Řádek | Problém → oprava | Závažnost | Test |
|---|---|---|---|---|---|
| CR-33 | `README.md`, `docs/technicky-dluh.md`, `docs/vyvoj.md` | 13 | README a hlavička této revize uváděly 75 endpointů. Kód jich má 73 (ostrovy B–G), s Platformou 77. Plán dluhu a příručka navíc označovaly zmrazení kontraktů jako bránu G2, správně je to K1 (G2 jsou rozhodnutí pro ostrov E). → Opraveno. Počty v README teď hlídá test. | 🟢 | `test_pocty_endpointu_v_readme` |

Snímek kontraktů (`kontrakty/openapi.json`, `kontrakty/rozhrani.json`) je od 2. 11. uložený se všemi 79 operacemi (73 ostrovů, 4 Platformy, `/api/docs` a `/api/openapi.json`) a s rozhraními ostrovů. Kontrola P10 tak hlídá i ostrovy, ne jen Platformu. Do brány K1 ho smí přeuložit P1 (`python -m nastroje.kontrakty uloz`), například po rozhodnutí Q-xx pro E a F.
