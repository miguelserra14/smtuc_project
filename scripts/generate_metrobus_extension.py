"""Gera a extensão do Metrobus (fase 2: Aeminium -> Coimbra B / República) em data/metrobus/.

Contexto: o utilizador acrescentou as novas paragens da fase 2 a stops.txt (Aeminium, Loja do
Cidadão, Câmara, Mercado, Praça, Arnado, Açude, Casa do Sal, Coimbra B), mas nenhuma viagem as
servia ainda - o Metrobus, nos dados, continuava todo a terminar/começar em Portagem. Este script:

1. Corrige 2 erros nos dados novos: o stop_id "MRC" da nova paragem "Mercado" colidia com o MRC
   já existente ("Miranda do Corvo", linha da Lousã); e a longitude de "Mercado" estava ~2km a
   mais para oeste do que devia (a latitude já batia certo com o "Mercado Municipal" real do
   SMTUC - só a longitude estava trocada).
2. Acrescenta 2 rotas novas (routes.txt) - uma por ramal a partir de "Aeminium" (AEM), que passa
   a ser o nó de interseção: ramal verde até Coimbra B (via Arnado/Açude/Casa do Sal) e ramal
   vermelho até "Praça" (via Loja do Cidadão/Câmara/Mercado). Rotas SEPARADAS da já existente
   (LOUSA, Portagem<->Serpins) de propósito - visualizations/lines_map.py desenha a forma de cada
   rota escolhendo a viagem com mais paragens dentro de cada (route_id, direction_id); juntar a
   extensão à rota LOUSA faria a viagem do tronco (mais longa) "ganhar" sempre e a extensão nunca
   apareceria no mapa.
3. Gera viagens (trips.txt) e horários (stop_times.txt) SÓ para a extensão nova (Portagem até
   cada um dos dois ramais) - o tronco Portagem<->Serpins existente fica exatamente como estava,
   por decisão explícita do utilizador. Cada ramal recebe a MESMA frequência que o resto da
   cidade, independente do outro ramal (não há alternância entre ramais - ambos correm em
   simultâneo à mesma cadência, o que dobra o nº de veículos face ao tronco mas é o que garante
   "mesma frequência nestas paragens que no resto da cidade").

Frequências por período (min):
 - Dias úteis (WD): banda derivada do padrão já existente no troço Portagem-Vale das Flores
   (arredondado a partir dos horários reais em Portagem - ver histórico da conversa; é uma
   ESTIMATIVA, ajustar WD_BANDS abaixo se não bater certo com o que se pretende).
 - Sábados (SAT) e Domingos/Feriados (SUN): fornecidas pelo utilizador (frequência oficial da
   fase 2, medida em "Mercado").

Corre uma vez, a partir da raiz do repo:
    python scripts/generate_metrobus_extension.py
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "metrobus"


def fix_stops() -> None:
    """Renomeia MRC->MER (Mercado) e corrige a sua longitude."""
    path = DATA_DIR / "stops.txt"
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    fixed = False
    for row in rows:
        if row["stop_id"] == "MRC" and row["stop_name"] == "Mercado":
            row["stop_id"] = "MER"
            row["stop_lon"] = "-8.425055"
            fixed = True
    if not fixed:
        raise RuntimeError('Paragem "Mercado" (MRC) não encontrada - já foi corrigida antes?')

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["stop_id", "stop_name", "stop_lat", "stop_lon"])
        writer.writeheader()
        writer.writerows(rows)


# Topologia dos 2 ramais a partir de Aeminium (AEM) - cada entrada é (stop_id, minutos desde a
# paragem anterior na lista, começando em Portagem). Tempos de viagem estimados por distância
# haversine ao ritmo urbano já usado no resto do troço central (~1-2 min/paragem).
BRANCHES = {
    "CBE": {
        "route_id": "METRO_CBE",
        "route_short_name": "Verde",
        "route_long_name": "Aeminium ↔ Coimbra B",
        "route_color": "2E8B57",
        "headsign": "Coimbra B",
        "stops": [("AEM", 1), ("ARN", 2), ("ACU", 2), ("CDS", 2), ("CBE", 2)],
    },
    "REP": {
        "route_id": "METRO_REP",
        "route_short_name": "Vermelho",
        "route_long_name": "Aeminium ↔ Praça",
        "route_color": "D32F2F",
        "headsign": "Praça",
        "stops": [("AEM", 1), ("LJC", 1), ("CMC", 1), ("MER", 2), ("REP", 2)],
    },
}

# Bandas de frequência por serviço: (início_min, fim_min, intervalo_min), minutos desde as 00:00.
DAY_START = 5 * 60 + 30
DAY_END = 24 * 60 + 30
WD_BANDS = [
    (5 * 60 + 30, 7 * 60 + 30, 30),
    (7 * 60 + 30, 9 * 60 + 30, 10),
    (9 * 60 + 30, 15 * 60, 30),
    (15 * 60, 19 * 60, 15),
    (19 * 60, DAY_END, 60),
]
SAT_BANDS = [
    (5 * 60 + 30, 7 * 60 + 30, 15),
    (7 * 60 + 30, 14 * 60 + 30, 7.5),
    (14 * 60 + 30, DAY_END, 15),
]
SUN_BANDS = [
    (5 * 60 + 30, 7 * 60 + 30, 30),
    (7 * 60 + 30, DAY_END, 15),
]
SERVICE_BANDS = {"WD": WD_BANDS, "SAT": SAT_BANDS, "SUN": SUN_BANDS}


def band_departures(bands: list[tuple[float, float, float]]) -> list[float]:
    """Devolve os minutos (desde as 00:00) em que uma viagem parte, cobrindo as bandas dadas."""
    times: list[float] = []
    for start, end, headway in bands:
        t = start
        while t < end:
            times.append(t)
            t += headway
    return sorted(set(times))


def fmt_time(total_min: float) -> str:
    """Formata minutos (desde as 00:00) como HH:MM:SS, sem dar wrap às 24h (tal como o resto do
    feed - já há horários tipo "24:15:00" para viagens que passam a meia-noite)."""
    total_min = int(round(total_min))
    h, m = divmod(total_min, 60)
    return f"{h:02d}:{m:02d}:00"


def generate_extension() -> tuple[list[dict], list[dict]]:
    trip_rows: list[dict] = []
    stop_time_rows: list[dict] = []

    def add_stop_time(trip_id: str, minutes: float, stop_id: str, seq: int) -> None:
        t = fmt_time(minutes)
        stop_time_rows.append(
            {"trip_id": trip_id, "arrival_time": t, "departure_time": t, "stop_id": stop_id, "stop_sequence": seq}
        )

    for service_id, bands in SERVICE_BANDS.items():
        departures = band_departures(bands)

        for branch_key, branch in BRANCHES.items():
            cum: list[tuple[str, float]] = []
            running = 0.0
            for stop_id, delta in branch["stops"]:
                running += delta
                cum.append((stop_id, running))
            total = cum[-1][1]

            for direction_id in (0, 1):
                headsign = branch["headsign"] if direction_id == 0 else "Portagem"
                for idx, t in enumerate(departures, start=1):
                    trip_id = f"EXT_{service_id}_{branch_key}_{direction_id}_{idx:03d}"
                    trip_rows.append(
                        {
                            "route_id": branch["route_id"],
                            "service_id": service_id,
                            "trip_id": trip_id,
                            "trip_headsign": headsign,
                            "direction_id": direction_id,
                        }
                    )

                    if direction_id == 0:
                        # Parte de Portagem no instante t; cada paragem seguinte soma o seu
                        # deslocamento acumulado desde Portagem.
                        add_stop_time(trip_id, t, "PTG", 1)
                        for seq, (stop_id, cum_min) in enumerate(cum, start=2):
                            add_stop_time(trip_id, t + cum_min, stop_id, seq)
                    else:
                        # Chega a Portagem no instante t; cada paragem, por ordem inversa (do
                        # terminal do ramal até Aeminium), fica esse mesmo deslocamento ANTES.
                        reversed_cum = list(reversed(cum))
                        for seq, (stop_id, cum_min) in enumerate(reversed_cum, start=1):
                            add_stop_time(trip_id, t - cum_min, stop_id, seq)
                        add_stop_time(trip_id, t, "PTG", len(reversed_cum) + 1)

    return trip_rows, stop_time_rows


def append_routes() -> None:
    path = DATA_DIR / "routes.txt"
    fieldnames = ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "route_color", "route_text_color"]
    new_rows = [
        {
            "route_id": branch["route_id"],
            "agency_id": "MM",
            "route_short_name": branch["route_short_name"],
            "route_long_name": branch["route_long_name"],
            "route_type": 3,
            "route_color": branch["route_color"],
            "route_text_color": "FFFFFF",
        }
        for branch in BRANCHES.values()
    ]
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(new_rows)


def append_trips(trip_rows: list[dict]) -> None:
    path = DATA_DIR / "trips.txt"
    fieldnames = ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id"]
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(trip_rows)


def append_stop_times(stop_time_rows: list[dict]) -> None:
    path = DATA_DIR / "stop_times.txt"
    fieldnames = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(stop_time_rows)


def main() -> None:
    fix_stops()
    trip_rows, stop_time_rows = generate_extension()
    append_routes()
    append_trips(trip_rows)
    append_stop_times(stop_time_rows)
    print(f"Paragens corrigidas: Mercado (MRC -> MER, longitude).")
    print(f"Rotas novas: {[b['route_id'] for b in BRANCHES.values()]}")
    print(f"Viagens novas: {len(trip_rows)}")
    print(f"Stop_times novos: {len(stop_time_rows)}")


if __name__ == "__main__":
    main()
