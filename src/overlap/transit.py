from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from config import OUTPUTS_INTEGRATION_DIR, WALK_SPEED_M_MIN
from gtfs_processing.gtfs import load_gtfs
from gtfs_processing.gtfs_probe import (
    NearestStopResult,
    _active_service_ids,
    _haversine_m,
    _parse_day,
    _resolve_stop_id,
    _to_seconds,
)


@lru_cache(maxsize=8)
def _load_gtfs_cached(dataset: str):
    return load_gtfs(dataset=dataset)


# Nota: a resolução de service_id ativos para um dia (incluindo o fallback por alias de
# dia-da-semana para feeds como o metrobus, onde trips.txt usa "WD"/"SAT"/"SUN" mas
# calendar.txt usa "Dias Uteis"/"Sabados"/"Domingos e Feriados") vive agora em
# `gtfs_processing.gtfs_probe._active_service_ids` - único sítio, usado por todos os
# chamadores (antes só este módulo tinha o fallback, deixando reachability/isócronas,
# sugestões de percurso e o score de população a excluir sempre o metrobus).


def _matching_stop_ids(gtfs, stop_ref: str) -> list[str]:
    ref = str(stop_ref).strip()
    if not ref:
        return []

    stops = gtfs.stops.copy()
    if stops.empty or "stop_id" not in stops.columns:
        return []

    stops["stop_id"] = stops["stop_id"].astype(str)

    out: list[str] = []

    direct = stops[stops["stop_id"] == ref]["stop_id"].drop_duplicates().tolist()
    out.extend(direct)

    if "stop_name" not in stops.columns:
        return out

    names = stops["stop_name"].astype(str)
    exact = stops[names.str.lower() == ref.lower()]["stop_id"].drop_duplicates().tolist()
    out.extend(exact)

    partial = stops[names.str.contains(ref, case=False, na=False)]["stop_id"].drop_duplicates().tolist()
    out.extend(partial)

    return list(dict.fromkeys(str(v) for v in out))


def _arrival_times_for_stop(
    gtfs,
    trips: pd.DataFrame,
    target_stop_id: str,
    origin_candidates: list[str] | None = None,
) -> list[str]:
    if trips.empty:
        return []

    st = gtfs.stop_times.copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)
    st = st[st["trip_id"].isin(trips["trip_id"].astype(str))]
    if st.empty:
        return []

    target_stop_id = str(target_stop_id)
    with_origin = bool(origin_candidates)
    origin_set = {str(v) for v in (origin_candidates or [])}

    out: list[str] = []
    for _, trip_st in st.groupby("trip_id"):
        trip_st = trip_st.sort_values("stop_sequence")
        target_rows = trip_st[trip_st["stop_id"] == target_stop_id]
        if target_rows.empty:
            continue

        target_row = target_rows.iloc[0]
        if with_origin:
            origins = trip_st[trip_st["stop_id"].isin(origin_set)]
            if origins.empty:
                continue
            origin_seq = int(origins["stop_sequence"].min())
            if origin_seq >= int(target_row["stop_sequence"]):
                continue

        out.append(str(target_row["arrival_time"]))

    return sorted(set(out))


def _arrival_events_for_stop(
    gtfs,
    trips: pd.DataFrame,
    target_stop_id: str,
    origin_candidates: list[str] | None = None,
    line_by_trip: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    if trips.empty:
        return []

    st = gtfs.stop_times.copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)
    st = st[st["trip_id"].isin(trips["trip_id"].astype(str))]
    if st.empty:
        return []

    target_stop_id = str(target_stop_id)
    with_origin = bool(origin_candidates)
    origin_set = {str(v) for v in (origin_candidates or [])}
    line_by_trip = line_by_trip or {}

    out: list[dict[str, str]] = []
    for trip_id, trip_st in st.groupby("trip_id"):
        trip_st = trip_st.sort_values("stop_sequence")
        target_rows = trip_st[trip_st["stop_id"] == target_stop_id]
        if target_rows.empty:
            continue

        target_row = target_rows.iloc[0]
        if with_origin:
            origins = trip_st[trip_st["stop_id"].isin(origin_set)]
            if origins.empty:
                continue
            origin_seq = int(origins["stop_sequence"].min())
            if origin_seq >= int(target_row["stop_sequence"]):
                continue

        out.append(
            {
                "time": str(target_row["arrival_time"]),
                "line": str(line_by_trip.get(str(trip_id), "")),
            }
        )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ev in sorted(out, key=lambda r: (_hhmmss_to_seconds(str(r["time"])), str(r["line"]))):
        k = (str(ev["time"]), str(ev["line"]))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(ev)
    return deduped


def _pick_best_target_stop_id(
    gtfs,
    trips: pd.DataFrame,
    target_candidates: list[str],
    origin_candidates: list[str] | None = None,
) -> str:
    if not target_candidates:
        raise ValueError("Sem paragens candidatas para o destino.")

    if len(target_candidates) == 1:
        return str(target_candidates[0])

    st = gtfs.stop_times.copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)
    st = st[st["trip_id"].isin(trips["trip_id"].astype(str))]

    origin_set = {str(v) for v in (origin_candidates or [])}
    use_origin = bool(origin_set)

    best_stop = str(target_candidates[0])
    best_score = -1
    for cand in [str(v) for v in target_candidates]:
        score = 0
        for _, trip_st in st.groupby("trip_id"):
            trip_st = trip_st.sort_values("stop_sequence")
            target_rows = trip_st[trip_st["stop_id"] == cand]
            if target_rows.empty:
                continue

            if use_origin:
                origins = trip_st[trip_st["stop_id"].isin(origin_set)]
                if origins.empty:
                    continue
                if int(origins["stop_sequence"].min()) >= int(target_rows.iloc[0]["stop_sequence"]):
                    continue

            score += 1

        if score > best_score:
            best_score = score
            best_stop = cand

    return best_stop


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower())
    cleaned = cleaned.strip("_")
    return cleaned or "value"


def _hhmmss_to_seconds(value: str) -> int:
    h, m, s = (int(part) for part in str(value).split(":"))
    return h * 3600 + m * 60 + s


def _seconds_to_hhmmss(value: int) -> str:
    value = int(value)
    h = value // 3600
    m = (value % 3600) // 60
    s = value % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _normalize_line_numbers(line_number: str | int | list[str | int] | tuple[str | int, ...]) -> list[str]:
    if isinstance(line_number, (list, tuple, set)):
        raw = [str(v).strip() for v in line_number if str(v).strip()]
    else:
        text = str(line_number).strip()
        if "," in text:
            raw = [p.strip() for p in text.split(",") if p.strip()]
        else:
            raw = [text] if text else []
    return list(dict.fromkeys(raw))


def nearest_business_day(from_day: date | None = None) -> date:
    """Return today if weekday, otherwise the nearest weekday (Sat->Fri, Sun->Mon)."""
    day = from_day or date.today()
    wd = day.weekday()
    if wd <= 4:
        return day
    if wd == 5:
        return day - timedelta(days=1)
    return day + timedelta(days=1)


def resolve_reference_day(day_str: str | None = None) -> date:
    """
    Resolve the reference day for integration analyses.

    Any explicit day provided by callers is intentionally ignored so execution stays
    anchored to the current business day policy.
    """
    _ = day_str  # kept for API compatibility and explicit intent
    return nearest_business_day(date.today())


def _direction_arrival_times_for_stop(gtfs, trips: pd.DataFrame, target_stop_id: str, direction_id: int) -> list[str]:
    """Como `_arrival_times_for_stop`, mas filtra por `trips.direction_id` em vez de exigir uma
    paragem de origem anterior ao alvo. Necessário quando o alvo É a própria origem da viagem
    nesse sentido (ex.: "Portagem" é stop_sequence=1 do Metrobus sentido Serpins - não há
    nenhuma paragem "antes" na mesma viagem para filtrar por origem, ao contrário do caso
    normal onde a paragem de origem faz sempre parte do trajeto antes do alvo)."""
    if trips.empty or "direction_id" not in trips.columns:
        return []
    dir_trips = trips[trips["direction_id"].astype(str) == str(direction_id)]
    if dir_trips.empty:
        return []

    st = gtfs.stop_times.copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)
    st = st[st["trip_id"].isin(dir_trips["trip_id"].astype(str))]
    if st.empty:
        return []

    rows = st[st["stop_id"] == str(target_stop_id)]
    return sorted(set(rows["arrival_time"].astype(str).tolist()))


def _resolve_bus_arrival_events(
    gtfs_bus,
    day: date,
    bus_target_candidates: list[str],
    bus_origin_candidates: list[str],
    line_number: str | int | list[str | int] | tuple[str | int, ...],
) -> tuple[list[dict[str, str]], str, str]:
    """Resolve os eventos de chegada de autocarro (uma ou mais linhas) a uma paragem, filtrados
    por sentido (`bus_origin_candidates`). Partilhado por `build_line_stop_vs_metro_table` e
    `build_reverse_stop_vs_metro_table` - a mesma resolução de linha->paragem->sentido serve os
    dois sentidos da comparação com o metro, só muda o que se faz com o resultado depois.

    Devolve `(bus_events, line_label, line_slug)`. Cada linha é resolvida de forma totalmente
    independente das outras: ao combinar várias linhas (ex. 54+38) NÃO se pode desligar o filtro
    de origem/sentido globalmente, senão uma linha cujo percurso nem passa pela origem pedida
    (ex. a 38 não passa em "Portela do Mondego") contaminaria a seleção da paragem física
    correta e o sentido das restantes linhas. Uma linha sem trips no sentido pedido contribui
    corretamente 0 eventos, em vez de eventos de sentido errado.
    """
    line_values = _normalize_line_numbers(line_number)
    if not line_values:
        raise ValueError("Linha(s) não indicada(s).")
    line_label = "+".join(line_values)
    line_slug = "_".join(_safe_slug(v) for v in line_values)

    routes = gtfs_bus.routes.copy()
    routes["route_id"] = routes["route_id"].astype(str)
    if "route_short_name" in routes.columns:
        routes["route_short_name"] = routes["route_short_name"].astype(str)
    else:
        routes["route_short_name"] = ""

    bus_services = _active_service_ids(gtfs_bus, day)
    all_bus_trips = gtfs_bus.trips.copy()
    all_bus_trips["route_id"] = all_bus_trips["route_id"].astype(str)
    all_bus_trips["service_id"] = all_bus_trips["service_id"].astype(str)
    if bus_services:
        all_bus_trips = all_bus_trips[all_bus_trips["service_id"].isin(bus_services)]

    route_to_line = {}
    if "route_short_name" in routes.columns:
        route_to_line = dict(
            zip(
                routes["route_id"].astype(str).tolist(),
                routes["route_short_name"].astype(str).str.strip().tolist(),
            )
        )

    bus_events: list[dict[str, str]] = []
    matched_any_line = False
    for line_val in line_values:
        route_ids = routes[routes["route_short_name"].str.strip() == line_val]["route_id"].drop_duplicates().tolist()
        if not route_ids:
            route_ids = routes[routes["route_id"].str.strip() == line_val]["route_id"].drop_duplicates().tolist()
        if not route_ids:
            continue
        matched_any_line = True

        line_trips = all_bus_trips[all_bus_trips["route_id"].isin(route_ids)]
        if line_trips.empty:
            continue

        line_target_stop_id = _pick_best_target_stop_id(
            gtfs=gtfs_bus,
            trips=line_trips,
            target_candidates=bus_target_candidates,
            origin_candidates=bus_origin_candidates,
        )
        line_by_trip = {
            str(row["trip_id"]): str(route_to_line.get(str(row["route_id"]), str(row["route_id"]))).strip()
            for _, row in line_trips[["trip_id", "route_id"]].iterrows()
        }
        bus_events.extend(
            _arrival_events_for_stop(
                gtfs=gtfs_bus,
                trips=line_trips,
                target_stop_id=line_target_stop_id,
                origin_candidates=bus_origin_candidates,
                line_by_trip=line_by_trip,
            )
        )

    if not matched_any_line:
        raise ValueError(f"Linha(s) não encontrada(s): {line_label}")

    bus_events = sorted(bus_events, key=lambda ev: (_hhmmss_to_seconds(str(ev["time"])), str(ev["line"])))
    return bus_events, line_label, line_slug


def build_line_stop_vs_metro_table(
    metro_stop_ref: str,
    bus_stop_ref: str,
    line_number: str | int | list[str | int] | tuple[str | int, ...],
    day_str: str | None = None,
    metro_origin_ref: str = "Portagem",
    bus_origin_ref: str = "Portagem",
    output_csv_name: str | None = None,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Gera uma tabela comparando horários de autocarro e metro numa paragem de destino.

    Requer apenas: nome/id da paragem de metro, nome/id da paragem de autocarro e número da linha.
    O dia de referência é sempre o dia útil atual (ou o dia útil mais próximo).

    Por omissão escreve o CSV em `OUTPUTS_INTEGRATION_DIR` (o mesmo diretório partilhado usado
    pelo dashboard). Passa `output_dir` (ex.: `tmp_path` de um teste) para escrever noutro sítio
    sem afetar os ficheiros publicados.
    """
    day = resolve_reference_day(day_str)

    gtfs_bus = _load_gtfs_cached("smtuc")
    gtfs_metro = _load_gtfs_cached("metrobus")

    # Candidate ids para filtrar sentido (ex.: Portagem -> Portela)
    bus_origin_candidates = _matching_stop_ids(gtfs_bus, str(bus_origin_ref))
    metro_origin_candidates = _matching_stop_ids(gtfs_metro, str(metro_origin_ref))
    bus_target_candidates = _matching_stop_ids(gtfs_bus, str(bus_stop_ref))
    metro_target_candidates = _matching_stop_ids(gtfs_metro, str(metro_stop_ref))

    if not bus_target_candidates:
        raise ValueError(f"Paragem de autocarro não encontrada: {bus_stop_ref}")
    if not metro_target_candidates:
        raise ValueError(f"Paragem de metro não encontrada: {metro_stop_ref}")

    # Trips do metro
    metro_services = _active_service_ids(gtfs_metro, day)
    metro_trips = gtfs_metro.trips.copy()
    metro_trips["service_id"] = metro_trips["service_id"].astype(str)
    if metro_services:
        metro_trips = metro_trips[metro_trips["service_id"].isin(metro_services)]

    metro_stop_id = _pick_best_target_stop_id(
        gtfs=gtfs_metro,
        trips=metro_trips,
        target_candidates=metro_target_candidates,
        origin_candidates=metro_origin_candidates,
    )

    bus_events, line_label, line_slug = _resolve_bus_arrival_events(
        gtfs_bus, day, bus_target_candidates, bus_origin_candidates, line_number
    )
    bus_times = [ev["time"] for ev in bus_events]
    bus_lines = [ev["line"] for ev in bus_events]
    metro_times = _arrival_times_for_stop(
        gtfs=gtfs_metro,
        trips=metro_trips,
        target_stop_id=metro_stop_id,
        origin_candidates=metro_origin_candidates,
    )

    n = max(len(bus_times), len(metro_times))
    columns = [
        "idx",
        "bus_line",
        "bus_line_passage",
        "bus_stop",
        "bus_time",
        "metro_stop",
        "metro_time_from_origin",
        "origin_ref",
        "date",
    ]
    if n == 0:
        out_df = pd.DataFrame(columns=columns)
        out_dir = Path(output_dir) if output_dir is not None else (
            Path(__file__).resolve().parents[2] / OUTPUTS_INTEGRATION_DIR
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_name = output_csv_name or (
            f"line_{line_slug}_bus_{_safe_slug(bus_stop_ref)}"
            f"_metro_{_safe_slug(metro_stop_ref)}.csv"
        )
        out_df.to_csv(out_dir / csv_name, index=False)
        return out_df

    rows = []
    for i in range(n):
        rows.append(
            {
                "idx": i + 1,
                "bus_line": line_label,
                "bus_line_passage": bus_lines[i] if i < len(bus_lines) else "",
                "bus_stop": str(bus_stop_ref),
                "bus_time": bus_times[i] if i < len(bus_times) else "",
                "metro_stop": str(metro_stop_ref),
                "metro_time_from_origin": metro_times[i] if i < len(metro_times) else "",
                "origin_ref": str(metro_origin_ref),
                "date": day.strftime("%Y-%m-%d"),
            }
        )

    out_df = pd.DataFrame(rows, columns=columns)

    out_dir = Path(output_dir) if output_dir is not None else (
        Path(__file__).resolve().parents[2] / OUTPUTS_INTEGRATION_DIR
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_name = output_csv_name or (
        f"line_{line_slug}_bus_{_safe_slug(bus_stop_ref)}"
        f"_metro_{_safe_slug(metro_stop_ref)}.csv"
    )
    out_df.to_csv(out_dir / csv_name, index=False)

    return out_df


def build_reverse_stop_vs_metro_table(
    bus_stop_ref: str,
    metro_stop_ref: str,
    line_number: str | int | list[str | int] | tuple[str | int, ...],
    metro_direction_id: int,
    day_str: str | None = None,
    bus_origin_ref: str = "Portagem",
    output_csv_name: str | None = None,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Gera a tabela do sentido INVERSO de `build_line_stop_vs_metro_table`: em vez de "quanto
    tempo espera quem chega de metro pelo próximo autocarro", mede "quanto tempo espera quem
    chega de autocarro pela próxima partida de metro".

    `metro_direction_id` identifica o sentido do Metrobus que continua a viagem a partir de
    `metro_stop_ref` (0 ou 1, conforme `trips.direction_id`) - usa-se o sentido da viagem em vez
    de uma paragem de origem porque nalguns casos a paragem-alvo é a própria origem da viagem
    nesse sentido (ex.: em Portagem, sentido Serpins, não há nenhuma paragem "antes" na mesma
    viagem para filtrar por origem - ver `_direction_arrival_times_for_stop`).

    Devolve o MESMO esquema de colunas que `build_line_stop_vs_metro_table`
    (`bus_time`/`bus_line_passage`, `metro_time_from_origin`) mas com o conteúdo trocado, DE
    PROPÓSITO: `bus_time`/`bus_line_passage` passam a conter as PARTIDAS de metro (rotuladas
    "Metro" - é o que se quer apanhar) e `metro_time_from_origin` passa a conter as CHEGADAS de
    autocarro (é o que desencadeia a espera). Isto mantém o contrato de colunas que
    `_build_waits_table` e as funções de visualização em `visualizations/integration.py` já
    esperam, para as reutilizar sem alterações nos dois sentidos.
    """
    day = resolve_reference_day(day_str)

    gtfs_bus = _load_gtfs_cached("smtuc")
    gtfs_metro = _load_gtfs_cached("metrobus")

    bus_origin_candidates = _matching_stop_ids(gtfs_bus, str(bus_origin_ref))
    bus_target_candidates = _matching_stop_ids(gtfs_bus, str(bus_stop_ref))
    metro_target_candidates = _matching_stop_ids(gtfs_metro, str(metro_stop_ref))

    if not bus_target_candidates:
        raise ValueError(f"Paragem de autocarro não encontrada: {bus_stop_ref}")
    if not metro_target_candidates:
        raise ValueError(f"Paragem de metro não encontrada: {metro_stop_ref}")

    metro_services = _active_service_ids(gtfs_metro, day)
    metro_trips = gtfs_metro.trips.copy()
    metro_trips["service_id"] = metro_trips["service_id"].astype(str)
    if metro_services:
        metro_trips = metro_trips[metro_trips["service_id"].isin(metro_services)]

    metro_stop_id = _pick_best_target_stop_id(
        gtfs=gtfs_metro,
        trips=metro_trips,
        target_candidates=metro_target_candidates,
    )
    metro_departure_times = _direction_arrival_times_for_stop(
        gtfs=gtfs_metro,
        trips=metro_trips,
        target_stop_id=metro_stop_id,
        direction_id=metro_direction_id,
    )

    bus_events, line_label, line_slug = _resolve_bus_arrival_events(
        gtfs_bus, day, bus_target_candidates, bus_origin_candidates, line_number
    )
    bus_arrival_times = sorted({str(ev["time"]) for ev in bus_events})

    n = max(len(bus_arrival_times), len(metro_departure_times))
    columns = [
        "idx",
        "bus_line",
        "bus_line_passage",
        "bus_stop",
        "bus_time",
        "metro_stop",
        "metro_time_from_origin",
        "origin_ref",
        "date",
    ]
    out_dir = Path(output_dir) if output_dir is not None else (
        Path(__file__).resolve().parents[2] / OUTPUTS_INTEGRATION_DIR
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_name = output_csv_name or (
        f"reverse_line_{line_slug}_bus_{_safe_slug(bus_stop_ref)}"
        f"_metro_{_safe_slug(metro_stop_ref)}.csv"
    )

    if n == 0:
        out_df = pd.DataFrame(columns=columns)
        out_df.to_csv(out_dir / csv_name, index=False)
        return out_df

    rows = []
    for i in range(n):
        rows.append(
            {
                "idx": i + 1,
                "bus_line": "Metro",
                "bus_line_passage": "Metro",
                "bus_stop": str(metro_stop_ref),
                "bus_time": metro_departure_times[i] if i < len(metro_departure_times) else "",
                "metro_stop": str(bus_stop_ref),
                "metro_time_from_origin": bus_arrival_times[i] if i < len(bus_arrival_times) else "",
                "origin_ref": str(bus_origin_ref),
                "date": day.strftime("%Y-%m-%d"),
            }
        )

    out_df = pd.DataFrame(rows, columns=columns)
    out_df.to_csv(out_dir / csv_name, index=False)

    return out_df


def build_metro_bus_connection_metrics(
    metro_stop_ref: str,
    bus_stop_ref: str,
    line_number: str | int | list[str | int] | tuple[str | int, ...],
    day_str: str | None = None,
    metro_origin_ref: str = "Portagem",
    bus_origin_ref: str = "Portagem",
    coverage_thresholds_min: tuple[int, ...] = (5, 10, 15),
    lost_connection_threshold_min: int = 15,
    output_csv_name: str | None = None,
) -> pd.DataFrame:
    """
    Calcula métricas de coordenação metro -> autocarro e grava um CSV em outputs/integration.
    """
    schedule_df = build_line_stop_vs_metro_table(
        metro_stop_ref=metro_stop_ref,
        bus_stop_ref=bus_stop_ref,
        line_number=line_number,
        day_str=day_str,
        metro_origin_ref=metro_origin_ref,
        bus_origin_ref=bus_origin_ref,
    )

    if schedule_df.empty:
        metrics_df = pd.DataFrame(
            [
                {
                    "scope": "overall",
                    "metric": "metro_arrivals_count",
                    "value": 0,
                    "unit": "count",
                    "note": "Sem dados para calcular métricas",
                }
            ]
        )
    else:
        bus_times = sorted(
            {
                _hhmmss_to_seconds(v)
                for v in schedule_df["bus_time"].astype(str).tolist()
                if str(v).strip()
            }
        )
        metro_times = sorted(
            {
                _hhmmss_to_seconds(v)
                for v in schedule_df["metro_time_from_origin"].astype(str).tolist()
                if str(v).strip()
            }
        )

        waits_min: list[float | None] = []
        for metro_s in metro_times:
            next_bus = next((b for b in bus_times if b >= metro_s), None)
            if next_bus is None:
                waits_min.append(None)
            else:
                waits_min.append(round((next_bus - metro_s) / 60.0, 2))

        waits_series = pd.Series(waits_min, dtype="float")
        waits_valid = waits_series.dropna()
        n_metro = len(metro_times)
        n_bus = len(bus_times)

        records: list[dict] = [
            {"scope": "overall", "metric": "metro_arrivals_count", "value": n_metro, "unit": "count", "note": ""},
            {"scope": "overall", "metric": "bus_arrivals_count", "value": n_bus, "unit": "count", "note": ""},
            {
                "scope": "overall",
                "metric": "bus_vs_metro_ratio",
                "value": round((n_bus / n_metro), 3) if n_metro else None,
                "unit": "ratio",
                "note": "passagens_autocarro / passagens_metro",
            },
            {
                "scope": "overall",
                "metric": "wait_median_min",
                "value": round(float(waits_valid.median()), 2) if not waits_valid.empty else None,
                "unit": "min",
                "note": "tempo de espera para o próximo autocarro",
            },
            {
                "scope": "overall",
                "metric": "wait_p75_min",
                "value": round(float(waits_valid.quantile(0.75)), 2) if not waits_valid.empty else None,
                "unit": "min",
                "note": "tempo de espera para o próximo autocarro",
            },
            {
                "scope": "overall",
                "metric": "wait_p90_min",
                "value": round(float(waits_valid.quantile(0.90)), 2) if not waits_valid.empty else None,
                "unit": "min",
                "note": "tempo de espera para o próximo autocarro",
            },
            {
                "scope": "overall",
                "metric": "wait_max_min",
                "value": round(float(waits_valid.max()), 2) if not waits_valid.empty else None,
                "unit": "min",
                "note": "tempo de espera para o próximo autocarro",
            },
        ]

        # Cobertura de ligação até T minutos
        for threshold in coverage_thresholds_min:
            coverage = float(((waits_series <= float(threshold)).sum() / n_metro) * 100.0) if n_metro else 0.0
            records.append(
                {
                    "scope": "overall",
                    "metric": f"coverage_le_{int(threshold)}_min_pct",
                    "value": round(coverage, 2),
                    "unit": "pct",
                    "note": "percentagem de chegadas de metro com autocarro ate T minutos",
                }
            )

        # Taxa de perda de ligação (espera > threshold ou sem autocarro seguinte)
        lost_count = int(((waits_series > float(lost_connection_threshold_min)) | waits_series.isna()).sum())
        lost_rate = float((lost_count / n_metro) * 100.0) if n_metro else 0.0
        records.append(
            {
                "scope": "overall",
                "metric": f"lost_connection_gt_{int(lost_connection_threshold_min)}_min_pct",
                "value": round(lost_rate, 2),
                "unit": "pct",
                "note": "espera superior ao limiar ou sem autocarro seguinte",
            }
        )

        # Janela sem serviço útil: maior sequência contínua de chegadas com ligação perdida
        bad_flags = [
            (w is None) or (float(w) > float(lost_connection_threshold_min))
            for w in waits_min
        ]
        best_start = None
        best_end = None
        current_start = None
        for i, is_bad in enumerate(bad_flags):
            if is_bad and current_start is None:
                current_start = i
            if not is_bad and current_start is not None:
                if best_start is None or (i - 1 - current_start) > (best_end - best_start):
                    best_start, best_end = current_start, i - 1
                current_start = None
        if current_start is not None:
            i = len(bad_flags)
            if best_start is None or (i - 1 - current_start) > (best_end - best_start):
                best_start, best_end = current_start, i - 1

        if best_start is not None and best_end is not None and metro_times:
            start_s = metro_times[best_start]
            end_s = metro_times[best_end]
            span_min = round((end_s - start_s) / 60.0, 2)
            records.extend(
                [
                    {
                        "scope": "overall",
                        "metric": "critical_window_start",
                        "value": _seconds_to_hhmmss(start_s),
                        "unit": "hh:mm:ss",
                        "note": "inicio da maior janela continua de ligacoes perdidas",
                    },
                    {
                        "scope": "overall",
                        "metric": "critical_window_end",
                        "value": _seconds_to_hhmmss(end_s),
                        "unit": "hh:mm:ss",
                        "note": "fim da maior janela continua de ligacoes perdidas",
                    },
                    {
                        "scope": "overall",
                        "metric": "critical_window_span_min",
                        "value": span_min,
                        "unit": "min",
                        "note": "duracao entre primeira e ultima chegada de metro da janela critica",
                    },
                ]
            )

        # Equidade temporal (manhã, meio do dia, tarde/noite)
        period_defs = [
            ("manha", 6, 12),
            ("meio_dia", 12, 17),
            ("tarde_noite", 17, 24),
        ]
        for label, start_h, end_h in period_defs:
            idxs = [
                i
                for i, sec in enumerate(metro_times)
                if start_h <= (sec // 3600) < end_h
            ]
            p_waits = pd.Series([waits_min[i] for i in idxs], dtype="float")
            p_n = len(idxs)
            p_cov10 = float(((p_waits <= 10).sum() / p_n) * 100.0) if p_n else None
            p_lost = float((((p_waits > float(lost_connection_threshold_min)) | p_waits.isna()).sum() / p_n) * 100.0) if p_n else None

            records.extend(
                [
                    {"scope": label, "metric": "metro_arrivals_count", "value": p_n, "unit": "count", "note": ""},
                    {
                        "scope": label,
                        "metric": "wait_median_min",
                        "value": round(float(p_waits.dropna().median()), 2) if not p_waits.dropna().empty else None,
                        "unit": "min",
                        "note": "tempo de espera para o próximo autocarro",
                    },
                    {
                        "scope": label,
                        "metric": "wait_p90_min",
                        "value": round(float(p_waits.dropna().quantile(0.90)), 2) if not p_waits.dropna().empty else None,
                        "unit": "min",
                        "note": "tempo de espera para o próximo autocarro",
                    },
                    {
                        "scope": label,
                        "metric": "coverage_le_10_min_pct",
                        "value": round(p_cov10, 2) if p_cov10 is not None else None,
                        "unit": "pct",
                        "note": "percentagem de chegadas com autocarro ate 10 minutos",
                    },
                    {
                        "scope": label,
                        "metric": f"lost_connection_gt_{int(lost_connection_threshold_min)}_min_pct",
                        "value": round(p_lost, 2) if p_lost is not None else None,
                        "unit": "pct",
                        "note": "espera superior ao limiar ou sem autocarro seguinte",
                    },
                ]
            )

        metrics_df = pd.DataFrame(records, columns=["scope", "metric", "value", "unit", "note"])

    sample_date = resolve_reference_day(day_str).strftime("%Y-%m-%d")
    line_values = _normalize_line_numbers(line_number)
    line_slug = "_".join(_safe_slug(v) for v in line_values) if line_values else _safe_slug(str(line_number))

    csv_name = output_csv_name or (
        f"line_{line_slug}_connection_metrics_"
        f"{_safe_slug(bus_stop_ref)}_vs_{_safe_slug(metro_stop_ref)}.csv"
    )

    root = Path(__file__).resolve().parents[2]
    out_dir = root / OUTPUTS_INTEGRATION_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_df.to_csv(out_dir / csv_name, index=False)

    return metrics_df


def find_direct_options(dataset: str, origin_ref: str, dest_ref: str, day_str: str, time_str: str) -> pd.DataFrame:
    gtfs = _load_gtfs_cached(dataset)
    d = _parse_day(day_str)
    t0 = _to_seconds(time_str)

    origin_id = _resolve_stop_id(gtfs, origin_ref)
    dest_id = _resolve_stop_id(gtfs, dest_ref)

    services = _active_service_ids(gtfs, d)
    trips = gtfs.trips.copy()
    trips["service_id"] = trips["service_id"].astype(str)
    if services:
        trips = trips[trips["service_id"].isin(services)]

    st = gtfs.stop_times.copy()
    left = st.rename(
        columns={
            "stop_id": "origin_stop_id",
            "stop_sequence": "origin_seq",
            "departure_seconds": "origin_dep_s",
            "departure_time": "origin_dep_time",
        }
    )
    right = st.rename(
        columns={
            "stop_id": "dest_stop_id",
            "stop_sequence": "dest_seq",
            "arrival_seconds": "dest_arr_s",
            "arrival_time": "dest_arr_time",
        }
    )

    m = (
        left.merge(
            right[["trip_id", "dest_stop_id", "dest_seq", "dest_arr_s", "dest_arr_time"]],
            on="trip_id",
            how="inner",
        )
        .merge(trips[["trip_id", "route_id"]], on="trip_id", how="inner")
    )

    m = m[
        (m["origin_stop_id"].astype(str) == origin_id)
        & (m["dest_stop_id"].astype(str) == dest_id)
        & (m["origin_seq"] < m["dest_seq"])
        & (m["origin_dep_s"] >= t0)
    ].copy()

    if m.empty:
        return m

    stops_small = gtfs.stops[["stop_id", "stop_name"]].copy() if "stop_name" in gtfs.stops.columns else gtfs.stops[["stop_id"]].copy()
    m = m.merge(
        stops_small.rename(columns={"stop_id": "origin_stop_id", "stop_name": "origin_name"}),
        on="origin_stop_id",
        how="left",
    ).merge(
        stops_small.rename(columns={"stop_id": "dest_stop_id", "stop_name": "dest_name"}),
        on="dest_stop_id",
        how="left",
    )

    if "route_short_name" in gtfs.routes.columns:
        m = m.merge(gtfs.routes[["route_id", "route_short_name"]], on="route_id", how="left")

    m["duration_min"] = ((m["dest_arr_s"] - m["origin_dep_s"]) / 60).round(1)

    cols = [
        c for c in [
            "route_id",
            "route_short_name",
            "trip_id",
            "origin_name",
            "dest_name",
            "origin_dep_time",
            "dest_arr_time",
            "duration_min",
        ] if c in m.columns
    ]
    return m[cols].sort_values(["origin_dep_time", "route_id"]).reset_index(drop=True)


def nearest_stop_for_dataset(dataset: str, lat: float, lon: float) -> NearestStopResult:
    gtfs = _load_gtfs_cached(dataset)
    stops = gtfs.stops.copy()

    if stops.empty or not {"stop_id", "stop_lat", "stop_lon"}.issubset(stops.columns):
        raise ValueError(f"Dataset sem paragens válidas: {dataset}")

    dists = _haversine_m(lat, lon, stops["stop_lat"], stops["stop_lon"])
    idx = dists.idxmin()

    stop_id = str(stops.loc[idx, "stop_id"])
    stop_name = str(stops.loc[idx, "stop_name"]) if "stop_name" in stops.columns else stop_id
    return NearestStopResult(dataset=dataset, stop_id=stop_id, stop_name=stop_name, distance_m=float(dists.loc[idx]))


def compare_nearest_network(lat: float, lon: float) -> tuple[NearestStopResult, NearestStopResult, str]:
    smtuc = nearest_stop_for_dataset("smtuc", lat, lon)
    metrobus = nearest_stop_for_dataset("metrobus", lat, lon)
    winner = "smtuc" if smtuc.distance_m <= metrobus.distance_m else "metrobus"
    return smtuc, metrobus, winner


def _collect_commute_options(
    home_lat: float,
    home_lon: float,
    work_lat: float,
    work_lon: float,
    day_str: str,
    time_str: str,
) -> list[pd.DataFrame]:
    rows: list[pd.DataFrame] = []

    for dataset in ("smtuc", "metrobus"):
        try:
            near_home = nearest_stop_for_dataset(dataset, home_lat, home_lon)
            near_work = nearest_stop_for_dataset(dataset, work_lat, work_lon)

            df = find_direct_options(
                dataset=dataset,
                origin_ref=near_home.stop_id,
                dest_ref=near_work.stop_id,
                day_str=day_str,
                time_str=time_str,
            )
            if df.empty:
                continue

            df = df.copy()
            df["dataset"] = dataset
            df["day"] = day_str
            df["time"] = time_str
            df["walk_home_m"] = round(near_home.distance_m, 1)
            df["walk_work_m"] = round(near_work.distance_m, 1)
            df["walk_home_min"] = (df["walk_home_m"] / WALK_SPEED_M_MIN).round(1)
            df["walk_work_min"] = (df["walk_work_m"] / WALK_SPEED_M_MIN).round(1)
            df["total_min_est"] = (df["duration_min"] + df["walk_home_min"] + df["walk_work_min"]).round(1)
            rows.append(df)
        except (ValueError, KeyError, TypeError):
            continue

    return rows


def _rank_commute_options(rows: list[pd.DataFrame]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    return (
        pd.concat(rows, ignore_index=True)
        .sort_values(["total_min_est", "duration_min", "dataset"])
        .drop_duplicates(subset=["dataset", "route_short_name", "origin_dep_time", "dest_arr_time"], keep="first")
        .reset_index(drop=True)
    )


def _pretty_print_commute(out: pd.DataFrame, limit: int, title: str, format_units: bool) -> None:
    disp = out.head(limit).copy().rename(columns={
        "dataset": "Rede",
        "day": "Dia",
        "time": "Hora",
        "route_short_name": "Linha",
        "origin_name": "Origem",
        "dest_name": "Destino",
        "origin_dep_time": "Partida",
        "dest_arr_time": "Chegada",
        "duration_min": "Viagem",
        "walk_home_m": "A pé casa",
        "walk_work_m": "A pé trabalho",
        "total_min_est": "Total estimado",
    })

    if format_units:
        if "Viagem" in disp.columns:
            disp["Viagem"] = disp["Viagem"].map(lambda x: f"{float(x):.1f} min")
        if "Total estimado" in disp.columns:
            disp["Total estimado"] = disp["Total estimado"].map(lambda x: f"{float(x):.1f} min")
        if "A pé casa" in disp.columns:
            disp["A pé casa"] = disp["A pé casa"].map(lambda x: f"{float(x):.0f} m")
        if "A pé trabalho" in disp.columns:
            disp["A pé trabalho"] = disp["A pé trabalho"].map(lambda x: f"{float(x):.0f} m")

    cols = [
        c for c in [
            "Rede", "Dia", "Hora", "Linha", "Origem", "Destino",
            "Partida", "Chegada", "Viagem", "A pé casa", "A pé trabalho", "Total estimado"
        ] if c in disp.columns
    ]

    print(f"\n=== {title} ===")
    print(disp[cols].to_string(index=False))


def suggest_random_commute_options(
    home_lat: float,
    home_lon: float,
    work_lat: float,
    work_lon: float,
    limit: int = 5,
    tries: int = 20,
) -> pd.DataFrame:
    for _ in range(tries):
        d = date.today() + timedelta(days=random.randint(0, 20))
        hh = random.randint(6, 22)
        mm = random.randint(0, 59)
        ss = random.choice([0, 30])

        day_str = d.strftime("%Y-%m-%d")
        time_str = f"{hh:02d}:{mm:02d}:{ss:02d}"

        rows = _collect_commute_options(
            home_lat=home_lat,
            home_lon=home_lon,
            work_lat=work_lat,
            work_lon=work_lon,
            day_str=day_str,
            time_str=time_str,
        )

        if rows:
            break

    if not rows:
        print("Não foi possível encontrar opções diretas nas tentativas aleatórias.")
        return pd.DataFrame()

    out = _rank_commute_options(rows)
    _pretty_print_commute(out=out, limit=limit, title="Melhores hipóteses casa -> trabalho", format_units=False)

    return out.head(limit)


def suggest_current_commute_options(
    home_lat: float,
    home_lon: float,
    work_lat: float,
    work_lon: float,
    limit: int = 3,
) -> pd.DataFrame:
    now = datetime.now()
    day_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    rows = _collect_commute_options(
        home_lat=home_lat,
        home_lon=home_lon,
        work_lat=work_lat,
        work_lon=work_lon,
        day_str=day_str,
        time_str=time_str,
    )

    if not rows:
        print("Sem opções diretas para a data/hora atual.")
        return pd.DataFrame()

    out = _rank_commute_options(rows)
    _pretty_print_commute(out=out, limit=limit, title=f"Top {limit} opções (agora)", format_units=True)

    return out.head(limit)


def next_monday(from_day: date) -> date:
    delta = (0 - from_day.weekday()) % 7
    return from_day + timedelta(days=delta)


def commute_options_for_datetime(
    home_lat: float,
    home_lon: float,
    work_lat: float,
    work_lon: float,
    day_str: str,
    time_str: str,
) -> pd.DataFrame:
    rows = _collect_commute_options(
        home_lat=home_lat,
        home_lon=home_lon,
        work_lat=work_lat,
        work_lon=work_lon,
        day_str=day_str,
        time_str=time_str,
    )
    return _rank_commute_options(rows)
