"""O guarda das pastas do projeto (conftest.py, auditoria de 2026-11-28): deteta criar, alterar e
apagar, teste a teste. Pastas temporárias no lugar de outputs/, reports/ e data/."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests import conftest as guard


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("outputs", "reports", "data"):
        (tmp_path / name / "sub").mkdir(parents=True)
    (tmp_path / "outputs" / "a.html").write_text("a", encoding="utf-8")
    (tmp_path / "data" / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "outputs" / "__pycache__").mkdir()
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "GUARDED", tuple(tmp_path / n for n in ("outputs", "reports", "data")))
    return tmp_path


def test_guard_sees_every_guarded_folder(folders: Path) -> None:
    assert set(guard.snapshot_guarded()) == {"outputs/a.html", "data/sub/b.txt"}


def test_guard_reports_created_changed_and_deleted(folders: Path) -> None:
    before = guard.snapshot_guarded()
    assert guard.guard_message(before, guard.snapshot_guarded()) is None
    (folders / "reports" / "novo.csv").write_text("x", encoding="utf-8")
    (folders / "outputs" / "a.html").write_text("mudou", encoding="utf-8")
    (folders / "data" / "sub" / "b.txt").unlink()
    (folders / "outputs" / "__pycache__" / "x.pyc").write_bytes(b"")  # ignorado
    message = guard.guard_message(before, guard.snapshot_guarded())
    assert "criado: reports/novo.csv" in message
    assert "alterado: outputs/a.html" in message
    assert "apagado: data/sub/b.txt" in message
    assert "__pycache__" not in message


def test_guard_sees_a_rewrite_with_the_same_size(folders: Path) -> None:
    # Reescrever com o mesmo conteúdo também conta (foi assim que o N2.5 passou despercebido no git).
    before = guard.snapshot_guarded()
    path = folders / "outputs" / "a.html"
    st = path.stat()
    path.write_text("a", encoding="utf-8")
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert "alterado: outputs/a.html" in guard.guard_message(before, guard.snapshot_guarded())


def test_real_guard_watches_the_project_folders() -> None:
    root = Path(__file__).resolve().parents[2]
    assert {p.relative_to(root).as_posix() for p in guard.GUARDED} == {"outputs", "reports", "data"}
