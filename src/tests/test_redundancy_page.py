"""Páginas da redundância (N2.5, visualizations/redundancy_page.py): ranking e medidas.

Dados sintéticos em memória; escreve só em tmp_path."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from overlap.redundancy import Redundancy, Waste, WasteFactors
from visualizations.redundancy_page import create_measures_html, create_ranking_html, measures_table

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
