"""Testes de scripts/search_phase_shift.py (passo 0.2 do roadmap).

O script original que deu os desvios -16 (otimizado) e -8 (melhorado) não estava no repositório;
o novo tem de os REPRODUZIR quando corrido com a regra antiga (transbordo = 0 min), senão a
diferença com transbordo não seria atribuível só ao transbordo.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from tests.reference_data import require_reference_data

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location("search_phase_shift", ROOT / "scripts" / "search_phase_shift.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schedule(bus: list[tuple[str, str]], metro: list[str]) -> pd.DataFrame:
    n = max(len(bus), len(metro))
    return pd.DataFrame(
        {
            "bus_time": [bus[i][0] if i < len(bus) else "" for i in range(n)],
            "bus_line_passage": [bus[i][1] if i < len(bus) else "" for i in range(n)],
            "metro_time_from_origin": [metro[i] if i < len(metro) else "" for i in range(n)],
        }
    )


def test_ranking_prefers_more_improved_then_fewer_regressions() -> None:
    script = _load_script()
    # 1 só sentido: autocarro 54 de 40 em 40 a partir das 08:00, metro às 08:30 e 09:10.
    # Desvio 0 -> espera 10 min; -10 -> autocarros às 08:30/09:10, espera 0 (sem colunas de
    # transbordo = regra antiga); +10 -> espera 20. O melhor tem de ser -10.
    df = _schedule([(f"{h:02d}:{m:02d}:00", "54") for h, m in ((8, 0), (8, 40), (9, 20), (10, 0))], ["08:30:00", "09:10:00"])
    results, base = script.search({"X metro→bus": df}, range(-20, 21))
    assert base["X metro→bus"]["median"] == 10.0
    best = script.best(results, "otimizado")
    assert int(best["shift_min"]) == -10 and int(best["melhorados"]) == 1 and int(best["regressoes"]) == 0
    assert best["X metro→bus mediana"] == 0.0
    # Com 2 min de transbordo no alvo, -10 já não dá (08:30 < 08:30 + 2) e o ótimo passa a -8.
    df["target_transfer_min"] = [2.0 if t else None for t in df["bus_time"]]
    results, _ = script.search({"X metro→bus": df}, range(-20, 21))
    best = script.best(results, "otimizado")
    assert int(best["shift_min"]) == -8 and best["X metro→bus mediana"] == 2.0


METRICAS = ROOT / "reports" / "metricas"


def _recorded(name: str) -> pd.DataFrame:
    df = pd.read_csv(METRICAS / name)
    df["_rank_key"] = list(zip(-df["melhorados"], df["regressoes"], df["soma_medianas"], df["shift_min"].abs()))
    return df


def test_recorded_synthetic_search_reproduces_original_shifts() -> None:
    """Registo do "antes" (metro SINTÉTICO, regra antiga sem transbordo): o script reproduzia os
    -16/-8 originais. Gravado a 2026-11-16 em reports/metricas/ antes de trocar para o oficial;
    o sintético deixou de ser o dataset "metrobus", por isso verifica-se a tabela gravada."""
    script = _load_script()
    results = _recorded("busca_fase_54_sintetico_sem_transbordo.csv")
    opt, mel = script.best(results, "otimizado"), script.best(results, "melhorado")
    assert (int(opt["shift_min"]), int(opt["melhorados"]), int(opt["regressoes"])) == (-16, 3, 1)
    assert (int(mel["shift_min"]), int(mel["melhorados"]), int(mel["regressoes"])) == (-8, 4, 0)
    with_transfer = _recorded("busca_fase_54_sintetico.csv")
    assert int(script.best(with_transfer, "otimizado")["shift_min"]) == -11  # passo 0.2


@pytest.mark.integration
def test_transfer_rule_changes_the_optimum(tmp_path: Path) -> None:
    """Metro OFICIAL (D1 passo 4): com o transbordo a pé o ótimo "otimizado" é -11; com a regra
    antiga (transbordo 0) seria -13."""
    require_reference_data("smtuc", "metrobus")  # valores calibrados para estes feeds
    script = _load_script()
    schedules = script.load_schedules(tmp_path)
    results, base = script.search(schedules, range(-20, 21))
    assert base["Portagem metro→bus"]["median"] == pytest.approx(26.02, abs=0.005)
    assert base["Portagem bus→metro"]["median"] == 2.0  # vaivéns urbanos a cada ~7 min
    assert int(script.best(results, "otimizado")["shift_min"]) == -11
    old_rule = {k: v.drop(columns=["target_transfer_min", "trigger_transfer_min"]) for k, v in schedules.items()}
    old_results, _ = script.search(old_rule, range(-20, 21))
    assert int(script.best(old_results, "otimizado")["shift_min"]) == -13


@pytest.mark.integration
@pytest.mark.xfail(
    strict=True,
    reason="AGUARDA DECISÃO: desvios da 54 ainda os do sintético (-11/-10); com o metro oficial a "
    "busca dá -11 (2 melhor./2 regr.) e -18 (3/1) - ver reports/metricas/busca_fase_54_oficial_fase1.csv",
)
def test_config_shifts_match_documented_properties(tmp_path: Path) -> None:
    """Os valores em config.py (e o comentário que os justifica) batem certo com a busca: o
    otimizado é o 1º do ranking (3 melhorados, 1 regressão) e o melhorado é o desvio sem nenhuma
    regressão com menor espera total. Se os dados mudarem, este teste falha (ou salta) e lembra
    que é preciso correr scripts/search_phase_shift.py de novo."""
    require_reference_data("smtuc", "metrobus")  # -16/-8 e -11/-10 calibrados para estes feeds
    from config import LINE_54_MELHORADO_PHASE_SHIFT_MIN, LINE_54_OPTIMIZED_PHASE_SHIFT_MIN

    script = _load_script()
    results, _ = script.search(script.load_schedules(tmp_path), range(-20, 21))

    opt = script.best(results, "otimizado")
    assert int(opt["shift_min"]) == int(LINE_54_OPTIMIZED_PHASE_SHIFT_MIN)
    assert (int(opt["melhorados"]), int(opt["regressoes"])) == (3, 1)

    mel = results[results["variant"] == "melhorado"]
    no_regression = mel[mel["regressoes"] == 0]
    chosen = mel[mel["shift_min"] == int(LINE_54_MELHORADO_PHASE_SHIFT_MIN)].iloc[0]
    assert int(chosen["regressoes"]) == 0 and int(chosen["melhorados"]) >= 1
    assert chosen["soma_medianas"] == no_regression["soma_medianas"].min()
    assert chosen["soma_medianas"] == mel["soma_medianas"].min()  # e menor espera total de todos
