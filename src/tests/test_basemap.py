"""Mapa base dos mapas Folium: CARTO só com chave (sem ela os tiles saem com "API KEY REQUIRED")."""
from __future__ import annotations

import pytest

pytest.importorskip("folium")

import config
from visualizations import basemap


def _html(monkeypatch: pytest.MonkeyPatch, key: str | None) -> str:
    monkeypatch.setattr(config, "BASEMAP_CARTO_KEY", key)
    return basemap.new_map([40.2, -8.4]).get_root().render()


def test_sem_chave_usa_esri_e_nunca_carto(monkeypatch):
    html = _html(monkeypatch, None)
    assert "World_Light_Gray_Base" in html
    assert "World_Light_Gray_Reference" in html
    assert "cartocdn" not in html
    assert "cartodbpositron" not in html


def test_chave_em_branco_conta_como_sem_chave(monkeypatch):
    assert "cartocdn" not in _html(monkeypatch, "   ")


def test_com_chave_usa_carto_com_a_chave_no_url(monkeypatch):
    html = _html(monkeypatch, "abc123")
    assert "basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png?key=abc123" in html
    assert "World_Light_Gray" not in html
    assert "carto.com/attributions" in html


def test_chave_e_codificada_no_url():
    # Um {key} ou caracteres especiais por codificar partiam o template do Leaflet.
    assert basemap.carto_tiles_url(" a/b&c ").endswith("?key=a%2Fb%26c")
