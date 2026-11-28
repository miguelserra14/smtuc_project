"""Configuração partilhada dos testes.

Guarda das pastas do projeto (passo 6.2 do roadmap; teste a teste desde a auditoria de
2026-11-28). outputs/ tem os ficheiros PUBLICADOS (dashboards, CSVs, cache de métricas),
reports/ os registos de métricas (linhas de base) e data/ os dados brutos e os feeds construídos.
Os testes têm de escrever só em pastas temporárias (tmp_path).

- Teste a teste: cada teste é comparado antes/depois; se criar, alterar ou apagar um ficheiro
  numa dessas pastas, ESSE teste dá erro com o nome e a lista do que mudou (aparece no resumo
  como "N errors", à vista).
- Sessão: a mesma comparação no fim da sessão inteira (apanha escritas fora dos testes, ex. na
  recolha), escrita no FIM do resumo e com exit code de falha.

Porquê teste a teste: até ao N3.5 só havia a guarda de sessão, que escrevia o aviso ANTES do
resumo - a última linha dizia "N passed" com exit code 1, e os testes do main() do regenerate
reescreveram outputs/redundancia/ de N2.5 a N3.4 sem ninguém dar por isso.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARDED = tuple(ROOT / name for name in ("outputs", "reports", "data"))
_SNAPSHOT_KEY = pytest.StashKey[dict[str, tuple[int, int]]]()
_SESSION_PROBLEMS_KEY = pytest.StashKey[list[str]]()
_IGNORED_DIRS = {"__pycache__", ".pytest_cache"}


def _walk(folder: str, prefix: int, out: dict[str, tuple[int, int]]) -> None:
    # Corre antes e depois de CADA teste, por isso tem de ser barato: os.scandir (no Windows o
    # stat vem da própria listagem) e caminhos em texto - com Path/relative_to por ficheiro um
    # snapshot levava ~40 ms em vez de ~7 ms (+30 s na suite).
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            if entry.name not in _IGNORED_DIRS:
                _walk(entry.path, prefix, out)
        elif entry.is_file(follow_symlinks=False):
            st = entry.stat(follow_symlinks=False)
            out[entry.path[prefix:].replace("\\", "/")] = (st.st_size, st.st_mtime_ns)


def snapshot_guarded() -> dict[str, tuple[int, int]]:
    """(tamanho, mtime) de cada ficheiro das pastas guardadas, por caminho relativo à raiz."""
    out: dict[str, tuple[int, int]] = {}
    prefix = len(str(ROOT)) + 1
    for folder in GUARDED:
        _walk(str(folder), prefix, out)
    return out


def changes(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    """Linhas "criado/alterado/apagado: caminho" entre dois snapshots (vazio = nada mudou)."""
    lines = [f"criado: {k}" for k in sorted(set(after) - set(before))]
    lines += [f"alterado: {k}" for k in sorted(k for k in set(before) & set(after) if before[k] != after[k])]
    lines += [f"apagado: {k}" for k in sorted(set(before) - set(after))]
    return lines


def guard_message(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> str | None:
    """Mensagem de erro do guarda de um teste, ou None se nada mudou."""
    found = changes(before, after)
    if not found:
        return None
    shown = "\n  ".join(found[:20]) + (f"\n  ... e mais {len(found) - 20}" if len(found) > 20 else "")
    return ("este teste escreveu nas pastas do projeto (só pode escrever em tmp_path):\n  " + shown
            + "\n  -> repor com: git checkout -- outputs reports data  (e corrigir o teste)")


@pytest.fixture(autouse=True)
def _guard_project_folders():
    before = snapshot_guarded()
    yield
    message = guard_message(before, snapshot_guarded())
    if message:
        pytest.fail(message, pytrace=False)


def pytest_sessionstart(session: pytest.Session) -> None:
    session.stash[_SNAPSHOT_KEY] = snapshot_guarded()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.stash.get(_SNAPSHOT_KEY, None)
    if before is None:
        return
    found = changes(before, snapshot_guarded())
    session.config.stash[_SESSION_PROBLEMS_KEY] = found  # lido no resumo (pytest_terminal_summary)
    if found:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    # Escrito no FIM do resumo (depois da linha "N passed"), para não passar despercebido.
    found = config.stash.get(_SESSION_PROBLEMS_KEY, None)
    if not found:
        return
    terminalreporter.write_line("")
    terminalreporter.write_line("[ERRO] A sessão de testes alterou as pastas do projeto (só pode escrever em tmp_path):", red=True)
    for line in found:
        terminalreporter.write_line(f"  {line}", red=True)
    terminalreporter.write_line("  -> repor com: git checkout -- outputs reports data  (e corrigir o teste)", red=True)
