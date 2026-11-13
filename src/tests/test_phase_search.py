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


@pytest.mark.integration
def test_reproduces_original_shifts_without_transfer(tmp_path: Path) -> None:
    require_reference_data("smtuc", "metrobus")  # -16/-8 e -11/-10 calibrados para estes feeds
    script = _load_script()
    schedules = script.load_schedules(tmp_path)
    old_rule = {k: v.drop(columns=["target_transfer_min", "trigger_transfer_min"]) for k, v in schedules.items()}
    results, _ = script.search(old_rule, range(-20, 21))

    opt = script.best(results, "otimizado")
    assert int(opt["shift_min"]) == -16
    assert (int(opt["melhorados"]), int(opt["regressoes"])) == (3, 1)  # "regride ligeiramente só 1"

    mel = script.best(results, "melhorado")
    assert int(mel["shift_min"]) == -8
    assert (int(mel["melhorados"]), int(mel["regressoes"])) == (4, 0)  # "melhora os 4 sem regressão"


@pytest.mark.integration
def test_transfer_rule_changes_the_optimum(tmp_path: Path) -> None:
    """Com o transbordo a pé, -16 deixa de ser o melhor desvio "otimizado" (valores atuais do
    config marcados como provisórios até se decidir - ver resumo do passo 0.2)."""
    require_reference_data("smtuc", "metrobus")  # -16/-8 e -11/-10 calibrados para estes feeds
    script = _load_script()
    results, base = script.search(script.load_schedules(tmp_path), range(-20, 21))
    assert base["Portagem metro→bus"]["median"] == 27.0  # era 19.5 com transbordo 0
    assert int(script.best(results, "otimizado")["shift_min"]) == -11


@pytest.mark.integration
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
