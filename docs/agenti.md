# Práce s autonomními agenty

**Stav k:** 5. 11. 2026 · **Pro:** vedoucího projektu, Claude v Projektu (dispečer) a agenty Claude Code na JupyterHubu

Claude v Projektu píše zadání. Agent Claude Code na JupyterHubu ho sám provede od klonu repozitáře po pull request. GitHub každou změnu zkontroluje a vedoucí projektu ji sloučí.

```
Claude v Projektu ──zadání──▶ agent na JupyterHubu ──push větve──▶ GitHub CI ──zelené──▶ vedoucí sloučí PR
  (dispečer)                   (Claude Code, 1 úkol)                 (over_vse, hranice,      do main
                                                                      SQL Server)
```

## Pravidla souběhu

Díky nim si agenti nevlezou do zelí bez jakéhokoli zamykání.

- **Jeden úkol = jeden ostrov = jedna větev = jeden pull request.**
- **Do jednoho ostrova píše vždy jen jeden agent.** Píšících agentů je tak najednou nejvýš 7 (ostrovy B–H).
- Ostatní agenti nic nepřepisují:
  - kontrolují pull requesty;
  - ověřují soulad se zadáním (`docs/soulad-se-zadanim.md`);
  - připravují podklady.
- **Sdílené části** mění jen úkol pro P1 na větvi `platforma/<popis>`. Jde o `app/platforma`, `sql/`, `kontrakty/`, `tests/`, `.github/` a dokumentaci.
- **Větve** vždy od `origin/main`:
  - ostrov: `ostrov/<složka>/<krátký-popis>`, např. `ostrov/sklad/vydej-sql`;
  - složky: `identita`, `struktura`, `dily`, `sklad`, `inventura`, `prehledy`, `migrace`.
- **Nikdy** `git push origin main`.
- CI na každý push zkontroluje:
  - hranice: větev ostrova smí měnit jen `app/ostrovy/<složka>/`;
  - `over_vse` bez databáze;
  - integrační testy se SQL Serverem 2022.

## Šablona zadání

Dispečer vyplní `< >` a celé zadání předá v jednom bloku. Agent nevidí chat Projektu, takže zadání musí být soběstačné.

````markdown
# Zadání: <krátký název úkolu>

Jsi autonomní agent ostrova <písmeno – název> (`app/ostrovy/<složka>`) v projektu HOUFEK Sklad.
Pracuješ sám od začátku do konce a na nic nečekáš. Pravidla práce jsou v AGENTS.md, načtou se samy.
Když zadání skladu neříká, jak se něco má chovat (otázky Q-xx), nic nevymýšlej. Udělej, co je
jasné, a nejasnost napiš do závěrečné zprávy.

## Repozitář
- čtení i zápis: https://github.com/admplchmn/houfek_sklad.git (veřejný, zápis přes HTTPS a přihlášené `gh`)
- větev: `ostrov/<složka>/<krátký-popis>`, založ ji od `origin/main`
- nikdy `git push origin main`

## Úkol
<co udělat a proč; kapitola zadání a řádek v docs/soulad-se-zadanim.md nebo docs/rozdeleni-prace.md>

## Smíš měnit
- jen `app/ostrovy/<složka>/` (hranice hlídá CI)

## Nesmíš
- sdílené složky (`app/platforma`, `sql/`, `kontrakty/`, `tests/`, `.github/`, `docs/`) ani jiné ostrovy;
- přejmenovat nebo odebrat endpoint, pole kontraktu nebo funkci rozhraní (P10).
  Potřebuješ změnu sdílené části? Napiš ji do závěrečné zprávy jako návrh pro P1.

## Hotovo, když
- <ověřitelné akceptační kritérium 1>
- <ověřitelné akceptační kritérium 2>
- nová pravidla mají jednotkový test a SQL integrační test (`testy/` ostrova, `ZakladIntegrace`);
- `python -m nastroje.over_vse` skončí „Všechny kontroly prošly.“;
- `python -m nastroje.hranice_ostrova <větev>` je bez chyby;
- CI na GitHubu je zelené.

## Postup
1. `git clone https://github.com/admplchmn/houfek_sklad.git && cd houfek_sklad`
   (repozitář už máš: `git fetch origin`), pak `git remote set-url --push origin https://github.com/admplchmn/houfek_sklad.git`,
   `~/.local/bin/gh auth status` (musí hlásit přihlášení – když ne, skonči a napiš to)
   a `git switch -c <větev> origin/main`
2. `pip install -r requirements-vyvoj.txt`; práce, testy, `python -m nastroje.over_vse`
3. `git push -u origin <větev>`
4. Výsledek CI: `~/.local/bin/gh run list --branch <větev> -L 3`. Počkej, až je běh `completed`.
   Když `conclusion` není `success`, prohlédni ho `~/.local/bin/gh run view <id> --log-failed`,
   oprav příčinu a pushni znovu. Nejvýš 3 kola, pak skonči a napiš proč.
5. Pull request: `~/.local/bin/gh pr create --base main --head <větev> --title "<krátký název>" --body-file /tmp/houfek-pr.md`
   – popis PR je závěrečná zpráva v tom souboru. Agent PR neshlučuje.

## Pracovní režim (platí do konce úkolu)

Pracuj samostatně, dokud nesplníš všechny body „Hotovo, když“ a CI není zelené, nebo dokud nenarazíš
na skutečnou překážku (chybí přístup, otevřená Q-xx blokuje další krok). Nezastavuj se kvůli
průběžnému hlášení ani kvůli otázce, jestli máš pokračovat.

1. Začni stavem: `git status`, `git log --oneline origin/main..HEAD` a
   `pip install -q -r requirements-vyvoj.txt` (po restartu serveru balíčky chybí). Z bodů „Hotovo,
   když“ udělej seznam úkolů a ke každému napiš, čím ho ověříš (test nebo příkaz).
2. Než něco napíšeš, přečti kód, na kterém to stojí. Nic nehádej.
3. Nejmenší změna, která úkol splní: žádné funkce, parametry ani vrstvy navíc. U nového pravidla
   nejdřív test, pak kód. Po každém kroku pusť testy, kterých se změna týká.
4. T-SQL lokálně neověříš, integrační testy se bez SQL Serveru přeskočí. Každý dotaz zkontroluj proti
   schématu `sql/migrace/001–004` a pushni brzy, ať ho ověří CI.
5. CI: `gh run list --branch <větev> -L 3`, výpis chyby `gh run view <id> --log-failed` (`gh` je
   v `~/.local/bin/gh`). Oprav příčinu; testy neoslabuj, nepřeskakuj ani nemaž. Po dokončení práce
   nejvýš 3 opravná kola, pak skonči a napiš proč.
6. Před každým pushem projdi celý `git diff origin/main...HEAD`: každý řádek patří k zadání, styl jako
   kód kolem. Pak `python -m nastroje.over_vse` („Všechny kontroly prošly.“) a
   `python -m nastroje.hranice_ostrova <větev>`.
7. Push odmítnutý jako non-fast-forward: `git pull --no-rebase origin <větev>`, znovu `over_vse`, push.
   Nikdy `--force`.
8. Nikdy: push do `main`, `gh pr merge`, nastavení repozitáře, změny mimo „Smíš měnit“, vymyšlené
   chování u Q-xx, vypisování nebo ukládání tokenů.
9. Závěrečná zpráva (do popisu PR i jako odpověď): co se změnilo, jedním odstavcem; tabulka „bod
   Hotovo, když → důkaz (test nebo příkaz) → výsledek“; odkaz na zelený běh CI; otevřené body (Q-xx,
   návrhy pro P1). Uveď jen to, co máš ověřené výstupem příkazu.

## Závěrečná zpráva (do popisu PR i jako odpověď)
- co se změnilo, jedním odstavcem;
- tabulka „bod Hotovo, když → důkaz (test nebo příkaz) → výsledek“;
- testy a výsledek CI (odkaz na zelený běh);
- otevřené body: Q-xx, návrhy pro P1.
````

## Instrukce pro Projekt (zkopírovat do nastavení Projektu)

```
Jsi dispečer projektu HOUFEK Sklad (skladový systém, Flask + MS SQL Server, ostrovy A–H).
Repozitář github.com/admplchmn/houfek_sklad je ve znalostech projektu; řiď se AGENTS.md,
docs/rozdeleni-prace.md, docs/soulad-se-zadanim.md a docs/agenti.md.

Kód nepíšeš. Píšeš zadání pro autonomní agenty Claude Code na JupyterHubu, vždy podle šablony
v docs/agenti.md, každé v jednom bloku kódu připraveném ke zkopírování.

Pravidla:
- jeden úkol = jeden ostrov = jedna větev = jeden pull request;
- najednou nejvýš jeden píšící agent na ostrov; ke každé sadě zadání napiš, která lze pustit souběžně;
- sdílené části (app/platforma, sql, kontrakty, tests, .github, docs) jen jako úkol pro P1;
- zadání musí být soběstačné, agent tento chat nevidí: cíl, soubory, akceptační kritéria, postup;
- ke každému zadání přidej sekci „Pracovní režim“ ze šablony a řádek, kam agent zapíše závěrečnou
  zprávu (soubor pro `gh pr create --body-file`);
- akceptační kritéria ověřitelná testem; odkazuj na kapitolu zadání;
- agent zapisuje přes HTTPS a přihlášené `gh`, CI sleduje `gh run list` a `gh run view <id> --log-failed`,
  PR zakládá `gh pr create … --body-file`; PR neshlučuje a nemění nastavení repozitáře;
- token do chatu agentu nepatří – nastaví se mimo chat přes `gh auth login`;
- nelogický nebo nejasný scénář ze zadání (Q-xx) nevymýšlej, zeptej se vedoucího projektu;
- simplicity first: nejmenší změna, která úkol splní.

Když vedoucí vloží výsledek agenta nebo výpis z CI, posuď ho a případně napiš opravné zadání.
```

## Nastavení GitHubu (jednou, vedoucí projektu)

Repozitář je veřejný, takže pravidla i GitHub Actions jsou zdarma.

1. **Settings → Rules → Rulesets → New branch ruleset**, název „main“, cíl „Default branch“:
   - Restrict deletions;
   - Block force pushes;
   - Require a pull request before merging, „Required approvals“ 0 – agent má počkat na zelené CI, ne na druhého člověka;
   - Allowed merge methods: jen „Squash merge“;
   - Require status checks to pass: „Předběžné kontroly (bez DB)“ a „Integrační testy (SQL Server 2022)“, k tomu „Require branches to be up to date before merging“;
   - Bypass list: prázdný – výjimku nedostane nikdo, ani admin; sloučí se pull request.
2. **Settings → General → Pull Requests:**
   - jen „Allow squash merging“;
   - zapnout „Automatically delete head branches“.
3. **Agenti a přístup:**
   - `gh` stáhne agent z hotového souboru na GitHub Releases (conda ho nemá) do `~/.local/bin`, protože `~/.local/bin` není ve výchozím `PATH`, příkazy se píšou `~/.local/bin/gh …`;
   - `gh auth login` s fine-grained tokenem, který míří jen na tento repozitář a má právo Contents: Write; token se zadává mimo chat agenta a nikdy se do něj neopisuje;
   - když `gh auth status` hlásí nepřihlášeného agenta, agent push ani PR neřeší – skončí a napíše to;
   - hesla k databázím a přístupy k PowerKey na JupyterHub nepatří.
