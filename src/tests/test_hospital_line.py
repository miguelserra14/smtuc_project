"""Velocidade de referência e tempos assumidos da Linha do Hospital (N3.1, gtfs_processing/hospital_line.py).

Tabelas sintéticas em memória; o teste com os dados oficiais salta sem o KMZ ou o feed da fase 2."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from gtfs_processing import hospital_line as hl
from gtfs_processing import kmz

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_KMZ = ROOT / "data/raw/dados-gov/metro-mondego-kmz/20260817-153951-91f456a7/rede-metrobus.kmz"


def _tables():
    stops = pd.DataFrame({"stop_id": ["1", "2", "3", "4"], "stop_name": ["Loja do Cidadão", "Câmara (asc)", "República (asc)", "Outra"]})
    rows = []
    for trip, start, minutes in (("t1", 3600, 3.0), ("t2", 7200, 4.0)):
        for seq, (stop, offset) in enumerate((("1", 0.0), ("2", minutes / 2), ("3", minutes)), start=1):
            t = start + int(offset * 60)
            rows.append({"trip_id": trip, "stop_id": stop, "stop_sequence": seq, "arrival_seconds": t, "departure_seconds": t})
    # t3 passa na República ANTES da Loja: não conta para "Loja -> República".
    rows += [{"trip_id": "t3", "stop_id": "3", "stop_sequence": 1, "arrival_seconds": 100, "departure_seconds": 100},
             {"trip_id": "t3", "stop_id": "1", "stop_sequence": 2, "arrival_seconds": 400, "departure_seconds": 400}]
    return stops, pd.DataFrame(rows)


def test_segment_minutes_only_in_travel_order() -> None:
    stops, st = _tables()
    minutes = hl.segment_minutes(stops, st, "Loja do Cidadão", "República (asc)")
    assert minutes.to_dict() == {"t1": 3.0, "t2": 4.0}


def test_segment_minutes_reads_time_strings() -> None:
    stops, st = _tables()
    as_text = st.drop(columns=["arrival_seconds", "departure_seconds"]).assign(
        arrival_time=[f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}" for s in st["arrival_seconds"]],
        departure_time=[f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}" for s in st["departure_seconds"]],
    )
    assert hl.segment_minutes(stops, as_text, "Loja do Cidadão", "República (asc)").to_dict() == {"t1": 3.0, "t2": 4.0}


def test_speed_and_leg_times() -> None:
    sp = hl.SegmentSpeed("subir", "A", "B", eixo_m=1000.0, viagens=2, minutos_medios=4.0)
    assert sp.m_por_min == 250.0 and sp.km_h == pytest.approx(15.0)
    legs = [kmz.Leg("B", "C", 500.0, 480.0, 0.0, 0.0), kmz.Leg("C", "D", 250.0, 250.0, 0.0, 0.0)]
    timed = hl.timed_legs(legs, sp)
    assert [(t.origem, t.destino, t.minutos) for t in timed] == [("B", "C", 2.0), ("C", "D", 1.0)]


@pytest.mark.integration
def test_official_reference_speeds() -> None:
    from gtfs_processing.gtfs import dataset_dir, load_gtfs_cached

    if not OFFICIAL_KMZ.exists() or not (dataset_dir("metro_fase2_oficial") / "stop_times.txt").exists():
        pytest.skip("KMZ oficial ou feed da fase 2 não disponível")
    gtfs = load_gtfs_cached("metro_fase2_oficial")
    speeds = hl.reference_speeds(OFFICIAL_KMZ, gtfs.stops, gtfs.stop_times)
    for sense, sp in speeds.items():
        assert sp.viagens > 100, sense          # U2, U3 e S2 fazem este troço
        assert 12 < sp.km_h < 30, (sense, sp)    # metrobus em meio urbano, com paragens
        assert 1000 < sp.eixo_m < 1400, (sense, sp)
    legs = hl.hospital_timetable_legs(OFFICIAL_KMZ, gtfs.stops, gtfs.stop_times)
    assert [l.destino for l in legs["subir"]][-1] == "Pediátrico"
    assert 5 < sum(l.minutos for l in legs["subir"]) < 12
    assert 5 < sum(l.minutos for l in legs["descer"]) < 12
