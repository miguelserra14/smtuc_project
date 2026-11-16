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
