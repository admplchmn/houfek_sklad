# HOUFEK Sklad

Skladový systém HOUFEK a.s. eviduje:
- strukturu skladu (pracoviště → regál → úroveň → box → pozice) a díly;
- zásobu na pozicích;
- skladové operace z PDA a PC: příjem, výdej, přesun, blokace, inventura;
- přehledy (sken, karta dílu, rozložení úrovně, monitoring).

Technologie: Flask + Microsoft SQL Server. Aplikace je jeden celek rozdělený na 8 **ostrovů**, které píše 4–6 programátorů souběžně. Spojují je pevná pravidla API (P1–P11).

**Stav (3. 11. 2026):** fáze 0 hotová, kontrakty připravené k bráně K1.
- Platforma je hotová.
- Ostrovy B–G mají hotový HTTP kontrakt: 73 endpointů (B 13, C 24, D 10, E 11, F 6, G 9) a čistá pravidla
  s testy a kostru služeb nad vzorovými daty; se 6 operacemi Platformy je ve snímku 79 operací.
- Projekt je zkontrolovaný proti obrázkům zadání kap. 5–21 ([kontrolní seznam](docs/soulad-se-zadanim.md)).
- Snímek kontraktů v `kontrakty/` je kandidát pro bránu K1. Do zmrazení ho smí přeuložit jen P1, potom se kontrakty jen přidávají.
- Migrace 001–004 jsou připravené. Spustí je testovací SQL Server v Dockeru (`docker-compose.yml`), zatím je ověřil jen statický rozbor.
- CI běží na GitHub Actions (`.github/workflows/ci.yml`): předběžné kontroly a druhý job s SQL Serverem 2022. První běh padl na validaci workflowu, opraveno – zelenou zatím nemáme.
- Čas se ukládá v **UTC** (`DATETIME2`, `SYSUTCDATETIME()`, `platforma.kontrakty.teď()`), najevo jde pražský čas. Rozhodnutí vedoucího 3. 11., splácí TD-11.
- Další krok: fáze 1 podle [rozdělení práce](docs/rozdeleni-prace.md). Pravidla pro programátory i AI agenty jsou v [AGENTS.md](AGENTS.md).

Otevřené body: [technický dluh](docs/technicky-dluh.md). Uzavřené záznamy (code review 26. 10. a 1. 11.) jsou ve složce [jiz_nepotrebne](jiz_nepotrebne/README.md).

## Rychlý start (bez databáze, ~5 min)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-vyvoj.txt
python -m nastroje.over_vse          # testy, pravidla ostrovů, kontrakty, ruff → „Všechny kontroly prošly.“
$env:HOUFEK_VYVOJ = "1"
flask --app app run --debug          # bez HOUFEK_DB_SERVER: kostra nad dočasnou sqlite, nic se neukládá
```

Pak otevřete http://localhost:5000/api/docs (Swagger) nebo http://localhost:5000/ui/vyvoj. Nejdřív `POST /api/system/vyvojove-prihlaseni` s `{"uzivatelId": 1, "kodRole": "ADMIN"}`, potom libovolný endpoint. Vzorová data popisuje hlavička `ukazky.py` každého ostrova.

S testovacím SQL Serverem v Dockeru (Docker Desktop, **nikdy PowerKey**):

```powershell
copy .env.priklad .env                # vyplnit HOUFEK_TEST_DB_SERVER=localhost a HOUFEK_TEST_DB_HESLO
docker compose up -d                  # SQL Server 2022 Developer na localhost:1433
python -m nastroje.testovaci_db       # založí HoufekSklad_TEST a provede migrace 001–004
python -m nastroje.over_vse           # teď proběhnou i integrační testy proti SQL Serveru
```

Podrobný postup, běh aplikace nad databází a vývojový uživatel: [docs/vyvoj.md](docs/vyvoj.md), sekce 1.1.

## Dokumentace

| Dokument | Pro koho | Obsah |
|---|---|---|
| [AGENTS.md](AGENTS.md) | programátoři, AI agenti | závazná pravidla práce a psaní kódu, hranice ostrova, odevzdání (`CLAUDE.md` ho načte agentovi Claude Code) |
| [docs/rozdeleni-prace.md](docs/rozdeleni-prace.md) | vedoucí, programátoři, agenti | krok 0, kdo dělá který ostrov, jak pracovat nezávisle, zadání fáze 1, scénáře T01–T33 |
| [docs/vyvoj.md](docs/vyvoj.md) | programátoři | prostředí, struktura ostrova, běžné úkoly krok za krokem, pravidla P1–P11, koho se ptát |
| [docs/architektura.md](docs/architektura.md) | všichni | požadavky a odhad zátěže, komponenty, tok příkazu, chyby a opakování, spolehlivost, kompromisy |
| [docs/adr/](docs/adr/README.md) | vedoucí, programátoři | 12 architektonických rozhodnutí s variantami a důsledky |
| [docs/provoz.md](docs/provoz.md) | IT, DBA | instalace (IIS, SQL Server), proměnné prostředí, nová verze a návrat, incidenty, zálohy, eskalace |
| [docs/technicky-dluh.md](docs/technicky-dluh.md) | vedoucí, P1 | registr dluhu s prioritami a plán splácení |
| [docs/migrace-xlsm.md](docs/migrace-xlsm.md) | P4 (ostrov H), vedoucí | rozbor vzorku XLSM od firmy, mapování sloupců, nálezy v datech, import a doplnění údajů v aplikaci |
| [docs/soulad-se-zadanim.md](docs/soulad-se-zadanim.md) | vedoucí, všichni | kontrolní seznam souladu s obrázky zadání kap. 5–21: opravy, rozhodnutí vedoucího, výklad, rozpory, odkud se berou data vzorových obrazovek |
| [jiz_nepotrebne/](jiz_nepotrebne/README.md) | jen pro dohledání | uzavřené záznamy, které už pro práci nejsou potřeba: code review 26. 10. (21 nálezů) a 1. 11. (11 nálezů), vše opraveno |

Zadání, analýza a pravidla mezi ostrovy jsou ve dvou sdílených dokumentech:
- „HOUFEK – Skladový systém: analýza zadání a osnova aplikace“;
- „HOUFEK – Ostrovy aplikace a konvence API“.

## Ostrovy

| Ostrov | Složka | Vlastník | Stav fáze 0 |
|---|---|---|---|
| A Platforma | `app/platforma` | P1 | hotovo: transakce, `requestId`, chyby, obálka, přihlášení, audit, migrace (+ zámek upgradu), OpenAPI, UI základ, běh bez DB |
| B Identita | `app/ostrovy/identita` | P1 | kontrakt 13 endpointů; pravidla PINu a rolí, hash argon2, hák `overeni_kontextu`; kostra |
| C Struktura | `app/ostrovy/struktura` | P2 | kontrakt 24 endpointů; parser, kódy a řady boxů, pořadí, šablona C1–C7, SVG 17.1, zámky hotové; kostra |
| D Díly | `app/ostrovy/dily` | P4 | kontrakt 10 endpointů; normalizace čísla a číselníků, potřeba místa V6 hotové; kostra |
| E Sklad | `app/ostrovy/sklad` | P3 | kontrakt 11 endpointů; kontroly příjmu, výdeje a přesunu, upozornění zásoby, kandidáti hotové; kostra |
| F Inventura | `app/ostrovy/inventura` | P5 | kontrakt 6 endpointů; vyhodnocení, přepočet, plán korekcí hotové; kostra |
| G Přehledy | `app/ostrovy/prehledy` | P6 | kontrakt 9 endpointů; barvy, souhrn, laser (Q-22) hotové; kostra přes rozhraní B–E |
| H Migrace | `app/ostrovy/migrace` | P4 | kostra CLI; po vzorku XLSM |

Vzor celé svislé cesty (endpoint → služba → doména → repozitář → tabulka) je `app/ostrovy/_sablona`. Funkce rozhraní označené `KOSTRA (fáze 0)` vracejí vzorová data a v provozním režimu selžou. Vlastník je nahradí **beze změny podpisu**.

## Přispívání

1. Pracujte jen ve složce svého ostrova. Platformu, `app/ostrovy/__init__.py`, `sql/` a `kontrakty/` mění P1 (`CODEOWNERS.priklad`).
2. Před pull requestem `python -m nastroje.over_vse`. Test pravidel odmítne zápis do cizích tabulek, čtení cizích tabulek mimo `v_*`, nepovolený import i měnitelná DTO.
3. Rozhodnutí, které nejde vyčíst z kódu, zapište jako ADR ([šablona](docs/adr/sablona.md)).
4. Hesla nikdy do repozitáře: `.env` je v `.gitignore`, provoz čte `HOUFEK_KONFIGURACE_SOUBOR` ([provoz.md](docs/provoz.md)).
