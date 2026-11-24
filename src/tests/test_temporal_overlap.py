"""Overlap temporal num GTFS sintético (passos 6.1 e 3.4/T3): fixa a regra de
`overlap._temporal_overlap_passages`, partilhada pelas métricas por linha e pela lista de eventos.

Regra: só conta o serviço do DIA DE REFERÊNCIA dos dois lados (`active_service_ids`, feriados
como domingo). Uma passagem SMTUC desse dia é candidata se houver uma paragem do metro a <= walk x
minutos, e tem overlap se nessa paragem passar um metro do mesmo dia a <= N minutos. Um serviço
que não está no calendário não corre - deixou de contar como "partilhado".
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import overlap.overlap as ov
from gtfs_processing.gtfs import GTFSData
from gtfs_processing.gtfs_probe import ServiceCalendarError

M_PER_DEG_LAT = 6371000.0 * 3.141592653589793 / 180.0
LAT0, LON0 = 40.0, -8.0
PARAMS = dict(walk_speed_m_min=80.0, temporal_overlap_max_min=5.0, spatial_overlap_walk_min=3.0)  # 240 m, 300 s
MONDAY = date(2026, 5, 11)
SATURDAY = date(2026, 5, 16)
HOLIDAY_FRIDAY = date(2026, 5, 1)  # Dia do Trabalhador: avaliado como domingo


def _s(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


def _calendar(rows: list[tuple[str, tuple[int, ...]]]) -> pd.DataFrame:
    cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return pd.DataFrame(
        [{"service_id": sid, **dict(zip(cols, mask)), "start_date": 20260101, "end_date": 20261231} for sid, mask in rows]
    )


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


WEEKDAYS, SATURDAYS = (1, 1, 1, 1, 1, 0, 0), (0, 0, 0, 0, 0, 1, 0)

BUS = _feed(
    {"A": 200.0, "B": 1000.0},  # A a 200 m do metro (candidata), B a 1 km (nunca)
    [
        ("t1", "R1", "WD", [("A", "08:05"), ("B", "08:10")]),  # 5 min exatos do metro WD -> overlap
        ("t2", "R1", "WD", [("A", "08:06")]),  # 6 min -> candidata sem overlap
        ("t3", "R1", "SAB", [("A", "12:03")]),  # sábado, metro de sábado às 12:00 -> overlap ao sábado
        ("t4", "R1", "WD", [("A", "12:01")]),  # o metro das 12:00 só corre ao sábado -> não
        ("t5", "R1", "XPTO", [("A", "09:02")]),  # fora do calendário: não corre (antes contava)
        ("t6", "R2", "WD", [("B", "08:00")]),  # linha 2 só passa longe do metro
    ],
    _calendar([("WD", WEEKDAYS), ("SAB", SATURDAYS)]),
)
METRO = _feed(
    {"M": 0.0},
    [
        ("m1", "RM", "WD", [("M", "08:00")]),
        ("m2", "RM", "WD", [("M", "09:00")]),
        ("m3", "RM", "SAT", [("M", "12:00")]),
    ],
    _calendar([("WD", WEEKDAYS), ("SAT", SATURDAYS)]),
)


@pytest.fixture(autouse=True)
def _synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ov, "load_gtfs_cached", lambda dataset: {"bus": BUS, "metro": METRO}[dataset])


def _metrics(lines: list, day: date, **params) -> pd.DataFrame:
    df = pd.DataFrame({"line": lines, "temporal_overlaps_count": [-1] * len(lines)})
    return ov.compute_temporal_overlaps_for_db(df, smtuc_dataset="bus", metrobus_dataset="metro", reference_day=day, **(params or PARAMS))


def _row(df: pd.DataFrame, i: int) -> tuple:
    r = df.iloc[i]
    return (r["temporal_spatial_candidates_count"], r["temporal_overlaps_count"], r["temporal_overlaps_pct"], r["temporal_overlap_stop_ids"])


def test_weekday_counts_only_that_days_service() -> None:
    out = _metrics(["1", "2", "nao_existe", 1.0], MONDAY)
    assert _row(out, 0) == (3, 1, 33.33, "A")  # t1, t2, t4 em A; só t1 coincide; t3 (sáb) e t5 não correm
    assert _row(out, 1) == (0, 0, 0.0, "")
    assert out.iloc[2]["temporal_overlaps_count"] == -1  # linha inexistente: fica como estava
    assert out.iloc[3]["temporal_overlaps_count"] == 1  # 1.0 normaliza para "1"


def test_saturday_and_holiday() -> None:
    assert _row(_metrics(["1"], SATURDAY), 0) == (1, 1, 100.0, "A")  # t3 vs metro de sábado
    assert _row(_metrics(["1"], HOLIDAY_FRIDAY), 0) == (0, 0, 0.0, "")  # feriado = domingo: sem serviço


def test_day_outside_the_feed_period_raises() -> None:
    with pytest.raises(ServiceCalendarError):
        _metrics(["1"], date(2027, 1, 4))


def test_events_follow_metrics_rows_and_stop_times_order() -> None:
    ev = ov.temporal_overlap_events_for_metrics(
        pd.DataFrame({"line": ["1", "nao_existe", "2", "1"]}), smtuc_dataset="bus", metrobus_dataset="metro", reference_day=MONDAY, **PARAMS
    )
    assert list(ev.columns) == ov._TEMPORAL_EVENT_COLUMNS
    assert ev["time_hhmm"].tolist() == ["08:05"] * 2  # linha repetida repete os eventos
    assert ev["smtuc_stop_name"].tolist() == ["Paragem A"] * 2
    assert ev["hour"].tolist() == [8, 8] and ev["nearby_metro_stops_count"].tolist() == [1, 1]


def test_thresholds_are_inclusive_and_parameters_are_used() -> None:
    assert _row(_metrics(["1"], MONDAY, **dict(PARAMS, temporal_overlap_max_min=4.0)), 0)[1] == 0  # 08:05 vs 08:00 deixa de contar
    assert _row(_metrics(["1"], MONDAY, **dict(PARAMS, spatial_overlap_walk_min=2.0)), 0)[0] == 0  # 160 m: A deixa de ser candidata
    ev = ov.temporal_overlap_events_for_metrics(
        pd.DataFrame({"line": ["2"]}), smtuc_dataset="bus", metrobus_dataset="metro", reference_day=MONDAY, **PARAMS
    )
    assert ev.empty and list(ev.columns) == ov._TEMPORAL_EVENT_COLUMNS
