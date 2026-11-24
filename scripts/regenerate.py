"""Regenera todos os HTML do projeto: população, overlap/isócronas (todos os cenários),
integração da 54 (todos os cenários), comparação antes vs fase 2 e os dashboards master,
apresentação e FeedNPlay.

Uso (não precisa de PYTHONPATH - o script põe src/ no sys.path, como os outros de scripts/):
    python scripts/regenerate.py

Valida primeiro o dia de referência de cada cenário contra os seus feeds (sai com 1 sem gerar nada
se algum estiver fora do período), corre cada secção registando falhas/saltos/avisos e sai com 1 se
alguma secção ou artefacto falhar.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

from config import (  # noqa: E402
    CATCHMENT_M,
    COMPARISON_SCENARIOS,
    INTEGRATION_SITES,
    LINE_54_MELHORADO_PHASE_SHIFT_MIN,
    LINE_54_OPTIMIZED_PHASE_SHIFT_MIN,
    OUTPUTS_COMPARISON_DIR,
    OUTPUTS_OVERLAP_DIR,
    OUTPUTS_POPULATION_DIR,
    POPULATION_STADIUM_MAP_RADIUS_M,
    REACHABILITY_MAX_TRANSFERS,
    STADIUM_COORD,
)
from gtfs_processing.gtfs import load_gtfs_cached  # noqa: E402
from gtfs_processing.gtfs_probe import (  # noqa: E402
    ServiceCalendarError,
    active_service_ids,
    feed_service_period,
    is_public_holiday,
)
from gtfs_processing.scenarios import (  # noqa: E402
    get_scenario,
    scenario_names,
    scenario_output_path,
    scenario_reference_time,
)
from overlap.overlap import compute_bgri_reachability_now  # noqa: E402
from overlap.overlap_db import line_metrics_db_path, load_line_metrics_db  # noqa: E402
from overlap.transit import resolve_reference_day  # noqa: E402
from population.data_processing import (  # noqa: E402
    compute_poi_underservice,
    compute_underserved_zones,
    filter_zones_by_distance,
    project_root,
    require_bgri_data,
    require_geo_stack,
)
from visualizations import (  # noqa: E402
    create_feednplay_dashboard_html,
    create_master_dashboard_html,
    create_overlap_lines_map,
    create_overlap_reachability_map,
    create_population_dashboard_html,
    create_presentation_dashboard_html,
    create_temporal_overlap_breakdown_html,
    generate_connection_visualizations,
    write_folium_html,
)
from visualizations.dashboard import load_overlap_stats, overlap_stats_footer_html  # noqa: E402
from visualizations.scenario_comparison import create_scenario_comparison_html  # noqa: E402

# Registo do que correu mal / foi saltado durante a execução, para o resumo final e o exit code.
# Antes cada secção engolia o seu erro com um print e o script acabava sempre com "CONCLUÍDA" e
# exit code 0, mesmo com secções inteiras por gerar (ex.: integração saltada por um
# UnicodeEncodeError de um print com "→" quando o stdout estava redirecionado).
_FAILURES: list[tuple[str, str]] = []
_SKIPPED: list[tuple[str, str]] = []
_WARNINGS: list[tuple[str, str]] = []


def _record_failure(section: str, exc: BaseException) -> None:
    """Uma secção/artefacto que devia ter sido gerado e não foi - faz o script sair com código 1."""
    import traceback

    print(f"[ERROR] {section}: {type(exc).__name__}: {exc}")
    traceback.print_exc()
    _FAILURES.append((section, f"{type(exc).__name__}: {exc}"))


def _record_skip(section: str, reason: str) -> None:
    """Secção saltada por falta de uma dependência/dados opcionais (não conta como falha)."""
    print(f"[WARNING] {section}: saltado - {reason}")
    _SKIPPED.append((section, reason))


def _record_warning(section: str, reason: str) -> None:
    """Artefacto gerado, mas com conteúdo opcional em falta (não conta como falha)."""
    print(f"[WARNING] {section}: {reason}")
    _WARNINGS.append((section, reason))


def _configure_utf8_output() -> None:
    """Força UTF-8 no stdout/stderr. Com o output redirecionado (pipe, ficheiro de log, tarefa
    agendada) o Python no Windows usa a codepage cp1252, que não tem "→" - um único print com
    esse carácter lançava UnicodeEncodeError e abortava a secção onde estava."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _print_summary() -> int:
    """Imprime o resumo da execução e devolve o exit code (1 se houve alguma falha)."""
    print("\n" + "=" * 60)
    if _FAILURES:
        print(f"[ERROR] REGENERAÇÃO INCOMPLETA - {len(_FAILURES)} falha(s):")
        for section, msg in _FAILURES:
            print(f"   - {section}: {msg}")
    else:
        print("[SUCCESS] REGENERAÇÃO CONCLUÍDA SEM FALHAS")
    for label, items in (("saltado(s)", _SKIPPED), ("aviso(s)", _WARNINGS)):
        if items:
            print(f"[WARNING] {len(items)} {label}:")
            for section, msg in items:
                print(f"   - {section}: {msg}")
    print("=" * 60)
    return 1 if _FAILURES else 0


def _validate_reference_day() -> bool:
    """Confirma, ANTES de gerar qualquer HTML, que o dia de referência de CADA cenário
    (config.SCENARIOS) pode ser avaliado nos feeds desse cenário (dentro do período de cada
    calendário, service_id ligáveis às trips). Sem isto, um dia fora do período só rebentava a
    meio, secção a secção, e cada secção engolia o erro. Devolve False (e explica porquê) se algum
    feed falhar; feeds ausentes são só avisados."""
    ok = True
    for name in scenario_names():
        sc = get_scenario(name)
        day = resolve_reference_day(scenario=sc)
        holiday_note = " (feriado - avaliado como domingo)" if is_public_holiday(day) else ""
        print(f"[INFO] Cenário {name}: dia de referência {day.isoformat()} ({day.strftime('%A')}){holiday_note}")
        for dataset in sc.datasets:
            if not _require_dataset(dataset):
                continue
            gtfs = load_gtfs_cached(dataset)
            period = feed_service_period(gtfs)
            try:
                services = active_service_ids(gtfs, day)
            except ServiceCalendarError as exc:
                print(f"[ERROR] {name}/{dataset}: {exc}")
                ok = False
                continue
            n_trips = int(gtfs.trips["service_id"].astype(str).isin(services).sum())
            print(f"[INFO]   {dataset}: período {period}, serviços ativos {sorted(services)}, {n_trips}/{len(gtfs.trips)} viagens")
            if n_trips == 0:
                print(f"[WARNING] {name}/{dataset}: nenhuma viagem ativa em {day.isoformat()} - as visualizações deste feed ficarão vazias.")
    return ok


def _require_dataset(dataset: str) -> Path:
    """Verifica se um dataset GTFS está disponível."""
    from gtfs_processing.gtfs import dataset_dir

    d = dataset_dir(dataset, project_root())
    required = ["routes.txt", "trips.txt", "stops.txt", "stop_times.txt"]
    if not d.exists() or any(not (d / f).exists() for f in required):
        print(f"[WARNING] Dataset GTFS inválido/incompleto: {d}")
        return None
    return d


def regenerate_population_htmls() -> None:
    """Regenera todos os HTMLs da população (BGRI)."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando HTMLs de População...")
    print("=" * 60)
    
    try:
        require_geo_stack()
    except Exception as e:
        _record_skip("população", f"geostack não disponível: {e}")
        return
    
    try:
        gpkg = require_bgri_data()
    except Exception as e:
        _record_skip("população", f"dataset BGRI não disponível: {e}")
        return
    
    try:
        # Cenário por omissão: os mesmos feeds e o mesmo dia de referência do overlap e da
        # integração, para todos os dashboards da mesma execução refletirem o mesmo dia de serviço.
        sc = get_scenario()
        day_str = resolve_reference_day(scenario=sc).strftime("%Y-%m-%d")

        print(f"[INFO] Usando data: {day_str}")
        
        # Computar zonas subservidas
        print("[INFO] Computando zonas subservidas...")
        merged = compute_underserved_zones(
            day_str=day_str,
            catchment_m=CATCHMENT_M,
            datasets=sc.datasets,
            bgri_gpkg_path=str(gpkg),
            bgri_layer="BGRI2021_0603",
            population_col="N_INDIVIDUOS",
            output_csv_path=scenario_output_path(f"{OUTPUTS_POPULATION_DIR}/bgri_transport_gap.csv", sc),
        )
        
        out_dir = project_root() / OUTPUTS_POPULATION_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # Filtrar zonas ao raio do painel "Estádio a X km" (POPULATION_STADIUM_MAP_RADIUS_M,
        # já em metros - não multiplicar). Propositadamente separado de STADIUM_RADIUS_M, que
        # é partilhado por outras análises (ver comentário em config.py).
        merged_2km = filter_zones_by_distance(merged, distance_m=POPULATION_STADIUM_MAP_RADIUS_M)

        # Camada opcional de polos de emprego/locais concorridos (só confiança boa/média - ver
        # points_of_interest.py) para os painéis de índice de subserviço. Falha graciosamente:
        # sem isto os painéis ficam exatamente como antes, sem o botão "Com POI"/"Sem POI".
        try:
            poi_df = compute_poi_underservice(day_str=day_str, catchment_m=CATCHMENT_M, datasets=sc.datasets)
        except Exception as e:
            _record_warning("população", f"camada de pontos de interesse não calculada: {e}")
            poi_df = None

        # Criar dashboard de população
        print("[INFO] Gerando dashboard de população...")
        dashboard_html = out_dir / "bgri.html"
        create_population_dashboard_html(
            dashboard_html,
            merged,
            merged_2km,
            day_str,
            stadium_radius_m=POPULATION_STADIUM_MAP_RADIUS_M,
            poi_df=poi_df,
        )
        print(f"[SUCCESS] Dashboard população: {dashboard_html}")
        
    except Exception as e:
        _record_failure("população", e)


def regenerate_overlap_htmls() -> None:
    """Overlap/isócronas do cenário por omissão (slide "Overlap")."""
    regenerate_overlap_scenario_htmls(get_scenario().name)


def regenerate_overlap_fase2_htmls() -> None:
    """Slide dedicado da fase 2 da apresentação (cenário "fase2" de config.SCENARIOS)."""
    regenerate_overlap_scenario_htmls("fase2")


def regenerate_overlap_scenario_htmls(scenario: str) -> None:
    """Isócronas a partir do estádio + mapa de linhas de UM cenário, com os feeds, o dia/hora de
    referência e o sufixo de ficheiros desse cenário (ex.: `_fase2`, para não pisar os do cenário
    por omissão). Só o cenário por omissão leva o rodapé de estatísticas no mapa de isócronas e a
    página de breakdown temporal - são as do slide "Overlap" original (ver `PRESENTATION_TABS`).

    Antes havia duas funções quase iguais (uma por cenário); esta é a única."""
    sc = get_scenario(scenario)
    is_default = not sc.output_suffix
    section = "overlap" if is_default else f"overlap {sc.name}"
    print("\n" + "=" * 60)
    print(f"[INFO] Regenerando HTMLs de Overlap (cenário {sc.name})...")
    print("=" * 60)

    missing = [d for d in sc.datasets if not _require_dataset(d)]
    if missing:
        _record_skip(section, f"dataset {', '.join(missing)} não disponível")
        return
    try:
        require_geo_stack()
        gpkg = require_bgri_data()
    except Exception as e:
        _record_skip(section, f"geostack/BGRI não disponível: {e}")
        return

    try:
        out_dir = project_root() / OUTPUTS_OVERLAP_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        # Cache de métricas validada/atualizada ANTES de qualquer leitura do CSV do disco (rodapé,
        # mapa de linhas, breakdown): só recalcula se dados/parâmetros/código mudaram.
        print(f"[INFO] Verificando cache de métricas de linha ({sc.name})...")
        load_line_metrics_db(scenario=sc)
        metrics_csv = line_metrics_db_path(scenario=sc)

        # Dia/hora das isócronas = os do cenário (os mesmos da integração e da população).
        day_str = resolve_reference_day(scenario=sc).strftime("%Y-%m-%d")
        reach_time_str = scenario_reference_time(sc)
        print(f"[INFO] Isócronas ({sc.name}): data/hora de referência {day_str} {reach_time_str or '(agora)'}")

        merged = compute_underserved_zones(
            day_str=day_str,
            catchment_m=CATCHMENT_M,
            datasets=sc.datasets,
            bgri_gpkg_path=str(gpkg),
            bgri_layer="BGRI2021_0603",
            population_col="N_INDIVIDUOS",
            output_csv_path=scenario_output_path(f"{OUTPUTS_POPULATION_DIR}/bgri_transport_gap.csv", sc),
        )
        reach_gdf = compute_bgri_reachability_now(
            merged_bgri=merged,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            datasets=sc.datasets,
            day_str=day_str,
            time_str=reach_time_str,
            max_transfers=REACHABILITY_MAX_TRANSFERS,
        )
        selected_time = str(reach_gdf["reach_time"].iloc[0]) if not reach_gdf.empty else "00:00:00"
        fig_map = create_overlap_reachability_map(
            reach_gdf=reach_gdf,
            origin_lat=STADIUM_COORD[0],
            origin_lon=STADIUM_COORD[1],
            day_str=day_str,
            time_str=selected_time,
        )

        footer_html = None
        if is_default:
            try:
                footer_html = overlap_stats_footer_html(load_overlap_stats(metrics_csv))
            except Exception as e:
                _record_warning(section, f"rodapé de estatísticas omitido: {e}")
        reachability_html = Path(scenario_output_path(out_dir / "overlap_reachability_now.html", sc))
        write_folium_html(fig_map, reachability_html, footer_html=footer_html)
        print(f"[SUCCESS] Mapa de reachability ({sc.name}): {reachability_html}")
    except Exception as e:
        _record_failure(section, e)
        return

    try:
        created = create_overlap_lines_map(
            output_path=Path(scenario_output_path(out_dir / "overlap_lines_map.html", sc)),
            metrics_csv=metrics_csv,
            smtuc_dataset=sc.smtuc,
            metrobus_dataset=sc.metro,
        )
        print(f"[SUCCESS] Mapa de linhas ({sc.name}): {created}")
    except Exception as e:
        _record_failure(f"{section}: mapa de linhas", e)

    if is_default:
        try:
            created = create_temporal_overlap_breakdown_html(
                output_path=out_dir / "overlap_temporal_breakdown.html", metrics_csv=metrics_csv
            )
            print(f"[SUCCESS] Breakdown overlap temporal: {created}")
        except Exception as e:
            _record_failure(f"{section}: breakdown temporal", e)


def regenerate_integration_htmls() -> None:
    """Regenera HTMLs de integração (Portagem e Portela) de TODOS os cenários: o cenário por
    omissão em `integration/<subpasta>/`, os outros em `integration/<subpasta><sufixo>/`."""
    for name in scenario_names():
        regenerate_integration_scenario_htmls(name)


def regenerate_integration_scenario_htmls(scenario: str | None = None) -> None:
    """Regenera os HTMLs de integração de um cenário (None = o cenário por omissão)."""
    sc = get_scenario(scenario)
    section = "integração" if not sc.output_suffix else f"integração {sc.name}"
    print("\n" + "=" * 60)
    print(f"[INFO] Regenerando HTMLs de Integração (cenário {sc.name})...")
    print("=" * 60)

    if not _require_dataset(sc.smtuc) or not _require_dataset(sc.metro):
        _record_skip(section, f"datasets GTFS {sc.smtuc}/{sc.metro} não disponíveis")
        return

    try:
        day_str = resolve_reference_day(scenario=sc).strftime("%Y-%m-%d")
        print(f"[INFO] Usando data: {day_str}")

        # Nós de integração definidos uma só vez em config.INTEGRATION_SITES (também usados por
        # scripts/search_phase_shift.py, que procura os desvios de fase abaixo).
        for site in INTEGRATION_SITES:
            lines = [site["line_number"]] if isinstance(site["line_number"], str) else list(site["line_number"])
            label = f"{section} {site['name']} ({'+'.join(lines)})"
            print()
            print(f"[INFO] Gerando {label}: {site['metro_origin_ref']} → {site['metro_stop_ref']}...")
            kwargs = {k: v for k, v in site.items() if k != "name"}
            kwargs["line_number"] = lines if len(lines) > 1 else lines[0]
            try:
                results = generate_connection_visualizations(
                    day_str=day_str,
                    phase_shift_min=LINE_54_OPTIMIZED_PHASE_SHIFT_MIN,
                    melhorado_phase_shift_min=LINE_54_MELHORADO_PHASE_SHIFT_MIN,
                    scenario=sc.name,
                    **kwargs,
                )
                print(f"[SUCCESS] {label}: {results.get('combined_html', 'N/A')}")
            except Exception as e:
                _record_failure(label, e)

    except Exception as e:
        _record_failure(section, e)


# Secções do snapshot que a página de comparação usa (sem "linhas" nem a busca de fase, que é a
# parte lenta e não entra na página).
_COMPARISON_SECTIONS = ("overlap_resumo", "esperas_54", "isocrona", "populacao")


def _load_snapshot_module():
    """`scripts/snapshot_metrics.py` carregado por caminho (scripts/ não é um pacote): a página de
    comparação usa EXATAMENTE os números de controlo de reports/metricas/, não uma cópia do cálculo."""
    path = project_root() / "scripts" / "snapshot_metrics.py"
    spec = importlib.util.spec_from_file_location("snapshot_metrics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def regenerate_comparison_html() -> None:
    """Página "Antes vs Fase 2" (D2.5): snapshot de cada cenário de COMPARISON_SCENARIOS (nada
    gravado em outputs/ pelo snapshot) -> outputs/comparacao/<antes>_vs_<depois>.{html,csv}.
    Corre depois das secções de overlap, para reaproveitar o cache de métricas já atualizado."""
    section = "comparação de cenários"
    print("\n" + "=" * 60)
    print("[INFO] Regenerando comparação de cenários...")
    print("=" * 60)

    before_name, after_name = COMPARISON_SCENARIOS
    for name in COMPARISON_SCENARIOS:
        sc = get_scenario(name)
        if not _require_dataset(sc.smtuc) or not _require_dataset(sc.metro):
            _record_skip(section, f"datasets GTFS {sc.smtuc}/{sc.metro} não disponíveis")
            return
    try:
        require_geo_stack()
        require_bgri_data()
    except Exception as e:
        _record_skip(section, f"geostack/BGRI não disponível (isócronas e população): {e}")
        return

    try:
        snapshot_metrics = _load_snapshot_module()
        snaps = {
            name: snapshot_metrics.take_snapshot(f"pagina_{name}", scenario=name, sections=_COMPARISON_SECTIONS)
            for name in COMPARISON_SCENARIOS
        }
        out_dir = project_root() / OUTPUTS_COMPARISON_DIR
        stem = f"{before_name}_vs_{after_name}"
        created = create_scenario_comparison_html(
            out_dir / f"{stem}.html",
            before=snaps[before_name],
            after=snaps[after_name],
            csv_path=out_dir / f"{stem}.csv",
        )
        print(f"[SUCCESS] Comparação de cenários: {created}")
    except Exception as e:
        _record_failure(section, e)


def regenerate_master_dashboard() -> None:
    """Regenera o dashboard master."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando Dashboard Master...")
    print("=" * 60)
    
    try:
        root = project_root()
        dashboard_path = root / "outputs" / "dashboard.html"
        
        print("[INFO] Gerando dashboard master...")
        created = create_master_dashboard_html(dashboard_path)
        print(f"[SUCCESS] Dashboard master: {created}")
        
    except Exception as e:
        _record_failure("dashboard master", e)


def regenerate_presentation_dashboard() -> None:
    """Regenera o dashboard de mockups da apresentacao."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando Dashboard de Mockups...")
    print("=" * 60)

    try:
        root = project_root()
        dashboard_path = root / "outputs" / "mockups_dashboard.html"

        print("[INFO] Gerando dashboard de mockups...")
        created = create_presentation_dashboard_html(dashboard_path)
        print(f"[SUCCESS] Dashboard mockups: {created}")

    except Exception as e:
        _record_failure("dashboard de mockups", e)


def regenerate_feednplay_dashboard() -> None:
    """Regenera o esqueleto do dashboard para a parede FeedNPlay."""
    print("\n" + "=" * 60)
    print("[INFO] Regenerando Dashboard FeedNPlay (esqueleto)...")
    print("=" * 60)

    try:
        root = project_root()
        dashboard_path = root / "outputs" / "feednplay_dashboard.html"

        print("[INFO] Gerando dashboard FeedNPlay...")
        created = create_feednplay_dashboard_html(dashboard_path)
        print(f"[SUCCESS] Dashboard FeedNPlay: {created}")

    except Exception as e:
        _record_failure("dashboard FeedNPlay", e)


def main() -> None:
    """Executa regeneração completa de todos os HTMLs. Sai com código 1 se o dia de referência
    for inválido ou se alguma secção/artefacto falhar (ver _print_summary)."""
    _configure_utf8_output()
    print("\n" + "=" * 60)
    print("REGENERANDO TODOS OS HTMLS DA DASHBOARD")
    print("=" * 60 + "\n")

    if not _validate_reference_day():
        print("[ERROR] Dia de referência inválido para pelo menos um feed GTFS - nada foi regenerado.")
        sys.exit(1)

    # Regenerar em ordem
    regenerate_population_htmls()
    regenerate_overlap_htmls()
    regenerate_overlap_fase2_htmls()
    regenerate_integration_htmls()
    regenerate_comparison_html()
    regenerate_master_dashboard()
    regenerate_presentation_dashboard()
    regenerate_feednplay_dashboard()

    exit_code = _print_summary()
    print("[INFO] Ver: python -m http.server 8000 (raiz do repo) -> http://localhost:8000/outputs/dashboard.html")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

