# Práce s autonomními agenty

**Stav k:** 4. 11. 2026 · **Pro:** vedoucího projektu, Claude v Projektu (dispečer) a agenty Claude Code na JupyterHubu

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
- čtení: https://github.com/admplchmn/houfek_sklad.git (veřejný)
- zápis: git@github.com:admplchmn/houfek_sklad.git
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
   (repozitář už máš: `git fetch origin`), pak `git remote set-url --push origin git@github.com:admplchmn/houfek_sklad.git`
   a `git switch -c <větev> origin/main`
2. `pip install -r requirements-vyvoj.txt`; práce, testy, `python -m nastroje.over_vse`
3. `git push -u origin <větev>`
4. Výsledek CI: `curl -s "https://api.github.com/repos/admplchmn/houfek_sklad/actions/runs?branch=<větev>&per_page=1"`.
   Počkej, až je `status` = `completed`. Když `conclusion` není `success`, otevři joby
   (`…/actions/runs/<id>/jobs`), oprav a pushni znovu. Nejvýš 3 kola, pak skonči a napiš proč.
5. Pull request: `gh pr create --base main --head <větev> --fill`, když je `gh` přihlášené;
   jinak do zprávy dej odkaz https://github.com/admplchmn/houfek_sklad/pull/new/<větev>

## Závěrečná zpráva (do popisu PR i jako odpověď)
- co se změnilo, jedním odstavcem;
- testy a výsledek CI (odkaz na běh);
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
- akceptační kritéria ověřitelná testem; odkazuj na kapitolu zadání;
- nelogický nebo nejasný scénář ze zadání (Q-xx) nevymýšlej, zeptej se vedoucího projektu;
- simplicity first: nejmenší změna, která úkol splní.

Když vedoucí vloží výsledek agenta nebo výpis z CI, posuď ho a případně napiš opravné zadání.
```

## Nastavení GitHubu (jednou, vedoucí projektu)

Repozitář je veřejný, takže pravidla i GitHub Actions jsou zdarma.

1. **Settings → Rules → Rulesets → New branch ruleset**, název „main“, cíl „Default branch“:
   - Restrict deletions;
   - Block force pushes;
   - Require a pull request before merging;
   - Require status checks to pass: „Předběžné kontroly (bez DB)“ a „Integrační testy (SQL Server 2022)“, k tomu „Require branches to be up to date before merging“;
   - Bypass list: Repository admin, tedy jen vy.
2. **Settings → General → Pull Requests:**
   - jen „Allow squash merging“;
   - zapnout „Automatically delete head branches“.
3. **Agenti a přístup:**
   - každý agent na JupyterHubu má SSH klíč s právem zápisu, nebo token omezený na tento repozitář s dobou platnosti;
   - hesla k databázím a přístupy k PowerKey na JupyterHub nepatří.
