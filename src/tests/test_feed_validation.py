"""Validador dos feeds GTFS em uso (D1.3 / roadmap 3.3): corre sobre TODOS os datasets de
config.DATASET_DIRS, para que um feed novo entre já verificado.

Regras (limites calibrados a 2026-11-16 nos feeds reais):
- integridade referencial (stop_times -> trips/stops, trips -> routes/serviços);
- horas válidas (HH:MM:SS, >= 24h permitido) e que nunca recuam dentro de uma viagem;
- velocidade entre paragens consecutivas <= 120 km/h (SMTUC: máx. 62; Metro oficial: máx. 46);
- duas paragens seguidas com a MESMA hora a mais de 1000 m = erro (SMTUC: máx. 571 m, horas ao minuto);
- o período de serviço cobre o dia de referência de cada cenário que usa o feed;
- feeds construídos por scripts/build_feeds.py: ficheiros iguais ao PROVENANCE.json (nada mexido à mão)
  e sem paragens técnicas PC1-PC8.

Problemas CONHECIDOS ficam em KNOWN_ISSUES como xfail estrito: o teste avisa quando deixarem de
existir (ex.: ao arquivar os sintéticos), em vez de os esconder.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

import numpy as np
import pandas as pd
import pytest

import config
from gtfs_processing.gtfs import dataset_dir, load_gtfs
from gtfs_processing.gtfs_probe import feed_service_period

MAX_SPEED_KMH = 120.0
MAX_SAME_TIME_DISTANCE_M = 1000.0

KNOWN_ISSUES: dict[tuple[str, str], str] = {
    ("metrobus_fase2", "velocidade"): "sintético: 4 paragens da Lousã com coordenadas erradas (troços a ~320 km/h)",
    ("metrobus_fase2", "horas"): "sintético: Casal de Santo António -> Serpins, 1077 m com a mesma hora (0 s)",
}

DATASETS = sorted(config.DATASET_DIRS)
# Feeds construídos por scripts/build_feeds.py (têm PROVENANCE.json). Os restantes são anteriores
# ao build (smtuc Ep212 e os sintéticos) - ver data/README.md.
BUILT = [d for d in DATASETS if (dataset_dir(d) / "PROVENANCE.json").exists()]


def _check(dataset: str, rule: str):
    reason = KNOWN_ISSUES.get((dataset, rule))
    return pytest.param(dataset, marks=pytest.mark.xfail(reason=reason, strict=True)) if reason else dataset


def _params(rule: str):
    return [_check(d, rule) for d in DATASETS]


@lru_cache(maxsize=None)
def _feed(dataset: str):
    if not (dataset_dir(dataset) / "trips.txt").exists():
        pytest.skip(f"{dataset}: {dataset_dir(dataset)} não existe nesta máquina")
    return load_gtfs(dataset=dataset)


def _seconds(value: object) -> int:
    h, m, s = str(value).strip().split(":")
    if not (h.isdigit() and m.isdigit() and s.isdigit() and int(m) < 60 and int(s) < 60):
        raise ValueError(value)
    return int(h) * 3600 + int(m) * 60 + int(s)


@lru_cache(maxsize=None)
def _segments(dataset: str) -> pd.DataFrame:
    """Troços entre paragens consecutivas de cada viagem: distância (m) e tempo (s)."""
    g = _feed(dataset)
    st = g.stop_times[["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"]].copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)
    st["seq"] = pd.to_numeric(st["stop_sequence"])
    st["arr"] = st["arrival_time"].map(_seconds)
    st["dep"] = st["departure_time"].map(_seconds)
    stops = g.stops[["stop_id", "stop_lat", "stop_lon"]].copy()
    stops["stop_id"] = stops["stop_id"].astype(str)
    st = st.merge(stops, on="stop_id", how="left").sort_values(["trip_id", "seq"])
    nxt = st.groupby("trip_id")[["stop_id", "arr", "stop_lat", "stop_lon"]].shift(-1)
    la1, lo1 = np.radians(st["stop_lat"].astype(float)), np.radians(st["stop_lon"].astype(float))
    la2, lo2 = np.radians(nxt["stop_lat"].astype(float)), np.radians(nxt["stop_lon"].astype(float))
    dist = 6371000 * 2 * np.arcsin(np.sqrt(np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2))
    out = pd.DataFrame({"trip_id": st["trip_id"], "de": st["stop_id"], "para": nxt["stop_id"],
                        "dist_m": dist, "dt_s": nxt["arr"] - st["dep"], "dwell_s": st["dep"] - st["arr"]})
    return out.dropna(subset=["para"])


@pytest.mark.integration
@pytest.mark.parametrize("dataset", _params("integridade"))
def test_referential_integrity(dataset: str) -> None:
    g = _feed(dataset)
    trips = set(g.trips["trip_id"].astype(str))
    stops = set(g.stops["stop_id"].astype(str))
    routes = set(g.routes["route_id"].astype(str))
    services = set(g.calendar["service_id"].astype(str)) if not g.calendar.empty else set()
    if not g.calendar_dates.empty:
        services |= set(g.calendar_dates["service_id"].astype(str))
    st_trips = set(g.stop_times["trip_id"].astype(str))
    problems = {
        "stop_times sem viagem": len(st_trips - trips),
        "stop_times sem paragem": len(set(g.stop_times["stop_id"].astype(str)) - stops),
        "viagens sem rota": len(set(g.trips["route_id"].astype(str)) - routes),
        "viagens sem horários": len(trips - st_trips),
        "paragens repetidas": int(g.stops["stop_id"].astype(str).duplicated().sum()),
        "viagens repetidas": int(g.trips["trip_id"].astype(str).duplicated().sum()),
    }
    # service_ids das viagens que nem o calendário nem os aliases resolvem: o _active_service_ids já
    # rebenta com ServiceCalendarError; aqui só se exige que cada viagem tenha um service_id.
    problems["viagens sem service_id"] = int(g.trips["service_id"].isna().sum())
    assert not any(problems.values()), problems
    assert services, "sem calendar nem calendar_dates"


@pytest.mark.integration
@pytest.mark.parametrize("dataset", _params("horas"))
def test_times_are_valid_and_never_go_back(dataset: str) -> None:
    seg = _segments(dataset)
    assert int((seg["dt_s"] < 0).sum()) == 0, seg[seg["dt_s"] < 0].head().to_dict("records")
    assert int((seg["dwell_s"] < 0).sum()) == 0, seg[seg["dwell_s"] < 0].head().to_dict("records")
    same_time_far = seg[(seg["dt_s"] == 0) & (seg["dist_m"] > MAX_SAME_TIME_DISTANCE_M)]
    assert same_time_far.empty, same_time_far.head().to_dict("records")


@pytest.mark.integration
@pytest.mark.parametrize("dataset", _params("velocidade"))
def test_speeds_are_plausible(dataset: str) -> None:
    seg = _segments(dataset)
    moving = seg[seg["dt_s"] > 0]
    speed = moving["dist_m"] / moving["dt_s"] * 3.6
    too_fast = moving.assign(kmh=speed.round(1))[speed > MAX_SPEED_KMH]
    assert too_fast.empty, f"{len(too_fast)} troços > {MAX_SPEED_KMH} km/h: {too_fast.head(3).to_dict('records')}"


@pytest.mark.integration
@pytest.mark.parametrize("dataset", _params("periodo"))
def test_service_period_covers_reference_day(dataset: str) -> None:
    """O período do feed cobre o dia de referência de CADA cenário que o usa (config.SCENARIOS)."""
    from gtfs_processing.scenarios import reference_days_by_dataset

    days = reference_days_by_dataset().get(dataset)
    if not days:
        pytest.skip(f"{dataset}: não é usado por nenhum cenário de config.SCENARIOS")
    start, end = feed_service_period(_feed(dataset))
    outside = sorted(d.isoformat() for d in days if not start <= int(d.strftime("%Y%m%d")) <= end)
    assert not outside, f"{dataset}: período {start}..{end} não cobre o(s) dia(s) de referência {outside}"


def test_official_metro_feeds_are_built_with_provenance() -> None:
    # Um feed de metro não sintético que entre no config sem passar pelo build (cópia à mão) é apanhado aqui.
    for dataset, folder in config.DATASET_DIRS.items():
        if folder.startswith("metro/") and "sintetico" not in folder:
            assert dataset in BUILT, f"{dataset}: sem PROVENANCE.json - construir com scripts/build_feeds.py"


@pytest.mark.parametrize("dataset", BUILT)
def test_built_feeds_match_their_provenance(dataset: str) -> None:
    folder = dataset_dir(dataset)
    prov = json.loads((folder / "PROVENANCE.json").read_text(encoding="utf-8"))
    # Quebras de linha normalizadas, como no build (o git converte para CRLF no checkout).
    current = {p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in sorted(folder.glob("*.txt"))}
    assert current == prov["ficheiros"], "ficheiros diferentes do PROVENANCE.json - editados à mão?"
    stops = pd.read_csv(folder / "stops.txt", dtype=str)
    assert not stops["stop_name"].str.fullmatch(r"PC\d+").any(), "paragens técnicas PC1-PC8 no feed"


def test_known_issues_refer_to_real_datasets() -> None:
    for dataset, rule in KNOWN_ISSUES:
        assert dataset in config.DATASET_DIRS and rule in ("integridade", "horas", "velocidade", "periodo")
