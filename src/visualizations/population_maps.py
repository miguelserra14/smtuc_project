from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, Optional, Tuple

import geopandas as gpd
from config import POPULATION_STADIUM_MAP_RADIUS_M
from overlap.transit import resolve_reference_day

try:
    import plotly.express as px
except Exception:  # pragma: no cover - optional dependency guard
    px = None


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _read_template(template_name: str) -> str:
    template_path = _TEMPLATE_DIR / template_name
    return template_path.read_text(encoding="utf-8")


def _figure_to_srcdoc(fig: object) -> str:
    """Serialize a Plotly figure into escaped full HTML for iframe srcdoc."""
    html_doc = fig.to_html(full_html=False, include_plotlyjs="cdn")
    return html.escape(html_doc, quote=True)


def create_population_dashboard_html(
    output_path: Path | str,
    merged: gpd.GeoDataFrame,
    merged_2km: gpd.GeoDataFrame,
    day_str: str,
    title: str = "Painel de População",
    stadium_radius_m: float = POPULATION_STADIUM_MAP_RADIUS_M,
) -> str:
    """Create a single HTML dashboard that embeds the three main population visualizations.

    `stadium_radius_m` deve corresponder ao `distance_m` já usado para filtrar `merged_2km`
    (via `filter_zones_by_distance`) - só controla o texto do painel ("Estádio a X km"), não
    volta a filtrar os dados.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    heatmap_fig = create_population_heatmap(merged, day_str, color_scale="RdYlGn")
    choropleth_fig = create_choropleth_map(merged, day_str, color_scale="YlOrRd")
    stadium_fig = create_2km_choropleth_map(merged_2km, day_str, color_scale="YlOrRd")

    heatmap_srcdoc = _figure_to_srcdoc(heatmap_fig)
    choropleth_srcdoc = _figure_to_srcdoc(choropleth_fig)
    stadium_srcdoc = _figure_to_srcdoc(stadium_fig)

    radius_km = stadium_radius_m / 1000.0
    radius_label = f"{radius_km:g} km"

    page = _read_template("population_dashboard.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__HEATMAP_SRCDOC__", heatmap_srcdoc)
    page = page.replace("__CHOROPLETH_SRCDOC__", choropleth_srcdoc)
    page = page.replace("__STADIUM_SRCDOC__", stadium_srcdoc)
    page = page.replace("__STADIUM_RADIUS_LABEL__", html.escape(radius_label))
    output_path.write_text(page, encoding="utf-8")
    return str(output_path)


def _create_choropleth_generic(
    gdf: gpd.GeoDataFrame,
    title: str | None = None,
    color_scale: str = "RdYlGn",
    color_col: str = "underservice_score",
    range_color: Optional[Tuple[float, float]] = None,
    hover_data: Optional[Dict] = None,
) -> object:
    """Create generic choropleth map."""
    if px is None:
        raise ImportError("plotly não está disponível para gerar visualizações")

    if not hover_data:
        hover_data = {
            "N_INDIVIDUOS": ":.0f",
            "supply_departures": ":.0f",
            "dep_per_1000_pop": ":.2f",
            "BGRI2021": True,
        }

    if range_color is None:
        score_p5 = float(gdf[color_col].quantile(0.05))
        score_p95 = float(gdf[color_col].quantile(0.90))
        if score_p95 <= score_p5:
            score_p5 = float(gdf[color_col].min())
            score_p95 = float(gdf[color_col].max())
        if score_p95 <= score_p5:
            score_p95 = score_p5 + 1.0
        range_color = (score_p5, score_p95)

    geojson = gdf.to_crs("EPSG:4326").__geo_interface__

    # Build labels mapping so the colorbar and hover show human-friendly names
    labels: Dict[str, str] = {}
    # Label for the color column (main metric)
    if color_col == "underservice_score":
        labels[color_col] = "Índice de Subserviço"
    else:
        labels[color_col] = str(color_col)

    # Common readable labels for other known columns
    labels.update({
        "N_INDIVIDUOS": "População residente",
        "supply_departures": "Passagens no dia",
        "dep_per_1000_pop": "Dep/1000 hab",
        "BGRI2021": "BGRI",
    })

    fig = px.choropleth(
        gdf,
        geojson=geojson,
        locations="BGRI2021",
        featureidkey="properties.BGRI2021",
        color=color_col,
        hover_data=hover_data,
        color_continuous_scale=color_scale,
        range_color=range_color,
        labels=labels,
    )
    if title:
        fig.update_layout(title={"text": title})
    else:
        fig.update_layout(title={"text": ""})
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 10, "b": 0})

    return fig


def create_choropleth_map(
    merged: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "RdYlGn",
) -> object:
    resolve_reference_day(day_str)
    return _create_choropleth_generic(merged, None, color_scale)


def create_2km_choropleth_map(
    merged_2km: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "RdYlGn",
) -> object:
    resolve_reference_day(day_str)
    return _create_choropleth_generic(
        merged_2km,
        None,
        color_scale,
    )

def create_population_heatmap(
    merged: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "RdYlGn",
) -> object:
    return _create_choropleth_generic(
        merged,
        None,
        color_scale,
        color_col="N_INDIVIDUOS",
        hover_data={
            "N_INDIVIDUOS": ":.0f",
            "BGRI2021": True,
        },
    )
