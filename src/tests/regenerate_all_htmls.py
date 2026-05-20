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
    generate_connection_visualizations,
    _write_folium_html,
)
from src.config import CATCHMENT_M, STADIUM_RADIUS_M, OUTPUTS_POPULATION_DIR, OUTPUTS_INTEGRATION_DIR, STADIUM_COORD
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
        _write_folium_html(fig_map, reachability_html)
        print(f"[SUCCESS] Mapa de reachability: {reachability_html}")
        
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

