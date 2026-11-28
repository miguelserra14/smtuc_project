"""Testes de scripts/snapshot_metrics.py (passo D0.2): formato, diff, proteção da linha de base e
- com os dados de referência - que o cálculo atual reproduz EXATAMENTE reports/metricas/sintetico.csv
(rede de segurança para refatorações: se um número mudar sem os dados mudarem, falha aqui)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.script_loader import load_script
from tests.reference_data import require_reference_data

ROOT = Path(__file__).resolve().parents[2]
# Linha de base ATUAL (dados e desvios em uso). Registos anteriores em reports/metricas/ (ver o
# README de lá): sintetico.csv (metro sintético) -> oficial_fase1.csv (metro oficial, desvios
# antigos) -> oficial_fase1_desvios.csv (desvios decididos a 2026-11-16) -> oficial_fase1_d24.csv
# (D2.4: a 38 conta em Portagem com origem própria; nós por distância) -> oficial_fase1_t3.csv
# (T3: overlap temporal só com o serviço do dia de referência; só mudam as colunas temporal_*).
BASELINE = ROOT / "reports" / "metricas" / "oficial_fase1_t3.csv"


def _load_script():
    return load_script("snapshot_metrics")


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


def test_optional_sections_stay_out_of_the_default() -> None:
    # Os registos já gravados (e o BASELINE) não têm a redundância: tem de ser pedida.
    assert "redundancia" in snap_mod.OPTIONAL_SECTIONS
    assert "redundancia" not in snap_mod.SECTIONS


@pytest.mark.integration
def test_redundancy_section_matches_the_module() -> None:
    from overlap.redundancy import scenario_redundancy

    require_reference_data("smtuc", "metrobus")  # salta sem os feeds (ex.: no CI)
    df = snap_mod.take_snapshot("x", sections=("redundancia",))
    data = df[df["section"] == "redundancia"].set_index(["key", "metric"])["value"]
    totals = scenario_redundancy().totals()
    assert float(data[("total", "km_metro")]) == pytest.approx(totals["km_metro"], abs=1e-3)
    assert int(float(data[("total", "viagens")])) == totals["viagens"]
    assert set(df["section"]) == {"meta", "redundancia"}
    assert ("desperdicio", "ano_t_co2") in data.index and ("semana-tipo sábado", "peso") in data.index


def test_node_departures_follow_the_config_window(monkeypatch: pytest.MonkeyPatch) -> None:
    import config

    monkeypatch.setattr(config, "NODE_ISOCHRONE_START", "08:00:00")
    monkeypatch.setattr(config, "NODE_ISOCHRONE_END", "08:30:00")
    monkeypatch.setattr(config, "NODE_ISOCHRONE_STEP_MIN", 10)
    assert snap_mod.node_departure_times() == ["08:00:00", "08:10:00", "08:20:00"]  # fim exclusive
    monkeypatch.setattr(config, "NODE_ISOCHRONE_STEP_MIN", 0)
    with pytest.raises(ValueError, match="janela"):
        snap_mod.node_departure_times()


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
        from population.data_processing import require_bgri_data, require_geo_stack

        require_geo_stack()
        require_bgri_data()
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
    # Frequências verificadas à mão (passo 0.1; SMTUC, não mudaram com o metro oficial).
    assert base[("linhas", "7", "avg_freq_min")] == "20"
    assert base[("linhas", "54", "avg_freq_min")] == "40"
    # D2.4: 54 + 38 (cada uma com a sua origem) em Portagem -> 19.02 (só a 54: 26.02; sintético 27).
    assert base[("esperas_54", "Portagem metro→bus | atual", "median")] == "19.02"
    assert base[("esperas_54", "Portela metro→bus | atual", "median")] == "15.33"  # Portela não muda
    # A busca no cenário "antes" daria 0 / -10; os desvios adotados (-10 / 0) vêm da fase 2.
    assert base[("busca_fase_54", "otimizado", "shift_min")] == "0"
    assert base[("busca_fase_54", "melhorado", "shift_min")] == "-10"
    assert base[("esperas_54", "Portagem metro→bus | otimizado", "shift_min")] == "-10"
    # T3 (aprovado 2026-11-24): overlap temporal do dia de referência (2026-05-11), não da semana
    # somada - antes 14115 de 15292 (92.3 %).
    assert base[("overlap_resumo", "total", "temporal_overlap_times")] == "4651"
    assert base[("overlap_resumo", "total", "total_spatial_candidates")] == "4971"
    assert base[("overlap_resumo", "total", "temporal_overlap_pct")] == "93.56"


# --------------------------------------------------------------------------- verificar (auditoria 2026-11-28)


def _record(path: Path, scenario: str, sections: str, values: dict[tuple[str, str], object], fp: str = "aa") -> None:
    rows = [("meta", "snapshot", "cenario", scenario), ("meta", "snapshot", "secoes", sections),
            ("meta", "dados", "impressao_digital_smtuc", fp), ("meta", "dados", "impressao_digital_metro", "bb")]
    rows += [(sec, key, "valor", v) for (sec, key), v in values.items()]
    snap_mod.write_snapshot(_frame(rows), path)


def _fake_snapshot(values: dict[tuple[str, str], object], fp: str = "aa"):
    calls = []

    def run(phase, scenario=None, sections=()):
        calls.append((scenario, tuple(sections)))
        rows = [("meta", "dados", "impressao_digital_smtuc", fp), ("meta", "dados", "impressao_digital_metro", "bb")]
        rows += [(sec, key, "valor", v) for (sec, key), v in values.items() if sec in sections]
        return _frame(rows)

    run.calls = calls
    return run


def test_verify_compares_each_record_on_its_own_sections(tmp_path: Path) -> None:
    _record(tmp_path / "base.csv", "fase2", "linhas;isocrona", {("linhas", "5"): 10, ("isocrona", "t"): 40})
    _record(tmp_path / "opt.csv", "fase2", "redundancia", {("redundancia", "km"): 1970})
    records = [("base", "fase2"), ("opt", "fase2")]
    same = _fake_snapshot({("linhas", "5"): 10, ("isocrona", "t"): 40, ("redundancia", "km"): 1970, ("populacao", "x"): 1})
    results = snap_mod.verify_records(records, tmp_path, snapshot_fn=same)
    assert [r["estado"] for r in results] == ["igual", "igual"]
    assert same.calls == [("fase2", ("linhas", "isocrona", "redundancia"))]  # um snapshot por cenário
    changed = _fake_snapshot({("linhas", "5"): 11, ("isocrona", "t"): 40, ("redundancia", "km"): 1970})
    results = {r["registo"]: r for r in snap_mod.verify_records(records, tmp_path, snapshot_fn=changed)}
    assert results["base"]["estado"] == "diferente" and len(results["base"]["diferencas"]) == 1
    assert results["opt"]["estado"] == "igual"


def test_verify_flags_missing_wrong_scenario_and_changed_data(tmp_path: Path) -> None:
    _record(tmp_path / "a.csv", "fase2", "linhas", {("linhas", "5"): 10})
    _record(tmp_path / "b.csv", "antes", "linhas", {("linhas", "5"): 10})
    records = [("a", "fase2"), ("b", "fase2"), ("c", "fase2")]
    results = {r["registo"]: r["estado"] for r in snap_mod.verify_records(records, tmp_path, snapshot_fn=_fake_snapshot({("linhas", "5"): 10}, fp="zz"))}
    assert results == {"a": "dados mudaram", "b": "cenário errado (antes)", "c": "em falta"}
    assert snap_mod._print_verification([{"registo": "a", "cenario": "fase2", "estado": "dados mudaram", "diferencas": None}]) == 1


def test_current_records_list_is_consistent() -> None:
    # em_vigor.csv: cada registo existe e é do cenário indicado, e cada cenário do config tem
    # registos que cobrem as secções por omissão (as que o cenário tem: sem a 54 não há esperas).
    import config

    records = snap_mod.load_current_records()
    folder = snap_mod.CURRENT_RECORDS_CSV.parent
    covered: dict[str, set[str]] = {}
    for name, scen in records:
        df = snap_mod.read_snapshot(folder / f"{name}.csv")
        assert snap_mod._meta(df, "cenario") == scen, name
        covered.setdefault(scen, set()).update(snap_mod.record_sections(df))
    from gtfs_processing.scenarios import excluded_integration_lines, get_scenario

    for scen in config.SCENARIOS:
        expected = set(snap_mod.SECTIONS)
        if excluded_integration_lines(get_scenario(scen)):
            expected -= {"esperas_54", "busca_fase_54"}
        missing = expected - covered.get(scen, set())
        assert not missing, f"cenário {scen} sem registo em vigor para {sorted(missing)} (reports/metricas/em_vigor.csv)"
