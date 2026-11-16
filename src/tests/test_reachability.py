"""Testes do cálculo de acessibilidade multimodal (`_reachable_stops_multimodal_now`), passo 0.6
do roadmap: resultado determinístico (independente de PYTHONHASHSEED) e caminhadas de transbordo
que não se encadeiam para além de `max_transfer_walk_min`.

Rede sintética (tudo ao longo de um meridiano, 1 grau de latitude ~ 111 195 m):

    T1: O (08:00) -> X (08:10) -> Y (08:20)        X ~300 m~ Y ~300 m~ Z  (a pé)
    T2: Y (08:25) -> W (08:35)                     T3: Z (08:20) -> V (08:25)

Partindo de O às 08:00, com limite de transbordo a pé de 5 min (400 m a 80 m/min):
  X = 10 (T1); Y = 13.75 (a pé de X, melhor que os 20 da T1); Z = 23.75 (a pé a partir da
  CHEGADA DA T1 a Y, 20 + 3.75) - nunca 17.5, que exigia encadear X->Y->Z a pé (600 m > 400 m);
  W = 35 (T2 apanhada em Y, 1 transbordo); V inalcançável (a T3 sai de Z às 08:20, antes de
  se lá chegar - só seria apanhável com o encadeamento indevido).

O código antigo dava Z=17.5 e V=25 ou Z=23.75 e V ausente, consoante a ordem de iteração de um
set (X antes ou depois de Y) - i.e. consoante PYTHONHASHSEED.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import overlap.overlap as ov
from gtfs_processing.gtfs import GTFSData

M_PER_DEG_LAT = 6371000.0 * np.pi / 180.0  # mesma esfera que _distances_from_point_m
LON = -8.4
LAT_X = 40.0


def _lat(offset_m: float) -> float:
    return LAT_X + offset_m / M_PER_DEG_LAT


STOPS = {
    "O": _lat(20_000),
    "X": _lat(0),
    "Y": _lat(300),
    "Z": _lat(600),
    "W": _lat(-20_000),
    "V": _lat(-40_000),
}


def _s(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 3600 + m * 60


def _synthetic_gtfs() -> GTFSData:
    trips_def = {
        "T1": [("O", "08:00"), ("X", "08:10"), ("Y", "08:20")],
        "T2": [("Y", "08:25"), ("W", "08:35")],
        "T3": [("Z", "08:20"), ("V", "08:25")],
    }
    st_rows = [
        {"trip_id": t, "stop_id": sid, "stop_sequence": i + 1, "arrival_seconds": _s(hm), "departure_seconds": _s(hm)}
        for t, seq in trips_def.items()
        for i, (sid, hm) in enumerate(seq)
    ]
    calendar = pd.DataFrame(
        [("WD", 1, 1, 1, 1, 1, 0, 0, 20260101, 20261231)],
        columns=["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
    )
    return GTFSData(
        routes=pd.DataFrame({"route_id": ["R"]}),
        trips=pd.DataFrame({"route_id": ["R"] * 3, "service_id": ["WD"] * 3, "trip_id": list(trips_def)}),
        stop_times=pd.DataFrame(st_rows),
        stops=pd.DataFrame({"stop_id": list(STOPS), "stop_lat": list(STOPS.values()), "stop_lon": [LON] * len(STOPS)}),
        shapes=pd.DataFrame(),
        calendar=calendar,
        calendar_dates=pd.DataFrame(),
    )


@pytest.fixture
def synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    gtfs = _synthetic_gtfs()
    monkeypatch.setattr(ov, "_load_gtfs_cached", lambda dataset: gtfs)


def _reach(max_transfers: int = 2) -> dict[str, float]:
    out = ov._reachable_stops_multimodal_now(
        datasets=("syn",),
        origin_lat=STOPS["O"],
        origin_lon=LON,
        day_str="2026-05-11",
        time_str="08:00:00",
        walk_speed_m_min=80.0,
        max_min=60.0,
        max_board_walk_min=10.0,
        max_transfer_walk_min=5.0,
        max_transfers=max_transfers,
    )
    return dict(zip(out["stop_id"], out["reach_min"].round(4)))


def test_expected_reach_times(synthetic: None) -> None:
    reach = _reach()
    assert reach["O"] == pytest.approx(0.0)
    assert reach["X"] == pytest.approx(10.0)
    assert reach["Y"] == pytest.approx(13.75, abs=1e-3)
    assert reach["Z"] == pytest.approx(23.75, abs=1e-3)
    assert reach["W"] == pytest.approx(35.0)


def test_transfer_walks_do_not_chain(synthetic: None) -> None:
    # Z a 17.5 min só encadeando X->Y->Z a pé (2 x 300 m > limite de 400 m).
    reach = _reach()
    assert reach["Z"] > 20.0
    assert "V" not in reach  # e por isso também não se apanha a T3 (08:20) em Z


def test_max_transfers_limits_boardings(synthetic: None) -> None:
    reach = _reach(max_transfers=0)  # só 1 viagem
    assert reach["X"] == pytest.approx(10.0)
    assert "W" not in reach


def test_result_independent_of_changed_set_order(synthetic: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Força ordens de iteração opostas sobre os stops melhorados: o resultado tem de ser igual.
    results = []
    for reverse in (False, True):
        monkeypatch.setattr(ov, "sorted", lambda it, _r=reverse: sorted(it, reverse=_r), raising=False)
        results.append(_reach())
    monkeypatch.delattr(ov, "sorted", raising=False)
    assert results[0] == results[1]


_ROOT = Path(__file__).resolve().parents[2]
_SNIPPET = (
    "import sys; sys.path.insert(0, r'%s');"
    "from overlap.overlap import _reachable_stops_multimodal_now as f;"
    "r = f(('smtuc','metrobus'), 40.203809, -8.407904, '2026-05-11', '08:20:00');"
    "print('RESULT', len(r), round(float(r.reach_min.sum()), 6))"
) % (_ROOT / "src")


@pytest.mark.integration
def test_real_reachability_is_deterministic_across_hash_seeds() -> None:
    from gtfs_processing.gtfs import dataset_dir

    if not (dataset_dir("smtuc") / "trips.txt").exists():
        pytest.skip("dados GTFS não disponíveis")
    outputs = set()
    for seed in ("0", "1", "7"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run([sys.executable, "-c", _SNIPPET], capture_output=True, text=True, env=env, timeout=600)
        assert proc.returncode == 0, proc.stderr
        outputs.add(next(line for line in proc.stdout.splitlines() if line.startswith("RESULT")))
    assert len(outputs) == 1, outputs


_SYNTH_SNIPPET = (
    "import sys; sys.path[:0] = [r'%s'];"
    "import overlap.overlap as ov, tests.test_reachability as t;"
    "ov._load_gtfs_cached = lambda d: t._synthetic_gtfs();"
    "print('RESULT', sorted(t._reach().items()))"
) % (_ROOT / "src")


def test_synthetic_reachability_is_deterministic_across_hash_seeds() -> None:
    """Sem dados reais: a ordem de iteração de sets muda com PYTHONHASHSEED, por isso corre-se a
    rede sintética em subprocessos com várias sementes (o código antigo divergia em ~metade)."""
    outputs = set()
    # 0 vs 3/4: sementes que comprovadamente divergiam no código antigo (Z=17.5 vs 23.75).
    for seed in ("0", "3", "4"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run([sys.executable, "-c", _SYNTH_SNIPPET], capture_output=True, text=True, env=env, cwd=_ROOT, timeout=300)
        assert proc.returncode == 0, proc.stderr
        outputs.add(next(line for line in proc.stdout.splitlines() if line.startswith("RESULT")))
    assert len(outputs) == 1, outputs
    assert "('Z', 23.75)" in outputs.pop()
