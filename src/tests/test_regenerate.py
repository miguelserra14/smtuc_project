"""Testes do entrypoint scripts/regenerate.py (passo 0.4 do roadmap): output UTF-8 mesmo com
stdout redirecionado, registo de falhas por secção e exit code != 0 quando algo falha.

Não geram HTML nenhum: as secções reais são substituídas por stubs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.script_loader import SCRIPTS_DIR, load_script

regen = load_script("regenerate")

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = (
    "regenerate_population_htmls",
    "regenerate_overlap_htmls",
    "regenerate_overlap_other_scenarios_htmls",
    "regenerate_integration_htmls",
    "regenerate_comparison_html",
    "regenerate_network_diff_html",
    "regenerate_master_dashboard",
    "regenerate_presentation_dashboard",
    "regenerate_feednplay_dashboard",
)


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(regen, "_FAILURES", [])
    monkeypatch.setattr(regen, "_SKIPPED", [])
    monkeypatch.setattr(regen, "_WARNINGS", [])
    # Não mexer no sys.stdout do pytest (capture) - testado à parte num subprocesso.
    monkeypatch.setattr(regen, "_configure_utf8_output", lambda: None)


def _stub_sections(monkeypatch: pytest.MonkeyPatch, calls: list[str], failing: str | None = None) -> None:
    for name in SECTIONS:
        def _stub(_name: str = name) -> None:
            calls.append(_name)
            if _name == failing:
                try:
                    raise RuntimeError("boom")
                except RuntimeError as exc:
                    regen._record_failure(_name, exc)
        monkeypatch.setattr(regen, name, _stub)


def test_summary_exit_code() -> None:
    assert regen._print_summary() == 0
    regen._record_skip("x", "sem geostack")
    regen._record_warning("y", "sem POI")
    assert regen._print_summary() == 0  # saltos e avisos não são falhas
    regen._record_failure("z", ValueError("falhou"))
    assert regen._print_summary() == 1


def test_summary_lists_every_problem(capsys: pytest.CaptureFixture[str]) -> None:
    regen._record_failure("integração Portela (54)", KeyError("stop"))
    regen._record_skip("overlap fase 2", "dataset metrobus_fase2 não disponível")
    regen._print_summary()
    out = capsys.readouterr().out
    assert "REGENERAÇÃO INCOMPLETA - 1 falha(s)" in out
    assert "integração Portela (54): KeyError" in out
    assert "overlap fase 2: dataset metrobus_fase2 não disponível" in out
    assert "SEM FALHAS" not in out


def test_main_all_ok_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _stub_sections(monkeypatch, calls)
    monkeypatch.setattr(regen, "_validate_reference_day", lambda: True)
    with pytest.raises(SystemExit) as exc_info:
        regen.main()
    assert exc_info.value.code == 0
    assert calls == list(SECTIONS)


def test_main_one_section_failing_exits_one_but_runs_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _stub_sections(monkeypatch, calls, failing="regenerate_integration_htmls")
    monkeypatch.setattr(regen, "_validate_reference_day", lambda: True)
    with pytest.raises(SystemExit) as exc_info:
        regen.main()
    assert exc_info.value.code == 1
    assert calls == list(SECTIONS)  # uma falha não impede as secções seguintes
    assert [s for s, _ in regen._FAILURES] == ["regenerate_integration_htmls"]


def test_main_invalid_reference_day_generates_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _stub_sections(monkeypatch, calls)
    monkeypatch.setattr(regen, "_validate_reference_day", lambda: False)
    with pytest.raises(SystemExit) as exc_info:
        regen.main()
    assert exc_info.value.code == 1
    assert calls == []


def test_real_integration_section_records_failure_instead_of_swallowing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A secção de integração real, com a geração a rebentar: tem de ficar registada como falha
    # (antes era só um print [WARNING] e o script acabava "CONCLUÍDA" com exit 0).
    monkeypatch.setattr(regen, "_require_dataset", lambda d: Path("."))

    def _boom(**kwargs):
        raise UnicodeEncodeError("charmap", "→", 0, 1, "character maps to <undefined>")

    monkeypatch.setattr(regen, "generate_connection_visualizations", _boom)
    regen.regenerate_integration_htmls()
    expected = []
    for name in _with_integration():  # o cenário por omissão sai sem o nome
        prefix = "integração" if not regen.get_scenario(name).output_suffix else f"integração {name}"
        expected += [f"{prefix} Portagem (54+38)", f"{prefix} Portela (54)"]
    assert [s for s, _ in regen._FAILURES] == expected
    assert "integração fase2 Portela (54)" in expected and "integração fase2_ep212 Portela (54)" in expected
    assert not any("antes_sem54" in name for name in expected)  # sem a 54 não há integração


def _with_integration() -> list[str]:
    """Cenários com páginas de integração: todos menos os que retiram a 54/38 (N2.3, A′)."""
    return [n for n in regen.scenario_names() if not regen.excluded_integration_lines(n)]


def test_overlap_section_covers_every_other_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    # N1: o overlap/isócronas sai para TODOS os cenários (antes só o "fase2", escrito à mão).
    seen: list[str] = []
    monkeypatch.setattr(regen, "regenerate_overlap_scenario_htmls", seen.append)
    regen.regenerate_overlap_other_scenarios_htmls()
    assert seen == [n for n in regen.scenario_names() if n != regen.get_scenario().name]
    assert "fase2_ep212" in seen and "fase2" in seen


def test_integration_section_covers_every_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cada cenário de config.SCENARIOS gera as suas páginas de integração (a fase 2 grava em
    # integration/<subpasta>_fase2/), com o SEU dia de referência e o seu nome de cenário.
    monkeypatch.setattr(regen, "_require_dataset", lambda d: Path("."))
    calls: list[tuple[str, str, str]] = []

    def _fake(**kwargs):
        calls.append((kwargs["scenario"], kwargs["day_str"], kwargs["output_subdir"]))
        return {"combined_html": "x"}

    monkeypatch.setattr(regen, "generate_connection_visualizations", _fake)
    regen.regenerate_integration_htmls()
    assert regen._FAILURES == []
    by_scenario: dict[str, set[str]] = {}
    for scenario, day, _subdir in calls:
        by_scenario.setdefault(scenario, set()).add(day)
    assert set(by_scenario) == set(_with_integration())
    assert "antes_sem54" in regen.scenario_names() and "antes_sem54" not in by_scenario
    for name, days in by_scenario.items():
        expected = regen.resolve_reference_day(scenario=regen.get_scenario(name)).strftime("%Y-%m-%d")
        assert days == {expected}
    assert len(calls) == len(_with_integration()) * len(regen.INTEGRATION_SITES)


def test_utf8_output_survives_redirected_stdout() -> None:
    """Corre num subprocesso com o stdout num pipe (o caso que rebentava: cp1252 sem "→") e SEM
    PYTHONIOENCODING/PYTHONUTF8, para reproduzir as condições reais."""
    code = (
        "import importlib.util as u;"
        "s = u.spec_from_file_location('r', r'%s'); r = u.module_from_spec(s); s.loader.exec_module(r);"
        "r._configure_utf8_output();"
        "print('Portela → Portagem · REGENERAÇÃO CONCLUÍDA')"
    ) % (SCRIPTS_DIR / "regenerate.py")
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, cwd=ROOT, timeout=300)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "Portela → Portagem · REGENERAÇÃO CONCLUÍDA" in proc.stdout.decode("utf-8")


def test_without_fix_redirected_stdout_really_breaks() -> None:
    """Controlo: confirma que o problema existe sem a correção (senão o teste acima não prova nada).
    Só se aplica quando a codificação por omissão de um pipe não é UTF-8 (Windows/cp1252)."""
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    probe = subprocess.run([sys.executable, "-c", "import sys; print(sys.stdout.encoding)"], capture_output=True, env=env, timeout=60)
    if "utf" in probe.stdout.decode().lower():
        pytest.skip("stdout redirecionado já é UTF-8 neste sistema")
    proc = subprocess.run([sys.executable, "-c", "print('→')"], capture_output=True, env=env, timeout=60)
    assert proc.returncode != 0 and b"UnicodeEncodeError" in proc.stderr


def test_comparison_section_writes_page_and_csv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # D2.5/N1: a secção tira UM snapshot por cenário de COMPARISON_PAIRS (aqui falso), mesmo que
    # entre em vários pares, e grava página + CSV por par em <raiz>/outputs/comparacao/ (aqui
    # tmp_path); erro no snapshot = falha registada.
    from tests.test_scenario_comparison import AFTER, BEFORE, MIDDLE, SEM54

    taken: list[tuple[str, tuple[str, ...]]] = []

    class _FakeSnapshot:
        @staticmethod
        def take_snapshot(phase, scenario=None, sections=()):
            taken.append((scenario, tuple(sections)))
            return {"antes_sem54": SEM54, "antes": BEFORE, "fase2_ep212": MIDDLE, "fase2": AFTER}[scenario]

    monkeypatch.setattr(regen, "_require_dataset", lambda d: Path("."))
    monkeypatch.setattr(regen, "require_geo_stack", lambda: None)
    monkeypatch.setattr(regen, "require_bgri_data", lambda: Path("."))
    monkeypatch.setattr(regen, "project_root", lambda: tmp_path)
    monkeypatch.setattr(regen, "_load_snapshot_module", lambda: _FakeSnapshot)
    regen.regenerate_comparison_html()
    assert regen._FAILURES == []
    assert sorted(s for s, _ in taken) == sorted({n for pair in regen.COMPARISON_PAIRS for n in pair})
    assert all("busca_fase_54" not in secs and "linhas" not in secs for _, secs in taken)
    out = tmp_path / "outputs" / "comparacao"
    for before, after in regen.COMPARISON_PAIRS:
        assert (out / f"{before}_vs_{after}.html").exists() and (out / f"{before}_vs_{after}.csv").exists()
    assert "338,1 km" in (out / "antes_vs_fase2.html").read_text(encoding="utf-8")
    assert "só muda o <strong>horário do SMTUC</strong>" in (out / "fase2_ep212_vs_fase2.html").read_text(encoding="utf-8")

    def _boom(*a, **k):
        raise RuntimeError("snapshot falhou")

    monkeypatch.setattr(_FakeSnapshot, "take_snapshot", staticmethod(_boom))
    regen.regenerate_comparison_html()
    assert [s for s, _ in regen._FAILURES] == ["comparação de cenários"]


def test_snapshot_module_loads_from_scripts() -> None:
    module = regen._load_snapshot_module()
    assert set(regen._COMPARISON_SECTIONS) <= set(module.SECTIONS)
