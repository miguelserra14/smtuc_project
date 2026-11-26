"""Vistas de dataset (N2.3): "<feed>-sem-<linhas>" = o feed sem essas linhas, filtrado em memória.

Unitários com um feed sintético; os que tocam na pasta real saltam sem os dados."""

from __future__ import annotations

import pandas as pd
import pytest

from gtfs_processing.gtfs import (
    GTFSData,
    base_dataset,
    dataset_dir,
    dataset_view,
    exclude_lines,
    parse_dataset_view,
)
from gtfs_processing.scenarios import excluded_integration_lines, get_scenario


def _feed() -> GTFSData:
    routes = pd.DataFrame([("r1", "54"), ("r2", "38"), ("r3", "5")], columns=["route_id", "route_short_name"])
    trips = pd.DataFrame([("r1", "U", "a"), ("r1", "U", "b"), ("r2", "U", "c"), ("r3", "U", "d")],
                         columns=["route_id", "service_id", "trip_id"])
    stop_times = pd.DataFrame({"trip_id": ["a", "a", "b", "c", "d"], "stop_id": ["1", "2", "1", "3", "4"]})
    stops = pd.DataFrame({"stop_id": ["1", "2", "3", "4"]})
    empty = pd.DataFrame()
    return GTFSData(routes=routes, trips=trips, stop_times=stop_times, stops=stops, shapes=empty,
                    calendar=empty, calendar_dates=empty)


def test_view_names_round_trip() -> None:
    assert dataset_view("smtuc", ["54"]) == "smtuc-sem-54"
    assert dataset_view("smtuc", ["54", "38", "54", " "]) == "smtuc-sem-38+54"  # ordenado, sem repetidos
    assert dataset_view("smtuc", []) == "smtuc"
    assert parse_dataset_view("smtuc-sem-38+54") == ("smtuc", ("38", "54"))
    assert parse_dataset_view("smtuc_atual") == ("smtuc_atual", ())
    assert base_dataset("smtuc-sem-54") == "smtuc"
    with pytest.raises(ValueError):
        dataset_view("smtuc", ["5+4"])


def test_a_view_reads_the_base_folder() -> None:
    assert dataset_dir("smtuc-sem-54") == dataset_dir("smtuc")
    with pytest.raises(KeyError):
        dataset_dir("nao_existe-sem-54")


def test_exclude_lines_drops_only_those_trips() -> None:
    feed = _feed()
    out = exclude_lines(feed, ("54",))
    assert list(out.trips["trip_id"]) == ["c", "d"]
    assert list(out.stop_times["trip_id"]) == ["c", "d"]
    assert list(out.routes["route_short_name"]) == ["38", "5"]
    assert out.stops is feed.stops  # paragens ficam (uma paragem sem viagens deixa de ter oferta)
    assert len(feed.trips) == 4  # o feed base não é alterado


def test_excluding_a_missing_line_raises() -> None:
    with pytest.raises(ValueError, match="não existem"):
        exclude_lines(_feed(), ("54", "99"))


def test_scenario_without_line_54() -> None:
    sc = get_scenario("antes_sem54")
    base = get_scenario("antes")
    assert sc.exclude_lines == ("54",)
    assert sc.smtuc == "smtuc-sem-54" and sc.smtuc_base == base.smtuc
    assert (sc.metro, sc.reference_day) == (base.metro, base.reference_day)
    assert excluded_integration_lines(sc) == ("54",)
    assert excluded_integration_lines(base) == ()


def test_scenario_exclude_lines_must_be_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    import config

    spec = {**config.SCENARIOS["antes"], "exclude_lines": "54"}
    monkeypatch.setitem(config.SCENARIOS, "x", spec)
    with pytest.raises(ValueError, match="lista"):
        get_scenario("x")


@pytest.mark.integration
def test_view_has_its_own_cache_signature() -> None:
    from overlap.overlap_db import _dataset_signature

    if not (dataset_dir("smtuc") / "trips.txt").exists():
        pytest.skip("feed SMTUC Ep212 não disponível")
    assert _dataset_signature("smtuc-sem-54") != _dataset_signature("smtuc")
