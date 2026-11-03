"""Všechny kontroly před odevzdáním změny – stejné, jaké poběží v CI.

    python -m nastroje.over_vse

1. testy Pythonu (unittest; pravidla ostrovů P1–P6 jsou také test),
2. testy api.js (node --test), pokud je nainstalovaný Node.js,
3. kontrakty jen přidáním (P10) proti snímku v kontrakty/,
4. ruff (styl), pokud je nainstalovaný.

Návratový kód 0 = vše v pořádku. Funguje na Windows i Linuxu.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

KOREN = Path(__file__).resolve().parents[1]


def _spust(nazev: str, prikaz: list[str]) -> bool:
    print(f"\n=== {nazev}: {' '.join(prikaz)}", flush=True)
    vysledek = subprocess.run(prikaz, cwd=KOREN)
    print(f"--- {nazev}: {'OK' if vysledek.returncode == 0 else 'SELHALO'}", flush=True)
    return vysledek.returncode == 0


def main() -> int:
    kroky: list[tuple[str, list[str]]] = [
        ("Testy Pythonu", [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py", "-t", "."]),
    ]
    vynechano: list[str] = []
    node = shutil.which("node")
    if node:
        kroky.append(("Testy api.js", [node, "--test", "tests/js/api.test.mjs"]))
    else:
        vynechano.append("Testy api.js (chybí Node.js)")
    kroky.append(("Kontrakty P10", [sys.executable, "-m", "nastroje.kontrakty", "over"]))
    if shutil.which("ruff"):
        kroky.append(("Ruff", ["ruff", "check", "."]))
    else:
        vynechano.append("Ruff (pip install -r requirements-vyvoj.txt)")

    selhalo = [nazev for nazev, prikaz in kroky if not _spust(nazev, prikaz)]
    print()
    for nazev in vynechano:
        print(f"VYNECHÁNO: {nazev}")
    if selhalo:
        print("SELHALO: " + ", ".join(selhalo))
        return 1
    print("Všechny kontroly prošly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
