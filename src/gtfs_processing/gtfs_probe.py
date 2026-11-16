from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from functools import lru_cache
from typing import Iterable

import pandas as pd

from config import FERIADOS_COMO_DOMINGO, FERIADOS_FIXOS_MMDD, FERIADOS_MOVEIS_OFFSET_PASCOA


class ServiceCalendarError(ValueError):
    """O dia pedido não pode ser avaliado com fiabilidade contra o calendário de um feed GTFS
    (fora do período coberto, feed sem calendário, ou service_id impossíveis de ligar às trips).

    Subclasse de ValueError de propósito: os chamadores que já apanham ValueError (ex.:
    `_collect_commute_options`) continuam a degradar como antes, mas o erro deixa de ser
    silencioso - antes estes casos devolviam TODOS os service_id do feed (dias úteis + sábados +
    domingos somados), o que triplicava a oferta sem qualquer aviso.
    """


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


_DAY_COLS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _easter_sunday(year: int) -> date:
    """Domingo de Páscoa (calendário gregoriano, algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=64)
def public_holidays(year: int) -> frozenset[date]:
    """Feriados de `year` segundo config (FERIADOS_FIXOS_MMDD + FERIADOS_MOVEIS_OFFSET_PASCOA)."""
    fixed = {date.fromisoformat(f"{year:04d}-{mmdd}") for mmdd in FERIADOS_FIXOS_MMDD}
    easter = _easter_sunday(year)
    moving = {easter + timedelta(days=int(offset)) for offset in FERIADOS_MOVEIS_OFFSET_PASCOA}
    return frozenset(fixed | moving)


def is_public_holiday(d: date) -> bool:
    return d in public_holidays(d.year)


def _ymd(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def _calendar_dates_frame(gtfs) -> pd.DataFrame:
    """calendar_dates.txt normalizado (date/exception_type como int, service_id como str), ou
    um DataFrame vazio se o feed não o tiver / não tiver as colunas obrigatórias."""
    cd = getattr(gtfs, "calendar_dates", None)
    if cd is None or cd.empty or not {"service_id", "date", "exception_type"}.issubset(cd.columns):
        return pd.DataFrame(columns=["service_id", "date", "exception_type"])
    out = cd[["service_id", "date", "exception_type"]].copy()
    out["service_id"] = out["service_id"].astype(str)
    out["date"] = pd.to_numeric(out["date"], errors="coerce")
    out["exception_type"] = pd.to_numeric(out["exception_type"], errors="coerce")
    return out.dropna(subset=["date", "exception_type"]).astype({"date": int, "exception_type": int})


def _has_calendar(gtfs) -> bool:
    cal = getattr(gtfs, "calendar", None)
    return cal is not None and not cal.empty and "service_id" in cal.columns


def feed_service_period(gtfs) -> tuple[int, int] | None:
    """(primeiro, último) dia YYYYMMDD coberto pelo calendário do feed: união dos intervalos
    start_date..end_date de calendar.txt com as datas adicionadas (exception_type=1) em
    calendar_dates.txt. None se o feed não tiver calendário nenhum."""
    bounds: list[int] = []
    if _has_calendar(gtfs) and {"start_date", "end_date"}.issubset(gtfs.calendar.columns):
        starts = pd.to_numeric(gtfs.calendar["start_date"], errors="coerce").dropna()
        ends = pd.to_numeric(gtfs.calendar["end_date"], errors="coerce").dropna()
        if not starts.empty and not ends.empty:
            bounds += [int(starts.min()), int(ends.max())]
    cd = _calendar_dates_frame(gtfs)
    added = cd.loc[cd["exception_type"] == 1, "date"]
    if not added.empty:
        bounds += [int(added.min()), int(added.max())]
    if not bounds:
        return None
    return min(bounds), max(bounds)


def _effective_weekday(gtfs, d: date) -> int:
    """Dia da semana (0=seg..6=dom) a usar para `d`: um feriado conta como domingo (ver
    config.FERIADOS_COMO_DOMINGO), EXCETO se o próprio feed já tiver alguma exceção em
    calendar_dates.txt para essa data - aí é o feed que manda (evita somar o serviço de domingo
    a um serviço especial que o operador já definiu para esse dia)."""
    if FERIADOS_COMO_DOMINGO and is_public_holiday(d):
        cd = _calendar_dates_frame(gtfs)
        if not (cd["date"] == _ymd(d)).any():
            return 6
    return d.weekday()


def _service_id_aliases_for_day(day: date, weekday: int | None = None) -> set[str]:
    weekday = day.weekday() if weekday is None else weekday
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
    próprio de calendar.txt (pode não bater certo com o de trips.txt - ver _active_service_ids).

    Levanta ServiceCalendarError se o feed não tiver calendário nenhum ou se `d` estiver fora do
    período que o feed cobre (ver `feed_service_period`). Antes, ambos os casos acabavam a
    devolver TODOS os service_id das trips (úteis + sábados + domingos somados) sem aviso -
    p.ex. a partir de 2027-01-01, quando os calendários atuais (end_date=20261231) expiram.
    Um dia DENTRO do período sem nenhum serviço ativo é legítimo e devolve um conjunto vazio.
    """
    period = feed_service_period(gtfs)
    if period is None:
        raise ServiceCalendarError(
            "Feed GTFS sem calendar.txt nem calendar_dates.txt utilizáveis - impossível saber que "
            "serviços correm em cada dia."
        )
    ymd = _ymd(d)
    if not (period[0] <= ymd <= period[1]):
        raise ServiceCalendarError(
            f"Dia {d.isoformat()} fora do período coberto pelo feed GTFS "
            f"({period[0]}..{period[1]}). Atualiza os dados GTFS ou escolhe um dia de referência "
            f"dentro do período (config.SCENARIOS[...]['reference_day'] / USE_FIXED_REFERENCE_DAY)."
        )

    active: set[str] = set()
    if _has_calendar(gtfs):
        cal = gtfs.calendar.copy()
        cal["service_id"] = cal["service_id"].astype(str)
        wd = _DAY_COLS[_effective_weekday(gtfs, d)]
        day_flag = pd.to_numeric(cal[wd], errors="coerce") if wd in cal.columns else pd.Series(0, index=cal.index)
        start = pd.to_numeric(cal.get("start_date", pd.Series(0, index=cal.index)), errors="coerce")
        end = pd.to_numeric(cal.get("end_date", pd.Series(99999999, index=cal.index)), errors="coerce")
        base = cal.loc[(day_flag == 1) & (start <= ymd) & (end >= ymd), "service_id"]
        active = set(base.tolist())

    # exceções (calendar_dates)
    cd = _calendar_dates_frame(gtfs)
    for sid, ex in cd.loc[cd["date"] == ymd, ["service_id", "exception_type"]].itertuples(index=False):
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

    Nunca devolve "todos os serviços" como fallback (ver `_calendar_active_service_ids`): um dia
    sem serviço dá um conjunto vazio, e os chamadores devem filtrar SEMPRE por este resultado
    (`trips[trips.service_id.isin(...)]`), mesmo vazio. Levanta ServiceCalendarError quando o
    dia está fora do período do feed, ou quando nenhum service_id de trips.txt consegue ser
    ligado ao calendário (nem diretamente nem por alias) - aí qualquer resultado seria inventado.
    Feriados contam como domingo (ver `_effective_weekday`).
    """
    trip_service_ids = set(gtfs.trips["service_id"].dropna().astype(str).unique())
    if not trip_service_ids:
        return set()

    active_by_calendar = _calendar_active_service_ids(gtfs, d)

    calendar_ids_norm = set()
    if _has_calendar(gtfs):
        calendar_ids_norm |= {_normalize_service_id(v) for v in gtfs.calendar["service_id"].astype(str)}
    calendar_ids_norm |= {_normalize_service_id(v) for v in _calendar_dates_frame(gtfs)["service_id"]}
    trips_norm = {_normalize_service_id(sid) for sid in trip_service_ids}
    all_aliases = _WEEKDAY_ALIASES | _SATURDAY_ALIASES | _SUNDAY_ALIASES
    if not (trips_norm & calendar_ids_norm) and not (trips_norm & all_aliases):
        raise ServiceCalendarError(
            f"Nenhum service_id de trips.txt ({sorted(trip_service_ids)}) corresponde ao "
            f"calendário do feed ({sorted(calendar_ids_norm)}) nem a um alias conhecido de dia da "
            f"semana - impossível saber que viagens correm em {d.isoformat()}."
        )

    if not active_by_calendar:
        return set()

    active_norm = {_normalize_service_id(v) for v in active_by_calendar}
    selected = {sid for sid in trip_service_ids if _normalize_service_id(sid) in active_norm}
    if selected:
        return selected

    # Espaços de nomes diferentes (caso metrobus): só se recorre a aliases quando trips.txt NÃO
    # partilha nenhum service_id com o calendário - se partilha, um "selected" vazio quer
    # simplesmente dizer que nenhuma das viagens corre hoje.
    if trips_norm & calendar_ids_norm:
        return set()

    aliases = _service_id_aliases_for_day(d, _effective_weekday(gtfs, d))
    fallback = {sid for sid in trip_service_ids if _normalize_service_id(sid) in aliases}

    # Se calendar_dates.txt tiver uma exceção para este dia mas os service_id de trips.txt não
    # baterem certo com calendar.txt/calendar_dates.txt de todo, não há forma fiável de aplicar
    # essa exceção (a feed não liga o service_id "adicionado" a nenhuma trip) - avisa em vez de
    # fingir silenciosamente que é um dia normal.
    cd = _calendar_dates_frame(gtfs)
    if not cd.empty:
        ymd = _ymd(d)
        day_exceptions = cd[cd["date"] == ymd]
        removed_norm = {
            _normalize_service_id(v)
            for v in day_exceptions.loc[day_exceptions["exception_type"] == 2, "service_id"]
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
