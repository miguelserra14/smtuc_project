"""Leitura do mapa oficial da rede Metrobus (KMZ do dados.gov.pt) e distâncias ao longo do eixo (N3.0).

O KMZ (data/raw/dados-gov/metro-mondego-kmz/.../rede-metrobus.kmz, CC BY 4.0) é a única fonte
oficial da Linha do Hospital (fase 3, março de 2027): tem as estações ("Paragens LH") e o eixo da
via ("Eixo LH"), mas nenhum horário. O eixo vem partido em troços soltos, sem ordem, que se tocam
nas pontas (ou numa ponta sobre um vértice de outro troço). Para medir a distância entre duas
estações monta-se um grafo com os vértices dos troços (vértices iguais = o mesmo nó; uma ponta a
<= SNAP_M de um vértice de outro troço fica ligada a ele), cada estação liga-se ao vértice mais
próximo (no máximo MAX_STATION_OFFSET_M: as estações ficam ao lado da via) e a distância é o caminho
mais curto no grafo (Dijkstra). O grafo não tem sentidos: onde a via se separa por sentido
("Directriz Ascendente/Descendente") a diferença é de poucos metros. No KMZ oficial o Pediátrico
fica no anel de viragem do fim da linha, por isso Hospitais -> Pediátrico (~840 m) é quase o dobro
da reta; sem sentidos, os dois sentidos usam o lado mais curto do anel.

Coordenadas do KML: "lon,lat[,alt]". Distâncias só com geo.haversine_m. Lê apenas XML (sem
dependências novas); o KMZ é um zip com doc.kml.
"""

from __future__ import annotations

import heapq
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from gtfs_processing.geo import haversine_m

KML_NS = "{http://www.opengis.net/kml/2.2}"
SNAP_M = 5.0
MAX_STATION_OFFSET_M = 75.0

# Pastas do KMZ oficial e a ordem das estações da Linha do Hospital em cada sentido. "asc" = a
# plataforma de quem sobe da Baixa para o hospital; "desc" = a de quem desce (no NeTEx da fase 2
# as viagens para a Baixa partem da República (desc) e as que vêm da Baixa chegam à República (asc)).
HOSPITAL_AXIS_FOLDER = "Eixo LH"
HOSPITAL_STATIONS_FOLDER = "Paragens LH"
HOSPITAL_UP = ("República (asc)", "Sereia (asc)", "Celas", "Polo Ciências da Saúde", "Hospitais (H.U.C.)", "Pediátrico")
HOSPITAL_DOWN = ("Pediátrico", "Hospitais (H.U.C.)", "Polo Ciências da Saúde", "Celas", "Sereia (desc)", "República (desc)")


class KmzError(ValueError):
    pass


@dataclass(frozen=True)
class Placemark:
    folders: tuple[str, ...]          # caminho de pastas (Folder/name) até ao placemark
    name: str
    kind: str                         # "point" ou "line"
    coords: tuple[tuple[float, float], ...]  # (lat, lon)


def _read_kml_text(path: Path) -> bytes:
    path = Path(path)
    if path.suffix.lower() == ".kml":
        return path.read_bytes()
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not names:
            raise KmzError(f"{path}: o KMZ não tem nenhum .kml")
        return zf.read("doc.kml" if "doc.kml" in names else names[0])


def _coords(text: str | None) -> tuple[tuple[float, float], ...]:
    out = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            raise KmzError(f"coordenada KML inválida: {token!r}")
        lon, lat = float(parts[0]), float(parts[1])
        out.append((lat, lon))
    return tuple(out)


def read_placemarks(path: Path | str) -> list[Placemark]:
    """Todos os pontos e linhas do KML/KMZ, com o caminho de pastas de cada um."""
    root = ET.fromstring(_read_kml_text(Path(path)))
    out: list[Placemark] = []

    def walk(el, folders: tuple[str, ...]) -> None:
        for child in el:
            tag = child.tag.replace(KML_NS, "")
            if tag == "Folder":
                walk(child, folders + ((child.findtext(f"{KML_NS}name") or "").strip(),))
            elif tag == "Document":
                walk(child, folders)
            elif tag == "Placemark":
                name = (child.findtext(f"{KML_NS}name") or "").strip()
                for ls in child.iter(f"{KML_NS}LineString"):
                    out.append(Placemark(folders, name, "line", _coords(ls.findtext(f"{KML_NS}coordinates"))))
                for pt in child.iter(f"{KML_NS}Point"):
                    out.append(Placemark(folders, name, "point", _coords(pt.findtext(f"{KML_NS}coordinates"))))

    walk(root, ())
    return out


def in_folder(placemarks: list[Placemark], folder: str, kind: str) -> list[Placemark]:
    return [p for p in placemarks if folder in p.folders and p.kind == kind]


def stations(placemarks: list[Placemark], folder: str) -> dict[str, tuple[float, float]]:
    """Nome -> (lat, lon) dos pontos de `folder`. Nomes repetidos levantam KmzError."""
    out: dict[str, tuple[float, float]] = {}
    for p in in_folder(placemarks, folder, "point"):
        if p.name in out:
            raise KmzError(f"estação repetida em {folder!r}: {p.name!r}")
        out[p.name] = p.coords[0]
    if not out:
        raise KmzError(f"nenhuma estação na pasta {folder!r}")
    return out


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(haversine_m(a[0], a[1], b[0], b[1]))


class AxisGraph:
    """Grafo não orientado dos vértices do eixo (nós = coordenadas distintas)."""

    def __init__(self, lines: list[tuple[tuple[float, float], ...]], snap_m: float = SNAP_M) -> None:
        self.nodes: list[tuple[float, float]] = []
        self._index: dict[tuple[float, float], int] = {}
        self.edges: dict[int, dict[int, float]] = {}
        for line in lines:
            ids = [self._node(c) for c in line]
            for a, b in zip(ids, ids[1:]):
                if a != b:
                    self._link(a, b, _dist(self.nodes[a], self.nodes[b]))
        # Pontas soltas: liga cada ponta ao vértice mais próximo de OUTRO troço, se a <= snap_m.
        for i, line in enumerate(lines):
            for end in (line[0], line[-1]):
                a = self._index[end]
                best, best_d = None, snap_m
                for j, other in enumerate(lines):
                    if j == i:
                        continue
                    for c in other:
                        d = _dist(end, c)
                        if 0 < d <= best_d:
                            best, best_d = self._index[c], d
                if best is not None:
                    self._link(a, best, best_d)

    def _node(self, c: tuple[float, float]) -> int:
        if c not in self._index:
            self._index[c] = len(self.nodes)
            self.nodes.append(c)
            self.edges[self._index[c]] = {}
        return self._index[c]

    def _link(self, a: int, b: int, d: float) -> None:
        if d < self.edges[a].get(b, float("inf")):
            self.edges[a][b] = d
            self.edges[b][a] = d

    def nearest(self, point: tuple[float, float]) -> tuple[int, float]:
        best = min(range(len(self.nodes)), key=lambda i: _dist(point, self.nodes[i]))
        return best, _dist(point, self.nodes[best])

    def path_m(self, a: int, b: int) -> float:
        """Caminho mais curto (m) entre dois nós; KmzError se não houver ligação."""
        dist = {a: 0.0}
        heap = [(0.0, a)]
        while heap:
            d, n = heapq.heappop(heap)
            if n == b:
                return d
            if d > dist.get(n, float("inf")):
                continue
            for m, w in self.edges[n].items():
                nd = d + w
                if nd < dist.get(m, float("inf")):
                    dist[m] = nd
                    heapq.heappush(heap, (nd, m))
        raise KmzError("o eixo não liga as duas estações (troços desligados)")


@dataclass(frozen=True)
class Leg:
    origem: str
    destino: str
    eixo_m: float      # ao longo do eixo, entre os vértices onde as estações se ligam
    reta_m: float      # em linha reta entre as estações (conferência)
    desvio_origem_m: float
    desvio_destino_m: float


def chain_distances(
    graph: AxisGraph,
    points: dict[str, tuple[float, float]],
    names: tuple[str, ...],
    max_offset_m: float = MAX_STATION_OFFSET_M,
) -> list[Leg]:
    """Distância no eixo entre cada par de estações consecutivas de `names`."""
    missing = [n for n in names if n not in points]
    if missing:
        raise KmzError(f"estações em falta no KMZ: {missing}")
    snapped = {}
    for n in names:
        node, offset = graph.nearest(points[n])
        if offset > max_offset_m:
            raise KmzError(f"{n!r} fica a {offset:.0f} m do eixo (máximo {max_offset_m:.0f} m)")
        snapped[n] = (node, offset)
    legs = []
    for a, b in zip(names, names[1:]):
        legs.append(Leg(a, b, graph.path_m(snapped[a][0], snapped[b][0]), _dist(points[a], points[b]),
                        snapped[a][1], snapped[b][1]))
    return legs


def axis_graph(placemarks: list[Placemark], folder: str = HOSPITAL_AXIS_FOLDER) -> AxisGraph:
    lines = [p.coords for p in in_folder(placemarks, folder, "line") if len(p.coords) >= 2]
    if not lines:
        raise KmzError(f"nenhum troço de eixo na pasta {folder!r}")
    return AxisGraph(lines)


def hospital_line_legs(path: Path | str) -> dict[str, list[Leg]]:
    """Distâncias da Linha do Hospital nos dois sentidos: {"subir": República (asc) -> Pediátrico,
    "descer": Pediátrico -> República (desc)}."""
    placemarks = read_placemarks(path)
    graph = axis_graph(placemarks)
    points = stations(placemarks, HOSPITAL_STATIONS_FOLDER)
    return {"subir": chain_distances(graph, points, HOSPITAL_UP),
            "descer": chain_distances(graph, points, HOSPITAL_DOWN)}


def _main() -> None:
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Distâncias da Linha do Hospital no eixo do KMZ oficial")
    parser.add_argument("kmz", type=Path)
    args = parser.parse_args()
    for sense, legs in hospital_line_legs(args.kmz).items():
        total = sum(leg.eixo_m for leg in legs)
        print(f"{sense}: {total:.0f} m no eixo")
        for leg in legs:
            print(f"  {leg.origem} -> {leg.destino}: eixo {leg.eixo_m:.0f} m, reta {leg.reta_m:.0f} m "
                  f"(estações a {leg.desvio_origem_m:.0f} / {leg.desvio_destino_m:.0f} m do eixo)")


if __name__ == "__main__":
    _main()
