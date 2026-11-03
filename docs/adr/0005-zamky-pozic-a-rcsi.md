# ADR-0005: Souběh – protokol zámků pozic a READ_COMMITTED_SNAPSHOT

**Stav:** Přijato (vedoucí projektu, 2. 11. 2026)
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu, DBA HOUFEK (zapnutí RCSI)
**Souvisí:** pravidlo P8; code review CR-12, CR-13

## Kontext

- Na stejný box nebo pozici můžou ve stejné chvíli sahat zaskladnění, výdej, přesun i inventura z různých terminálů.
- Zadání vyžaduje platná pravidla obsahu: kapacita, jeden díl na pozici u statických míst, blokace.
- Kontrola „vejde se“ a zápis musí proběhnout **bez mezery**, do které by se vešel jiný terminál.
- SQL Server ve výchozím režimu READ COMMITTED se zamykáním při čtení blokuje zápisy čtením. Obrazovka monitoringu by tak brzdila terminály.
- Zámky brané v libovolném pořadí vedou k deadlockům, například přesun A→B a současně B→A.

## Rozhodnutí

1. **Protokol zámků (P8).**
   - Každý příkaz, který mění obsah místa, zavolá na **začátku** jednou `struktura.rozhrani.zamkni_mista(spoj, ids)` pro všechna dotčená místa. Teprve potom čte obsah a kontroluje pravidla.
   - Zámek je `UPDLOCK, HOLDLOCK` na řádcích `VnitrniPoziceBoxu` do konce transakce, **vzestupně podle ID**:
     - do 20 pozic po jednom řádku (pořadí je zaručené),
     - nad 20 po dávkách `IN (…)` po 1 000 (limit 2 100 parametrů); zbytkové riziko deadlocku řeší bod 4.
   - Jinak se zámky neberou.
2. **READ_COMMITTED_SNAPSHOT ON** pro databázi aplikace (jednorázový ruční krok DBA, [provoz.md](../provoz.md)). Čtení (přehledy, vyhledávání) neblokuje zápisy a zápisy neblokují čtení.
3. **Omezené čekání.** `SET LOCK_TIMEOUT 5000` na každém spojení. Chyba 1222 → `CONCURRENT_CHANGE` „Místo právě zpracovává někdo jiný. Zkuste to za chvíli znovu.“ Nic se nezapsalo.
4. **Deadlock** (1205) → `@transakce` zopakuje celou operaci nejvýše 2× s náhodným odstupem 50–150 ms × pokus, pak `CONCURRENT_CHANGE`.
5. **`SET XACT_ABORT ON`** – jakákoli chyba zruší celou transakci.

**Proč je čtení po zámku správné i s RCSI.**
1. Každý zapisovatel obsahu místa musí nejdřív vzít jeho zámek (P8).
2. Kdo zámek drží, má jistotu, že předchozí zapisovatel už potvrdil.
3. Příkaz `SELECT` spuštěný po získání zámku proto vidí jeho data.

Podmínkou je, že **nikdo nezapisuje obsah místa bez zámku**. Proto zápis do `ObsahPozice` smí jen ostrov E (P1) a revize hlídá volání `zamkni_mista`.

## Zvažované možnosti

### Možnost A: Pesimistický protokol zámků + RCSI (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – jedno pravidlo (zamknout první, pak číst), jedna funkce |
| Náklady | RCSI: verze řádků v tempdb (malé při této zátěži) |
| Škálovatelnost | Zámky na úrovni pozice, souběh mezi různými místy neomezený |
| Znalost týmu | Střední – hinty T-SQL jsou v jedné funkci |

**Pro:** konflikt se projeví hned na začátku operace, ne až při zápisu. Pořadí zámků je dané, takže deadlocky jsou výjimka. Přehledy neblokují terminály.
**Proti:** pravidlo „zamknout první“ musí dodržet každý příkaz ostrova E. Přidání RCSI je ruční krok DBA s krátkým výhradním přístupem k databázi.

### Možnost B: Optimistický souběh (`rowversion`, kontrola při zápisu)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – každý zápis s podmínkou `WHERE Verze = ?`, opakování ve službách |
| Náklady | Sloupec navíc v tabulkách obsahu |
| Škálovatelnost | Dobrá při řídkých konfliktech |
| Znalost týmu | Střední |

**Pro:** žádné držení zámků.
**Proti:** u oblíbeného boxu (častý výdej) konflikty nejsou řídké. Kontrola kapacity přes víc řádků (všechny díly v boxu) se špatně vyjadřuje jednou verzí. Konflikt se ukáže až po práci uživatele.

### Možnost C: SERIALIZABLE pro všechny příkazy

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká v kódu (jedno nastavení) |
| Náklady | Rozsahové zámky, víc deadlocků |
| Škálovatelnost | Horší – zámky i na sousední klíče |
| Znalost týmu | Střední |

**Pro:** správnost bez přemýšlení o pořadí.
**Proti:** zamyká víc, než je potřeba (rozsahy indexů). Deadlocky jsou častější a hůř předvídatelné.

### Možnost D: Aplikační zámek (`sp_getapplock` na kód místa nebo zámek v paměti)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká až střední |
| Náklady | Žádné |
| Škálovatelnost | `sp_getapplock` dobrá; paměť nefunguje pro víc procesů |
| Znalost týmu | Nízká |

**Pro:** zámek nezávislý na datech.
**Proti:** zámek v paměti porušuje P9 (víc procesů waitress). `sp_getapplock` je neviditelný v běžných nástrojích DBA a pojmenování zámků je další konvence k dodržování.

## Rozbor kompromisů

A zamyká přesně to, co se mění (řádky pozic), v daném pořadí a viditelně pro DBA. B by přenášela konflikty na uživatele až po skenu. C zamyká víc, než je nutné. D řeší totéž co A, ale mimo data. RCSI je nutná součást A, ne volitelná optimalizace. Bez ní by přehledy (ostrov G) čekaly na zámky terminálů a naopak.

## Důsledky

- **Snazší:**
  - pravidla kapacity se kontrolují obyčejným `SELECT` po zámku;
  - přehledy můžou číst kdykoli;
  - uživatel dostane srozumitelnou hlášku do 5 s místo zamrzlého terminálu.
- **Těžší:**
  - příkaz, který zapomene zamknout, funguje v testu i při malém provozu a selže až při souběhu. Hlídá to revize a integrační test souběhu (TD-01);
  - inventura nad stovkami pozic drží hodně zámků najednou. Ostrov F zvažuje zámky po regálech.
- **Přehodnotit:**
  - pokud monitoring ukáže časté `CONCURRENT_CHANGE` na stejném místě, zvážit frontu operací pro toto místo;
  - pokud dávkové zamykání nad 20 pozic vede k deadlockům, zamykat po jedné.

## Úkoly

1. [x] `zamkni_mista` (CR-13), `LOCK_TIMEOUT` a `XACT_ABORT` (CR-12), mapování 1222 a 1205.
2. [ ] DBA: `ALTER DATABASE … SET READ_COMMITTED_SNAPSHOT ON` na vývojové, testovací i provozní databázi ([provoz.md](../provoz.md)).
3. [ ] Integrační test: dva přesuny A→B a B→A souběžně, žádný deadlock; čekání nad 5 s vrátí `CONCURRENT_CHANGE` (TD-01).
4. [ ] Kontrolní seznam revize ostrova E: „zamkni_mista před prvním čtením obsahu“.
