"""Shared utilities for population analysis module."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pandas as pd
import geopandas as gpd

from config import STADIUM_COORD
from paths import PROJECT_ROOT

if TYPE_CHECKING:
    pass


def project_root() -> Path:
    """Get the root directory of the project."""
    return PROJECT_ROOT


def ensure_crs(gdf: gpd.GeoDataFrame, target_crs: str = "EPSG:3763") -> gpd.GeoDataFrame:
    """
    Ensure GeoDataFrame has correct CRS, converting if necessary.
    
    Args:
        gdf: GeoDataFrame to process
        target_crs: Target CRS (default EPSG:3763)
    
    Returns:
        GeoDataFrame with correct CRS
    """
    if gdf.crs is None:
        return gdf.set_crs(target_crs)
    elif str(gdf.crs).upper() != target_crs.upper():
        return gdf.to_crs(target_crs)
    return gdf


def create_stadium_point(crs: str = "EPSG:3763") -> gpd.GeoDataFrame:
    """
    Create a GeoDataFrame with stadium point.
    
    Args:
        crs: Target CRS
    
    Returns:
        GeoDataFrame with stadium point
    """
    stadium_geo = gpd.GeoDataFrame(
        {"name": ["stadium"]},
        geometry=gpd.points_from_xy([STADIUM_COORD[1]], [STADIUM_COORD[0]]),
        crs="EPSG:4326",
    )
    if crs != "EPSG:4326":
        stadium_geo = stadium_geo.to_crs(crs)
    return stadium_geo


def infer_bgri_id_col(columns) -> str:
    """
    Infer BGRI ID column from available columns.
    
    Args:
        columns: Column names
    
    Returns:
        Name of BGRI ID column
    """
    cols = list(columns)
    if "BGRI2021" in cols:
        return "BGRI2021"
    for c in cols:
        if "BGRI" in c.upper():
            return c
    raise ValueError("Não foi possível inferir a coluna identificadora BGRI.")


def load_bgri_file(
    gpkg_path: str,
    layer: str = "BGRI2021_0603",
    target_crs: str = "EPSG:3763",
) -> gpd.GeoDataFrame:
    """
    Load BGRI from GeoPackage and ensure valid state.

    O GeoPackage é lido UMA vez por processo (memória por caminho+camada+CRS+tamanho+mtime) e
    cada chamada recebe uma CÓPIA, que pode alterar à vontade. Antes cada secção do regenerate /
    snapshot voltava a lê-lo do disco (10 leituras num regenerate).

    Args:
        gpkg_path: Path to GeoPackage
        layer: Layer name
        target_crs: Target CRS

    Returns:
        Processed GeoDataFrame
    """
    path = Path(gpkg_path).resolve()
    stat = path.stat()
    return _read_bgri_cached(str(path), layer, target_crs, stat.st_size, stat.st_mtime_ns).copy()


@lru_cache(maxsize=4)
def _read_bgri_cached(path: str, layer: str, target_crs: str, size: int, mtime_ns: int) -> gpd.GeoDataFrame:
    """Leitura real (nunca devolver este objeto a quem chama - ver load_bgri_file)."""
    bgri = gpd.read_file(path, layer=layer)
    if bgri.empty:
        raise ValueError(f"Layer {layer} vazio")

    # Remove rows without geometry
    bgri = bgri[~bgri.geometry.isna()].copy()

    # Ensure correct CRS
    return ensure_crs(bgri, target_crs)


__all__ = [
    "project_root",
    "ensure_crs",
    "create_stadium_point",
    "infer_bgri_id_col",
    "load_bgri_file",
]
