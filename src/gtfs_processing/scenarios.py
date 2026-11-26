"""Cenários de análise (D2.3): que feeds GTFS e que dia/hora de referência entram em cada análise.

Um cenário junta um SMTUC e um Metro (nomes lógicos de config.DATASET_DIRS) ao dia em que esses
dois feeds se comparam. Antes havia um só dia global (config.REACHABILITY_REFERENCE_DAY) e os nomes
"smtuc"/"metrobus" estavam escritos à mão em vários módulos; com dados oficiais isso deixa de
servir, porque a rede "antes" (até 09/09/2026) e a da fase 2 (desde 10/09/2026) não têm nenhum dia
em comum.

Os cenários definem-se em config.SCENARIOS (dados, sem lógica). Este módulo é a única porta de
entrada: `get_scenario()` valida e devolve um `Scenario` imutável, `scenario_reference_day()` dá o
dia a usar (fixo ou dinâmico, conforme config.USE_FIXED_REFERENCE_DAY) e `scenario_output_path()`
acrescenta o sufixo do cenário aos ficheiros gerados, para os cenários não se pisarem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import config


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    smtuc: str
    metro: str
    reference_day: date
    reference_time: str
    output_suffix: str
    label: str = ""  # nome curto (páginas de comparação); "" = usar o nome
    # Linhas SMTUC retiradas do feed (N2.3, ex.: a rede da fase 1 sem a 54). Com linhas, `smtuc` é
    # o nome da VISTA do dataset (gtfs.dataset_view, ex.: "smtuc-sem-54"), que todo o código lê
    # como um dataset normal; `smtuc_base` é o feed de onde vem.
    exclude_lines: tuple[str, ...] = ()

    @property
    def smtuc_base(self) -> str:
        from gtfs_processing.gtfs import base_dataset

        return base_dataset(self.smtuc)

    @property
    def display_name(self) -> str:
        return self.label or self.name

    @property
    def datasets(self) -> tuple[str, str]:
        """(smtuc, metro), na ordem que as análises multimodais esperam."""
        return (self.smtuc, self.metro)


_REQUIRED_KEYS = ("description", "smtuc", "metro", "reference_day", "reference_time", "output_suffix")


def scenario_names() -> tuple[str, ...]:
    return tuple(config.SCENARIOS)


def get_scenario(scenario: str | Scenario | None = None) -> Scenario:
    """`None` -> config.DEFAULT_SCENARIO; um `Scenario` passa tal como está (permite cenários ad hoc,
    ex.: o snapshot com --smtuc/--metro); um nome desconhecido ou mal definido levanta ValueError."""
    if isinstance(scenario, Scenario):
        return scenario
    name = scenario or config.DEFAULT_SCENARIO
    spec = config.SCENARIOS.get(name)
    if spec is None:
        raise ValueError(f"Cenário desconhecido: {name!r} (definidos em config.SCENARIOS: {', '.join(config.SCENARIOS)})")
    missing = [k for k in _REQUIRED_KEYS if k not in spec]
    if missing:
        raise ValueError(f"Cenário {name!r} sem as chaves {missing} em config.SCENARIOS")
    for role in ("smtuc", "metro"):
        if spec[role] not in config.DATASET_DIRS:
            raise ValueError(f"Cenário {name!r}: dataset {role}={spec[role]!r} não existe em config.DATASET_DIRS")
    raw_excluded = spec.get("exclude_lines") or ()
    if isinstance(raw_excluded, str):
        raise ValueError(f"Cenário {name!r}: exclude_lines tem de ser uma lista de linhas, não {raw_excluded!r}")
    from gtfs_processing.gtfs import dataset_view

    excluded = tuple(sorted({str(line).strip() for line in raw_excluded if str(line).strip()}))
    return Scenario(
        name=name,
        description=str(spec["description"]),
        smtuc=dataset_view(str(spec["smtuc"]), excluded),
        metro=str(spec["metro"]),
        reference_day=date.fromisoformat(str(spec["reference_day"])),
        reference_time=str(spec["reference_time"]),
        output_suffix=str(spec["output_suffix"]),
        label=str(spec.get("label") or ""),
        exclude_lines=excluded,
    )


def excluded_integration_lines(scenario: str | Scenario | None = None) -> tuple[str, ...]:
    """Linhas dos nós de integração (config.INTEGRATION_SITES: 54, 38) que o cenário retira do
    feed. Não vazio = o cenário não tem páginas de integração nem esperas/busca de fase da 54."""
    sc = get_scenario(scenario)
    lines: set[str] = set()
    for site in config.INTEGRATION_SITES:
        value = site["line_number"]
        lines.update([value] if isinstance(value, str) else [str(v) for v in value])
    return tuple(sorted(lines & set(sc.exclude_lines)))


def nearest_business_day(from_day: date | None = None) -> date:
    """Hoje se for dia útil; senão o dia útil mais próximo (sábado -> 6ª, domingo -> 2ª)."""
    day = from_day or date.today()
    wd = day.weekday()
    if wd <= 4:
        return day
    if wd == 5:
        return day - timedelta(days=1)
    return day + timedelta(days=1)


def scenario_reference_day(scenario: str | Scenario | None = None) -> date:
    """Dia de referência do cenário. Com config.USE_FIXED_REFERENCE_DAY=True (por omissão) é o dia
    fixo do cenário (reprodutível); com False, o dia útil mais próximo de hoje - o MESMO para todos
    os cenários, por isso só faz sentido com feeds em vigor hoje."""
    if config.USE_FIXED_REFERENCE_DAY:
        return get_scenario(scenario).reference_day
    return nearest_business_day(date.today())


def scenario_reference_time(scenario: str | Scenario | None = None) -> str | None:
    """Hora das isócronas: a do cenário com o dia fixo; None ("agora") com o dia dinâmico."""
    return get_scenario(scenario).reference_time if config.USE_FIXED_REFERENCE_DAY else None


def scenario_output_path(path: str | Path, scenario: str | Scenario | None = None) -> str:
    """`outputs/overlap/line_metrics_db.csv` -> `outputs/overlap/line_metrics_db_fase2.csv` (sufixo
    do cenário antes da extensão; o cenário por omissão tem sufixo vazio e mantém os nomes de
    sempre). Devolve str com barras "/" para servir de chave/URL relativo."""
    p = Path(path)
    suffix = get_scenario(scenario).output_suffix
    return (p.with_name(f"{p.stem}{suffix}{p.suffix}")).as_posix()


def reference_days_by_dataset() -> dict[str, set[date]]:
    """Para cada dataset usado em algum cenário, os dias de referência em que tem de ser avaliado
    (validação do regenerate e do validador de feeds). Uma vista conta como o seu feed base (são
    os mesmos ficheiros)."""
    from gtfs_processing.gtfs import base_dataset

    out: dict[str, set[date]] = {}
    for name in scenario_names():
        sc = get_scenario(name)
        day = scenario_reference_day(sc)
        for dataset in sc.datasets:
            out.setdefault(base_dataset(dataset), set()).add(day)
    return out


# Valores por omissão das funções que recebem datasets explícitos (overlap, população, mapas):
# vêm do cenário por omissão em vez de "smtuc"/"metrobus" escritos à mão em cada assinatura.
DEFAULT_SMTUC_DATASET: str = get_scenario().smtuc
DEFAULT_METRO_DATASET: str = get_scenario().metro
DEFAULT_DATASETS: tuple[str, str] = get_scenario().datasets
