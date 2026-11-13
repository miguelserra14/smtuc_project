"""Configuração partilhada dos testes.

Guarda de outputs/ (passo 6.2 do roadmap): outputs/ tem os ficheiros PUBLICADOS (dashboards,
CSVs, cache de métricas). Os testes têm de escrever só em pastas temporárias (tmp_path); antes,
cada corrida da suite reescrevia bgri.html, overlap_reachability_now.html e
bgri_transport_gap.csv - o que estragava as comparações de números entre fases e arriscava
commits acidentais de ficheiros gerados por testes. Se algum teste criar, alterar ou apagar um
ficheiro em outputs/, a sessão termina com falha e a lista do que mudou.
"""

from __future__ import annotations

from pathlib import Path

import pytest

OUTPUTS = Path(__file__).resolve().parents[2] / "outputs"
_SNAPSHOT_KEY = pytest.StashKey[dict[str, tuple[int, int]]]()


def _snapshot() -> dict[str, tuple[int, int]]:
    if not OUTPUTS.exists():
        return {}
    return {
        p.relative_to(OUTPUTS).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in OUTPUTS.rglob("*")
        if p.is_file()
    }


def pytest_sessionstart(session: pytest.Session) -> None:
    session.stash[_SNAPSHOT_KEY] = _snapshot()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.stash.get(_SNAPSHOT_KEY, None)
    if before is None:
        return
    after = _snapshot()
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    if not (created or deleted or modified):
        return
    lines = ["", "[ERRO] Os testes alteraram outputs/ (devem escrever só em tmp_path):"]
    for label, items in (("criados", created), ("alterados", modified), ("apagados", deleted)):
        lines += [f"  {label}: {item}" for item in items]
    lines.append("  -> repor com: git checkout -- outputs  (e corrigir o teste)")
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    for line in lines:
        (terminal.write_line(line, red=True) if terminal else print(line))
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
