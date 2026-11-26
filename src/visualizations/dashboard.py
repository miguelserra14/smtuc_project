from __future__ import annotations

import copy
import csv
import html
import json
from pathlib import Path
from typing import Any

from config import (
    FEEDNPLAY_CLICK_TO_ADVANCE,
    FEEDNPLAY_PREVIEW_BASE_FONT_PX,
    FEEDNPLAY_PREVIEW_MODE,
    LINE_METRICS_DB_PATH,
)
from gtfs_processing.scenarios import scenario_output_path
from overlap.overlap_db import line_metrics_db_path

from .presentation_content import PRESENTATION_TABS, SCENARIO_LADDER, SECTIONS


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _read_template(template_name: str) -> str:
    template_path = _TEMPLATE_DIR / template_name
    return template_path.read_text(encoding="utf-8")


def _to_float(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_overlap_stats(
    metrics_path: str | Path | None = None,
) -> dict[str, list[dict[str, str]]] | None:
    metrics_path = line_metrics_db_path(metrics_path)
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
                    # Vazio = sem passagens suficientes no dia/janela de referência -> "-", nunca
                    # "0.0" (que se leria como "passa de 0 em 0 min").
                    "avg_freq_min": (
                        f"{_to_float(row.get('avg_freq_min')):.1f}"
                        if str(row.get("avg_freq_min") or "").strip() not in ("", "nan", "None")
                        else "-"
                    ),
                }
            )
        return out

    # temporal aggregates from ALL lines (CSV contains per-line temporal counts)
    total_spatial_candidates = int(sum(_to_float(r.get("temporal_spatial_candidates_count")) for r in rows))
    total_temporal_overlaps = int(sum(_to_float(r.get("temporal_overlaps_count")) for r in rows))

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

    # Soma simples de overlap_extension_m por linha (cada linha já vem com o seu próprio
    # troço em overlap, não há dupla-contagem entre linhas a corrigir aqui) - dá a extensão
    # total de linhas SMTUC que coincide (a pé) com o Metrobus, para o slide de overlap.
    total_overlap_extension_m = sum(_to_float(r.get("overlap_extension_m")) for r in rows)
    if total_overlap_extension_m >= 1000:
        total_overlap_extension_fmt = f"{total_overlap_extension_m / 1000:.1f} km"
    else:
        total_overlap_extension_fmt = f"{total_overlap_extension_m:.0f} m"

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
            "total_overlap_extension_m": round(total_overlap_extension_m, 1),
            "total_overlap_extension_fmt": total_overlap_extension_fmt,
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
    overlap_stats = load_overlap_stats()
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
        # D2.5: comparação antes vs fase 2 (página de regenerate_comparison_html) + as vistas da
        # fase 2 que não têm separador próprio. Desde o N1 também os dois pares que separam o
        # efeito do metro do efeito do horário SMTUC (os slides usam só esses).
        {
            "id": "antes-vs-fase2",
            "label": "Fase 1 vs Como Vou",
            "description": "Indicadores lado a lado: rede da fase 1 (11/05/2026) e rede em vigor (09/11/2026). Entre as duas mudam o metro e o horário SMTUC; as duas páginas a seguir separam os dois efeitos.",
            "kind": "iframe",
            "src": "comparacao/antes_vs_fase2.html",
            "extra_frames": [
                {
                    "title": "Efeito do metro: fase 1 → metro da fase 2 com o SMTUC Ep212",
                    "src": "comparacao/antes_vs_fase2_ep212.html",
                    "caption": "Só muda o metro: o horário SMTUC é o mesmo (Ep212).",
                },
                {
                    "title": "Efeito do horário SMTUC: metro da fase 2 com o Ep212 → Como Vou",
                    "src": "comparacao/fase2_ep212_vs_fase2.html",
                    "caption": "Só muda o horário SMTUC (Como Vou e as mudanças de março a setembro): o metro e o dia são os mesmos.",
                },
                {
                    "title": "Mapa de linhas sobrepostas (fase 2)",
                    "src": "overlap/overlap_lines_map_fase2.html",
                    "caption": "Linhas SMTUC com maior e menor overlap face à rede já com a fase 2.",
                },
                {
                    "title": "Reachability e overlap temporal (fase 2)",
                    "src": "overlap/overlap_reachability_now_fase2.html",
                    "caption": "Isócronas a partir do estádio com a fase 2.",
                },
                {
                    "title": "Integração Portagem (fase 2)",
                    "src": "integration/portagem_fase2/l54_38_all.html",
                    "caption": "Linhas 54 e 38 com o metro da fase 2.",
                },
                {
                    "title": "Integração Portela (fase 2)",
                    "src": "integration/portela_fase2/l54_all.html",
                    "caption": "Linha 54 com o metro da fase 2.",
                },
            ],
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


# Slides de kind "overlap" -> cenário (config.SCENARIOS) cujo cache de métricas mostram (ver
# _default_presentation_tabs). Por omissão (qualquer id não listado aqui) usa-se o cenário por
# omissão (dados antigos, pré-fase 2) - só o slide dedicado da fase 2 aponta para o seu. O caminho
# do cache sai do sufixo do cenário, o mesmo que o regenerate grava.
_OVERLAP_TAB_SCENARIO = {
    "overlap_fase2": "fase2",
}


def overlap_stats_footer_html(stats: dict | None) -> str:
    """HTML do rodapé de estatísticas (top 5, bottom 5 junto ao estádio e resumo temporal) que
    vai por baixo do mapa de isócronas do slide "Overlap"; "" se não houver estatísticas.
    Antes era montado dentro do script de regenerate."""
    if not stats:
        return ""
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

    return "<div id=\"overlap-stats-footer\" style=\"max-width:980px;margin:8px auto 28px;background:#fff;padding:6px;border:1px solid #ddd;border-radius:4px;\">" + "\n".join(footer_parts) + temporal_html + "</div>"


def _overlap_tab_metrics_path(tab_id: str) -> str:
    return scenario_output_path(LINE_METRICS_DB_PATH, _OVERLAP_TAB_SCENARIO.get(tab_id))


_LADDER_BY_ID = {step["id"]: step for step in SCENARIO_LADDER}
_SECTIONS_BY_ID = {section["id"]: section for section in SECTIONS}


def _ladder_steps(ids: list[str], where: str) -> list[dict[str, Any]]:
    unknown = [step_id for step_id in ids if step_id not in _LADDER_BY_ID]
    if unknown:
        raise ValueError(f"{where}: degraus inexistentes em SCENARIO_LADDER: {unknown}")
    return [copy.deepcopy(_LADDER_BY_ID[step_id]) for step_id in ids]


def _section_meta(section_id: str, where: str) -> dict[str, Any]:
    """Cópia da secção de `SECTIONS`, com "planned" = compara algum degrau planeado (leva o selo
    "cenário planeado")."""
    if section_id not in _SECTIONS_BY_ID:
        raise ValueError(f"{where}: secção inexistente em SECTIONS: {section_id!r}")
    section = copy.deepcopy(_SECTIONS_BY_ID[section_id])
    compared = _ladder_steps(section["compare"], f"secção {section_id}")
    _ladder_steps(section.get("context", []), f"secção {section_id}")
    section["planned"] = any(step["nature"] == "planeado" for step in compared)
    return section


def _attach_narrative(tabs: list[dict[str, Any]]) -> None:
    """Resolve os ids de "section"/"ladder" de cada slide (ver `presentation_content.py`) no que
    os templates leem: "section_meta", "ladder_meta" e, nos slides da escada e nos divisores,
    "ladder_all"/"sections_all". Um id desconhecido rebenta aqui, em vez de o slide sair sem
    etiqueta."""
    for tab in tabs:
        where = f"slide {tab.get('id')!r}"
        if tab.get("section") is not None:
            tab["section_meta"] = _section_meta(tab["section"], where)
        if tab.get("ladder") is not None:
            tab["ladder_meta"] = _ladder_steps(tab["ladder"], where)
        if tab.get("kind") in ("section", "ladder"):
            tab["ladder_all"] = copy.deepcopy(SCENARIO_LADDER)
        if tab.get("kind") == "ladder":
            tab["sections_all"] = [_section_meta(section["id"], where) for section in SECTIONS]


def _default_presentation_tabs() -> list[dict[str, Any]]:
    """Devolve os dados dos slides da apresentação - texto vem de `presentation_content.py`,
    exceto "stats" nos slides de kind "overlap", calculado aqui em tempo real a partir do cache
    de métricas de linha (ver `_OVERLAP_TAB_SCENARIO` - há mais do que um slide "overlap"
    desde que o slide dedicado à fase 2 existe, cada um com o seu próprio cache/dataset, por
    isso a escolha é por `id`, não só por `kind`), e os metadados de secção/cenário de
    `_attach_narrative`. `deepcopy` evita mutar a lista partilhada ao nível do módulo entre
    chamadas sucessivas (ex.: presentation_dashboard.html e feednplay_dashboard.html chamam esta
    função cada um a sua vez)."""
    tabs = copy.deepcopy(PRESENTATION_TABS)
    _attach_narrative(tabs)
    for tab in tabs:
        if tab.get("kind") == "overlap":
            metrics_path = _overlap_tab_metrics_path(str(tab.get("id")))
            tab["stats"] = load_overlap_stats(metrics_path)
    return tabs


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

    As zonas de anterior/seguinte navegam sempre por dwell (permanecer); poderem também ser
    clicadas/tocadas diretamente é opt-in, ligado/desligado por FEEDNPLAY_CLICK_TO_ADVANCE em
    `src/config.py` (sem precisar de mexer neste ficheiro nem no template). FEEDNPLAY_PREVIEW_MODE
    (mesmo ficheiro) troca a tipografia à distância da parede por FEEDNPLAY_PREVIEW_BASE_FONT_PX,
    para pré-visualizar num PC normal.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_tabs = _add_cache_busting(tabs or _default_presentation_tabs(), output_path.parent)

    page = _read_template("feednplay_dashboard.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__TABS_JSON__", json.dumps(resolved_tabs, ensure_ascii=False))
    page = page.replace("__FNP_CLICK_TO_ADVANCE__", json.dumps(bool(FEEDNPLAY_CLICK_TO_ADVANCE)))
    page = page.replace("__FNP_PREVIEW_MODE__", json.dumps(bool(FEEDNPLAY_PREVIEW_MODE)))
    page = page.replace("__FNP_PREVIEW_BASE_FONT_PX__", f"{FEEDNPLAY_PREVIEW_BASE_FONT_PX}px")

    output_path.write_text(page, encoding="utf-8")
    return str(output_path)
