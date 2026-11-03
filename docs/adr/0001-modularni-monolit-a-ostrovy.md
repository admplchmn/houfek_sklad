# ADR-0001: Modulární monolit rozdělený na 8 ostrovů

**Stav:** Přijato
**Datum:** 2026-10-26
**Rozhodují:** vedoucí projektu

## Kontext

Jednu skladovou aplikaci (Flask + SQL Server, web a terminály PDA) píše 4–6 programátorů souběžně. Potřebujeme:

- **Souběžná práce bez šlapání si na prsty:** každý programátor má svůj kód, své tabulky a své testy.
- **Silná konzistence skladu:** jedna operace často mění strukturu i zásobu najednou (přesun boxu, výdej s blokací). Musí proběhnout v **jedné** databázové transakci.
- **Jednoduché spojení:** nový ostrov se zapojí jedním řádkem.
- **Malá zátěž, malý provoz:** odhad je v [architektuře](../architektura.md), sekce 2.4. Aplikaci spravuje interní IT bez DevOps týmu.

## Rozhodnutí

Jedna aplikace (jeden proces, jedno nasazení, jedna databáze) rozdělená na 8 **ostrovů** s pevnými hranicemi podle dokumentu „HOUFEK – Ostrovy aplikace a konvence API“:

| Ostrov | Prefix | Závisí na (kromě Platformy) |
|---|---|---|
| A Platforma | `system` | – |
| B Identita | `identita` | – |
| C Struktura | `struktura` | – (čte pohled `v_ObsahPozice` ostrova E) |
| D Díly | `dily` | – (čte pohled `v_ObsahPozice` ostrova E) |
| E Sklad | `sklad` | C, D |
| F Inventura | `inventura` | C, D, E |
| G Přehledy | `prehledy` | B, C, D, E |
| H Migrace | `migrace` (jen CLI) | C, D, E |

Hranice drží pravidla P1–P11. P1–P4 a P6 hlídá automaticky test `tests/test_pravidla_ostrovu.py`:
- zápis jen do vlastních tabulek,
- cizí data jen přes `rozhrani.py` nebo pohledy `v_*`,
- import z cizího ostrova jen `rozhrani` a jen ve směru mapy výše,
- rozhraní bez Flasku,
- neměnná DTO.

Spojení ostrovů = jeden řádek v `app/ostrovy/__init__.py` (`OSTROVY = [...]`).

## Zvažované možnosti

### Možnost A: Modulární monolit s ostrovy (zvoleno)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká až střední – jeden proces, hranice jsou konvence hlídané testem |
| Náklady | Jeden server aplikace, jedna databáze |
| Škálovatelnost | Svislá; pro odhadovanou zátěž s velkou rezervou |
| Znalost týmu | Vysoká – běžná Flask aplikace |

**Pro:** jedna transakce přes ostrovy (volající předává `spoj`), jedno nasazení, žádná síť mezi moduly, jednoduché ladění.
**Proti:** hranice drží jen kázeň a testy. Ostrovy nejde nasadit ani škálovat samostatně. Změny schématu je třeba koordinovat (P11).

### Možnost B: Mikroslužby

| Hledisko | Hodnocení |
|---|---|
| Složitost | Vysoká – síť, verze API, distribuované transakce (sagy) |
| Náklady | Víc procesů, kontejnery nebo orchestrace, monitoring každé služby |
| Škálovatelnost | Vodorovná po službách – tady nepotřebná |
| Znalost týmu | Nízká až střední |

**Pro:** nezávislé nasazení a technologie po službách.
**Proti:** přesun boxu se zámky pozic a zápisem pohybu by se rozpadl do ságy s kompenzacemi. Interní IT by provozovalo 6–8 služeb. Zátěž to neospravedlňuje.

### Možnost C: Klasický vrstvený monolit bez doménových hranic

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nejnižší na začátku, roste s každou funkcí |
| Náklady | Stejné jako A |
| Škálovatelnost | Stejná jako A |
| Znalost týmu | Vysoká |

**Pro:** nejrychlejší start, žádná pravidla navíc.
**Proti:** šest lidí upravuje stejné modely a služby, takže vznikají konflikty při slučování a skryté vazby. Nikdo nemá jasnou zodpovědnost za data.

## Rozbor kompromisů

Rozhodla atomicita skladových operací a velikost týmu. B by řešila problém, který nemáme (nezávislé škálování), za cenu problému, který mít nechceme (konzistence přes síť). C neřeší souběžnou práci šesti lidí. A dává oddělení práce jako B s jedinou transakcí jako C. Cenou je kázeň a tu vynucuje test, ne dobrá vůle.

## Důsledky

- **Snazší:**
  - souběžný vývoj (vlastník = složka + tabulky),
  - zapojení ostrova jedním řádkem,
  - transakce přes ostrovy (P5: transakci otevírá jen služba, která příkaz řídí),
  - jedno nasazení.
- **Těžší:**
  - každá změna cizího rozhraní nebo pohledu jde přes jeho vlastníka a schválení P1 (`CODEOWNERS`),
  - po zmrazení kontraktů jen přidáváme (P10).
- **Přehodnotit:**
  - kdyby Přehledy potřebovaly samostatný výkon (čtecí replika), pohledy `v_*` jsou připravený šev (ADR-0006),
  - kdyby vznikla druhá aplikace nad stejnými daty, ostrov se dá vyčlenit za jeho `rozhrani` jako HTTP služba.

## Úkoly

1. [x] Kostra ostrovů, šablona `_sablona`, test pravidel P1–P4 a P6.
2. [ ] Po založení repozitáře přejmenovat `CODEOWNERS.priklad` a doplnit účty (TD-02).
3. [ ] CI spouští `python -m nastroje.over_vse` na každý pull request (TD-02).
