"""Mapa base (tiles) de todos os mapas Folium - único sítio onde se escolhe o fornecedor.

Desde setembro de 2026 a CARTO exige chave em TODOS os tiles de basemaps.cartocdn.com: sem ela
responde HTTP 200 com um tile marcado "API KEY REQUIRED / carto.com/basemaps/apikey", por isso o
Leaflet não regista erro nenhum e o mapa parece "partido" só no browser. A chave é gratuita para
uso não comercial (sem conta): https://carto.com/basemaps/apikey -> `BASEMAP_CARTO_KEY` em
src/config_local.py. Sem chave usa-se o Esri World Light Gray (cinzento claro como o Positron,
não pede chave), com a camada de nomes por cima.
"""
from __future__ import annotations

from urllib.parse import quote

import config

try:
    import folium
except Exception:  # pragma: no cover - optional dependency guard
    folium = None

BASEMAP_LAYER_NAME = "Mapa base"

# Forma documentada pela CARTO (https://carto.com/basemaps/apikey): sem subdomínios, chave em ?key=.
CARTO_POSITRON_URL = "https://basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png?key="
CARTO_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
    '&copy; <a href="https://carto.com/attributions">CARTO</a>'
)

_ESRI_CANVAS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas"
ESRI_GRAY_BASE_URL = _ESRI_CANVAS + "/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
ESRI_GRAY_LABELS_URL = _ESRI_CANVAS + "/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
ESRI_ATTRIBUTION = (
    "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, "
    "and the GIS User Community"
)
# O Light Gray Canvas só tem tiles até ao zoom 16; acima disso o Leaflet amplia os do 16 em vez
# de pedir tiles que não existem (ficava em branco ao fazer zoom na zona do estádio).
ESRI_GRAY_MAX_NATIVE_ZOOM = 16
MAX_ZOOM = 19


def carto_tiles_url(key: str) -> str:
    """URL de tiles do Positron com a chave já embutida (o Leaflet rebentava com um {key} por preencher)."""
    return CARTO_POSITRON_URL + quote(key.strip(), safe="")


def add_basemap(m: object) -> None:
    """Junta ao mapa o mapa base: Positron da CARTO se houver chave, senão Esri Light Gray."""
    if folium is None:
        raise ImportError("folium não está disponível para gerar visualizações de mapa")
    key = (config.BASEMAP_CARTO_KEY or "").strip()
    if key:
        folium.TileLayer(
            tiles=carto_tiles_url(key),
            attr=CARTO_ATTRIBUTION,
            name=BASEMAP_LAYER_NAME,
            max_zoom=MAX_ZOOM,
        ).add_to(m)
        return
    folium.TileLayer(
        tiles=ESRI_GRAY_BASE_URL,
        attr=ESRI_ATTRIBUTION,
        name=BASEMAP_LAYER_NAME,
        max_zoom=MAX_ZOOM,
        max_native_zoom=ESRI_GRAY_MAX_NATIVE_ZOOM,
    ).add_to(m)
    # Nomes de ruas/localidades: o Base do Esri não os tem (o Positron tinha). Fica fora do
    # controlo de camadas para não aparecer como mais uma caixa ao lado das linhas.
    folium.TileLayer(
        tiles=ESRI_GRAY_LABELS_URL,
        attr=ESRI_ATTRIBUTION,
        name="Nomes",
        overlay=True,
        control=False,
        max_zoom=MAX_ZOOM,
        max_native_zoom=ESRI_GRAY_MAX_NATIVE_ZOOM,
    ).add_to(m)


def new_map(location: object, zoom_start: int = 13, **kwargs: object) -> object:
    """`folium.Map` com o mapa base do projeto (usar sempre em vez de `tiles="cartodbpositron"`)."""
    if folium is None:
        raise ImportError("folium não está disponível para gerar visualizações de mapa")
    m = folium.Map(location=location, zoom_start=zoom_start, tiles=None, max_zoom=MAX_ZOOM, **kwargs)
    add_basemap(m)
    return m
