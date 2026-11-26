"""Diferenças de rede SMTUC linha a linha (N1.3, overlap/network_diff.py) e a sua página.

Feeds sintéticos em memória: não lê dados nem escreve em outputs/."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from gtfs_processing.gtfs import GTFSData
from overlap.network_diff import (
    STATUS_ORDER,
    LineProfile,
    add_line_metrics,
    annotate_line_changes,
    compare_networks,
    line_profiles,
    load_line_changes,
    stop_coordinates,
    summarize,
)
from visualizations.network_diff_page import create_network_diff_html

MONDAY = date(2026, 11, 9)


def _p(line: str, stops: str, departures: tuple[int, ...] = (100,), name: str = "") -> LineProfile:
    keys = frozenset(stops.split())
    return LineProfile(line=line, name=name, trips=len(departures), stops=keys, departures=departures)


def _coords(*keys: str, lat0: float = 40.2, step_m: float = 1000.0) -> dict[str, tuple[float, float]]:
    """Paragens em fila, `step_m` entre cada uma (1 grau de latitude ~ 111 km)."""
    return {k: (lat0 + i * step_m / 111_000, -8.4) for i, k in enumerate(keys)}


def test_each_status_and_the_order() -> None:
    before = {
        "1": _p("1", "a b c d"),                    # igual
        "2": _p("2", "a b c", (100, 200)),          # só horário (mesmas paragens)
        "3": _p("3", "a b c d e f"),                # percurso alterado (e, f -> x, y, z, w longe)
        "4": _p("4", "g h i"),                      # ajuste: i deslocada para i2 (a 50 m)
        "33": _p("33", "m n o p q"),                # renumerada em 101 (4 de 5 paragens)
        "7T": _p("7T", "r s t"),                    # cortada
    }
    after = {
        "1": _p("1", "a b c d"),
        "2": _p("2", "a b c", (100, 210)),
        "3": _p("3", "a b c d x y z w"),
        "4": _p("4", "g h i2"),
        "101": _p("101", "m n o p"),
        "251": _p("251", "u v"),                    # nova
    }
    coords_b = {**_coords("a", "b", "c", "d", "e", "f", "g", "h", "m", "n", "o", "p", "q", "r", "s", "t"), "i": (40.0, -8.4)}
    # x, y, z, w a ~90 km das paragens retiradas e, f: não podem contar como deslocadas.
    coords_a = {**_coords("x", "y", "z", "w", lat0=41.0), "i2": (40.0 + 50 / 111_000, -8.4)}
    diff = compare_networks(before, after, coords_b, coords_a)
    status = {(r.linha_antes, r.linha_depois): r.estado for r in diff.itertuples()}
    assert status == {
        ("1", "1"): "igual",
        ("2", "2"): "só horário",
        ("3", "3"): "percurso alterado",
        ("4", "4"): "ajuste de paragens",
        ("33", "101"): "renumerada",
        ("7T", ""): "cortada",
        ("", "251"): "nova",
    }
    # Ordenado pelo estado (STATUS_ORDER).
    order = [STATUS_ORDER.index(s) for s in diff["estado"]]
    assert order == sorted(order)
    four = diff[diff["linha_antes"] == "4"].iloc[0]
    assert (four.paragens_deslocadas, four.paragens_retiradas, four.paragens_novas) == (1, 0, 0)
    three = diff[diff["linha_antes"] == "3"].iloc[0]
    assert (three.paragens_mantidas, three.paragens_retiradas, three.paragens_novas) == (4, 2, 4)
    assert summarize(diff)["estados"]["renumerada"] == 1


def test_without_coordinates_nothing_counts_as_moved() -> None:
    # Sem coordenadas, a troca de i por i2 é uma diferença de paragens (ajuste, abaixo do limiar).
    diff = compare_networks({"4": _p("4", "g h i")}, {"4": _p("4", "g h i2")})
    row = diff.iloc[0]
    assert (row.estado, row.paragens_deslocadas, row.paragens_retiradas, row.paragens_novas) == ("ajuste de paragens", 0, 1, 1)


def test_renumbering_pairs_each_line_once_by_best_similarity() -> None:
    before = {"A": _p("A", "1 2 3 4 5"), "B": _p("B", "1 2 3 4 9")}
    after = {"X": _p("X", "1 2 3 4 5")}  # A é igual a X; B fica cortada (X já tem par)
    diff = compare_networks(before, after)
    assert set(zip(diff["linha_antes"], diff["linha_depois"], diff["estado"])) == {
        ("A", "X", "renumerada"), ("B", "", "cortada")}


def _feed(stop_ids: dict[str, str]) -> GTFSData:
    """Duas linhas; a "W" só circula ao sábado. `stop_ids` = código -> stop_id deste feed (o Ep225
    renumerou os stop_id, mas o stop_code manteve-se)."""
    calendar = pd.DataFrame(
        [("U", 1, 1, 1, 1, 1, 0, 0, 20260101, 20261231), ("S", 0, 0, 0, 0, 0, 1, 0, 20260101, 20261231)],
        columns=["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
    )
    routes = pd.DataFrame([("r1", "5", "Pedrulha - Portagem"), ("r2", "W", "Só sábados")],
                          columns=["route_id", "route_short_name", "route_long_name"])
    trips = pd.DataFrame([("r1", "U", "t1"), ("r1", "U", "t2"), ("r2", "S", "t3")], columns=["route_id", "service_id", "trip_id"])
    rows = []
    for trip, start in (("t2", 900), ("t1", 300), ("t3", 500)):
        for seq, code in enumerate(("1000", "1001", "1002"), start=1):
            rows.append({"trip_id": trip, "stop_id": stop_ids[code], "stop_sequence": seq, "departure_seconds": start + 60 * seq})
    stops = pd.DataFrame([(sid, code, 40.2 + i / 1000, -8.4) for i, (code, sid) in enumerate(stop_ids.items())],
                         columns=["stop_id", "stop_code", "stop_lat", "stop_lon"])
    return GTFSData(routes=routes, trips=trips, stop_times=pd.DataFrame(rows), stops=stops,
                    shapes=pd.DataFrame(), calendar=calendar, calendar_dates=pd.DataFrame())


def test_profiles_use_the_reference_day_and_stop_codes() -> None:
    old = _feed({"1000": "1", "1001": "2", "1002": "3"})
    new = _feed({"1000": "1000", "1001": "1001", "1002": "1002"})
    prof_old, prof_new = line_profiles(old, MONDAY), line_profiles(new, MONDAY)
    assert set(prof_old) == {"5"}  # a "W" só circula ao sábado
    five = prof_old["5"]
    assert (five.trips, five.departures, five.name) == (2, (360, 960), "Pedrulha - Portagem")
    assert five.stops == prof_new["5"].stops == frozenset({"1000", "1001", "1002"})
    assert stop_coordinates(old)["1000"] == stop_coordinates(new)["1000"]
    assert compare_networks(prof_old, prof_new).iloc[0]["estado"] == "igual"


def test_metrics_and_notices_are_joined_by_line(tmp_path: Path) -> None:
    diff = compare_networks({"33": _p("33", "a b"), "5": _p("5", "c d")}, {"5": _p("5", "c d e f g h")})
    metrics_b = pd.DataFrame({"line": ["33", "5"], "overlap_extension_m": [7000.0, 6400.0]})
    metrics_a = pd.DataFrame({"line": [5], "overlap_extension_m": [14600.0]})  # número, não texto
    diff = add_line_metrics(diff, metrics_b, metrics_a)
    five = diff[diff["linha_antes"] == "5"].iloc[0]
    assert (five.overlap_extension_m_antes, five.overlap_extension_m_depois) == (6400.0, 14600.0)
    cut = diff[diff["linha_antes"] == "33"].iloc[0]
    assert pd.isna(cut.overlap_extension_m_depois)  # sem métricas -> vazio, nunca 0

    csv = tmp_path / "avisos.csv"
    csv.write_text(
        "data_vigor,linhas,periodo,descricao,data_aviso,fonte\n"
        "2026-06-14,5;33,antes do Como Vou,Reestruturação,2026-05-29,https://exemplo/aviso\n",
        encoding="utf-8",
    )
    diff = annotate_line_changes(diff, load_line_changes(csv))
    assert set(diff["aviso"]) == {"antes do Como Vou (14/06/2026)"}

    hostile = diff.copy()
    hostile.loc[0, "nome_antes"] = "<script>alert(1)</script>"
    page = Path(create_network_diff_html(tmp_path / "rede.html", hostile, "Metro + Ep212", "Como Vou",
                                         csv_path=tmp_path / "rede.csv"))
    text = page.read_text(encoding="utf-8")
    assert "<script>" not in text
    assert "Metro + Ep212 → Como Vou" in text and "antes do Como Vou (14/06/2026)" in text
    assert len(pd.read_csv(tmp_path / "rede.csv")) == len(diff)
