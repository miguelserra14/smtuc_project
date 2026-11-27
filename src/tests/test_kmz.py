"""Leitura do KMZ da rede Metrobus e distâncias no eixo (N3.0, gtfs_processing/kmz.py).

KML sintético em tmp_path; o teste com o KMZ oficial salta se ele não estiver em data/raw/."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from gtfs_processing import kmz
from gtfs_processing.geo import haversine_m

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_KMZ = ROOT / "data/raw/dados-gov/metro-mondego-kmz/20260817-153951-91f456a7/rede-metrobus.kmz"
_LAT0, _LON0 = 40.2, -8.4
_DEG_LAT_M = 111_195.0  # metros por grau de latitude na esfera da haversine


def _n(m: float) -> float:
    return _LAT0 + m / _DEG_LAT_M


def _line(*points_m: float, lon: float = _LON0) -> str:
    return " ".join(f"{lon},{_n(m)},0" for m in points_m)


def _kml(lines: list[str], points: dict[str, tuple[float, float]]) -> str:
    pls = "".join(f"<Placemark><name>eixo</name><LineString><coordinates>{c}</coordinates></LineString></Placemark>" for c in lines)
    pts = "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"
                  for n, (lat, lon) in points.items())
    return ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<Folder><name>Linha do Hospital</name><Folder><name>Eixo LH</name>{pls}</Folder>"
            f"<Folder><name>Paragens LH</name>{pts}</Folder></Folder></Document></kml>")


def _write_kmz(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rede.kmz"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("doc.kml", text)
    return path


def test_reads_folders_points_and_lines(tmp_path: Path) -> None:
    path = _write_kmz(tmp_path, _kml([_line(0, 100)], {"A": (_n(0), _LON0)}))
    pms = kmz.read_placemarks(path)
    assert {(p.kind, p.name) for p in pms} == {("line", "eixo"), ("point", "A")}
    line = next(p for p in pms if p.kind == "line")
    assert line.folders == ("Linha do Hospital", "Eixo LH")
    assert line.coords[0] == pytest.approx((_n(0), _LON0))  # (lat, lon), não (lon, lat)


def test_distance_follows_the_axis_across_fragments(tmp_path: Path) -> None:
    # Dois troços em ordem trocada que se tocam numa ponta, e um terceiro cuja ponta fica a 2 m
    # de um vértice do primeiro (junta-se por SNAP_M).
    lines = [_line(500, 1000), _line(0, 250, 500), _line(1002, 1500)]
    points = {"A": (_n(0), _LON0), "B": (_n(500), _LON0 + 0.0002), "C": (_n(1500), _LON0)}
    path = _write_kmz(tmp_path, _kml(lines, points))
    pms = kmz.read_placemarks(path)
    legs = kmz.chain_distances(kmz.axis_graph(pms), kmz.stations(pms, "Paragens LH"), ("A", "B", "C"))
    assert [(l.origem, l.destino) for l in legs] == [("A", "B"), ("B", "C")]
    assert legs[0].eixo_m == pytest.approx(500, abs=1)
    assert legs[1].eixo_m == pytest.approx(1000, abs=1)  # 1000 -> 1002 pela junção de 2 m
    assert legs[0].desvio_destino_m == pytest.approx(17, abs=2)  # B fica ao lado da via
    assert legs[0].reta_m == pytest.approx(float(haversine_m(_n(0), _LON0, _n(500), _LON0 + 0.0002)))


def test_station_too_far_from_the_axis_raises(tmp_path: Path) -> None:
    path = _write_kmz(tmp_path, _kml([_line(0, 100)], {"A": (_n(0), _LON0), "Longe": (_n(100), _LON0 + 0.01)}))
    pms = kmz.read_placemarks(path)
    with pytest.raises(kmz.KmzError, match="do eixo"):
        kmz.chain_distances(kmz.axis_graph(pms), kmz.stations(pms, "Paragens LH"), ("A", "Longe"))


def test_disconnected_axis_and_missing_station_raise(tmp_path: Path) -> None:
    path = _write_kmz(tmp_path, _kml([_line(0, 100), _line(500, 600)], {"A": (_n(0), _LON0), "B": (_n(600), _LON0)}))
    pms = kmz.read_placemarks(path)
    graph, points = kmz.axis_graph(pms), kmz.stations(pms, "Paragens LH")
    with pytest.raises(kmz.KmzError, match="não liga"):
        kmz.chain_distances(graph, points, ("A", "B"))
    with pytest.raises(kmz.KmzError, match="em falta"):
        kmz.chain_distances(graph, points, ("A", "Z"))


def test_plain_kml_and_repeated_station(tmp_path: Path) -> None:
    text = _kml([_line(0, 100)], {"A": (_n(0), _LON0)}).replace("</Folder></Folder>", "<Placemark><name>A</name><Point><coordinates>-8.4,40.2,0</coordinates></Point></Placemark></Folder></Folder>")
    path = tmp_path / "rede.kml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(kmz.KmzError, match="repetida"):
        kmz.stations(kmz.read_placemarks(path), "Paragens LH")


@pytest.mark.integration
def test_official_hospital_line() -> None:
    if not OFFICIAL_KMZ.exists():
        pytest.skip("KMZ oficial não disponível")
    legs = kmz.hospital_line_legs(OFFICIAL_KMZ)
    assert [l.origem for l in legs["subir"]][0] == "República (asc)" and legs["subir"][-1].destino == "Pediátrico"
    assert [l.destino for l in legs["descer"]][-1] == "República (desc)"
    for sense in ("subir", "descer"):
        total = sum(l.eixo_m for l in legs[sense])
        assert 2000 < total < 3500  # ~2,5-2,7 km
        for leg in legs[sense]:
            # Eixo nunca muito mais curto do que a reta (só pelo desvio das estações à via) nem absurdo.
            assert 0.8 * leg.reta_m < leg.eixo_m < 2.5 * leg.reta_m, leg
