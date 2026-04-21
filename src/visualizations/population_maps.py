from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, Optional, Tuple

import geopandas as gpd

try:
    import plotly.express as px
except Exception:  # pragma: no cover - optional dependency guard
    px = None


def create_population_dashboard_html(output_path: Path | str, title: str = "BGRI Coimbra — Painel de População") -> str:
        """Create a single HTML dashboard that embeds the three main population visualizations."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        heatmap_rel = "bgri_population_heatmap.html"
        choropleth_rel = "bgri_underservice_choropleth.html"
        stadium_rel = "2kmstadium.html"

        page = f"""<!DOCTYPE html>
<html lang=\"pt\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <meta name=\"color-scheme\" content=\"light only\" />
    <title>{html.escape(title)}</title>
    <style>
        :root {{
            --bg: #f7f8fa;
            --card: #ffffff;
            --ink: #222222;
            --muted: #5a6573;
            --border: #dde2e8;
            --accent: #145da0;
            color-scheme: light only;
        }}
        html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--ink); font-family: Segoe UI, Tahoma, sans-serif; }}
        .container {{ max-width: 1360px; margin: 0 auto; padding: 24px 16px 40px; }}
        h1 {{ margin: 0 0 8px; color: var(--accent); font-size: 1.55rem; }}
        p {{ margin: 0 0 20px; color: var(--muted); }}
        .panel {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-bottom: 16px; }}
        .panel h2 {{ margin: 0; padding: 12px 14px; font-size: 1rem; border-bottom: 1px solid var(--border); }}
        .panel iframe {{ width: 100%; height: 700px; border: 0; display: block; background: #fff; }}
        @media (max-width: 860px) {{
            .panel iframe {{ height: 520px; }}
            h1 {{ font-size: 1.25rem; }}
        }}
    </style>
</head>
<body>
    <main class=\"container\">
        <h1>{html.escape(title)}</h1>
        <p>Painel agregado com heatmap de população e duas visualizações de subserviço.</p>
        <section class=\"panel\">
            <h2>Heatmap de população</h2>
            <iframe src=\"{heatmap_rel}\" loading=\"lazy\" title=\"Heatmap de população\"></iframe>
        </section>
        <section class=\"panel\" style=\"padding: 16px 14px;\">
            <p style=\"margin: 0; color: var(--muted); line-height: 1.45;\">
                O índice de subserviço mede a pressão de serviço em cada BGRI e é calculado por
                <strong>índice de subserviço = população residente / (passagens no dia + 1)</strong>.
                Aqui, <strong>população residente</strong> corresponde a <strong>N_INDIVIDUOS</strong> e
                <strong>passagens no dia</strong> corresponde a <strong>supply_departures</strong>.
                O <strong>+ 1</strong> evita divisões por zero e faz com que zonas sem oferta fiquem com pontuação mais alta,
                enquanto zonas com mais passagens tenham pontuação mais baixa.
            </p>
        </section>
        <section class=\"panel\">
            <h2>Índice de subserviço</h2>
            <iframe src=\"{choropleth_rel}\" loading=\"lazy\" title=\"Índice de subserviço\"></iframe>
        </section>
        <section class=\"panel\">
            <h2>Estádio a 2 km</h2>
            <iframe src=\"{stadium_rel}\" loading=\"lazy\" title=\"Estádio a 2 km\"></iframe>
        </section>
    </main>
</body>
</html>
"""
        output_path.write_text(page, encoding="utf-8")
        return str(output_path)


def _create_choropleth_generic(
    gdf: gpd.GeoDataFrame,
    title: str,
    color_scale: str = "YlOrRd",
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

    fig = px.choropleth(
        gdf,
        geojson=geojson,
        locations="BGRI2021",
        featureidkey="properties.BGRI2021",
        color=color_col,
        hover_data=hover_data,
        title=title,
        color_continuous_scale=color_scale,
        range_color=range_color,
    )
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 50, "b": 0})

    return fig


def create_choropleth_map(
    merged: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "YlOrRd",
) -> object:
    map_title = f"BGRI Coimbra — Índice de Subserviço (dia {day_str}, raio 500m)"
    return _create_choropleth_generic(merged, map_title, color_scale)


def create_2km_choropleth_map(
    merged_2km: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "YlOrRd",
) -> object:
    map_title = f"BGRI Coimbra — Índice de Subserviço (dia {day_str}, raio 2km)"
    return _create_choropleth_generic(
        merged_2km,
        map_title,
        color_scale,
    )


def create_population_heatmap(
    merged: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "RdYlGn",
) -> object:
    map_title = f"BGRI Coimbra — Heatmap de População (dia {day_str})"
    return _create_choropleth_generic(
        merged,
        map_title,
        color_scale,
        color_col="N_INDIVIDUOS",
        hover_data={
            "N_INDIVIDUOS": ":.0f",
            "BGRI2021": True,
        },
    )


def create_scatter_plot(
    scatter_df,
    day_str: str,
) -> object:
    if px is None:
        raise ImportError("plotly não está disponível para gerar visualizações")

    scatter_score_p5 = float(scatter_df["underservice_score"].quantile(0.05))
    scatter_score_p95 = float(scatter_df["underservice_score"].quantile(0.95))
    if scatter_score_p95 <= scatter_score_p5:
        scatter_score_p5 = float(scatter_df["underservice_score"].min())
        scatter_score_p95 = float(scatter_df["underservice_score"].max())
    if scatter_score_p95 <= scatter_score_p5:
        scatter_score_p95 = scatter_score_p5 + 1.0

    fig_scatter = px.scatter(
        scatter_df,
        x="supply_departures",
        y="N_INDIVIDUOS",
        color="underservice_score",
        size="N_INDIVIDUOS",
        hover_name="BGRI2021",
        color_continuous_scale="YlOrRd",
        range_color=(scatter_score_p5, scatter_score_p95),
        title=f"População vs Oferta por BGRI (dia {day_str})",
        labels={
            "supply_departures": "Oferta (n.º de passagens no dia)",
            "N_INDIVIDUOS": "População",
            "underservice_score": "Índice de subserviço",
        },
    )
    fig_scatter.update_traces(
        marker={
            "opacity": 0.9,
            "line": {"color": "black", "width": 0.7},
        },
        selector={"mode": "markers"},
    )
    fig_scatter.update_layout(
        margin={"l": 0, "r": 30, "t": 50, "b": 0},
        plot_bgcolor="white",
        xaxis={
            "gridcolor": "black",
            "showgrid": False,
            "showline": False,
            "zeroline": True,
            "zerolinecolor": "black",
            "zerolinewidth": 2,
            "range": [0, None],
        },
        yaxis={
            "gridcolor": "black",
            "showgrid": False,
            "showline": False,
            "zeroline": True,
            "zerolinecolor": "black",
            "zerolinewidth": 2,
            "range": [0, None],
        },
    )

    return fig_scatter
