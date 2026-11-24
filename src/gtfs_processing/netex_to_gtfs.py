"""Conversor NeTEx (perfil EPIP da AGIT) -> tabelas GTFS (D2.1), usado por scripts/build_feeds.py.

Mapeamento (ver docs/integracao_dados_agit/README.md, secção 4):

    agency      Operator (gtfs:agency_id, Name, ContactDetails/Url, Phone; fuso das FrameDefaults)
    routes      Line (gtfs:route_id, ShortName -> route_short_name, Name -> route_long_name,
                TransportMode, Presentation/Colour/TextColour)
    stops       ScheduledStopPoint (gtfs:stop_id, Name, Location, PublicCode -> stop_code)
    trips       ServiceJourney (gtfs:trip_id, Name -> trip_short_name, DayTypeRef -> service_id) ->
                ServiceJourneyPattern -> Route (DirectionType outbound/inbound -> 0/1, LineRef)
    stop_times  TimetabledPassingTime -> StopPointInJourneyPattern (order -> stop_sequence,
                ScheduledStopPointRef, ForBoarding/ForAlighting -> pickup_type/drop_off_type)
    calendar    UicOperatingPeriod.ValidDayBits (1 bit por dia desde FromDate) via
                DayTypeAssignment -> PADRÃO SEMANAL + exceções em calendar_dates, nunca uma data
                por linha: config.FERIADOS_COMO_DOMINGO só atua em datas sem exceção no feed, por
                isso um feed só de datas explícitas punha os feriados não codificados (o Metro não
                os codifica) com o serviço do dia da semana.

Horas depois da meia-noite: as horas vêm em relógio de 24 h e o dia seguinte é marcado por
ArrivalDayOffset/DepartureDayOffset (NeTEx do Metro de 2026-11-11: 447 + 447, em 32 viagens).
O conversor:
  1. usa ArrivalDayOffset/DepartureDayOffset quando a viagem os tiver (+24 h por dia);
  2. só numa viagem SEM nenhum offset (reserva para exports que os percam): soma 24 h sempre que
     a hora recua dentro da viagem (23:50 -> 00:05 = 24:05), e uma viagem que COMEÇA antes de
     `night_start_before` (04:00) passa toda a 24:xx - é a cauda da noite do dia de serviço
     anterior (o GTFS de 2025 do mesmo operador tem 10 viagens a começar às 24:xx e nenhuma
     antes das 05:00; no NeTEx não há partidas entre as 00:40 e as 04:42).
Cada caso é contado no relatório, que vai para o PROVENANCE.json (no Metro de 2026-11-11 a
reserva não corrige nenhuma viagem).

Tudo o que o conversor não percebe (referência por resolver, DayType com 0 ou 2 períodos,
ValidDayBits com o comprimento errado, sentido desconhecido, viagem com mais de um DayType)
levanta NetexError - nunca se adivinha em silêncio.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, timedelta

from gtfs_processing.timeutil import hhmmss_to_seconds, seconds_to_hhmmss

NS = "{http://www.netex.org.uk/netex}"

Table = tuple[list[str], list[dict[str, str]]]

ROUTE_TYPES = {"bus": "3", "tram": "0", "rail": "2", "metro": "1", "water": "4", "coach": "3"}
DIRECTIONS = {"outbound": "0", "inbound": "1"}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class NetexError(ValueError):
    pass


# --------------------------------------------------------------------------- utilitários XML


def _text(el: ET.Element | None, path: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(path)
    return (found.text or "").strip() if found is not None and found.text is not None else default


def _key(el: ET.Element, name: str) -> str:
    for kv in el.iter(f"{NS}KeyValue"):
        if _text(kv, f"{NS}Key") == name:
            return _text(kv, f"{NS}Value")
    raise NetexError(f"{el.tag.removeprefix(NS)} {el.get('id')}: sem {name} na keyList")


def _ref(el: ET.Element, tag: str) -> str:
    found = el.find(f"{NS}{tag}")
    if found is None or not found.get("ref"):
        raise NetexError(f"{el.tag.removeprefix(NS)} {el.get('id')}: sem {tag}")
    return found.get("ref")


def _bool(value: str, what: str) -> bool:
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    raise NetexError(f"{what}: valor booleano inesperado {value!r}")


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


# --------------------------------------------------------------------------- calendário


def weekly_calendar(service_id: str, active: set[date]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Datas ativas -> (linha de calendar.txt, exceções de calendar_dates.txt).

    Período = da 1ª à última data ativa. Um dia da semana entra no padrão se estiver ativo em mais
    de metade das suas ocorrências no período; as diferenças viram exceções (1 = acrescentado,
    2 = retirado). Assim um feriado que o operador não codifica fica SEM exceção (e o projeto
    trata-o como domingo), e um dia especial codificado continua explícito."""
    if not active:
        raise NetexError(f"serviço {service_id}: nenhum dia ativo")
    start, end = min(active), max(active)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    total = Counter(d.weekday() for d in days)
    on = Counter(d.weekday() for d in days if d in active)
    pattern = {wd for wd in range(7) if on[wd] * 2 > total[wd]}
    row = {"service_id": service_id, **{WEEKDAYS[wd]: "1" if wd in pattern else "0" for wd in range(7)},
           "start_date": _ymd(start), "end_date": _ymd(end)}
    exceptions = []
    for d in days:
        in_pattern, is_active = d.weekday() in pattern, d in active
        if is_active and not in_pattern:
            exceptions.append({"service_id": service_id, "date": _ymd(d), "exception_type": "1"})
        elif in_pattern and not is_active:
            exceptions.append({"service_id": service_id, "date": _ymd(d), "exception_type": "2"})
    return row, exceptions


# --------------------------------------------------------------------------- conversor


def netex_to_gtfs(xml_bytes: bytes, night_start_before: str = "04:00:00") -> tuple[dict[str, Table], dict]:
    """Converte um PublicationDelivery NeTEx em tabelas GTFS. Devolve (feed, relatório)."""
    root = ET.fromstring(xml_bytes)
    by_tag: dict[str, list[ET.Element]] = {}
    for el in root.iter():
        if el.get("id") and el.tag.startswith(NS):
            by_tag.setdefault(el.tag.removeprefix(NS), []).append(el)

    def index(tag: str) -> dict[str, ET.Element]:
        return {el.get("id"): el for el in by_tag.get(tag, [])}

    timezone = _text(root, f".//{NS}FrameDefaults/{NS}DefaultLocale/{NS}TimeZone", "Europe/Lisbon")

    # agency
    operators = index("Operator")
    agency_rows = []
    for op in operators.values():
        agency_rows.append({
            "agency_id": _key(op, "gtfs:agency_id"),
            "agency_name": _text(op, f"{NS}Name"),
            "agency_url": _text(op, f"{NS}ContactDetails/{NS}Url"),
            "agency_timezone": timezone,
            "agency_lang": "pt",
            "agency_phone": _text(op, f"{NS}ContactDetails/{NS}Phone"),
        })
    agency_of_op = {oid: _key(op, "gtfs:agency_id") for oid, op in operators.items()}

    # routes
    lines = index("Line")
    route_rows, route_of_line = [], {}
    for lid, line in lines.items():
        mode = _text(line, f"{NS}TransportMode")
        if mode not in ROUTE_TYPES:
            raise NetexError(f"Line {lid}: TransportMode {mode!r} sem route_type conhecido")
        route_id = _key(line, "gtfs:route_id")
        route_of_line[lid] = route_id
        route_rows.append({
            "route_id": route_id,
            "agency_id": agency_of_op[_ref(line, "OperatorRef")],
            "route_short_name": _text(line, f"{NS}ShortName"),
            "route_long_name": _text(line, f"{NS}Name"),
            "route_type": ROUTE_TYPES[mode],
            "route_color": _text(line, f"{NS}Presentation/{NS}Colour"),
            "route_text_color": _text(line, f"{NS}Presentation/{NS}TextColour"),
        })

    routes = {}
    for rid, route in index("Route").items():
        direction = _text(route, f"{NS}DirectionType")
        if direction not in DIRECTIONS:
            raise NetexError(f"Route {rid}: DirectionType {direction!r} desconhecido")
        line_ref = _ref(route, "LineRef")
        if line_ref not in route_of_line:
            raise NetexError(f"Route {rid}: LineRef {line_ref} por resolver")
        routes[rid] = (route_of_line[line_ref], DIRECTIONS[direction])

    # stops
    stop_rows, stop_of_ssp = [], {}
    for sid, ssp in index("ScheduledStopPoint").items():
        lat = _text(ssp, f"{NS}Location/{NS}Latitude")
        lon = _text(ssp, f"{NS}Location/{NS}Longitude")
        if not lat or not lon:
            raise NetexError(f"ScheduledStopPoint {sid}: sem coordenadas")
        stop_id = _key(ssp, "gtfs:stop_id")
        stop_of_ssp[sid] = stop_id
        stop_rows.append({"stop_id": stop_id, "stop_code": _text(ssp, f"{NS}PublicCode"),
                          "stop_name": _text(ssp, f"{NS}Name"), "stop_lat": lat, "stop_lon": lon})

    # padrões: StopPointInJourneyPattern -> (ordem, paragem, embarque, desembarque)
    points, pattern_route = {}, {}
    for pid, sjp in index("ServiceJourneyPattern").items():
        route_ref = _ref(sjp, "RouteRef")
        if route_ref not in routes:
            raise NetexError(f"ServiceJourneyPattern {pid}: RouteRef {route_ref} por resolver")
        pattern_route[pid] = routes[route_ref]
        for spjp in sjp.iter(f"{NS}StopPointInJourneyPattern"):
            ssp_ref = _ref(spjp, "ScheduledStopPointRef")
            if ssp_ref not in stop_of_ssp:
                raise NetexError(f"StopPointInJourneyPattern {spjp.get('id')}: paragem {ssp_ref} por resolver")
            points[spjp.get("id")] = (
                int(spjp.get("order")),
                stop_of_ssp[ssp_ref],
                _bool(_text(spjp, f"{NS}ForBoarding", "true"), f"{spjp.get('id')} ForBoarding"),
                _bool(_text(spjp, f"{NS}ForAlighting", "true"), f"{spjp.get('id')} ForAlighting"),
            )

    # calendário: DayType -> período (DayTypeAssignment) -> ValidDayBits
    service_of_daytype = {did: _key(dt, "gtfs:service_id") for did, dt in index("DayType").items()}
    periods = index("UicOperatingPeriod")
    active_by_service: dict[str, set[date]] = {}
    assigned: Counter = Counter()
    for dta in by_tag.get("DayTypeAssignment", []):
        if not _bool(_text(dta, f"{NS}isAvailable", "true"), f"{dta.get('id')} isAvailable"):
            raise NetexError(f"DayTypeAssignment {dta.get('id')}: isAvailable=false não suportado")
        dt_ref, op_ref = _ref(dta, "DayTypeRef"), _ref(dta, "OperatingPeriodRef")
        if dt_ref not in service_of_daytype or op_ref not in periods:
            raise NetexError(f"DayTypeAssignment {dta.get('id')}: referência por resolver")
        period = periods[op_ref]
        start, end = _day(_text(period, f"{NS}FromDate")), _day(_text(period, f"{NS}ToDate"))
        bits = _text(period, f"{NS}ValidDayBits")
        if len(bits) != (end - start).days + 1 or set(bits) - {"0", "1"}:
            raise NetexError(f"UicOperatingPeriod {op_ref}: ValidDayBits com {len(bits)} dias para {start}..{end}")
        days = {start + timedelta(days=i) for i, b in enumerate(bits) if b == "1"}
        active_by_service.setdefault(service_of_daytype[dt_ref], set()).update(days)
        assigned[dt_ref] += 1
    unassigned = sorted(set(service_of_daytype) - set(assigned))
    if unassigned:
        raise NetexError(f"DayType sem período: {unassigned}")
    calendar_rows, calendar_dates_rows, calendar_report = [], [], {}
    for service_id in sorted(active_by_service):
        row, exceptions = weekly_calendar(service_id, active_by_service[service_id])
        calendar_rows.append(row)
        calendar_dates_rows.extend(exceptions)
        calendar_report[service_id] = {
            "dias": "".join(WEEKDAYS[i][:3] if row[WEEKDAYS[i]] == "1" else "-" for i in range(7)),
            "de": row["start_date"], "ate": row["end_date"], "datas_ativas": len(active_by_service[service_id]),
            "excecoes_acrescentadas": sum(e["exception_type"] == "1" for e in exceptions),
            "excecoes_retiradas": sum(e["exception_type"] == "2" for e in exceptions),
        }

    # trips + stop_times
    night_cutoff = hhmmss_to_seconds(night_start_before)
    trip_rows, stop_time_rows = [], []
    wrapped_trips = night_trips = offset_trips = 0
    pickup_none = dropoff_none = 0
    for jid, sj in index("ServiceJourney").items():
        day_refs = [r.get("ref") for r in sj.iter(f"{NS}DayTypeRef")]
        if len(day_refs) != 1 or day_refs[0] not in service_of_daytype:
            raise NetexError(f"ServiceJourney {jid}: {len(day_refs)} DayTypeRef (esperado 1, resolúvel)")
        pattern_ref = _ref(sj, "ServiceJourneyPatternRef")
        if pattern_ref not in pattern_route:
            raise NetexError(f"ServiceJourney {jid}: padrão {pattern_ref} por resolver")
        route_id, direction_id = pattern_route[pattern_ref]
        trip_id = _key(sj, "gtfs:trip_id")
        trip_rows.append({"route_id": route_id, "service_id": service_of_daytype[day_refs[0]], "trip_id": trip_id,
                          "trip_short_name": _text(sj, f"{NS}Name"), "direction_id": direction_id})

        passings = []
        has_offset = False
        for tpt in sj.iter(f"{NS}TimetabledPassingTime"):
            point_ref = _ref(tpt, "StopPointInJourneyPatternRef")
            if point_ref not in points:
                raise NetexError(f"ServiceJourney {jid}: ponto {point_ref} por resolver")
            arr = _text(tpt, f"{NS}ArrivalTime") or _text(tpt, f"{NS}DepartureTime")
            dep = _text(tpt, f"{NS}DepartureTime") or arr
            arr_off = int(_text(tpt, f"{NS}ArrivalDayOffset", "0") or 0)
            dep_off = int(_text(tpt, f"{NS}DepartureDayOffset", "0") or 0)
            has_offset |= bool(arr_off or dep_off)
            passings.append((points[point_ref], hhmmss_to_seconds(arr) + arr_off * 86400, hhmmss_to_seconds(dep) + dep_off * 86400))
        passings.sort(key=lambda p: p[0][0])
        if not passings:
            raise NetexError(f"ServiceJourney {jid}: sem horários")
        offset_trips += has_offset

        if not has_offset:
            shift, last, wrapped = 0, -1, False
            if passings[0][2] < night_cutoff:
                shift = 86400
                night_trips += 1
            fixed = []
            for point, arr, dep in passings:
                arr += shift
                if arr < last:
                    shift += 86400
                    arr += 86400
                    wrapped = True
                dep += shift
                if dep < arr:
                    shift += 86400
                    dep += 86400
                    wrapped = True
                last = dep
                fixed.append((point, arr, dep))
            passings = fixed
            wrapped_trips += wrapped

        for (order, stop_id, boarding, alighting), arr, dep in passings:
            pickup_none += not boarding
            dropoff_none += not alighting
            stop_time_rows.append({
                "trip_id": trip_id, "arrival_time": seconds_to_hhmmss(arr), "departure_time": seconds_to_hhmmss(dep),
                "stop_id": stop_id, "stop_sequence": str(order),
                "pickup_type": "0" if boarding else "1", "drop_off_type": "0" if alighting else "1",
            })

    all_days = sorted(set().union(*active_by_service.values()))
    feed = {
        "agency.txt": (list(agency_rows[0]), agency_rows),
        "routes.txt": (list(route_rows[0]), route_rows),
        "stops.txt": (list(stop_rows[0]), stop_rows),
        "trips.txt": (list(trip_rows[0]), trip_rows),
        "stop_times.txt": (list(stop_time_rows[0]), stop_time_rows),
        "calendar.txt": (list(calendar_rows[0]), calendar_rows),
        "calendar_dates.txt": (["service_id", "date", "exception_type"], calendar_dates_rows),
        "feed_info.txt": (
            ["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date", "feed_end_date", "feed_version"],
            [{"feed_publisher_name": "AGIT (NeTEx convertido para GTFS por scripts/build_feeds.py)",
              "feed_publisher_url": "https://agit.pt/", "feed_lang": "pt",
              "feed_start_date": _ymd(all_days[0]), "feed_end_date": _ymd(all_days[-1]),
              "feed_version": _text(root, f"{NS}PublicationTimestamp")[:10]}],
        ),
    }
    report = {
        "contagens": {"agencies": len(agency_rows), "routes": len(route_rows), "services": len(calendar_rows),
                      "stopTimes": len(stop_time_rows), "stops": len(stop_rows), "trips": len(trip_rows)},
        "calendario": calendar_report,
        "meia_noite": {
            "viagens_com_day_offset": offset_trips,
            "viagens_que_passam_a_meia_noite": wrapped_trips,
            "viagens_noturnas_passadas_a_24h": night_trips,
            "regra_noturna": f"viagem sem DayOffset que começa antes das {night_start_before} = cauda da noite anterior (+24 h)",
        },
        "embarque": {"passagens_sem_embarque": pickup_none, "passagens_sem_desembarque": dropoff_none},
    }
    return feed, report
