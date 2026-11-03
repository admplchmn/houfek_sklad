"""Základ HTTP kontraktů (sekce 4.2): camelCase v JSON, snake_case v Pythonu.

Každý vstup ostrova dědí z `Vstup` (skladový příkaz ze `SkladovyVstup`, změna kmenových dat
ze `Zmena`), GET filtry z `Parametry`, každý výstup z `Vystup`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Generic, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator
from pydantic.alias_generators import to_camel

from .chyby import chyba_vstupu

# Všechny časy se ukládají i počítají v UTC (TD-11); CASOVA_ZONA slouží jen k zobrazení.
CASOVA_ZONA = ZoneInfo("Europe/Prague")


def teď() -> datetime:
    """Aktuální čas tak, jak se ukládá do DATETIME2: naive UTC (TD-11).

    Databáze ani pyodbc neznají časové pásmo, proto je UTC jediná báze, která (a) nedává dvojznačnou
    hodinu při přechodu na zimní čas a (b) nezávisí na časovém pásmu stroje – SQL Server v Dockeru i CI
    běží na UTC, takže hodnoty z DEFAULT (SYSUTCDATETIME()) mají stejnou bázi jako ty z Pythonu.
    Naive (ne aware) je proto, že takový čas vrací i čtení z DATETIME2 – hodnota se nemění po round-trip.
    Najevo se převádí na místní čas až `_cas_iso`.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cas_iso(hodnota: datetime) -> str:
    if hodnota.tzinfo is None:          # DATETIME2 v databázi je UTC bez zóny (TD-11)
        hodnota = hodnota.replace(tzinfo=timezone.utc)
    return hodnota.astimezone(CASOVA_ZONA).isoformat(timespec="seconds")


# Čas: ISO 8601 s posunem pro Prahu, např. "2026-10-26T17:59:00+01:00" (v databázi se ukládá UTC)
Cas = Annotated[datetime, PlainSerializer(_cas_iso, return_type=str, when_used="json")]
# Milimetry: v JSON číslo (ne text), nejvýše 2 desetinná místa
Mm = Annotated[Decimal, Field(max_digits=10, decimal_places=2),
               PlainSerializer(float, return_type=float, when_used="json")]
# Počet kusů: celé číslo v rozsahu sloupce INT; obchodní limity si ostrov zúží sám (gt=0 apod.)
Ks = Annotated[int, Field(ge=0, le=2_147_483_647)]
# Důvod změny: ukládá se do AuditZmen.Poznamka (NVARCHAR(500)); povinný u každé změny kmenových dat
Duvod = Annotated[str, Field(min_length=3, max_length=500)]
# Naskenovaný nebo zadaný kód regálu, boxu či pozice; rozkládá ho parser ostrova Struktura (5.1)
Kod = Annotated[str, Field(min_length=1, max_length=150)]
# GET filtr podle aktivity: výchozí hodnotu (obvykle True) určuje model; prázdná hodnota v query
# (?aktivni=, např. volba „vše“ ve formuláři) = None = bez filtru (nacti_parametry)
FiltrAktivni = Annotated[bool | None, Field(
    description="true = jen aktivní, false = jen vyřazené, prázdná hodnota (?aktivni=) = vše")]

_KONFIGURACE_VSTUPU = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid",
                                 str_strip_whitespace=True, frozen=True)


class Parametry(BaseModel):
    """Query parametry GET endpointu (filtry, stránkování). Neznámý parametr je chyba."""

    model_config = _KONFIGURACE_VSTUPU


class Vstup(BaseModel):
    """Vstup endpointu. Neznámá pole jsou chyba (překlep v názvu pole se neztratí).

    requestId je u běžných vstupů volitelný (UI ho posílá u každého POST), povinný je
    jen ve `SkladovyVstup`.
    """

    model_config = _KONFIGURACE_VSTUPU

    request_id: uuid.UUID | None = None


class SkladovyVstup(Vstup):
    """Vstup skladového příkazu: requestId je povinný (sekce 4.5)."""

    request_id: uuid.UUID


class DuvodVstup(Vstup):
    """Akce, ke které stačí důvod: deaktivace, zrušení, ukončení (POST …/{id}/{akce})."""

    duvod: Duvod


class Zmena(Vstup):
    """Vstup PATCH (sekce 4.1): posílají se jen měněná pole a důvod.

    Neposlané pole se nemění, poslané `null` hodnotu vymaže – jen u nepovinných údajů; povinné
    údaje vyjmenuje model v NELZE_VYMAZAT a `null` u nich je VALIDATION_ERROR s názvem pole.
    Které pole klient poslal, vrací `zmenena_pole()`; prázdná změna je VALIDATION_ERROR.
    """

    NELZE_VYMAZAT: ClassVar[tuple[str, ...]] = ()   # názvy polí v snake_case (sloupce NOT NULL)

    duvod: Duvod

    @model_validator(mode="after")
    def _neco_se_meni(self) -> "Zmena":
        if not self.zmenena_pole():
            raise ValueError("Pošlete aspoň jedno pole, které se má změnit.")
        vymazana = [nazev for nazev in self.NELZE_VYMAZAT
                    if nazev in self.model_fields_set and getattr(self, nazev) is None]
        if vymazana:
            # AppError projde validací Pydanticu beze změny a obálka ho vrátí jako VALIDATION_ERROR
            raise chyba_vstupu("Povinný údaj nejde vymazat.",
                               {to_camel(nazev): "Povinný údaj nejde vymazat." for nazev in vymazana})
        return self

    def zmenena_pole(self) -> dict[str, Any]:
        """Poslaná pole kromě důvodu a requestId, v abecedním pořadí (pro audit)."""
        return {nazev: getattr(self, nazev) for nazev in sorted(self.model_fields_set)
                if nazev not in ("duvod", "request_id")}


@dataclass(frozen=True)
class Varovani:
    """Varování nezastaví operaci; v JSON jako {"code": …, "message": …}."""

    kod: str
    zprava: str


class Vystup(BaseModel):
    """Výstup endpointu = obsah pole `data` v obálce.

    `transakce_id` a `varovani` se do `data` neposílají, Platforma je dá do obálky.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

    transakce_id: uuid.UUID | None = Field(default=None, exclude=True)
    varovani: tuple[Varovani, ...] = Field(default=(), exclude=True)


class Strankovani(Parametry):
    strana: int = Field(1, ge=1)
    velikost: int = Field(50, ge=1, le=200)


T = TypeVar("T")


class Strana(Vystup, Generic[T]):
    polozky: list[T]
    strana: int
    velikost: int
    celkem: int


class Seznam(Vystup, Generic[T]):
    """Krátký seznam bez stránkování (číselníky, regály pracoviště, role)."""

    polozky: list[T]


class CiselnikRadek(Vystup):
    """Položka číselníku pro filtry a formuláře (pracoviště, materiál, typ pohybu …)."""

    id: int
    kod: str
    nazev: str | None
    aktivni: bool
