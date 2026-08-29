"""
Script para regenerar todos os ficheiros HTML da dashboard.

Uso:
    python src/tests/regenerate_all_htmls.py
    python -m pytest src/tests/regenerate_all_htmls.py --tb=short
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import pandas as pd

# Importar as funÃ§Ãµes de geraÃ§Ã£o
from population.data_processing import (
    _project_root,
    _require_bgri_data,
    _require_geo_stack,
    compute_poi_underservice,
    compute_underserved_zones,
    filter_zones_by_distance,
)
from overlap.overlap import (
    compute_bgri_reachability_now,
)
from overlap.overlap_db import load_line_metrics_db
from visualizations import (
    create_master_dashboard_html,
    create_presentation_dashboard_html,
    create_feednplay_dashboard_html,
    create_population_dashboard_html,
    create_overlap_reachability_map,
        create_overlap_lines_map,
    create_temporal_overlap_breakdown_html,
    generate_connection_visualizations,
    _write_folium_html,
)
from visualizations.dashboard import _load_overlap_stats
from src.config import (
    CATCHMENT_M,
    POPULATION_STADIUM_MAP_RADIUS_M,
    OUTPUTS_POPULATION_DIR,
    OUTPUTS_INTEGRATION_DIR,
    STADIUM_COORD,
    REACHABILITY_MAX_TRANSFERS,
    REACHABILITY_REFERENCE_TIME,
    USE_FIXED_REFERENCE_DAY,
    LINE_54_OPTIMIZED_PHASE_SHIFT_MIN,
    LINE_54_MELHORADO_PHASE_SHIFT_MIN,
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
        # Mesmo dia de referência ("nearest weekday") usado por overlap/integração, para que
        # todos os dashboards gerados na mesma execução reflitam o mesmo dia de serviço GTFS -
        # antes usava-se _next_monday (sempre a próxima segunda), divergindo silenciosamente do
        # dia usado pelas restantes secções.
        day_str = resolve_reference_day().strftime("%Y-%m-%d")

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
        
        # Filtrar zonas ao raio do painel "Estádio a X km" (POPULATION_STADIUM_MAP_RADIUS_M,
        # já em metros - não multiplicar). Propositadamente separado de STADIUM_RADIUS_M, que
        # é partilhado por outras análises (ver comentário em config.py).
        merged_2km = filter_zones_by_distance(merged, distance_m=POPULATION_STADIUM_MAP_RADIUS_M)

        # Camada opcional de polos de emprego/locais concorridos (só confiança boa/média - ver
        # points_of_interest.py) para os painéis de índice de subserviço. Falha graciosamente:
        # sem isto os painéis ficam exatamente como antes, sem o botão "Com POI"/"Sem POI".
        try:
            poi_df = compute_poi_underservice(day_str=day_str, catchment_m=CATCHMENT_M)
        except Exception as e:
            print(f"[WARNING] Não foi possível calcular a camada de pontos de interesse: {e}")
            poi_df = None

        # Criar dashboard de populaÃ§Ã£o
        print("[INFO] Gerando dashboard de populaÃ§Ã£o...")
        dashboard_html = out_dir / "bgri.html"
        create_population_dashboard_html(
            dashboard_html,
            merged,
            merged_2km,
            day_str,
            stadium_radius_m=POPULATION_STADIUM_MAP_RADIUS_M,
            poi_df=poi_df,
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

        # Garantir que outputs/overlap/line_metrics_db.csv está atualizado antes de qualquer
        # coisa que o leia diretamente do disco (_load_overlap_stats, create_overlap_lines_map).
        # load_line_metrics_db valida a assinatura dos dados/parâmetros e só recalcula se algo
        # mudou - não regenera do zero em cada execução.
        print("[INFO] Verificando cache de métricas de linha (line_metrics_db)...")
        load_line_metrics_db()

        day_str = resolve_reference_day().strftime("%Y-%m-%d")
        print(f"[INFO] Usando data: {day_str}")

        # Dia do mapa de isócronas: day_str já reflete a variável global USE_FIXED_REFERENCE_DAY
        # (via resolve_reference_day()), a mesma usada pela integração e pela população - não
        # reintroduzir aqui um fallback próprio, senão o mapa deixa de acompanhar a flag global.
        # A hora só faz sentido fixá-la junto com o dia (REACHABILITY_REFERENCE_TIME): com a
        # flag desligada usa-se "agora", tal como o dia passa a ser dinâmico.
        reach_day_str = day_str
        reach_time_str = REACHABILITY_REFERENCE_TIME if USE_FIXED_REFERENCE_DAY else None
        print(f"[INFO] Isócronas: usando data/hora de referência {reach_day_str} {reach_time_str or '(agora)'}")

        # Computar zonas subservidas como base
        print("[INFO] Computando reachability...")
        merged = compute_underserved_zones(day_str=reach_day_str)

        # Computar reachability a partir do estÃ¡dio
        reach_gdf = compute_bgri_reachability_now(
            merged_bgri=merged,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            day_str=reach_day_str,
            time_str=reach_time_str,
            max_transfers=REACHABILITY_MAX_TRANSFERS,
        )

        selected_time = str(reach_gdf["reach_time"].iloc[0]) if not reach_gdf.empty else "00:00:00"

        # Criar mapa de reachability
        print("[INFO] Gerando mapa de reachability...")
        fig_map = create_overlap_reachability_map(
            reach_gdf=reach_gdf,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            day_str=reach_day_str,
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

        try:
            breakdown_html = out_dir / "overlap_temporal_breakdown.html"
            created = create_temporal_overlap_breakdown_html(output_path=breakdown_html)
            print(f"[SUCCESS] Breakdown overlap temporal: {created}")
        except Exception as e:
            print(f"[WARNING] Não foi possível gerar breakdown de overlap temporal: {e}")

    except Exception as e:
        print(f"[ERROR] Erro ao regenerar HTMLs de overlap: {e}")
        import traceback
        traceback.print_exc()


def regenerate_overlap_fase2_htmls() -> None:
    """Regenera os 2 HTMLs standalone (isócronas + mapa de linhas) com os dados da fase 2
    (data/metrobus_fase2 - Aeminium + ramais Coimbra B/República), para o slide dedicado da
    apresentação. Deliberadamente SEPARADO de `regenerate_overlap_htmls()`: todas as restantes
    visualizações (incluindo o slide "Overlap" original) continuam a usar `metrobus` (dados
    antigos, pré-fase 2) - ver `PRESENTATION_TABS` em presentation_content.py para o porquê. Usa
    ficheiros de saída/cache PRÓPRIOS (sufixo `_fase2`) para não pisar os da versão antiga."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando HTMLs de Overlap (fase 2 - slide dedicado)...")
    print("=" * 60)

    if not _require_dataset("metrobus_fase2"):
        print("[WARNING] Dataset metrobus_fase2 não disponível. A saltar slide da fase 2.")
        return

    try:
        _require_geo_stack()
        gpkg = _require_bgri_data()
    except Exception as e:
        print(f"[WARNING] Geostack/BGRI não disponível - a saltar slide da fase 2: {e}")
        return

    try:
        out_dir = _project_root() / "outputs" / "overlap"
        out_dir.mkdir(parents=True, exist_ok=True)

        print("[INFO] Verificando cache de métricas de linha (fase 2)...")
        load_line_metrics_db(
            db_path=f"{out_dir}/line_metrics_db_fase2.csv",
            metrobus_dataset="metrobus_fase2",
        )

        day_str = resolve_reference_day().strftime("%Y-%m-%d")
        reach_time_str = REACHABILITY_REFERENCE_TIME if USE_FIXED_REFERENCE_DAY else None
        print(f"[INFO] Isócronas (fase 2): usando data/hora de referência {day_str} {reach_time_str or '(agora)'}")

        print("[INFO] Computando reachability (fase 2)...")
        merged_fase2 = compute_underserved_zones(
            day_str=day_str,
            catchment_m=CATCHMENT_M,
            datasets=("smtuc", "metrobus_fase2"),
            bgri_gpkg_path=str(gpkg),
            bgri_layer="BGRI2021_0603",
            population_col="N_INDIVIDUOS",
            output_csv_path=f"{OUTPUTS_POPULATION_DIR}/bgri_transport_gap_fase2.csv",
        )
        reach_gdf_fase2 = compute_bgri_reachability_now(
            merged_bgri=merged_fase2,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            datasets=("smtuc", "metrobus_fase2"),
            day_str=day_str,
            time_str=reach_time_str,
            max_transfers=REACHABILITY_MAX_TRANSFERS,
        )
        selected_time = str(reach_gdf_fase2["reach_time"].iloc[0]) if not reach_gdf_fase2.empty else "00:00:00"

        print("[INFO] Gerando mapa de reachability (fase 2)...")
        fig_map_fase2 = create_overlap_reachability_map(
            reach_gdf=reach_gdf_fase2,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            day_str=day_str,
            time_str=selected_time,
        )
        reachability_html_fase2 = out_dir / "overlap_reachability_now_fase2.html"
        _write_folium_html(fig_map_fase2, reachability_html_fase2)
        print(f"[SUCCESS] Mapa de reachability (fase 2): {reachability_html_fase2}")

        lines_map_html_fase2 = out_dir / "overlap_lines_map_fase2.html"
        created = create_overlap_lines_map(
            output_path=lines_map_html_fase2,
            metrics_csv=f"{out_dir}/line_metrics_db_fase2.csv",
            metrobus_dataset="metrobus_fase2",
        )
        print(f"[SUCCESS] Mapa de linhas (fase 2): {created}")

    except Exception as e:
        print(f"[ERROR] Erro ao regenerar HTMLs de overlap (fase 2): {e}")
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
                phase_shift_min=LINE_54_OPTIMIZED_PHASE_SHIFT_MIN,
                melhorado_phase_shift_min=LINE_54_MELHORADO_PHASE_SHIFT_MIN,
                reverse_metro_direction_id=1,  # Metrobus sentido Serpins, a partir de Portagem
                reverse_metro_route_id="LOUSA",  # não confundir com as viagens dos ramais novos (fase 2)
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
                phase_shift_min=LINE_54_OPTIMIZED_PHASE_SHIFT_MIN,
                melhorado_phase_shift_min=LINE_54_MELHORADO_PHASE_SHIFT_MIN,
                reverse_metro_direction_id=0,  # Metrobus sentido Portagem, a passar por Portela
                reverse_metro_route_id="LOUSA",  # não confundir com as viagens dos ramais novos (fase 2)
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


def regenerate_presentation_dashboard() -> None:
    """Regenera o dashboard de mockups da apresentacao."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando Dashboard de Mockups...")
    print("=" * 60)

    try:
        root = _project_root()
        dashboard_path = root / "outputs" / "mockups_dashboard.html"

        print("[INFO] Gerando dashboard de mockups...")
        created = create_presentation_dashboard_html(dashboard_path)
        print(f"[SUCCESS] Dashboard mockups: {created}")

    except Exception as e:
        print(f"[ERROR] Erro ao regenerar dashboard de mockups: {e}")
        import traceback
        traceback.print_exc()


def regenerate_feednplay_dashboard() -> None:
    """Regenera o esqueleto do dashboard para a parede FeedNPlay."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando Dashboard FeedNPlay (esqueleto)...")
    print("=" * 60)

    try:
        root = _project_root()
        dashboard_path = root / "outputs" / "feednplay_dashboard.html"

        print("[INFO] Gerando dashboard FeedNPlay...")
        created = create_feednplay_dashboard_html(dashboard_path)
        print(f"[SUCCESS] Dashboard FeedNPlay: {created}")

    except Exception as e:
        print(f"[ERROR] Erro ao regenerar dashboard FeedNPlay: {e}")
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
    regenerate_overlap_fase2_htmls()
    regenerate_integration_htmls()
    regenerate_master_dashboard()
    regenerate_presentation_dashboard()
    regenerate_feednplay_dashboard()

    print("\n" + "=" * 60)
    print("[SUCCESS] REGENERAÃ‡ÃƒO CONCLUÃDA!")
    print("=" * 60)
    print("\n[INFO] Todos os ficheiros HTML foram atualizados em outputs/")
    print("[INFO] Abrir: file:///path/para/projeto/outputs/dashboard.html\n")


if __name__ == "__main__":
    main()

