"""Testes de scripts/build_feeds.py (D1, passo 3) num zip GTFS sintético em tmp_path: cada
transformação faz o que diz (e falha se o feed não for o esperado), o resultado é determinístico,
o ficheiro bruto é conferido com o MANIFEST e uma pasta construída nunca é sobrescrita."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_feeds", ROOT / "scripts" / "build_feeds.py")
bf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bf
_spec.loader.exec_module(bf)

BOM = "﻿"


def _zip(short: str = "Serpins - Portagem", end: str = "20251231", pc: bool = True) -> bytes:
    files = {
        "agency.txt": "agency_id,agency_name\n1,Metro Mondego\n",
        "routes.txt": f"route_id,agency_id,route_short_name,route_long_name,route_type\n3606,1,{short},S1,3\n",
        "calendar.txt": f"service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n3,1,1,1,1,1,0,0,20251101,{end}\n",
        "calendar_dates.txt": "",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n1,Portagem,40.2075,-8.4306\n2,Parque,40.2037,-8.4251\n"
                     + ("9,PC1,40.20,-8.42\n" if pc else ""),
        "trips.txt": "route_id,service_id,trip_id,direction_id\n3606,3,T1,0\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,08:00:00,08:00:00,1,1\n"
                          + ("T1,08:01:00,08:01:00,9,2\n" if pc else "") + "T1,08:03:00,08:03:00,2,3\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, (BOM + text.replace("\n", "\r\n")).encode("utf-8"))  # como o oficial
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw, gtfs = tmp_path / "raw", tmp_path / "gtfs"
    monkeypatch.setattr(bf, "RAW_DIR", raw)
    monkeypatch.setattr(bf, "GTFS_DIR", gtfs)

    def put_raw(data: bytes, manifest_sha: str | None = None) -> bf.Build:
        rel = "dados-gov/metro-mondego-gtfs/v1/feed.zip"
        (raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (raw / rel).write_bytes(data)
        with open(raw / "MANIFEST.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["ficheiro", "estado", "sha256", "versao", "url", "verificacoes"])
            w.writeheader()
            w.writerow({"ficheiro": rel, "estado": "novo", "sha256": manifest_sha or hashlib.sha256(data).hexdigest(),
                        "versao": "v1", "url": "https://exemplo/feed.zip", "verificacoes": "teste"})
        return bf.Build(target="metro/teste", raw=rel, descricao="teste", steps=bf.BUILDS[0].steps)

    return put_raw, gtfs / "metro" / "teste"


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_build_applies_each_transformation_and_records_it(env) -> None:
    put_raw, target = env
    assert bf.run_build(put_raw(_zip())) == "construido"
    assert [s["stop_name"] for s in _rows(target / "stops.txt")] == ["Portagem", "Parque"]
    assert [r["stop_id"] for r in _rows(target / "stop_times.txt")] == ["1", "2"]
    assert _rows(target / "calendar.txt")[0]["end_date"] == "20260909"
    route = _rows(target / "routes.txt")[0]
    assert (route["route_short_name"], route["route_long_name"]) == ("S1", "Serpins - Portagem")
    assert (target / "calendar_dates.txt").read_text(encoding="utf-8") == "service_id,date,exception_type\n"
    for p in target.glob("*.txt"):
        data = p.read_bytes()
        assert not data.startswith(BOM.encode()) and b"\r\n" not in data, p.name  # UTF-8 sem BOM, LF
    prov = json.loads((target / "PROVENANCE.json").read_text(encoding="utf-8"))
    steps = {s["passo"]: s for s in prov["transformacoes"]}
    assert steps["remover paragens técnicas"]["paragens_removidas"] == ["PC1"]
    assert steps["remover paragens técnicas"]["passagens_removidas"] == 1
    assert prov["ignorados_do_zip"] == ["[Content_Types].xml"]
    assert prov["ficheiros"]["stops.txt"] == hashlib.sha256((target / "stops.txt").read_bytes()).hexdigest()


def test_checkout_with_crlf_still_matches_provenance(env) -> None:
    """core.autocrlf=true: o git devolve os .txt com CRLF - o feed continua a ser "igual"."""
    put_raw, target = env
    build = put_raw(_zip())
    bf.run_build(build)
    for p in target.glob("*.txt"):
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert bf.run_build(build, verify_only=True) == "igual"


def test_rebuild_is_idempotent_and_verify_passes(env) -> None:
    put_raw, _ = env
    build = put_raw(_zip())
    assert bf.run_build(build) == "construido"
    assert bf.run_build(build) == "igual"
    assert bf.run_build(build, verify_only=True) == "igual"


def test_built_folder_is_never_overwritten(env) -> None:
    put_raw, target = env
    build = put_raw(_zip())
    bf.run_build(build)
    (target / "stops.txt").write_text("stop_id,stop_name\n1,Mexido\n", encoding="utf-8")
    with pytest.raises(bf.BuildError, match="difere"):
        bf.run_build(build)
    assert (target / "stops.txt").read_text(encoding="utf-8") == "stop_id,stop_name\n1,Mexido\n"


def test_verify_only_never_builds(env) -> None:
    put_raw, target = env
    with pytest.raises(bf.BuildError, match="não existe"):
        bf.run_build(put_raw(_zip()), verify_only=True)
    assert not target.exists()


@pytest.mark.parametrize(
    "kwargs, message",
    [({"short": "S1"}, "routes.txt"), ({"end": "20251130"}, "calendar.txt"), ({"pc": False}, "nenhuma paragem")],
)
def test_transformations_refuse_an_unexpected_feed(env, kwargs: dict, message: str) -> None:
    put_raw, target = env
    with pytest.raises(bf.BuildError, match=message):
        bf.run_build(put_raw(_zip(**kwargs)))
    assert not target.exists()  # falha no build = nada gravado (o build corre numa pasta temporária)


def test_raw_file_must_match_the_manifest(env) -> None:
    put_raw, target = env
    with pytest.raises(bf.BuildError, match="MANIFEST"):
        bf.run_build(put_raw(_zip(), manifest_sha="0" * 64))
    assert not target.exists()


def test_real_build_definitions_point_to_registered_raw_files() -> None:
    with open(ROOT / "data" / "raw" / "MANIFEST.csv", encoding="utf-8", newline="") as fh:
        registered = {r["ficheiro"] for r in csv.DictReader(fh) if r["estado"] == "novo"}
    import config

    targets = set(config.DATASET_DIRS.values())
    for b in bf.BUILDS:
        assert b.raw in registered, b.raw
        assert b.target in targets, f"{b.target} construído mas não está em config.DATASET_DIRS"


# --------------------------------------------------------------------------- Linha do Hospital (N3.2)

_DEG = 111_195.0  # metros por grau de latitude (haversine)
_HOSPITAL_KMZ_STATIONS = {  # nome no KMZ -> metros para norte (todas no eixo, exceto o desvio de 10 m da desc)
    "Loja de Cidadão": 0, "Câmara": 400, "Mercado": 800, "República (asc)": 1200, "República (desc)": 1200,
    "Sereia (asc)": 1700, "Sereia (desc)": 1700, "Celas": 2200, "Polo Ciências da Saúde": 2700,
    "Hospitais (H.U.C.)": 3000, "Pediátrico": 3500,
}


def _lat(m: float) -> float:
    return 40.2 + m / _DEG


def _hospital_kmz() -> bytes:
    axis = " ".join(f"-8.4,{_lat(m)},0" for m in range(0, 3501, 100))
    pts = "".join(f"<Placemark><name>{n}</name><Point><coordinates>-8.4,{_lat(m)},0</coordinates></Point></Placemark>"
                  for n, m in _HOSPITAL_KMZ_STATIONS.items())
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<Folder><name>Eixo LH</name><Placemark><name>eixo</name><LineString><coordinates>{axis}</coordinates>"
           f"</LineString></Placemark></Folder><Folder><name>Paragens LH</name>{pts}</Folder></Document></kml>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.kml", kml)
    return buf.getvalue()


def _hospital_feed() -> dict:
    stops = [("1", "Loja do Cidadão", 0), ("2", "Câmara (asc)", 400), ("3", "Mercado (asc)", 800),
             ("4", "República (asc)", 1200), ("5", "República (desc)", 1200), ("6", "Mercado (desc)", 800)]
    st_cols = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence", "pickup_type", "drop_off_type"]
    st = []

    def trip(tid: str, ids: list[str], start_min: int) -> None:
        for k, sid in enumerate(ids):
            t = f"08:{start_min + 2 * k:02d}:00"  # 2 min entre paragens
            st.append({"trip_id": tid, "arrival_time": t, "departure_time": t, "stop_id": sid, "stop_sequence": str(k + 1),
                       "pickup_type": "1" if k == len(ids) - 1 else "0", "drop_off_type": "1" if k == 0 else "0"})

    for tid, start in (("t1", 0), ("t2", 10), ("t3", 20)):
        trip(tid, ["1", "2", "3", "4"], start)          # U2 a subir: acaba na República (asc)
    trip("t4", ["5", "6", "1"], 30)                      # U2 a descer: parte da República (desc)
    trip("t9", ["1", "2", "3", "4"], 40)                 # outra linha: fica igual
    return {
        "stops.txt": (["stop_id", "stop_name", "stop_lat", "stop_lon"],
                      [{"stop_id": i, "stop_name": n, "stop_lat": f"{_lat(m):.6f}", "stop_lon": "-8.4"} for i, n, m in stops]),
        "routes.txt": (["route_id", "route_short_name"], [{"route_id": "r2", "route_short_name": "U2"},
                                                          {"route_id": "r9", "route_short_name": "X"}]),
        "trips.txt": (["route_id", "trip_id"], [{"route_id": "r9" if t == "t9" else "r2", "trip_id": t}
                                                for t in ("t1", "t2", "t3", "t4", "t9")]),
        "stop_times.txt": (st_cols, st),
    }


@pytest.fixture
def hospital_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    raw = tmp_path / "raw"
    monkeypatch.setattr(bf, "RAW_DIR", raw)
    rel = "dados-gov/metro-mondego-kmz/v1/rede.kmz"
    data = _hospital_kmz()
    (raw / rel).parent.mkdir(parents=True, exist_ok=True)
    (raw / rel).write_bytes(data)
    with open(raw / "MANIFEST.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ficheiro", "estado", "sha256", "versao", "url", "verificacoes"])
        w.writeheader()
        w.writerow({"ficheiro": rel, "estado": "novo", "sha256": hashlib.sha256(data).hexdigest(),
                    "versao": "v1", "url": "https://exemplo/rede.kmz", "verificacoes": "teste"})
    return rel


def _by_trip(feed: dict) -> dict[str, list[dict]]:
    names = {r["stop_id"]: r["stop_name"] for r in feed["stops.txt"][1]}
    out: dict[str, list[dict]] = {}
    for r in feed["stop_times.txt"][1]:
        out.setdefault(r["trip_id"], []).append({**r, "nome": names[r["stop_id"]]})
    return {t: sorted(rows, key=lambda r: int(r["stop_sequence"])) for t, rows in out.items()}


def test_extend_to_hospital_all_trips(hospital_env: str) -> None:
    feed = _hospital_feed()
    report = bf.extend_to_hospital(hospital_env, ("U2",), 1, "teste")(feed)
    trips = _by_trip(feed)
    up = trips["t1"]
    assert [r["nome"] for r in up][-6:] == ["República (asc)", "Sereia (asc)", "Celas", "Polo Ciências da Saúde",
                                           "Hospitais (H.U.C.)", "Pediátrico"]
    # Velocidade de referência: Loja -> República = 1200 m em 6 min = 200 m/min; 2300 m -> 11,5 min.
    assert up[3]["arrival_time"] == "08:06:00" and up[-1]["arrival_time"] == "08:17:30"
    assert (up[3]["pickup_type"], up[-1]["pickup_type"]) == ("0", "1")  # a República deixa de ser o fim
    down = trips["t4"]
    assert [r["nome"] for r in down][:2] == ["Pediátrico", "Hospitais (H.U.C.)"]
    assert down[0]["drop_off_type"] == "1" and down[5]["nome"] == "República (desc)" and down[5]["drop_off_type"] == "0"
    assert [int(r["stop_sequence"]) for r in down] == list(range(1, len(down) + 1))
    assert down[0]["departure_time"] < down[5]["departure_time"] == "08:30:00"
    assert [r["nome"] for r in trips["t9"]][-1] == "República (asc)"  # outra linha não muda
    assert report["viagens_prolongadas"] == {"U2 descer": "1/1", "U2 subir": "3/3"}
    assert report["velocidade_referencia"]["subir"]["km_h"] == 12.0
    assert len([s for s in feed["stops.txt"][1] if s["stop_id"].startswith("LH")]) == 6


def test_extend_to_hospital_every_other_trip(hospital_env: str) -> None:
    feed = _hospital_feed()
    report = bf.extend_to_hospital(hospital_env, ("U2",), 2, "teste")(feed)
    ends = {t: rows[-1]["nome"] for t, rows in _by_trip(feed).items()}
    assert (ends["t1"], ends["t2"], ends["t3"]) == ("Pediátrico", "República (asc)", "Pediátrico")  # 1.ª, 3.ª
    assert report["viagens_prolongadas"]["U2 subir"] == "2/3"


def test_extend_to_hospital_refuses_unknown_lines_and_a_changed_kmz(hospital_env: str) -> None:
    with pytest.raises(bf.BuildError, match="não existem"):
        bf.extend_to_hospital(hospital_env, ("U2", "Z9"), 1, "teste")(_hospital_feed())
    (bf.RAW_DIR / hospital_env).write_bytes(b"mexido")
    with pytest.raises(bf.BuildError, match="MANIFEST"):
        bf.extend_to_hospital(hospital_env, ("U2",), 1, "teste")(_hospital_feed())
