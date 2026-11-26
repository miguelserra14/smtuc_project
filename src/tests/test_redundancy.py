"""Redundância autocarro x metro viagem a viagem (N2.1, overlap/redundancy.py).

Feeds sintéticos em memória: não lê dados nem escreve em outputs/."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from gtfs_processing.gtfs import GTFSData
from overlap.overlap_db import _route_direction_summaries
from overlap.redundancy import (
    bus_stop_overlap,
    redundancy_by_corridor,
    redundancy_by_line,
    station_name,
    trip_segments,
)

MONDAY = date(2026, 11, 9)
SATURDAY = date(2026, 11, 14)
CATCHMENT_M = 240.0
_LAT0 = 40.2
_M_PER_DEG_LAT = 111_000.0


def _north(m: float) -> float:
    return _LAT0 + m / _M_PER_DEG_LAT


def _calendar() -> pd.DataFrame:
    return pd.DataFrame(
        [("U", 1, 1, 1, 1, 1, 0, 0, 20260101, 20261231), ("S", 0, 0, 0, 0, 0, 1, 0, 20260101, 20261231)],
        columns=["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                 "start_date", "end_date"],
    )


def _bus_feed(extra_stops: list[tuple] | None = None, trips_spec: list[tuple] | None = None) -> GTFSData:
    """Paragens p0..p4 em fila para norte, 500 m entre cada uma. Só p2 e p3 ficam perto do metro."""
    stops = [(f"p{i}", _north(500.0 * i), -8.4) for i in range(5)] + (extra_stops or [])
    stops_df = pd.DataFrame(stops, columns=["stop_id", "stop_lat", "stop_lon"])
    routes = pd.DataFrame([("r1", "5"), ("r2", "101")], columns=["route_id", "route_short_name"])
    trips_spec = trips_spec or [
        ("r1", "U", "t1", "p0 p1 p2 p3 p4", 6 * 3600),
        ("r1", "U", "t2", "p0 p1 p2 p3 p4", 7 * 3600),
        ("r1", "U", "t3", "p2 p3", 8 * 3600),          # viagem curta só no troço a par do metro
        ("r1", "S", "t4", "p0 p1 p2 p3 p4", 9 * 3600),  # sábado
        ("r2", "U", "t5", "p2 p3", 10 * 3600),          # linha >= 100: fora, como nas métricas
    ]
    trips = pd.DataFrame([(r, s, t, "0") for r, s, t, _, _ in trips_spec],
                         columns=["route_id", "service_id", "trip_id", "direction_id"])
    rows = []
    for _, _, trip, seq_stops, start in trips_spec:
        for k, stop in enumerate(seq_stops.split()):
            t = start + 120 * k  # 2 min entre paragens consecutivas
            rows.append({"trip_id": trip, "stop_id": stop, "stop_sequence": k + 1,
                         "arrival_seconds": t, "departure_seconds": t})
    return GTFSData(routes=routes, trips=trips, stop_times=pd.DataFrame(rows), stops=stops_df,
                    shapes=pd.DataFrame(), calendar=_calendar(), calendar_dates=pd.DataFrame())


def _metro_feed() -> GTFSData:
    east_100m = 100.0 / 85_000.0  # ~100 m para leste a 40,2 N
    stops = pd.DataFrame(
        [("m1", "Alfa", _north(1000.0), -8.4 + east_100m),
         ("m2", "Beta (asc)", _north(1500.0), -8.4),
         ("m3", "Beta (desc)", _north(1500.0) + 30 / _M_PER_DEG_LAT, -8.4)],
        columns=["stop_id", "stop_name", "stop_lat", "stop_lon"],
    )
    empty = pd.DataFrame()
    return GTFSData(routes=empty, trips=empty, stop_times=empty, stops=stops, shapes=empty,
                    calendar=empty, calendar_dates=empty)


def test_station_name_drops_the_platform_suffix() -> None:
    assert station_name("Câmara (desc)") == "Câmara"
    assert station_name("República (ASC) ") == "República"
    assert station_name("Lousã - Estação") == "Lousã - Estação"


def test_stop_flags_use_the_nearest_station() -> None:
    flags = bus_stop_overlap(_bus_feed(), _metro_feed(), CATCHMENT_M)
    assert flags["overlap"].to_dict() == {"p0": False, "p1": False, "p2": True, "p3": True, "p4": False}
    assert flags.loc["p2", "station"] == "Alfa" and flags.loc["p3", "station"] == "Beta"


def test_every_trip_of_the_day_counts_with_its_own_stops() -> None:
    seg = trip_segments(_bus_feed(), _metro_feed(), MONDAY, CATCHMENT_M)
    assert set(seg["line"]) == {"5"}  # a 101 fica de fora; a t4 é de sábado
    by_line = redundancy_by_line(seg).set_index("line")
    five = by_line.loc["5"]
    assert five["viagens"] == 3 and five["viagens_com_troco_metro"] == 3
    assert five["km"] == pytest.approx(2 * 2.0 + 0.5, rel=5e-3)
    assert five["km_metro"] == pytest.approx(3 * 0.5, rel=5e-3)
    assert five["pct_km_metro"] == pytest.approx(100 * 1.5 / 4.5, rel=5e-3)
    assert five["horas_metro"] == pytest.approx(3 * 2 / 60)
    assert five["horas"] == pytest.approx((2 * 4 * 2 + 2) / 60)

    corridor = redundancy_by_corridor(seg)
    assert corridor[["station_a", "station_b", "passagens", "linhas"]].values.tolist() == [["Alfa", "Beta", 3, "5"]]
    assert corridor.loc[0, "km_metro"] == pytest.approx(1.5, rel=5e-3)


def test_saturday_uses_the_saturday_service() -> None:
    by_line = redundancy_by_line(trip_segments(_bus_feed(), _metro_feed(), SATURDAY, CATCHMENT_M))
    assert by_line[["line", "viagens"]].values.tolist() == [["5", 1]]


def test_same_rule_as_the_line_extension_next_to_the_metro() -> None:
    """Viagens todas no percurso representativo -> autocarros·km a par do metro = viagens x a
    extensão a par do metro desse percurso (a regra das métricas por linha)."""
    bus, metro = _bus_feed(), _metro_feed()
    trips = [("r1", "U", f"t{i}", "p0 p1 p2 p3 p4", 6 * 3600 + 600 * i) for i in range(4)]
    bus = _bus_feed(trips_spec=trips)
    (summary,) = _route_direction_summaries(bus, "r1", metro.stops, CATCHMENT_M)
    five = redundancy_by_line(trip_segments(bus, metro, MONDAY, CATCHMENT_M)).iloc[0]
    assert five["km_metro"] == pytest.approx(4 * summary["overlap_ext_m"] / 1000.0)
    assert five["km"] == pytest.approx(4 * summary["total_ext_m"] / 1000.0)


def test_a_stop_without_coordinates_leaves_the_sequence() -> None:
    trips = [("r1", "U", "t1", "p2 px p3", 6 * 3600)]
    bus = _bus_feed(extra_stops=[("px", None, None)], trips_spec=trips)
    seg = trip_segments(bus, _metro_feed(), MONDAY, CATCHMENT_M)
    assert seg[["from_stop_id", "to_stop_id", "overlap"]].values.tolist() == [["p2", "p3", True]]
    assert seg.loc[0, "minutes"] == pytest.approx(4.0)


def test_no_service_gives_empty_tables() -> None:
    sunday = date(2026, 11, 15)
    seg = trip_segments(_bus_feed(), _metro_feed(), sunday, CATCHMENT_M)
    assert seg.empty
    assert redundancy_by_line(seg).empty and redundancy_by_corridor(seg).empty
