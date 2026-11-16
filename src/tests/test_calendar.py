"""Testes da resolução de serviços ativos por dia (calendário GTFS, feriados, período do feed).

Unitários (GTFS sintético em memória, sem dados em disco) + um bloco de integração contra os
feeds reais (marcado `integration`). Cobrem o passo 0.3 do roadmap de auditoria: antes, um dia
fora do período do feed (ex.: a partir de 2027-01-01) ou sem serviço devolvia TODOS os
service_id (úteis + sábados + domingos somados) sem qualquer aviso.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gtfs_processing import gtfs_probe
from gtfs_processing.gtfs import GTFSData
from gtfs_processing.gtfs_probe import (
    ServiceCalendarError,
    _active_service_ids,
    _calendar_active_service_ids,
    _easter_sunday,
    feed_service_period,
    is_public_holiday,
    public_holidays,
)
from tests.reference_data import require_reference_data

WEEKDAY = date(2026, 5, 11)  # segunda-feira normal (o dia de referência fixo do projeto)
SATURDAY = date(2026, 5, 16)
SUNDAY = date(2026, 5, 17)
CHRISTMAS = date(2026, 12, 25)  # sexta-feira, feriado
OUT_OF_RANGE = date(2027, 1, 4)  # segunda-feira, depois de end_date=20261231
BEFORE_RANGE = date(2025, 12, 1)


def _calendar(rows: list[tuple]) -> pd.DataFrame:
    cols = ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"]
    return pd.DataFrame(rows, columns=cols)


STANDARD_CALENDAR = [
    ("Dias Uteis", 1, 1, 1, 1, 1, 0, 0, 20260104, 20261231),
    ("Sabados", 0, 0, 0, 0, 0, 1, 0, 20260104, 20261231),
    ("Domingos e Feriados", 0, 0, 0, 0, 0, 0, 1, 20260104, 20261231),
]


def _gtfs(
    trip_services: list[str],
    calendar_rows: list[tuple] | None = STANDARD_CALENDAR,
    calendar_dates_rows: list[tuple] | None = None,
) -> GTFSData:
    trips = pd.DataFrame(
        {
            "route_id": ["R"] * len(trip_services),
            "service_id": trip_services,
            "trip_id": [f"T{i}" for i in range(len(trip_services))],
        }
    )
    calendar = _calendar(calendar_rows) if calendar_rows else pd.DataFrame()
    calendar_dates = (
        pd.DataFrame(calendar_dates_rows, columns=["service_id", "date", "exception_type"])
        if calendar_dates_rows
        else pd.DataFrame()
    )
    empty = pd.DataFrame()
    return GTFSData(
        routes=empty, trips=trips, stop_times=empty, stops=empty, shapes=empty,
        calendar=calendar, calendar_dates=calendar_dates,
    )


# Feed tipo SMTUC: trips.txt usa os mesmos service_id que calendar.txt.
SMTUC_LIKE = ["Dias Uteis", "Dias Uteis", "Sabados", "Domingos e Feriados"]
# Feed tipo Metrobus: trips.txt usa WD/SAT/SUN, calendar.txt usa nomes por extenso (nunca se cruzam).
METRO_LIKE = ["WD", "WD", "SAT", "SUN"]


# --------------------------------------------------------------------------------------------
# Feriados
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "year, expected",
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2038, date(2038, 4, 25))],
)
def test_easter_sunday_known_dates(year: int, expected: date) -> None:
    assert _easter_sunday(year) == expected


def test_public_holidays_2026_complete_list() -> None:
    expected = {
        date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 5), date(2026, 4, 25), date(2026, 5, 1),
        date(2026, 6, 4), date(2026, 6, 10), date(2026, 7, 4), date(2026, 8, 15), date(2026, 10, 5),
        date(2026, 11, 1), date(2026, 12, 1), date(2026, 12, 8), date(2026, 12, 25),
    }
    assert set(public_holidays(2026)) == expected


def test_moving_holidays_2027() -> None:
    assert is_public_holiday(date(2027, 3, 26))  # Sexta-feira Santa
    assert is_public_holiday(date(2027, 5, 27))  # Corpo de Deus
    assert not is_public_holiday(date(2027, 6, 4))  # Corpo de Deus de 2026, não de 2027


def test_reference_day_is_not_a_holiday() -> None:
    assert not is_public_holiday(WEEKDAY)


# --------------------------------------------------------------------------------------------
# Dias normais (sem regressões face ao comportamento anterior)
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "day, smtuc_expected, metro_expected",
    [(WEEKDAY, {"Dias Uteis"}, {"WD"}), (SATURDAY, {"Sabados"}, {"SAT"}), (SUNDAY, {"Domingos e Feriados"}, {"SUN"})],
)
def test_normal_days(day: date, smtuc_expected: set[str], metro_expected: set[str]) -> None:
    assert _active_service_ids(_gtfs(SMTUC_LIKE), day) == smtuc_expected
    assert _active_service_ids(_gtfs(METRO_LIKE), day) == metro_expected


def test_service_id_matching_is_case_and_underscore_insensitive() -> None:
    gtfs = _gtfs(["DIAS_UTEIS", "SABADOS"])
    assert _active_service_ids(gtfs, WEEKDAY) == {"DIAS_UTEIS"}


# --------------------------------------------------------------------------------------------
# Feriados tratados como domingo
# --------------------------------------------------------------------------------------------

def test_holiday_on_weekday_uses_sunday_service() -> None:
    assert _active_service_ids(_gtfs(SMTUC_LIKE), CHRISTMAS) == {"Domingos e Feriados"}
    assert _active_service_ids(_gtfs(METRO_LIKE), CHRISTMAS) == {"SUN"}


def test_holiday_on_saturday_uses_sunday_service() -> None:
    coimbra_day = date(2026, 7, 4)  # sábado, feriado municipal
    assert _active_service_ids(_gtfs(SMTUC_LIKE), coimbra_day) == {"Domingos e Feriados"}


def test_holiday_handling_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gtfs_probe, "FERIADOS_COMO_DOMINGO", False)
    assert _active_service_ids(_gtfs(SMTUC_LIKE), CHRISTMAS) == {"Dias Uteis"}
    assert _active_service_ids(_gtfs(METRO_LIKE), CHRISTMAS) == {"WD"}


def test_feed_exception_on_holiday_wins_over_sunday_substitution() -> None:
    # O operador definiu ele próprio um serviço especial para o Natal: não se soma o de domingo.
    gtfs = _gtfs(
        SMTUC_LIKE + ["Natal"],
        calendar_dates_rows=[("Natal", 20261225, 1), ("Dias Uteis", 20261225, 2)],
    )
    assert _active_service_ids(gtfs, CHRISTMAS) == {"Natal"}


# --------------------------------------------------------------------------------------------
# calendar_dates.txt (exceções)
# --------------------------------------------------------------------------------------------

def test_calendar_dates_added_and_removed_service() -> None:
    # Caso real SMTUC: 23/03/2026 tem um serviço especial que substitui o de dia útil.
    gtfs = _gtfs(
        SMTUC_LIKE + ["23/03/2026"],
        calendar_dates_rows=[("23/03/2026", 20260323, 1), ("Dias Uteis", 20260323, 2)],
    )
    assert _active_service_ids(gtfs, date(2026, 3, 23)) == {"23/03/2026"}
    assert _active_service_ids(gtfs, date(2026, 3, 24)) == {"Dias Uteis"}


def test_calendar_dates_removal_with_namespace_mismatch_falls_back_to_alias(capsys: pytest.CaptureFixture[str]) -> None:
    # Caso real Metrobus: a exceção adiciona um service_id que nenhuma trip usa.
    gtfs = _gtfs(METRO_LIKE, calendar_dates_rows=[("07/01/2026", 20260107, 1), ("Dias Uteis", 20260107, 2)])
    assert _active_service_ids(gtfs, date(2026, 1, 7)) == {"WD"}
    assert "[WARNING]" in capsys.readouterr().out


def test_calendar_dates_only_feed() -> None:
    gtfs = _gtfs(["S1", "S2"], calendar_rows=None, calendar_dates_rows=[("S1", 20260511, 1), ("S2", 20260512, 1)])
    assert feed_service_period(gtfs) == (20260511, 20260512)
    assert _active_service_ids(gtfs, WEEKDAY) == {"S1"}
    assert _active_service_ids(gtfs, date(2026, 5, 12)) == {"S2"}


def test_all_services_removed_gives_empty_set_not_everything() -> None:
    gtfs = _gtfs(SMTUC_LIKE, calendar_dates_rows=[("Dias Uteis", 20260511, 2)])
    assert _active_service_ids(gtfs, WEEKDAY) == set()


# --------------------------------------------------------------------------------------------
# Período do feed e erros explícitos (antes: fallback silencioso para todos os serviços)
# --------------------------------------------------------------------------------------------

def test_feed_service_period() -> None:
    assert feed_service_period(_gtfs(SMTUC_LIKE)) == (20260104, 20261231)
    assert feed_service_period(_gtfs(SMTUC_LIKE, calendar_rows=None)) is None


@pytest.mark.parametrize("day", [OUT_OF_RANGE, BEFORE_RANGE])
def test_day_outside_feed_period_raises(day: date) -> None:
    for trips in (SMTUC_LIKE, METRO_LIKE):
        with pytest.raises(ServiceCalendarError, match="fora do período") as exc_info:
            _active_service_ids(_gtfs(trips), day)
        assert "20260104..20261231" in str(exc_info.value)


def test_last_and_first_day_of_period_are_inside() -> None:
    assert _active_service_ids(_gtfs(SMTUC_LIKE), date(2026, 12, 31)) == {"Dias Uteis"}  # quinta
    assert _active_service_ids(_gtfs(SMTUC_LIKE), date(2026, 1, 4)) == {"Domingos e Feriados"}  # domingo


def test_feed_without_any_calendar_raises() -> None:
    with pytest.raises(ServiceCalendarError, match="sem calendar"):
        _active_service_ids(_gtfs(SMTUC_LIKE, calendar_rows=None), WEEKDAY)


def test_unmappable_service_ids_raise() -> None:
    with pytest.raises(ServiceCalendarError, match="Nenhum service_id"):
        _active_service_ids(_gtfs(["X1", "X2"]), WEEKDAY)


def test_service_calendar_error_is_a_value_error() -> None:
    # Chamadores que já apanham ValueError (ex.: _collect_commute_options) continuam a degradar.
    assert issubclass(ServiceCalendarError, ValueError)


def test_in_range_day_without_service_is_empty_not_error() -> None:
    weekday_only = [("Dias Uteis", 1, 1, 1, 1, 1, 0, 0, 20260104, 20261231)]
    assert _active_service_ids(_gtfs(["Dias Uteis"], calendar_rows=weekday_only), SUNDAY) == set()
    # Mesmo com trips "SUN" (espaço de nomes diferente), manda o calendário: domingo sem serviço.
    assert _active_service_ids(_gtfs(["WD", "SUN"], calendar_rows=weekday_only), SUNDAY) == set()


def test_calendar_service_outside_its_own_range_is_inactive() -> None:
    rows = [
        ("Inverno", 1, 1, 1, 1, 1, 0, 0, 20260104, 20260630),
        ("Verao", 1, 1, 1, 1, 1, 0, 0, 20260701, 20261231),
    ]
    gtfs = _gtfs(["Inverno", "Verao"], calendar_rows=rows)
    assert _calendar_active_service_ids(gtfs, WEEKDAY) == {"Inverno"}
    assert _active_service_ids(gtfs, date(2026, 7, 6)) == {"Verao"}


def test_empty_trips_gives_empty_set() -> None:
    assert _active_service_ids(_gtfs([]), WEEKDAY) == set()


# --------------------------------------------------------------------------------------------
# Integração: feeds reais em data/ (read-only)
# --------------------------------------------------------------------------------------------

def _real(dataset: str):
    from gtfs_processing.gtfs import dataset_dir

    if not (dataset_dir(dataset) / "trips.txt").exists():
        pytest.skip(f"dataset {dataset} não disponível")
    from overlap.overlap_db import _load_gtfs_cached

    return _load_gtfs_cached(dataset)


# Feriado de teste por feed: o GTFS oficial do Metro (fase 1) só vai até 2026-09-09, por isso
# usa o 10 de Junho em vez do Natal.
DIA_DE_PORTUGAL = date(2026, 6, 10)  # quarta-feira, feriado


@pytest.mark.integration
@pytest.mark.parametrize(
    "dataset, weekday_trips, sunday_ids, holiday",
    [
        ("smtuc", 2373, {"Domingos e Feriados"}, CHRISTMAS),
        # Oficial (D1 passo 4): serviço 3 = dias úteis, 1 = domingo; 291 conferido no ficheiro bruto.
        ("metrobus", 291, {"1"}, DIA_DE_PORTUGAL),
        ("metrobus_fase2", 303, {"SUN"}, CHRISTMAS),
    ],
)
def test_real_feeds(dataset: str, weekday_trips: int, sunday_ids: set[str], holiday: date) -> None:
    gtfs = _real(dataset)
    require_reference_data(dataset)  # contagens fixas: só valem para os feeds calibrados
    trip_sids = gtfs.trips["service_id"].astype(str)

    active = _active_service_ids(gtfs, WEEKDAY)
    assert int(trip_sids.isin(active).sum()) == weekday_trips  # igual ao valor antes da alteração

    assert _active_service_ids(gtfs, holiday) == sunday_ids
    assert _active_service_ids(gtfs, SUNDAY) == sunday_ids

    with pytest.raises(ServiceCalendarError):
        _active_service_ids(gtfs, OUT_OF_RANGE)


@pytest.mark.integration
def test_official_phase1_metro_refuses_phase2_dates() -> None:
    """O GTFS da fase 1 vale até 2026-09-09 (calendário estendido no build): um dia já da fase 2
    tem de dar erro, nunca o horário da fase 1."""
    gtfs = _real("metrobus")
    require_reference_data("metrobus")
    assert _active_service_ids(gtfs, date(2026, 9, 9)) == {"3"}
    with pytest.raises(ServiceCalendarError):
        _active_service_ids(gtfs, date(2026, 9, 10))


@pytest.mark.integration
def test_real_feed_out_of_range_propagates_to_departures() -> None:
    _real("smtuc")
    require_reference_data("smtuc")  # OUT_OF_RANGE só está fora do período deste feed
    from population.operations_population import _departures_per_stop_for_day

    with pytest.raises(ServiceCalendarError):
        _departures_per_stop_for_day("smtuc", OUT_OF_RANGE)
