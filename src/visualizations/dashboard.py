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

    overlap_stations = int(sum(_to_float(r.get("overlap_stops")) for r in rows))
    overlap_lines = int(len([r for r in rows if _to_float(r.get("overlap_pct")) > 0]))

    temporal_overlap_times = total_temporal_overlaps
    temporal_overlap_stations = int(len([r for r in rows if _to_float(r.get("temporal_overlaps_count")) > 0]))
    temporal_overlap_lines = int(len({r.get("line") for r in rows if _to_float(r.get("temporal_overlaps_count")) > 0}))

    temporal_overlap_pct = (total_temporal_overlaps / total_spatial_candidates) * 100.0 if total_spatial_candidates > 0 else 0.0

    # Try to import the configured temporal threshold and walk speed if available
    try:
        from src.config import TEMPORAL_OVERLAP_MAX_MIN, WALK_SPEED_M_MIN  # type: ignore
    except Exception:
        try:
            from config import TEMPORAL_OVERLAP_MAX_MIN, WALK_SPEED_M_MIN  # type: ignore
        except Exception:
            TEMPORAL_OVERLAP_MAX_MIN = 5.0
            WALK_SPEED_M_MIN = 80.0

    walk_distance_threshold = WALK_SPEED_M_MIN * 5.0

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
                    "src": "integration/portagem/l54_portagem_all.html?show=heatmaps",
                },
                {
                    "id": "integration-portela",
                    "label": "Integração Portela",
                    "description": "Heatmaps de espera e equidade.",
                    "src": "integration/portela/l54_all.html?show=heatmaps",
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
        },
        {
            "id": "integration-portagem",
            "label": "Integração Portagem",
            "description": "Linha 54 no sentido Portela -> Portagem.",
            "kind": "iframe",
            "src": "integration/portagem/l54_portagem_all.html",
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

    page = _read_template("master_dashboard.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__TABS_JSON__", json.dumps(tabs or _default_dashboard_tabs(), ensure_ascii=False))

    output_path.write_text(page, encoding="utf-8")
    return str(output_path)
