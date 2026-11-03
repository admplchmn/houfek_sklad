# Pokyny pro programátory a AI agenty

Platí pro každého, kdo mění kód v tomto repozitáři, ať je to člověk, nebo agent. Je tu jen to závazné, podrobnosti jsou v odkazech.

## Než začneš

1. [docs/rozdeleni-prace.md](docs/rozdeleni-prace.md): najdi svůj ostrov. Je tam, co máš udělat, na čem stavíš a kdy je hotovo.
2. [docs/vyvoj.md](docs/vyvoj.md): prostředí, soubory ostrova, běžné úkoly krok za krokem, pravidla P1–P11 a konvence API.
3. `app/ostrovy/_sablona`: vzor celé cesty endpoint → služba → doména → repozitář. Piš stejně jako on a jako kód kolem.

## Hranice

- Měníš jen složku svého ostrova `app/ostrovy/<ostrov>/`. Platformu (`app/platforma`), `app/ostrovy/__init__.py`, `sql/`, `kontrakty/` a `tests/` mění jen P1, ty mu pošli návrh.
- Jiný ostrov voláš jen funkcemi z jeho `rozhrani.py` a cizí data čteš jen z pohledů `v_*`. Do cizích tabulek nepíšeš ani je nečteš.
- Endpointy, modely v `kontrakty.py`, funkce v `rozhrani.py` a sloupce pohledů se jen přidávají. Přejmenování nebo odebrání odmítne kontrola kontraktů (P10).
- Databáze PowerKey se zatím nepoužívá, ani pro testy. Napojení přijde později jako samostatné zadání.
- Hesla a přístupy nikdy do repozitáře (`.env` je v `.gitignore`).
- Když zadání neříká, jak má něco fungovat (otázky Q-xx, kódy a štítky, skladový proces), nic si nevymýšlej. Zeptej se vedoucího projektu a do té doby dělej jen to, co je jasné.

## Jak tvoje práce zapadne do ostatních

Všechny ostrovy jsou zapojené už teď (`app/ostrovy/__init__.py`). Když nezměníš podpisy funkcí rozhraní ani kontrakt API, tvoje práce zapadne bez dalšího spojování:
- ostatní ostrovy volají tvoje `rozhrani.py` (podpisy jsou ve snímku `kontrakty/rozhrani.json`);
- čtou tvoje pohledy `v_*` (návrh v `pohledy.sql`, v databázi přes migrace);
- klienti volají tvoje endpointy (snímek `kontrakty/openapi.json`, ve vývoji Swagger `/api/docs`).

## Práce a odevzdání

- Jedna větev na ostrov: `ostrov/<ostrov>`. Agenti na jednom PC pracují každý ve vlastním `git worktree`.
- Před odevzdáním spusť `python -m nastroje.over_vse`. Musí skončit „Všechny kontroly prošly.“
- Pull request schvaluje vlastník složky. Změny `rozhrani.py`, `kontrakty.py`, pohledů a migrací navíc schvaluje P1.
- Hotovo je, když:
  - kontroly prošly;
  - každá nová operace má test: pravidla jednotkově, SQL proti SQL Serveru;
  - změnu jde vysvětlit jedním odstavcem.

## Pravidla psaní kódu (závazná)

Znění od vedoucího projektu, beze změn:

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
