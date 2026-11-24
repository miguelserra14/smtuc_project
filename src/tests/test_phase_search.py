"""Testes de scripts/search_phase_shift.py (passo 0.2 do roadmap).

O script original que deu os desvios -16 (otimizado) e -8 (melhorado) não estava no repositório;
o novo tem de os REPRODUZIR quando corrido com a regra antiga (transbordo = 0 min), senão a
diferença com transbordo não seria atribuível só ao transbordo.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.script_loader import load_script
from tests.reference_data import require_reference_data

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    return load_script("search_phase_shift")


def _schedule(bus: list[tuple[str, str]], metro: list[str]) -> pd.DataFrame:
    n = max(len(bus), len(metro))
    return pd.DataFrame(
        {
            "bus_time": [bus[i][0] if i < len(bus) else "" for i in range(n)],
            "bus_line_passage": [bus[i][1] if i < len(bus) else "" for i in range(n)],
            "metro_time_from_origin": [metro[i] if i < len(metro) else "" for i in range(n)],
        }
    )


def test_search_covers_half_a_cycle_per_proposal() -> None:
    script = _load_script()
    assert script.default_shifts("otimizado") == range(-20, 21)  # ciclo de 40 min
    assert script.default_shifts("melhorado") == range(-10, 11)  # ciclo de 20 min (2.º autocarro)


def test_ranking_never_accepts_a_regression_to_improve_another_sense() -> None:
    """Critério de 2026-11-16: menos regressões primeiro, depois menor espera total. O antigo
    ("mais sentidos melhorados" primeiro) escolhia +10 aqui, que melhora A mas piora B."""
    script = _load_script()
    import pandas as pd

    results = pd.DataFrame(
        [
            {"variant": "otimizado", "shift_min": 10, "melhorados": 1, "regressoes": 1, "soma_medianas": 30.0},
            {"variant": "otimizado", "shift_min": -5, "melhorados": 0, "regressoes": 0, "soma_medianas": 32.0},
            {"variant": "otimizado", "shift_min": 0, "melhorados": 0, "regressoes": 0, "soma_medianas": 32.0},
            {"variant": "otimizado", "shift_min": 3, "melhorados": 1, "regressoes": 0, "soma_medianas": 31.0},
        ]
    )
    results["_rank_key"] = script.rank_key(results)
    assert int(script.best(results, "otimizado")["shift_min"]) == 3
    # Empate na espera total: o desvio mais pequeno (0 antes de -5).
    results = results[results["shift_min"].isin([-5, 0])].copy()
    assert int(script.best(results, "otimizado")["shift_min"]) == 0


def test_ranking_finds_the_coinciding_shift() -> None:
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
    """Tabela gravada, ordenada com o critério ANTIGO (mais sentidos melhorados primeiro) com que
    os desvios históricos foram escolhidos."""
    df = pd.read_csv(METRICAS / name)
    df["_rank_key"] = list(zip(-df["melhorados"], df["regressoes"], df["soma_medianas"], df["shift_min"].abs()))
    return df


def test_recorded_synthetic_search_reproduces_original_shifts() -> None:
    """Registo do "antes" (metro SINTÉTICO, regra antiga sem transbordo, critério antigo): o
    script reproduzia os -16/-8 originais. Gravado a 2026-11-16 em reports/metricas/ antes de
    trocar para o oficial; o sintético deixou de ser o dataset "metrobus", por isso
    verifica-se a tabela gravada."""
    script = _load_script()
    results = _recorded("busca_fase_54_sintetico_sem_transbordo.csv")
    opt, mel = script.best(results, "otimizado"), script.best(results, "melhorado")
    assert (int(opt["shift_min"]), int(opt["melhorados"]), int(opt["regressoes"])) == (-16, 3, 1)
    assert (int(mel["shift_min"]), int(mel["melhorados"]), int(mel["regressoes"])) == (-8, 4, 0)
    with_transfer = _recorded("busca_fase_54_sintetico.csv")
    assert int(script.best(with_transfer, "otimizado")["shift_min"]) == -11  # passo 0.2


@pytest.mark.integration
def test_transfer_rule_changes_the_optimum(tmp_path: Path) -> None:
    """Cenário "antes" (metro oficial fase 1, com a 38 a contar em Portagem desde a D2.4): com o
    transbordo a pé a busca escolheria 0 / -10; com a regra antiga (transbordo 0 = ligações
    fisicamente impossíveis contam) seriam -13 / +7."""
    require_reference_data("smtuc", "metrobus")  # valores calibrados para estes feeds
    script = _load_script()
    schedules = script.load_schedules(tmp_path, scenario="antes")
    results, base = script.search(schedules)
    assert base["Portagem metro→bus"]["median"] == pytest.approx(19.02, abs=0.005)  # 54 + 38 (antes só a 54: 26.02)
    assert base["Portagem bus→metro"]["median"] == 4.0
    assert (int(script.best(results, "otimizado")["shift_min"]), int(script.best(results, "melhorado")["shift_min"])) == (0, -10)
    old_rule = {k: v.drop(columns=["target_transfer_min", "trigger_transfer_min"]) for k, v in schedules.items()}
    old_results, _ = script.search(old_rule)
    assert (int(script.best(old_results, "otimizado")["shift_min"]), int(script.best(old_results, "melhorado")["shift_min"])) == (-13, 7)


@pytest.mark.integration
def test_config_shifts_match_documented_properties(tmp_path: Path) -> None:
    """Os desvios em config.py (e o comentário que os justifica) são os que a busca escolhe na
    REDE DA FASE 2 (cenário fase2, decidido a 2026-11-16): em meio ciclo, menos regressões
    e depois a menor espera total. Se os dados mudarem, este teste salta e lembra que é preciso
    correr scripts/search_phase_shift.py --cenario ... de novo."""
    require_reference_data("smtuc_atual", "metro_fase2_oficial")
    from config import LINE_54_MELHORADO_PHASE_SHIFT_MIN, LINE_54_OPTIMIZED_PHASE_SHIFT_MIN

    script = _load_script()
    results, _ = script.search(script.load_schedules(tmp_path, scenario="fase2"))
    for variant, configured, expected in (
        ("otimizado", LINE_54_OPTIMIZED_PHASE_SHIFT_MIN, (3, 0, 48.59)),
        ("melhorado", LINE_54_MELHORADO_PHASE_SHIFT_MIN, (2, 1, 38.03)),
    ):
        chosen = script.best(results, variant)
        assert int(chosen["shift_min"]) == int(configured), variant
        assert (int(chosen["melhorados"]), int(chosen["regressoes"]), float(chosen["soma_medianas"])) == expected, variant
        sub = results[results["variant"] == variant]
        assert chosen["regressoes"] == sub["regressoes"].min()
        assert chosen["soma_medianas"] == sub[sub["regressoes"] == chosen["regressoes"]]["soma_medianas"].min()
