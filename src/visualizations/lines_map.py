from __future__ import annotations

from pathlib import Path
from typing import Iterable

try:
    import folium
    from folium import FeatureGroup
except Exception:  # pragma: no cover - optional dependency
    folium = None

import pandas as pd

from config import STADIUM_COORD
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
            # Simplified fallback: draw metro stops as markers only (avoid reconstructing many polylines
            # from trips/stop_times which can create confusing/overlapping traces and heavy DOM).
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

    # Helper to add SMTUC line feature groups
    def _add_line_groups(lines: Iterable[str], color: str, prefix: str) -> None:
        for line in lines:
            fg = FeatureGroup(name=f"{prefix} {line}", show=False)
            try:
                # get route ids for this line
                line_map = _line_to_route_ids(gtfs_smtuc)
                route_ids = line_map.get(str(line), [])
                for rid in route_ids:
                    for lat_arr, lon_arr, _ in _iter_route_direction_stop_arrays(gtfs_smtuc, rid):
                        pts = list(zip(lat_arr.tolist(), lon_arr.tolist()))
                        if len(pts) >= 2:
                            folium.PolyLine(pts, color=color, weight=3, opacity=0.85).add_to(fg)
            except Exception:
                # best-effort: skip if anything fails
                continue
            m.add_child(fg)

    _add_line_groups(top_lines, "#2e7d32", "Top")
    _add_line_groups(bottom_lines, "#b71c1c", "Bottom")

    folium.LayerControl(collapsed=False).add_to(m)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Save map
    _write_folium_html(m, out_path)
    return str(out_path)
