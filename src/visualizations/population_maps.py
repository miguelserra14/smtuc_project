from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
from config import POPULATION_STADIUM_MAP_RADIUS_M
from overlap.transit import resolve_reference_day

try:
    import plotly.express as px
except Exception:  # pragma: no cover - optional dependency guard
    px = None


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Casas decimais mantidas nas coordenadas do GeoJSON embutido no HTML. 6 casas decimais
# equivalem a ~11cm de precisão em Coimbra - muito acima do que um mapa web consegue sequer
# desenhar - mas os polígonos BGRI vêm de `geopandas` com precisão float64 completa (~15
# dígitos), o que quase duplicava o tamanho do HTML gerado sem qualquer ganho visual.
_GEOJSON_COORD_PRECISION = 6


def _read_template(template_name: str) -> str:
    template_path = _TEMPLATE_DIR / template_name
    return template_path.read_text(encoding="utf-8")


def _round_coordinates(coords: Any, ndigits: int = _GEOJSON_COORD_PRECISION) -> Any:
    """Arredonda recursivamente coordenadas GeoJSON (listas/tuplos aninhados de [lon, lat])."""
    if isinstance(coords, (int, float)):
        return round(coords, ndigits)
    if isinstance(coords, (list, tuple)):
        return [_round_coordinates(c, ndigits) for c in coords]
    return coords


def _simplify_geojson_precision(geojson: Dict[str, Any]) -> Dict[str, Any]:
    """Reduz a precisão das coordenadas de todas as features de um dict `__geo_interface__`,
    sem alterar a estrutura - só corta dígitos irrelevantes para a renderização no browser."""
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry")
        if geometry and "coordinates" in geometry:
            geometry["coordinates"] = _round_coordinates(geometry["coordinates"])
    return geojson


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
    poi_df: Optional[pd.DataFrame] = None,
) -> str:
    """Create a single HTML dashboard that embeds the three main population visualizations.

    `stadium_radius_m` deve corresponder ao `distance_m` já usado para filtrar `merged_2km`
    (via `filter_zones_by_distance`) - só controla o texto do painel ("Estádio a X km"), não
    volta a filtrar os dados.

    `poi_df` (opcional) é o resultado de `population.data_processing.compute_poi_underservice`
    - se passado, os dois painéis de índice de subserviço (choropleth geral e "Estádio a X
    km") ganham um botão "Com POI"/"Sem POI" para sobrepor os polos de emprego/locais
    concorridos de confiança boa/média. Sem `poi_df`, os painéis ficam exatamente como antes
    (sem botão nenhum) - a camada é opcional em todos os sentidos: no clique E na chamada.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    heatmap_fig = create_population_heatmap(merged, day_str, color_scale="RdYlGn")
    choropleth_fig = create_choropleth_map(merged, day_str, color_scale="YlOrRd", poi_df=poi_df)
    stadium_fig = create_2km_choropleth_map(merged_2km, day_str, color_scale="YlOrRd", poi_df=poi_df)

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


# Percentil real usado como teto da escala de cor em `log_color=True` - NÃO o máximo. Testado
# empiricamente: mesmo em log, usar o máximo (253 em Coimbra) como teto deixa quase toda a
# cidade (68% das zonas têm score log < 10% do máximo) comprimida no mesmo tom pálido, porque
# 1-2 zonas atípicas esticam a escala inteira. Bins por quantil (`pd.qcut`) também não resolvem
# isto: testado com 10 grupos de igual contagem, o grupo mais alto continua a juntar 182 zonas
# (9.8%) com scores de 30 a 253 na mesma cor - o problema original não desaparece, só muda de
# forma. Um teto em P98 deixa só ~2% das zonas (as genuinamente mais extremas) saturadas na cor
# máxima, e dá à escala log espaço para diferenciar bem o resto (ver `_log_color_ticks`).
_LOG_COLOR_CEIL_PERCENTILE = 0.98


def _log_color_ticks(real_values: pd.Series, ceiling: float) -> Tuple[List[float], List[str]]:
    """Marcas do colorbar (em espaço log1p, rotuladas com o valor real) para um mapa com
    `log_color=True`. `ceiling` é o valor real onde a escala satura (`_LOG_COLOR_CEIL_PERCENTILE`)
    - acima disso todas as zonas mostram a cor mais intensa, por isso a última marca leva "≥"."""
    candidates = sorted({
        round(v)
        for v in [
            0.0,
            float(real_values.quantile(0.5)),
            float(real_values.quantile(0.9)),
            ceiling,
        ]
        if pd.notna(v)
    })
    tickvals = [float(np.log1p(v)) for v in candidates]
    # A última marca (sempre o teto, por `candidates` estar ordenado) leva "≥": arredondar o
    # teto para inteiro podia empatar/ficar abaixo do valor de `ceiling` usado no filtro acima,
    # por isso marcamos por posição em vez de comparar valores.
    ticktext = [f"{v:,.0f}" for v in candidates]
    if ticktext:
        ticktext[-1] = f"≥{ticktext[-1]}"
    return tickvals, ticktext


def _create_choropleth_generic(
    gdf: gpd.GeoDataFrame,
    title: str | None = None,
    color_scale: str = "RdYlGn",
    color_col: str = "underservice_score",
    range_color: Optional[Tuple[float, float]] = None,
    hover_data: Optional[Dict] = None,
    log_color: bool = False,
) -> object:
    """Create generic choropleth map.

    `log_color=True` colore pelo logaritmo (`log1p`) de `color_col`, com o teto da escala
    fixado em `_LOG_COLOR_CEIL_PERCENTILE` (não no máximo real) - mantendo o hover e a legenda
    do colorbar com os valores reais (via `_log_color_ticks`). O índice de subserviço é uma
    cauda longa (mediana ~0.3, P90 ~29, máximo ~250 em Coimbra): em escala linear com teto no
    P90, todo o "pior" decil (scores 29 a 253, gravidades bem diferentes entre si) fica pintado
    da mesma cor máxima. Em log mas com teto no máximo real, o problema inverte-se - 1-2 zonas
    atípicas esticam a escala e quase todo o resto (68% das zonas) fica comprimido no mesmo tom
    pálido. Combinar log + teto em P98 evita as duas distorções: só as zonas genuinamente mais
    extremas (~2%) saturam, e o resto da escala fica com espaço para diferenciar."""
    if px is None:
        raise ImportError("plotly não está disponível para gerar visualizações")

    if not hover_data:
        hover_data = {
            "N_INDIVIDUOS": ":.0f",
            "supply_departures": ":.0f",
            "dep_per_1000_pop": ":.2f",
            "BGRI2021": True,
        }
    else:
        hover_data = dict(hover_data)

    plot_col = color_col
    if log_color:
        plot_col = f"__{color_col}_log"
        gdf = gdf.assign(**{plot_col: np.log1p(gdf[color_col].clip(lower=0))})
        # Sem isto, o Plotly mostraria o valor transformado (log) no hover em vez do índice
        # real - escondemos a coluna log e mostramos explicitamente a coluna original.
        hover_data[plot_col] = False
        hover_data.setdefault(color_col, ":.1f")

    log_ceiling_real: float | None = None
    if log_color:
        log_ceiling_real = float(gdf[color_col].quantile(_LOG_COLOR_CEIL_PERCENTILE))
    if range_color is None:
        if log_color:
            lo = float(gdf[plot_col].min())
            hi = float(np.log1p(max(log_ceiling_real, 0.0)))
        else:
            lo = float(gdf[color_col].quantile(0.05))
            hi = float(gdf[color_col].quantile(0.90))
            if hi <= lo:
                lo = float(gdf[color_col].min())
                hi = float(gdf[color_col].max())
        if hi <= lo:
            hi = lo + 1.0
        range_color = (lo, hi)

    geojson = _simplify_geojson_precision(gdf.to_crs("EPSG:4326").__geo_interface__)

    # Build labels mapping so the colorbar and hover show human-friendly names
    labels: Dict[str, str] = {}
    # Label for the color column (main metric)
    if color_col == "underservice_score":
        labels[color_col] = "Índice de Subserviço"
    else:
        labels[color_col] = str(color_col)
    if plot_col != color_col:
        # Tem de ser um texto DIFERENTE do label de `color_col`: o Plotly Express deduplica
        # linhas do hover por texto de label, e como `plot_col` está escondido (hover_data
        # ...=False), um label igual faz com que a linha do valor real também desapareça.
        labels[plot_col] = f"{labels[color_col]} (log, uso interno)"

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
        color=plot_col,
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

    if log_color:
        tickvals, ticktext = _log_color_ticks(gdf[color_col], log_ceiling_real)
        fig.update_layout(
            coloraxis_colorbar=dict(
                title=labels.get(color_col, color_col),
                tickvals=tickvals,
                ticktext=ticktext,
            )
        )

    return fig


def _add_poi_overlay(fig: object, poi_df: Optional[pd.DataFrame]) -> None:
    """Sobrepõe os polos de interesse (`poi_df`) a um choropleth de índice de subserviço,
    escondidos por omissão, com um botão a alternar "Com POI"/"Sem POI".

    `poi_df` já deve vir filtrado a confiança boa/média (ver
    `data_processing.compute_poi_underservice`) e ter as colunas `nome`, `lat`, `lon`,
    `pessoas_estimadas`, `supply_departures`, `poi_underservice_score`, `confianca`. Não faz
    nada (função no-op) se `poi_df` for None/vazio - é assim que a camada fica opcional
    também ao nível da chamada, não só do clique no botão.
    """
    if poi_df is None or poi_df.empty:
        return

    hover_text = [
        f"{row['nome']}<br>"
        f"Pessoas/dia (estimado): {row['pessoas_estimadas']:,.0f}<br>"
        f"Partidas no dia (raio de captação): {row['supply_departures']:,.0f}<br>"
        f"Índice de subserviço (POI): {row['poi_underservice_score']:.1f}<br>"
        f"Confiança da estimativa: {row['confianca']}"
        for _, row in poi_df.iterrows()
    ]

    fig.add_scattergeo(
        lat=poi_df["lat"],
        lon=poi_df["lon"],
        mode="markers",
        marker=dict(
            size=11,
            symbol="diamond",
            color=poi_df["poi_underservice_score"],
            colorscale="YlOrRd",
            line=dict(width=1.2, color="#000000"),
            showscale=False,
        ),
        text=hover_text,
        hoverinfo="text",
        name="Polos de interesse",
        visible=False,
    )

    poi_trace_index = len(fig.data) - 1
    existing_updatemenus = list(fig.layout.updatemenus) if fig.layout.updatemenus else []
    fig.update_layout(
        updatemenus=existing_updatemenus + [
            dict(
                type="buttons",
                direction="right",
                x=0.0,
                y=1.08,
                xanchor="left",
                yanchor="top",
                showactive=True,
                buttons=[
                    dict(label="Sem POI", method="restyle", args=[{"visible": False}, [poi_trace_index]]),
                    dict(label="Com POI", method="restyle", args=[{"visible": True}, [poi_trace_index]]),
                ],
            )
        ]
    )


def create_choropleth_map(
    merged: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "RdYlGn",
    poi_df: Optional[pd.DataFrame] = None,
) -> object:
    resolve_reference_day(day_str)
    fig = _create_choropleth_generic(merged, None, color_scale, log_color=True)
    _add_poi_overlay(fig, poi_df)
    return fig


def create_2km_choropleth_map(
    merged_2km: gpd.GeoDataFrame,
    day_str: str,
    color_scale: str = "RdYlGn",
    poi_df: Optional[pd.DataFrame] = None,
) -> object:
    resolve_reference_day(day_str)
    fig = _create_choropleth_generic(
        merged_2km,
        None,
        color_scale,
        log_color=True,
    )
    _add_poi_overlay(fig, poi_df)
    return fig

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
