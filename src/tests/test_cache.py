"""Testes da integridade do cache line_metrics_db.csv (passo 3.1 do roadmap): escrita atómica e
nunca gravar resultados parciais. A chave do cache (dia de referência, versão da fórmula, janela
de frequência) está em test_frequency.py."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import overlap.overlap as ov
from overlap import overlap_db as odb

MONDAY = date(2026, 5, 11)


@pytest.fixture
def fake_compute(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    calls: list[date] = []

    def _compute(**kwargs):
        calls.append(kwargs["reference_day"])
        return pd.DataFrame([{"line": "7", "avg_freq_min": 20.0, "ref_day_trips": 101}])

    monkeypatch.setattr(odb, "_compute_line_metrics", _compute)
    monkeypatch.setattr(ov, "compute_temporal_overlaps_for_db", lambda df, **kwargs: df)
    monkeypatch.setattr(odb, "_dataset_signature", lambda dataset: f"sig-{dataset}")
    return calls


def _leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


def test_atomic_write_replaces_file(tmp_path: Path) -> None:
    target = tmp_path / "m.csv"
    target.write_text("antigo\n", encoding="utf-8")
    odb._atomic_write_csv(pd.DataFrame({"a": [1, 2]}), target)
    assert target.read_text(encoding="utf-8").splitlines() == ["a", "1", "2"]
    assert _leftovers(tmp_path) == []


def test_atomic_write_interrupted_keeps_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "m.csv"
    target.write_text("line,avg_freq_min\n7,20.0\n", encoding="utf-8")
    before = target.read_bytes()

    def _partial_then_crash(self, path, **kwargs):
        Path(path).write_text("line,avg_fr", encoding="utf-8")  # meio ficheiro...
        raise KeyboardInterrupt("interrompido a meio da escrita")

    monkeypatch.setattr(pd.DataFrame, "to_csv", _partial_then_crash)
    with pytest.raises(KeyboardInterrupt):
        odb._atomic_write_csv(pd.DataFrame({"line": ["9"]}), target)
    assert target.read_bytes() == before  # o cache anterior continua inteiro
    assert _leftovers(tmp_path) == []  # e o temporário foi limpo


def test_temporal_failure_writes_nothing(tmp_path: Path, fake_compute: list[date], monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(df, **kwargs):
        raise ValueError("falha simulada no overlap temporal")

    monkeypatch.setattr(ov, "compute_temporal_overlaps_for_db", _boom)
    db = tmp_path / "m.csv"
    with pytest.raises(RuntimeError, match="NÃO foi gravado"):
        odb.build_line_metrics_db(db_path=str(db), reference_day=MONDAY)
    assert not db.exists()  # antes: gravava o CSV com zeros e ficava em cache
    assert _leftovers(tmp_path) == []


def test_temporal_failure_keeps_previous_cache(tmp_path: Path, fake_compute: list[date], monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "m.csv"
    odb.build_line_metrics_db(db_path=str(db), reference_day=MONDAY)
    before = db.read_bytes()

    def _boom(df, **kwargs):
        raise ValueError("falha simulada")

    monkeypatch.setattr(ov, "compute_temporal_overlaps_for_db", _boom)
    with pytest.raises(RuntimeError):
        # Outro dia -> o cache não serve e tenta recalcular; a falha não pode estragar o CSV.
        odb.build_line_metrics_db(db_path=str(db), reference_day=date(2026, 5, 12))
    assert db.read_bytes() == before


def test_successful_build_leaves_no_temp_files(tmp_path: Path, fake_compute: list[date]) -> None:
    odb.build_line_metrics_db(db_path=str(tmp_path / "m.csv"), reference_day=MONDAY)
    assert _leftovers(tmp_path) == []
    assert (tmp_path / "m.csv").exists()
