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
from overlap.overlap_db import (
    build_line_metrics_db,
    load_line_metrics_db,
    _load_gtfs_cached,
    _line_to_route_ids,
    _line_numeric_prefix,
)
from gtfs_processing.gtfs_probe import _active_service_ids, _parse_day, _to_seconds


def _filter_numeric_bus_lines(df: pd.DataFrame) -> pd.DataFrame:
    if "line" not in df.columns:
        return df
    numeric_prefix = df["line"].map(_line_numeric_prefix)
    return df[numeric_prefix.notna() & (numeric_prefix < 100)]


def line_overlap_top(
    smtuc_dataset: str = "smtuc",
    metrobus_dataset: str = "metrobus",
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
    smtuc_dataset: str = "smtuc",
    metrobus_dataset: str = "metrobus",
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


def _get_time_seconds(row):
    """Extrai segundos desde meia-noite de uma linha de stop_times."""
    if "arrival_seconds" in row and pd.notna(row["arrival_seconds"]):
        try:
            return int(row["arrival_seconds"])
        except (ValueError, TypeError):
            pass
    if "departure_seconds" in row and pd.notna(row["departure_seconds"]):
        try:
            return int(row["departure_seconds"])
        except (ValueError, TypeError):
            pass
    return None


def _service_day_masks(calendar_df: pd.DataFrame) -> dict[str, tuple[int, ...]]:
    day_cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if calendar_df is None or calendar_df.empty or "service_id" not in calendar_df.columns:
        return {}

    cal = calendar_df.copy()
    for day_col in day_cols:
        if day_col not in cal.columns:
            cal[day_col] = 0

    out: dict[str, tuple[int, ...]] = {}
    for _, row in cal.iterrows():
        service_id = str(row["service_id"])
        out[service_id] = tuple(int(row[day_col]) for day_col in day_cols)
    return out


def _service_days_overlap(
    smtuc_service_id: str,
    metro_service_id: str,
    smtuc_masks: dict[str, tuple[int, ...]],
    metro_masks: dict[str, tuple[int, ...]],
) -> bool:
    smtuc_mask = smtuc_masks.get(str(smtuc_service_id))
    metro_mask = metro_masks.get(str(metro_service_id))

    if smtuc_mask is None or metro_mask is None:
        return True

    return any((a == 1 and b == 1) for a, b in zip(smtuc_mask, metro_mask))


def _distances_from_point_m(
    query_lat: float,
    query_lon: float,
    ref_lat: np.ndarray,
    ref_lon: np.ndarray,
) -> np.ndarray:
    r = 6371000.0
    q_lat_r = np.radians(float(query_lat))
    q_lon_r = np.radians(float(query_lon))
    ref_lat_r = np.radians(ref_lat)
    ref_lon_r = np.radians(ref_lon)

    dlat = ref_lat_r - q_lat_r
    dlon = ref_lon_r - q_lon_r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(q_lat_r) * np.cos(ref_lat_r) * (np.sin(dlon / 2.0) ** 2)
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return r * c


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


def compute_temporal_overlaps_for_db(
    metrics_df: pd.DataFrame,
    smtuc_dataset: str = "smtuc",
    metrobus_dataset: str = "metrobus",
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    temporal_overlap_max_min: float = TEMPORAL_OVERLAP_MAX_MIN,
) -> pd.DataFrame:
    """Adiciona colunas de overlap temporal ao DataFrame de métricas."""
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

    gtfs_smtuc = _load_gtfs_cached(smtuc_dataset)
    gtfs_metro = _load_gtfs_cached(metrobus_dataset)

    walk_catchment_m = walk_speed_m_min * SPATIAL_OVERLAP_WALK_MIN
    temporal_threshold_s = int(float(temporal_overlap_max_min) * 60)
    metro_stops = gtfs_metro.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
    metro_stops["stop_id"] = metro_stops["stop_id"].astype(str)

    metro_trips = gtfs_metro.trips[["trip_id", "service_id"]].copy()
    metro_stop_times = gtfs_metro.stop_times.copy().merge(metro_trips, on="trip_id", how="left")
    
    if metro_stops.empty or metro_stop_times.empty:
        return metrics_df
    
    # Preparar dados Metrobus
    metro_stop_times_with_times = metro_stop_times.copy()
    metro_stop_times_with_times["stop_id"] = metro_stop_times_with_times["stop_id"].astype(str)
    metro_stop_times_with_times["service_id"] = metro_stop_times_with_times["service_id"].astype(str)
    metro_stop_times_with_times["time_sec"] = metro_stop_times_with_times.apply(_get_time_seconds, axis=1)
    metro_stop_times_with_times = metro_stop_times_with_times.dropna(subset=["time_sec"])

    metro_passages = metro_stop_times_with_times.merge(metro_stops, on="stop_id", how="left").dropna(
        subset=["stop_lat", "stop_lon"]
    )

    metro_stop_ids = metro_stops["stop_id"].astype(str).to_numpy()
    metro_stop_lats = metro_stops["stop_lat"].astype(float).to_numpy()
    metro_stop_lons = metro_stops["stop_lon"].astype(float).to_numpy()

    metro_times_by_stop: dict[str, np.ndarray] = {}
    metro_services_by_stop: dict[str, np.ndarray] = {}
    for stop_id, group in metro_passages.groupby("stop_id"):
        metro_times_by_stop[str(stop_id)] = group["time_sec"].astype(int).to_numpy()
        metro_services_by_stop[str(stop_id)] = group["service_id"].astype(str).to_numpy()

    smtuc_day_masks = _service_day_masks(gtfs_smtuc.calendar)
    metro_day_masks = _service_day_masks(gtfs_metro.calendar)
    
    # Calcular para cada linha
    line_to_route_ids = _line_to_route_ids(gtfs_smtuc)
    
    for idx, row in metrics_df.iterrows():
        line = _normalize_line_value(row.get("line"))
        if not line:
            continue
        
        if line not in line_to_route_ids:
            continue
        
        route_ids = line_to_route_ids[line]
        
        # Obter stop_times para esta linha
        smtuc_trips = gtfs_smtuc.trips[
            gtfs_smtuc.trips["route_id"].astype(str).isin([str(r) for r in route_ids])
        ][["trip_id", "service_id"]].copy()
        smtuc_trips["trip_id"] = smtuc_trips["trip_id"].astype(str)
        smtuc_trips["service_id"] = smtuc_trips["service_id"].astype(str)
        
        smtuc_stop_times = gtfs_smtuc.stop_times[
            gtfs_smtuc.stop_times["trip_id"].astype(str).isin(smtuc_trips["trip_id"])
        ].copy()
        smtuc_stop_times["trip_id"] = smtuc_stop_times["trip_id"].astype(str)
        smtuc_stop_times = smtuc_stop_times.merge(smtuc_trips, on="trip_id", how="left")
        
        # Juntar com stops
        smtuc_stop_times = smtuc_stop_times.merge(
            gtfs_smtuc.stops[["stop_id", "stop_lat", "stop_lon"]],
            on="stop_id", how="left"
        ).dropna(subset=["stop_lat", "stop_lon"])
        
        # Calcular tempos
        smtuc_stop_times["time_sec"] = smtuc_stop_times.apply(_get_time_seconds, axis=1)
        smtuc_stop_times = smtuc_stop_times.dropna(subset=["time_sec"])
        
        total_passages_nearby = 0
        temporal_overlaps = 0
        temporal_overlap_stop_ids: set[str] = set()

        for _, passage in smtuc_stop_times.iterrows():
            smtuc_lat = float(passage["stop_lat"])
            smtuc_lon = float(passage["stop_lon"])
            smtuc_time_s = int(passage["time_sec"])
            smtuc_service_id = str(passage.get("service_id", ""))

            distances = _distances_from_point_m(smtuc_lat, smtuc_lon, metro_stop_lats, metro_stop_lons)
            nearby_stop_ids = metro_stop_ids[distances <= walk_catchment_m]

            if len(nearby_stop_ids) == 0:
                continue

            total_passages_nearby += 1

            has_temporal_overlap = False
            for nearby_stop_id in nearby_stop_ids:
                stop_id = str(nearby_stop_id)
                stop_times = metro_times_by_stop.get(stop_id)
                if stop_times is None or len(stop_times) == 0:
                    continue

                time_diffs = np.abs(stop_times - smtuc_time_s)
                candidate_idx = np.where(time_diffs <= temporal_threshold_s)[0]
                if len(candidate_idx) == 0:
                    continue

                stop_services = metro_services_by_stop.get(stop_id)
                if stop_services is None or len(stop_services) == 0:
                    has_temporal_overlap = True
                    break

                for candidate in candidate_idx:
                    metro_service_id = str(stop_services[candidate])
                    if _service_days_overlap(
                        smtuc_service_id,
                        metro_service_id,
                        smtuc_day_masks,
                        metro_day_masks,
                    ):
                        has_temporal_overlap = True
                        break

                if has_temporal_overlap:
                    break

            if has_temporal_overlap:
                temporal_overlaps += 1
                temporal_overlap_stop_ids.add(str(passage["stop_id"]))

        metrics_df.at[idx, "temporal_spatial_candidates_count"] = total_passages_nearby
        metrics_df.at[idx, "temporal_overlaps_count"] = temporal_overlaps
        metrics_df.at[idx, "temporal_overlap_stop_ids"] = ";".join(sorted(temporal_overlap_stop_ids))
        if total_passages_nearby > 0:
            metrics_df.at[idx, "temporal_overlaps_pct"] = round(
                (temporal_overlaps / total_passages_nearby) * 100, 2
            )
        else:
            metrics_df.at[idx, "temporal_overlaps_pct"] = 0.0
    
    return metrics_df


def temporal_overlap_events_for_metrics(
    metrics_df: pd.DataFrame,
    smtuc_dataset: str = "smtuc",
    metrobus_dataset: str = "metrobus",
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    temporal_overlap_max_min: float = TEMPORAL_OVERLAP_MAX_MIN,
    spatial_overlap_walk_min: float = SPATIAL_OVERLAP_WALK_MIN,
) -> pd.DataFrame:
    """Devolve eventos de overlap temporal para um conjunto de linhas em métricas."""
    if metrics_df.empty or "line" not in metrics_df.columns:
        return pd.DataFrame(
            columns=[
                "line",
                "smtuc_stop_id",
                "smtuc_stop_name",
                "time_sec",
                "time_hhmm",
                "hour",
                "nearby_metro_stops_count",
            ]
        )

    gtfs_smtuc = _load_gtfs_cached(smtuc_dataset)
    gtfs_metro = _load_gtfs_cached(metrobus_dataset)

    walk_catchment_m = walk_speed_m_min * spatial_overlap_walk_min
    temporal_threshold_s = int(float(temporal_overlap_max_min) * 60)

    metro_stops = gtfs_metro.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
    metro_stops["stop_id"] = metro_stops["stop_id"].astype(str)
    metro_trips = gtfs_metro.trips[["trip_id", "service_id"]].copy()
    metro_stop_times = gtfs_metro.stop_times.copy().merge(metro_trips, on="trip_id", how="left")

    if metro_stops.empty or metro_stop_times.empty:
        return pd.DataFrame(
            columns=[
                "line",
                "smtuc_stop_id",
                "smtuc_stop_name",
                "time_sec",
                "time_hhmm",
                "hour",
                "nearby_metro_stops_count",
            ]
        )

    metro_stop_times["stop_id"] = metro_stop_times["stop_id"].astype(str)
    metro_stop_times["service_id"] = metro_stop_times["service_id"].astype(str)
    metro_stop_times["time_sec"] = metro_stop_times.apply(_get_time_seconds, axis=1)
    metro_stop_times = metro_stop_times.dropna(subset=["time_sec"])

    metro_passages = metro_stop_times.merge(metro_stops, on="stop_id", how="left").dropna(subset=["stop_lat", "stop_lon"])

    metro_stop_ids = metro_stops["stop_id"].astype(str).to_numpy()
    metro_stop_lats = metro_stops["stop_lat"].astype(float).to_numpy()
    metro_stop_lons = metro_stops["stop_lon"].astype(float).to_numpy()

    metro_times_by_stop: dict[str, np.ndarray] = {}
    metro_services_by_stop: dict[str, np.ndarray] = {}
    for stop_id, group in metro_passages.groupby("stop_id"):
        metro_times_by_stop[str(stop_id)] = group["time_sec"].astype(int).to_numpy()
        metro_services_by_stop[str(stop_id)] = group["service_id"].astype(str).to_numpy()

    smtuc_day_masks = _service_day_masks(gtfs_smtuc.calendar)
    metro_day_masks = _service_day_masks(gtfs_metro.calendar)
    line_to_route_ids = _line_to_route_ids(gtfs_smtuc)

    stop_name_col = "stop_name" if "stop_name" in gtfs_smtuc.stops.columns else None
    stop_cols = ["stop_id", "stop_lat", "stop_lon"]
    if stop_name_col:
        stop_cols.append(stop_name_col)

    events: list[dict[str, object]] = []

    for _, row in metrics_df.iterrows():
        line = _normalize_line_value(row.get("line"))
        if not line or line not in line_to_route_ids:
            continue

        route_ids = line_to_route_ids[line]
        smtuc_trips = gtfs_smtuc.trips[
            gtfs_smtuc.trips["route_id"].astype(str).isin([str(r) for r in route_ids])
        ][["trip_id", "service_id"]].copy()
        smtuc_trips["trip_id"] = smtuc_trips["trip_id"].astype(str)
        smtuc_trips["service_id"] = smtuc_trips["service_id"].astype(str)

        smtuc_stop_times = gtfs_smtuc.stop_times[
            gtfs_smtuc.stop_times["trip_id"].astype(str).isin(smtuc_trips["trip_id"])
        ].copy()
        smtuc_stop_times["trip_id"] = smtuc_stop_times["trip_id"].astype(str)
        smtuc_stop_times = smtuc_stop_times.merge(smtuc_trips, on="trip_id", how="left")
        smtuc_stop_times = smtuc_stop_times.merge(gtfs_smtuc.stops[stop_cols], on="stop_id", how="left").dropna(
            subset=["stop_lat", "stop_lon"]
        )

        smtuc_stop_times["time_sec"] = smtuc_stop_times.apply(_get_time_seconds, axis=1)
        smtuc_stop_times = smtuc_stop_times.dropna(subset=["time_sec"])

        for _, passage in smtuc_stop_times.iterrows():
            smtuc_lat = float(passage["stop_lat"])
            smtuc_lon = float(passage["stop_lon"])
            smtuc_time_s = int(passage["time_sec"])
            smtuc_service_id = str(passage.get("service_id", ""))

            distances = _distances_from_point_m(smtuc_lat, smtuc_lon, metro_stop_lats, metro_stop_lons)
            nearby_stop_ids = metro_stop_ids[distances <= walk_catchment_m]
            if len(nearby_stop_ids) == 0:
                continue

            has_temporal_overlap = False
            for nearby_stop_id in nearby_stop_ids:
                stop_id = str(nearby_stop_id)
                stop_times = metro_times_by_stop.get(stop_id)
                if stop_times is None or len(stop_times) == 0:
                    continue

                time_diffs = np.abs(stop_times - smtuc_time_s)
                candidate_idx = np.where(time_diffs <= temporal_threshold_s)[0]
                if len(candidate_idx) == 0:
                    continue

                stop_services = metro_services_by_stop.get(stop_id)
                if stop_services is None or len(stop_services) == 0:
                    has_temporal_overlap = True
                    break

                for candidate in candidate_idx:
                    metro_service_id = str(stop_services[candidate])
                    if _service_days_overlap(
                        smtuc_service_id,
                        metro_service_id,
                        smtuc_day_masks,
                        metro_day_masks,
                    ):
                        has_temporal_overlap = True
                        break

                if has_temporal_overlap:
                    break

            if not has_temporal_overlap:
                continue

            h = smtuc_time_s // 3600
            m = (smtuc_time_s % 3600) // 60
            events.append(
                {
                    "line": line,
                    "smtuc_stop_id": str(passage["stop_id"]),
                    "smtuc_stop_name": str(passage.get(stop_name_col, "")) if stop_name_col else "",
                    "time_sec": smtuc_time_s,
                    "time_hhmm": f"{h:02d}:{m:02d}",
                    "hour": int(h),
                    "nearby_metro_stops_count": int(len(nearby_stop_ids)),
                }
            )

    return pd.DataFrame(events)


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
    day = _parse_day(day_str)
    t0 = int(_to_seconds(from_time_str))
    t1 = int(_to_seconds(latest_time_str)) if latest_time_str else None
    board_walk_m = float(walk_speed_m_min) * float(max_board_walk_min)

    best_departure_s: int | None = None

    for dataset in datasets:
        gtfs = _load_gtfs_cached(dataset)

        stops = gtfs.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
        if stops.empty:
            continue

        stops["stop_id"] = stops["stop_id"].astype(str)
        d_m = _distances_from_point_m(
            origin_lat,
            origin_lon,
            stops["stop_lat"].astype(float).to_numpy(),
            stops["stop_lon"].astype(float).to_numpy(),
        )
        boardable_ids = set(stops.loc[d_m <= board_walk_m, "stop_id"].astype(str).tolist())
        if not boardable_ids:
            continue

        active_services = _active_service_ids(gtfs, day)
        trips = gtfs.trips[["trip_id", "service_id"]].copy()
        trips["trip_id"] = trips["trip_id"].astype(str)
        trips["service_id"] = trips["service_id"].astype(str)
        if active_services:
            trips = trips[trips["service_id"].isin(active_services)]
        if trips.empty:
            continue

        st = gtfs.stop_times[["trip_id", "stop_id", "departure_seconds"]].copy()
        st["trip_id"] = st["trip_id"].astype(str)
        st["stop_id"] = st["stop_id"].astype(str)
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
    gtfs = _load_gtfs_cached(dataset)

    stops = gtfs.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
    if stops.empty:
        return pd.DataFrame(columns=["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"])

    stops["stop_id"] = stops["stop_id"].astype(str)
    stop_ids = stops["stop_id"].to_numpy()
    stop_lats = stops["stop_lat"].astype(float).to_numpy()
    stop_lons = stops["stop_lon"].astype(float).to_numpy()

    direct_walk_m = _distances_from_point_m(origin_lat, origin_lon, stop_lats, stop_lons)
    direct_walk_min = direct_walk_m / float(walk_speed_m_min)

    reach_by_stop = pd.Series(direct_walk_min, index=stop_ids, dtype="float64")

    day = _parse_day(day_str)
    t0 = int(_to_seconds(time_str))
    active_services = _active_service_ids(gtfs, day)

    trips = gtfs.trips[["trip_id", "service_id"]].copy()
    trips["trip_id"] = trips["trip_id"].astype(str)
    trips["service_id"] = trips["service_id"].astype(str)
    if active_services:
        trips = trips[trips["service_id"].isin(active_services)]
    if trips.empty:
        out = stops.copy()
        out["dataset"] = dataset
        out["reach_min"] = reach_by_stop.reindex(out["stop_id"]).astype(float).to_numpy()
        return out[["dataset", "stop_id", "stop_lat", "stop_lon", "reach_min"]]

    st_cols = ["trip_id", "stop_id", "stop_sequence", "departure_seconds", "arrival_seconds"]
    st = gtfs.stop_times[st_cols].copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)
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
    day = _parse_day(day_str)
    t0 = int(_to_seconds(time_str))

    all_stops_parts: list[pd.DataFrame] = []
    trip_tables: list[pd.DataFrame] = []

    for dataset in datasets:
        gtfs = _load_gtfs_cached(dataset)

        stops = gtfs.stops[["stop_id", "stop_lat", "stop_lon"]].dropna().copy()
        if stops.empty:
            continue

        stops["stop_id"] = stops["stop_id"].astype(str)
        stops["global_stop_id"] = dataset + ":" + stops["stop_id"]
        stops["dataset"] = dataset
        all_stops_parts.append(stops[["dataset", "stop_id", "global_stop_id", "stop_lat", "stop_lon"]])

        trips = gtfs.trips[["trip_id", "service_id"]].copy()
        trips["trip_id"] = trips["trip_id"].astype(str)
        trips["service_id"] = trips["service_id"].astype(str)
        active_services = _active_service_ids(gtfs, day)
        if active_services:
            trips = trips[trips["service_id"].isin(active_services)]
        if trips.empty:
            continue

        st_cols = ["trip_id", "stop_id", "stop_sequence", "departure_seconds", "arrival_seconds"]
        stop_times = gtfs.stop_times[st_cols].copy()
        stop_times["trip_id"] = stop_times["trip_id"].astype(str)
        stop_times["stop_id"] = stop_times["stop_id"].astype(str)
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
    direct_walk_m = _distances_from_point_m(origin_lat, origin_lon, stop_lats, stop_lons)
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
                earliest_at_stop_s = float(arrivals_prev_s.get(sid, inf_s))
                dep_s = float(trip_dep_s[i])
                arr_s = float(trip_arr_s[i])

                if (not on_board) and np.isfinite(earliest_at_stop_s) and dep_s >= earliest_at_stop_s and dep_s >= float(t0):
                    on_board = True

                if on_board and arr_s < float(arrivals_curr_s.get(sid, inf_s)):
                    arrivals_curr_s.loc[sid] = arr_s
                    changed_stop_ids.add(sid)

        # Transfer-walk relaxation from improved stops.
        # One relaxation wave per round keeps runtime bounded while enabling chained transfers across rounds.
        if changed_stop_ids:
            for sid in list(changed_stop_ids):
                src_idx = stop_id_to_idx.get(sid)
                if src_idx is None:
                    continue
                base_arrival_s = float(arrivals_curr_s.get(sid, inf_s))
                if not np.isfinite(base_arrival_s):
                    continue

                dists_m = _distances_from_point_m(stop_lats[src_idx], stop_lons[src_idx], stop_lats, stop_lons)
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
    datasets: tuple[str, ...] = ("smtuc", "metrobus"),
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

    direct_walk_min = _distances_from_point_m(origin_lat, origin_lon, cent_lat, cent_lon) / float(walk_speed_m_min)

    pt_best_min = np.full(shape=len(gdf_3763), fill_value=np.inf, dtype="float64")
    for idx in range(len(gdf_3763)):
        d_to_stops_m = _distances_from_point_m(cent_lat[idx], cent_lon[idx], stop_lat, stop_lon)
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
            )

    out = merged_bgri.copy()
    out["reach_min"] = reach_min
    out["reach_mode"] = reach_mode
    out["reach_bin"] = pd.Series(reach_min).apply(_reach_bin_label).astype(str)
    out["reach_day"] = str(day_str)
    out["reach_time"] = str(time_str)
    return out
