# ADR-0010: `FullBoxKlic` jako uložený sloupec (Q-03)

**Stav:** Přijato na bráně G1, potvrzeno 2. 11. 2026
**Datum:** 2026-10-26 (rozhodnutí G1)
**Rozhodují:** vlastník procesu skladu (potvrzení), vedoucí projektu (G1)
**Souvisí:** analýza Q-03, schéma `001_schema_g1.sql` (Δ9)

## Kontext

Box má trvalou identitu `KodBoxu` (např. `BPLE037`) na štítku a adresu v regálu. Adresa se skládá z kódů nadřazených úrovní:

`FullBoxKlic` = `KodFirmy-KodPracoviste-KodRegalu-KodUrovne-KodBoxu`, např. `HOUFEK-PLE-R01-U03-BPLE037`.

Zadání používá úplný klíč při skenování a v přehledech. Otázka Q-03 zněla, zda ho počítat, nebo ukládat. Rozhodnutí G1 se odchyluje od návrhu analýzy (jen pohled):

- `FullBoxKlic` zůstává **uložený sloupec**;
- přepočítává se v transakci strukturálního přesunu boxu;
- identita boxu = `BoxID` + `KodBoxu`;
- záložní varianta je výpočet jen v pohledu;
- finální slovo má vlastník procesu.

## Rozhodnutí

- `Box.FullBoxKlic VARCHAR(150) NOT NULL UNIQUE`, povolené znaky `0-9 A-Z -`.
- **Kdo ho mění.** Nastavuje ho jen ostrov C (Struktura) při založení boxu. Přepočítává ho jen při strukturálním přesunu boxu nebo změně kódu nadřazené úrovně, **v téže transakci** a pod zámky P8.
- **Vazby.** Vazby mezi tabulkami a z jiných ostrovů jdou přes `BoxID`, nikdy přes `FullBoxKlic`. `FullBoxKlic` slouží jen k vyhledání při skenu a k zobrazení.
- **Hlídání shody.** `v_KontrolaIntegrity` hlásí `FULLBOXKLIC_NESEDI`, když uložená hodnota neodpovídá adrese spočítané ze struktury.

## Zvažované možnosti

### Možnost A: Uložený sloupec + přepočet v transakci přesunu (zvoleno na G1)

| Hledisko | Hodnocení |
|---|---|
| Složitost | Střední – přepočet na jednom místě v ostrově C |
| Náklady | Jeden sloupec a unikátní index |
| Škálovatelnost | Sken = vyhledání v indexu, bez spojení přes hierarchii |
| Znalost týmu | Vysoká |

**Pro:** rychlé a jednoduché vyhledání při skenu. Unikátnost adresy hlídá databáze.
**Proti:** riziko rozjetí, kdyby někdo změnil kód regálu nebo úrovně bez přepočtu. Proto ho smí měnit jen C a hlídá ho kontrola integrity.

### Možnost B: Jen výpočet v pohledu (`v_Misto`), záložní varianta

| Hledisko | Hodnocení |
|---|---|
| Složitost | Nízká – nic se nepřepočítává |
| Náklady | Žádné úložiště |
| Škálovatelnost | Sken = spojení přes 5 tabulek nebo indexovaný pohled (omezení SQL Serveru) |
| Znalost týmu | Vysoká |

**Pro:** nemůže se rozjet.
**Proti:** vyhledání podle adresy bez indexu. Unikátnost adresy by se musela hlídat jinak.

### Možnost C: Počítaný sloupec (`PERSISTED`)

| Hledisko | Hodnocení |
|---|---|
| Složitost | – |
| Náklady | – |
| Škálovatelnost | – |
| Znalost týmu | – |

**Nejde:** počítaný sloupec smí číst jen sloupce téhož řádku a adresa čte kódy z nadřazených tabulek.

## Rozbor kompromisů

A kupuje rychlý sken a databázovou unikátnost za cenu přepočtu, který je na jednom místě a hlídá ho kontrola integrity. B je bezpečnější proti rozjetí, ale pomalejší a bez unikátnosti. Při přechodu z A na B se mění jen ostrov C a pohled `v_Misto`, ostatní ostrovy používají `BoxID`.

## Důsledky

- **Snazší:** sken adresy a tisk štítků bez spojení přes hierarchii.
- **Těžší:** přejmenování kódu regálu nebo úrovně = přepočet všech boxů pod ním v jedné transakci (ostrov C). Hromadné přejmenování mimo aplikaci (SSMS) je zakázané.
- **Přehodnotit:** pokud vlastník procesu nepotvrdí, přejít na B (sloupec zrušit nebo nechat jen jako mezipaměť).

## Úkoly

1. [x] Sloupec, unikátní index, CHECK, kontrola `FULLBOXKLIC_NESEDI` (001, Δ9).
2. [x] Potvrzení (2. 11. 2026, dokument „Technická revize“).
3. [ ] Ostrov C: přepočet při přesunu boxu (`POST /api/struktura/boxy/{id}/presun`) a při změně kódu nadřazené úrovně + integrační test (TD-01).
