"""Páginas da redundância (N2.5, visualizations/redundancy_page.py): ranking, medidas e o
aumento com um metro novo (N3.4).

Dados sintéticos em memória; escreve só em tmp_path."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from overlap.redundancy import Redundancy, Waste, WasteFactors
from visualizations.redundancy_page import (
    create_extension_html,
    create_measures_html,
    create_ranking_html,
    measures_table,
    temporal_overlap_pct,
)

_F = WasteFactors(fleet_total=1, fleet_electric=0, diesel_l_per_km=1.0, electric_kwh_per_km=0.0,
                  diesel_kg_co2_per_l=1.0, grid_kg_co2_per_kwh=0.0, weeks_per_year=52)


def _waste(lines: dict[str, float], corridors: list[tuple[str, str, float]] | None = None) -> Waste:
    by_line = pd.DataFrame({
        "line": list(lines), "viagens": [10] * len(lines), "km": [100.0] * len(lines),
        "km_metro": list(lines.values()), "pct_km_metro": [v for v in lines.values()],
        "horas": [5.0] * len(lines), "horas_metro": [1.0] * len(lines), "viagens_com_troco_metro": [10] * len(lines),
    }).sort_values("km_metro", ascending=False, kind="mergesort").reset_index(drop=True)
    corridors = corridors or [("Alfa", "Beta", 3.0), ("Gama", "Gama", 1.0)]
    by_corridor = pd.DataFrame({
        "station_a": [c[0] for c in corridors], "station_b": [c[1] for c in corridors],
        "km_metro": [c[2] for c in corridors], "horas_metro": [0.5] * len(corridors),
        "passagens": [4] * len(corridors), "linhas": ["5;<b>"] * len(corridors),
    })
    week = pd.DataFrame({"tipo": ["dia útil", "sábado", "domingo"], "dia": ["2026-11-09", "2026-11-07", "2026-11-08"],
                         "peso": [5, 1, 1], "viagens": [10, 5, 2], "km": [100.0, 50.0, 20.0],
                         "km_metro": [by_line["km_metro"].sum(), 1.0, 1.0], "horas_metro": [1.0, 0.5, 0.5]})
    line_week = by_line[["line", "km_metro", "horas_metro"]].assign(km_metro=lambda d: d["km_metro"] * 7)
    ref = Redundancy("x", date(2026, 11, 9), by_line, by_corridor)
    return Waste("x", ref, week, line_week, _F)


def test_ranking_page_lists_lines_and_corridors(tmp_path: Path) -> None:
    waste = _waste({"7T": 190.9, "5": 148.7, "<x>": 0.0})
    csv = tmp_path / "ranking.csv"
    page = Path(create_ranking_html(tmp_path / "ranking.html", waste, "Metro & SMTUC", csv_path=csv)).read_text(encoding="utf-8")
    assert "Metro &amp; SMTUC" in page and "Metro & SMTUC" not in page
    assert page.index(">7T<") < page.index(">5<")  # ordenado
    assert "&lt;x&gt;" not in page  # sem autocarros·km a par do metro não entra no ranking
    assert "Alfa – Beta" in page and "junto a Gama" in page
    assert "5, &lt;b&gt;" in page  # linhas do corredor escapadas
    assert "191" in page and "dia útil" in page
    assert set(pd.read_csv(csv)["line"].astype(str)) == {"7T", "5", "<x>"}  # o CSV tem todas
    assert (tmp_path / "ranking_corredores.csv").exists()


def test_measures_follow_the_network_diff() -> None:
    before = _waste({"7T": 190.0, "33": 98.0, "5": 148.0, "9": 10.0})
    after = _waste({"5": 184.0, "101": 50.0})
    diff = pd.DataFrame({
        "linha_antes": ["7T", "33", "5", "9", ""],
        "linha_depois": ["", "101", "5", "", "251"],
        "estado": ["cortada", "renumerada", "percurso alterado", "cortada", "nova"],
        "aviso": ["Como Vou (10/09/2026)", "", "", "", ""],
    })
    table = measures_table(before, after, diff, top_n=3).set_index("linha")
    assert list(table.index) == ["7T", "5", "33"]
    assert (table.loc["7T", "km_metro_depois"], table.loc["7T", "estado"]) == (0.0, "cortada")
    assert (table.loc["33", "linha_depois"], table.loc["33", "km_metro_depois"]) == ("101", 50.0)
    assert table.loc["5", "km_metro_depois"] == 184.0


def test_measures_page(tmp_path: Path) -> None:
    before = _waste({"7T": 190.0, "5": 148.0})
    after = _waste({"5": 184.0})
    diff = pd.DataFrame({"linha_antes": ["7T", "5"], "linha_depois": ["", "5"],
                         "estado": ["cortada", "igual"], "aviso": ["<aviso>", ""]})
    csv = tmp_path / "m.csv"
    page = Path(create_measures_html(tmp_path / "m.html", before, after, diff, "B", "C", csv_path=csv)).read_text(encoding="utf-8")
    assert "&lt;aviso&gt;" in page and "<aviso>" not in page
    assert "cortada" in page and "—" in page  # linha cortada: sem valor depois
    assert "As 2 linhas mais redundantes de B" in page
    assert len(pd.read_csv(csv)) == 2


def _metrics(pcts: dict[str, tuple[int, int]]) -> pd.DataFrame:
    """Métricas por linha mínimas: {linha: (passagens com metro, candidatos)}."""
    return pd.DataFrame({
        "line": list(pcts),
        "temporal_overlaps_count": [v[0] for v in pcts.values()],
        "temporal_spatial_candidates_count": [v[1] for v in pcts.values()],
        "temporal_overlaps_pct": [100.0 * v[0] / v[1] for v in pcts.values()],
    })


def test_temporal_overlap_total_is_passages_over_candidates() -> None:
    total, per_line = temporal_overlap_pct(_metrics({"6": (9, 10), "7": (1, 10)}))
    assert total == 50.0 and per_line["6"] == 90.0


def test_extension_page(tmp_path: Path) -> None:
    from tests.test_redundancy import _extension_waste

    before = _extension_waste({"6": (10.0, 1.0)}, [("6", "República", "República", 10.0, 1.0, 5)])
    after = _extension_waste(
        {"6": (25.0, 2.5), "<7>": (30.0, 2.0)},
        [("6", "República", "República", 10.0, 1.0, 5), ("6", "Celas", "Hospitais", 15.0, 1.5, 6),
         ("<7>", "Celas", "Celas", 30.0, 2.0, 9)],
    )
    temporal = {"C": _metrics({"6": (9, 10)}), "D": _metrics({"6": (10, 10), "<7>": (5, 10)}),
                "D metade": _metrics({"6": (6, 10), "<7>": (2, 10)})}
    csv = tmp_path / "aumento.csv"
    page = Path(create_extension_html(tmp_path / "aumento.html", before, after, ("Celas", "Hospitais"), "C", "D & cia",
                                      temporal, csv_path=csv)).read_text(encoding="utf-8")
    assert "D &amp; cia" in page and "&lt;7&gt;" in page and "<7>" not in page
    assert page.index("&lt;7&gt;</th>") < page.index(">6</th>")  # maior aumento primeiro
    assert "+30" in page and "+15" in page
    assert page.count("Overlap temporal<br>") == 3  # uma coluna por horário do metro, incl. a sensibilidade
    assert "Celas, Hospitais" in page and "junto a Celas" in page and "Celas – Hospitais" in page
    # totais da rede: C 9/10, D (10+5)/20, metade (6+2)/20
    assert "90,0 %" in page and "75,0 %" in page and "40,0 %" in page
    table = pd.read_csv(csv)
    assert set(table["line"].astype(str)) == {"6", "<7>"}
    assert "overlap_temporal_pct | D metade" in table.columns
    assert (tmp_path / "aumento_corredores.csv").exists()
