from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from overlap.transit import build_line_stop_vs_metro_table


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

    # Data de segunda-feira dentro do calendario GTFS atual.
    df = build_line_stop_vs_metro_table(
        metro_stop_ref="Portela",
        bus_stop_ref="Portela do Mondego",
        line_number="54",
        day_str="2026-04-20",
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

    bus_times = df.loc[df["bus_time"] != "", "bus_time"].tolist()
    metro_times = df.loc[df["metro_time_from_origin"] != "", "metro_time_from_origin"].tolist()

    assert len(bus_times) > 0
    assert len(metro_times) > 0

    # Guard rails para este dataset: horarios conhecidos para o cenario pedido.
    assert "07:20:00" in bus_times
    assert "06:44:00" in metro_times

    print("\nTabela comparativa (linha 54 Portela vs Metro Portela vindo da Portagem):")
    print(df.to_string(index=False))
