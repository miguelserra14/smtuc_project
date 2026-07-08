from __future__ import annotations

from pathlib import Path
from typing import Iterable

try:
    import folium
    from folium import FeatureGroup
except Exception:  # pragma: no cover - optional dependency
    folium = None

import pandas as pd

from config import STADIUM_COORD, STADIUM_RADIUS_M, STADIUM_MIN_EXTENSION_PCT
from gtfs_processing.gtfs import load_gtfs
from overlap.overlap_db import _line_to_route_ids, _iter_route_direction_stop_arrays
from visualizations.io import _write_folium_html


def _safe_center(lat: float, lon: float) -> tuple[float, float]:
    try:
        return float(lat), float(lon)
    except Exception:
        return 40.203809, -8.407904


def create_overlap_lines_map(
    output_path: Path | str,
    metrics_csv: str | Path = "outputs/overlap/line_metrics_db.csv",
    smtuc_dataset: str = "smtuc",
    metrobus_dataset: str = "metrobus",
    top_n: int = 5,
    bottom_n: int = 5,
    stadium_n: int = 5,
    stadium_radius_m: float = STADIUM_RADIUS_M,
    stadium_min_extension_pct: float = STADIUM_MIN_EXTENSION_PCT,
) -> str:
    """Create a standalone HTML map showing Metrobus and selected SMTUC lines (top/bottom overlap).

    The map is saved to `output_path` and includes layer control so users can toggle lines.
    """
    if folium is None:
        raise ImportError("folium não disponível para gerar o mapa de linhas")

    metrics_path = Path(metrics_csv)
    if not metrics_path.exists():
        raise FileNotFoundError(f"Metrics CSV not found: {metrics_path}")

    df = pd.read_csv(metrics_path)
    if df.empty:
        raise ValueError("Metrics CSV is empty")

    df = df.copy()
    # Ensure `line` is string
    df["line"] = df["line"].astype(str)

    top_lines = list(df.sort_values(["overlap_pct", "overlap_extension_m"], ascending=False).head(top_n)["line"].astype(str))
    bottom_lines = list(df.sort_values(["overlap_pct", "overlap_extension_m"], ascending=True).head(bottom_n)["line"].astype(str))

    # Linhas com pelo menos `stadium_min_extension_pct`% da extensão dentro de `stadium_radius_m`
    # do estádio, ordenadas por menor overlap - mesma regra usada em line_low_overlap_near_stadium_top.
    stadium_lines: list[str] = []
    if {"radius_m", "radius_extension_pct"}.issubset(df.columns):
        near_stadium = df[
            (df["radius_extension_pct"].fillna(-1) >= stadium_min_extension_pct)
            & (df["radius_m"].sub(stadium_radius_m).abs().fillna(float("inf")) <= 1e-6)
        ]
        stadium_lines = list(
            near_stadium.sort_values(["overlap_pct", "overlap_extension_m"], ascending=True)
            .head(stadium_n)["line"]
            .astype(str)
        )

    # Load GTFS
    gtfs_smtuc = load_gtfs(dataset=smtuc_dataset)
    gtfs_metro = load_gtfs(dataset=metrobus_dataset)

    center = _safe_center(*STADIUM_COORD)
    m = folium.Map(location=center, zoom_start=13, tiles="cartodbpositron")

    # Metrobus layer: prefer shapes if available
    metro_fg = FeatureGroup(name="Metrobus (shapes)", show=True)
    try:
        if hasattr(gtfs_metro, "shapes") and not gtfs_metro.shapes.empty:
            for sid, grp in gtfs_metro.shapes.groupby("shape_id"):
                pts = list(zip(grp["shape_pt_lat"].astype(float), grp["shape_pt_lon"].astype(float)))
                if len(pts) >= 2:
                    folium.PolyLine(pts, color="#1976d2", weight=3, opacity=0.8).add_to(metro_fg)
        else:
            # Sem shapes.txt: liga as paragens pela ordem real dos trips (stop_sequence de um
            # trip representativo por sentido), tal como já fazemos para as linhas SMTUC, em vez
            # de deixar só pontos soltos.
            try:
                if hasattr(gtfs_metro, "routes") and not gtfs_metro.routes.empty:
                    metro_route_ids = gtfs_metro.routes["route_id"].astype(str).tolist()
                    for rid in metro_route_ids:
                        for lat_arr, lon_arr, _stop_ids, _count in _iter_route_direction_stop_arrays(gtfs_metro, rid):
                            pts = list(zip(lat_arr.tolist(), lon_arr.tolist()))
                            if len(pts) >= 2:
                                folium.PolyLine(pts, color="#1976d2", weight=3, opacity=0.8).add_to(metro_fg)
            except Exception:
                pass

            try:
                if hasattr(gtfs_metro, "stops") and not gtfs_metro.stops.empty:
                    stops = gtfs_metro.stops.dropna(subset=["stop_lat", "stop_lon"])
                    for _, s in stops.iterrows():
                        folium.CircleMarker(location=(float(s.stop_lat), float(s.stop_lon)), radius=3, color="#1976d2", fill=True, fillOpacity=0.9).add_to(metro_fg)
            except Exception:
                # If even stops fail, do nothing
                pass
    except Exception:
        pass
    m.add_child(metro_fg)

    # Estádio: marcador de referência (usado no filtro "linhas junto ao estádio" a <=stadium_radius_m)
    stadium_fg = FeatureGroup(name="Estádio", show=True)
    folium.CircleMarker(
        location=center,
        radius=6,
        color="#000000",
        weight=1,
        fill=True,
        fill_color="#ffd600",
        fill_opacity=1.0,
        popup="Estádio",
    ).add_to(stadium_fg)
    m.add_child(stadium_fg)

    # Helper to add SMTUC line feature groups
    def _add_line_groups(lines: Iterable[str], color: str, prefix: str) -> None:
        for line in lines:
            fg = FeatureGroup(name=f"{prefix} {line}", show=False)
            try:
                # get route ids for this line
                line_map = _line_to_route_ids(gtfs_smtuc)
                route_ids = line_map.get(str(line), [])
                for rid in route_ids:
                    for lat_arr, lon_arr, _stop_ids, _count in _iter_route_direction_stop_arrays(gtfs_smtuc, rid):
                        pts = list(zip(lat_arr.tolist(), lon_arr.tolist()))
                        if len(pts) >= 2:
                            folium.PolyLine(pts, color=color, weight=3, opacity=0.85).add_to(fg)
            except Exception:
                # best-effort: skip if anything fails
                continue
            m.add_child(fg)

    _add_line_groups(top_lines, "#2e7d32", "Top")
    _add_line_groups(bottom_lines, "#b71c1c", "Bottom")
    _add_line_groups(stadium_lines, "#f57c00", "Estádio")

    folium.LayerControl(collapsed=False).add_to(m)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Prepare lines data (coords + metrics) to embed for interactive selection
    try:
        metrics_df = pd.read_csv(metrics_path).fillna("")
        # only numeric-ish lines
        metrics_df["line"] = metrics_df["line"].astype(str)
    except Exception:
        metrics_df = pd.DataFrame()

    lines_data: dict = {}
    try:
        line_map_all = _line_to_route_ids(gtfs_smtuc)
        for line in sorted(set(metrics_df["line"].tolist())):
            if line not in line_map_all:
                continue
            route_ids = line_map_all.get(line, [])
            # Guarda TODOS os sentidos/variantes da linha (não só o mais comprido) - cada um
            # vira um segmento da mesma polyline multi-parte no mapa.
            directions_coords: list[list[tuple[float, float]]] = []
            for rid in route_ids:
                for lat_arr, lon_arr, _stop_ids, _count in _iter_route_direction_stop_arrays(gtfs_smtuc, rid):
                    if len(lat_arr) >= 2:
                        directions_coords.append(list(zip(lat_arr.tolist(), lon_arr.tolist())))
            if not directions_coords:
                continue
            row = metrics_df[metrics_df["line"] == line].iloc[0].to_dict() if not metrics_df.empty else {}
            lines_data[line] = {
                "coords": directions_coords,
                "overlap_pct": row.get("overlap_pct", ""),
                "overlap_m": row.get("overlap_extension_m", ""),
                "extension_m": row.get("line_extension_m", ""),
            }
    except Exception:
        lines_data = {}

    # embed a small control and the lines_data JSON into the page
    try:
        import json

        control_html = """
        <div id="line-select-control" style="position: absolute; bottom: 20px; left: 10px; z-index: 9999; background: rgba(255,255,255,0.95); padding:8px; border-radius:6px; box-shadow:0 1px 6px rgba(0,0,0,0.2); font-size:13px;">
          <div style="margin-bottom:6px; font-weight:600;">Mostrar linha</div>
          <div style="display:flex; gap:6px;">
            <input id="line-input" placeholder="Número da linha" style="width:110px;padding:4px;border:1px solid #ccc;border-radius:4px" />
            <button id="line-show-btn" style="padding:4px 8px;border-radius:4px;border:none;background:#1976d2;color:#fff">Mostrar</button>
            <button id="line-clear-btn" style="padding:4px 8px;border-radius:4px;border:none;background:#999;color:#fff">Limpar</button>
          </div>
          <div id="line-info" style="margin-top:6px;font-size:12px;color:#222"></div>
        </div>
        <script>
          var __LINES_DATA__ = __LINES_DATA_JSON__;
          (function(){
            var selectedLayer = null;
            var map = null;
            function showLine(line){
              if(!line || !map) return;
              var data = __LINES_DATA__[line] || __LINES_DATA__[line.toUpperCase()];
              if(!data) { document.getElementById('line-info').innerText = 'Linha não encontrada'; return; }
              if(selectedLayer){ map.removeLayer(selectedLayer); selectedLayer = null; }
              // data.coords é uma lista de sentidos/variantes; cada um vira um segmento da
              // mesma polyline multi-parte (o Leaflet desenha arrays aninhados como uma única
              // camada com vários troços, incluindo os dois sentidos da linha).
              var latlngs = data.coords.map(function(dir){
                return dir.map(function(p){ return [p[0], p[1]]; });
              });
              selectedLayer = L.polyline(latlngs, {color: '#ff5722', weight: 4, opacity:0.9}).addTo(map);
              map.fitBounds(selectedLayer.getBounds(), {padding:[20,20]});
              var info = 'Linha: ' + line + ' — Overlap: ' + (data.overlap_pct || '-') + ' %, Overlap m: ' + (data.overlap_m || '-') + ', Extensão m: ' + (data.extension_m || '-');
              document.getElementById('line-info').innerText = info;
              selectedLayer.bindPopup(info).openPopup();
            }
            function wire(){
              // Só resolvemos a variável do mapa aqui dentro: por esta altura o script de
              // inicialização do Leaflet gerado pelo folium (que cria a variável do mapa) já
              // correu de certeza, mesmo que apareça fisicamente depois deste bloco no HTML.
              map = __MAP_VAR_NAME__;
              var btn = document.getElementById('line-show-btn');
              var clr = document.getElementById('line-clear-btn');
              var inp = document.getElementById('line-input');
              btn.addEventListener('click', function(){ showLine(inp.value.trim()); });
              inp.addEventListener('keydown', function(e){ if(e.key === 'Enter'){ showLine(inp.value.trim()); }});
              clr.addEventListener('click', function(){ if(selectedLayer){ map.removeLayer(selectedLayer); selectedLayer=null; } document.getElementById('line-info').innerText=''; });
            }
            if(document.readyState === 'loading'){
              document.addEventListener('DOMContentLoaded', wire);
            } else {
              wire();
            }
          })();
        </script>
        """
        control_html = control_html.replace("__LINES_DATA_JSON__", json.dumps(lines_data, ensure_ascii=False))
        control_html = control_html.replace("__MAP_VAR_NAME__", m.get_name())

        # O folium coloca o <script> que cria de facto o objeto do mapa (L.map(...)) DEPOIS do
        # </body> (antes só de </html>). Inserir antes de </body> corria antes de o mapa existir.
        page = m.get_root().render()
        insert_at = page.rfind('</html>')
        if insert_at == -1:
            insert_at = page.rfind('</body>')
        if insert_at != -1:
            new_page = page[:insert_at] + control_html + page[insert_at:]
        else:
            new_page = page + control_html
        out_path.write_text(new_page, encoding='utf-8')
    except Exception:
        # fallback: save map normally
        _write_folium_html(m, out_path)
    return str(out_path)
