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
    INFORMATIVE_WAIT_SENSES,
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
# Cenário do meio (N1): mesmo SMTUC do BEFORE, mesmo metro do AFTER.
MIDDLE = _snap("fase2_ep212", "2026-11-09", {
    ("overlap_resumo", "total", "total_overlap_extension_m"): 398216.5,
    ("esperas_54", "Portagem metro→bus | atual", "median"): 18.5,
})
MIDDLE.loc[MIDDLE["metric"] == "smtuc", "value"] = "smtuc_antes"
MIDDLE.loc[MIDDLE["metric"] == "metro", "value"] = "metro_fase2"
# A′ (N2.3): o SMTUC do BEFORE sem a 54 (vista do dataset), o mesmo metro; sem esperas da 54.
SEM54 = _snap("antes_sem54", "2026-05-11", {
    ("overlap_resumo", "total", "total_overlap_extension_m"): 100000.0,
    ("populacao", "sem_oferta", "populacao"): 14000,
})
SEM54.loc[SEM54["metric"] == "smtuc", "value"] = "smtuc_antes-sem-54"
SEM54.loc[SEM54["metric"] == "metro", "value"] = "metro_antes"
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
    # Sem valores do sentido informativo em nenhum snapshot -> a linha não aparece.
    assert [r["label"] for r in rows["waits"]] == [
        s.replace("bus", "autocarro") for s in WAIT_SENSES if s not in INFORMATIVE_WAIT_SENSES
    ]


def test_informative_north_sense_only_after(tmp_path: Path) -> None:
    # O norte de Portagem só existe na fase 2: "–" no antes, sem tendência, marcado com * e nota.
    after = pd.concat([AFTER, pd.DataFrame(
        [("esperas_54", f"Portagem bus→metro (norte) | {v}", "median", str(x))
         for v, x in (("atual", 5.65), ("otimizado", 5.8), ("melhorado", 5.8))],
        columns=AFTER.columns,
    )], ignore_index=True)
    rows = build_comparison_rows(BEFORE, after)
    labels = [r["label"] for r in rows["waits"]]
    assert labels.index("Portagem autocarro→metro (norte) *") == labels.index("Portagem autocarro→metro") + 1
    north = _wait(rows, "Portagem autocarro→metro (norte) *")
    assert (north["before"], north["atual"], north["trend"]) == ("–", "5,7 min", "")
    assert north["otimizado_trend"] == "pior"
    text = Path(create_scenario_comparison_html(tmp_path / "c.html", BEFORE, after, csv_path=tmp_path / "c.csv")).read_text(encoding="utf-8")
    assert "* Informativo" in text
    assert "* Informativo" not in Path(create_scenario_comparison_html(tmp_path / "d.html", BEFORE, AFTER, csv_path=tmp_path / "d.csv")).read_text(encoding="utf-8")


def test_page_and_csv(tmp_path: Path) -> None:
    hostile = AFTER.copy()
    hostile.loc[hostile["metric"] == "smtuc", "value"] = "<script>alert(1)</script>"
    page = Path(create_scenario_comparison_html(tmp_path / "c.html", BEFORE, hostile, csv_path=tmp_path / "c.csv"))
    text = page.read_text(encoding="utf-8")
    # Nomes dos cenários de config.SCENARIOS[...]["label"] e título "<antes> vs <depois>".
    assert "Fase 1 (11/05/2026)" in text and "Como Vou (09/11/2026)" in text
    assert "<title>Fase 1 vs Como Vou</title>" in text
    assert "mudam o metro <strong>e</strong> o horário do SMTUC" in text
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
    # Narrativa de 2026-11-26: a integração da fase 1 fica na secção 1.5, antes da secção 2
    # (Como Vou). Desde o N1 a secção 2 compara pares que mudam UMA coisa: A -> B (só o metro) e
    # B -> C (só o horário SMTUC); a comparação A -> C (os dois juntos) saiu dos slides.
    assert ids.index("integracao") < ids.index("efeito_metro") < ids.index("s2_rede") < ids.index("como_vou") < ids.index("integracao_fase2")
    assert "antes_vs_fase2" not in ids
    tables = {t["id"]: t["table"]["src"] for t in tabs if t["kind"] == "scenario-compare"}
    assert tables == {
        # N2: ranking da fase 1 (A), contributo da 54 (A′ -> A), redundâncias depois do Como Vou (B -> C).
        "s1_ranking": "redundancia/ranking.html",
        "s1_5_contributo": "comparacao/antes_sem54_vs_antes.html",
        "s2_redundancias": "redundancia/medidas_fase2_ep212_vs_fase2.html",
        "efeito_metro": "comparacao/antes_vs_fase2_ep212.html",
        "s2_rede": "comparacao/rede_fase2_ep212_vs_fase2.html",
        "como_vou": "comparacao/fase2_ep212_vs_fase2.html",
    }
    for column in tabs[ids.index("integracao")]["columns"]:
        assert "_fase2" not in column["current"]["src"]  # secção 1.5 = só a fase 1
    for column in tabs[ids.index("integracao_fase2")]["columns"]:
        srcs = [s["src"] for s in column["scenarios"]]
        assert srcs[0] == column["current"]["src"]  # abre na rede atual (C)
        assert "_fase2/" in srcs[0]
        assert any("_fase2_ep212/" in s for s in srcs)  # e o botão mostra B (mesmo metro)

    master = {t["id"]: t for t in _default_dashboard_tabs()}
    assert master["antes-vs-fase2"]["src"] == "comparacao/antes_vs_fase2.html"
    assert master["redundancia"]["src"] == "redundancia/ranking_fase2.html"
    assert "comparacao/antes_sem54_vs_antes.html" in [f["src"] for f in master["redundancia"]["extra_frames"]]
    # N2 fechado: nenhum slide das secções 1, 1.5 e 2 continua por construir.
    assert not [t["id"] for t in tabs if t["kind"] == "pending" and t.get("section") in ("s1", "s1_5", "s2")]

    for create in (create_presentation_dashboard_html, create_feednplay_dashboard_html):
        out = Path(create(tmp_path / f"{create.__name__}.html"))
        text = out.read_text(encoding="utf-8")
        assert "kind === 'scenario-compare'" in text and "data-scenario-src" in text
        data = json.loads(re.search(r"const tabs = (\[.*?\]);\n", text, re.S).group(1))
        assert any(t["id"] == "como_vou" for t in data)
    master_html = Path(create_master_dashboard_html(tmp_path / "m.html")).read_text(encoding="utf-8")
    assert "integration/portela_fase2/l54_all.html" in master_html


def test_what_changes_is_computed_from_the_feeds(tmp_path: Path) -> None:
    # N1: a frase sobre o que muda sai dos feeds de cada snapshot, nunca escrita à mão - a página
    # "fase 1 -> metro novo" não pode dizer que mudou o SMTUC, nem a "metro novo -> Como Vou" o metro.
    from visualizations.scenario_comparison import what_changes

    assert "só muda o <strong>metro</strong>" in what_changes(BEFORE, MIDDLE)
    assert "Cada um é medido no seu dia" in what_changes(BEFORE, MIDDLE)
    assert "só muda o <strong>horário do SMTUC</strong>" in what_changes(MIDDLE, AFTER)
    assert "Cada um é medido" not in what_changes(MIDDLE, AFTER)  # mesmo dia
    assert "mudam o metro <strong>e</strong>" in what_changes(BEFORE, AFTER)
    text = Path(create_scenario_comparison_html(tmp_path / "m.html", MIDDLE, AFTER)).read_text(encoding="utf-8")
    assert "Metro da fase 2 + SMTUC Ep212 (09/11/2026)" in text
    assert "horário atual de Como Vou (e esse com Metro da fase 2 + SMTUC Ep212)" in text


def test_what_changes_names_the_excluded_line(tmp_path: Path) -> None:
    # N2.3: entre A′ e A só muda a linha 54 (mesmo feed, filtrado) - não "o horário do SMTUC".
    from visualizations.scenario_comparison import what_changes

    text = what_changes(SEM54, BEFORE)
    assert "só muda a linha <strong>54</strong>, que só existe no segundo" in text
    assert "horário do SMTUC</strong>" not in text and "Cada um é medido" not in text
    assert "que só existe no primeiro" in what_changes(BEFORE, SEM54)
    page = Path(create_scenario_comparison_html(tmp_path / "s.html", SEM54, BEFORE)).read_text(encoding="utf-8")
    assert "Fase 1 sem a 54 (11/05/2026)" in page


def test_node_isochrone_rows_only_when_a_snapshot_has_them() -> None:
    # N2.4: as isócronas dos nós são uma secção opcional - sem ela as linhas não saem.
    from visualizations.scenario_comparison import build_comparison_rows

    labels = [r["label"] for r in build_comparison_rows(BEFORE, AFTER)["kpis"]]
    assert not any("estação Portela" in label for label in labels)

    def with_nodes(snap: pd.DataFrame, minutes: float, pop: float) -> pd.DataFrame:
        extra = pd.DataFrame([
            ("isocrona_nos", "Portela | origem", "partidas", "07:30:00-09:20:00/12"),
            ("isocrona_nos", "Portela | total", "tempo_medio_ponderado_min", str(minutes)),
            ("isocrona_nos", "Portela | total", "populacao_30min_media", str(pop)),
        ], columns=snap.columns)
        return pd.concat([snap, extra], ignore_index=True)

    rows = build_comparison_rows(with_nodes(SEM54, 46.96, 51137), with_nodes(BEFORE, 46.01, 52375))["kpis"]
    portela = {r["label"]: r for r in rows if "estação Portela" in r["label"]}
    time_row = next(r for label, r in portela.items() if label.startswith("Tempo médio"))
    assert "07:30–09:20" in next(iter(portela))
    assert (time_row["before"], time_row["after"], time_row["delta"], time_row["trend"]) == ("47,0 min", "46,0 min", "−1,0 min", "melhor")
    pop_row = next(r for label, r in portela.items() if label.startswith("População"))
    assert (pop_row["delta"], pop_row["trend"]) == ("+1 238", "melhor")
    # Portagem não está em nenhum dos dois: não sai.
    assert not any("estação Portagem" in r["label"] for r in rows)


def test_hospital_isochrone_rows_only_when_a_snapshot_has_them() -> None:
    # N3.4: secção opcional isocrona_huc (ponto fixo dos HUC) - sem ela as linhas não saem.
    from config import HOSPITAL_ISOCHRONE_ORIGIN
    from visualizations.scenario_comparison import build_comparison_rows

    name = HOSPITAL_ISOCHRONE_ORIGIN[0]
    assert not any(name in r["label"] for r in build_comparison_rows(BEFORE, AFTER)["kpis"])

    def with_huc(snap: pd.DataFrame, minutes: float, pop: float) -> pd.DataFrame:
        extra = pd.DataFrame([
            ("isocrona_huc", f"{name} | origem", "partidas", "07:30:00-09:20:00/12"),
            ("isocrona_huc", f"{name} | total", "tempo_medio_ponderado_min", str(minutes)),
            ("isocrona_huc", f"{name} | total", "populacao_30min_media", str(pop)),
        ], columns=snap.columns)
        return pd.concat([snap, extra], ignore_index=True)

    rows = [r for r in build_comparison_rows(with_huc(BEFORE, 40.0, 70000), with_huc(AFTER, 38.5, 72000))["kpis"]
            if name in r["label"]]
    assert len(rows) == 2 and "07:30–09:20" in rows[0]["label"]
    assert (rows[0]["delta"], rows[0]["trend"]) == ("−1,5 min", "melhor")
    assert (rows[1]["delta"], rows[1]["trend"]) == ("+2 000", "melhor")
