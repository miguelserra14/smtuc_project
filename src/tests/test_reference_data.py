"""Testes de tests/reference_data.py: os testes com valores fixos têm de SALTAR (não falhar) quando
os feeds GTFS mudam, e de continuar a correr quando só mudam as quebras de linha."""

from __future__ import annotations

from pathlib import Path

import pytest

import config
import tests.reference_data as ref


@pytest.fixture(autouse=True)
def _fake_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os feeds falsos "x"/"y" resolvem-se como os reais: config.DATASET_DIRS -> data/gtfs/<pasta>."""
    monkeypatch.setattr(config, "DATASET_DIRS", {**config.DATASET_DIRS, "x": "falso/x", "y": "falso/y"})


def _feed(root: Path, name: str, trips: bytes = b"route_id,service_id,trip_id\nR,WD,T1\n") -> Path:
    folder = root / config.GTFS_DIR / "falso" / name
    folder.mkdir(parents=True)
    (folder / "trips.txt").write_bytes(trips)
    (folder / "stops.txt").write_bytes(b"stop_id,stop_name\nA,Alfa\n")
    return folder


def test_fingerprint_ignores_line_endings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ref, "ROOT", tmp_path)
    folder = _feed(tmp_path, "x")
    lf = ref.dataset_fingerprint("x")
    (folder / "trips.txt").write_bytes((folder / "trips.txt").read_bytes().replace(b"\n", b"\r\n"))
    assert ref.dataset_fingerprint("x") == lf


def test_fingerprint_changes_with_content_and_missing_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ref, "ROOT", tmp_path)
    folder = _feed(tmp_path, "x")
    before = ref.dataset_fingerprint("x")
    (folder / "trips.txt").write_bytes(b"route_id,service_id,trip_id\nR,WD,T2\n")
    assert ref.dataset_fingerprint("x") != before
    assert ref.dataset_fingerprint("nao_existe") is None


def test_require_reference_data_skips_on_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ref, "ROOT", tmp_path)
    _feed(tmp_path, "x")
    monkeypatch.setattr(ref, "REFERENCE_FINGERPRINTS", {"x": ref.dataset_fingerprint("x")})
    ref.require_reference_data("x")  # igual -> não salta

    monkeypatch.setattr(ref, "REFERENCE_FINGERPRINTS", {"x": "0000000000000000"})
    with pytest.raises(pytest.skip.Exception, match="x: mudou"):
        ref.require_reference_data("x")
    with pytest.raises(pytest.skip.Exception, match="y: não existe"):
        ref.require_reference_data("y")


def test_current_repo_feeds_match_reference() -> None:
    """Sem isto, uma impressão digital mal copiada fazia TODOS os testes com valores fixos saltarem
    em silêncio. Salta (não falha) só se os dados do repositório mudaram de propósito."""
    if any(ref.dataset_fingerprint(d) is None for d in ref.REFERENCE_FINGERPRINTS):
        pytest.skip("dados GTFS não disponíveis")
    current = {d: ref.dataset_fingerprint(d) for d in ref.REFERENCE_FINGERPRINTS}
    if current != ref.REFERENCE_FINGERPRINTS:
        pytest.skip(f"feeds mudaram - rever testes com valores fixos e atualizar: {current}")
