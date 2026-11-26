"""Comparação lado a lado de dois cenários (D2.5; um par de cada vez desde o N1, ver
config.COMPARISON_PAIRS: fase 1 -> metro novo com o Ep212 -> Como Vou, e fase 1 -> Como Vou).

Os números vêm de snapshots de `scripts/snapshot_metrics.py` (DataFrame longo
section,key,metric,value) - a MESMA definição dos registos em `reports/metricas/` e da tabela do
README, para a página nunca divergir deles. Este módulo só formata e escreve: quem tira os
snapshots é o chamador (`scripts/regenerate.py`, `regenerate_comparison_html`), porque
`snapshot_metrics` vive em `scripts/` e não é importável como módulo de `src/`.

Os nomes dos cenários vêm de config.SCENARIOS[...]["label"] e a frase sobre o que muda entre os
dois é calculada a partir dos feeds de cada snapshot (só o metro, só o SMTUC, ou os dois), para
uma página nunca dizer que mudaram coisas que não mudaram.

Saídas: uma página HTML só com tabelas (usada como iframe nos slides e no separador do dashboard
master) e um CSV com os mesmos valores, para se poder conferir.
"""

from __future__ import annotations

import csv
import html
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

from gtfs_processing.scenarios import get_scenario

from .io import _read_template

# Sentidos e variantes da 54 na ordem em que aparecem na tabela (chaves de esperas_54 no snapshot).
WAIT_SENSES = (
    "Portagem metro→bus",
    "Portagem bus→metro",
    "Portagem bus→metro (norte)",
    "Portela metro→bus",
    "Portela bus→metro",
)
# Sentidos só informativos (config INTEGRATION_SITES[*]["informative_reverse_senses"]): não
# entram na busca do desvio de fase e podem não existir num dos cenários (o norte de Portagem só
# existe na fase 2). Um sentido sem valor em NENHUM dos snapshots não sai na tabela.
INFORMATIVE_WAIT_SENSES = ("Portagem bus→metro (norte)",)
WAIT_VARIANTS = ("atual", "otimizado", "melhorado")


def snapshot_value(snap: pd.DataFrame, section: str, key: str, metric: str) -> str | None:
    """Valor (texto, como está no CSV) de uma linha do snapshot; None se não existir."""
    rows = snap[(snap["section"] == section) & (snap["key"] == key) & (snap["metric"] == metric)]
    if rows.empty:
        return None
    return str(rows["value"].iloc[0])


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN -> None


def _fmt_number(value: float | None, decimals: int = 0, unit: str = "") -> str:
    """Formato PT-PT: espaço nos milhares, vírgula decimal ("14 141", "103,6 km", "92,3 %")."""
    if value is None:
        return "–"
    text = f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return f"{text} {unit}".strip() if unit else text


def _fmt_delta(before: float | None, after: float | None, decimals: int, unit: str) -> str:
    if before is None or after is None:
        return "–"
    delta = after - before
    if round(delta, decimals) == 0:
        return "="
    sign = "+" if delta > 0 else "−"
    return f"{sign}{_fmt_number(abs(delta), decimals, unit)}"


def _fmt_day(iso: str | None) -> str:
    try:
        return date.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(iso or "?")


@dataclass(frozen=True)
class _Kpi:
    label: Callable[[pd.DataFrame], str]
    section: str
    key: str
    metric: str
    decimals: int = 0
    unit: str = ""
    scale: float = 1.0
    better: str = ""  # "lower"/"higher": sentido em que a mudança é uma melhoria ("" = neutro)
    delta_unit: str | None = None  # unidade da diferença, se for outra (percentagem -> "p.p.")


def _param(snap: pd.DataFrame, name: str, default: str) -> str:
    value = snapshot_value(snap, "overlap_resumo", "total", name) or snapshot_value(snap, "meta", "parametros", name)
    number = _number(value)
    return _fmt_number(number) if number is not None else default


KPIS: tuple[_Kpi, ...] = (
    _Kpi(lambda s: f"Linhas SMTUC com troços a ≤ {_param(s, 'walk_distance_threshold', '240')} m do metro",
         "overlap_resumo", "total", "overlap_lines"),
    _Kpi(lambda s: f"Paragens SMTUC a ≤ {_param(s, 'walk_distance_threshold', '240')} m de uma estação",
         "overlap_resumo", "total", "overlap_stations"),
    _Kpi(lambda s: "Extensão de linhas SMTUC a par do metro (soma por linha)",
         "overlap_resumo", "total", "total_overlap_extension_m", decimals=1, unit="km", scale=1 / 1000),
    _Kpi(lambda s: f"Passagens nessas paragens com um metro a ≤ {_param(s, 'TEMPORAL_OVERLAP_MAX_MIN', '5')} min",
         "overlap_resumo", "total", "temporal_overlap_pct", decimals=1, unit="%", delta_unit="p.p."),
    _Kpi(lambda s: "Tempo médio a partir do estádio às "
         f"{(snapshot_value(s, 'meta', 'dados', 'hora_isocrona') or '')[:5]} (ponderado pela população)",
         "isocrona", "total", "tempo_medio_ponderado_min", decimals=1, unit="min", better="lower"),
    _Kpi(lambda s: "População a ≤ 10 min do estádio",
         "isocrona", "faixa 0-10", "populacao", better="higher"),
    _Kpi(lambda s: "População em subsecções sem oferta",
         "populacao", "sem_oferta", "populacao", better="lower"),
)


def _trend(before: float | None, after: float | None, better: str, decimals: int) -> str:
    """Compara os valores ARREDONDADOS como aparecem na página (19,0 -> 19,0 nunca é "melhor")."""
    if not better or before is None or after is None:
        return ""
    before, after = round(before, decimals), round(after, decimals)
    if after == before:
        return ""
    improved = (after < before) if better == "lower" else (after > before)
    return "melhor" if improved else "pior"


def build_comparison_rows(before: pd.DataFrame, after: pd.DataFrame) -> dict[str, list[dict[str, str]]]:
    """Linhas das duas tabelas (indicadores gerais e esperas da 54), já formatadas.

    Cada linha traz também os valores numéricos crus (`before_value`/`after_value`, texto do
    snapshot) para o CSV - a página mostra só os formatados."""
    kpis: list[dict[str, str]] = []
    for kpi in KPIS:
        raw_b = snapshot_value(before, kpi.section, kpi.key, kpi.metric)
        raw_a = snapshot_value(after, kpi.section, kpi.key, kpi.metric)
        b = _number(raw_b)
        a = _number(raw_a)
        b = b * kpi.scale if b is not None else None
        a = a * kpi.scale if a is not None else None
        kpis.append({
            "label": kpi.label(after),
            "before": _fmt_number(b, kpi.decimals, kpi.unit),
            "after": _fmt_number(a, kpi.decimals, kpi.unit),
            "delta": _fmt_delta(b, a, kpi.decimals, kpi.unit if kpi.delta_unit is None else kpi.delta_unit),
            "trend": _trend(b, a, kpi.better, kpi.decimals),
            "before_value": raw_b or "",
            "after_value": raw_a or "",
            "source": f"{kpi.section}/{kpi.key}/{kpi.metric}",
        })

    waits: list[dict[str, str]] = []
    for sense in WAIT_SENSES:
        raw_b = snapshot_value(before, "esperas_54", f"{sense} | atual", "median")
        if sense in INFORMATIVE_WAIT_SENSES and raw_b is None and snapshot_value(
            after, "esperas_54", f"{sense} | atual", "median"
        ) is None:
            continue
        row = {
            "label": sense.replace("bus", "autocarro") + (" *" if sense in INFORMATIVE_WAIT_SENSES else ""),
            "before": _fmt_number(_number(raw_b), 1, "min"),
            "before_value": raw_b or "",
        }
        after_atual = _number(snapshot_value(after, "esperas_54", f"{sense} | atual", "median"))
        for variant in WAIT_VARIANTS:
            raw = snapshot_value(after, "esperas_54", f"{sense} | {variant}", "median")
            value = _number(raw)
            row[variant] = _fmt_number(value, 1, "min")
            row[f"{variant}_value"] = raw or ""
            if variant != "atual":
                row[f"{variant}_trend"] = _trend(after_atual, value, "lower", 1)
        row["trend"] = _trend(_number(raw_b), after_atual, "lower", 1)
        waits.append(row)
    return {"kpis": kpis, "waits": waits}


def scenario_label(name: str) -> str:
    """Nome curto de um cenário (config.SCENARIOS[...]["label"]); o próprio nome se o cenário não
    existir (ex.: um snapshot ad hoc com --smtuc/--metro)."""
    try:
        return get_scenario(name).display_name
    except ValueError:
        return name


def _snapshot_label(snap: pd.DataFrame, fallback: str) -> str:
    return scenario_label(snapshot_value(snap, "meta", "snapshot", "cenario") or fallback)


def _scenario_heading(snap: pd.DataFrame, fallback: str) -> str:
    return f"{_snapshot_label(snap, fallback)} ({_fmt_day(snapshot_value(snap, 'meta', 'dados', 'dia_referencia'))})"


def what_changes(before: pd.DataFrame, after: pd.DataFrame) -> str:
    """Frase (HTML, sem dados por escapar) sobre o que muda entre os dois snapshots, a partir dos
    feeds de cada um: só o metro, só o horário do SMTUC, só umas linhas (vistas "<feed>-sem-<linhas>",
    N2.3), os dois, ou nenhum."""
    from gtfs_processing.gtfs import parse_dataset_view

    changed = [
        role for role in ("metro", "smtuc")
        if snapshot_value(before, "meta", "dados", role) != snapshot_value(after, "meta", "dados", role)
    ]
    base_b, excl_b = parse_dataset_view(str(snapshot_value(before, "meta", "dados", "smtuc") or ""))
    base_a, excl_a = parse_dataset_view(str(snapshot_value(after, "meta", "dados", "smtuc") or ""))
    if changed == ["smtuc"] and base_b == base_a:
        only_after = sorted(set(excl_b) - set(excl_a))
        only_before = sorted(set(excl_a) - set(excl_b))
        parts = []
        for lines, where in ((only_after, "segundo"), (only_before, "primeiro")):
            if lines:
                many = len(lines) > 1
                parts.append(f"{'as linhas' if many else 'a linha'} {_lines_html(lines)}, que só "
                             f"existe{'m' if many else ''} no {where}")
        sentence = (
            f"Entre os dois cenários só muda {' e '.join(parts)}. "
            "O resto do horário do SMTUC e o metro são os mesmos."
        )
        return sentence + _days_note(before, after)
    sentence = {
        ("metro", "smtuc"): "Entre os dois cenários mudam o metro <strong>e</strong> o horário do SMTUC.",
        ("metro",): "Entre os dois cenários só muda o <strong>metro</strong>: o horário do SMTUC é o mesmo.",
        ("smtuc",): "Entre os dois cenários só muda o <strong>horário do SMTUC</strong>: o metro é o mesmo.",
        (): "Os dois cenários usam os mesmos horários.",
    }[tuple(changed)]
    return sentence + _days_note(before, after)


def _lines_html(lines: list[str]) -> str:
    return " e ".join(f"<strong>{html.escape(line)}</strong>" for line in lines)


def _days_note(before: pd.DataFrame, after: pd.DataFrame) -> str:
    days = {snapshot_value(snap, "meta", "dados", "dia_referencia") for snap in (before, after)}
    return " Cada um é medido no seu dia de referência." if len(days) > 1 else ""


def _cell(text: str, trend: str = "") -> str:
    cls = f' class="trend-{trend}"' if trend else ""
    return f"<td{cls}>{html.escape(text)}</td>"


def _render_body(before: pd.DataFrame, after: pd.DataFrame, rows: dict[str, list[dict[str, str]]]) -> str:
    head_b = html.escape(_scenario_heading(before, "antes"))
    head_a = html.escape(_scenario_heading(after, "fase2"))
    kpi_rows = "".join(
        f"<tr><th scope=\"row\">{html.escape(r['label'])}</th>{_cell(r['before'])}{_cell(r['after'])}"
        f"{_cell(r['delta'], r['trend'])}</tr>"
        for r in rows["kpis"]
    )
    informative_note = (
        '<p class="note">* Informativo: só existe com o metro da fase 2, que continua de Portagem para '
        "Coimbra B e para a República (conta a primeira partida em qualquer dos ramos). Fica fora da "
        "busca do desvio de fase da 54.</p>"
        if any(r["label"].endswith(" *") for r in rows["waits"])
        else ""
    )
    label_b = html.escape(_snapshot_label(before, "antes"))
    label_a = html.escape(_snapshot_label(after, "depois"))
    wait_rows = "".join(
        f"<tr><th scope=\"row\">{html.escape(r['label'])}</th>{_cell(r['before'])}"
        f"{_cell(r['atual'], r['trend'])}{_cell(r['otimizado'], r.get('otimizado_trend', ''))}"
        f"{_cell(r['melhorado'], r.get('melhorado_trend', ''))}</tr>"
        for r in rows["waits"]
    )
    feeds = []
    for snap in (before, after):
        feeds.append(
            f"{html.escape(_scenario_heading(snap, '?'))}: SMTUC "
            f"<code>{html.escape(snapshot_value(snap, 'meta', 'dados', 'smtuc') or '?')}</code> + Metro "
            f"<code>{html.escape(snapshot_value(snap, 'meta', 'dados', 'metro') or '?')}</code>"
        )
    return f"""
<section>
  <h2>Rede, cobertura e acessibilidade</h2>
  <table>
    <thead><tr><th scope="col">Indicador</th><th scope="col">{head_b}</th><th scope="col">{head_a}</th><th scope="col">Diferença</th></tr></thead>
    <tbody>{kpi_rows}</tbody>
  </table>
  <p class="note">A extensão soma o troço de cada linha: um corredor com várias linhas conta várias vezes.</p>
</section>
<section>
  <h2>Linha 54: espera mediana no transbordo</h2>
  <table>
    <thead><tr><th scope="col">Sentido</th><th scope="col">{head_b}<br><span>atual</span></th><th scope="col">{head_a}<br><span>atual</span></th><th scope="col">{head_a}<br><span>otimizado</span></th><th scope="col">{head_a}<br><span>melhorado (2 autocarros)</span></th></tr></thead>
    <tbody>{wait_rows}</tbody>
  </table>
  <p class="note">A cor compara as propostas com o horário atual de {label_a} (e esse com {label_b}): <span class="trend-melhor">menos espera</span>, <span class="trend-pior">mais espera</span>.</p>
  {informative_note}
</section>
<p class="note sources">{what_changes(before, after)} {' · '.join(feeds)}. Dados: AGIT / dados.gov.pt (CC BY 4.0), SMTUC, INE (BGRI 2021).</p>
"""


def write_comparison_csv(rows: dict[str, list[dict[str, str]]], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["tabela", "indicador", "variante", "antes", "depois"])
        for r in rows["kpis"]:
            writer.writerow(["indicadores", r["source"], "", r["before_value"], r["after_value"]])
        for r in rows["waits"]:
            for variant in WAIT_VARIANTS:
                writer.writerow(["esperas_54_mediana_min", r["label"], variant,
                                 r["before_value"] if variant == "atual" else "", r[f"{variant}_value"]])
    return path


def create_scenario_comparison_html(
    output_path: Path | str,
    before: pd.DataFrame,
    after: pd.DataFrame,
    title: str | None = None,
    csv_path: Path | str | None = None,
) -> str:
    """Escreve a página de comparação (e, se `csv_path`, o CSV com os mesmos valores). Sem `title`,
    o título é "<cenário antes> vs <cenário depois>" (nomes de config.SCENARIOS)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_comparison_rows(before, after)
    if title is None:
        title = f"{_snapshot_label(before, 'antes')} vs {_snapshot_label(after, 'depois')}"
    page = _read_template("scenario_comparison.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__BODY__", _render_body(before, after, rows))
    output_path.write_text(page, encoding="utf-8")
    if csv_path is not None:
        write_comparison_csv(rows, csv_path)
    return str(output_path)
