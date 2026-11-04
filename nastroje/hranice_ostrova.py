"""Kontrola hranic ostrova: větev `ostrov/<složka>/<popis>` smí měnit jen `app/ostrovy/<složka>/`.

    python -m nastroje.hranice_ostrova <větev> [<základ>]      # základ = origin/main

Ostatní větve (`platforma/…` a další větve vedoucího projektu) se nekontrolují. Běží v CI
na každý push (.github/workflows/ci.yml) a agent ji pouští před pushem (docs/agenti.md).
Chyba = vypíše soubory mimo ostrov a skončí s kódem 1.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

KOREN = Path(__file__).resolve().parents[1]
OSTROVY = KOREN / "app" / "ostrovy"


def mimo_ostrov(vetev: str, soubory: list[str]) -> list[str]:
    """Soubory, které větev ostrova měnit nesmí. Neznámý ostrov = všechny soubory jsou mimo."""
    casti = vetev.split("/")
    if casti[0] != "ostrov":
        return []
    if len(casti) < 2 or not casti[1] or casti[1].startswith("_") or not (OSTROVY / casti[1]).is_dir():
        return list(soubory) or [f"(neznámý ostrov ve větvi {vetev!r})"]
    slozka = f"app/ostrovy/{casti[1]}/"
    return [s for s in soubory if not s.startswith(slozka)]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    vetev, zaklad = argv[0], (argv[1] if len(argv) > 1 else "origin/main")
    soubory = subprocess.run(["git", "diff", "--name-only", f"{zaklad}...HEAD"], cwd=KOREN, check=True,
                             capture_output=True, text=True).stdout.split()
    spatne = mimo_ostrov(vetev, soubory)
    if spatne:
        print(f"Větev {vetev} mění soubory mimo svůj ostrov (AGENTS.md, Hranice):")
        print("\n".join(f"  {s}" for s in spatne))
        print("Změnu sdílené části dejte jako zvláštní úkol pro P1.")
        return 1
    print(f"Hranice ostrova v pořádku ({len(soubory)} změněných souborů).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
