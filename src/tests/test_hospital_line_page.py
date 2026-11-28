"""Serviço numa estação e página do horário assumido da Linha do Hospital (N3.5).

Feed sintético em memória; escreve só em tmp_path."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gtfs_processing.gtfs import GTFSData
from gtfs_processing.hospital_line import ALL_LINES, station_service
from visualizations.hospital_line_page import create_hospital_line_html, extension_step, legs_table

MONDAY = date(2026, 11, 9)


def _feed() -> GTFSData:
    """Linha U2: 3 viagens a subir (República -> HUC -> Pediátrico) às 08:00, 08:10, 08:30 e uma
    a descer (Pediátrico -> HUC -> República (desc)); a viagem de sábado não conta."""
    stops = pd.DataFrame([("r", "República (asc)"), ("h", "Hospitais (H.U.C.)"), ("p", "Pediátrico"),
                          ("rd", "República (desc)")], columns=["stop_id", "stop_name"])
    routes = pd.DataFrame([("1", "U2")], columns=["route_id", "route_short_name"])
    calendar = pd.DataFrame([("U", 1, 1, 1, 1, 1, 0, 0, 20260101, 20261231), ("S", 0, 0, 0, 0, 0, 1, 0, 20260101, 20261231)],
                            columns=["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                                     "sunday", "start_date", "end_date"])
    spec = [("a", "U", "r h p", 8 * 60), ("b", "U", "r h p", 8 * 60 + 10), ("c", "U", "r h p", 8 * 60 + 30),
            ("d", "U", "p h rd", 9 * 60), ("e", "S", "r h p", 8 * 60)]
    trips = pd.DataFrame([("1", s, t) for t, s, _, _ in spec], columns=["route_id", "service_id", "trip_id"])
    rows = []
    for trip, _, seq, start in spec:
        for k, stop in enumerate(seq.split()):
            t = (start + 2 * k) * 60
            rows.append({"trip_id": trip, "stop_id": stop, "stop_sequence": k + 1, "arrival_seconds": t, "departure_seconds": t})
    return GTFSData(routes=routes, trips=trips, stop_times=pd.DataFrame(rows), stops=stops, shapes=pd.DataFrame(),
                    calendar=calendar, calendar_dates=pd.DataFrame())


def test_station_service_by_line_and_sense() -> None:
    service = station_service(_feed(), MONDAY, "Hospitais (H.U.C.)", "Pediátrico", (7, 20)).set_index(["linha", "sentido"])
    up = service.loc[("U2", "subir")]
    assert (up["passagens"], up["primeira"], up["ultima"]) == (3, "08:02", "08:32")
    assert up["intervalo_mediano_min"] == 15.0  # intervalos 10 e 20
    assert service.loc[("U2", "descer"), "passagens"] == 1
    assert pd.isna(service.loc[("U2", "descer"), "intervalo_mediano_min"])  # uma só passagem
    assert service.loc[(ALL_LINES, "subir"), "passagens"] == 3
    # fora da janela não entra no intervalo
    narrow = station_service(_feed(), MONDAY, "Hospitais (H.U.C.)", "Pediátrico", (8.1, 20)).set_index(["linha", "sentido"])
    assert narrow.loc[("U2", "subir"), "intervalo_mediano_min"] == 20.0


def _step() -> dict:
    return {
        "passo": "PLANEADO: prolongar até ao Pediátrico (Linha do Hospital)",
        "linhas": ["U2", "U3"],
        "velocidade_referencia": {"subir": {"troco": "A -> B", "eixo_m": 1000.0, "viagens": 10, "minutos_medios": 3.0, "km_h": 20.0}},
        "trocos": {
            "subir": [{"de": "República (asc)", "para": "Celas", "eixo_m": 900.0, "minutos": 2.7},
                      {"de": "Celas", "para": "<Pediátrico>", "eixo_m": 500.0, "minutos": 1.5}],
            "descer": [{"de": "<Pediátrico>", "para": "Celas", "eixo_m": 500.0, "minutos": 1.7},
                       {"de": "Celas", "para": "República (desc)", "eixo_m": 880.0, "minutos": 3.0}],
        },
    }


def test_extension_step_and_legs(tmp_path: Path) -> None:
    path = tmp_path / "PROVENANCE.json"
    path.write_text(json.dumps({"transformacoes": [{"passo": "outro"}, _step()]}), encoding="utf-8")
    assert extension_step(path)["linhas"] == ["U2", "U3"]
    legs = legs_table(_step())
    assert legs[["de", "para"]].values.tolist() == [["República", "Celas"], ["Celas", "<Pediátrico>"]]
    assert legs.loc[0, "min_descer"] == 3.0  # o troço a descer correspondente, ao contrário
    path.write_text(json.dumps({"transformacoes": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="esperado 1"):
        extension_step(path)


def test_hospital_line_page(tmp_path: Path) -> None:
    service = station_service(_feed(), MONDAY, "Hospitais (H.U.C.)", "Pediátrico", (7, 20))
    page = Path(create_hospital_line_html(tmp_path / "l.html", _step(), {"D": service, "D & metade": service.iloc[0:0]},
                                          "Hospitais (H.U.C.)", "09/11/2026")).read_text(encoding="utf-8")
    assert "&lt;Pediátrico&gt;" in page and "<Pediátrico>" not in page
    assert "D &amp; metade" in page
    assert "1 400 m" in page  # total da via a subir
    assert "Todas as linhas" in page and "15,0 min" in page
    assert "20,0 km/h" in page and "U2, U3" in page
