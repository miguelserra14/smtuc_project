"""Regras que as versões vetorizadas (T6) têm de manter, iguais às dos antigos ciclos por viagem.

- `_first_passages` (chegadas a uma paragem e escolha da paragem do nó): conta a 1.ª passagem de
  cada viagem pela paragem (menor stop_sequence) e, com origem, só se a origem vem ANTES dessa
  passagem; a escolha da paragem desempata pela ordem das candidatas.
- `overlap_db.iter_route_direction_stop_arrays`: memorizado por feed e rota, arrays só de
  leitura, e um GTFSData novo nunca recebe resultados de outro.
"""

from __future__ import annotations

import gc

import numpy as np
import pandas as pd
import pytest

from gtfs_processing.gtfs import GTFSData
from overlap import overlap_db
from overlap.transit import _arrival_events_for_stop, _arrival_times_for_stop, _pick_best_target_stop_id


def _feed(rows: list[tuple[str, str, int, str]], stops: dict[str, tuple[float, float]] | None = None) -> GTFSData:
    st = pd.DataFrame(rows, columns=["trip_id", "stop_id", "stop_sequence", "arrival_time"])
    st["departure_time"] = st["arrival_time"]
    trips = pd.DataFrame({"trip_id": st["trip_id"].unique()})
    trips["route_id"] = "R"
    trips["service_id"] = "WD"
    trips["direction_id"] = "0"
    stops = stops or {sid: (40.0 + i * 0.01, -8.4) for i, sid in enumerate(sorted(st["stop_id"].unique()))}
    stops_df = pd.DataFrame([(k, v[0], v[1]) for k, v in stops.items()], columns=["stop_id", "stop_lat", "stop_lon"])
    return GTFSData(routes=pd.DataFrame({"route_id": ["R"]}), trips=trips, stop_times=st, stops=stops_df,
                    shapes=pd.DataFrame(), calendar=pd.DataFrame(), calendar_dates=pd.DataFrame())


# Circular: L passa em P duas vezes (seq 1 e 4); a origem A vem entre as duas passagens.
LOOP = [
    ("L", "P", 1, "08:00:00"), ("L", "A", 2, "08:05:00"), ("L", "B", 3, "08:10:00"), ("L", "P", 4, "08:20:00"),
    ("M", "A", 1, "09:00:00"), ("M", "P", 2, "09:10:00"),
    ("N", "B", 1, "10:00:00"), ("N", "Q", 2, "10:10:00"),
]


def test_first_passage_and_origin_before_it() -> None:
    gtfs = _feed(LOOP)
    trips = gtfs.trips
    # Sem origem: 1.ª passagem de cada viagem por P (L às 08:00, não às 08:20).
    assert _arrival_times_for_stop(gtfs, trips, "P") == ["08:00:00", "09:10:00"]
    # Origem A: em L vem DEPOIS da 1.ª passagem por P -> L não conta (regra antiga mantida).
    assert _arrival_times_for_stop(gtfs, trips, "P", ["A"]) == ["09:10:00"]
    events = _arrival_events_for_stop(gtfs, trips, "P", None, {"L": "54", "M": "38"})
    assert events == [{"time": "08:00:00", "line": "54"}, {"time": "09:10:00", "line": "38"}]


def test_best_stop_counts_trips_and_breaks_ties_by_candidate_order() -> None:
    gtfs = _feed(LOOP)
    trips = gtfs.trips
    assert _pick_best_target_stop_id(gtfs, trips, ["Q", "P"]) == "P"  # P 2 viagens (L, M), Q 1 (N)
    assert _pick_best_target_stop_id(gtfs, trips, ["Q", "B", "P"]) == "B"  # B 2 (L, N), P 2 -> a 1.ª com o máximo
    assert _pick_best_target_stop_id(gtfs, trips, ["Q", "P", "B"]) == "P"
    # Com origem A: P só conta M (em L a A vem depois), B conta L -> empate 1-1 -> a 1.ª.
    assert _pick_best_target_stop_id(gtfs, trips, ["P", "B"], ["A"]) == "P"
    assert _pick_best_target_stop_id(gtfs, trips, ["Q", "B"], ["A"]) == "B"
    assert _pick_best_target_stop_id(gtfs, trips.iloc[0:0], ["Q", "B"]) == "Q"  # sem viagens -> a 1.ª


def test_route_arrays_are_memoized_read_only_and_per_feed() -> None:
    gtfs = _feed(LOOP)
    first = overlap_db.iter_route_direction_stop_arrays(gtfs, "R")
    again = overlap_db.iter_route_direction_stop_arrays(gtfs, "R")
    assert first[0][0] is again[0][0]  # memorizado
    lat, _lon, stop_ids, n = first[0]
    assert list(stop_ids) == ["P", "A", "B", "P"] and n == 4  # a viagem com mais paragens, por ordem
    with pytest.raises(ValueError):
        lat[0] = 0.0  # só de leitura: ninguém pode estragar a memória partilhada

    other = _feed([("X", "A", 1, "08:00:00"), ("X", "B", 2, "08:10:00")])
    assert list(overlap_db.iter_route_direction_stop_arrays(other, "R")[0][2]) == ["A", "B"]
    key = id(other)
    del other
    gc.collect()
    assert key not in overlap_db._TRIP_INDEXES  # libertado com o feed (sem resultados velhos por id reutilizado)
    assert np.array_equal(overlap_db.iter_route_direction_stop_arrays(gtfs, "R")[0][1], first[0][1])
