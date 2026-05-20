"""
Script para regenerar todos os ficheiros HTML da dashboard.

Uso:
    python src/tests/regenerate_all_htmls.py
    python -m pytest src/tests/regenerate_all_htmls.py --tb=short
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

# Importar as funÃ§Ãµes de geraÃ§Ã£o
from population.data_processing import (
    _next_monday,
    _project_root,
    _require_bgri_data,
    _require_geo_stack,
    compute_underserved_zones,
    filter_zones_by_distance,
)
from overlap.overlap import (
    compute_bgri_reachability_now,
)
from visualizations import (
    create_master_dashboard_html,
    create_population_dashboard_html,
    create_overlap_reachability_map,
        create_overlap_lines_map,
    generate_connection_visualizations,
    _write_folium_html,
)
from visualizations.dashboard import _load_overlap_stats
from src.config import (
    CATCHMENT_M,
    STADIUM_RADIUS_M,
    OUTPUTS_POPULATION_DIR,
    OUTPUTS_INTEGRATION_DIR,
    STADIUM_COORD,
    REACHABILITY_MAX_TRANSFERS,
)
from overlap.transit import build_line_stop_vs_metro_table, resolve_reference_day


def _require_dataset(dataset: str) -> Path:
    """Verifica se um dataset GTFS estÃ¡ disponÃ­vel."""
    root = _project_root()
    d = root / "data" / dataset
    required = ["routes.txt", "trips.txt", "stops.txt", "stop_times.txt"]
    if not d.exists() or any(not (d / f).exists() for f in required):
        print(f"[WARNING] Dataset GTFS invÃ¡lido/incompleto: {d}")
        return None
    return d


def regenerate_population_htmls() -> None:
    """Regenera todos os HTMLs da populaÃ§Ã£o (BGRI)."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando HTMLs de PopulaÃ§Ã£o...")
    print("=" * 60)
    
    try:
        _require_geo_stack()
    except Exception as e:
        print(f"[WARNING] Geostack nÃ£o disponÃ­vel: {e}")
        return
    
    try:
        gpkg = _require_bgri_data()
    except Exception as e:
        print(f"[WARNING] Dataset BGRI nÃ£o disponÃ­vel: {e}")
        return
    
    try:
        monday = _next_monday(date.today())
        day_str = monday.strftime("%Y-%m-%d")
        
        print(f"[INFO] Usando data: {day_str}")
        
        # Computar zonas subservidas
        print("[INFO] Computando zonas subservidas...")
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
        
        # Filtrar zonas a 2km do estÃ¡dio
        merged_2km = filter_zones_by_distance(merged, distance_m=STADIUM_RADIUS_M * 2)
        
        # Criar dashboard de populaÃ§Ã£o
        print("[INFO] Gerando dashboard de populaÃ§Ã£o...")
        dashboard_html = out_dir / "bgri.html"
        create_population_dashboard_html(
            dashboard_html,
            merged,
            merged_2km,
            day_str,
        )
        print(f"[SUCCESS] Dashboard populaÃ§Ã£o: {dashboard_html}")
        
    except Exception as e:
        print(f"[ERROR] Erro ao regenerar HTMLs de populaÃ§Ã£o: {e}")
        import traceback
        traceback.print_exc()


def regenerate_overlap_htmls() -> None:
    """Regenera HTMLs de overlap/reachability."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando HTMLs de Overlap...")
    print("=" * 60)
    
    try:
        out_dir = _project_root() / "outputs" / "overlap"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        day_str = resolve_reference_day().strftime("%Y-%m-%d")
        print(f"[INFO] Usando data: {day_str}")
        
        # Computar zonas subservidas como base
        print("[INFO] Computando reachability...")
        merged = compute_underserved_zones(day_str=day_str)
        
        # Computar reachability a partir do estÃ¡dio
        reach_gdf = compute_bgri_reachability_now(
            merged_bgri=merged,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            day_str=day_str,
            time_str=None,
            max_transfers=REACHABILITY_MAX_TRANSFERS,
        )
        
        selected_time = str(reach_gdf["reach_time"].iloc[0]) if not reach_gdf.empty else "00:00:00"
        
        # Criar mapa de reachability
        print("[INFO] Gerando mapa de reachability...")
        fig_map = create_overlap_reachability_map(
            reach_gdf=reach_gdf,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            day_str=day_str,
            time_str=selected_time,
        )
        
        reachability_html = out_dir / "overlap_reachability_now.html"
        # Generate footer HTML with overlap stats tables and append below the map
        stats = _load_overlap_stats()
        footer_html = ""
        if stats:
            try:
                top5 = stats.get("top5", [])
                bottom5 = stats.get("bottom5", [])
                bottom5_stadium = stats.get("bottom5_stadium", [])
                temporal = stats.get("temporal_summary", {})

                def _table_html(title, rows):
                    html_rows = """
                    <div style="margin:12px 6px; padding:8px; border-top:1px solid #ddd;">
                      <h3 style="margin:6px 0;">%s</h3>
                      <table style="border-collapse:collapse; width:100%%; font-size:12px">
                        <thead>
                          <tr>
                            <th style="text-align:left; padding:4px; border-bottom:1px solid #ccc">Linha</th>
                            <th style="text-align:right; padding:4px; border-bottom:1px solid #ccc">Overlap %%</th>
                            <th style="text-align:right; padding:4px; border-bottom:1px solid #ccc">Overlap m</th>
                            <th style="text-align:right; padding:4px; border-bottom:1px solid #ccc">Extensão m</th>
                          </tr>
                        </thead>
                        <tbody>
                    """ % (html.escape(title))
                    for r in rows:
                        html_rows += "<tr>"
                        html_rows += f"<td style=\"padding:4px;border-bottom:1px solid #eee\">{html.escape(str(r.get('line','-')))}</td>"
                        html_rows += f"<td style=\"padding:4px;border-bottom:1px solid #eee;text-align:right\">{html.escape(str(r.get('overlap_pct','-')))}</td>"
                        html_rows += f"<td style=\"padding:4px;border-bottom:1px solid #eee;text-align:right\">{html.escape(str(r.get('overlap_m','-')))}</td>"
                        html_rows += f"<td style=\"padding:4px;border-bottom:1px solid #eee;text-align:right\">{html.escape(str(r.get('extension_m','-')))}</td>"
                        html_rows += "</tr>"
                    html_rows += "</tbody></table></div>"
                    return html_rows

                footer_parts = []
                footer_parts.append(_table_html("Top 5: linhas com maior overlap espacial", top5))
                footer_parts.append(_table_html("Bottom 5 (estádios): possíveis redundâncias locais", bottom5_stadium))

                temporal_html = "<div style=\"margin:12px 6px;padding:8px;border-top:1px solid #ddd;font-size:12px\">"
                temporal_html += f"<h3 style=\"margin:6px 0\">Resumo temporal</h3>"
                temporal_html += f"<div>Total candidatos espaciais: {temporal.get('total_spatial_candidates',0)}</div>"
                temporal_html += f"<div>Estações com overlap temporal: {temporal.get('temporal_overlap_stations',0)}</div>"
                temporal_html += f"<div>Ocorrências temporais: {temporal.get('temporal_overlap_times',0)}</div>"
                temporal_html += f"<div>% sobre candidatos espaciais: {temporal.get('temporal_overlap_pct',0)}%</div>"
                temporal_html += f"<div>Tempo máximo temporal configurado (min): {temporal.get('TEMPORAL_OVERLAP_MAX_MIN')}</div>"
                temporal_html += f"<div>Distância de caminhada (m) usada p/ overlap espacial: {temporal.get('walk_distance_threshold',0):.1f}</div>"
                temporal_html += "</div>"

                footer_html = "<div id=\"overlap-stats-footer\" style=\"max-width:980px;margin:8px auto 28px;background:#fff;padding:6px;border:1px solid #ddd;border-radius:4px;\">" + "\n".join(footer_parts) + temporal_html + "</div>"
            except Exception:
                footer_html = ""

        _write_folium_html(fig_map, reachability_html, footer_html=footer_html)
        print(f"[SUCCESS] Mapa de reachability: {reachability_html}")

        # Also create a standalone overlap lines map (top/bottom lines + metro)
        try:
            lines_map_html = out_dir / "overlap_lines_map.html"
            created = create_overlap_lines_map(output_path=lines_map_html)
            print(f"[SUCCESS] Mapa de linhas (overlap): {created}")
        except Exception as e:
            print(f"[WARNING] Não foi possível gerar mapa de linhas: {e}")
        
    except Exception as e:
        print(f"[ERROR] Erro ao regenerar HTMLs de overlap: {e}")
        import traceback
        traceback.print_exc()


def regenerate_integration_htmls() -> None:
    """Regenera HTMLs de integraÃ§Ã£o (Portagem e Portela)."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando HTMLs de IntegraÃ§Ã£o...")
    print("=" * 60)
    
    # Verificar datasets
    if not _require_dataset("smtuc") or not _require_dataset("metrobus"):
        print("[WARNING] Datasets GTFS nÃ£o disponÃ­veis. Pulando integraÃ§Ã£o.")
        return
    
    try:
        day_str = resolve_reference_day().strftime("%Y-%m-%d")
        print(f"[INFO] Usando data: {day_str}")
        
        # Portagem: Linhas 54 + 38 (Portela â†’ Portagem)
        # Generates: l54_38_wt.csv, line_54_38_bus_portagem_metro_portagem.csv, etc.
        print("\n[INFO] Gerando integração Portagem (Portela → Portagem) com linhas 54 + 38...")
        try:
            results = generate_connection_visualizations(
                metro_stop_ref="Portagem",
                bus_stop_ref="Portagem",
                line_number=["54", "38"],
                day_str=day_str,
                metro_origin_ref="Portela",
                bus_origin_ref="Portela do Mondego",
                output_prefix="l54_38",  # Explicitly use prefix for lines 54+38
                output_subdir="portagem",
                fixed_html_name="l54_38_all.html",
            )
            print(f"[SUCCESS] IntegraÃ§Ã£o Portagem (54+38): {results.get('html_path', 'N/A')}")
        except Exception as e:
            print(f"[WARNING] Erro na integraÃ§Ã£o Portagem (54+38): {e}")
        
        # Portela: Linha 54 (Portagem â†’ Portela)
        # Generates: l54_wt.csv, line_54_bus_portela_do_mondego_metro_portela.csv, etc.
        print("\n[INFO] Gerando integração Portela (Portagem → Portela) com linha 54...")
        try:
            results = generate_connection_visualizations(
                metro_stop_ref="Portela",
                bus_stop_ref="Portela do Mondego",
                line_number="54",
                day_str=day_str,
                metro_origin_ref="Portagem",
                bus_origin_ref="Portagem",
                output_prefix="l54",  # Explicitly use prefix for line 54 only
                output_subdir="portela",
                fixed_html_name="l54_all.html",
            )
            print(f"[SUCCESS] IntegraÃ§Ã£o Portela (54): {results.get('html_path', 'N/A')}")
        except Exception as e:
            print(f"[WARNING] Erro na integraÃ§Ã£o Portela (54): {e}")
        
    except Exception as e:
        print(f"[ERROR] Erro ao regenerar HTMLs de integraÃ§Ã£o: {e}")
        import traceback
        traceback.print_exc()


def regenerate_master_dashboard() -> None:
    """Regenera o dashboard master."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando Dashboard Master...")
    print("=" * 60)
    
    try:
        root = _project_root()
        dashboard_path = root / "outputs" / "dashboard.html"
        
        print("[INFO] Gerando dashboard master...")
        created = create_master_dashboard_html(dashboard_path)
        print(f"[SUCCESS] Dashboard master: {created}")
        
    except Exception as e:
        print(f"[ERROR] Erro ao regenerar dashboard master: {e}")
        import traceback
        traceback.print_exc()


def main() -> None:
    """Executa regeneraÃ§Ã£o completa de todos os HTMLs."""
    print("\n" + "=" * 60)
    print("REGENERANDO TODOS OS HTMLS DA DASHBOARD")
    print("=" * 60 + "\n")
    
    # Regenerar em ordem
    regenerate_population_htmls()
    regenerate_overlap_htmls()
    regenerate_integration_htmls()
    regenerate_master_dashboard()
    
    print("\n" + "=" * 60)
    print("[SUCCESS] REGENERAÃ‡ÃƒO CONCLUÃDA!")
    print("=" * 60)
    print("\n[INFO] Todos os ficheiros HTML foram atualizados em outputs/")
    print("[INFO] Abrir: file:///path/para/projeto/outputs/dashboard.html\n")


if __name__ == "__main__":
    main()

