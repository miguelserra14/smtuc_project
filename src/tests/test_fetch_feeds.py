"""Testes de scripts/fetch_feeds.py (D0.3) com uma rede FALSA em memória - nenhum teste vai à
internet nem escreve fora de tmp_path. Cobrem as 4 verificações (transporte, identidade, conteúdo,
semântica), a imutabilidade de data/raw e o manifest."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fetch_feeds", ROOT / "scripts" / "fetch_feeds.py")
ff = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ff  # dataclasses precisam do módulo registado
_spec.loader.exec_module(ff)

AGIT_ID = "urn:agit:Dataset:metro-mondego"
NETEX_VAL = f"{ff.AGIT_API.format(dataset='metro-mondego')}/validation"
NETEX_DL = f"{ff.AGIT_API.format(dataset='metro-mondego')}/download"


# --------------------------------------------------------------------------- dados sintéticos


def netex_zip(stamp: str = "2026-11-11T15:14:47Z", journeys: int = 2, identifier: str = AGIT_ID, modified: str = "2026-11-11") -> bytes:
    sj = "".join(f"<ServiceJourney id='sj{i}'><passingTimes><TimetabledPassingTime/><TimetabledPassingTime/></passingTimes></ServiceJourney>" for i in range(journeys))
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>\n<PublicationDelivery xmlns='http://www.netex.org.uk/netex'>\n"
        f"  <PublicationTimestamp>{stamp}</PublicationTimestamp>\n"
        "  <dataObjects><Operator/><StopPlace><quays><Quay/></quays></StopPlace><ScheduledStopPoint/>"
        f"<Line/><Route/><ServiceJourneyPattern/><ServiceCalendar/><DayType/>{sj}</dataObjects>\n"
        "</PublicationDelivery>\n"
    )
    meta = {"dcterms:identifier": identifier, "dcterms:modified": {"@value": modified},
            "dcterms:temporal": {"dcat:startDate": {"@value": "2026-06-10"}, "dcat:endDate": {"@value": "2026-12-31"}}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.jsonld", json.dumps(meta))
        zf.writestr("netex.xml", xml)
    return buf.getvalue()


def validation_for(data: bytes, origin: str = "o1", journeys: int | None = None, release: str = "R1") -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml_sha = hashlib.sha256(zf.read("netex.xml")).hexdigest()
        meta_sha = hashlib.sha256(zf.read("metadata.jsonld")).hexdigest()
        n = journeys if journeys is not None else zf.read("netex.xml").count(b"<ServiceJourney ")
    return {
        "status": "valid",
        "source": {"releaseId": release, "sha256": origin},
        "artifact": {"sha256": hashlib.sha256(data).hexdigest(), "xmlSha256": xml_sha, "generatedAt": "2026-11-11T15:14:47.79+00:00",
                     "metadata": {"filename": "metadata.jsonld", "sha256": meta_sha}},
        "counts": {
            "netex": {"operators": 1, "stopPlaces": 1, "quays": 1, "scheduledStopPoints": 1, "lines": 1, "routeVariants": 1,
                      "journeyPatterns": 1, "serviceJourneys": n, "passingTimes": 2 * n, "serviceCalendars": 1, "dayTypes": 1},
            "gtfs": {"stops": 1, "trips": n},
        },
    }


def gtfs_zip(agency: str = "Metro Mondego", trips: int = 2) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("agency.txt", f"agency_id,agency_name\nMM,{agency}\n")
        zf.writestr("routes.txt", "route_id,route_short_name\n3606,MM\n")
        zf.writestr("trips.txt", "route_id,service_id,trip_id\n" + "".join(f"3606,3,T{i}\n" for i in range(trips)))
        zf.writestr("stop_times.txt", "trip_id,stop_id,stop_sequence\nT0,A,1\n")
        zf.writestr("stops.txt", "stop_id,stop_name\nA,Portagem\n")
        zf.writestr("calendar.txt", "service_id,start_date,end_date\n3,20251101,20251231\n")
    return buf.getvalue()


def catalog(url: str, data: bytes, title: str | None = None, sha1: str | None = None, extra: list | None = None) -> dict:
    res = {"title": title or url.rsplit("/", 1)[-1], "url": url, "filesize": len(data),
           "checksum": {"type": "sha1", "value": sha1 or hashlib.sha1(data).hexdigest()}}
    return {"resources": [res, *(extra or [])]}


class FakeHttp:
    def __init__(self, json_map: dict | None = None, files: dict | None = None) -> None:
        self.json_map, self.files, self.downloads = dict(json_map or {}), dict(files or {}), []

    def get_json(self, url: str) -> dict:
        if url not in self.json_map:
            raise OSError(f"404 {url}")
        return self.json_map[url]

    def download(self, url: str, dest: Path) -> None:
        self.downloads.append(url)
        if url not in self.files:
            raise OSError(f"404 {url}")
        dest.write_bytes(self.files[url])


SRC_API = next(s for s in ff.SOURCES if s.id == "agit/metro-mondego-netex")
SRC_MIRROR = next(s for s in ff.SOURCES if s.id == "dados-gov/metro-mondego-netex")
SRC_GTFS = next(s for s in ff.SOURCES if s.id == "dados-gov/metro-mondego-gtfs")


def api_http(data: bytes, **kw) -> FakeHttp:
    return FakeHttp({NETEX_VAL: validation_for(data, **kw)}, {NETEX_DL: data})


def manifest(raw: Path) -> list[dict[str, str]]:
    return ff.read_manifest(raw)


def stored_files(raw: Path) -> list[str]:
    return sorted(p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file() and p.name != "MANIFEST.csv")


# --------------------------------------------------------------------------- API AGIT


def test_new_api_version_is_verified_stored_read_only_and_registered(tmp_path: Path) -> None:
    data = netex_zip()
    r = ff.process_source(SRC_API, api_http(data), tmp_path)
    assert r.status == "novo"
    files = stored_files(tmp_path)
    assert len(files) == 2 and files[0].endswith("/metro-mondego-netex.zip") and files[1].endswith("/validation.json")
    zpath = tmp_path / files[0]
    assert zpath.read_bytes() == data
    assert b"
" not in (tmp_path / files[1]).read_bytes()  # bytes iguais em qualquer sistema
    assert not os.access(zpath, os.W_OK)  # só de leitura
    (row,) = manifest(tmp_path)
    assert row["estado"] == "novo" and row["identificador"] == AGIT_ID and row["valido_ate"] == "2026-12-31"
    assert row["verificacoes"] == "sha256=validacao;identidade;membros=validacao;contagens=validacao"
    assert json.loads(row["contagens"])["serviceJourneys"] == 2
    assert not list(tmp_path.rglob("*.part"))


def test_same_release_is_not_downloaded_again(tmp_path: Path) -> None:
    data = netex_zip()
    ff.process_source(SRC_API, api_http(data), tmp_path)
    http = api_http(data)
    assert ff.process_source(SRC_API, http, tmp_path).status == "sem_alteracoes"
    assert http.downloads == [] and len(manifest(tmp_path)) == 1


def test_regenerated_file_with_same_origin_is_registered_without_download(tmp_path: Path) -> None:
    ff.process_source(SRC_API, api_http(netex_zip(stamp="2026-10-21T01:26:15Z")), tmp_path)
    regenerated = netex_zip(stamp="2026-11-11T15:14:47Z")  # mesmo GTFS de origem, só muda o timestamp
    http = api_http(regenerated)
    r = ff.process_source(SRC_API, http, tmp_path)
    assert r.status == "igual" and http.downloads == []
    rows = manifest(tmp_path)
    assert [x["estado"] for x in rows] == ["novo", "igual"] and rows[1]["igual_a"] == f"{SRC_API.id}/{rows[0]['versao']}"
    assert len(stored_files(tmp_path)) == 2  # nenhuma cópia nova


def test_new_origin_with_identical_content_is_not_stored_twice(tmp_path: Path) -> None:
    ff.process_source(SRC_API, api_http(netex_zip(stamp="A"), origin="o1"), tmp_path)
    r = ff.process_source(SRC_API, api_http(netex_zip(stamp="B"), origin="o2"), tmp_path)
    assert r.status == "igual"  # descarregado, mas o conteúdo (sem PublicationTimestamp) é o mesmo
    assert len(stored_files(tmp_path)) == 2


def test_real_content_change_is_a_new_version(tmp_path: Path) -> None:
    ff.process_source(SRC_API, api_http(netex_zip(journeys=2), origin="o1"), tmp_path)
    r = ff.process_source(SRC_API, api_http(netex_zip(journeys=3), origin="o2"), tmp_path)
    assert r.status == "novo"
    assert [x["estado"] for x in manifest(tmp_path)] == ["novo", "novo"]


@pytest.mark.parametrize(
    "breakage, message",
    [
        ("transporte", "transporte"),
        ("contagens", "semântica"),
        ("identidade", "identidade"),
        ("xml", "netex.xml"),
        ("estado", "estado"),
    ],
)
def test_any_failed_check_stores_nothing(tmp_path: Path, breakage: str, message: str) -> None:
    data = netex_zip(identifier="urn:agit:Dataset:outro" if breakage == "identidade" else AGIT_ID)
    val = validation_for(data, journeys=5 if breakage == "contagens" else None)
    if breakage == "transporte":
        val["artifact"]["sha256"] = "0" * 64
    if breakage == "xml":
        val["artifact"]["xmlSha256"] = "0" * 64
    if breakage == "estado":
        val["status"] = "invalid"
    with pytest.raises(ff.FetchError, match=message):
        ff.process_source(SRC_API, FakeHttp({NETEX_VAL: val}, {NETEX_DL: data}), tmp_path)
    assert stored_files(tmp_path) == [] and manifest(tmp_path) == []
    assert not list(tmp_path.rglob("*")) or all(p.is_dir() for p in tmp_path.rglob("*"))


def test_dry_run_downloads_and_writes_nothing(tmp_path: Path) -> None:
    http = api_http(netex_zip())
    assert ff.process_source(SRC_API, http, tmp_path, dry_run=True).status == "seria_descarregado"
    assert http.downloads == [] and not tmp_path.joinpath("MANIFEST.csv").exists()


# --------------------------------------------------------------------------- catálogo dados.gov.pt


def _mirror_url(name: str, version: str = "20261024-200518-b5d28613", slug: str = "metro-mondego") -> str:
    return f"https://dados.gov.pt/s/resources/{slug}/{version}/{name}"


def test_catalog_gtfs_checks_sha1_operator_and_uses_url_version(tmp_path: Path) -> None:
    data = gtfs_zip()
    url = _mirror_url("20251219-export-gtfs.zip", "20260817-153951-d08309cb")
    http = FakeHttp({ff.CATALOG_API.format(slug="metro-mondego"): catalog(url, data)}, {url: data})
    assert ff.process_source(SRC_GTFS, http, tmp_path).status == "novo"
    (row,) = manifest(tmp_path)
    assert row["versao"] == "20260817-153951-d08309cb" and row["valido_de"] == "20251101" and row["valido_ate"] == "20251231"
    assert json.loads(row["contagens"])["trips"] == 2
    assert ff.process_source(SRC_GTFS, http, tmp_path).status == "sem_alteracoes"
    assert len(http.downloads) == 1


def test_catalog_rejects_wrong_sha1_wrong_operator_and_ambiguous_resources(tmp_path: Path) -> None:
    data = gtfs_zip()
    url = _mirror_url("20251219-export-gtfs.zip")
    cat = ff.CATALOG_API.format(slug="metro-mondego")
    with pytest.raises(ff.FetchError, match="transporte"):
        ff.process_source(SRC_GTFS, FakeHttp({cat: catalog(url, data, sha1="0" * 40)}, {url: data}), tmp_path)
    bad = gtfs_zip(agency="Outra Empresa")
    with pytest.raises(ff.FetchError, match="identidade"):
        ff.process_source(SRC_GTFS, FakeHttp({cat: catalog(url, bad)}, {url: bad}), tmp_path)
    two = catalog(url, data, extra=[{"title": "x-export-gtfs.zip", "url": url, "filesize": 1, "checksum": {"type": "sha1", "value": "a"}}])
    with pytest.raises(ff.FetchError, match="2 recursos"):
        ff.process_source(SRC_GTFS, FakeHttp({cat: two}, {url: data}), tmp_path)
    no_sum = {"resources": [{"title": "20251219-export-gtfs.zip", "url": url, "filesize": len(data), "checksum": None}]}
    with pytest.raises(ff.FetchError, match="não é verificável"):
        ff.process_source(SRC_GTFS, FakeHttp({cat: no_sum}, {url: data}), tmp_path)
    assert stored_files(tmp_path) == [] and manifest(tmp_path) == []


def test_mirror_with_same_content_as_api_is_not_stored_twice(tmp_path: Path) -> None:
    ff.process_source(SRC_API, api_http(netex_zip(stamp="2026-11-11")), tmp_path)
    mirror = netex_zip(stamp="2026-10-21", modified="2026-10-21")  # outra publicação, mesmos dados
    url = _mirror_url("metro-mondego-netex.zip", slug="metro-mondego-netex")
    http = FakeHttp({ff.CATALOG_API.format(slug="metro-mondego-netex"): catalog(url, mirror)}, {url: mirror})
    r = ff.process_source(SRC_MIRROR, http, tmp_path)
    assert r.status == "igual" and SRC_API.id in r.detail
    assert len(stored_files(tmp_path)) == 2


# --------------------------------------------------------------------------- manifest, imutabilidade, CLI


def test_store_never_overwrites(tmp_path: Path) -> None:
    final = tmp_path / "a" / "f.zip"
    part = tmp_path / "p"
    part.write_bytes(b"1")
    ff._store(part, final)
    part.write_bytes(b"2")
    with pytest.raises(ff.FetchError, match="imutável"):
        ff._store(part, final)
    assert final.read_bytes() == b"1"


def test_manifest_only_grows(tmp_path: Path) -> None:
    for i in range(3):
        ff.append_manifest(tmp_path, {"fonte": "x", "versao": str(i), "estado": "novo"})
    rows = manifest(tmp_path)
    assert [r["versao"] for r in rows] == ["0", "1", "2"]
    with open(tmp_path / "MANIFEST.csv", encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == ff.MANIFEST_COLUMNS


def test_register_manual_file(tmp_path: Path) -> None:
    raw, src = tmp_path / "raw", tmp_path / "horario.pdf"
    src.write_bytes(b"%PDF-1.4 teste")
    final = ff.register_manual(src, "manual/metro-mondego-pdf", "2026-09-06", raw, move=True)
    assert final == raw / "manual/metro-mondego-pdf/2026-09-06/horario.pdf" and not src.exists()
    assert not os.access(final, os.W_OK)
    src.write_bytes(b"%PDF-1.4 teste")
    with pytest.raises(ff.FetchError, match="já está registado"):
        ff.register_manual(src, "manual/metro-mondego-pdf", "2026-09-07", raw)
    with pytest.raises(ff.FetchError, match="manual/"):
        ff.register_manual(src, "agit/x", "v1", raw)


def test_main_reports_failures_but_processes_other_sources(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    data = netex_zip()
    http = api_http(data)  # o catálogo do GTFS não existe -> essa fonte falha
    code = ff.main(["--raw", str(tmp_path), "--fontes", f"{SRC_GTFS.id},{SRC_API.id}"], http=http)
    out = capsys.readouterr().out
    assert code == 1 and "[falhou" in out and "[novo" in out
    assert [r["fonte"] for r in manifest(tmp_path)] == [SRC_API.id]


def test_sources_are_consistent() -> None:
    ids = [s.id for s in ff.SOURCES]
    assert len(ids) == len(set(ids))
    for s in ff.SOURCES:
        assert s.kind in ("agit", "agit_validacao", "catalogo") and s.fmt in ("netex", "gtfs", "outro")
        assert s.id.split("/")[0] in ("agit", "dados-gov", "municipio-coimbra")
        if s.fmt == "netex":
            assert s.identifier.startswith("urn:agit:Dataset:")
        if s.fmt == "gtfs":
            assert s.operator
        if s.mesmo_conteudo:
            assert s.mesmo_conteudo in ids
    # Fontes não versionadas têm de estar no .gitignore (licença do GTFS do Município).
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for s in ff.SOURCES:
        if not s.versionar:
            assert f"data/raw/{s.id}/" in gitignore
