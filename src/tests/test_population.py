"""Integration tests for BGRI population transport gap analysis and visualizations."""

from __future__ import annotations

import pandas as pd

import pytest

from overlap.transit import resolve_reference_day
from population.data_processing import (
    _project_root,
    _require_bgri_data,
    _require_geo_stack,
    compute_underserved_zones,
    filter_zones_by_distance,
    get_population_near_stadium,
)
from visualizations import (
    create_population_dashboard_html,
)
from src.config import CATCHMENT_M, STADIUM_RADIUS_M, OUTPUTS_POPULATION_DIR


@pytest.mark.integration
def test_population_detail_near_stadium_1km() -> None:
    """Test population distribution within 1km radius of stadium."""
    _require_geo_stack()

    total_pop, pop_1km, pct = get_population_near_stadium(
        bgri_gpkg_path=str(_require_bgri_data()),
        radius_m=STADIUM_RADIUS_M/2,  # 1km radius
    )

    print("\n=== População BGRI no raio de 1km do estádio (estimativa areal) ===")
    print(f"População total no concelho (BGRI): {total_pop:,.0f}")
    print(f"População estimada a <=1km do estádio: {pop_1km:,.0f} ({pct:.2f}%)")

    assert total_pop > 0
    assert pop_1km > 0


@pytest.fixture(scope="module")
def bgri_underserved_context() -> dict[str, object]:
    """Build shared context for underserved zones and visualization outputs."""
    _require_geo_stack()
    gpkg = _require_bgri_data()

    day_str = resolve_reference_day().strftime("%Y-%m-%d")

    # Compute underserved zones
    merged = compute_underserved_zones(
        day_str=day_str,
        catchment_m=CATCHMENT_M,
        datasets=("smtuc", "metrobus"),
        bgri_gpkg_path=str(gpkg),
        bgri_layer="BGRI2021_0603",
        population_col="N_INDIVIDUOS",
        output_csv_path=f"{OUTPUTS_POPULATION_DIR}/bgri_transport_gap.csv",
    )

    out_dir = _project_root() / OUTPUTS_POPULATION_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    assert len(merged) > 0
    return {
        "merged": merged,
        "day_str": day_str,
        "out_dir": out_dir,
    }


@pytest.mark.integration
def test_bgri_underserved_zones_dataset(bgri_underserved_context: dict[str, object]) -> None:
    """Validate underserved zones dataset used by all visualization tests."""
    merged = bgri_underserved_context["merged"]
    assert isinstance(merged, pd.DataFrame)
    assert len(merged) > 0

    print("\n=== Top 10 zonas BGRI mais subservidas (população vs oferta) ===")
    print(
        merged[["BGRI2021", "N_INDIVIDUOS", "supply_departures", "dep_per_1000_pop", "underservice_score"]]
        .head(10)
        .to_string(index=False)
    )


@pytest.mark.integration
def test_bgri_population_dashboard(bgri_underserved_context: dict[str, object]) -> None:
    """Generate the combined population dashboard with embedded population maps."""
    merged = bgri_underserved_context["merged"]
    day_str = bgri_underserved_context["day_str"]
    out_dir = bgri_underserved_context["out_dir"]
    merged_2km = filter_zones_by_distance(merged, distance_m=STADIUM_RADIUS_M)

    dashboard_html = out_dir / "bgri.html"
    create_population_dashboard_html(
        dashboard_html,
        merged=merged,
        merged_2km=merged_2km,
        day_str=day_str,
    )

    print(f"Dashboard de população gerado: {dashboard_html}")
    assert dashboard_html.exists()
