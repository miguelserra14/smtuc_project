"""Página do horário assumido da Linha do Hospital (N3.5, PLANEADO), para o slide s3_linha.

Tudo vem dos dados: os troços, as distâncias no eixo, os tempos e a velocidade de referência do
passo `extend_to_hospital` registado no PROVENANCE.json do feed planeado (scripts/build_feeds.py),
e o serviço num dia útil numa estação nova (`hospital_line.station_service`) em cada variante do
horário. Mesma casca das páginas de comparação; tudo o que vem dos dados é escapado.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from gtfs_processing.hospital_line import ALL_LINES
from overlap.redundancy import station_name

from .io import _read_template
from .scenario_comparison import _fmt_number

EXTENSION_STEP_PREFIX = "PLANEADO: prolongar"
_SENSE_LABEL = {"subir": "para o Pediátrico", "descer": "da Linha do Hospital para a Baixa"}


def extension_step(provenance_path: Path | str) -> dict:
    """O passo `extend_to_hospital` de um PROVENANCE.json (levanta se não houver exatamente um)."""
    data = json.loads(Path(provenance_path).read_text(encoding="utf-8"))
    steps = [t for t in data.get("transformacoes", []) if str(t.get("passo", "")).startswith(EXTENSION_STEP_PREFIX)]
    if len(steps) != 1:
        raise ValueError(f"{provenance_path}: {len(steps)} passos '{EXTENSION_STEP_PREFIX}...' (esperado 1)")
    return steps[0]


def legs_table(step: dict) -> pd.DataFrame:
    """Um troço por linha, da República para o Pediátrico: distância no eixo e minutos em cada
    sentido (o troço a descer correspondente é o mesmo par de estações, ao contrário)."""
    up = step["trocos"]["subir"]
    down = {(station_name(leg["para"]), station_name(leg["de"])): leg for leg in step["trocos"]["descer"]}
    rows = []
    for leg in up:
        key = (station_name(leg["de"]), station_name(leg["para"]))
        back = down.get(key)
        if back is None:
            raise ValueError(f"troço {key[0]} -> {key[1]} sem o correspondente a descer")
        rows.append({"de": key[0], "para": key[1], "eixo_subir_m": float(leg["eixo_m"]), "min_subir": float(leg["minutos"]),
                     "eixo_descer_m": float(back["eixo_m"]), "min_descer": float(back["minutos"])})
    return pd.DataFrame(rows)


def _fmt_min(value: float) -> str:
    return "–" if value != value else _fmt_number(value, 1, "min")


def create_hospital_line_html(
    output_path: Path | str,
    step: dict,
    services: dict[str, pd.DataFrame],
    station: str,
    day_label: str,
) -> str:
    """`step` = o passo do PROVENANCE (troços e velocidades); `services` = {variante:
    station_service(...)} na estação `station`, pela ordem das colunas."""
    legs = legs_table(step)
    speeds = step["velocidade_referencia"]
    lines = ", ".join(str(x) for x in step["linhas"])
    leg_rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{html.escape(r.de)} – {html.escape(r.para)}</th>"
        f"<td>{_fmt_number(r.eixo_subir_m)} m</td><td>{_fmt_min(r.min_subir)}</td><td>{_fmt_min(r.min_descer)}</td>"
        "</tr>"
        for r in legs.itertuples(index=False)
    )
    leg_rows += (
        f"<tr><th scope=\"row\">Total</th><td>{_fmt_number(legs['eixo_subir_m'].sum())} m</td>"
        f"<td>{_fmt_min(legs['min_subir'].sum())}</td><td>{_fmt_min(legs['min_descer'].sum())}</td></tr>"
    )
    speed_text = " ".join(
        f"A {html.escape(sense)}: {html.escape(str(sp['troco']).replace(' -> ', ' → '))},{_fmt_number(sp['eixo_m'])} m em "
        f"{_fmt_number(sp['minutos_medios'], 2)} min, média de {sp['viagens']} viagens = {_fmt_number(sp['km_h'], 1)} km/h."
        for sense, sp in speeds.items()
    )

    labels = list(services)
    keyed = {label: df.set_index(["linha", "sentido"]) for label, df in services.items()}
    order: list[tuple[str, str]] = []
    for df in services.values():
        for key in zip(df["linha"], df["sentido"]):
            if key not in order:
                order.append(key)
    order.sort(key=lambda k: (0 if k[1] == "subir" else 1, k[0] == ALL_LINES, k[0]))
    heads = "".join(f"<th scope=\"col\">Passagens<br><span>{html.escape(l)}</span></th>"
                    f"<th scope=\"col\">Intervalo mediano<br><span>{html.escape(l)}</span></th>" for l in labels)

    def cells(key: tuple[str, str]) -> str:
        out = []
        for label in labels:
            df = keyed[label]
            if key in df.index:
                r = df.loc[key]
                out.append(f"<td>{int(r['passagens'])}</td><td>{_fmt_min(float(r['intervalo_mediano_min']))}</td>")
            else:
                out.append("<td>0</td><td>–</td>")
        return "".join(out)

    total_cls = ' class="total"'
    service_rows = "".join(
        f"<tr{total_cls if linha == ALL_LINES else ''}><th scope=\"row\">"
        f"{'Todas as linhas' if linha == ALL_LINES else html.escape(linha)}</th>"
        f"<td class=\"text\">{html.escape(_SENSE_LABEL.get(sentido, sentido))}</td>{cells((linha, sentido))}</tr>"
        for linha, sentido in order
    )
    body = f"""
<section>
  <h2>Linha do Hospital: estações e tempos assumidos</h2>
  <table>
    <thead><tr><th scope="col">Troço</th><th scope="col">Distância na via</th><th scope="col">A subir</th><th scope="col">A descer</th></tr></thead>
    <tbody>{leg_rows}</tbody>
  </table>
  <p class="note">Estações e via do mapa oficial do Metro Mondego. Não há horário oficial: as viagens {html.escape(lines)} que hoje acabam ou começam na República seguem até ao Pediátrico, com a mesma frequência, e cada troço novo demora a distância na via ÷ a velocidade média do troço urbano que chega à República. {speed_text}</p>
</section>
<section>
  <h2>Serviço num dia útil ({html.escape(day_label)}) na estação {html.escape(station)}</h2>
  <table>
    <thead><tr><th scope="col">Linha</th><th scope="col">Sentido</th>{heads}</tr></thead>
    <tbody>{service_rows}</tbody>
  </table>
  <p class="note">Intervalo mediano entre passagens consecutivas das 7 h às 20 h. A variante com metade das viagens é a sensibilidade do horário assumido: uma em cada duas viagens de cada linha e sentido segue até ao Pediátrico, as outras acabam na República.</p>
</section>
<p class="note sources">Cenário planeado, não oficial. Dados: Metro Mondego (NeTEx AGIT de 11/11/2026; mapa da rede, dados.gov.pt, CC BY 4.0).</p>
"""
    page = _read_template("scenario_comparison.html")
    page = page.replace("__TITLE__", html.escape("Linha do Hospital (planeado)")).replace("__BODY__", body)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return str(output_path)
