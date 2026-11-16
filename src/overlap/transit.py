from __future__ import annotations

import math
import random
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from config import (
    OUTPUTS_INTEGRATION_DIR,
    REACHABILITY_REFERENCE_DAY,
    TRANSFER_BUFFER_MIN,
    USE_FIXED_REFERENCE_DAY,
    WALK_SPEED_M_MIN,
)
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
    Resolve the reference day used by every GTFS-dependent visualization (integration,
    reachability/isochrones, population).

    Any explicit day provided by callers is intentionally ignored - the shared reference day is
    controlled by config.USE_FIXED_REFERENCE_DAY (single global switch), not by individual call
    sites. When True, returns the fixed config.REACHABILITY_REFERENCE_DAY (reproducible, doesn't
    depend on when the code runs). When False, returns the nearest business day to today
    (dynamic).
    """
    _ = day_str  # kept for API compatibility and explicit intent
    if USE_FIXED_REFERENCE_DAY and REACHABILITY_REFERENCE_DAY:
        return date.fromisoformat(REACHABILITY_REFERENCE_DAY)
    return nearest_business_day(date.today())


def _towards_arrival_times_for_stop(
    gtfs, trips: pd.DataFrame, target_stop_id: str, towards_candidates: list[str]
) -> list[str]:
    """Horas de passagem em `target_stop_id` das viagens que, DEPOIS dele, passam numa paragem de
    `towards_candidates` (o sentido define-se pelas paragens, não por `trips.direction_id`).

    O espelho de `_arrival_times_for_stop` (que exige uma paragem de ORIGEM antes do alvo): aqui o
    alvo pode ser a própria origem da viagem (ex.: "Portagem" é a 1ª paragem do Metro sentido
    Serpins), por isso filtra-se pelo que vem a seguir. Substitui o antigo filtro por
    direction_id + route_id, que dependia da convenção de cada feed - no feed sintético o
    sentido 1 é "a partir de Portagem" e no GTFS oficial de 2025 é o 0 - e que trocava de
    sentido em silêncio ao trocar de dados. Viagens que TERMINAM no alvo (ex.: ramais da fase 2)
    não têm nada depois e ficam de fora sem precisar de filtrar a rota."""
    if trips.empty or not towards_candidates:
        return []
    st = gtfs.stop_times.copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)
    st = st[st["trip_id"].isin(trips["trip_id"].astype(str))]
    if st.empty:
        return []
    st["seq"] = pd.to_numeric(st["stop_sequence"], errors="coerce")

    at_target = st[st["stop_id"] == str(target_stop_id)]
    towards = set(str(s) for s in towards_candidates) - {str(target_stop_id)}
    last_towards_seq = st[st["stop_id"].isin(towards)].groupby("trip_id")["seq"].max()
    at_target = at_target[at_target["trip_id"].map(last_towards_seq) > at_target["seq"]]
    return sorted(set(at_target["arrival_time"].astype(str).tolist()))


def _stop_latlon(gtfs, stop_id: str) -> tuple[float, float]:
    row = gtfs.stops[gtfs.stops["stop_id"].astype(str) == str(stop_id)]
    if row.empty:
        raise ValueError(f"Paragem sem coordenadas: {stop_id}")
    return float(row.iloc[0]["stop_lat"]), float(row.iloc[0]["stop_lon"])


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def transfer_minutes(
    gtfs_a,
    stop_a: str,
    gtfs_b,
    stop_b: str,
    walk_speed_m_min: float = WALK_SPEED_M_MIN,
    buffer_min: float = TRANSFER_BUFFER_MIN,
) -> float:
    """Tempo mínimo (min) para mudar entre duas paragens (de feeds possivelmente diferentes):
    distância real a pé ÷ velocidade + margem fixa (ver config.TRANSFER_BUFFER_MIN)."""
    dist = _distance_m(_stop_latlon(gtfs_a, stop_a), _stop_latlon(gtfs_b, stop_b))
    return round(dist / float(walk_speed_m_min) + float(buffer_min), 2)


def _optional_minutes(value: object) -> float:
    """Minutos de transbordo de uma célula da tabela: vazio/NaN/ausente -> 0 (tabelas antigas,
    sem as colunas de transbordo, continuam a funcionar com o comportamento anterior)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(out) else out


def _non_empty_time(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and text.lower() != "nan" else None


def compute_transfer_waits(schedule_df: pd.DataFrame) -> list[dict]:
    """Regra ÚNICA de espera no transbordo, partilhada pelo gráfico (visualizations/integration.py)
    e pelas métricas (`build_metro_bus_connection_metrics`).

    Lê o contrato de colunas das tabelas de `build_line_stop_vs_metro_table` /
    `build_reverse_stop_vs_metro_table`: `metro_time_from_origin` = chegadas que desencadeiam a
    espera ("gatilhos"), `bus_time` (+ `bus_line_passage`) = partidas a apanhar ("alvos").
    `trigger_transfer_min` / `target_transfer_min` (opcionais, alinhadas com cada coluna) somam o
    tempo de transbordo a pé; um alvo só é apanhável se partir em ou depois de
    `gatilho + transbordo`. Antes não havia transbordo nenhum: uma partida à mesma hora da chegada
    contava como ligação perfeita de 0 min, fisicamente impossível.

    Devolve, por gatilho (ordenado), `trigger_s`, `transfer_min`, `target_s`/`target_time`/
    `target_line` (None se não houver ligação) e `wait_min` = minutos entre a chegada e a partida
    apanhada (inclui a caminhada) ou None.
    """
    if schedule_df is None or schedule_df.empty:
        return []
    line_col = next((c for c in ("bus_line_passage", "bus_line") if c in schedule_df.columns), None)

    targets: list[tuple[int, float, str, str]] = []
    triggers: set[tuple[int, float]] = set()
    for row in schedule_df.to_dict("records"):
        target_time = _non_empty_time(row.get("bus_time"))
        if target_time:
            line = str(row.get(line_col, "")).strip() if line_col else ""
            targets.append((_hhmmss_to_seconds(target_time), _optional_minutes(row.get("target_transfer_min")), target_time, line))
        trigger_time = _non_empty_time(row.get("metro_time_from_origin"))
        if trigger_time:
            triggers.add((_hhmmss_to_seconds(trigger_time), _optional_minutes(row.get("trigger_transfer_min"))))
    targets.sort(key=lambda tg: (tg[0], tg[3]))

    out: list[dict] = []
    for trigger_s, trigger_tr in sorted(triggers):
        target = next((tg for tg in targets if tg[0] >= trigger_s + (trigger_tr + tg[1]) * 60.0 - 1e-6), None)
        out.append(
            {
                "trigger_s": trigger_s,
                # Sem ligação -> None (não 0.0, que se leria como "transbordo instantâneo").
                "transfer_min": round(trigger_tr + target[1], 2) if target else None,
                "target_s": target[0] if target else None,
                "target_time": target[2] if target else "",
                "target_line": target[3] if target else "",
                "wait_min": round((target[0] - trigger_s) / 60.0, 2) if target else None,
            }
        )
    return out


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
    # Filtra SEMPRE (mesmo com o conjunto vazio = dia sem serviço) - ver _active_service_ids.
    all_bus_trips = all_bus_trips[all_bus_trips["service_id"].isin(bus_services)]

    route_to_line = {}
    if "route_short_name" in routes.columns:
        route_to_line = dict(
            zip(
                routes["route_id"].astype(str).tolist(),
                routes["route_short_name"].astype(str).str.strip().tolist(),
            )
        )

    # A linha identifica-se pelo número público (route_short_name). O route_id só serve quando o
    # feed não tem números públicos nenhuns: nos feeds SMTUC antigos o route_id "54" é a linha 5F
    # (Pedrulha-Portagem) e a 54 verdadeira tem route_id 684/685 - recorrer ao route_id quando o
    # número não existe apanhava a linha errada em silêncio (ex.: Ep202, que ainda não tinha a 54).
    short_names = routes["route_short_name"].str.strip()
    use_route_id = not short_names.replace({"nan": "", "None": ""}).astype(bool).any()
    match_col = routes["route_id"].str.strip() if use_route_id else short_names

    bus_events: list[dict[str, str]] = []
    missing = [v for v in line_values if not (match_col == v).any()]
    if missing:
        raise ValueError(
            f"Linha(s) não encontrada(s) no feed: {', '.join(missing)} (procuradas em "
            f"{'route_id' if use_route_id else 'route_short_name'})"
        )
    for line_val in line_values:
        route_ids = routes[match_col == line_val]["route_id"].drop_duplicates().tolist()

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
        line_events = _arrival_events_for_stop(
            gtfs=gtfs_bus,
            trips=line_trips,
            target_stop_id=line_target_stop_id,
            origin_candidates=bus_origin_candidates,
            line_by_trip=line_by_trip,
        )
        # Paragem física usada por esta linha (pode ser diferente entre linhas no mesmo nó - ex.:
        # Portagem tem várias) - necessária para o tempo de transbordo de cada passagem.
        for ev in line_events:
            ev["stop_id"] = str(line_target_stop_id)
        bus_events.extend(line_events)

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
    # Filtra SEMPRE (mesmo com o conjunto vazio = dia sem serviço) - ver _active_service_ids.
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
    bus_stop_ids = [ev.get("stop_id", "") for ev in bus_events]
    transfer_by_stop = {
        sid: transfer_minutes(gtfs_metro, metro_stop_id, gtfs_bus, sid) for sid in dict.fromkeys(bus_stop_ids) if sid
    }
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
        "bus_stop_id",
        "metro_stop_id",
        "target_transfer_min",
        "trigger_transfer_min",
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
                # Transbordo metro -> esta paragem de autocarro (alinhado com bus_time).
                "bus_stop_id": bus_stop_ids[i] if i < len(bus_stop_ids) else "",
                "metro_stop_id": str(metro_stop_id),
                "target_transfer_min": transfer_by_stop.get(bus_stop_ids[i]) if i < len(bus_stop_ids) else None,
                "trigger_transfer_min": 0.0 if i < len(metro_times) else None,
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
    metro_towards_ref: str,
    day_str: str | None = None,
    bus_origin_ref: str = "Portagem",
    output_csv_name: str | None = None,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Gera a tabela do sentido INVERSO de `build_line_stop_vs_metro_table`: em vez de "quanto
    tempo espera quem chega de metro pelo próximo autocarro", mede "quanto tempo espera quem
    chega de autocarro pela próxima partida de metro".

    `metro_towards_ref` identifica o sentido do metro que continua a viagem a partir de
    `metro_stop_ref`: só contam as viagens que passam numa paragem com este nome/id DEPOIS de
    `metro_stop_ref` (ex.: em Portagem, "Vale das Flores" = sentido Serpins). Usa-se uma paragem
    e não `trips.direction_id`/`route_id` porque esses códigos mudam de feed para feed (ver
    `_towards_arrival_times_for_stop`).

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
    metro_towards_candidates = _matching_stop_ids(gtfs_metro, str(metro_towards_ref))

    if not bus_target_candidates:
        raise ValueError(f"Paragem de autocarro não encontrada: {bus_stop_ref}")
    if not metro_target_candidates:
        raise ValueError(f"Paragem de metro não encontrada: {metro_stop_ref}")
    if not metro_towards_candidates:
        raise ValueError(f"Paragem de metro (sentido) não encontrada: {metro_towards_ref}")

    metro_services = _active_service_ids(gtfs_metro, day)
    metro_trips = gtfs_metro.trips.copy()
    metro_trips["service_id"] = metro_trips["service_id"].astype(str)
    # Filtra SEMPRE (mesmo com o conjunto vazio = dia sem serviço) - ver _active_service_ids.
    metro_trips = metro_trips[metro_trips["service_id"].isin(metro_services)]

    metro_stop_id = _pick_best_target_stop_id(
        gtfs=gtfs_metro,
        trips=metro_trips,
        target_candidates=metro_target_candidates,
    )
    metro_departure_times = _towards_arrival_times_for_stop(
        gtfs=gtfs_metro,
        trips=metro_trips,
        target_stop_id=metro_stop_id,
        towards_candidates=metro_towards_candidates,
    )

    bus_events, line_label, line_slug = _resolve_bus_arrival_events(
        gtfs_bus, day, bus_target_candidates, bus_origin_candidates, line_number
    )
    # (hora, paragem) únicos: com várias linhas, a mesma hora pode chegar a paragens diferentes,
    # cada uma com o seu tempo de transbordo até ao metro.
    bus_arrivals = sorted(
        {(str(ev["time"]), str(ev.get("stop_id", ""))) for ev in bus_events},
        key=lambda a: (_hhmmss_to_seconds(a[0]), a[1]),
    )
    bus_arrival_times = [time for time, _ in bus_arrivals]
    transfer_by_stop = {
        sid: transfer_minutes(gtfs_bus, sid, gtfs_metro, metro_stop_id) for _, sid in bus_arrivals if sid
    }

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
        "bus_stop_id",
        "metro_stop_id",
        "target_transfer_min",
        "trigger_transfer_min",
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
                # Transbordo desta paragem de autocarro -> metro (alinhado com metro_time_from_origin,
                # que nesta tabela invertida guarda as chegadas de autocarro).
                "bus_stop_id": bus_arrivals[i][1] if i < len(bus_arrivals) else "",
                "metro_stop_id": str(metro_stop_id),
                "target_transfer_min": 0.0 if i < len(metro_departure_times) else None,
                "trigger_transfer_min": transfer_by_stop.get(bus_arrivals[i][1]) if i < len(bus_arrivals) else None,
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
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Calcula métricas de coordenação metro -> autocarro e grava um CSV em outputs/integration.

    Por omissão escreve em `OUTPUTS_INTEGRATION_DIR` (tal como `build_line_stop_vs_metro_table`) -
    passa `output_dir` para escrever noutro sítio (ex.: subpasta `atual/` do dashboard).
    """
    schedule_df = build_line_stop_vs_metro_table(
        metro_stop_ref=metro_stop_ref,
        bus_stop_ref=bus_stop_ref,
        line_number=line_number,
        day_str=day_str,
        metro_origin_ref=metro_origin_ref,
        bus_origin_ref=bus_origin_ref,
        output_dir=output_dir,
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
        # Mesma regra (com transbordo a pé) que o gráfico de esperas - ver compute_transfer_waits.
        waits = compute_transfer_waits(schedule_df)
        metro_times = [w["trigger_s"] for w in waits]
        waits_min: list[float | None] = [w["wait_min"] for w in waits]
        transfer_values = pd.Series([w["transfer_min"] for w in waits if w["wait_min"] is not None], dtype="float")

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
            {
                "scope": "overall",
                "metric": "transfer_walk_median_min",
                "value": round(float(transfer_values.median()), 2) if not transfer_values.empty else None,
                "unit": "min",
                "note": "tempo mínimo de transbordo (caminhada + margem) já incluído nas esperas",
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

    out_dir = Path(output_dir) if output_dir is not None else (
        Path(__file__).resolve().parents[2] / OUTPUTS_INTEGRATION_DIR
    )
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
    # Filtra SEMPRE (mesmo com o conjunto vazio = dia sem serviço) - ver _active_service_ids.
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
