"""Horário assumido da Linha do Hospital (fase 3, PLANEADO): velocidade de referência e tempos (N3.1).

Não há horário oficial da Linha do Hospital; o KMZ oficial só dá as estações e a via. Decisão do
utilizador (2026-11-26): os tempos entre as estações novas = distância no eixo do KMZ ÷ a velocidade
média do metro no troço urbano que acaba na República, medida no horário oficial da fase 2.

Troço de referência: Loja do Cidadão -> Câmara -> Mercado -> República. A decisão falava em
"Aeminium - República", mas nenhum serviço faz esse percurso: Aeminium só está no U1 (Coimbra B -
Vale das Flores), e os três serviços que chegam à República (U2, U3, S2) passam todos por Loja do
Cidadão, Câmara e Mercado. É o troço urbano comum mais próximo do decidido, todo no eixo da Linha do
Hospital ("Eixo LH") - por isso a distância é medida com a mesma régua que o troço novo.

Velocidade = distância no eixo do troço ÷ tempo médio de todas as viagens que o fazem (partida na
1.ª estação -> chegada à última, incluindo as paragens intermédias). Calculada por sentido: as
plataformas e os tempos não são simétricos.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from gtfs_processing import kmz
from gtfs_processing.timeutil import seconds_to_hhmmss, series_hhmmss_to_seconds

# Troço de referência por sentido: (nomes no GTFS da fase 2, nomes no KMZ). "subir" = da Baixa
# para a República (plataformas asc), "descer" = da República para a Baixa (desc).
SPEED_SEGMENTS: dict[str, tuple[tuple[str, str], tuple[str, ...]]] = {
    "subir": (("Loja do Cidadão", "República (asc)"), ("Loja de Cidadão", "Câmara", "Mercado", "República (asc)")),
    "descer": (("República (desc)", "Loja do Cidadão"), ("República (desc)", "Mercado", "Câmara", "Loja de Cidadão")),
}


class HospitalLineError(ValueError):
    pass


@dataclass(frozen=True)
class SegmentSpeed:
    sentido: str
    origem: str
    destino: str
    eixo_m: float
    viagens: int
    minutos_medios: float

    @property
    def m_por_min(self) -> float:
        return self.eixo_m / self.minutos_medios

    @property
    def km_h(self) -> float:
        return self.m_por_min * 60 / 1000


def segment_minutes(stops: pd.DataFrame, stop_times: pd.DataFrame, origin: str, destination: str) -> pd.Series:
    """Minutos de cada viagem entre a partida em `origin` e a chegada a `destination` (nomes de
    paragem; `destination` depois de `origin` na mesma viagem). Índice = trip_id."""
    names = stops.set_index(stops["stop_id"].astype(str))["stop_name"]
    st = stop_times.assign(stop_id=stop_times["stop_id"].astype(str))
    st = st.assign(_name=st["stop_id"].map(names), _seq=pd.to_numeric(st["stop_sequence"]))
    if "departure_seconds" not in st.columns:
        st = st.assign(departure_seconds=series_hhmmss_to_seconds(st["departure_time"]),
                       arrival_seconds=series_hhmmss_to_seconds(st["arrival_time"]))
    a = st.loc[st["_name"] == origin, ["trip_id", "_seq", "departure_seconds"]]
    b = st.loc[st["_name"] == destination, ["trip_id", "_seq", "arrival_seconds"]]
    m = a.merge(b, on="trip_id", suffixes=("_a", "_b"))
    m = m[m["_seq_a"] < m["_seq_b"]].sort_values(["trip_id", "_seq_a"]).drop_duplicates("trip_id")
    return ((m["arrival_seconds"] - m["departure_seconds"]) / 60.0).set_axis(m["trip_id"].to_numpy())


def reference_speeds(kmz_path: Path | str, stops: pd.DataFrame, stop_times: pd.DataFrame) -> dict[str, SegmentSpeed]:
    """Velocidade de referência por sentido (SPEED_SEGMENTS): eixo do KMZ ÷ tempo médio no feed."""
    placemarks = kmz.read_placemarks(kmz_path)
    graph = kmz.axis_graph(placemarks)
    points = kmz.stations(placemarks, kmz.HOSPITAL_STATIONS_FOLDER)
    out: dict[str, SegmentSpeed] = {}
    for sense, ((origin, destination), axis_names) in SPEED_SEGMENTS.items():
        axis_m = sum(leg.eixo_m for leg in kmz.chain_distances(graph, points, axis_names))
        minutes = segment_minutes(stops, stop_times, origin, destination)
        if minutes.empty:
            raise HospitalLineError(f"nenhuma viagem {origin} -> {destination} no feed")
        if (minutes <= 0).any():
            raise HospitalLineError(f"{origin} -> {destination}: viagens com tempo <= 0")
        out[sense] = SegmentSpeed(sense, origin, destination, axis_m, int(len(minutes)), float(minutes.mean()))
    return out


@dataclass(frozen=True)
class TimedLeg:
    origem: str
    destino: str
    eixo_m: float
    minutos: float


def timed_legs(legs: list[kmz.Leg], speed: SegmentSpeed) -> list[TimedLeg]:
    """Tempo de cada troço novo = distância no eixo ÷ velocidade de referência do sentido."""
    return [TimedLeg(leg.origem, leg.destino, leg.eixo_m, leg.eixo_m / speed.m_por_min) for leg in legs]


def hospital_timetable_legs(kmz_path: Path | str, stops: pd.DataFrame, stop_times: pd.DataFrame) -> dict[str, list[TimedLeg]]:
    """Troços novos com tempo, por sentido ("subir": República (asc) -> Pediátrico; "descer":
    Pediátrico -> República (desc))."""
    speeds = reference_speeds(kmz_path, stops, stop_times)
    legs = kmz.hospital_line_legs(kmz_path)
    return {sense: timed_legs(legs[sense], speeds[sense]) for sense in ("subir", "descer")}


SERVICE_COLUMNS = ("linha", "sentido", "passagens", "primeira", "ultima", "intervalo_mediano_min")
ALL_LINES = "todas"


def station_service(gtfs, day, station: str, terminus: str, window_h: tuple[float, float]) -> pd.DataFrame:
    """Serviço de um dia numa estação do metro (N3.5: a página do horário assumido), por linha e
    sentido: "subir" = a viagem acaba em `terminus`, "descer" = as outras. `station`/`terminus` sem
    sufixo de plataforma. Passagens no dia, primeira e última (HH:MM) e o intervalo mediano entre
    passagens consecutivas que partem dentro de `window_h` (horas, fim exclusive; NaN com menos de
    duas). Mais uma linha ALL_LINES por sentido com todas as linhas juntas. Só viagens com serviço
    em `day` (active_service_ids)."""
    from gtfs_processing.gtfs_probe import active_service_ids
    from overlap.redundancy import station_name

    active = active_service_ids(gtfs, day)
    trips = gtfs.trips[gtfs.trips["service_id"].isin(active)][["trip_id", "route_id"]].astype(str)
    lines = gtfs.routes.assign(route_id=gtfs.routes["route_id"].astype(str)).set_index("route_id")["route_short_name"]
    trips = trips.assign(linha=trips["route_id"].map(lines).astype(str))
    names = gtfs.stops.assign(stop_id=gtfs.stops["stop_id"].astype(str)).set_index("stop_id")["stop_name"].map(station_name)
    st = gtfs.stop_times[gtfs.stop_times["trip_id"].astype(str).isin(trips["trip_id"])]
    st = st.assign(trip_id=st["trip_id"].astype(str), _name=st["stop_id"].astype(str).map(names),
                   _seq=pd.to_numeric(st["stop_sequence"]))
    if "departure_seconds" not in st.columns:
        st = st.assign(departure_seconds=series_hhmmss_to_seconds(st["departure_time"]))
    last = st.sort_values(["trip_id", "_seq"]).drop_duplicates("trip_id", keep="last").set_index("trip_id")["_name"]
    at = st[st["_name"] == station].sort_values(["trip_id", "_seq"]).drop_duplicates("trip_id")
    at = at.merge(trips[["trip_id", "linha"]], on="trip_id")
    at = at.assign(sentido=at["trip_id"].map(last).eq(terminus).map({True: "subir", False: "descer"}))
    start, end = window_h[0] * 3600, window_h[1] * 3600

    def row(linha: str, sentido: str, times: pd.Series) -> dict:
        t = times.sort_values().to_numpy()
        inside = t[(t >= start) & (t < end)]
        gaps = pd.Series(inside[1:] - inside[:-1]) / 60.0
        return {"linha": linha, "sentido": sentido, "passagens": int(len(t)),
                "primeira": seconds_to_hhmmss(int(t[0]) % 86400)[:5] if len(t) else "",
                "ultima": seconds_to_hhmmss(int(t[-1]) % 86400)[:5] if len(t) else "",  # 24:10 -> 00:10
                "intervalo_mediano_min": float(gaps.median()) if len(gaps) else float("nan")}

    rows = []
    for sentido in ("subir", "descer"):
        part = at[at["sentido"] == sentido]
        for linha, g in sorted(part.groupby("linha"), key=lambda kv: kv[0]):
            rows.append(row(linha, sentido, g["departure_seconds"]))
        if not part.empty:
            rows.append(row(ALL_LINES, sentido, part["departure_seconds"]))
    return pd.DataFrame(rows, columns=list(SERVICE_COLUMNS))


def _main() -> None:
    import argparse
    import sys

    from gtfs_processing.gtfs import load_gtfs_cached

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Velocidade de referência e tempos da Linha do Hospital (planeado)")
    parser.add_argument("kmz", type=Path)
    parser.add_argument("--dataset", default="metro_fase2_oficial")
    args = parser.parse_args()
    gtfs = load_gtfs_cached(args.dataset)
    for sense, sp in reference_speeds(args.kmz, gtfs.stops, gtfs.stop_times).items():
        print(f"{sense}: {sp.origem} -> {sp.destino}: {sp.eixo_m:.0f} m no eixo, {sp.viagens} viagens, "
              f"{sp.minutos_medios:.2f} min -> {sp.km_h:.1f} km/h")
    for sense, legs in hospital_timetable_legs(args.kmz, gtfs.stops, gtfs.stop_times).items():
        print(f"{sense}: {sum(l.minutos for l in legs):.1f} min no total")
        for leg in legs:
            print(f"  {leg.origem} -> {leg.destino}: {leg.eixo_m:.0f} m, {leg.minutos:.2f} min")


if __name__ == "__main__":
    _main()
