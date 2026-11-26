"""Redundância autocarro x metro, viagem a viagem (N2.1): quanto serviço SMTUC corre a par do metro.

A regra de "a par do metro" é a MESMA da extensão a par do metro das métricas por linha
(`overlap_db._route_direction_summaries`): um troço entre duas paragens consecutivas conta quando
as DUAS ficam a <= velocidade a pé x SPATIAL_OVERLAP_WALK_MIN de uma estação do metro. A diferença
é a unidade: a extensão mede o percurso representativo de cada sentido (km de linha); aqui somam-se
TODAS as viagens do dia de referência, cada uma com as suas paragens (autocarros·km e
autocarros·hora). É esta a medida do desperdício: o mesmo troço servido 60 vezes pesa 60 vezes.

Cada troço a par do metro é também atribuído a um CORREDOR do metro: as estações mais próximas das
suas duas pontas (a mesma estação nas duas pontas = troço junto a essa estação). As plataformas
"(asc)"/"(desc)" do NeTEx da fase 2 contam como a mesma estação.

Mesmas linhas que as métricas por linha (número público < 100). Paragens sem coordenadas saem da
sequência (os vizinhos passam a ser consecutivos), como no percurso representativo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from config import SPATIAL_OVERLAP_WALK_MIN, WALK_SPEED_M_MIN
from gtfs_processing.geo import haversine_m
from gtfs_processing.gtfs import load_gtfs_cached
from gtfs_processing.gtfs_probe import active_service_ids
from gtfs_processing.scenarios import Scenario, get_scenario, scenario_reference_day
from overlap.overlap_db import _line_numeric_prefix, line_to_route_ids

_PLATFORM_SUFFIX = re.compile(r"\s*\((?:asc|desc)\)\s*$", re.IGNORECASE)

SEGMENT_COLUMNS = (
    "line", "trip_id", "from_stop_id", "to_stop_id", "length_m", "minutes", "overlap", "station_a", "station_b",
)
LINE_COLUMNS = (
    "line", "viagens", "km", "km_metro", "pct_km_metro", "horas", "horas_metro", "viagens_com_troco_metro",
)
CORRIDOR_COLUMNS = ("station_a", "station_b", "km_metro", "horas_metro", "passagens", "linhas")


def station_name(stop_name: object) -> str:
    """Nome da estação sem o sufixo de plataforma: "Câmara (desc)" -> "Câmara"."""
    return _PLATFORM_SUFFIX.sub("", str(stop_name)).strip()


def _metro_stations(gtfs_metro) -> pd.DataFrame:
    stops = gtfs_metro.stops.dropna(subset=["stop_lat", "stop_lon"])
    return pd.DataFrame(
        {
            "station": stops["stop_name"].map(station_name).to_numpy(),
            "lat": stops["stop_lat"].astype(float).to_numpy(),
            "lon": stops["stop_lon"].astype(float).to_numpy(),
        }
    )


def bus_stop_overlap(gtfs_bus, gtfs_metro, catchment_m: float) -> pd.DataFrame:
    """Por paragem de autocarro com coordenadas: distância à estação do metro mais próxima, essa
    estação e se fica dentro de `catchment_m`. Índice = stop_id."""
    stops = gtfs_bus.stops.dropna(subset=["stop_lat", "stop_lon"])
    stops = stops.assign(stop_id=stops["stop_id"].astype(str)).drop_duplicates("stop_id")
    metro = _metro_stations(gtfs_metro)
    if stops.empty or metro.empty:
        return pd.DataFrame(columns=["distance_m", "station", "overlap"], index=pd.Index([], name="stop_id"))
    lat = stops["stop_lat"].astype(float).to_numpy()
    lon = stops["stop_lon"].astype(float).to_numpy()
    dist = haversine_m(lat[:, None], lon[:, None], metro["lat"].to_numpy()[None, :], metro["lon"].to_numpy()[None, :])
    nearest = dist.argmin(axis=1)
    best = dist[np.arange(len(stops)), nearest]
    return pd.DataFrame(
        {"distance_m": best, "station": metro["station"].to_numpy()[nearest], "overlap": best <= catchment_m},
        index=pd.Index(stops["stop_id"].astype(str).to_numpy(), name="stop_id"),
    )


def _active_trips_by_line(gtfs_bus, day: date) -> pd.DataFrame:
    active = active_service_ids(gtfs_bus, day)
    route_line = {route: line for line, routes in line_to_route_ids(gtfs_bus).items() for route in routes}
    trips = gtfs_bus.trips[gtfs_bus.trips["service_id"].isin(active)][["trip_id", "route_id"]]
    trips = trips.assign(line=trips["route_id"].map(route_line))
    prefix = trips["line"].map(_line_numeric_prefix)
    return trips[trips["line"].notna() & prefix.notna() & (prefix < 100)][["trip_id", "line"]]


def trip_segments(gtfs_bus, gtfs_metro, day: date, catchment_m: float | None = None) -> pd.DataFrame:
    """Um troço por par de paragens consecutivas de cada viagem com serviço em `day`. Colunas
    SEGMENT_COLUMNS; station_a/station_b (ordenadas) só nos troços a par do metro."""
    if catchment_m is None:
        catchment_m = WALK_SPEED_M_MIN * SPATIAL_OVERLAP_WALK_MIN
    trips = _active_trips_by_line(gtfs_bus, day)
    flags = bus_stop_overlap(gtfs_bus, gtfs_metro, catchment_m)
    st = gtfs_bus.stop_times[["trip_id", "stop_id", "stop_sequence", "arrival_seconds", "departure_seconds"]]
    st = st[st["trip_id"].isin(trips["trip_id"]) & st["stop_id"].astype(str).isin(flags.index)]
    if st.empty:
        return pd.DataFrame(columns=list(SEGMENT_COLUMNS))
    st = st.assign(_seq=pd.to_numeric(st["stop_sequence"]), stop_id=st["stop_id"].astype(str))
    st = st.sort_values(["trip_id", "_seq"], kind="mergesort").reset_index(drop=True)
    coords = gtfs_bus.stops.dropna(subset=["stop_lat", "stop_lon"]).assign(stop_id=lambda s: s["stop_id"].astype(str))
    coords = coords.drop_duplicates("stop_id").set_index("stop_id")
    lat = coords.loc[st["stop_id"], "stop_lat"].astype(float).to_numpy()
    lon = coords.loc[st["stop_id"], "stop_lon"].astype(float).to_numpy()

    same_trip = (st["trip_id"].to_numpy()[:-1] == st["trip_id"].to_numpy()[1:])
    a = np.flatnonzero(same_trip)
    b = a + 1
    overlap_stop = flags.loc[st["stop_id"], "overlap"].to_numpy(dtype=bool)
    station = flags.loc[st["stop_id"], "station"].to_numpy()
    overlap = overlap_stop[a] & overlap_stop[b]
    s1, s2 = station[a], station[b]
    first = np.where(s1 <= s2, s1, s2)
    second = np.where(s1 <= s2, s2, s1)
    seg = pd.DataFrame(
        {
            "trip_id": st["trip_id"].to_numpy()[a],
            "from_stop_id": st["stop_id"].to_numpy()[a],
            "to_stop_id": st["stop_id"].to_numpy()[b],
            "length_m": haversine_m(lat[a], lon[a], lat[b], lon[b]),
            "minutes": (st["arrival_seconds"].to_numpy()[b] - st["departure_seconds"].to_numpy()[a]) / 60.0,
            "overlap": overlap,
            "station_a": np.where(overlap, first, ""),
            "station_b": np.where(overlap, second, ""),
        }
    )
    seg = seg.merge(trips, on="trip_id", how="left")
    return seg[list(SEGMENT_COLUMNS)]


def redundancy_by_line(segments: pd.DataFrame) -> pd.DataFrame:
    """Por linha: viagens no dia, autocarros·km e autocarros·hora (totais e a par do metro)."""
    if segments.empty:
        return pd.DataFrame(columns=list(LINE_COLUMNS))
    seg = segments.assign(
        _m_metro=segments["length_m"].where(segments["overlap"], 0.0),
        _min_metro=segments["minutes"].where(segments["overlap"], 0.0),
    )
    per_trip = seg.groupby(["line", "trip_id"]).agg(
        m=("length_m", "sum"), m_metro=("_m_metro", "sum"), mins=("minutes", "sum"), mins_metro=("_min_metro", "sum"),
    )
    g = per_trip.groupby("line")
    out = pd.DataFrame(
        {
            "viagens": g.size(),
            "km": g["m"].sum() / 1000.0,
            "km_metro": g["m_metro"].sum() / 1000.0,
            "horas": g["mins"].sum() / 60.0,
            "horas_metro": g["mins_metro"].sum() / 60.0,
            "viagens_com_troco_metro": g["m_metro"].apply(lambda s: int((s > 0).sum())),
        }
    )
    out["pct_km_metro"] = np.where(out["km"] > 0, 100.0 * out["km_metro"] / out["km"], 0.0)
    out = out.reset_index().sort_values(["km_metro", "line"], ascending=[False, True], kind="mergesort")
    return out[list(LINE_COLUMNS)].reset_index(drop=True)


def redundancy_by_corridor(segments: pd.DataFrame) -> pd.DataFrame:
    """Por corredor do metro (par de estações): autocarros·km e ·hora a par dele, nº de passagens
    (troços de viagens) e linhas (separadas por ";")."""
    seg = segments[segments["overlap"]] if not segments.empty else segments
    if seg.empty:
        return pd.DataFrame(columns=list(CORRIDOR_COLUMNS))
    g = seg.groupby(["station_a", "station_b"])
    out = pd.DataFrame(
        {
            "km_metro": g["length_m"].sum() / 1000.0,
            "horas_metro": g["minutes"].sum() / 60.0,
            "passagens": g.size(),
            "linhas": g["line"].apply(lambda s: ";".join(sorted(set(map(str, s)), key=_line_key))),
        }
    ).reset_index()
    out = out.sort_values(["km_metro", "station_a", "station_b"], ascending=[False, True, True], kind="mergesort")
    return out[list(CORRIDOR_COLUMNS)].reset_index(drop=True)


def _line_key(line: str) -> tuple[float, str]:
    prefix = _line_numeric_prefix(line)
    return (prefix if prefix is not None else float("inf"), line)


@dataclass(frozen=True)
class Redundancy:
    scenario: str
    day: date
    by_line: pd.DataFrame
    by_corridor: pd.DataFrame

    def totals(self) -> dict[str, float]:
        bl = self.by_line
        km = float(bl["km"].sum())
        km_metro = float(bl["km_metro"].sum())
        return {
            "linhas": int(len(bl)),
            "linhas_com_troco_metro": int((bl["km_metro"] > 0).sum()),
            "viagens": int(bl["viagens"].sum()),
            "km": km,
            "km_metro": km_metro,
            "pct_km_metro": 100.0 * km_metro / km if km > 0 else 0.0,
            "horas": float(bl["horas"].sum()),
            "horas_metro": float(bl["horas_metro"].sum()),
        }


def scenario_redundancy(scenario: str | Scenario | None = None, day: date | None = None) -> Redundancy:
    """Redundância do cenário no seu dia de referência (ou em `day`, ex.: sábado da semana-tipo)."""
    sc = get_scenario(scenario)
    day = day or scenario_reference_day(sc)
    segments = trip_segments(load_gtfs_cached(sc.smtuc), load_gtfs_cached(sc.metro), day)
    return Redundancy(sc.name, day, redundancy_by_line(segments), redundancy_by_corridor(segments))
