"""Cenários (D2.3, gtfs_processing/scenarios.py): cada cenário tem os seus feeds e o seu dia de
referência, e esses valores chegam a quem calcula (tabelas da 54, cache de métricas, validação do
regenerate) em vez de "smtuc"/"metrobus" e de um dia global escritos à mão."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import config
from gtfs_processing import scenarios
from gtfs_processing.scenarios import (
    get_scenario,
    reference_days_by_dataset,
    scenario_output_path,
    scenario_reference_day,
    scenario_reference_time,
)

TWO_SCENARIOS = {
    "a": {
        "description": "a", "smtuc": "smtuc", "metro": "metrobus",
        "reference_day": "2026-05-11", "reference_time": "08:20:00", "output_suffix": "",
    },
    "b": {
        "description": "b", "smtuc": "smtuc", "metro": "metro_fase2_oficial",
        "reference_day": "2026-11-09", "reference_time": "09:00:00", "output_suffix": "_b",
    },
}


@pytest.fixture
def two_scenarios(monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS", TWO_SCENARIOS)
    monkeypatch.setattr(config, "DEFAULT_SCENARIO", "a")
    monkeypatch.setattr(config, "USE_FIXED_REFERENCE_DAY", True)


def test_config_scenarios_are_valid() -> None:
    # Todos os cenários do config resolvem (chaves completas, datasets existentes, dia ISO) e o
    # cenário por omissão tem sufixo vazio (mantém os nomes de ficheiro de sempre).
    for name in config.SCENARIOS:
        sc = get_scenario(name)
        assert sc.name == name and sc.datasets == (sc.smtuc, sc.metro)
    assert get_scenario().name == config.DEFAULT_SCENARIO
    assert get_scenario().output_suffix == ""
    suffixes = [get_scenario(n).output_suffix for n in config.SCENARIOS]
    assert len(set(suffixes)) == len(suffixes), "dois cenários com o mesmo sufixo pisavam os ficheiros um do outro"


def test_unknown_or_broken_scenario_raises(monkeypatch) -> None:
    with pytest.raises(ValueError, match="desconhecido"):
        get_scenario("nao_existe")
    broken = {"x": {**TWO_SCENARIOS["a"], "metro": "metro_que_nao_existe"}}
    monkeypatch.setattr(config, "SCENARIOS", broken)
    with pytest.raises(ValueError, match="DATASET_DIRS"):
        get_scenario("x")
    incomplete = {"y": {k: v for k, v in TWO_SCENARIOS["a"].items() if k != "reference_day"}}
    monkeypatch.setattr(config, "SCENARIOS", incomplete)
    with pytest.raises(ValueError, match="reference_day"):
        get_scenario("y")


def test_each_scenario_has_its_own_reference_day(two_scenarios) -> None:
    from overlap.transit import resolve_reference_day

    assert scenario_reference_day("a") == date(2026, 5, 11)
    assert scenario_reference_day("b") == date(2026, 11, 9)
    assert scenario_reference_day() == date(2026, 5, 11)  # cenário por omissão
    # O dia vem SEMPRE do cenário - um day_str explícito continua a ser ignorado.
    assert resolve_reference_day("2020-01-01", scenario="b") == date(2026, 11, 9)
    assert scenario_reference_time("b") == "09:00:00"


def test_dynamic_day_is_the_same_for_every_scenario(two_scenarios, monkeypatch) -> None:
    monkeypatch.setattr(config, "USE_FIXED_REFERENCE_DAY", False)
    today = scenarios.nearest_business_day(date.today())
    assert scenario_reference_day("a") == scenario_reference_day("b") == today
    assert scenario_reference_time("b") is None  # "agora"


def test_output_path_gets_the_scenario_suffix(two_scenarios) -> None:
    assert scenario_output_path("outputs/overlap/line_metrics_db.csv", "a") == "outputs/overlap/line_metrics_db.csv"
    assert scenario_output_path("outputs/overlap/line_metrics_db.csv", "b") == "outputs/overlap/line_metrics_db_b.csv"
    assert scenario_output_path("outputs/overlap/mapa.html", "b") == "outputs/overlap/mapa_b.html"


def test_reference_days_by_dataset_collects_every_scenario(two_scenarios) -> None:
    days = reference_days_by_dataset()
    assert days["smtuc"] == {date(2026, 5, 11), date(2026, 11, 9)}
    assert days["metrobus"] == {date(2026, 5, 11)}
    assert days["metro_fase2_oficial"] == {date(2026, 11, 9)}


class _Loaded(Exception):
    pass


def test_line_54_tables_load_the_scenario_feeds(two_scenarios, monkeypatch, tmp_path) -> None:
    # Antes, transit.py carregava sempre "smtuc" e "metrobus", fosse qual fosse o cenário.
    from overlap import transit

    loaded: list[str] = []

    def fake_load(dataset):
        loaded.append(dataset)
        if len(loaded) == 2:
            raise _Loaded
        return None

    monkeypatch.setattr(transit, "_load_gtfs_cached", fake_load)
    for build in (transit.build_line_stop_vs_metro_table, transit.build_reverse_stop_vs_metro_table):
        loaded.clear()
        kwargs = {"metro_towards_ref": "X"} if build is transit.build_reverse_stop_vs_metro_table else {}
        with pytest.raises(_Loaded):
            build("Portagem", "Portagem", "54", output_dir=tmp_path, scenario="b", **kwargs)
        assert loaded == ["smtuc", "metro_fase2_oficial"]


def test_line_metrics_cache_uses_the_scenario(two_scenarios, monkeypatch, tmp_path) -> None:
    # Sem argumentos explícitos, o cache usa os datasets, o dia e o ficheiro (com sufixo) do cenário.
    from overlap import overlap_db

    seen: dict = {}

    def fake_compute(**kwargs):
        seen.update(kwargs)
        return pd.DataFrame()  # vazio -> não grava nada

    monkeypatch.setattr(overlap_db, "LINE_METRICS_DB_PATH", str(tmp_path / "line_metrics_db.csv"))
    monkeypatch.setattr(overlap_db, "_compute_line_metrics", fake_compute)
    monkeypatch.setattr(overlap_db, "_dataset_signature", lambda dataset: "sig")
    resolved: list = []
    real_resolve = overlap_db._resolve_db_path
    monkeypatch.setattr(overlap_db, "_resolve_db_path", lambda p=None: resolved.append(p) or real_resolve(p))

    overlap_db.build_line_metrics_db(scenario="b")
    assert seen["smtuc_dataset"] == "smtuc" and seen["metrobus_dataset"] == "metro_fase2_oficial"
    assert seen["reference_day"] == date(2026, 11, 9)
    assert resolved[-1].endswith("line_metrics_db_b.csv")


def test_regenerate_validates_each_scenario_on_its_own_day(two_scenarios, monkeypatch) -> None:
    import tests.regenerate_all_htmls as regen

    checked: list[tuple[str, date]] = []

    class FakeFeed:
        def __init__(self, name):
            self.name = name
            self.trips = pd.DataFrame({"service_id": ["s"]})

    monkeypatch.setattr(regen, "_require_dataset", lambda d: True)
    monkeypatch.setattr(regen, "_load_gtfs_cached", FakeFeed)
    monkeypatch.setattr(regen, "feed_service_period", lambda g: (20260101, 20261231))

    def fake_active(gtfs, day):
        checked.append((gtfs.name, day))
        if gtfs.name == "metro_fase2_oficial" and day < date(2026, 9, 10):
            raise regen.ServiceCalendarError("fora do período")
        return {"s"}

    monkeypatch.setattr(regen, "_active_service_ids", fake_active)
    assert regen._validate_reference_day() is True
    assert set(checked) == {
        ("smtuc", date(2026, 5, 11)), ("metrobus", date(2026, 5, 11)),
        ("smtuc", date(2026, 11, 9)), ("metro_fase2_oficial", date(2026, 11, 9)),
    }

    # Um cenário com o dia fora do período de um dos seus feeds faz falhar a validação.
    bad = {**TWO_SCENARIOS, "b": {**TWO_SCENARIOS["b"], "reference_day": "2026-05-11"}}
    monkeypatch.setattr(config, "SCENARIOS", bad)
    assert regen._validate_reference_day() is False
