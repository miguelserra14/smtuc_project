"""Distância haversine (esfera de raio 6371 km). Fonte ÚNICA no projeto - antes havia quatro
implementações (math, pandas.apply e duas numpy)."""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Distância em metros entre (lat1, lon1) e (lat2, lon2), em graus.

    Aceita escalares ou arrays com broadcasting numpy: ponto-contra-muitos (`lat1` escalar,
    `lat2` array) ou par-a-par (arrays do mesmo tamanho). Devolve float para escalares e
    np.ndarray caso contrário.
    """
    lat1_r = np.radians(np.asarray(lat1, dtype="float64"))
    lon1_r = np.radians(np.asarray(lon1, dtype="float64"))
    lat2_r = np.radians(np.asarray(lat2, dtype="float64"))
    lon2_r = np.radians(np.asarray(lon2, dtype="float64"))
    a = np.sin((lat2_r - lat1_r) / 2.0) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin((lon2_r - lon1_r) / 2.0) ** 2
    out = EARTH_RADIUS_M * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return float(out) if np.ndim(out) == 0 else out
