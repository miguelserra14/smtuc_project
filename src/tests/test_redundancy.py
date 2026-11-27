"""Redundância autocarro x metro viagem a viagem (N2.1, overlap/redundancy.py).

Feeds sintéticos em memória: não lê dados nem escreve em outputs/."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from gtfs_processing.gtfs import GTFSData
from overlap.overlap_db import _route_direction_summaries
from overlap.redundancy import (
    Redundancy,
    Waste,
    WasteFactors,
    bus_stop_overlap,
    metro_extension_increase,
    new_station_corridors,
    redundancy_by_corridor,
    redundancy_by_line,
    redundancy_by_line_corridor,
    station_name,
    trip_segments,
    typical_week,
    waste_factors,
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


# --------------------------------------------------------------------------- desperdício (N2.2)


def _feed_with_period(start: int, end: int) -> GTFSData:
    feed = _bus_feed()
    calendar = feed.calendar.assign(start_date=start, end_date=end)
    return GTFSData(routes=feed.routes, trips=feed.trips, stop_times=feed.stop_times, stops=feed.stops,
                    shapes=feed.shapes, calendar=calendar, calendar_dates=feed.calendar_dates)


def test_typical_week_takes_the_nearest_weekend_days() -> None:
    week = typical_week(_bus_feed(), MONDAY)
    assert week == [("dia útil", MONDAY, 5), ("sábado", date(2026, 11, 7), 1), ("domingo", date(2026, 11, 8), 1)]


def test_typical_week_stays_inside_the_feed_period() -> None:
    # Como o Ep225 (até 12/11): com uma 6.ª de referência, o sábado seguinte (14/11) fica fora.
    friday = date(2026, 11, 13)
    feed = _feed_with_period(20260918, 20261113)
    assert [d for _, d, _ in typical_week(feed, friday)] == [friday, date(2026, 11, 7), date(2026, 11, 8)]


def test_typical_week_skips_holidays() -> None:
    # 01/11/2026 é domingo e feriado (Todos os Santos): conta o domingo seguinte.
    monday = date(2026, 11, 2)
    assert typical_week(_bus_feed(), monday)[2] == ("domingo", date(2026, 11, 8), 1)


def test_typical_week_needs_a_working_day() -> None:
    with pytest.raises(ValueError, match="dia útil"):
        typical_week(_bus_feed(), SATURDAY)
    with pytest.raises(ValueError, match="dia útil"):
        typical_week(_bus_feed(), date(2026, 12, 8))  # 3.ª, feriado


def test_co2_per_km_mixes_the_fleet() -> None:
    f = WasteFactors(fleet_total=4, fleet_electric=1, diesel_l_per_km=0.5, electric_kwh_per_km=1.0,
                     diesel_kg_co2_per_l=2.0, grid_kg_co2_per_kwh=0.1, weeks_per_year=52)
    assert f.electric_share == 0.25
    assert f.kg_co2_per_km == pytest.approx(0.75 * 0.5 * 2.0 + 0.25 * 1.0 * 0.1)
    assert 0 < waste_factors().kg_co2_per_km < 2  # fatores do config


def test_week_and_year_are_weighted() -> None:
    f = WasteFactors(fleet_total=1, fleet_electric=0, diesel_l_per_km=1.0, electric_kwh_per_km=0.0,
                     diesel_kg_co2_per_l=1.0, grid_kg_co2_per_kwh=0.0, weeks_per_year=52)
    by_line = pd.DataFrame({"line": ["5"], "viagens": [10], "km": [100.0], "km_metro": [10.0], "pct_km_metro": [10.0],
                            "horas": [5.0], "horas_metro": [1.0], "viagens_com_troco_metro": [10]})
    ref = Redundancy("x", MONDAY, by_line, pd.DataFrame())
    week = pd.DataFrame({"tipo": ["dia útil", "sábado", "domingo"], "dia": ["", "", ""], "peso": [5, 1, 1],
                         "viagens": [10, 5, 2], "km": [100.0, 50.0, 20.0], "km_metro": [10.0, 4.0, 2.0],
                         "horas_metro": [1.0, 0.5, 0.25]})
    line_week = pd.DataFrame({"line": ["5"], "km_metro": [56.0], "horas_metro": [5.75]})
    s = Waste("x", ref, week, line_week, f).summary()
    assert s["semana_km_metro"] == pytest.approx(5 * 10 + 4 + 2)
    assert s["ano_km_metro"] == pytest.approx(56 * 52)
    assert s["ano_t_co2"] == pytest.approx(56 * 52 / 1000)
    assert s["dia_t_co2"] == pytest.approx(10 / 1000)


# --------------------------------------------------------------------------- metro novo (N3.4)


def test_line_corridor_breakdown_adds_up_to_the_corridors() -> None:
    seg = trip_segments(_bus_feed(), _metro_feed(), MONDAY, CATCHMENT_M)
    by_lc = redundancy_by_line_corridor(seg)
    assert by_lc[["line", "station_a", "station_b", "passagens"]].values.tolist() == [["5", "Alfa", "Beta", 3]]
    corridor = redundancy_by_corridor(seg)
    assert by_lc["km_metro"].sum() == pytest.approx(corridor["km_metro"].sum())
    assert by_lc["horas_metro"].sum() == pytest.approx(corridor["horas_metro"].sum())
    assert redundancy_by_line_corridor(seg.iloc[0:0]).empty


_F = WasteFactors(fleet_total=1, fleet_electric=0, diesel_l_per_km=1.0, electric_kwh_per_km=0.0,
                  diesel_kg_co2_per_l=1.0, grid_kg_co2_per_kwh=0.0, weeks_per_year=52)


def _extension_waste(lines: dict[str, tuple[float, float]], line_corridors: list[tuple]) -> Waste:
    """lines = {linha: (km_metro, horas_metro)} no dia; line_corridors = (linha, a, b, km, horas, passagens).
    A semana-tipo é o dia x 7 (pesos já aplicados)."""
    by_line = pd.DataFrame({"line": list(lines), "viagens": 10, "km": 100.0,
                            "km_metro": [v[0] for v in lines.values()], "pct_km_metro": 0.0, "horas": 5.0,
                            "horas_metro": [v[1] for v in lines.values()], "viagens_com_troco_metro": 1})
    lc = pd.DataFrame(line_corridors, columns=["line", "station_a", "station_b", "km_metro", "horas_metro", "passagens"])
    corridors = lc.groupby(["station_a", "station_b"], as_index=False).agg(
        km_metro=("km_metro", "sum"), horas_metro=("horas_metro", "sum"), passagens=("passagens", "sum"),
        linhas=("line", lambda s: ";".join(sorted(s))))
    week = pd.DataFrame({"tipo": ["dia útil"], "dia": ["2026-11-09"], "peso": [5], "viagens": [10], "km": [100.0],
                         "km_metro": [by_line["km_metro"].sum()], "horas_metro": [by_line["horas_metro"].sum()]})
    line_week = by_line[["line", "km_metro", "horas_metro"]].assign(km_metro=lambda d: d["km_metro"] * 7,
                                                                   horas_metro=lambda d: d["horas_metro"] * 7)
    lc_week = lc.assign(km_metro=lc["km_metro"] * 7, horas_metro=lc["horas_metro"] * 7, passagens=lc["passagens"] * 7)
    return Waste("x", Redundancy("x", MONDAY, by_line, corridors, lc), week, line_week, _F, lc_week)


def test_metro_extension_increase_line_by_line() -> None:
    # C: a 6 já corre 10 km a par da República; em D passa também por Celas e pelos HUC; a 7
    # aparece; a 5 não muda e não passa por estações novas -> fica de fora.
    before = _extension_waste({"6": (10.0, 1.0), "5": (4.0, 0.5)},
                              [("6", "República", "República", 10.0, 1.0, 5), ("5", "Alfa", "Beta", 4.0, 0.5, 2)])
    after = _extension_waste(
        {"6": (25.0, 2.5), "5": (4.0, 0.5), "7": (30.0, 2.0)},
        [("6", "República", "República", 10.0, 1.0, 5), ("6", "Celas", "Hospitais", 15.0, 1.5, 6),
         ("5", "Alfa", "Beta", 4.0, 0.5, 2), ("7", "Celas", "Celas", 30.0, 2.0, 9)],
    )
    stations = ("Celas", "Hospitais")
    table = metro_extension_increase(before, after, stations).set_index("line")
    assert list(table.index) == ["7", "6"]  # maior aumento primeiro; a 5 sai
    six = table.loc["6"]
    assert (six["km_antes"], six["km_depois"], six["delta_km"], six["delta_horas"]) == (10.0, 25.0, 15.0, 1.5)
    assert six["ano_delta_horas"] == pytest.approx(1.5 * 7 * 52)
    assert six["ano_delta_t_co2"] == pytest.approx(15.0 * 7 * 52 / 1000.0)  # 1 kg CO2/km nos fatores do teste
    assert (six["horas_novas"], six["ano_horas_novas"]) == (1.5, pytest.approx(1.5 * 7 * 52))
    assert six["estacoes_novas"] == "Celas, Hospitais" and six["corredores_novos"] == "Celas – Hospitais"
    seven = table.loc["7"]
    assert (seven["km_antes"], seven["delta_km"], seven["corredores_novos"]) == (0.0, 30.0, "junto a Celas")
    # a ordem das estações vem de `stations`, não do alfabeto
    assert metro_extension_increase(before, after, ("Hospitais", "Celas")).set_index("line").loc["6", "estacoes_novas"] == "Hospitais, Celas"
    # uma linha só de fim de semana (fora do dia útil) entra pela semana-tipo: conta no ano
    weekend = pd.DataFrame({"line": ["W"], "km_metro": [2.0], "horas_metro": [0.5]})
    after_we = Waste("x", after.reference, after.week, pd.concat([after.line_week, weekend], ignore_index=True), _F,
                     after.line_corridor_week)
    w = metro_extension_increase(before, after_we, stations).set_index("line").loc["W"]
    assert (w["delta_km"], w["ano_delta_horas"]) == (0.0, pytest.approx(0.5 * 52))
    corridors = new_station_corridors(after, stations)
    assert sorted(zip(corridors["station_a"], corridors["station_b"])) == [("Celas", "Celas"), ("Celas", "Hospitais")]
