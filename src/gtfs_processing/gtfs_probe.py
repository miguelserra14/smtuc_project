from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, date
from typing import Iterable

import pandas as pd


@dataclass
class NearestStopResult:
    dataset: str
    stop_id: str
    stop_name: str
    distance_m: float


# -----------------------------------------------------------------------------
# 1) Helpers básicos de parsing/normalização (baixo nível)
# -----------------------------------------------------------------------------

def _to_seconds(hhmmss: str) -> int:
    """Parse a "HH:MM:SS" query time string to seconds-from-midnight.

    Deliberately strict (raises on malformed input) - this parses user-supplied query time
    strings, not raw feed rows, so failing fast on bad input is correct here. Contrast with
    `gtfs_processing.gtfs._to_seconds`, which is lenient on purpose (parses the entire raw
    stop_times feed at load time, where one bad row must not abort ingestion).
    """
    try:
        h, m, s = map(int, str(hhmmss).split(":"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Hora inválida (esperado HH:MM:SS): {hhmmss!r}") from exc
    return h * 3600 + m * 60 + s


def _parse_day(day_str: str) -> date:
    return datetime.strptime(day_str, "%Y-%m-%d").date()


def _weekday_col(d: date) -> str:
    return d.strftime("%A").lower()  # monday, tuesday, ...


def _haversine_m(lat1: float, lon1: float, lat2: Iterable[float], lon2: Iterable[float]) -> pd.Series:
    r = 6371000.0
    lat1r = math.radians(lat1)
    lon1r = math.radians(lon1)

    lat2s = pd.Series(lat2, dtype="float64").apply(math.radians)
    lon2s = pd.Series(lon2, dtype="float64").apply(math.radians)

    dlat = lat2s - lat1r
    dlon = lon2s - lon1r

    a = (dlat / 2).apply(math.sin) ** 2 + pd.Series(
        [math.cos(lat1r) * math.cos(v) for v in lat2s], dtype="float64"
    ) * (dlon / 2).apply(math.sin) ** 2

    c = 2 * a.apply(lambda x: math.atan2(math.sqrt(x), math.sqrt(1 - x)))
    return r * c


# -----------------------------------------------------------------------------
# 2) Helpers GTFS intermédios (filtragem e resolução de entidades)
# -----------------------------------------------------------------------------

def _normalize_service_id(value: str) -> str:
    return str(value).strip().upper().replace("_", " ")


# calendar.txt/calendar_dates.txt em alguns feeds usam um espaço de nomes de service_id (ex.:
# "Dias Uteis") completamente diferente do usado em trips.txt (ex.: "WD") - confirmado no
# dataset metrobus, onde nenhum service_id de trips.txt aparece em calendar.txt. Estes grupos
# cobrem as variantes conhecidas de cada um dos 3 padrões semanais, para resolver esse caso.
_WEEKDAY_ALIASES = {_normalize_service_id(v) for v in ("DIAS UTEIS", "WEEKDAY", "WEEKDAYS", "WD", "WKD")}
_SATURDAY_ALIASES = {_normalize_service_id(v) for v in ("SABADOS", "SABADO", "SATURDAY", "SAT", "SAB")}
_SUNDAY_ALIASES = {_normalize_service_id(v) for v in ("DOMINGOS E FERIADOS", "DOMINGO", "SUNDAY", "SUN", "DOM")}

_ALIAS_WEEKDAY_MASK = (1, 1, 1, 1, 1, 0, 0)
_ALIAS_SATURDAY_MASK = (0, 0, 0, 0, 0, 1, 0)
_ALIAS_SUNDAY_MASK = (0, 0, 0, 0, 0, 0, 1)


def _service_id_aliases_for_day(day: date) -> set[str]:
    weekday = day.weekday()
    if weekday <= 4:
        return set(_WEEKDAY_ALIASES)
    if weekday == 5:
        return set(_SATURDAY_ALIASES)
    return set(_SUNDAY_ALIASES)


def _alias_day_mask(service_id: str) -> tuple[int, ...] | None:
    """Resolve a service_id like "WD"/"SAT"/"SUN" straight to a (mon..sun) weekly mask,
    without needing a calendar.txt row - used as a fallback when a service_id's own
    calendar.txt entry can't be found under a matching key (see _active_service_ids)."""
    norm = _normalize_service_id(service_id)
    if norm in _WEEKDAY_ALIASES:
        return _ALIAS_WEEKDAY_MASK
    if norm in _SATURDAY_ALIASES:
        return _ALIAS_SATURDAY_MASK
    if norm in _SUNDAY_ALIASES:
        return _ALIAS_SUNDAY_MASK
    return None


def _calendar_active_service_ids(gtfs, d: date) -> set[str]:
    """Service ids ativos em `d` segundo calendar.txt/calendar_dates.txt, no espaço de nomes
    próprio de calendar.txt (pode não bater certo com o de trips.txt - ver _active_service_ids)."""
    # fallback: sem calendar -> usa todos os services dos trips
    if gtfs.calendar.empty or "service_id" not in gtfs.calendar.columns:
        return set(gtfs.trips["service_id"].dropna().astype(str).unique())

    cal = gtfs.calendar.copy()
    cal["service_id"] = cal["service_id"].astype(str)
    ymd = int(d.strftime("%Y%m%d"))
    wd = _weekday_col(d)

    base = cal[
        (cal.get(wd, 0) == 1)
        & (cal["start_date"] <= ymd)
        & (cal["end_date"] >= ymd)
    ]["service_id"]

    active = set(base.astype(str).tolist())

    # exceções (calendar_dates)
    if not gtfs.calendar_dates.empty and {"service_id", "date", "exception_type"}.issubset(gtfs.calendar_dates.columns):
        cd = gtfs.calendar_dates[gtfs.calendar_dates["date"] == ymd]
        for _, r in cd.iterrows():
            sid = str(r["service_id"])
            ex = int(r["exception_type"])
            if ex == 1:
                active.add(sid)
            elif ex == 2:
                active.discard(sid)

    return active


def _active_service_ids(gtfs, d: date) -> set[str]:
    """Service ids ativos em `d`, garantidamente no espaço de nomes de trips.txt (para que os
    chamadores possam filtrar `trips` com segurança via `.isin(...)`).

    calendar.txt/calendar_dates.txt por vezes usam um espaço de nomes de service_id
    completamente diferente do de trips.txt (confirmado no feed metrobus: calendar.txt usa
    "Dias Uteis"/"Sabados"/"Domingos e Feriados", trips.txt usa "WD"/"SAT"/"SUN" - nunca se
    cruzam). Quando isso acontece, uma correspondência direta não encontra nada e todas as
    trips desse dataset seriam silenciosamente excluídas de qualquer cálculo dependente do
    dia (reachability, sugestões de percurso, contagem de partidas). Nesse caso cai-se para
    uma correspondência por alias de dia-da-semana contra os próprios service_id de trips.txt.
    """
    trip_service_ids = set(gtfs.trips["service_id"].dropna().astype(str).unique())
    if not trip_service_ids:
        return set()

    active_by_calendar = _calendar_active_service_ids(gtfs, d)
    if not active_by_calendar:
        return trip_service_ids

    active_norm = {_normalize_service_id(v) for v in active_by_calendar}
    selected = {sid for sid in trip_service_ids if _normalize_service_id(sid) in active_norm}
    if selected:
        return selected

    aliases = _service_id_aliases_for_day(d)
    fallback = {sid for sid in trip_service_ids if _normalize_service_id(sid) in aliases}

    # Se calendar_dates.txt tiver uma exceção para este dia mas os service_id de trips.txt não
    # baterem certo com calendar.txt/calendar_dates.txt de todo, não há forma fiável de aplicar
    # essa exceção (a feed não liga o service_id "adicionado" a nenhuma trip) - avisa em vez de
    # fingir silenciosamente que é um dia normal.
    calendar_dates = getattr(gtfs, "calendar_dates", None)
    if calendar_dates is not None and not calendar_dates.empty and {"service_id", "date", "exception_type"}.issubset(calendar_dates.columns):
        ymd = int(d.strftime("%Y%m%d"))
        day_exceptions = calendar_dates[calendar_dates["date"].astype(int) == ymd]
        removed_norm = {
            _normalize_service_id(v)
            for v in day_exceptions.loc[day_exceptions["exception_type"].astype(int) == 2, "service_id"]
        }
        if removed_norm & aliases:
            print(
                f"[WARNING] calendar_dates.txt remove o serviço normal em {ymd}, mas os "
                f"service_id de trips.txt ({sorted(trip_service_ids)}) não correspondem a "
                f"nenhum service_id de calendar.txt/calendar_dates.txt - a exceção não pode ser "
                f"aplicada com fiabilidade; a usar o horário normal do dia da semana."
            )

    return fallback


def _resolve_stop_id(gtfs, ref: str) -> str:
    ref = str(ref).strip()

    # 1) id direto
    ids = gtfs.stops["stop_id"].astype(str)
    if (ids == ref).any():
        return ref

    # 2) nome exato
    names = gtfs.stops["stop_name"].astype(str) if "stop_name" in gtfs.stops.columns else pd.Series([], dtype=str)
    exact = gtfs.stops[names.str.lower() == ref.lower()]
    if len(exact) == 1:
        return str(exact.iloc[0]["stop_id"])

    # 3) nome parcial
    part = gtfs.stops[names.str.contains(ref, case=False, na=False)]
    if len(part) == 1:
        return str(part.iloc[0]["stop_id"])
    if len(part) > 1:
        sample = part[["stop_id", "stop_name"]].head(5).to_dict(orient="records")
        raise ValueError(f"Paragem ambígua '{ref}'. Exemplos: {sample}")

    raise ValueError(f"Paragem não encontrada: '{ref}'")
