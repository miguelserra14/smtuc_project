"""Testes de scripts/snapshot_metrics.py (passo D0.2): formato, diff, proteção da linha de base e
- com os dados de referência - que o cálculo atual reproduz EXATAMENTE reports/metricas/sintetico.csv
(rede de segurança para refatorações: se um número mudar sem os dados mudarem, falha aqui)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from tests.reference_data import require_reference_data

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "reports" / "metricas" / "sintetico.csv"


def _load_script():
    spec = importlib.util.spec_from_file_location("snapshot_metrics", ROOT / "scripts" / "snapshot_metrics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snap_mod = _load_script()


def _frame(rows: list[tuple[str, str, str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=snap_mod.COLUMNS).astype(str)


# --------------------------------------------------------------------------- unitários


def test_normalize_rounds_and_keeps_special_values() -> None:
    n = snap_mod._normalize
    assert n(3.0) == 3 and isinstance(n(3.0), int)
    assert n(1.234567) == 1.2346
    assert n(float("nan")) == "nan" and n(float("inf")) == "inf" and n(float("-inf")) == "-inf"
    assert n(None) == "" and n(True) == "True" and n("54") == "54"
    import numpy as np

    assert n(np.int64(7)) == 7 and n(np.float64(0.5)) == 0.5


def test_duplicate_keys_are_rejected() -> None:
    s = snap_mod.Snapshot()
    s.add("linhas", "54", "avg_freq_min", 40)
    s.add("linhas", "54", "avg_freq_min", 41)
    with pytest.raises(ValueError, match="repetidas"):
        s.frame()


def test_unknown_section_is_rejected() -> None:
    with pytest.raises(ValueError, match="desconhecidas"):
        snap_mod.take_snapshot("x", sections=("linhas", "nao_existe"))


def test_diff_classifies_changes() -> None:
    before = _frame([
        ("meta", "snapshot", "fase", "a"),
        ("linhas", "54", "avg_freq_min", "40"),
        ("linhas", "54", "ref_day_trips", "42"),
        ("linhas", "7", "avg_freq_min", "20"),
        ("linhas", "9", "avg_freq_min", "nan"),
        ("overlap_resumo", "top5_01", "line", "7"),
        ("populacao", "x", "score", "1.0000001"),
    ])
    after = _frame([
        ("meta", "snapshot", "fase", "b"),
        ("linhas", "54", "avg_freq_min", "30"),        # mudou -25%
        ("linhas", "54", "ref_day_trips", "42"),       # igual
        ("linhas", "9", "avg_freq_min", "nan"),        # nan == nan -> igual
        ("linhas", "8", "avg_freq_min", "15"),         # novo
        ("overlap_resumo", "top5_01", "line", "4"),    # texto mudou
        ("populacao", "x", "score", "1.0000002"),      # dentro da tolerância
    ])                                                 # linha 7 removida
    d = snap_mod.diff_snapshots(before, after).set_index(["section", "key", "metric"])
    assert d.loc[("linhas", "54", "avg_freq_min"), "status"] == "mudou"
    assert d.loc[("linhas", "54", "avg_freq_min"), "delta"] == -10
    assert d.loc[("linhas", "54", "avg_freq_min"), "delta_pct"] == -25
    assert d.loc[("linhas", "8", "avg_freq_min"), "status"] == "novo"
    assert d.loc[("linhas", "7", "avg_freq_min"), "status"] == "removido"
    assert d.loc[("overlap_resumo", "top5_01", "line"), "status"] == "mudou"
    assert d.loc[("meta", "snapshot", "fase"), "status"] == "mudou"
    for same in (("linhas", "54", "ref_day_trips"), ("linhas", "9", "avg_freq_min"), ("populacao", "x", "score")):
        assert same not in d.index
    assert len(d) == 5
    # meta aparece primeiro (contexto antes dos números)
    assert snap_mod.diff_snapshots(before, after)["section"].iloc[0] == "meta"


def test_write_refuses_to_overwrite_baseline(tmp_path: Path) -> None:
    df = _frame([("linhas", "54", "avg_freq_min", "40")])
    path = snap_mod.write_snapshot(df, tmp_path / "base.csv")
    with pytest.raises(FileExistsError):
        snap_mod.write_snapshot(_frame([("linhas", "54", "avg_freq_min", "1")]), path)
    assert snap_mod.read_snapshot(path)["value"].tolist() == ["40"]
    snap_mod.write_snapshot(_frame([("linhas", "54", "avg_freq_min", "1")]), path, force=True)
    assert snap_mod.read_snapshot(path)["value"].tolist() == ["1"]
    assert not list(tmp_path.glob(".*.tmp"))  # sem temporários deixados para trás
    assert snap_mod.main(["snapshot", "base", "--out", str(path)]) == 2  # CLI sem --force


def test_read_rejects_non_snapshot(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="não é um snapshot"):
        snap_mod.read_snapshot(bad)


def test_diff_check_exit_code_ignores_meta(tmp_path: Path) -> None:
    a, b, c = tmp_path / "a.csv", tmp_path / "b.csv", tmp_path / "c.csv"
    snap_mod.write_snapshot(_frame([("meta", "snapshot", "fase", "a"), ("linhas", "54", "avg_freq_min", "40")]), a)
    snap_mod.write_snapshot(_frame([("meta", "snapshot", "fase", "b"), ("linhas", "54", "avg_freq_min", "40")]), b)
    snap_mod.write_snapshot(_frame([("meta", "snapshot", "fase", "c"), ("linhas", "54", "avg_freq_min", "41")]), c)
    assert snap_mod.main(["diff", str(a), str(b), "--check"]) == 0
    assert snap_mod.main(["diff", str(a), str(c), "--check"]) == 1
    assert snap_mod.main(["diff", str(a), str(c)]) == 0  # sem --check é só informativo
    out = tmp_path / "diff.csv"
    snap_mod.main(["diff", str(a), str(c), "--csv", str(out)])
    assert set(pd.read_csv(out)["status"]) == {"mudou"}


# --------------------------------------------------------------------------- integração


@pytest.fixture(scope="module")
def current_snapshot(tmp_path_factory: pytest.TempPathFactory) -> pd.DataFrame:
    require_reference_data("smtuc", "metrobus")
    if not BASELINE.exists():
        pytest.skip(f"linha de base em falta: {BASELINE}")
    try:
        from population.data_processing import _require_bgri_data, _require_geo_stack

        _require_geo_stack()
        _require_bgri_data()
    except Exception as exc:  # geostack/BGRI são opcionais
        pytest.skip(f"geostack/BGRI não disponível: {exc}")
    df = snap_mod.take_snapshot("teste", workdir=tmp_path_factory.mktemp("snapshot"))
    path = snap_mod.write_snapshot(df, tmp_path_factory.mktemp("snapshot_out") / "teste.csv")
    return snap_mod.read_snapshot(path)


@pytest.mark.integration
def test_current_code_reproduces_baseline(current_snapshot: pd.DataFrame) -> None:
    """Se falhar: ou um cálculo mudou (confirmar que é intencional e refazer a linha de base com
    `python scripts/snapshot_metrics.py snapshot sintetico --force`), ou é uma regressão."""
    diff = snap_mod.diff_snapshots(snap_mod.read_snapshot(BASELINE), current_snapshot)
    numbers = diff[diff["section"] != "meta"]
    assert numbers.empty, f"{len(numbers)} números diferentes da linha de base:\n{numbers.head(20).to_string()}"


@pytest.mark.integration
def test_baseline_covers_every_section_and_known_values(current_snapshot: pd.DataFrame) -> None:
    base = snap_mod.read_snapshot(BASELINE).set_index(["section", "key", "metric"])["value"]
    assert set(base.index.get_level_values("section")) == {"meta", *snap_mod.SECTIONS}
    assert base[("meta", "snapshot", "secoes_omitidas")] == ""
    # Valores verificados à mão contra os horários (passos 0.1 e 0.2 do roadmap).
    assert base[("linhas", "7", "avg_freq_min")] == "20"
    assert base[("linhas", "54", "avg_freq_min")] == "40"
    assert base[("esperas_54", "Portagem metro→bus | atual", "median")] == "27"
    assert base[("busca_fase_54", "otimizado", "shift_min")] == "-11"
