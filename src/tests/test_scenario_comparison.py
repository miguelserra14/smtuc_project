"""Página "Antes vs Fase 2" (D2.5): formatação a partir de snapshots, CSV, e ligação aos slides e
ao dashboard master. Só snapshots sintéticos em memória - não lê dados nem escreve em outputs/."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pandas as pd

from visualizations.dashboard import (
    _default_dashboard_tabs,
    _default_presentation_tabs,
    create_feednplay_dashboard_html,
    create_master_dashboard_html,
    create_presentation_dashboard_html,
)
from visualizations.scenario_comparison import (
    WAIT_SENSES,
    _fmt_number,
    build_comparison_rows,
    create_scenario_comparison_html,
)


def _snap(scenario: str, day: str, values: dict[tuple[str, str, str], object]) -> pd.DataFrame:
    rows = [
        ("meta", "snapshot", "cenario", scenario),
        ("meta", "dados", "dia_referencia", day),
        ("meta", "dados", "hora_isocrona", "08:20:00"),
        ("meta", "dados", "smtuc", f"smtuc_{scenario}"),
        ("meta", "dados", "metro", f"metro_{scenario}"),
        ("overlap_resumo", "total", "walk_distance_threshold", "240"),
        ("overlap_resumo", "total", "TEMPORAL_OVERLAP_MAX_MIN", "5"),
    ]
    rows += [(*k, str(v)) for k, v in values.items()]
    return pd.DataFrame(rows, columns=["section", "key", "metric", "value"])


BEFORE = _snap("antes", "2026-05-11", {
    ("overlap_resumo", "total", "overlap_lines"): 68,
    ("overlap_resumo", "total", "total_overlap_extension_m"): 103560.8,
    ("overlap_resumo", "total", "temporal_overlap_pct"): 92.3,
    ("isocrona", "total", "tempo_medio_ponderado_min"): 39.5,
    ("isocrona", "faixa 0-10", "populacao"): 14141,
    ("populacao", "sem_oferta", "populacao"): 13701,
    ("esperas_54", "Portagem metro→bus | atual", "median"): 19.0,
    ("esperas_54", "Portela metro→bus | atual", "median"): 15.3,
})
AFTER = _snap("fase2", "2026-11-09", {
    ("overlap_resumo", "total", "overlap_lines"): 86,
    ("overlap_resumo", "total", "total_overlap_extension_m"): 338075.3,
    ("overlap_resumo", "total", "temporal_overlap_pct"): 97.84,
    ("isocrona", "total", "tempo_medio_ponderado_min"): 35.6858,
    ("isocrona", "faixa 0-10", "populacao"): 16633,
    ("populacao", "sem_oferta", "populacao"): 13534,
    ("esperas_54", "Portagem metro→bus | atual", "median"): 18.965,  # arredonda para 19,0
    ("esperas_54", "Portagem metro→bus | otimizado", "median"): 18.535,
    ("esperas_54", "Portagem metro→bus | melhorado", "median"): 9.08,
    ("esperas_54", "Portela metro→bus | atual", "median"): 19.75,
    ("esperas_54", "Portela metro→bus | otimizado", "median"): 19.75,
    ("esperas_54", "Portela metro→bus | melhorado", "median"): 17.68,
})


def _kpi(rows, source: str) -> dict[str, str]:
    return next(r for r in rows["kpis"] if r["source"] == source)


def _wait(rows, label: str) -> dict[str, str]:
    return next(r for r in rows["waits"] if r["label"] == label)


def test_number_format_is_pt_pt() -> None:
    assert _fmt_number(14141) == "14 141"
    assert _fmt_number(103.5608, 1, "km") == "103,6 km"
    assert _fmt_number(None) == "–"


def test_rows_match_readme_values_and_trends() -> None:
    rows = build_comparison_rows(BEFORE, AFTER)
    ext = _kpi(rows, "overlap_resumo/total/total_overlap_extension_m")
    assert (ext["before"], ext["after"], ext["delta"], ext["trend"]) == ("103,6 km", "338,1 km", "+234,5 km", "")
    pct = _kpi(rows, "overlap_resumo/total/temporal_overlap_pct")
    assert (pct["after"], pct["delta"]) == ("97,8 %", "+5,5 p.p.")
    iso = _kpi(rows, "isocrona/total/tempo_medio_ponderado_min")
    assert (iso["after"], iso["delta"], iso["trend"]) == ("35,7 min", "−3,8 min", "melhor")
    assert _kpi(rows, "isocrona/faixa 0-10/populacao")["trend"] == "melhor"
    assert _kpi(rows, "populacao/sem_oferta/populacao")["delta"] == "−167"
    # Métrica em falta num dos snapshots -> "–", nunca um número inventado.
    stations = _kpi(rows, "overlap_resumo/total/overlap_stations")
    assert (stations["before"], stations["delta"]) == ("–", "–")
    assert "≤ 240 m" in _kpi(rows, "overlap_resumo/total/overlap_lines")["label"]


def test_wait_trend_follows_displayed_rounding() -> None:
    rows = build_comparison_rows(BEFORE, AFTER)
    portagem = _wait(rows, "Portagem metro→autocarro")
    # 19,0 -> 19,0 (18,965 arredondado) não pode aparecer como melhoria.
    assert (portagem["before"], portagem["atual"], portagem["trend"]) == ("19,0 min", "19,0 min", "")
    assert (portagem["melhorado"], portagem["melhorado_trend"]) == ("9,1 min", "melhor")
    portela = _wait(rows, "Portela metro→autocarro")
    assert portela["trend"] == "pior"
    assert portela["otimizado_trend"] == ""
    assert [r["label"] for r in rows["waits"]] == [s.replace("bus", "autocarro") for s in WAIT_SENSES]


def test_page_and_csv(tmp_path: Path) -> None:
    hostile = AFTER.copy()
    hostile.loc[hostile["metric"] == "smtuc", "value"] = "<script>alert(1)</script>"
    page = Path(create_scenario_comparison_html(tmp_path / "c.html", BEFORE, hostile, csv_path=tmp_path / "c.csv"))
    text = page.read_text(encoding="utf-8")
    assert "Antes (11/05/2026)" in text and "Fase 2 (09/11/2026)" in text
    assert "338,1 km" in text and 'class="trend-melhor"' in text
    assert "<script>" not in text  # tudo o que vem dos dados é escapado
    assert "http" not in text.replace("dados.gov.pt", "")  # sem recursos externos (offline)
    with (tmp_path / "c.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ext = next(r for r in rows if r["indicador"].endswith("total_overlap_extension_m"))
    assert (ext["antes"], ext["depois"]) == ("103560.8", "338075.3")
    melhorado = next(r for r in rows if r["indicador"] == "Portagem metro→autocarro" and r["variante"] == "melhorado")
    assert (melhorado["antes"], melhorado["depois"]) == ("", "9.08")


def test_slides_and_master_link_both_scenarios(tmp_path: Path) -> None:
    tabs = _default_presentation_tabs()
    ids = [t["id"] for t in tabs]
    assert ids.index("overlap_fase2") < ids.index("antes_vs_fase2") < ids.index("integracao")
    compare = tabs[ids.index("antes_vs_fase2")]
    assert compare["kind"] == "scenario-compare"
    assert compare["table"]["src"] == "comparacao/antes_vs_fase2.html"
    for column in tabs[ids.index("integracao")]["columns"]:
        srcs = [s["src"] for s in column["scenarios"]]
        assert srcs[0] == column["current"]["src"]  # abre no antes, como antes
        assert any("_fase2/" in s for s in srcs)

    master = {t["id"]: t for t in _default_dashboard_tabs()}
    assert master["antes-vs-fase2"]["src"] == "comparacao/antes_vs_fase2.html"

    for create in (create_presentation_dashboard_html, create_feednplay_dashboard_html):
        out = Path(create(tmp_path / f"{create.__name__}.html"))
        text = out.read_text(encoding="utf-8")
        assert "kind === 'scenario-compare'" in text and "data-scenario-src" in text
        data = json.loads(re.search(r"const tabs = (\[.*?\]);\n", text, re.S).group(1))
        assert any(t["id"] == "antes_vs_fase2" for t in data)
    master_html = Path(create_master_dashboard_html(tmp_path / "m.html")).read_text(encoding="utf-8")
    assert "integration/portela_fase2/l54_all.html" in master_html
