"""Peças de base do T1: horas GTFS, distância haversine e o carregamento dos feeds (ids como texto,
horas estritas, cache única)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gtfs_processing import gtfs as gtfs_mod
from gtfs_processing.geo import haversine_m
from gtfs_processing.timeutil import hhmmss_to_seconds, seconds_to_hhmmss, series_hhmmss_to_seconds


# --- horas -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, secs", [("00:00:00", 0), ("7:05:09", 25509), ("25:10:00", 90600), (" 08:00:00 ", 28800)])
def test_hhmmss_roundtrip(text: str, secs: int) -> None:
    assert hhmmss_to_seconds(text) == secs
    assert hhmmss_to_seconds(seconds_to_hhmmss(secs)) == secs


@pytest.mark.parametrize("bad", ["", None, float("nan"), "8:00", "08:60:00", "08:00:61", "ab:cd:ef"])
def test_hhmmss_is_strict(bad) -> None:
    with pytest.raises(ValueError):
        hhmmss_to_seconds(bad)


def test_series_parse_matches_scalar_and_rejects_blanks() -> None:
    values = pd.Series(["06:00:00", "24:30:15", "7:01:02"])
    assert series_hhmmss_to_seconds(values).tolist() == [hhmmss_to_seconds(v) for v in values]
    with pytest.raises(ValueError, match="1 valor"):
        series_hhmmss_to_seconds(pd.Series(["06:00:00", None]))


# --- distância ---------------------------------------------------------------------------------

def test_haversine_scalar_and_broadcast() -> None:
    # 1 grau de latitude na esfera de 6371 km
    assert haversine_m(40.0, -8.0, 41.0, -8.0) == pytest.approx(6371000.0 * np.pi / 180.0)
    lats, lons = np.array([40.2, 40.21, 40.2]), np.array([-8.4, -8.4, -8.41])
    one_to_many = haversine_m(40.2, -8.4, lats, lons)
    assert isinstance(one_to_many, np.ndarray) and one_to_many[0] == 0.0
    pairwise = haversine_m(lats[:-1], lons[:-1], lats[1:], lons[1:])
    assert pairwise.shape == (2,)
    matrix = haversine_m(lats[:, None], lons[:, None], lats[None, :], lons[None, :])
    assert matrix.shape == (3, 3) and np.allclose(matrix, matrix.T)


# --- carregamento ------------------------------------------------------------------------------

def _write_feed(folder: Path, stop_times: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "routes.txt").write_text("route_id,route_short_name\n054,54\n9,\n", encoding="utf-8")
    (folder / "trips.txt").write_text("route_id,service_id,trip_id\n054,1,10\n", encoding="utf-8")
    (folder / "stops.txt").write_text("stop_id,stop_name,stop_lat,stop_lon\n007,A,40.2,-8.4\n8,B,40.21,-8.41\n", encoding="utf-8")
    (folder / "stop_times.txt").write_text(stop_times, encoding="utf-8")
    (folder / "calendar.txt").write_text(
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "1,1,1,1,1,1,0,0,20260101,20261231\n",
        encoding="utf-8",
    )
    return folder


_GOOD_STOP_TIMES = "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n10,07:00:00,07:00:00,007,1\n10,07:05:00,07:05:30,8,2\n"


def test_ids_are_read_as_text(tmp_path: Path) -> None:
    feed = gtfs_mod.load_gtfs(source_dir=str(_write_feed(tmp_path / "f", _GOOD_STOP_TIMES)))
    # zeros à esquerda preservados e o mesmo tipo em todas as tabelas -> merges diretos
    assert feed.stops["stop_id"].tolist() == ["007", "8"]
    assert feed.routes["route_id"].tolist() == ["054", "9"]
    assert feed.trips["trip_id"].tolist() == ["10"]
    assert feed.calendar["service_id"].tolist() == ["1"]
    # número público vazio NÃO transforma "54" em "54.0"
    assert feed.routes["route_short_name"].iloc[0] == "54"
    merged = feed.stop_times.merge(feed.stops, on="stop_id", how="inner")
    assert len(merged) == 2
    assert feed.stop_times["departure_seconds"].tolist() == [25200, 25530]


def test_blank_stop_time_is_an_error_not_midnight(tmp_path: Path) -> None:
    folder = _write_feed(
        tmp_path / "f",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n10,07:00:00,07:00:00,007,1\n10,,,8,2\n",
    )
    with pytest.raises(ValueError, match="arrival_time"):
        gtfs_mod.load_gtfs(source_dir=str(folder))


def test_single_shared_cache() -> None:
    """overlap_db, transit, overlap, lines_map e operations_population usam TODOS a mesma cache."""
    from overlap import overlap, overlap_db, transit
    from population import operations_population
    from visualizations import lines_map

    for module in (overlap, overlap_db, transit, operations_population, lines_map):
        assert module.load_gtfs_cached is gtfs_mod.load_gtfs_cached, module.__name__
