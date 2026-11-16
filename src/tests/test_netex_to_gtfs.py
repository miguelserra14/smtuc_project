"""Conversor NeTEx -> GTFS (D2.1, gtfs_processing/netex_to_gtfs.py) e o build do Metro fase 2.

Unitários sobre um NeTEx mínimo escrito aqui (mapeamento, calendário semanal + exceções, horas
depois da meia-noite, recusa do que não percebe) e sobre o build (contagens contra o
validation.json, troca de nomes das linhas, fontes não versionadas). Integração (feeds reais,
guardada por impressão digital): os números de controlo da D2.2 nos feeds construídos."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from gtfs_processing.netex_to_gtfs import NetexError, netex_to_gtfs, weekly_calendar
from tests.reference_data import require_reference_data

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_feeds_netex", ROOT / "scripts" / "build_feeds.py")
bf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bf
_spec.loader.exec_module(bf)


# --------------------------------------------------------------------------- NeTEx mínimo


def _kv(key: str, value: str) -> str:
    return f"<keyList><KeyValue><Key>{key}</Key><Value>{value}</Value></KeyValue></keyList>"


def _bits(start: date, end: date, active) -> str:
    return "".join("1" if active(start + timedelta(days=i)) else "0" for i in range((end - start).days + 1))


def netex(
    journeys: list[tuple[str, str, list[tuple[str, str] | tuple[str, str, int]]]] | None = None,
    weekday_bits: str | None = None,
    extra_daytype_ref: bool = False,
    bad_stop_ref: bool = False,
) -> bytes:
    """2 linhas (U1 'Azul' e S1 'Azul', como no Metro), 3 paragens, 1 padrão A->B->C (A só
    embarque, C só desembarque), DayType "11" = dias úteis de setembro de 2026 e "1" = domingos.
    `journeys`: (trip_id, daytype, [(hora_chegada, hora_partida[, offset]) por paragem])."""
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    weekday_bits = weekday_bits or _bits(start, end, lambda d: d.weekday() < 5)
    sunday_bits = _bits(start, end, lambda d: d.weekday() == 6)
    journeys = journeys or [("T1", "11", [("08:00:00", "08:00:00"), ("08:05:00", "08:06:00"), ("08:10:00", "08:10:00")])]
    stops = [("A", "Portagem", "40.2075", "-8.4306"), ("B", "São José", "40.2031", "-8.4134"), ("C", "Portela", "40.1930", "-8.3955")]
    ssp = "".join(
        f'<ScheduledStopPoint id="SSP:{s}">{_kv("gtfs:stop_id", s)}<Name>{n}</Name>'
        f"<Location><Longitude>{lon}</Longitude><Latitude>{lat}</Latitude></Location><PublicCode>c_{s}</PublicCode></ScheduledStopPoint>"
        for s, n, lat, lon in stops
    )
    flags = [("false", "true"), ("true", "true"), ("true", "false")]  # (ForAlighting, ForBoarding)
    spjp = "".join(
        f'<StopPointInJourneyPattern id="SPJP:{i}" order="{i + 1}">'
        f'<ScheduledStopPointRef ref="SSP:{"X" if bad_stop_ref and i == 1 else s[0]}"/>'
        f"<ForAlighting>{a}</ForAlighting><ForBoarding>{b}</ForBoarding></StopPointInJourneyPattern>"
        for i, (s, (a, b)) in enumerate(zip(stops, flags))
    )
    sjs = ""
    for trip_id, daytype, times in journeys:
        tpts = ""
        for i, t in enumerate(times):
            off = f"<ArrivalDayOffset>{t[2]}</ArrivalDayOffset><DepartureDayOffset>{t[2]}</DepartureDayOffset>" if len(t) > 2 else ""
            tpts += (f'<TimetabledPassingTime id="TPT:{trip_id}:{i}"><StopPointInJourneyPatternRef ref="SPJP:{i}"/>'
                     f"<ArrivalTime>{t[0]}</ArrivalTime><DepartureTime>{t[1]}</DepartureTime>{off}</TimetabledPassingTime>")
        extra = '<DayTypeRef ref="DT:1"/>' if extra_daytype_ref else ""
        sjs += (f'<ServiceJourney id="SJ:{trip_id}">{_kv("gtfs:trip_id", trip_id)}<Name>{trip_id}N</Name>'
                f'<dayTypes><DayTypeRef ref="DT:{daytype}"/>{extra}</dayTypes>'
                f'<ServiceJourneyPatternRef ref="SJP:1"/><passingTimes>{tpts}</passingTimes></ServiceJourney>')
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PublicationDelivery xmlns="http://www.netex.org.uk/netex" version="1.1">
  <PublicationTimestamp>2026-11-11T15:14:47Z</PublicationTimestamp>
  <dataObjects><CompositeFrame id="CF:1">
    <FrameDefaults><DefaultLocale><TimeZone>Europe/Lisbon</TimeZone></DefaultLocale></FrameDefaults>
    <frames>
      <ResourceFrame id="RF:1"><organisations>
        <Operator id="OP:1">{_kv("gtfs:agency_id", "1")}<Name>Metro Mondego</Name>
          <ContactDetails><Phone>+351</Phone><Url>https://www.metromondego.pt</Url></ContactDetails></Operator>
      </organisations></ResourceFrame>
      <ServiceFrame id="SF:1">
        <routes><Route id="R:1">{_kv("gtfs:route_id", "3622")}<LineRef ref="L:U1"/><DirectionType>inbound</DirectionType></Route></routes>
        <lines>
          <Line id="L:U1">{_kv("gtfs:route_id", "3622")}<Name>U1</Name><ShortName>Azul</ShortName><TransportMode>bus</TransportMode>
            <OperatorRef ref="OP:1"/><Presentation><Colour>2B6CC4</Colour><TextColour>FFFFFF</TextColour></Presentation></Line>
          <Line id="L:S1">{_kv("gtfs:route_id", "3624")}<Name>S1</Name><ShortName>Azul</ShortName><TransportMode>bus</TransportMode>
            <OperatorRef ref="OP:1"/></Line>
        </lines>
        <scheduledStopPoints>{ssp}</scheduledStopPoints>
        <journeyPatterns><ServiceJourneyPattern id="SJP:1"><RouteRef ref="R:1"/><pointsInSequence>{spjp}</pointsInSequence></ServiceJourneyPattern></journeyPatterns>
      </ServiceFrame>
      <ServiceCalendarFrame id="SCF:1"><ServiceCalendar id="SC:1">
        <dayTypes>
          <DayType id="DT:11">{_kv("gtfs:service_id", "11")}<Name>11</Name></DayType>
          <DayType id="DT:1">{_kv("gtfs:service_id", "1")}<Name>1</Name></DayType>
        </dayTypes>
        <operatingPeriods>
          <UicOperatingPeriod id="OP:11"><FromDate>{start}T00:00:00Z</FromDate><ToDate>{end}T23:59:59Z</ToDate><ValidDayBits>{weekday_bits}</ValidDayBits></UicOperatingPeriod>
          <UicOperatingPeriod id="OP:1"><FromDate>{start}T00:00:00Z</FromDate><ToDate>{end}T23:59:59Z</ToDate><ValidDayBits>{sunday_bits}</ValidDayBits></UicOperatingPeriod>
        </operatingPeriods>
        <dayTypeAssignments>
          <DayTypeAssignment id="DTA:11" order="1"><OperatingPeriodRef ref="OP:11"/><DayTypeRef ref="DT:11"/><isAvailable>true</isAvailable></DayTypeAssignment>
          <DayTypeAssignment id="DTA:1" order="2"><OperatingPeriodRef ref="OP:1"/><DayTypeRef ref="DT:1"/><isAvailable>true</isAvailable></DayTypeAssignment>
        </dayTypeAssignments>
      </ServiceCalendar></ServiceCalendarFrame>
      <TimetableFrame id="TF:1"><vehicleJourneys>{sjs}</vehicleJourneys></TimetableFrame>
    </frames>
  </CompositeFrame></dataObjects>
</PublicationDelivery>"""
    return xml.encode("utf-8")


def _times(feed, trip_id: str) -> list[tuple[str, str]]:
    return [(r["arrival_time"], r["departure_time"]) for r in feed["stop_times.txt"][1] if r["trip_id"] == trip_id]


# --------------------------------------------------------------------------- conversor


def test_maps_every_gtfs_table() -> None:
    feed, report = netex_to_gtfs(netex())
    assert feed["agency.txt"][1] == [{"agency_id": "1", "agency_name": "Metro Mondego", "agency_url": "https://www.metromondego.pt",
                                       "agency_timezone": "Europe/Lisbon", "agency_lang": "pt", "agency_phone": "+351"}]
    routes = {r["route_id"]: r for r in feed["routes.txt"][1]}
    # Mapeamento fiel (ShortName -> short): a troca para U1/S1 é um passo do build, explícito.
    assert (routes["3622"]["route_short_name"], routes["3622"]["route_long_name"]) == ("Azul", "U1")
    assert routes["3622"]["route_type"] == "3" and routes["3622"]["route_color"] == "2B6CC4"
    stops = {s["stop_id"]: s for s in feed["stops.txt"][1]}
    assert stops["B"] == {"stop_id": "B", "stop_code": "c_B", "stop_name": "São José", "stop_lat": "40.2031", "stop_lon": "-8.4134"}
    assert feed["trips.txt"][1] == [{"route_id": "3622", "service_id": "11", "trip_id": "T1", "trip_short_name": "T1N", "direction_id": "1"}]
    st = feed["stop_times.txt"][1]
    assert [(r["stop_id"], r["stop_sequence"], r["pickup_type"], r["drop_off_type"]) for r in st] == [
        ("A", "1", "0", "1"), ("B", "2", "0", "0"), ("C", "3", "1", "0")]
    assert _times(feed, "T1") == [("08:00:00", "08:00:00"), ("08:05:00", "08:06:00"), ("08:10:00", "08:10:00")]
    assert report["contagens"] == {"agencies": 1, "routes": 2, "services": 2, "stopTimes": 3, "stops": 3, "trips": 1}
    assert feed["feed_info.txt"][1][0]["feed_start_date"] == "20260901"


def test_calendar_is_a_weekly_pattern_not_one_date_per_row() -> None:
    feed, report = netex_to_gtfs(netex())
    cal = {r["service_id"]: r for r in feed["calendar.txt"][1]}
    assert [cal["11"][d] for d in ("monday", "friday", "saturday", "sunday")] == ["1", "1", "0", "0"]
    assert (cal["11"]["start_date"], cal["11"]["end_date"]) == ("20260901", "20260930")
    assert cal["1"]["sunday"] == "1" and cal["1"]["monday"] == "0"
    assert feed["calendar_dates.txt"][1] == []  # nada codificado à parte
    assert report["calendario"]["11"]["dias"] == "montuewedthufri--"


def test_uncoded_holiday_gets_no_exception_and_a_coded_one_does() -> None:
    # Feriado que o operador NÃO codifica (ativo como dia útil): fica sem exceção -> o projeto
    # trata-o como domingo (FERIADOS_COMO_DOMINGO). Um dia útil que o operador TIRA vira exceção 2.
    weekdays = {date(2026, 9, 1) + timedelta(days=i) for i in range(30)}
    weekdays = {d for d in weekdays if d.weekday() < 5}
    row, exc = weekly_calendar("11", weekdays)
    assert exc == []
    row, exc = weekly_calendar("11", weekdays - {date(2026, 9, 15)} | {date(2026, 9, 13)})
    assert row["monday"] == "1" and row["sunday"] == "0"
    assert exc == [{"service_id": "11", "date": "20260913", "exception_type": "1"},
                   {"service_id": "11", "date": "20260915", "exception_type": "2"}]
    with pytest.raises(NetexError):
        weekly_calendar("x", set())


def test_day_offsets_become_24h_times() -> None:
    times = [("23:50:00", "23:50:00"), ("00:02:00", "00:02:00", 1), ("00:10:00", "00:10:00", 1)]
    feed, report = netex_to_gtfs(netex(journeys=[("N", "11", times)]))
    assert _times(feed, "N") == [("23:50:00", "23:50:00"), ("24:02:00", "24:02:00"), ("24:10:00", "24:10:00")]
    assert report["meia_noite"]["viagens_com_day_offset"] == 1


def test_without_offsets_midnight_wrap_and_night_trips_are_fixed() -> None:
    wrap = [("23:50:00", "23:50:00"), ("00:02:00", "00:02:00"), ("00:10:00", "00:10:00")]
    night = [("00:20:00", "00:20:00"), ("00:30:00", "00:30:00"), ("00:40:00", "00:40:00")]
    morning = [("05:30:00", "05:30:00"), ("05:40:00", "05:40:00"), ("05:50:00", "05:50:00")]
    feed, report = netex_to_gtfs(netex(journeys=[("W", "11", wrap), ("N", "11", night), ("M", "11", morning)]))
    assert _times(feed, "W")[1:] == [("24:02:00", "24:02:00"), ("24:10:00", "24:10:00")]
    assert _times(feed, "N")[0] == ("24:20:00", "24:20:00")  # cauda da noite do dia de serviço
    assert _times(feed, "M")[0] == ("05:30:00", "05:30:00")
    assert report["meia_noite"]["viagens_que_passam_a_meia_noite"] == 1
    assert report["meia_noite"]["viagens_noturnas_passadas_a_24h"] == 1


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"weekday_bits": "1" * 10}, "ValidDayBits"),
        ({"extra_daytype_ref": True}, "DayTypeRef"),
        ({"bad_stop_ref": True}, "por resolver"),
    ],
)
def test_refuses_what_it_does_not_understand(kwargs: dict, message: str) -> None:
    with pytest.raises(NetexError, match=message):
        netex_to_gtfs(netex(**kwargs))


# --------------------------------------------------------------------------- build


@pytest.fixture
def netex_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw, gtfs = tmp_path / "raw", tmp_path / "gtfs"
    monkeypatch.setattr(bf, "RAW_DIR", raw)
    monkeypatch.setattr(bf, "GTFS_DIR", gtfs)
    rel = "agit/metro-mondego-netex/v1/metro-mondego-netex.zip"

    def put(counts: dict | None = None, with_validation: bool = True, versionado: bool = True) -> "bf.Build":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("netex.xml", netex())
            zf.writestr("metadata.jsonld", json.dumps({"dcterms:identifier": "urn:agit:Dataset:metro-mondego"}))
        data = buf.getvalue()
        (raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (raw / rel).write_bytes(data)
        if with_validation:
            gtfs_counts = counts or {"agencies": 1, "routes": 2, "services": 2, "stopTimes": 3, "stops": 3, "trips": 1}
            (raw / rel).with_name("validation.json").write_text(
                json.dumps({"counts": {"gtfs": gtfs_counts}, "source": {"releaseId": "R1"}}), encoding="utf-8")
        with open(raw / "MANIFEST.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["ficheiro", "estado", "sha256", "versao", "url", "verificacoes"])
            w.writeheader()
            w.writerow({"ficheiro": rel, "estado": "novo", "sha256": hashlib.sha256(data).hexdigest(),
                        "versao": "v1", "url": "https://exemplo", "verificacoes": "teste"})
        steps = (bf.swap_all_route_names({"3622": "Azul", "3624": "Azul"}, "teste"),)
        return bf.Build(target="metro/teste", raw=rel, descricao="teste", formato="netex", steps=steps, versionado=versionado)

    return put, gtfs / "metro" / "teste"


def test_netex_build_checks_counts_and_unswaps_route_names(netex_env) -> None:
    put, target = netex_env
    assert bf.run_build(put()) == "construido"
    with open(target / "routes.txt", encoding="utf-8", newline="") as fh:
        routes = {r["route_id"]: (r["route_short_name"], r["route_long_name"]) for r in csv.DictReader(fh)}
    assert routes == {"3622": ("U1", "Azul"), "3624": ("S1", "Azul")}  # sem a troca, U1 e S1 = "Azul"
    prov = json.loads((target / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov["conversao_netex"]["verificacao_semantica"]["igual_a_counts_gtfs"] is True
    assert prov["conversao_netex"]["metadata"]["identificador"] == "urn:agit:Dataset:metro-mondego"
    assert prov["ignorados_do_zip"] == ["metadata.jsonld"]
    assert bf.run_build(put(), verify_only=True) == "igual"


def test_netex_build_refuses_counts_different_from_agit(netex_env) -> None:
    put, target = netex_env
    with pytest.raises(bf.BuildError, match="counts.gtfs"):
        bf.run_build(put(counts={"agencies": 1, "routes": 2, "services": 2, "stopTimes": 4, "stops": 3, "trips": 1}))
    with pytest.raises(bf.BuildError, match="validation.json"):
        bf.run_build(put(with_validation=False))
    assert not target.exists()


def test_swap_all_route_names_refuses_an_unexpected_feed() -> None:
    feed = {"routes.txt": (["route_id", "route_short_name", "route_long_name"],
                           [{"route_id": "1", "route_short_name": "Azul", "route_long_name": "U1"},
                            {"route_id": "2", "route_short_name": "Azul", "route_long_name": "U1"}])}
    with pytest.raises(bf.BuildError, match="esperados"):
        bf.swap_all_route_names({"1": "Verde", "2": "Azul"}, "x")(feed)
    with pytest.raises(bf.BuildError, match="repetidos"):
        bf.swap_all_route_names({"1": "Azul", "2": "Azul"}, "x")(feed)


def test_unversioned_source_is_absent_or_rebuilt_from_provenance(netex_env) -> None:
    put, target = netex_env
    build = put(versionado=False)
    assert bf.run_build(build) == "construido"
    for p in target.glob("*.txt"):  # clone novo: só o PROVENANCE.json veio do git
        p.unlink()
    with pytest.raises(bf.BuildError, match="só tem PROVENANCE"):
        bf.run_build(build, verify_only=True)
    assert bf.run_build(build) == "reconstruido"
    assert bf.run_build(build, verify_only=True) == "igual"
    (bf.RAW_DIR / build.raw).unlink()  # máquina sem o bruto (não versionado)
    assert bf.run_build(build) == "ausente"


# --------------------------------------------------------------------------- feeds reais (D2.2)


def _real(dataset: str):
    from gtfs_processing.gtfs import dataset_dir, load_gtfs

    if not (dataset_dir(dataset) / "trips.txt").exists():
        pytest.skip(f"{dataset} não existe nesta máquina (scripts/fetch_feeds.py + build_feeds.py)")
    require_reference_data(dataset)
    return load_gtfs(dataset=dataset)


def _trips_on(gtfs, day: date) -> tuple[list[str], int]:
    from gtfs_processing.gtfs_probe import _active_service_ids

    services = _active_service_ids(gtfs, day)
    return sorted(services), int(gtfs.trips["service_id"].astype(str).isin(services).sum())


@pytest.mark.integration
def test_official_metro_phase2_control_numbers() -> None:
    g = _real("metro_fase2_oficial")
    assert sorted(g.routes["route_short_name"].astype(str)) == ["S1", "S2", "U1", "U2", "U3"]
    assert _trips_on(g, date(2026, 11, 9)) == (["11"], 452)  # dia de referência do cenário fase2_oficial
    # Feriados que o Metro não codifica -> serviço de domingo pela regra do projeto.
    for holiday in (date(2026, 10, 5), date(2026, 12, 8), date(2026, 12, 25)):
        assert _trips_on(g, holiday) == (["1"], 225)
    st = g.stop_times.merge(g.trips[["trip_id", "service_id"]], on="trip_id")
    st = st[st["service_id"].astype(str) == "11"]
    names = g.stops.set_index(g.stops["stop_id"].astype(str))["stop_name"]
    per_stop = st["stop_id"].astype(str).map(names).value_counts()
    assert (per_stop["Portagem"], per_stop["Portela"], per_stop["Coimbra B"]) == (303, 120, 304)
    assert int((st["departure_time"].astype(str) >= "24").sum()) == 150  # DayOffset -> 24:xx


@pytest.mark.integration
def test_smtuc_ep225_control_numbers() -> None:
    g = _real("smtuc_atual")
    assert _trips_on(g, date(2026, 11, 9)) == (["Dias Úteis:Ep225_Prog1"], 2407)
    assert _trips_on(g, date(2026, 10, 5)) == (["Domingos e Feriados:Ep225_Prog1"], 790)  # feriado codificado
    assert _trips_on(g, date(2026, 9, 23)) == (["Especial-23092026:Ep225_Prog1"], 2423)  # substitui o dia útil
    routes = g.routes.assign(route_short_name=g.routes["route_short_name"].astype(str))
    line54 = routes[routes["route_short_name"] == "54"]["route_id"].astype(str)
    trips54 = g.trips[g.trips["route_id"].astype(str).isin(line54)]
    services = _trips_on(g, date(2026, 11, 9))[0]
    assert int(trips54["service_id"].astype(str).isin(services).sum()) == 42  # = Ep212, ao minuto
