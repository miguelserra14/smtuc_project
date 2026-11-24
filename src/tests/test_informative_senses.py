"""Sentidos bus->metro informativos (Portagem -> norte na fase 2) e origens que não existem no feed.

1. Uma origem/sentido pedido que não existe no feed REBENTA. Antes, uma lista de candidatas vazia
   desligava o filtro de sentido (`bool([])` é False) e contava as passagens dos dois sentidos:
   metro "vindo de Coimbra B" no feed da fase 1 (que acaba em Portagem) dava as 257 passagens.
2. O sentido norte de Portagem (`informative_reverse_senses` no config) junta os dois ramos da
   fase 2 (Coimbra B e República), só existe na fase 2 e nunca entra na busca do desvio de fase.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from config import INTEGRATION_SITES, SCENARIOS
from gtfs_processing.gtfs import GTFSData
from overlap.transit import (
    _arrival_events_for_stop,
    _arrival_times_for_stop,
    _origin_candidates_by_line,
    _pick_best_target_stop_id,
    informative_reverse_senses,
)
from tests.reference_data import require_reference_data
from tests.script_loader import load_script

PORTAGEM = next(s for s in INTEGRATION_SITES if s["name"] == "Portagem")


def _feed() -> GTFSData:
    # A -> B -> C e C -> B -> A (uma viagem por sentido).
    stops = pd.DataFrame({"stop_id": ["A", "B", "C"], "stop_name": ["Alfa", "Beta", "Gama"],
                          "stop_lat": [40.0, 40.01, 40.02], "stop_lon": [-8.0, -8.0, -8.0]})
    trips = pd.DataFrame({"route_id": ["R", "R"], "service_id": ["WD", "WD"], "trip_id": ["UP", "DOWN"]})
    rows = []
    for trip, seq in (("UP", [("A", "08:00:00"), ("B", "08:05:00"), ("C", "08:10:00")]),
                      ("DOWN", [("C", "09:00:00"), ("B", "09:05:00"), ("A", "09:10:00")])):
        for i, (stop, t) in enumerate(seq, start=1):
            rows.append({"trip_id": trip, "stop_id": stop, "stop_sequence": i, "arrival_time": t, "departure_time": t})
    return GTFSData(routes=pd.DataFrame(), trips=trips, stop_times=pd.DataFrame(rows), stops=stops,
                    shapes=pd.DataFrame(), calendar=pd.DataFrame(), calendar_dates=pd.DataFrame())


# --------------------------------------------------------------------------- origem desconhecida


def test_none_means_no_direction_filter_but_empty_list_raises() -> None:
    gtfs = _feed()
    assert _arrival_times_for_stop(gtfs, gtfs.trips, "B", None) == ["08:05:00", "09:05:00"]
    assert _arrival_times_for_stop(gtfs, gtfs.trips, "B", ["A"]) == ["08:05:00"]
    with pytest.raises(ValueError, match="sentido não seria filtrado"):
        _arrival_times_for_stop(gtfs, gtfs.trips, "B", [])
    with pytest.raises(ValueError, match="sentido não seria filtrado"):
        _arrival_events_for_stop(gtfs, gtfs.trips, "B", [])
    with pytest.raises(ValueError, match="sentido não seria filtrado"):
        _pick_best_target_stop_id(gtfs, gtfs.trips, ["A", "B"], [])


def test_unknown_bus_origin_raises() -> None:
    gtfs = _feed()
    with pytest.raises(ValueError, match="Origem de autocarro não encontrada.*38"):
        _origin_candidates_by_line(gtfs, {"54": "Alfa", "38": "Inexistente"}, ["54", "38"], 0)
    with pytest.raises(ValueError, match="Origem de autocarro não encontrada"):
        _origin_candidates_by_line(gtfs, "Inexistente", ["54"], 0)


# --------------------------------------------------------------------------- configuração


def test_informative_senses_config_is_consistent() -> None:
    for site in INTEGRATION_SITES:
        keys = [sense["key"] for sense in site.get("informative_reverse_senses", ())]
        assert len(keys) == len(set(keys)), site["name"]
        for sense in site.get("informative_reverse_senses", ()):
            assert set(sense) == {"key", "label", "towards_refs", "scenarios"}
            assert sense["towards_refs"] and not isinstance(sense["towards_refs"], str)
            assert set(sense["scenarios"]) <= set(SCENARIOS), "cenário desconhecido"


def test_north_of_portagem_only_in_phase_2() -> None:
    assert informative_reverse_senses(PORTAGEM, "antes") == []
    (north,) = informative_reverse_senses(PORTAGEM, "fase2")
    assert north["key"] == "norte" and tuple(north["towards_refs"]) == ("Coimbra B", "República")
    portela = next(s for s in INTEGRATION_SITES if s["name"] == "Portela")
    assert informative_reverse_senses(portela, "fase2") == []


def test_integration_page_renders_informative_groups_safely(tmp_path: Path) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    from visualizations.integration import create_combined_integration_dashboard

    fig = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]))
    hostile = "</script><script>alert(1)</script>"
    out = create_combined_integration_dashboard(
        tmp_path / "p.html", fig, fig,
        reverse={"waits_fig": fig, "equity_fig": fig, "variants": None},
        informative=[{"waits_fig": fig, "equity_fig": fig, "variants": None, "heading": hostile, "note": "nota"}],
    )
    text = Path(out).read_text(encoding="utf-8")
    assert "__INFORMATIVE_JSON__" not in text
    assert hostile not in text  # "</" escapado dentro do <script>
    # Só fecham as 2 tags reais (plotly por src= e o bloco da página): o texto não sai do <script>.
    assert text.count("</script>") == 2
    empty = Path(create_combined_integration_dashboard(tmp_path / "q.html", fig, fig)).read_text(encoding="utf-8")
    assert "const informative = [];" in empty


# --------------------------------------------------------------------------- dados reais


@pytest.mark.integration
def test_unknown_metro_origin_or_branch_raises_with_real_feeds(tmp_path: Path) -> None:
    require_reference_data("smtuc", "metrobus")
    from overlap.transit import build_line_stop_vs_metro_table, build_reverse_stop_vs_metro_table

    lines = list(PORTAGEM["line_number"])
    # Fase 1: o metro acaba em Portagem - não há "vindo de Coimbra B" nem sentido norte.
    with pytest.raises(ValueError, match="origem/sentido.*Coimbra B"):
        build_line_stop_vs_metro_table("Portagem", "Portagem", lines, metro_origin_ref="Coimbra B",
                                       bus_origin_ref="Portagem", output_dir=tmp_path, scenario="antes")
    with pytest.raises(ValueError, match="sentido.*Coimbra B"):
        build_reverse_stop_vs_metro_table("Portagem", "Portagem", lines, ("Vale das Flores", "Coimbra B"),
                                          bus_origin_ref=PORTAGEM["bus_origin_ref"], output_dir=tmp_path,
                                          scenario="antes")


@pytest.mark.integration
def test_north_sense_joins_both_branches_and_stays_out_of_the_search(tmp_path: Path) -> None:
    require_reference_data("smtuc_atual", "metro_fase2_oficial")
    from overlap.transit import build_reverse_stop_vs_metro_table

    search = load_script("search_phase_shift")
    main = search.load_schedules(tmp_path, scenario="fase2")
    info = search.load_informative_schedules(tmp_path, scenario="fase2")
    assert list(main) == ["Portagem metro→bus", "Portagem bus→metro", "Portela metro→bus", "Portela bus→metro"]
    assert list(info) == ["Portagem bus→metro (norte)"]
    assert search.load_informative_schedules(tmp_path, scenario="antes") == {}

    def departures(df: pd.DataFrame) -> set[str]:
        return {t for t in df["bus_time"].fillna("") if t}

    north = info["Portagem bus→metro (norte)"]
    kwargs = dict(bus_origin_ref=PORTAGEM["bus_origin_ref"], output_dir=tmp_path, scenario="fase2")
    lines = list(PORTAGEM["line_number"])
    coimbra_b = build_reverse_stop_vs_metro_table("Portagem", "Portagem", lines, "Coimbra B", output_csv_name="cb.csv", **kwargs)
    republica = build_reverse_stop_vs_metro_table("Portagem", "Portagem", lines, "República", output_csv_name="rp.csv", **kwargs)
    # Norte = união dos dois ramos (U1+S1 para Coimbra B, U2+S2 para a República), sem o sul.
    assert departures(north) == departures(coimbra_b) | departures(republica)
    assert len(departures(north)) == 153
    assert not departures(north) & departures(main["Portagem bus→metro"]) - departures(coimbra_b) - departures(republica)

    # Valores de 2026-11-24 (dia 2026-11-09, 54+38): sul 4,5 min; norte 5,73 min.
    m = search.sense_metrics(north)
    assert m["median"] == pytest.approx(5.73)
    assert search.sense_metrics(main["Portagem bus→metro"])["median"] == pytest.approx(4.5)
