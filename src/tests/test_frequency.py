"""Testes da frequência média por linha (`overlap_db._line_avg_frequency_min`) e da chave do cache
`line_metrics_db.csv` (passo 0.1 do roadmap).

Antes: todos os service_id (úteis + sábados + domingos) e os dois sentidos eram misturados numa
só lista de 1ªs partidas -> valores 2-8x mais baixos do que o real (linha 7: 6.6 em vez de 20).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gtfs_processing.gtfs import GTFSData
from gtfs_processing.gtfs_probe import ServiceCalendarError
from overlap import overlap_db as odb

MONDAY = date(2026, 5, 11)


def _s(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 3600 + m * 60


def _hhmm(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


class _Feed:
    """Construtor mínimo de um GTFS sintético: cada viagem é uma lista de (stop_id, HH:MM)."""

    def __init__(self) -> None:
        self.trips: list[dict] = []
        self.stop_times: list[dict] = []

    def trip(self, route: str, direction: int, stops: list[tuple[str, str]], service: str = "Dias Uteis") -> None:
        trip_id = f"t{len(self.trips)}"
        self.trips.append({"route_id": route, "service_id": service, "trip_id": trip_id, "direction_id": direction})
        for seq, (sid, hm) in enumerate(stops, start=1):
            self.stop_times.append(
                {"trip_id": trip_id, "stop_id": sid, "stop_sequence": seq, "arrival_seconds": _s(hm), "departure_seconds": _s(hm)}
            )

    def every(self, route: str, direction: int, stops: list[str], start: str, end: str, step_min: int,
              offsets_min: list[int] | None = None, service: str = "Dias Uteis") -> None:
        offsets_min = offsets_min or [5 * i for i in range(len(stops))]
        t = _s(start)
        while t <= _s(end):
            self.trip(route, direction, [(sid, _hhmm(t + off * 60)) for sid, off in zip(stops, offsets_min)], service)
            t += step_min * 60

    def gtfs(self) -> GTFSData:
        calendar = pd.DataFrame(
            [("Dias Uteis", 1, 1, 1, 1, 1, 0, 0, 20260101, 20261231), ("Sabados", 0, 0, 0, 0, 0, 1, 0, 20260101, 20261231)],
            columns=["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
        )
        return GTFSData(
            routes=pd.DataFrame(), trips=pd.DataFrame(self.trips), stop_times=pd.DataFrame(self.stop_times),
            stops=pd.DataFrame(), shapes=pd.DataFrame(), calendar=calendar, calendar_dates=pd.DataFrame(),
        )


def test_line_value_is_mean_of_direction_medians() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:40", 20)
    f.every("R", 1, ["B", "A"], "07:00", "19:30", 30)
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 25.0


def test_other_service_days_are_excluded() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:00", 30)
    # Sábados desfasados 15 min - com a fórmula antiga baixavam o resultado para ~15.
    f.every("R", 0, ["A", "B"], "07:15", "19:15", 30, service="Sabados")
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 30.0
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], date(2026, 5, 16)) == 30.0  # sábado


def test_directions_are_not_interleaved() -> None:
    # Sentidos desfasados 10 min: misturados dariam intervalos de 10/30 min (média 20).
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:00", 40)
    f.every("R", 1, ["B", "A"], "07:10", "19:10", 40)
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 40.0


def test_passages_outside_window_are_ignored() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:30", 30)
    for hm in ("05:00", "21:00", "23:30"):  # serviço noturno esparso
        f.trip("R", 0, [("A", hm), ("B", hm)])
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 30.0


def test_window_end_is_exclusive() -> None:
    f = _Feed()
    f.every("R", 0, ["A"], "07:00", "20:00", 60, offsets_min=[0])  # 07:00 .. 20:00
    gtfs = f.gtfs()
    assert odb._line_avg_frequency_min(gtfs, ["R"], MONDAY) == 60.0
    # Janela 19h-20h: só a passagem das 19:00 conta (20:00 fica de fora) -> < 2 passagens.
    assert odb._line_avg_frequency_min(gtfs, ["R"], MONDAY, window_start_h=19, window_end_h=20) is None


def test_headway_measured_at_common_stop_not_first_departure() -> None:
    # Viagens completas A->B->C de 30 em 30 e viagens curtas que só começam em B a meio de cada
    # intervalo: em B passa um autocarro de 15 em 15 min. As 1ªs partidas (A e B misturadas)
    # dariam outra coisa; a paragem de referência é a servida por mais viagens (B ou C).
    f = _Feed()
    f.every("R", 0, ["A", "B", "C"], "07:00", "18:30", 30, offsets_min=[0, 10, 20])
    f.every("R", 0, ["B", "C"], "07:25", "18:55", 30, offsets_min=[0, 10])
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 15.0


def test_median_resists_one_long_gap() -> None:
    f = _Feed()
    times = ["07:00", "07:20", "07:40", "08:00", "12:00", "12:20", "12:40"]  # buraco de 4h
    for hm in times:
        f.trip("R", 0, [("A", hm)])
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 20.0


def test_direction_without_enough_passages_is_skipped() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:00", 30)
    f.trip("R", 1, [("B", "08:00"), ("A", "08:10")])  # 1 só passagem neste sentido
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 30.0


def test_no_service_on_day_gives_none() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:00", 30)
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], date(2026, 5, 17)) is None  # domingo
    assert odb._line_avg_frequency_min(f.gtfs(), [], MONDAY) is None


def test_feed_without_direction_id() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:00", 30)
    gtfs = f.gtfs()
    gtfs.trips = gtfs.trips.drop(columns="direction_id")
    assert odb._line_avg_frequency_min(gtfs, ["R"], MONDAY) == 30.0


def test_only_requested_routes_count() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:00", 30)
    f.every("OTHER", 0, ["A", "B"], "07:15", "19:15", 30)
    assert odb._line_avg_frequency_min(f.gtfs(), ["R"], MONDAY) == 30.0
    assert odb._line_avg_frequency_min(f.gtfs(), ["R", "OTHER"], MONDAY) == 15.0  # variantes da mesma linha


def test_ref_day_trips() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "08:00", 30)  # 3 viagens
    f.every("R", 1, ["B", "A"], "07:00", "07:30", 30)  # 2 viagens
    f.every("R", 0, ["A", "B"], "07:00", "09:00", 30, service="Sabados")
    assert odb._line_trips_on_day(f.gtfs(), ["R"], MONDAY) == 5


def test_out_of_range_day_raises() -> None:
    f = _Feed()
    f.every("R", 0, ["A", "B"], "07:00", "19:00", 30)
    with pytest.raises(ServiceCalendarError):
        odb._line_avg_frequency_min(f.gtfs(), ["R"], date(2027, 1, 4))


# --------------------------------------------------------------------------------------------
# Chave do cache line_metrics_db.csv
# --------------------------------------------------------------------------------------------

@pytest.fixture
def fake_compute(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    """Substitui o cálculo pesado por uma tabela de 1 linha e regista cada recálculo."""
    calls: list[date] = []

    def _compute(**kwargs):
        calls.append(kwargs["reference_day"])
        return pd.DataFrame([{"line": "7", "avg_freq_min": 20.0, "ref_day_trips": 101}])

    import overlap.overlap as ov

    monkeypatch.setattr(odb, "_compute_line_metrics", _compute)
    monkeypatch.setattr(ov, "compute_temporal_overlaps_for_db", lambda df, **kwargs: df)
    monkeypatch.setattr(odb, "_dataset_signature", lambda dataset: f"sig-{dataset}")
    return calls


def test_cache_hit_and_reference_day_in_key(tmp_path: Path, fake_compute: list[date]) -> None:
    db = str(tmp_path / "m.csv")
    first = odb.build_line_metrics_db(db_path=db, reference_day=MONDAY)
    assert fake_compute == [MONDAY]
    assert "__meta_reference_day" not in first.columns  # metadados nunca saem para os chamadores

    odb.build_line_metrics_db(db_path=db, reference_day=MONDAY)
    assert fake_compute == [MONDAY]  # cache usado

    other = date(2026, 5, 12)
    odb.build_line_metrics_db(db_path=db, reference_day=other)
    assert fake_compute == [MONDAY, other]  # outro dia -> recalcula

    raw = pd.read_csv(db)
    assert raw.loc[0, "__meta_reference_day"] == "2026-05-12"
    assert str(raw.loc[0, "__meta_schema_version"]) == str(odb.LINE_METRICS_SCHEMA_VERSION)


def test_schema_version_bump_invalidates_cache(tmp_path: Path, fake_compute: list[date], monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "m.csv")
    odb.build_line_metrics_db(db_path=db, reference_day=MONDAY)
    monkeypatch.setattr(odb, "LINE_METRICS_SCHEMA_VERSION", odb.LINE_METRICS_SCHEMA_VERSION + 1)
    odb.build_line_metrics_db(db_path=db, reference_day=MONDAY)
    assert len(fake_compute) == 2


def test_frequency_window_change_invalidates_cache(tmp_path: Path, fake_compute: list[date], monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "m.csv")
    odb.build_line_metrics_db(db_path=db, reference_day=MONDAY)
    monkeypatch.setattr(odb, "FREQUENCY_WINDOW_END_H", 21)
    odb.build_line_metrics_db(db_path=db, reference_day=MONDAY)
    assert len(fake_compute) == 2


def test_old_format_cache_is_recomputed(tmp_path: Path, fake_compute: list[date]) -> None:
    # CSV no formato antigo (sem __meta_schema_version / __meta_reference_day), ex. o que está hoje
    # em outputs/overlap/ - tem de ser recalculado, não servido com a frequência antiga.
    db = tmp_path / "m.csv"
    odb.build_line_metrics_db(db_path=str(db), reference_day=MONDAY)
    raw = pd.read_csv(db).drop(columns=["__meta_schema_version", "__meta_reference_day"])
    raw["avg_freq_min"] = 6.6
    raw.to_csv(db, index=False)
    out = odb.build_line_metrics_db(db_path=str(db), reference_day=MONDAY)
    assert len(fake_compute) == 2
    assert out.loc[0, "avg_freq_min"] == 20.0


# --------------------------------------------------------------------------------------------
# Integração: valores reais conferidos à mão contra os horários (dia útil 2026-05-11)
# --------------------------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("line, expected", [("7", 20.0), ("54", 40.0), ("10", 75.0)])
def test_real_line_frequencies(line: str, expected: float) -> None:
    if not (Path(__file__).resolve().parents[2] / "data" / "smtuc" / "trips.txt").exists():
        pytest.skip("dados GTFS não disponíveis")
    gtfs = odb._load_gtfs_cached("smtuc")
    route_ids = odb._line_to_route_ids(gtfs)[line]
    assert odb._line_avg_frequency_min(gtfs, route_ids, MONDAY) == expected
