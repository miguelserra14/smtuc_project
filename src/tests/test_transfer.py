"""Testes do tempo mínimo de transbordo metro <-> autocarro (passo 0.2 do roadmap).

Antes, `next_bus >= chegada_metro`: uma partida à mesma hora da chegada contava como ligação
perfeita de 0 min, apesar de as paragens estarem a 20-250 m uma da outra.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from gtfs_processing.gtfs import GTFSData
from overlap.transit import compute_transfer_waits, transfer_minutes
from tests.reference_data import require_reference_data
from visualizations.integration import (
    _build_waits_table,
    _double_and_shift_schedule_bus_times,
    _shift_reverse_schedule_bus_arrivals,
    _shift_schedule_bus_times,
)

M_PER_DEG_LAT = 6371000.0 * math.pi / 180.0


def _stops(**offsets_m: float) -> GTFSData:
    """Paragens ao longo de um meridiano, a `offset` metros de lat=40."""
    stops = pd.DataFrame(
        {"stop_id": list(offsets_m), "stop_lat": [40.0 + m / M_PER_DEG_LAT for m in offsets_m.values()], "stop_lon": -8.4}
    )
    e = pd.DataFrame()
    return GTFSData(routes=e, trips=e, stop_times=e, stops=stops, shapes=e, calendar=e, calendar_dates=e)


def _schedule(bus: list[tuple[str, str, float | None]], metro: list[tuple[str, float | None]]) -> pd.DataFrame:
    """Tabela no contrato de build_line_stop_vs_metro_table: alvos (bus_time, linha, transbordo)
    e gatilhos (metro_time_from_origin, transbordo), alinhados por índice como no original."""
    n = max(len(bus), len(metro))
    rows = []
    for i in range(n):
        rows.append(
            {
                "bus_time": bus[i][0] if i < len(bus) else "",
                "bus_line_passage": bus[i][1] if i < len(bus) else "",
                "target_transfer_min": bus[i][2] if i < len(bus) else None,
                "metro_time_from_origin": metro[i][0] if i < len(metro) else "",
                "trigger_transfer_min": metro[i][1] if i < len(metro) else None,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------------
# transfer_minutes
# --------------------------------------------------------------------------------------------

def test_transfer_minutes_is_walk_plus_buffer() -> None:
    g = _stops(M=0, B=160)
    assert transfer_minutes(g, "M", g, "B", walk_speed_m_min=80.0, buffer_min=1.0) == pytest.approx(3.0, abs=0.01)
    assert transfer_minutes(g, "M", g, "B", walk_speed_m_min=80.0, buffer_min=0.0) == pytest.approx(2.0, abs=0.01)


def test_transfer_minutes_same_stop_is_just_buffer() -> None:
    g = _stops(M=0)
    assert transfer_minutes(g, "M", g, "M", buffer_min=1.0) == 1.0


def test_transfer_minutes_across_feeds_and_unknown_stop() -> None:
    metro, bus = _stops(M=0), _stops(B=240)
    assert transfer_minutes(metro, "M", bus, "B", walk_speed_m_min=80.0, buffer_min=1.0) == pytest.approx(4.0, abs=0.01)
    with pytest.raises(ValueError, match="sem coordenadas"):
        transfer_minutes(metro, "M", bus, "NOPE")


# --------------------------------------------------------------------------------------------
# compute_transfer_waits / _build_waits_table
# --------------------------------------------------------------------------------------------

def test_departure_at_arrival_time_is_no_longer_a_zero_minute_connection() -> None:
    df = _schedule(bus=[("08:00:00", "54", 2.0), ("08:40:00", "54", 2.0)], metro=[("08:00:00", 0.0)])
    (w,) = compute_transfer_waits(df)
    assert w["target_time"] == "08:40:00" and w["wait_min"] == 40.0  # antes: 0.0


def test_boundary_exactly_at_transfer_time_is_catchable() -> None:
    df = _schedule(bus=[("08:01:59", "54", 2.0), ("08:02:00", "54", 2.0)], metro=[("08:00:00", 0.0)])
    (w,) = compute_transfer_waits(df)
    assert w["target_time"] == "08:02:00" and w["wait_min"] == 2.0 and w["transfer_min"] == 2.0


def test_missing_transfer_columns_keep_old_behaviour() -> None:
    df = _schedule(bus=[("08:00:00", "54", None)], metro=[("08:00:00", None)]).drop(columns=["target_transfer_min", "trigger_transfer_min"])
    (w,) = compute_transfer_waits(df)
    assert w["wait_min"] == 0.0 and w["transfer_min"] == 0.0


def test_each_line_uses_its_own_stop_transfer() -> None:
    # Linha "A" pára longe (5 min a pé), "B" perto (1 min): às 10:00 só a B das 10:04 é apanhável,
    # apesar de a A das 10:03 partir primeiro.
    df = _schedule(bus=[("10:03:00", "A", 5.0), ("10:04:00", "B", 1.0)], metro=[("10:00:00", 0.0)])
    (w,) = compute_transfer_waits(df)
    assert (w["target_line"], w["wait_min"], w["transfer_min"]) == ("B", 4.0, 1.0)


def test_reverse_direction_transfer_is_on_the_trigger() -> None:
    # Sentido autocarro -> metro: o transbordo vem com a chegada do autocarro (gatilho).
    df = _schedule(bus=[("09:02:00", "Metro", 0.0), ("09:10:00", "Metro", 0.0)], metro=[("09:00:00", 3.0)])
    (w,) = compute_transfer_waits(df)
    assert w["target_time"] == "09:10:00" and w["wait_min"] == 10.0


def test_no_catchable_departure() -> None:
    df = _schedule(bus=[("23:00:00", "54", 2.0)], metro=[("22:59:00", 0.0), ("23:30:00", 0.0)])
    waits = _build_waits_table(df)
    assert waits["wait_class"].tolist() == ["sem_ligacao", "sem_ligacao"]
    assert waits["wait_min"].isna().all()
    assert waits["transfer_min"].isna().all()  # nunca 0.0 sem ligação


def test_waits_table_columns_and_classes() -> None:
    df = _schedule(
        bus=[("08:05:00", "54", 2.0), ("08:30:00", "54", 2.0), ("09:30:00", "54", 2.0)],
        metro=[("08:00:00", 0.0), ("08:18:00", 0.0), ("09:00:00", 0.0)],
    )
    waits = _build_waits_table(df)
    assert list(waits.columns) == ["metro_time", "next_bus_time", "next_bus_line", "wait_min", "transfer_min", "wait_class", "period"]
    assert waits["wait_min"].tolist() == [5.0, 12.0, 30.0]
    assert waits["wait_class"].tolist() == ["<=10", "10-15", ">15"]
    assert (waits["transfer_min"] == 2.0).all()


def test_empty_schedule() -> None:
    assert compute_transfer_waits(pd.DataFrame()) == []
    assert _build_waits_table(pd.DataFrame()).empty


def test_csv_roundtrip_with_blank_cells() -> None:
    # As tabelas vão para CSV e voltam: células vazias passam a NaN ("nan" em str).
    df = _schedule(bus=[("08:05:00", "54", 2.0), ("08:30:00", "54", 2.0)], metro=[("08:00:00", 0.0)])
    back = pd.read_csv(pd.io.common.StringIO(df.to_csv(index=False)))
    assert compute_transfer_waits(back) == compute_transfer_waits(df)


# --------------------------------------------------------------------------------------------
# Variantes otimizado/melhorado: o transbordo acompanha cada passagem deslocada/duplicada
# --------------------------------------------------------------------------------------------

def test_shift_keeps_transfer_aligned_with_its_passage() -> None:
    df = _schedule(bus=[("08:10:00", "54", 2.0), ("08:12:00", "38", 5.0)], metro=[("08:05:00", 0.0)])
    shifted = _shift_schedule_bus_times(df, "54", -4.0)  # 54 passa para as 08:06
    assert shifted.loc[0, ["bus_time", "target_transfer_min"]].tolist() == ["08:06:00", 2.0]
    assert shifted.loc[1, ["bus_time", "target_transfer_min"]].tolist() == ["08:12:00", 5.0]  # 38 intocada
    (w,) = compute_transfer_waits(shifted)
    # 08:05 + 2 min = 08:07 > 08:06 -> a 54 deslocada já não dá; a 38 (08:12) exige 08:10 -> dá.
    assert (w["target_line"], w["target_time"]) == ("38", "08:12:00")


def test_double_and_shift_copies_transfer_to_the_new_bus() -> None:
    df = _schedule(bus=[("08:00:00", "54", 2.0)], metro=[("08:15:00", 0.0)])
    doubled = _double_and_shift_schedule_bus_times(df, "54", 0.0)
    rows = doubled[doubled["bus_line_passage"] == "54"].sort_values("bus_time")
    assert rows["bus_time"].tolist() == ["08:00:00", "08:20:00"]
    assert rows["target_transfer_min"].tolist() == [2.0, 2.0]
    (w,) = compute_transfer_waits(doubled)
    assert w["target_time"] == "08:20:00" and w["wait_min"] == 5.0


def test_reverse_shift_keeps_trigger_transfer() -> None:
    df = _schedule(bus=[("09:10:00", "Metro", 0.0)], metro=[("09:00:00", 3.0)])
    shifted = _shift_reverse_schedule_bus_arrivals(df, 5.0)
    assert shifted.loc[0, ["metro_time_from_origin", "trigger_transfer_min"]].tolist() == ["09:05:00", 3.0]
    (w,) = compute_transfer_waits(shifted)
    assert w["wait_min"] == 5.0


# --------------------------------------------------------------------------------------------
# Integração: nós reais Portela / Portagem
# --------------------------------------------------------------------------------------------

def _require_data() -> None:
    # Distâncias/transbordos fixos (2.39, 1.28) só valem para estes feeds (coords do metro sintético).
    require_reference_data("smtuc", "metrobus")


@pytest.mark.integration
@pytest.mark.parametrize("site_name, expected_transfer", [("Portela", 2.39), ("Portagem", 1.28)])
def test_real_sites_transfer_and_no_impossible_connections(tmp_path: Path, site_name: str, expected_transfer: float) -> None:
    _require_data()
    from config import INTEGRATION_SITES
    from overlap.transit import build_line_stop_vs_metro_table, build_metro_bus_connection_metrics, build_reverse_stop_vs_metro_table

    s = next(x for x in INTEGRATION_SITES if x["name"] == site_name)
    lines = s["line_number"] if isinstance(s["line_number"], str) else list(s["line_number"])
    fwd = build_line_stop_vs_metro_table(
        s["metro_stop_ref"], s["bus_stop_ref"], lines, metro_origin_ref=s["metro_origin_ref"],
        bus_origin_ref=s["bus_origin_ref"], output_dir=tmp_path,
    )
    rev = build_reverse_stop_vs_metro_table(
        s["bus_stop_ref"], s["metro_stop_ref"], lines, metro_direction_id=s["reverse_metro_direction_id"],
        bus_origin_ref=s["bus_origin_ref"], metro_route_id=s["reverse_metro_route_id"], output_dir=tmp_path,
    )
    assert fwd["target_transfer_min"].dropna().unique().tolist() == [expected_transfer]
    assert rev["trigger_transfer_min"].dropna().unique().tolist() == [expected_transfer]

    for df in (fwd, rev):
        waits = _build_waits_table(df)
        valid = waits.dropna(subset=["wait_min"])
        assert (valid["wait_min"] >= valid["transfer_min"] - 1e-9).all()  # nunca abaixo do tempo a pé
        assert (valid["wait_min"] > 0).all()

    # Métricas e gráfico usam a mesma regra -> a mesma mediana.
    metrics = build_metro_bus_connection_metrics(
        s["metro_stop_ref"], s["bus_stop_ref"], lines, metro_origin_ref=s["metro_origin_ref"],
        bus_origin_ref=s["bus_origin_ref"], output_dir=tmp_path,
    )
    median_metric = float(metrics.loc[(metrics.scope == "overall") & (metrics.metric == "wait_median_min"), "value"].iloc[0])
    assert median_metric == pytest.approx(float(_build_waits_table(fwd)["wait_min"].median()))
    walk = float(metrics.loc[metrics.metric == "transfer_walk_median_min", "value"].iloc[0])
    assert walk == pytest.approx(expected_transfer)
