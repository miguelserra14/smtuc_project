from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from config import (
    OVERLAP_TABLE_TOP_N,
    REACHABILITY_MAX_BOARDING_WALK_MIN,
    SPATIAL_OVERLAP_WALK_MIN,
    REACHABILITY_MAX_MIN,
    REACHABILITY_MAX_TRANSFERS,
    REACHABILITY_MAX_TRANSFER_WALK_MIN,
    STADIUM_COORD,
    STADIUM_MIN_EXTENSION_PCT,
    STADIUM_RADIUS_M,
    TEMPORAL_OVERLAP_MAX_MIN,
    WALK_SPEED_M_MIN,
)
from gtfs_processing.scenarios import DEFAULT_DATASETS, DEFAULT_METRO_DATASET, DEFAULT_SMTUC_DATASET
from overlap.overlap_db import (
    build_line_metrics_db,
    load_line_metrics_db,
    load_gtfs_cached,
    line_to_route_ids,
    _line_numeric_prefix,
)
from gtfs_processing.geo import haversine_m
from gtfs_processing.gtfs_probe import active_service_ids, alias_day_mask, parse_day
from gtfs_processing.timeutil import hhmmss_to_seconds


def _filter_numeric_bus_lines(df: pd.DataFrame) -> pd.DataFrame:
    if "line" not in df.columns:
        return df
    numeric_prefix = df["line"].map(_line_numeric_prefix)
    return df[numeric_prefix.notna() & (numeric_prefix < 100)]


def line_overlap_top(
    smtuc_dataset: str = DEFAULT_SMTUC_DATASET,
    metrobus_dataset: str = DEFAULT_METRO_DATASET,
    top_n: int = OVERLAP_TABLE_TOP_N,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
) -> pd.DataFrame:
    base = build_line_metrics_db(
        smtuc_dataset=smtuc_dataset,
        metrobus_dataset=metrobus_dataset,
        walk_speed_m_min=walk_speed_m_min,
    )
    if base.empty:
        return pd.DataFrame()

    base = _filter_numeric_bus_lines(base)

    return base.sort_values(["overlap_pct", "overlap_extension_m"], ascending=False).head(top_n).reset_index(drop=True)


def line_low_overlap_near_stadium_top(
    stadium_lat: float = STADIUM_COORD[0],
    stadium_lon: float = STADIUM_COORD[1],
    radius_m: float = STADIUM_RADIUS_M,
    min_radius_extension_pct: float = STADIUM_MIN_EXTENSION_PCT,
    top_n: int = OVERLAP_TABLE_TOP_N,
    smtuc_dataset: str = DEFAULT_SMTUC_DATASET,
    metrobus_dataset: str = DEFAULT_METRO_DATASET,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
) -> pd.DataFrame:
    base = build_line_metrics_db(
        smtuc_dataset=smtuc_dataset,
        metrobus_dataset=metrobus_dataset,
        walk_speed_m_min=walk_speed_m_min,
        stadium_lat=stadium_lat,
        stadium_lon=stadium_lon,
        radius_m=radius_m,
    )
    if base.empty:
        return pd.DataFrame()

    base = _filter_numeric_bus_lines(base)

    if "radius_m" in base.columns:
        base = base[np.isclose(base["radius_m"].astype(float), float(radius_m), atol=1e-6)]

    filtered = base[base["radius_extension_pct"].fillna(-1) >= min_radius_extension_pct].copy()
    if filtered.empty:
        return filtered

    return (
        filtered.sort_values(
            ["overlap_pct", "overlap_extension_m", "radius_extension_pct"],
            ascending=[True, True, False],
        )
        .head(top_n)
        .reset_index(drop=True)
    )


def _service_day_masks(calendar_df: pd.DataFrame) -> dict[str, tuple[int, ...]]:
    day_cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if calendar_df is None or calendar_df.empty or "service_id" not in calendar_df.columns:
        return {}

    cal = calendar_df.copy()
    for day_col in day_cols:
        if day_col not in cal.columns:
            cal[day_col] = 0

    out: dict[str, tuple[int, ...]] = {}
    for row in cal[["service_id", *day_cols]].itertuples(index=False):
        out[str(row[0])] = tuple(int(v) for v in row[1:])
    return out


def _resolve_service_day_mask(
    service_id: str,
    calendar_masks: dict[str, tuple[int, ...]],
) -> tuple[int, ...] | None:
    """Resolve a service_id to its (mon..sun) weekly mask.

    Tries a direct calendar.txt lookup first, then falls back to alias-based resolution
    (e.g. "WD"/"SAT"/"SUN") for feeds where trips.txt's service_id namespace doesn't match
    calendar.txt's - same mismatch fixed in `active_service_ids`, needed here too since this
    compares service_id values taken straight from trips.txt/stop_times, not from calendar.txt.
    """
    mask = calendar_masks.get(str(service_id))
    if mask is not None:
        return mask
    return alias_day_mask(service_id)


def _service_days_overlap(
    smtuc_service_id: str,
    metro_service_id: str,
    smtuc_masks: dict[str, tuple[int, ...]],
    metro_masks: dict[str, tuple[int, ...]],
) -> bool:
    smtuc_mask = _resolve_service_day_mask(smtuc_service_id, smtuc_masks)
    metro_mask = _resolve_service_day_mask(metro_service_id, metro_masks)

    if smtuc_mask is None or metro_mask is None:
        return True

    return any((a == 1 and b == 1) for a, b in zip(smtuc_mask, metro_mask))


def _normalize_line_value(raw_line: object) -> str | None:
    if pd.isna(raw_line):
        return None

    line = str(raw_line).strip()
    if line.endswith(".0"):
        try:
            as_float = float(line)
            if as_float.is_integer():
                line = str(int(as_float))
        except ValueError:
            pass
    return line


_TEMPORAL_EVENT_COLUMNS = [
    "line",
    "smtuc_stop_id",
    "smtuc_stop_name",
    "time_sec",
    "time_hhmm",
    "hour",
    "nearby_metro_stops_count",
]


def _temporal_overlap_passages(
    lines: list[str],
    smtuc_dataset: str,
    metrobus_dataset: str,
    walk_speed_m_min: float,
    temporal_overlap_max_min: float,
    spatial_overlap_walk_min: float,
) -> tuple[pd.DataFrame, set[str]] | None:
    """Regra ÚNICA do overlap temporal (usada pelas métricas por linha e pela lista de eventos).

    Para cada linha pedida, considera TODAS as passagens SMTUC (cada linha de stop_times de cada
    viagem da linha, em qualquer serviço). Uma passagem é:
    - candidata espacial se houver alguma paragem do metro a <= velocidade x minutos a pé;
    - sobreposição temporal se, numa dessas paragens do metro, houver uma passagem do metro a
      <= `temporal_overlap_max_min` minutos (|diferença|) cujo serviço partilhe algum dia da
      semana com o da passagem SMTUC (`_service_days_overlap`; serviço impossível de resolver
      conta como partilhado - ver passo 3.4 do roadmap).

    Devolve (passagens, linhas_conhecidas): uma linha por passagem SMTUC com coordenadas, por
    ordem das linhas pedidas e, dentro de cada linha, pela ordem de stop_times.txt, com as
    colunas line, stop_id, stop_name, time_sec, nearby_metro_stops_count (0 = não é candidata) e
    temporal_overlap (bool); e o conjunto de linhas pedidas que existem no feed. None se o metro
    não tiver paragens ou horários (os chamadores mantêm então o que já tinham).

    Vetorizado (passo 5.1): distâncias numa matriz por coordenada única de paragem SMTUC e, por
    paragem SMTUC x serviço do metro, `searchsorted` sobre os horários ordenados do metro - em
    vez de um ciclo Python por passagem (~170 mil) com um ciclo interno por passagem do metro.
    """
    gtfs_smtuc = load_gtfs_cached(smtuc_dataset)
    gtfs_metro = load_gtfs_cached(metrobus_dataset)

    walk_catchment_m = walk_speed_m_min * spatial_overlap_walk_min
    threshold_s = int(float(temporal_overlap_max_min) * 60)

    metro_stops = gtfs_metro.stops[["stop_id", "stop_lat", "stop_lon"]].dropna()
    metro_st = gtfs_metro.stop_times[["trip_id", "stop_id", "arrival_seconds"]].merge(
        gtfs_metro.trips[["trip_id", "service_id"]], on="trip_id", how="left"
    )
    if metro_stops.empty or metro_st.empty:
        return None

    # Horários do metro por paragem e por serviço, já ordenados (para o searchsorted).
    metro_st = metro_st[metro_st["stop_id"].isin(metro_stops["stop_id"])]
    metro_sid = metro_st["service_id"].astype(str)  # serviço em falta -> "nan", como antes
    metro_times: dict[str, dict[str, np.ndarray]] = {}
    for (stop_id, sid), grp in metro_st.groupby([metro_st["stop_id"], metro_sid], sort=False)["arrival_seconds"]:
        metro_times.setdefault(stop_id, {})[sid] = np.sort(grp.to_numpy(dtype="int64"))

    metro_stop_ids = metro_stops["stop_id"].to_numpy()
    metro_lat = metro_stops["stop_lat"].to_numpy(dtype="float64")
    metro_lon = metro_stops["stop_lon"].to_numpy(dtype="float64")

    # Linhas pedidas -> viagens SMTUC (uma linha por par linha x viagem).
    routes_by_line = line_to_route_ids(gtfs_smtuc)
    wanted = [line for line in dict.fromkeys(lines) if line in routes_by_line]
    line_routes = pd.DataFrame(
        [(rank, line, str(rid)) for rank, line in enumerate(wanted) for rid in routes_by_line[line]],
        columns=["_line_rank", "line", "route_id"],
    )
    trips = gtfs_smtuc.trips[["trip_id", "service_id", "route_id"]].merge(line_routes, on="route_id")

    stop_cols = ["stop_id", "stop_lat", "stop_lon"] + (["stop_name"] if "stop_name" in gtfs_smtuc.stops.columns else [])
    st = gtfs_smtuc.stop_times[["trip_id", "stop_id", "arrival_seconds"]].copy()
    st["_pos"] = np.arange(len(st))
    passages = (
        st.merge(trips[["_line_rank", "line", "trip_id", "service_id"]], on="trip_id")
        .merge(gtfs_smtuc.stops[stop_cols], on="stop_id", how="left")
        .dropna(subset=["stop_lat", "stop_lon"])
        .sort_values(["_line_rank", "_pos"], kind="stable")
        .reset_index(drop=True)
    )
    passages["stop_name"] = passages["stop_name"].astype(str) if "stop_name" in passages.columns else ""
    passages["time_sec"] = passages["arrival_seconds"].astype("int64")
    smtuc_sid = passages["service_id"].astype(str).to_numpy()

    # Espacial: matriz (coordenadas únicas SMTUC x paragens do metro).
    coords = passages[["stop_lat", "stop_lon"]].to_numpy(dtype="float64")
    uniq, coord_idx = np.unique(coords, axis=0, return_inverse=True)
    coord_idx = coord_idx.reshape(-1)
    near = haversine_m(uniq[:, 0:1], uniq[:, 1:2], metro_lat[None, :], metro_lon[None, :]) <= walk_catchment_m
    nearby_count = near.sum(axis=1)
    passages["nearby_metro_stops_count"] = nearby_count[coord_idx].astype("int64")

    # Compatibilidade de dias entre serviços (poucos valores distintos de cada lado).
    smtuc_masks = _service_day_masks(gtfs_smtuc.calendar)
    metro_masks = _service_day_masks(gtfs_metro.calendar)
    metro_sids = sorted({sid for by_sid in metro_times.values() for sid in by_sid})
    compatible = {
        (s, m): _service_days_overlap(s, m, smtuc_masks, metro_masks)
        for s in set(smtuc_sid)
        for m in metro_sids
    }

    times = passages["time_sec"].to_numpy()
    overlap = np.zeros(len(passages), dtype=bool)
    order = np.argsort(coord_idx, kind="stable")
    bounds = np.searchsorted(coord_idx[order], np.arange(len(uniq) + 1))
    for u in np.flatnonzero(nearby_count):
        rows = order[bounds[u]:bounds[u + 1]]
        # horários do metro nas paragens próximas, juntados por serviço
        by_sid: dict[str, list[np.ndarray]] = {}
        for stop_id in metro_stop_ids[near[u]]:
            for sid, arr in metro_times.get(stop_id, {}).items():
                by_sid.setdefault(sid, []).append(arr)
        for sid, arrays in by_sid.items():
            ok_rows = rows[np.fromiter((compatible[(s, sid)] for s in smtuc_sid[rows]), dtype=bool, count=len(rows))]
            ok_rows = ok_rows[~overlap[ok_rows]]
            if len(ok_rows) == 0:
                continue
            metro = np.sort(np.concatenate(arrays))
            t = times[ok_rows]
            pos = np.searchsorted(metro, t)
            before = np.abs(t - metro[np.clip(pos - 1, 0, len(metro) - 1)])
            after = np.abs(metro[np.clip(pos, 0, len(metro) - 1)] - t)
            overlap[ok_rows] |= np.minimum(before, after) <= threshold_s
    passages["temporal_overlap"] = overlap

    cols = ["line", "stop_id", "stop_name", "time_sec", "nearby_metro_stops_count", "temporal_overlap"]
    return passages[cols], set(wanted)


def compute_temporal_overlaps_for_db(
    metrics_df: pd.DataFrame,
    smtuc_dataset: str = DEFAULT_SMTUC_DATASET,
    metrobus_dataset: str = DEFAULT_METRO_DATASET,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    temporal_overlap_max_min: float = TEMPORAL_OVERLAP_MAX_MIN,
    spatial_overlap_walk_min: float = SPATIAL_OVERLAP_WALK_MIN,
) -> pd.DataFrame:
    """Adiciona ao DataFrame de métricas, por linha, as colunas de overlap temporal (regra em
    `_temporal_overlap_passages`): candidatos espaciais, passagens com overlap, % e paragens."""
    if metrics_df.empty:
        return metrics_df

    if "temporal_spatial_candidates_count" not in metrics_df.columns:
        metrics_df["temporal_spatial_candidates_count"] = 0
    if "temporal_overlaps_count" not in metrics_df.columns:
        metrics_df["temporal_overlaps_count"] = 0
    if "temporal_overlaps_pct" not in metrics_df.columns:
        metrics_df["temporal_overlaps_pct"] = 0.0
    if "temporal_overlap_stop_ids" not in metrics_df.columns:
        metrics_df["temporal_overlap_stop_ids"] = ""

    lines = [_normalize_line_value(v) for v in metrics_df["line"]] if "line" in metrics_df.columns else []
    result = _temporal_overlap_passages(
        [line for line in lines if line],
        smtuc_dataset,
        metrobus_dataset,
        walk_speed_m_min,
        temporal_overlap_max_min,
        spatial_overlap_walk_min,
    )
    if result is None:
        return metrics_df
    passages, known_lines = result

    candidates = passages[passages["nearby_metro_stops_count"] > 0]
    hits = candidates[candidates["temporal_overlap"]]
    n_candidates = candidates.groupby("line").size().to_dict()
    n_hits = hits.groupby("line").size().to_dict()
    hit_stops = hits.groupby("line")["stop_id"].agg(lambda s: ";".join(sorted(set(s)))).to_dict()

    for idx, line in zip(metrics_df.index, lines):
        if not line or line not in known_lines:
            continue
        total = int(n_candidates.get(line, 0))
        overlaps = int(n_hits.get(line, 0))
        metrics_df.at[idx, "temporal_spatial_candidates_count"] = total
        metrics_df.at[idx, "temporal_overlaps_count"] = overlaps
        metrics_df.at[idx, "temporal_overlap_stop_ids"] = hit_stops.get(line, "")
        metrics_df.at[idx, "temporal_overlaps_pct"] = round((overlaps / total) * 100, 2) if total > 0 else 0.0

    return metrics_df


def temporal_overlap_events_for_metrics(
    metrics_df: pd.DataFrame,
    smtuc_dataset: str = DEFAULT_SMTUC_DATASET,
    metrobus_dataset: str = DEFAULT_METRO_DATASET,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    temporal_overlap_max_min: float = TEMPORAL_OVERLAP_MAX_MIN,
    spatial_overlap_walk_min: float = SPATIAL_OVERLAP_WALK_MIN,
) -> pd.DataFrame:
    """Uma linha por passagem SMTUC com overlap temporal (mesma regra das métricas, ver
    `_temporal_overlap_passages`), pela ordem das linhas de `metrics_df` (uma linha repetida em
    `metrics_df` repete os seus eventos)."""
    empty = pd.DataFrame(columns=_TEMPORAL_EVENT_COLUMNS)
    if metrics_df.empty or "line" not in metrics_df.columns:
        return empty

    lines = [_normalize_line_value(v) for v in metrics_df["line"]]
    result = _temporal_overlap_passages(
        [line for line in lines if line],
        smtuc_dataset,
        metrobus_dataset,
        walk_speed_m_min,
        temporal_overlap_max_min,
        spatial_overlap_walk_min,
    )
    if result is None:
        return empty
    passages, known_lines = result

    hits = passages[passages["temporal_overlap"]]
    by_line = {line: grp for line, grp in hits.groupby("line", sort=False)}
    parts = [by_line[line] for line in lines if line and line in known_lines and line in by_line]
    if not parts:
        return empty

    events = pd.concat(parts, ignore_index=True)
    secs = events["time_sec"].astype("int64")
    hours = secs // 3600
    return pd.DataFrame(
        {
            "line": events["line"],
            "smtuc_stop_id": events["stop_id"],
            "smtuc_stop_name": events["stop_name"],
            "time_sec": secs,
            "time_hhmm": [f"{h:02d}:{m:02d}" for h, m in zip(hours, (secs % 3600) // 60)],
            "hour": hours,
            "nearby_metro_stops_count": events["nearby_metro_stops_count"],
        }
    )


def _current_day_time() -> tuple[str, str]:
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")


def _next_service_relevant_time(
    day_str: str,
    from_time_str: str,
    datasets: tuple[str, ...],
    origin_lat: float,
    origin_lon: float,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    max_board_walk_min: float = 20.0,
    latest_time_str: str | None = None,
    fallback_to_from_time: bool = True,
) -> str | None:
    """Return the next boardable departure time from the given origin across datasets.

    If no relevant departure is found, keeps the original time.
    """
    day = parse_day(day_str)
    t0 = int(hhmmss_to_seconds(from_time_str))
    t1 = int(hhmmss_to_seconds(latest_time_str)) if latest_time_str else None
    board_walk_m = float(walk_speed_m_min) * float(max_board_walk_min)

    best_departure_s: int | None = None

    for dataset in datasets:
        gtfs = load_gtfs_cached(dataset)

        stops = gtfs.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
        if stops.empty:
            continue

        d_m = haversine_m(
            origin_lat,
            origin_lon,
            stops["stop_lat"].astype(float).to_numpy(),
            stops["stop_lon"].astype(float).to_numpy(),
        )
        boardable_ids = set(stops.loc[d_m <= board_walk_m, "stop_id"].astype(str).tolist())
        if not boardable_ids:
            continue

        active_services = active_service_ids(gtfs, day)
        trips = gtfs.trips[["trip_id", "service_id"]].copy()
        # Filtra SEMPRE (mesmo com o conjunto vazio = dia sem serviço) - ver active_service_ids.
        trips = trips[trips["service_id"].isin(active_services)]
        if trips.empty:
            continue

        st = gtfs.stop_times[["trip_id", "stop_id", "departure_seconds"]].copy()
        st = st.merge(trips, on="trip_id", how="inner")
        if st.empty:
            continue

        dep_mask = (
            st["stop_id"].isin(boardable_ids)
            & st["departure_seconds"].notna()
            & (st["departure_seconds"].astype(float) >= float(t0))
        )
        if t1 is not None:
            dep_mask = dep_mask & (st["departure_seconds"].astype(float) <= float(t1))

        dep = st[dep_mask]["departure_seconds"]

        if dep.empty:
            continue

        dataset_best = int(dep.astype(float).min())
        if best_departure_s is None or dataset_best < best_departure_s:
            best_departure_s = dataset_best

    if best_departure_s is None:
        return from_time_str if fallback_to_from_time else None

    h = best_departure_s // 3600
    m = (best_departure_s % 3600) // 60
    s = best_departure_s % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _reach_bin_label(minutes: float) -> str:
    if minutes <= 10.0:
        return "0-10"
    if minutes <= 15.0:
        return "10-15"
    if minutes <= 30.0:
        return "15-30"
    if minutes <= 60.0:
        return "30-60"
    return ">60"


def _reachable_stops_for_dataset_now(
    dataset: str,
    origin_lat: float,
    origin_lon: float,
    day_str: str,
    time_str: str,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    max_min: float = REACHABILITY_MAX_MIN,
    max_board_walk_min: float = REACHABILITY_MAX_BOARDING_WALK_MIN,
) -> pd.DataFrame:
    gtfs = load_gtfs_cached(dataset)

    stops = gtfs.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
    if stops.empty:
        return pd.DataFrame(columns=["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"])

    stop_ids = stops["stop_id"].to_numpy()
    stop_lats = stops["stop_lat"].astype(float).to_numpy()
    stop_lons = stops["stop_lon"].astype(float).to_numpy()

    direct_walk_m = haversine_m(origin_lat, origin_lon, stop_lats, stop_lons)
    direct_walk_min = direct_walk_m / float(walk_speed_m_min)

    reach_by_stop = pd.Series(direct_walk_min, index=stop_ids, dtype="float64")

    day = parse_day(day_str)
    t0 = int(hhmmss_to_seconds(time_str))
    active_services = active_service_ids(gtfs, day)

    trips = gtfs.trips[["trip_id", "service_id"]].copy()
    # Filtra SEMPRE (mesmo com o conjunto vazio = dia sem serviço) - ver active_service_ids.
    trips = trips[trips["service_id"].isin(active_services)]
    if trips.empty:
        out = stops.copy()
        out["dataset"] = dataset
        out["reach_min"] = reach_by_stop.reindex(out["stop_id"]).astype(float).to_numpy()
        return out[["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"]]

    st_cols = ["trip_id", "stop_id", "stop_sequence", "departure_seconds", "arrival_seconds"]
    st = gtfs.stop_times[st_cols].copy()
    st = st.merge(trips, on="trip_id", how="inner")
    if st.empty:
        out = stops.copy()
        out["dataset"] = dataset
        out["reach_min"] = reach_by_stop.reindex(out["stop_id"]).astype(float).to_numpy()
        return out[["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"]]

    walk_df = pd.DataFrame({"stop_id": stop_ids, "walk_to_board_min": direct_walk_min})
    boardable_ids = set(walk_df.loc[walk_df["walk_to_board_min"] <= float(max_board_walk_min), "stop_id"].astype(str))

    board = st[
        st["stop_id"].isin(boardable_ids)
        & st["departure_seconds"].notna()
        & (st["departure_seconds"].astype(float) >= float(t0))
    ][["trip_id", "stop_id", "stop_sequence", "departure_seconds"]].copy()

    if not board.empty:
        board = board.merge(walk_df, on="stop_id", how="left")

        alight = st[["trip_id", "stop_id", "stop_sequence", "arrival_seconds"]].copy()
        alight = alight.rename(
            columns={
                "stop_id": "alight_stop_id",
                "stop_sequence": "alight_seq",
                "arrival_seconds": "alight_arrival_s",
            }
        )

        board = board.rename(
            columns={
                "stop_sequence": "board_seq",
                "departure_seconds": "board_dep_s",
            }
        )

        pairs = board.merge(alight, on="trip_id", how="inner")
        pairs = pairs[
            pairs["alight_arrival_s"].notna()
            & (pairs["alight_seq"].astype(float) > pairs["board_seq"].astype(float))
        ].copy()

        if not pairs.empty:
            pairs["total_min"] = (
                pairs["walk_to_board_min"].astype(float)
                + (pairs["board_dep_s"].astype(float) - float(t0)) / 60.0
                + (pairs["alight_arrival_s"].astype(float) - pairs["board_dep_s"].astype(float)) / 60.0
            )
            pairs = pairs[pairs["total_min"] >= 0.0]

            if not pairs.empty:
                best_transit = pairs.groupby("alight_stop_id", as_index=False).agg(reach_min=("total_min", "min"))
                best_transit["alight_stop_id"] = best_transit["alight_stop_id"].astype(str)

                for _, row in best_transit.iterrows():
                    sid = str(row["alight_stop_id"])
                    best = float(row["reach_min"])
                    current = float(reach_by_stop.get(sid, np.inf))
                    if best < current:
                        reach_by_stop.loc[sid] = best

    out = stops.copy()
    out["dataset"] = dataset
    out["reach_min"] = reach_by_stop.reindex(out["stop_id"]).astype(float).to_numpy()
    out = out[out["reach_min"].notna()].copy()
    out = out[out["reach_min"] <= float(max_min)].copy()
    return out[["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"]]


def _reachable_stops_multimodal_now(
    datasets: tuple[str, ...],
    origin_lat: float,
    origin_lon: float,
    day_str: str,
    time_str: str,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    max_min: float = REACHABILITY_MAX_MIN,
    max_board_walk_min: float = REACHABILITY_MAX_BOARDING_WALK_MIN,
    max_transfer_walk_min: float = REACHABILITY_MAX_TRANSFER_WALK_MIN,
    max_transfers: int = REACHABILITY_MAX_TRANSFERS,
) -> pd.DataFrame:
    """
    Compute stop-level multimodal reachability allowing chained trips with transfers.

    Model:
    - Initial walk from origin to boardable stops.
    - Ride on a trip to any downstream stop.
    - Walk transfer between nearby stops, then board another trip.
    """
    day = parse_day(day_str)
    t0 = int(hhmmss_to_seconds(time_str))

    all_stops_parts: list[pd.DataFrame] = []
    trip_tables: list[pd.DataFrame] = []

    for dataset in datasets:
        gtfs = load_gtfs_cached(dataset)

        stops = gtfs.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
        if stops.empty:
            continue

        stops["global_stop_id"] = dataset + ":" + stops["stop_id"]
        stops["dataset"] = dataset
        all_stops_parts.append(stops[["dataset", "stop_id", "global_stop_id", "stop_lat", "stop_lon"]])

        trips = gtfs.trips[["trip_id", "service_id"]].copy()
        active_services = active_service_ids(gtfs, day)
        # Filtra SEMPRE (mesmo com o conjunto vazio = dia sem serviço) - ver active_service_ids.
        trips = trips[trips["service_id"].isin(active_services)]
        if trips.empty:
            continue

        st_cols = ["trip_id", "stop_id", "stop_sequence", "departure_seconds", "arrival_seconds"]
        stop_times = gtfs.stop_times[st_cols].copy()
        stop_times = stop_times.merge(trips[["trip_id"]], on="trip_id", how="inner")
        if stop_times.empty:
            continue

        stop_times["global_trip_id"] = dataset + ":" + stop_times["trip_id"]
        stop_times["global_stop_id"] = dataset + ":" + stop_times["stop_id"]
        stop_times["dep_s"] = pd.to_numeric(stop_times["departure_seconds"], errors="coerce")
        stop_times["arr_s"] = pd.to_numeric(stop_times["arrival_seconds"], errors="coerce")
        stop_times["dep_s"] = stop_times["dep_s"].fillna(stop_times["arr_s"])
        stop_times["arr_s"] = stop_times["arr_s"].fillna(stop_times["dep_s"])
        stop_times = stop_times.dropna(subset=["dep_s", "arr_s", "stop_sequence"])
        if stop_times.empty:
            continue

        stop_times = stop_times[["global_trip_id", "global_stop_id", "stop_sequence", "dep_s", "arr_s"]]
        trip_tables.append(stop_times)

    if not all_stops_parts:
        return pd.DataFrame(columns=["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"])

    all_stops = pd.concat(all_stops_parts, ignore_index=True).drop_duplicates(subset=["global_stop_id"]) 
    all_stops["stop_lat"] = all_stops["stop_lat"].astype(float)
    all_stops["stop_lon"] = all_stops["stop_lon"].astype(float)

    global_stop_ids = all_stops["global_stop_id"].astype(str).tolist()
    stop_lats = all_stops["stop_lat"].to_numpy(dtype=float)
    stop_lons = all_stops["stop_lon"].to_numpy(dtype=float)

    # Initial access walk: restrict to boardable radius to avoid unrealistic long pre-walks.
    direct_walk_m = haversine_m(origin_lat, origin_lon, stop_lats, stop_lons)
    direct_walk_min = direct_walk_m / float(walk_speed_m_min)

    inf_s = float("inf")
    arrivals_prev_s = pd.Series(inf_s, index=global_stop_ids, dtype="float64")
    boardable_mask = direct_walk_min <= float(max_board_walk_min)
    if np.any(boardable_mask):
        arrivals_prev_s.loc[np.array(global_stop_ids)[boardable_mask]] = (
            float(t0) + direct_walk_min[boardable_mask] * 60.0
        )

    if not trip_tables:
        out = all_stops[["dataset", "stop_id", "stop_lat", "stop_lon"]].copy()
        out["reach_min"] = (arrivals_prev_s.reindex(all_stops["global_stop_id"]).to_numpy(dtype=float) - float(t0)) / 60.0
        out = out[np.isfinite(out["reach_min"])].copy()
        out = out[out["reach_min"] <= float(max_min)].copy()
        return out

    full_stop_times = pd.concat(trip_tables, ignore_index=True)
    full_stop_times = full_stop_times.sort_values(["global_trip_id", "stop_sequence"]).reset_index(drop=True)

    trips_grouped: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for _, group in full_stop_times.groupby("global_trip_id", sort=False):
        stop_arr = group["global_stop_id"].astype(str).to_numpy()
        dep_arr = group["dep_s"].astype(float).to_numpy()
        arr_arr = group["arr_s"].astype(float).to_numpy()
        if len(stop_arr) >= 2:
            trips_grouped.append((stop_arr, dep_arr, arr_arr))

    transfer_walk_m = float(max_transfer_walk_min) * float(walk_speed_m_min)
    stop_id_to_idx = {sid: i for i, sid in enumerate(global_stop_ids)}
    max_boardings = max(1, int(max_transfers) + 1)

    for _round in range(max_boardings):
        arrivals_curr_s = arrivals_prev_s.copy()
        changed_stop_ids: set[str] = set()

        # Trip relaxation: board any feasible trip and alight at any downstream stop.
        for trip_stops, trip_dep_s, trip_arr_s in trips_grouped:
            on_board = False
            for i in range(len(trip_stops)):
                sid = str(trip_stops[i])
                arr_s = float(trip_arr_s[i])

                # Alight/relax using the trip boarded at a PREVIOUS stop (on_board carried over
                # from the last iteration) - must run before the boarding check below, not
                # after. Otherwise a trip that dwells at its own boarding stop (arr_s < dep_s
                # there) would overwrite that stop's own arrival with the trip's scheduled
                # arrival, which can be earlier than when the passenger actually got there -
                # claiming a stop is reachable sooner than physically possible. Real GTFS feeds
                # in this project currently have zero dwell everywhere so this was dormant, but
                # is not guaranteed to stay that way (e.g. a modeled layover at a transfer hub).
                if on_board and arr_s < float(arrivals_curr_s.get(sid, inf_s)):
                    arrivals_curr_s.loc[sid] = arr_s
                    changed_stop_ids.add(sid)

                if not on_board:
                    earliest_at_stop_s = float(arrivals_prev_s.get(sid, inf_s))
                    dep_s = float(trip_dep_s[i])
                    if np.isfinite(earliest_at_stop_s) and dep_s >= earliest_at_stop_s and dep_s >= float(t0):
                        on_board = True

        # Transfer-walk relaxation from stops improved BY A TRIP in this round (RAPTOR footpaths).
        # A caminhada parte sempre da chegada de viagem fotografada ANTES deste ciclo (snapshot),
        # nunca de um valor já baixado por outra caminhada no mesmo ciclo. Antes lia-se
        # arrivals_curr_s, que este próprio ciclo vai alterando: A->B a pé e depois B->C a pé
        # encadeavam-se (ultrapassando o limite de max_transfer_walk_min) ou não, conforme a
        # ordem de iteração do set changed_stop_ids - que depende de PYTHONHASHSEED, aleatório
        # em cada execução. Resultado: isócronas diferentes a cada regeneração (1072-1090
        # paragens alcançáveis a partir do estádio, medido). Com o snapshot o resultado é
        # independente da ordem; `sorted` fica só por legibilidade/reprodutibilidade de debug.
        if changed_stop_ids:
            trip_arrival_s = {sid: float(arrivals_curr_s.get(sid, inf_s)) for sid in changed_stop_ids}
            for sid in sorted(changed_stop_ids):
                src_idx = stop_id_to_idx.get(sid)
                if src_idx is None:
                    continue
                base_arrival_s = trip_arrival_s[sid]
                if not np.isfinite(base_arrival_s):
                    continue

                dists_m = haversine_m(stop_lats[src_idx], stop_lons[src_idx], stop_lats, stop_lons)
                near_idx = np.where(dists_m <= transfer_walk_m)[0]
                if len(near_idx) == 0:
                    continue

                walk_sec = (dists_m[near_idx] / float(walk_speed_m_min)) * 60.0
                candidate_arrival_s = base_arrival_s + walk_sec

                for j, cand_s in zip(near_idx, candidate_arrival_s):
                    nid = global_stop_ids[int(j)]
                    if cand_s < float(arrivals_curr_s.get(nid, inf_s)):
                        arrivals_curr_s.loc[nid] = float(cand_s)

        if not np.any((arrivals_curr_s - arrivals_prev_s) < -1e-9):
            break
        arrivals_prev_s = arrivals_curr_s

    out = all_stops[["dataset", "stop_id", "stop_lat", "stop_lon", "global_stop_id"]].copy()
    out["reach_min"] = (arrivals_prev_s.reindex(out["global_stop_id"]).to_numpy(dtype=float) - float(t0)) / 60.0
    out = out[np.isfinite(out["reach_min"])].copy()
    out = out[out["reach_min"] >= 0.0].copy()
    out = out[out["reach_min"] <= float(max_min)].copy()
    return out[["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"]]


def compute_bgri_reachability_now(
    merged_bgri,
    origin_lat: float = STADIUM_COORD[0],
    origin_lon: float = STADIUM_COORD[1],
    datasets: tuple[str, ...] = DEFAULT_DATASETS,
    day_str: str | None = None,
    time_str: str | None = None,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    max_min: float = REACHABILITY_MAX_MIN,
    max_transfers: int = REACHABILITY_MAX_TRANSFERS,
) -> pd.DataFrame:
    """Calcula tempo mínimo estimado para alcançar cada zona BGRI no momento atual."""
    auto_time_mode = time_str is None

    if day_str is None or time_str is None:
        now_day, now_time = _current_day_time()
        day_str = day_str or now_day
        time_str = time_str or now_time
        # Prefer a representative service time. Outside useful daytime hours,
        # prioritize a morning peak slot between 08:00 and 09:00.
        if time_str < "08:00:00" or time_str > "21:00:00":
            morning_peak_time = _next_service_relevant_time(
                day_str=day_str,
                from_time_str="08:00:00",
                latest_time_str="09:00:00",
                fallback_to_from_time=False,
                datasets=datasets,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                walk_speed_m_min=walk_speed_m_min,
            )
            if morning_peak_time is not None:
                time_str = morning_peak_time
            else:
                time_str = _next_service_relevant_time(
                    day_str=day_str,
                    from_time_str="08:00:00",
                    datasets=datasets,
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    walk_speed_m_min=walk_speed_m_min,
                )
        else:
            # During daytime, keep the next boardable time from now.
            time_str = _next_service_relevant_time(
                day_str=day_str,
                from_time_str=time_str,
                datasets=datasets,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                walk_speed_m_min=walk_speed_m_min,
            )

    stop_df = _reachable_stops_multimodal_now(
        datasets=datasets,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        day_str=day_str,
        time_str=time_str,
        walk_speed_m_min=walk_speed_m_min,
        max_min=max_min,
        max_transfers=max_transfers,
    )

    if stop_df.empty:
        out = merged_bgri.copy()
        out["reach_min"] = np.inf
        out["reach_mode"] = "a pé"
        out["reach_bin"] = ">60"
        out["reach_day"] = day_str
        out["reach_time"] = time_str
        return out

    stop_lat = stop_df["stop_lat"].astype(float).to_numpy()
    stop_lon = stop_df["stop_lon"].astype(float).to_numpy()
    stop_reach = stop_df["reach_min"].astype(float).to_numpy()

    gdf_3763 = merged_bgri.to_crs("EPSG:3763").copy()
    centroids = gdf_3763.geometry.centroid
    centroids_ll = centroids.to_crs("EPSG:4326")
    cent_lat = centroids_ll.y.astype(float).to_numpy()
    cent_lon = centroids_ll.x.astype(float).to_numpy()

    direct_walk_min = haversine_m(origin_lat, origin_lon, cent_lat, cent_lon) / float(walk_speed_m_min)

    pt_best_min = np.full(shape=len(gdf_3763), fill_value=np.inf, dtype="float64")
    for idx in range(len(gdf_3763)):
        d_to_stops_m = haversine_m(cent_lat[idx], cent_lon[idx], stop_lat, stop_lon)
        candidate = stop_reach + (d_to_stops_m / float(walk_speed_m_min))
        if len(candidate) > 0:
            pt_best_min[idx] = float(np.min(candidate))

    reach_min = np.minimum(direct_walk_min, pt_best_min)
    reach_mode = np.where(pt_best_min + 1e-9 < direct_walk_min, "transporte público", "a pé")

    # If automatic "now" selection still yields no PT wins (e.g., night hours),
    # fallback to a service-relevant morning slot.
    if auto_time_mode and not np.any(reach_mode == "transporte público"):
        morning_time = _next_service_relevant_time(
            day_str=day_str,
            from_time_str="08:00:00",
            latest_time_str="09:00:00",
            fallback_to_from_time=False,
            datasets=datasets,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            walk_speed_m_min=walk_speed_m_min,
        )
        if morning_time is not None and morning_time != time_str:
            return compute_bgri_reachability_now(
                merged_bgri=merged_bgri,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                datasets=datasets,
                day_str=day_str,
                time_str=morning_time,
                walk_speed_m_min=walk_speed_m_min,
                max_min=max_min,
                max_transfers=max_transfers,  # antes omitido -> caía no default do config
            )

    out = merged_bgri.copy()
    out["reach_min"] = reach_min
    out["reach_mode"] = reach_mode
    out["reach_bin"] = pd.Series(reach_min).apply(_reach_bin_label).astype(str)
    out["reach_day"] = str(day_str)
    out["reach_time"] = str(time_str)
    return out
