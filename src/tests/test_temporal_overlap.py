"""Overlap temporal num GTFS sintético (passo 6.1): fixa a regra ATUAL de
`overlap._temporal_overlap_passages`, partilhada pelas métricas por linha e pela lista de eventos.

Regra: uma passagem SMTUC é candidata se houver uma paragem do metro a <= walk x minutos; tem
overlap se nessa paragem houver uma passagem do metro a <= N minutos cujo serviço partilhe algum
dia da semana. Serviço impossível de resolver conta como partilhado - comportamento herdado que o
passo T3 (3.4) vai rever; quando mudar, este teste muda com ele.
"""

from __future__ import annotations

import pandas as pd
import pytest

import overlap.overlap as ov
from gtfs_processing.gtfs import GTFSData

M_PER_DEG_LAT = 6371000.0 * 3.141592653589793 / 180.0
LAT0, LON0 = 40.0, -8.0
PARAMS = dict(walk_speed_m_min=80.0, temporal_overlap_max_min=5.0, spatial_overlap_walk_min=3.0)  # 240 m, 300 s


def _s(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


def _feed(stops: dict[str, float], trips: list[tuple[str, str, str, list[tuple[str, str]]]], calendar: pd.DataFrame) -> GTFSData:
    """trips = [(trip_id, route_id, service_id, [(stop_id, "HH:MM"), ...])]; stops = {id: metros a norte}."""
    st = [
        {"trip_id": t, "stop_id": sid, "stop_sequence": i + 1, "arrival_seconds": _s(hm), "departure_seconds": _s(hm)}
        for t, _r, _sv, seq in trips
        for i, (sid, hm) in enumerate(seq)
    ]
    routes = sorted({r for _t, r, _sv, _seq in trips})
    return GTFSData(
        routes=pd.DataFrame({"route_id": routes, "route_short_name": [r.removeprefix("R") for r in routes]}),
        trips=pd.DataFrame([{"trip_id": t, "route_id": r, "service_id": sv} for t, r, sv, _seq in trips]),
        stop_times=pd.DataFrame(st),
        stops=pd.DataFrame(
            {
                "stop_id": list(stops),
                "stop_name": [f"Paragem {k}" for k in stops],
                "stop_lat": [LAT0 + m / M_PER_DEG_LAT for m in stops.values()],
                "stop_lon": [LON0] * len(stops),
            }
        ),
        shapes=pd.DataFrame(),
        calendar=calendar,
        calendar_dates=pd.DataFrame(),
    )


_WD_CAL = pd.DataFrame(
    [("WD", 1, 1, 1, 1, 1, 0, 0, 20260101, 20261231)],
    columns=["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
)

BUS = _feed(
    {"A": 200.0, "B": 1000.0},  # A a 200 m do metro (candidata), B a 1 km (não)
    [
        ("t1", "R1", "WD", [("A", "08:05"), ("B", "08:10")]),  # A: 5 min exatos do metro WD -> overlap
        ("t2", "R1", "WD", [("A", "08:06")]),  # 6 min -> candidata sem overlap
        ("t3", "R1", "SAB", [("A", "12:03")]),  # sábado (alias) vs metro de sábado -> overlap
        ("t4", "R1", "WD", [("A", "12:01")]),  # 1 min do metro de sábado, mas dias diferentes -> não
        ("t5", "R1", "XPTO", [("A", "09:02")]),  # serviço desconhecido -> conta como partilhado (herdado)
        ("t6", "R2", "WD", [("B", "08:00")]),  # linha 2 só passa longe do metro
    ],
    _WD_CAL,
)
METRO = _feed(
    {"M": 0.0},
    [
        ("m1", "RM", "WD", [("M", "08:00")]),
        ("m2", "RM", "WD", [("M", "09:00")]),
        ("m3", "RM", "SAT", [("M", "12:00")]),  # sem calendar.txt: resolvido por alias
    ],
    pd.DataFrame(),
)


@pytest.fixture(autouse=True)
def _synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ov, "load_gtfs_cached", lambda dataset: {"bus": BUS, "metro": METRO}[dataset])


def test_metrics_per_line() -> None:
    df = pd.DataFrame({"line": ["1", "2", "nao_existe", 1.0], "temporal_overlaps_count": [-1, -1, -1, -1]})
    out = ov.compute_temporal_overlaps_for_db(df, smtuc_dataset="bus", metrobus_dataset="metro", **PARAMS)
    one = out.iloc[0]
    assert one["temporal_spatial_candidates_count"] == 5  # t1..t5 em A; B nunca conta
    assert one["temporal_overlaps_count"] == 3  # t1, t3, t5
    assert one["temporal_overlaps_pct"] == 60.0
    assert one["temporal_overlap_stop_ids"] == "A"
    two = out.iloc[1]
    assert (two["temporal_spatial_candidates_count"], two["temporal_overlaps_count"], two["temporal_overlaps_pct"]) == (0, 0, 0.0)
    assert out.iloc[2]["temporal_overlaps_count"] == -1  # linha inexistente: fica como estava
    assert out.iloc[3]["temporal_overlaps_count"] == 3  # 1.0 normaliza para "1"


def test_events_follow_metrics_rows_and_stop_times_order() -> None:
    ev = ov.temporal_overlap_events_for_metrics(
        pd.DataFrame({"line": ["1", "nao_existe", "2", "1"]}), smtuc_dataset="bus", metrobus_dataset="metro", **PARAMS
    )
    assert list(ev.columns) == ov._TEMPORAL_EVENT_COLUMNS
    assert ev["time_hhmm"].tolist() == ["08:05", "12:03", "09:02"] * 2  # linha repetida repete eventos
    assert set(ev["smtuc_stop_id"]) == {"A"} and set(ev["smtuc_stop_name"]) == {"Paragem A"}
    assert ev["hour"].tolist() == [8, 12, 9] * 2
    assert set(ev["nearby_metro_stops_count"]) == {1}


def test_thresholds_are_inclusive_and_parameters_are_used() -> None:
    narrower = dict(PARAMS, temporal_overlap_max_min=4.0)  # 08:05 vs 08:00 deixa de contar
    out = ov.compute_temporal_overlaps_for_db(pd.DataFrame({"line": ["1"]}), smtuc_dataset="bus", metrobus_dataset="metro", **narrower)
    assert out.iloc[0]["temporal_overlaps_count"] == 2
    tiny_walk = dict(PARAMS, spatial_overlap_walk_min=2.0)  # 160 m: A (200 m) deixa de ser candidata
    out = ov.compute_temporal_overlaps_for_db(pd.DataFrame({"line": ["1"]}), smtuc_dataset="bus", metrobus_dataset="metro", **tiny_walk)
    assert out.iloc[0]["temporal_spatial_candidates_count"] == 0
    ev = ov.temporal_overlap_events_for_metrics(pd.DataFrame({"line": ["2"]}), smtuc_dataset="bus", metrobus_dataset="metro", **PARAMS)
    assert ev.empty and list(ev.columns) == ov._TEMPORAL_EVENT_COLUMNS
