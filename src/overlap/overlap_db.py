from __future__ import annotations

import hashlib
import os
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    FREQUENCY_WINDOW_END_H,
    FREQUENCY_WINDOW_START_H,
    LINE_METRICS_DB_PATH,
    STADIUM_COORD,
    STADIUM_RADIUS_M,
    WALK_SPEED_M_MIN,
    SPATIAL_OVERLAP_WALK_MIN,
    TEMPORAL_OVERLAP_MAX_MIN,
)
from paths import PROJECT_ROOT, project_path
from gtfs_processing.geo import haversine_m
from gtfs_processing.gtfs import load_gtfs_cached
from gtfs_processing.gtfs_probe import active_service_ids
from gtfs_processing.scenarios import Scenario, get_scenario, scenario_output_path

# Versão do cálculo guardada no cache (line_metrics_db.csv). Incrementar SEMPRE que a fórmula de
# alguma coluna mudar: a assinatura dos dados/parâmetros não deteta alterações de código, por isso
# sem isto um CSV calculado com a fórmula antiga continuava a ser servido até um force_refresh.
#   2 - avg_freq_min por dia de referência + sentido + mediana 7h-20h, + coluna ref_day_trips
#       (passo 0.1 do roadmap)
#   3 - overlap temporal (temporal_*) só com o serviço do dia de referência, dos dois lados;
#       serviço desconhecido deixa de contar como partilhado (passo 3.4 / T3)
LINE_METRICS_SCHEMA_VERSION = 3


def _min_distance_to_points_m(
    query_lat: np.ndarray,
    query_lon: np.ndarray,
    ref_lat: np.ndarray,
    ref_lon: np.ndarray,
) -> np.ndarray:
    dists = haversine_m(query_lat[:, None], query_lon[:, None], ref_lat[None, :], ref_lon[None, :])
    return dists.min(axis=1)


def _representative_route_stops_for_subset(gtfs, route_trips: pd.DataFrame) -> pd.DataFrame:
    if route_trips.empty:
        return pd.DataFrame()

    st = gtfs.stop_times[gtfs.stop_times["trip_id"].isin(route_trips["trip_id"])].copy()
    if st.empty:
        return pd.DataFrame()

    trip_sizes = st.groupby("trip_id", as_index=False).agg(n_stops=("stop_id", "count"))
    best_trip = str(trip_sizes.sort_values("n_stops", ascending=False).iloc[0]["trip_id"])

    best = st[st["trip_id"] == best_trip].sort_values("stop_sequence")
    best = best.merge(
        gtfs.stops[["stop_id", "stop_lat", "stop_lon"]],
        on="stop_id",
        how="left",
    )
    return best[["stop_id", "stop_sequence", "stop_lat", "stop_lon"]].drop_duplicates(subset=["stop_sequence"])


def iter_route_direction_stop_arrays(
    gtfs_smtuc,
    route_id: str,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, int]]:
    route_trips = gtfs_smtuc.trips[gtfs_smtuc.trips["route_id"] == str(route_id)].copy()
    if route_trips.empty:
        return []

    if "direction_id" in route_trips.columns:
        direction_values = route_trips["direction_id"].dropna().astype(str).unique().tolist() or ["na"]
    else:
        direction_values = ["na"]

    directions: list[tuple[np.ndarray, np.ndarray, np.ndarray, int]] = []
    for direction in direction_values:
        subset = route_trips if direction == "na" else route_trips[route_trips["direction_id"].astype(str) == direction]

        route_stops = _representative_route_stops_for_subset(gtfs_smtuc, subset)
        route_stops = route_stops.dropna(subset=["stop_lat", "stop_lon"]).reset_index(drop=True)
        if len(route_stops) < 2:
            continue

        route_lat = route_stops["stop_lat"].astype(float).to_numpy()
        route_lon = route_stops["stop_lon"].astype(float).to_numpy()
        route_stop_ids = route_stops["stop_id"].to_numpy()
        directions.append((route_lat, route_lon, route_stop_ids, int(len(route_stops))))

    return directions


def _route_direction_summaries(
    gtfs_smtuc,
    route_id: str,
    metro_stops: pd.DataFrame,
    walk_catchment_m: float,
) -> list[dict]:
    metro_lat = metro_stops["stop_lat"].astype(float).to_numpy()
    metro_lon = metro_stops["stop_lon"].astype(float).to_numpy()
    summaries: list[dict] = []

    for route_lat, route_lon, route_stop_ids, _total_stops in iter_route_direction_stop_arrays(gtfs_smtuc, route_id):

        min_dist = _min_distance_to_points_m(route_lat, route_lon, metro_lat, metro_lon)
        is_overlap = min_dist <= walk_catchment_m

        seg_lengths = haversine_m(route_lat[:-1], route_lon[:-1], route_lat[1:], route_lon[1:])
        overlap_segments = is_overlap[:-1] & is_overlap[1:]

        total_ext_m = float(seg_lengths.sum())
        overlap_ext_m = float(seg_lengths[overlap_segments].sum())

        if total_ext_m <= 0:
            continue

        summaries.append(
            {
                "total_ext_m": total_ext_m,
                "overlap_ext_m": overlap_ext_m,
                "overlap_stop_ids": set(route_stop_ids[is_overlap].tolist()),
                "total_stop_ids": set(route_stop_ids.tolist()),
            }
        )

    return summaries


def _direction_headway_median_min(
    stop_times: pd.DataFrame,
    window_start_s: int,
    window_end_s: int,
) -> float | None:
    """Mediana (min) dos intervalos entre passagens consecutivas de um sentido, medidos numa
    paragem de referência: a paragem servida por mais viagens desse sentido (desempate pelo
    stop_id, para ser determinístico). Medir numa paragem comum - e não na 1ª partida de cada
    viagem - evita misturar viagens curtas que começam a meio do percurso com as completas.
    Só contam passagens dentro de [window_start_s, window_end_s). None se houver < 2."""
    if stop_times.empty:
        return None
    trips_per_stop = stop_times.groupby("stop_id")["trip_id"].nunique()
    max_trips = trips_per_stop.max()
    ref_stop = sorted(trips_per_stop[trips_per_stop == max_trips].index.astype(str))[0]
    at_ref = stop_times[stop_times["stop_id"] == ref_stop]
    times = pd.to_numeric(at_ref["departure_seconds"], errors="coerce").dropna()
    times = times[(times >= window_start_s) & (times < window_end_s)]
    passages = np.sort(times.unique())
    if len(passages) < 2:
        return None
    return float(np.median(np.diff(passages))) / 60.0


def _line_trips_on_day(gtfs_smtuc, route_ids: list[str], reference_day: date) -> int:
    """Nº de viagens (ambos os sentidos) da linha no dia de referência - acompanha avg_freq_min
    porque, numa linha esporádica (ex.: 5 viagens/dia), um intervalo mediano de "275 min" diz pouco
    sozinho."""
    active = active_service_ids(gtfs_smtuc, reference_day)
    trips = gtfs_smtuc.trips
    mask = trips["route_id"].isin([str(r) for r in route_ids]) & trips["service_id"].isin(active)
    return int(mask.sum())


def _line_avg_frequency_min(
    gtfs_smtuc,
    route_ids: list[str],
    reference_day: date,
    window_start_h: float = FREQUENCY_WINDOW_START_H,
    window_end_h: float = FREQUENCY_WINDOW_END_H,
) -> float | None:
    """Intervalo típico (min) entre autocarros de uma linha no dia de referência.

    Por sentido (`direction_id`), mediana dos intervalos entre passagens numa paragem de
    referência, dentro da janela [window_start_h, window_end_h); o valor da linha é a média dos
    sentidos com dados. Antes misturavam-se TODOS os service_id (úteis + sábados + domingos) e os
    dois sentidos numa só lista de partidas, o que dava valores 3-4x mais baixos do que o real
    (ex.: linha 7 com 6.6 min quando passa de ~22 em ~22 min em cada sentido num dia útil).
    """
    if not route_ids:
        return None

    active = active_service_ids(gtfs_smtuc, reference_day)
    trips = gtfs_smtuc.trips[
        gtfs_smtuc.trips["route_id"].isin([str(r) for r in route_ids])
        & gtfs_smtuc.trips["service_id"].isin(active)
    ]
    if trips.empty or "departure_seconds" not in gtfs_smtuc.stop_times.columns:
        return None

    stop_times = gtfs_smtuc.stop_times[gtfs_smtuc.stop_times["trip_id"].isin(trips["trip_id"])]
    if stop_times.empty:
        return None

    if "direction_id" in trips.columns and trips["direction_id"].notna().any():
        direction_by_trip = dict(zip(trips["trip_id"], trips["direction_id"].fillna(-1).astype(str)))
    else:
        direction_by_trip = {str(t): "na" for t in trips["trip_id"]}
    directions = stop_times["trip_id"].map(direction_by_trip)

    window_start_s = int(float(window_start_h) * 3600)
    window_end_s = int(float(window_end_h) * 3600)
    medians = [
        m
        for _, group in stop_times.groupby(directions, sort=True)
        if (m := _direction_headway_median_min(group, window_start_s, window_end_s)) is not None
    ]
    if not medians:
        return None
    return round(float(np.mean(medians)), 1)


def line_to_route_ids(gtfs_smtuc) -> dict[str, list[str]]:
    routes_map_df = gtfs_smtuc.routes.copy()
    if routes_map_df.empty or "route_id" not in routes_map_df.columns:
        return {}

    name_col = "route_short_name" if "route_short_name" in routes_map_df.columns else "route_id"
    routes_map_df = routes_map_df[["route_id", name_col]].copy()
    routes_map_df["line"] = routes_map_df[name_col].astype(str)

    trips_enriched = gtfs_smtuc.trips.copy()
    trips_enriched = trips_enriched.merge(routes_map_df[["route_id", "line"]], on="route_id", how="left")
    trips_enriched["line"] = trips_enriched["line"].fillna(trips_enriched["route_id"])

    return (
        trips_enriched[["line", "route_id"]]
        .dropna()
        .drop_duplicates()
        .groupby("line")["route_id"]
        .apply(list)
        .to_dict()
    )


def _line_numeric_prefix(line: object) -> float | None:
    """Leading numeric part of a line label (e.g. "24T" -> 24, "103" -> 103, "5F" -> 5).

    Used to exclude only the genuinely-numbered->=100 special lines while keeping lettered
    variants (turno/reforço/feriado, etc.) of the base numbered lines in the overlap analysis.
    """
    match = re.match(r"^\s*(\d+)", str(line))
    if not match:
        return None
    return float(match.group(1))


def _project_root() -> Path:
    return PROJECT_ROOT


def _resolve_db_path(path: str | None = None) -> Path:
    rel = path if path is not None else LINE_METRICS_DB_PATH
    return (_project_root() / rel).resolve()


def line_metrics_db_path(path: str | Path | None = None, scenario: str | Scenario | None = None) -> Path:
    """Caminho ABSOLUTO do CSV de métricas de linha, para quem o lê do disco (dashboards, mapa de
    linhas, breakdown temporal, snapshots): `path` se for dado (relativo = à raiz do projeto, não
    à pasta onde se corre o comando) ou, sem ele, o do cenário
    (`outputs/overlap/line_metrics_db<sufixo>.csv`). Quem o lê assume que `load_line_metrics_db`
    já o validou/atualizou (o regenerate fá-lo antes de gerar as páginas)."""
    if path is None:
        path = scenario_output_path(LINE_METRICS_DB_PATH, get_scenario(scenario))
    return project_path(path)


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    """Grava `df` em `path` sem nunca deixar um CSV truncado: escreve primeiro num temporário na
    mesma pasta e só depois o troca pelo destino (os.replace é atómico no mesmo volume). Antes
    gravava-se diretamente - uma execução interrompida a meio deixava um CSV parcial que a
    validação de cache (que só lê a 1ª linha) aceitava como válido."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _dataset_signature(dataset: str) -> str:
    # Mesma pasta que load_gtfs() lê (gtfs.dataset_dir); os .txt estão diretamente nela (sem
    # subpastas - _find_gtfs_dir deixou de as aceitar).
    from gtfs_processing.gtfs import dataset_dir

    folder = dataset_dir(dataset, _project_root())
    txt_files = sorted(folder.glob("*.txt")) if folder.exists() else []
    raw = "|".join(
        f"{p.relative_to(folder).as_posix()}:{p.stat().st_size}:{p.stat().st_mtime_ns}"
        for p in txt_files
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _route_direction_radius_coverage_summaries(
    gtfs_smtuc,
    route_id: str,
    center_lat: float,
    center_lon: float,
    radius_m: float,
) -> list[dict]:
    summaries: list[dict] = []

    for route_lat, route_lon, _stop_ids, _ in iter_route_direction_stop_arrays(gtfs_smtuc, route_id):

        dist_to_center = haversine_m(
            np.full(route_lat.shape, center_lat, dtype=float),
            np.full(route_lon.shape, center_lon, dtype=float),
            route_lat,
            route_lon,
        )
        in_radius = dist_to_center <= radius_m

        seg_lengths = haversine_m(route_lat[:-1], route_lon[:-1], route_lat[1:], route_lon[1:])
        in_radius_segments = in_radius[:-1] & in_radius[1:]

        total_ext_m = float(seg_lengths.sum())
        in_radius_ext_m = float(seg_lengths[in_radius_segments].sum())

        if total_ext_m <= 0:
            continue

        summaries.append({"total_ext_m": total_ext_m, "in_radius_ext_m": in_radius_ext_m})

    return summaries


def _compute_line_metrics(
    smtuc_dataset: str,
    metrobus_dataset: str,
    walk_speed_m_min: float,
    stadium_lat: float,
    stadium_lon: float,
    radius_m: float,
    reference_day: date,
) -> pd.DataFrame:
    gtfs_smtuc = load_gtfs_cached(smtuc_dataset)
    gtfs_metro = load_gtfs_cached(metrobus_dataset)

    walk_catchment_m = walk_speed_m_min * SPATIAL_OVERLAP_WALK_MIN
    metro_stops = gtfs_metro.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
    if metro_stops.empty:
        return pd.DataFrame()

    routes_by_line = line_to_route_ids(gtfs_smtuc)
    if not routes_by_line:
        return pd.DataFrame()

    out_rows: list[dict] = []
    for line, route_ids in routes_by_line.items():
        line_summaries: list[dict] = []
        radius_summaries: list[dict] = []
        for route_id in route_ids:
            line_summaries.extend(_route_direction_summaries(gtfs_smtuc, route_id, metro_stops, walk_catchment_m))
            radius_summaries.extend(
                _route_direction_radius_coverage_summaries(gtfs_smtuc, route_id, stadium_lat, stadium_lon, radius_m)
            )

        if not line_summaries:
            continue

        total_ext_m = sum(s["total_ext_m"] for s in line_summaries)
        if total_ext_m <= 0:
            continue

        overlap_ext_m = sum(s["overlap_ext_m"] for s in line_summaries)
        # Uniões de stop_id (não somas por direção): uma paragem física partilhada entre os 2
        # sentidos de uma linha só deve contar uma vez - somar contagens por direção inflava
        # overlap_stops/total_stops até ~2-3x face ao nº real de paragens físicas (visível nas
        # colunas "overlap_stops / total_stops" dos dashboards).
        overlap_stop_ids: set[str] = set()
        total_stop_ids: set[str] = set()
        for s in line_summaries:
            overlap_stop_ids |= s.get("overlap_stop_ids", set())
            total_stop_ids |= s.get("total_stop_ids", set())

        row = {
            "line": str(line),
            "avg_freq_min": _line_avg_frequency_min(gtfs_smtuc, route_ids, reference_day),
            "ref_day_trips": _line_trips_on_day(gtfs_smtuc, route_ids, reference_day),
            "overlap_extension_m": round(overlap_ext_m, 1),
            "line_extension_m": round(total_ext_m, 1),
            "overlap_pct": round((overlap_ext_m / total_ext_m) * 100.0, 2),
            "overlap_stops": len(overlap_stop_ids),
            "overlap_stop_ids": ";".join(sorted(overlap_stop_ids)),
            "total_stops": len(total_stop_ids),
            "directions_considered": len(line_summaries),
            "radius_extension_m": np.nan,
            "radius_extension_pct": np.nan,
            "radius_m": float(radius_m),
            "temporal_overlaps_count": 0,
            "temporal_overlaps_pct": 0.0,
            "temporal_overlap_stop_ids": "",
        }

        if radius_summaries:
            radius_total_ext_m = sum(s["total_ext_m"] for s in radius_summaries)
            if radius_total_ext_m > 0:
                radius_ext_m = sum(s["in_radius_ext_m"] for s in radius_summaries)
                row["radius_extension_m"] = round(radius_ext_m, 1)
                row["radius_extension_pct"] = round((radius_ext_m / radius_total_ext_m) * 100.0, 2)

        out_rows.append(row)

    if not out_rows:
        return pd.DataFrame()

    df = pd.DataFrame(out_rows)
    numeric_prefix = df["line"].map(_line_numeric_prefix)
    return df[numeric_prefix.notna() & (numeric_prefix < 100)].reset_index(drop=True)


def build_line_metrics_db(
    smtuc_dataset: str | None = None,
    metrobus_dataset: str | None = None,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    stadium_lat: float = STADIUM_COORD[0],
    stadium_lon: float = STADIUM_COORD[1],
    radius_m: float = STADIUM_RADIUS_M,
    db_path: str | None = None,
    force_refresh: bool = False,
    reference_day: date | None = None,
    scenario: str | Scenario | None = None,
) -> pd.DataFrame:
    """Tabela de métricas por linha, cacheada em CSV.

    `scenario` (config.SCENARIOS; None = o cenário por omissão) dá os valores que não forem
    passados explicitamente: os datasets, o dia de referência e o ficheiro do cache
    (LINE_METRICS_DB_PATH com o sufixo do cenário, ex.: line_metrics_db_fase2.csv). O dia entra no
    cálculo de avg_freq_min e por isso também na chave do cache, tal como
    LINE_METRICS_SCHEMA_VERSION e a janela de frequência."""
    sc = get_scenario(scenario)
    smtuc_dataset = smtuc_dataset or sc.smtuc
    metrobus_dataset = metrobus_dataset or sc.metro
    if reference_day is None:
        from overlap.transit import resolve_reference_day

        reference_day = resolve_reference_day(scenario=sc)
    if db_path is None:
        # Lido na chamada (não na importação): os testes trocam overlap_db.LINE_METRICS_DB_PATH.
        db_path = scenario_output_path(LINE_METRICS_DB_PATH, sc)
    csv_path = _resolve_db_path(db_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    signature_smtuc = _dataset_signature(smtuc_dataset)
    signature_metro = _dataset_signature(metrobus_dataset)

    if csv_path.exists() and not force_refresh:
        cached = pd.read_csv(csv_path)
        if not cached.empty:
            meta_ok = (
                str(cached.iloc[0].get("__meta_smtuc_dataset", "")) == smtuc_dataset
                and str(cached.iloc[0].get("__meta_metro_dataset", "")) == metrobus_dataset
                and float(cached.iloc[0].get("__meta_walk_speed_m_min", -1.0)) == float(walk_speed_m_min)
                and float(cached.iloc[0].get("__meta_stadium_lat", 999.0)) == float(stadium_lat)
                and float(cached.iloc[0].get("__meta_stadium_lon", 999.0)) == float(stadium_lon)
                and float(cached.iloc[0].get("__meta_radius_m", -1.0)) == float(radius_m)
                and float(cached.iloc[0].get("__meta_spatial_overlap_walk_min", -1.0)) == float(SPATIAL_OVERLAP_WALK_MIN)
                and float(cached.iloc[0].get("__meta_temporal_overlap_max_min", -1.0)) == float(TEMPORAL_OVERLAP_MAX_MIN)
                and str(cached.iloc[0].get("__meta_sig_smtuc", "")) == signature_smtuc
                and str(cached.iloc[0].get("__meta_sig_metro", "")) == signature_metro
                and str(cached.iloc[0].get("__meta_reference_day", "")) == reference_day.isoformat()
                and str(cached.iloc[0].get("__meta_schema_version", "")) == str(LINE_METRICS_SCHEMA_VERSION)
                and str(cached.iloc[0].get("__meta_frequency_window_h", "")) == f"{FREQUENCY_WINDOW_START_H}-{FREQUENCY_WINDOW_END_H}"
            )
            if meta_ok:
                return cached.drop(columns=[c for c in cached.columns if c.startswith("__meta_")], errors="ignore")

    load_gtfs_cached.cache_clear()

    fresh = _compute_line_metrics(
        smtuc_dataset=smtuc_dataset,
        metrobus_dataset=metrobus_dataset,
        walk_speed_m_min=walk_speed_m_min,
        stadium_lat=stadium_lat,
        stadium_lon=stadium_lon,
        radius_m=radius_m,
        reference_day=reference_day,
    )
    if fresh.empty:
        return fresh

    # Compute temporal overlap candidates/counts per line before saving to CSV
    try:
        # Local import to avoid circular dependency between overlap_db and overlap
        from overlap.overlap import compute_temporal_overlaps_for_db

        fresh = compute_temporal_overlaps_for_db(
            fresh,
            smtuc_dataset=smtuc_dataset,
            metrobus_dataset=metrobus_dataset,
            walk_speed_m_min=walk_speed_m_min,
            temporal_overlap_max_min=TEMPORAL_OVERLAP_MAX_MIN,
            reference_day=reference_day,
        )
    except Exception as exc:
        # NÃO se grava nada: antes gravava-se o CSV com zeros nas colunas temporais, que ficava
        # em cache ("colado") até um force_refresh, e os dashboards mostravam 0 overlaps
        # temporais como se fosse um resultado. O cache anterior (se existir) fica intacto e o
        # erro sobe - o regenerate regista-o como falha e sai com código 1.
        raise RuntimeError(
            f"overlap temporal falhou - {csv_path.name} NÃO foi gravado (cache anterior intacto): {exc}"
        ) from exc

    fresh["__meta_smtuc_dataset"] = smtuc_dataset
    fresh["__meta_metro_dataset"] = metrobus_dataset
    fresh["__meta_walk_speed_m_min"] = float(walk_speed_m_min)
    fresh["__meta_stadium_lat"] = float(stadium_lat)
    fresh["__meta_stadium_lon"] = float(stadium_lon)
    fresh["__meta_radius_m"] = float(radius_m)
    fresh["__meta_spatial_overlap_walk_min"] = float(SPATIAL_OVERLAP_WALK_MIN)
    fresh["__meta_temporal_overlap_max_min"] = float(TEMPORAL_OVERLAP_MAX_MIN)
    fresh["__meta_sig_smtuc"] = signature_smtuc
    fresh["__meta_sig_metro"] = signature_metro
    fresh["__meta_reference_day"] = reference_day.isoformat()
    fresh["__meta_schema_version"] = str(LINE_METRICS_SCHEMA_VERSION)
    fresh["__meta_frequency_window_h"] = f"{FREQUENCY_WINDOW_START_H}-{FREQUENCY_WINDOW_END_H}"
    _atomic_write_csv(fresh, csv_path)

    return fresh.drop(columns=[c for c in fresh.columns if c.startswith("__meta_")], errors="ignore")


def load_line_metrics_db(
    db_path: str | None = None,
    smtuc_dataset: str | None = None,
    metrobus_dataset: str | None = None,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    stadium_lat: float = STADIUM_COORD[0],
    stadium_lon: float = STADIUM_COORD[1],
    radius_m: float = STADIUM_RADIUS_M,
    scenario: str | Scenario | None = None,
) -> pd.DataFrame:
    return build_line_metrics_db(
        scenario=scenario,
        smtuc_dataset=smtuc_dataset,
        metrobus_dataset=metrobus_dataset,
        walk_speed_m_min=walk_speed_m_min,
        stadium_lat=stadium_lat,
        stadium_lon=stadium_lon,
        radius_m=radius_m,
        db_path=db_path,
        force_refresh=False,
    )
