from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from overlap.transit import build_line_stop_vs_metro_table, resolve_reference_day


def _dataset_dir(dataset: str) -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / dataset


def _require_dataset(dataset: str) -> Path:
    d = _dataset_dir(dataset)
    required = ["routes.txt", "trips.txt", "stops.txt", "stop_times.txt"]
    if not d.exists() or any(not (d / f).exists() for f in required):
        pytest.skip(f"Dataset GTFS invalido/incompleto: {d}")
    return d


@pytest.mark.integration
def test_line_54_portela_bus_vs_metro_from_portagem() -> None:
    """
    Verifica a pergunta:
    "a que horas a linha 54 passa na paragem de autocarros da Portela
    e a que horas o metro passa proveniente da Portagem pela paragem de metro da Portela".
    """
    _require_dataset("smtuc")
    _require_dataset("metrobus")

    expected_day = resolve_reference_day().strftime("%Y-%m-%d")

    # Mesmo com uma data hardcoded, o cálculo deve usar o dia útil de referência atual.
    df = build_line_stop_vs_metro_table(
        metro_stop_ref="Portela",
        bus_stop_ref="Portela do Mondego",
        line_number="54",
        day_str="2026-04-20",
        metro_origin_ref="Portagem",
        bus_origin_ref="Portagem",
    )
    # Reforço: outra data hardcoded também deve convergir para o mesmo dia útil.
    df_alt = build_line_stop_vs_metro_table(
        metro_stop_ref="Portela",
        bus_stop_ref="Portela do Mondego",
        line_number="54",
        day_str="1999-12-31",
        metro_origin_ref="Portagem",
        bus_origin_ref="Portagem",
    )

    expected_cols = {
        "idx",
        "bus_line",
        "bus_stop",
        "bus_time",
        "metro_stop",
        "metro_time_from_origin",
        "origin_ref",
        "date",
    }
    assert isinstance(df, pd.DataFrame)
    assert expected_cols.issubset(set(df.columns))
    assert not df.empty

    assert (df["bus_line"] == "54").all()
    assert (df["origin_ref"].str.lower() == "portagem").all()
    assert (df["date"] == expected_day).all()
    assert (df_alt["date"] == expected_day).all()

    bus_times = df.loc[df["bus_time"] != "", "bus_time"].tolist()
    metro_times = df.loc[df["metro_time_from_origin"] != "", "metro_time_from_origin"].tolist()

    assert len(bus_times) > 0
    assert len(metro_times) > 0

    # Guard rails estáveis para este dataset em dias úteis.
    assert any(t.startswith("07:") for t in bus_times)
    assert any(t.startswith("06:") for t in metro_times)

    print("\nTabela comparativa (linha 54 Portela vs Metro Portela vindo da Portagem):")
    print(df.to_string(index=False))


@pytest.mark.integration
def test_line_54_portagem_bus_vs_metro_from_portela() -> None:
    """
    Verifica a pergunta espelho:
    "a que horas a linha 54 passa na Portagem e a que horas o metro
    passa na Portagem proveniente da Portela".
    """
    _require_dataset("smtuc")
    _require_dataset("metrobus")

    expected_day = resolve_reference_day().strftime("%Y-%m-%d")

    # Mesmo com uma data hardcoded, o cálculo deve usar o dia útil de referência atual.
    df = build_line_stop_vs_metro_table(
        metro_stop_ref="Portagem",
        bus_stop_ref="Portagem",
        line_number="54",
        day_str="2026-04-20",
        metro_origin_ref="Portela",
        bus_origin_ref="Portela do Mondego",
    )
    # Reforço: outra data hardcoded também deve convergir para o mesmo dia útil.
    df_alt = build_line_stop_vs_metro_table(
        metro_stop_ref="Portagem",
        bus_stop_ref="Portagem",
        line_number="54",
        day_str="1999-12-31",
        metro_origin_ref="Portela",
        bus_origin_ref="Portela do Mondego",
    )

    expected_cols = {
        "idx",
        "bus_line",
        "bus_stop",
        "bus_time",
        "metro_stop",
        "metro_time_from_origin",
        "origin_ref",
        "date",
    }
    assert isinstance(df, pd.DataFrame)
    assert expected_cols.issubset(set(df.columns))
    assert not df.empty

    assert (df["bus_line"] == "54").all()
    assert (df["origin_ref"].str.lower() == "portela").all()
    assert (df["date"] == expected_day).all()
    assert (df_alt["date"] == expected_day).all()

    bus_times = df.loc[df["bus_time"] != "", "bus_time"].tolist()
    metro_times = df.loc[df["metro_time_from_origin"] != "", "metro_time_from_origin"].tolist()

    assert len(bus_times) > 0
    assert len(metro_times) > 0

    # Guard rails estáveis para este dataset em dias úteis.
    assert any(t.startswith("07:") for t in bus_times)
    assert any(t.startswith("06:") for t in metro_times)

    print("\nTabela comparativa (linha 54 Portagem vs Metro Portagem vindo da Portela):")
    print(df.to_string(index=False))
