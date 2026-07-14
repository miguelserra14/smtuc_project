from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _read_template(template_name: str) -> str:
    template_path = _TEMPLATE_DIR / template_name
    return template_path.read_text(encoding="utf-8")


def _to_float(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except Exception:
        return 0.0


def _load_overlap_stats() -> dict[str, list[dict[str, str]]] | None:
    metrics_path = Path("outputs/overlap/line_metrics_db.csv")
    if not metrics_path.exists():
        return None

    rows: list[dict[str, str]] = []
    with metrics_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row:
                continue
            rows.append(row)

    if not rows:
        return None

    ranked = sorted(rows, key=lambda r: (_to_float(r.get("overlap_pct")), _to_float(r.get("overlap_extension_m"))), reverse=True)
    top5 = ranked[:5]
    bottom5 = list(reversed(ranked[-5:]))
    stadium_candidates = [
        row
        for row in rows
        if _to_float(row.get("radius_extension_pct")) >= 50.0
        and _to_float(row.get("radius_m")) <= 2000.0
    ]
    stadium_ranked = sorted(
        stadium_candidates,
        key=lambda r: (_to_float(r.get("overlap_pct")), _to_float(r.get("overlap_extension_m"))),
    )
    bottom5_stadium = stadium_ranked[:5]

    def _fmt(items: list[dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for row in items:
            out.append(
                {
                    "line": str(row.get("line", "-")),
                    "overlap_pct": f"{_to_float(row.get('overlap_pct')):.2f}%",
                    "overlap_m": f"{_to_float(row.get('overlap_extension_m')):.1f}",
                    "extension_m": f"{_to_float(row.get('line_extension_m')):.1f}",
                    "overlap_stops": str(row.get("overlap_stops", "-")),
                    "total_stops": str(row.get("total_stops", "-")),
                    "avg_freq_min": f"{_to_float(row.get('avg_freq_min')):.1f}",
                }
            )
        return out

    # temporal aggregates from ALL lines (CSV contains per-line temporal counts)
    try:
        total_spatial_candidates = int(sum(_to_float(r.get("temporal_spatial_candidates_count")) for r in rows))
    except Exception:
        total_spatial_candidates = 0

    try:
        total_temporal_overlaps = int(sum(_to_float(r.get("temporal_overlaps_count")) for r in rows))
    except Exception:
        total_temporal_overlaps = 0

    def _split_ids(value: str | None) -> set[str]:
        if not value:
            return set()
        return {v for v in str(value).split(";") if v}

    # Distinct physical stops, not a sum across lines (a stop shared by several lines must
    # only count once) - derived from the per-line stop_id sets stored in the CSV.
    overlap_stations_set: set[str] = set()
    temporal_overlap_stations_set: set[str] = set()
    for r in rows:
        overlap_stations_set |= _split_ids(r.get("overlap_stop_ids"))
        temporal_overlap_stations_set |= _split_ids(r.get("temporal_overlap_stop_ids"))

    overlap_stations = len(overlap_stations_set)
    overlap_lines = int(len([r for r in rows if _to_float(r.get("overlap_pct")) > 0]))

    temporal_overlap_times = total_temporal_overlaps
    temporal_overlap_stations = len(temporal_overlap_stations_set)
    temporal_overlap_lines = int(len({r.get("line") for r in rows if _to_float(r.get("temporal_overlaps_count")) > 0}))

    temporal_overlap_pct = (total_temporal_overlaps / total_spatial_candidates) * 100.0 if total_spatial_candidates > 0 else 0.0

    # Import configured temporal threshold and walk speed from central config
    from config import TEMPORAL_OVERLAP_MAX_MIN, WALK_SPEED_M_MIN, SPATIAL_OVERLAP_WALK_MIN

    walk_distance_threshold = WALK_SPEED_M_MIN * SPATIAL_OVERLAP_WALK_MIN

    return {
        "top5": _fmt(top5),
        "bottom5": _fmt(bottom5),
        "bottom5_stadium": _fmt(bottom5_stadium),
        "temporal_summary": {
            "total_spatial_candidates": total_spatial_candidates,
            "overlap_stations": overlap_stations,
            "overlap_lines": overlap_lines,
            "temporal_overlap_pct": round(temporal_overlap_pct, 2),
            "temporal_overlap_times": temporal_overlap_times,
            "temporal_overlap_stations": temporal_overlap_stations,
            "temporal_overlap_lines": temporal_overlap_lines,
            "TEMPORAL_OVERLAP_MAX_MIN": TEMPORAL_OVERLAP_MAX_MIN,
            "walk_distance_threshold": walk_distance_threshold,
        },
    }


def _cache_busted_src(root: Path, src: str) -> str:
    """Acrescenta `?v=<mtime do ficheiro>` (ou `&v=...` se já houver query string) a um `src`
    de iframe que aponte para um ficheiro local existente, relativo a `root`.

    Sem isto, `<iframe src="...">` fica à mercê da heurística de cache do browser: como
    `python -m http.server` não envia `Cache-Control`, browsers como o Chrome podem servir o
    iframe da cache sem revalidar mesmo depois de um refresh normal da página principal e do
    ficheiro ter sido genuinamente regenerado no disco - confirmado com o utilizador (painel
    de população a mostrar dados antigos depois de regenerar `bgri.html`). Uma query string
    diferente é sempre um URL novo aos olhos do browser, o que força um pedido fresco.
    """
    if src.startswith(("http://", "https://", "data:")):
        return src
    path_part = src.split("?", 1)[0].split("#", 1)[0]
    file_path = root / path_part
    if not file_path.exists():
        return src
    version = int(file_path.stat().st_mtime)
    separator = "&" if "?" in src else "?"
    return f"{src}{separator}v={version}"


def _add_cache_busting(obj: Any, root: Path) -> Any:
    """Percorre recursivamente uma estrutura de tabs (dicts/listas aninhadas) e aplica
    `_cache_busted_src` a qualquer valor sob uma chave "src"."""
    if isinstance(obj, dict):
        return {
            k: (_cache_busted_src(root, v) if k == "src" and isinstance(v, str) else _add_cache_busting(v, root))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_add_cache_busting(item, root) for item in obj]
    return obj


def _default_dashboard_tabs() -> list[dict[str, Any]]:
    # Put population and overlap first (displayed on top of the page), integrations below
    overlap_stats = _load_overlap_stats()
    return [
        {
            "id": "summary",
            "label": "Resumo",
            "description": "Com a entrada do Metrobus em Coimbra, os SMTUC requerem uma reconfiguração para evitar redundância excessiva onde já existe boa cobertura de transportes públicos, reforçar zonas com baixa oferta relativa à população e melhorar a complementaridade espacial e temporal entre redes.",
            "kind": "summary",
            "preview_items": [
                {
                    "id": "overlap",
                    "label": "Overlap",
                    "description": "Mapa de isócronas dinâmico e dados associados.",
                    "src": "population/bgri.html?show=choropleth",
                },
                {
                    "id": "population",
                    "label": "População",
                    "description": "Mapas de população e de Índice de Subserviço.",
                    "src": "population/bgri.html",
                },
                {
                    "id": "integration-portagem",
                    "label": "Integração Portagem",
                    "description": "Heatmaps de espera e equidade.",
                    "src": "integration/portagem/l54_38_all.html",
                },
                {
                    "id": "integration-portela",
                    "label": "Integração Portela",
                    "description": "Heatmaps de espera e equidade.",
                    "src": "integration/portela/l54_all.html",
                },
            ],
        },
        {
            "id": "population",
            "label": "População",
            "description": "Mapas de população e de Índice de Subserviço.",
            "kind": "iframe",
            "src": "population/bgri.html",
        },
        {
            "id": "overlap",
            "label": "Overlap",
            "description": "Mapa de isócronas dinâmico e dados associados.",
            "kind": "iframe",
            "src": "overlap/overlap_reachability_now.html",
            "overlap_stats": overlap_stats,
            "extra_frames": [
                {
                    "title": "Mapa de linhas sobrepostas (overlap espacial)",
                    "src": "overlap/overlap_lines_map.html",
                    "caption": "Linhas SMTUC com maior e menor overlap espacial face ao Metrobus, com os polos de emprego e locais concorridos sobrepostos.",
                },
                {
                    "title": "Breakdown do overlap temporal",
                    "src": "overlap/overlap_temporal_breakdown.html",
                    "caption": "Detalhe do overlap temporal (<=5 min) entre passagens SMTUC e Metrobus, por linha e paragem.",
                },
            ],
        },
        {
            "id": "integration-portagem",
            "label": "Integração Portagem",
            "description": "Linha 54 no sentido Portela -> Portagem.",
            "kind": "iframe",
            "src": "integration/portagem/l54_38_all.html",
        },
        {
            "id": "integration-portela",
            "label": "Integração Portela",
            "description": "Linha 54 no sentido Portagem -> Portela.",
            "kind": "iframe",
            "src": "integration/portela/l54_all.html",
        },
    ]


def create_master_dashboard_html(
    output_path: Path | str,
    title: str = "SMTUC: A caminho da complementaridade",
    tabs: list[dict[str, Any]] | None = None,
) -> str:
    """Create a single HTML page that links to all main visualization dashboards."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_tabs = _add_cache_busting(tabs or _default_dashboard_tabs(), output_path.parent)

    page = _read_template("master_dashboard.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__TABS_JSON__", json.dumps(resolved_tabs, ensure_ascii=False))

    output_path.write_text(page, encoding="utf-8")
    return str(output_path)


def _default_presentation_tabs() -> list[dict[str, Any]]:
    overlap_stats = _load_overlap_stats()
    return [
        {
            "id": "intro",
            "label": "Introdução",
            "kind": "hero",
            "eyebrow": "Apresentação final",
            "title": "SMTUC: A caminho da complementaridade",
            "subtitle": "Como o Metrobus mudou a mobilidade em Coimbra e o que o SMTUC pode adaptar já",
            "lead": "As obras ainda não estão acabadas, mas o estudo já está encaminhado e já há bastante que pode ser feito com impacto tangível.",
            "chips": ["Metrobus", "SMTUC", "Coimbra", "Urgência em setembro"],
            "highlights": [
                "Mudança estrutural da mobilidade",
                "Resposta já possível com os dados que existem",
                "Janela de oportunidade para a entrada de caloiros",
            ],
        },
        {
            "id": "metodologia",
            "label": "Metodologia",
            "kind": "methodology",
            "description": "Como os dados de SMTUC, Metrobus e população entram no mesmo fluxo de análise.",
            "note": "Cruza-se oferta de transporte, população e contexto urbano para perceber onde a rede mudou e onde o SMTUC pode ajustar-se já.",
            "steps": ["Recolha", "Limpeza", "Métricas", "Visualização"],
            "source_tags": ["SMTUC", "Metrobus", "População", "Locais de trabalho", "Locais de convívio"],
            "iframes": [
                {
                    "title": "Heatmap de população",
                    "src": "population/bgri.html?show=heatmap",
                    "caption": "Distribuição da população por Coimbra.",
                },
                {
                    "title": "Índice de subserviço",
                    "src": "population/bgri.html?show=choropleth",
                    "caption": "Primeira leitura da pressão de serviço.",
                },
            ],
        },
        {
            "id": "subservico",
            "label": "Subserviço + Isócronas",
            "kind": "three-up",
            "description": "A métrica de subserviço e a leitura territorial das isócronas.",
            "note": "A taxa de subserviço relaciona população com oferta e ajuda a perceber onde o serviço está mais pressionado. As isócronas devem passar a incluir também locais de trabalho e convívio.",
            "iframes": [
                {
                    "title": "Mapa global de subserviço",
                    "src": "population/bgri.html?show=choropleth",
                    "caption": "Índice de subserviço em Coimbra.",
                },
                {
                    "title": "Subserviço a 2 km",
                    "src": "population/bgri.html?show=stadium",
                    "caption": "Leitura de detalhe da pressão territorial.",
                },
                {
                    "title": "Isócronas dinâmicas",
                    "src": "overlap/overlap_reachability_now.html",
                    "caption": "Cobertura, acessibilidade e overlap temporal.",
                },
            ],
        },
        {
            "id": "overlap",
            "label": "Overlap",
            "kind": "overlap",
            "description": "Onde a rede SMTUC e o Metrobus mais se sobrepõem.",
            "note": "Este bloco mostra onde existe redundância espacial e temporal. A leitura deve ser visual, direta e rápida.",
            "iframes": [
                {
                    "title": "Reachability e overlap temporal",
                    "src": "overlap/overlap_reachability_now.html",
                    "caption": "Mapa principal com cobertura e temporalidade.",
                },
                {
                    "title": "Mapa de linhas sobrepostas",
                    "src": "overlap/overlap_lines_map.html",
                    "caption": "Linhas com maior e menor overlap.",
                },
            ],
            "stats": overlap_stats,
        },
        {
            "id": "integracao",
            "label": "Integração",
            "kind": "comparison",
            "description": "Comparação Portagem e Portela com a linha 54.",
            "note": "A versão otimizada ainda é um objetivo do projeto, por isso o foco aqui é mostrar o estado atual e a direção de melhoria: menos espera, melhor coordenação e horários mais úteis.",
            "columns": [
                {
                    "title": "Portagem",
                    "subtitle": "Linha 54 + 38",
                    "current": {
                        "title": "Estado atual",
                        "src": "integration/portagem/l54_38_all.html",
                        "caption": "Integração atual no sentido Portela → Portagem.",
                    },
                    "optimized": [
                        "Reduzir tempos de espera no transbordo",
                        "Ajustar horários ao Metrobus",
                        "Evidenciar a correspondência entre modos",
                    ],
                },
                {
                    "title": "Portela",
                    "subtitle": "Linha 54",
                    "current": {
                        "title": "Estado atual",
                        "src": "integration/portela/l54_all.html",
                        "caption": "Integração atual no sentido Portagem → Portela.",
                    },
                    "optimized": [
                        "Simplificar o percurso de ligação",
                        "Reorganizar a cadência horária",
                        "Mostrar melhor o ganho tangível para o utilizador",
                    ],
                },
            ],
        },
        {
            "id": "conclusao",
            "label": "Conclusões",
            "kind": "closing",
            "description": "O que a apresentação quer deixar claro no final.",
            "headline": "O Metrobus alterou a mobilidade em Coimbra e o SMTUC precisa de se adaptar.",
            "points": [
                "Há já impacto tangível que pode ser mostrado antes de as obras terminarem.",
                "O reforço do SMTUC deve responder ao novo contexto, não competir com ele.",
                "Setembro é a oportunidade para demonstrar a nova era da mobilidade em Coimbra.",
            ],
        },
        {
            "id": "agradecimentos",
            "label": "Agradecimentos",
            "kind": "thanks",
            "description": "Fecho minimalista e limpo para o ecrã final.",
            "title": "Obrigado",
            "subtitle": "Nomes, instituição e contactos",
            "contacts": ["Nome 1", "Nome 2", "Curso / Unidade curricular", "Setembro 2026"],
        },
    ]


def create_presentation_dashboard_html(
    output_path: Path | str,
    title: str = "SMTUC: Mockups da apresentação",
    tabs: list[dict[str, Any]] | None = None,
) -> str:
    """Create a tabbed HTML dashboard aligned with the presentation mockups."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_tabs = _add_cache_busting(tabs or _default_presentation_tabs(), output_path.parent)

    page = _read_template("presentation_dashboard.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__TABS_JSON__", json.dumps(resolved_tabs, ensure_ascii=False))

    output_path.write_text(page, encoding="utf-8")
    return str(output_path)


def create_feednplay_dashboard_html(
    output_path: Path | str,
    title: str = "SMTUC: FeedNPlay",
    tabs: list[dict[str, Any]] | None = None,
) -> str:
    """Esqueleto do build para a parede FeedNPlay (9720x1920px).

    Reutiliza o mesmo conteúdo/motor de tabs de `create_presentation_dashboard_html` - só o
    template (`feednplay_dashboard.html`) muda, com CSS full-bleed em vez de coluna centrada.
    Grid de bezels, tipografia à distância e o bridge à câmara de topo (ver
    `src/feednplay/bridge.py`) ainda não estão ligados aqui, ficam para depois de validar que
    este esqueleto corre no canvas certo.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_tabs = _add_cache_busting(tabs or _default_presentation_tabs(), output_path.parent)

    page = _read_template("feednplay_dashboard.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__TABS_JSON__", json.dumps(resolved_tabs, ensure_ascii=False))

    output_path.write_text(page, encoding="utf-8")
    return str(output_path)
