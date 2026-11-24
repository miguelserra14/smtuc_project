"""gtfs.dataset_dir: fonte única do caminho de cada feed (config.DATASET_DIRS) - D1, passo 1."""

from __future__ import annotations

from pathlib import Path

import pytest

import config
from gtfs_processing import gtfs as gtfs_mod
from gtfs_processing.gtfs import _find_gtfs_dir, _looks_like_gtfs_folder, dataset_dir
# Importado aqui e não dentro dos testes: importar `overlap` com config.DATASET_DIRS trocado pelo
# fixture `fake` corre a validação de cenários de scenarios.py contra o mapa falso e rebenta (o
# teste só passava quando outro já tinha importado o módulo antes).
from overlap import overlap_db

_MIN_GTFS = {
    "agency.txt": "agency_id,agency_name\nA,Teste\n",
    "routes.txt": "route_id,route_short_name\nR,1\n",
    "trips.txt": "route_id,service_id,trip_id\nR,WD,T1\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS,Paragem,40.2,-8.4\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,08:00:00,08:00:00,S,1\n",
}


def _write_gtfs(folder: Path) -> None:
    folder.mkdir(parents=True)
    for name in gtfs_mod.REQUIRED_FILES:
        (folder / name).write_text(_MIN_GTFS.get(name, "x\n"), encoding="utf-8")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(config, "DATASET_DIRS", {"plano": "rede/plano", "aninhado": "rede/aninhado"})
    return tmp_path


def test_known_name_resolves_under_gtfs_dir(fake: Path) -> None:
    assert dataset_dir("plano", fake) == fake / config.GTFS_DIR / "rede" / "plano"


def test_unknown_name_raises_instead_of_guessing(fake: Path) -> None:
    with pytest.raises(KeyError, match="desconhecido"):
        dataset_dir("smtuc", fake)  # não está no mapa (falso) -> nunca cai em data/smtuc


def test_files_must_be_directly_in_the_folder(fake: Path) -> None:
    _write_gtfs(dataset_dir("plano", fake))
    assert _find_gtfs_dir("plano", fake) == dataset_dir("plano", fake)
    # Antes aceitava-se a 1ª subpasta com GTFS (ex.: um export guardado lá dentro).
    _write_gtfs(dataset_dir("aninhado", fake) / "export_antigo")
    with pytest.raises(FileNotFoundError, match="esperado em"):
        _find_gtfs_dir("aninhado", fake)


def test_cache_signature_reads_the_same_folder_as_the_loader(fake: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overlap_db, "_project_root", lambda: fake)
    folder = dataset_dir("plano", fake)
    _write_gtfs(folder)
    before = overlap_db._dataset_signature("plano")
    (folder / "trips.txt").write_text("route_id,service_id,trip_id\nR,WD,T1\nR,WD,T2\n", encoding="utf-8")
    assert overlap_db._dataset_signature("plano") != before
    nested = folder / "sub"
    nested.mkdir()
    after = overlap_db._dataset_signature("plano")
    (nested / "trips.txt").write_text("lixo\n", encoding="utf-8")
    assert overlap_db._dataset_signature("plano") == after  # subpastas não são lidas por ninguém


def test_cache_signature_depends_on_content_not_mtime(fake: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Antes era nome+tamanho+mtime: o OneDrive/git a tocar nos ficheiros invalidava a cache sem
    # nada ter mudado. Agora só o conteúdo conta (e CRLF == LF, como na impressão digital).
    import os

    from overlap import overlap_db

    monkeypatch.setattr(overlap_db, "_project_root", lambda: fake)
    folder = dataset_dir("plano", fake)
    _write_gtfs(folder)
    before = overlap_db._dataset_signature("plano")
    trips = folder / "trips.txt"
    stat = trips.stat()
    os.utime(trips, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert overlap_db._dataset_signature("plano") == before
    trips.write_bytes(trips.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert overlap_db._dataset_signature("plano") == before
    trips.write_bytes(trips.read_bytes() + b"R,WD,T9\r\n")
    assert overlap_db._dataset_signature("plano") != before


def test_real_datasets_exist_where_config_says() -> None:
    root = Path(__file__).resolve().parents[2]
    absent = []
    for name in config.DATASET_DIRS:
        folder = dataset_dir(name)
        assert folder == root / config.GTFS_DIR / config.DATASET_DIRS[name]
        # Pasta ausente, ou só com o PROVENANCE.json num clone (os .txt do SMTUC Ep225 estão fora do
        # git): não há nada a verificar nesta máquina - mas continua com os outros datasets.
        if not _looks_like_gtfs_folder(folder):
            absent.append(name)
            continue
        assert _find_gtfs_dir(name, root) == folder
    if len(absent) == len(config.DATASET_DIRS):
        pytest.skip(f"nenhum dataset GTFS nesta máquina: {absent}")
