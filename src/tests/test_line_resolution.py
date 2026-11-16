"""Resolução "número da linha -> viagens" em overlap.transit._resolve_bus_arrival_events.

Nos feeds SMTUC antigos o route_id "54" é a linha 5F (Pedrulha-Portagem) e a 54 verdadeira tem
route_id 684; o Ep202 (jan/2026) ainda nem tinha a 54. O código antigo, quando não encontrava o
número público, procurava no route_id e devolvia a 5F sem erro.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd
import pytest

from gtfs_processing.gtfs import GTFSData
from overlap.transit import _node_stop_ids, _origin_candidates_by_line, _resolve_bus_arrival_events, bus_origin_label

DAY = date(2026, 5, 11)  # segunda-feira


def _feed(routes: list[tuple[str, str]], with_short_names: bool = True) -> GTFSData:
    """Cada rota tem 1 viagem de dia útil A (Portela) -> B (Portagem); a hora de partida
    identifica a rota (route_id "54" -> 07:00, "684" -> 08:00, "38" -> 09:00)."""
    hour = {"54": 7, "684": 8, "38": 9, "10": 10}
    routes_df = pd.DataFrame(routes, columns=["route_id", "route_short_name"])
    if not with_short_names:
        routes_df = routes_df.drop(columns="route_short_name")
    trips = pd.DataFrame(
        [{"route_id": rid, "service_id": "WD", "trip_id": f"T{rid}", "direction_id": 0} for rid, _ in routes]
    )
    stop_times = pd.DataFrame(
        [
            row
            for rid, _ in routes
            for row in (
                {"trip_id": f"T{rid}", "stop_id": "A", "stop_sequence": 1,
                 "arrival_time": f"{hour[rid]:02d}:00:00", "departure_time": f"{hour[rid]:02d}:00:00"},
                {"trip_id": f"T{rid}", "stop_id": "B", "stop_sequence": 2,
                 "arrival_time": f"{hour[rid]:02d}:10:00", "departure_time": f"{hour[rid]:02d}:10:00"},
            )
        ]
    )
    stops = pd.DataFrame(
        {"stop_id": ["A", "B"], "stop_name": ["Portela", "Portagem"], "stop_lat": [40.19, 40.20], "stop_lon": [-8.40, -8.43]}
    )
    calendar = pd.DataFrame(
        [{"service_id": "WD", "monday": 1, "tuesday": 1, "wednesday": 1, "thursday": 1, "friday": 1,
          "saturday": 0, "sunday": 0, "start_date": 20260101, "end_date": 20261231}]
    )
    return GTFSData(routes=routes_df, trips=trips, stop_times=stop_times, stops=stops, shapes=pd.DataFrame(),
                    calendar=calendar, calendar_dates=pd.DataFrame())


def _times(gtfs: GTFSData, line) -> list[str]:
    events, _, _ = _resolve_bus_arrival_events(gtfs, DAY, ["B"], defaultdict(lambda: ["A"]), line)
    return [ev["time"][:5] for ev in events]


def test_line_is_matched_by_public_number_not_route_id() -> None:
    # Como no Ep212: route_id "54" = 5F, a 54 verdadeira é a route_id 684.
    gtfs = _feed([("54", "5F"), ("684", "54")])
    assert _times(gtfs, "54") == ["08:10"]
    assert _times(gtfs, "5F") == ["07:10"]


def test_missing_line_raises_instead_of_using_route_id() -> None:
    # Como no Ep202: não há nenhuma linha com número 54, mas há route_id "54" (= 5F).
    gtfs = _feed([("54", "5F"), ("38", "38")])
    with pytest.raises(ValueError, match="não encontrada.*54"):
        _times(gtfs, "54")


def test_any_missing_line_in_a_combination_raises() -> None:
    gtfs = _feed([("54", "5F"), ("38", "38")])
    with pytest.raises(ValueError, match="54"):
        _times(gtfs, ["54", "38"])
    assert _times(gtfs, ["38"]) == ["09:10"]


def test_route_id_is_used_only_when_feed_has_no_public_numbers() -> None:
    assert _times(_feed([("54", ""), ("10", "")], with_short_names=False), "54") == ["07:10"]
    assert _times(_feed([("54", "nan"), ("10", "nan")]), "10") == ["10:10"]


# --------------------------------------------------------------------------- D2.4: nó por distância e origem por linha


def _stops_feed() -> GTFSData:
    gtfs = _feed([("684", "54"), ("38", "38")])
    # C fica a ~100 m de B (como "Parque 2" e "Portagem" no Ep225); D a ~1,1 km.
    gtfs.stops = pd.DataFrame({
        "stop_id": ["A", "B", "C", "D"],
        "stop_name": ["Portela", "Portagem", "Parque 2", "Santa Clara (Junta de Freguesia)"],
        "stop_lat": [40.19, 40.20, 40.2009, 40.21],
        "stop_lon": [-8.40, -8.43, -8.43, -8.43],
    })
    return gtfs


def test_node_includes_stops_within_the_radius() -> None:
    gtfs = _stops_feed()
    assert _node_stop_ids(gtfs, "Portagem", radius_m=250) == ["B", "C"]
    assert _node_stop_ids(gtfs, "Portagem", radius_m=50) == ["B"]
    assert _node_stop_ids(gtfs, "Portagem", radius_m=0) == ["B"]
    # Nome com parênteses: procura literal (antes era uma regex e o grupo "(...)" falhava em parte).
    assert _node_stop_ids(gtfs, "Santa Clara (Junta de Freguesia)", radius_m=0) == ["D"]


def test_origin_can_be_given_per_line() -> None:
    gtfs = _stops_feed()
    by_line = _origin_candidates_by_line(gtfs, {"54": "Portela", 38: "Santa Clara (Junta de Freguesia)"}, ["54", "38"], 0)
    assert by_line == {"54": ["A"], "38": ["D"]}
    assert _origin_candidates_by_line(gtfs, "Portela", ["54", "38"], 0) == {"54": ["A"], "38": ["A"]}
    with pytest.raises(ValueError, match="Origem em falta.*38"):
        _origin_candidates_by_line(gtfs, {"54": "Portela"}, ["54", "38"], 0)
    assert bus_origin_label({"54": "Portela", "38": "Santa Clara"}) == "54: Portela; 38: Santa Clara"


def test_line_with_trips_but_none_from_its_origin_raises() -> None:
    # As viagens vão de A para B: com a origem em D (que nenhuma viagem visita) antes saía 0 em silêncio.
    gtfs = _stops_feed()
    with pytest.raises(ValueError, match="Linha 38: 1 viagens"):
        _resolve_bus_arrival_events(gtfs, DAY, ["B"], {"54": ["A"], "38": ["D"]}, ["54", "38"])
