"""Sentido do metro no nó de integração (bus->metro): define-se por paragens, não por códigos.

No feed sintético `direction_id` 1 = "a partir de Portagem" (sentido Serpins); no GTFS oficial
de 2025 é o 0. O filtro antigo (direction_id + route_id do config) trocava de sentido em
silêncio ao trocar de dados. overlap.transit._towards_arrival_times_for_stop escolhe as viagens
que passam numa paragem DEPOIS do nó.
"""

from __future__ import annotations

import pandas as pd

from gtfs_processing.gtfs import GTFSData
from overlap.transit import _towards_arrival_times_for_stop

# Linha P (Portagem) - V (Vale das Flores) - S (Serpins).
STOPS = pd.DataFrame({"stop_id": ["P", "V", "S"], "stop_name": ["Portagem", "Vale das Flores", "Serpins"]})


def _feed(outbound_direction: str) -> GTFSData:
    inbound = "1" if outbound_direction == "0" else "0"
    trips = pd.DataFrame(
        [
            {"route_id": "R", "service_id": "WD", "trip_id": "OUT_08", "direction_id": outbound_direction},  # P -> S
            {"route_id": "R", "service_id": "WD", "trip_id": "OUT_09", "direction_id": outbound_direction},  # P -> V (vaivém urbano)
            {"route_id": "R", "service_id": "WD", "trip_id": "IN_10", "direction_id": inbound},              # S -> P (termina em P)
            {"route_id": "X", "service_id": "WD", "trip_id": "RAMAL_11", "direction_id": outbound_direction},  # ramal que TERMINA em P
        ]
    )
    rows = []
    for trip, seq in (
        ("OUT_08", [("P", "08:00:00"), ("V", "08:10:00"), ("S", "08:40:00")]),
        ("OUT_09", [("P", "09:00:00"), ("V", "09:10:00")]),
        ("IN_10", [("S", "10:00:00"), ("V", "10:30:00"), ("P", "10:40:00")]),
        ("RAMAL_11", [("V", "11:00:00"), ("P", "11:10:00")]),
    ):
        for i, (stop, t) in enumerate(seq, start=1):
            rows.append({"trip_id": trip, "stop_id": stop, "stop_sequence": i, "arrival_time": t, "departure_time": t})
    return GTFSData(routes=pd.DataFrame(), trips=trips, stop_times=pd.DataFrame(rows), stops=STOPS,
                    shapes=pd.DataFrame(), calendar=pd.DataFrame(), calendar_dates=pd.DataFrame())


def test_direction_comes_from_stop_order_not_direction_id() -> None:
    synthetic_like = _feed(outbound_direction="1")
    official_like = _feed(outbound_direction="0")
    for gtfs in (synthetic_like, official_like):
        # Sentido Serpins a partir de Portagem = passa DEPOIS em Vale das Flores.
        assert _towards_arrival_times_for_stop(gtfs, gtfs.trips, "P", ["V"]) == ["08:00:00", "09:00:00"]


def test_trips_ending_at_the_node_never_count_as_departures() -> None:
    gtfs = _feed(outbound_direction="0")
    # IN_10 e RAMAL_11 terminam em P: não há nada depois, logo não são partidas de P.
    assert _towards_arrival_times_for_stop(gtfs, gtfs.trips, "P", ["V", "S"]) == ["08:00:00", "09:00:00"]
    # No sentido contrário (passa em P depois de V), conta a chegada a V das viagens que vão para P.
    assert _towards_arrival_times_for_stop(gtfs, gtfs.trips, "V", ["P"]) == ["10:30:00", "11:00:00"]


def test_towards_the_far_terminal_excludes_short_turns() -> None:
    gtfs = _feed(outbound_direction="0")
    assert _towards_arrival_times_for_stop(gtfs, gtfs.trips, "P", ["S"]) == ["08:00:00"]  # o vaivém só vai até V
    assert _towards_arrival_times_for_stop(gtfs, gtfs.trips, "P", []) == []
