"""Páginas da redundância autocarro x metro (N2.5), a partir de `overlap.redundancy`.

- `create_ranking_html`: o ranking de um cenário - onde está o serviço SMTUC a par do metro, por
  linha e por corredor do metro, no dia útil e no ano estimado (secções 1 e 2).
- `create_measures_html`: o que um horário novo fez às linhas mais redundantes do anterior
  (B -> C = o Como Vou), linha a linha, com o estado das diferenças de rede e o aviso SMTUC.
- `create_extension_html`: o que um metro novo (mesmo SMTUC) faz à redundância (C -> D = a Linha
  do Hospital, N3.4): as linhas que passam a correr a par do metro, a capacidade nos corredores
  das estações novas e o overlap temporal com cada horário do metro (incl. a sensibilidade).

Mesma casca das páginas de comparação (templates/scenario_comparison.html: sem recursos externos,
fundo claro para os iframes dos slides e da parede FeedNPlay). As barras são HTML/CSS. Tudo o que
vem dos dados é escapado; as notas de método são texto fixo do projeto.
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from overlap.redundancy import Waste, metro_extension_increase, new_station_corridors

from .io import _read_template
from .scenario_comparison import _fmt_delta, _fmt_number, _trend

_METHOD_NOTE = (
    "Viagem a viagem no dia útil de referência, cada viagem com as suas paragens. Um troço conta "
    "como a par do metro quando as duas paragens ficam a ≤ 3 min a pé de uma estação (a mesma regra "
    "da extensão a par do metro). Corredor = as estações mais próximas das duas pontas do troço. "
    "Ano estimado = semana-tipo (o dia útil × 5, mais o sábado e o domingo mais próximos dentro do "
    "período do horário) × 52, sem descontar feriados nem agosto. CO2 com a frota SMTUC de fev/2025 "
    "repartida por igual pelas linhas e consumos típicos (fontes em reports/estatisticas.txt). "
    "Dados: SMTUC / Município de Coimbra; Metro Mondego (AGIT)."
)


def _corridor_label(a: str, b: str) -> str:
    return f"junto a {a}" if a == b else f"{a} – {b}"


def _bar(value: float, top: float) -> str:
    pct = 0.0 if top <= 0 else max(0.0, min(100.0, 100.0 * value / top))
    return f'<span class="bar" style="width:{pct:.1f}%"></span>'


def _page(title: str, body: str) -> str:
    page = _read_template("scenario_comparison.html")
    return page.replace("__TITLE__", html.escape(title)).replace("__BODY__", body)


def _write(output_path: Path | str, title: str, body: str) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_page(title, body), encoding="utf-8")
    return str(output_path)


def line_table(waste: Waste) -> pd.DataFrame:
    """Por linha: dia útil (by_line do dia de referência) + ano estimado (line_year)."""
    return waste.reference.by_line.merge(waste.line_year(), on="line", how="left")


def create_ranking_html(
    output_path: Path | str,
    waste: Waste,
    label: str,
    top_n: int = 15,
    csv_path: Path | str | None = None,
) -> str:
    """Ranking das redundâncias de um cenário. Com `csv_path`, grava as linhas (todas) nesse CSV e
    os corredores em `<csv>_corredores.csv`."""
    s = waste.summary()
    t = waste.reference.totals()
    lines = line_table(waste)
    top_lines = lines[lines["km_metro"] > 0].head(top_n)
    corridors = waste.reference.by_corridor.head(top_n)
    day = waste.reference.day.strftime("%d/%m/%Y")
    lab = html.escape(label)

    summary_rows = (
        f"<tr><th scope=\"row\">Autocarros·km a par do metro</th><td>{_fmt_number(s['dia_km_metro'])}</td>"
        f"<td>{_fmt_number(s['ano_km_metro'])}</td></tr>"
        f"<tr><th scope=\"row\">Autocarros·hora a par do metro</th><td>{_fmt_number(s['dia_horas_metro'])}</td>"
        f"<td>{_fmt_number(s['ano_horas_metro'])}</td></tr>"
        f"<tr><th scope=\"row\">t CO2 a par do metro</th><td>{_fmt_number(s['dia_t_co2'], 1)}</td>"
        f"<td>{_fmt_number(s['ano_t_co2'])}</td></tr>"
    )
    share = (
        f"{_fmt_number(t['km_metro'])} de {_fmt_number(t['km'])} autocarros·km do dia "
        f"({_fmt_number(t['pct_km_metro'], 1, '%')}), em {t['linhas_com_troco_metro']} das {t['linhas']} linhas com viagens."
    )
    week = " · ".join(
        f"{html.escape(str(r.tipo))} {html.escape(pd.Timestamp(r.dia).strftime('%d/%m'))}"
        f"{' × ' + str(int(r.peso)) if int(r.peso) > 1 else ''}: {_fmt_number(r.km_metro)}"
        for r in waste.week.itertuples(index=False)
    )

    top_km = float(top_lines["km_metro"].max()) if not top_lines.empty else 0.0
    line_rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{html.escape(str(r.line))}</th>"
        f"<td class=\"barcell\">{_bar(r.km_metro, top_km)}<span class=\"barval\">{_fmt_number(r.km_metro)}</span></td>"
        f"<td>{_fmt_number(r.pct_km_metro, 0, '%')}</td>"
        f"<td>{r.viagens}</td>"
        f"<td>{_fmt_number(r.horas_metro, 1)}</td>"
        f"<td>{_fmt_number(r.ano_km_metro)}</td>"
        f"<td>{_fmt_number(r.ano_t_co2, 1)}</td>"
        "</tr>"
        for r in top_lines.itertuples(index=False)
    )
    top_c = float(corridors["km_metro"].max()) if not corridors.empty else 0.0
    corridor_rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{html.escape(_corridor_label(r.station_a, r.station_b))}</th>"
        f"<td class=\"barcell\">{_bar(r.km_metro, top_c)}<span class=\"barval\">{_fmt_number(r.km_metro)}</span></td>"
        f"<td>{r.passagens}</td>"
        f"<td class=\"text\">{html.escape(str(r.linhas).replace(';', ', '))}</td>"
        "</tr>"
        for r in corridors.itertuples(index=False)
    )
    body = f"""
<section>
  <h2>{lab}: serviço SMTUC a par do metro</h2>
  <table class="counts">
    <thead><tr><th scope="col">A par do metro</th><th scope="col">Dia útil ({html.escape(day)})</th><th scope="col">Ano (estimativa)</th></tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>
  <p class="note">{share} Semana-tipo (autocarros·km a par do metro): {week}.</p>
</section>
<section>
  <h2>Linhas com mais autocarros·km a par do metro (dia útil)</h2>
  <table>
    <thead><tr><th scope="col">Linha</th><th scope="col">Autocarros·km</th><th scope="col">% dos km da linha</th><th scope="col">Viagens</th><th scope="col">Horas</th><th scope="col">Autocarros·km/ano</th><th scope="col">t CO2/ano</th></tr></thead>
    <tbody>{line_rows}</tbody>
  </table>
</section>
<section>
  <h2>Troços do metro com mais autocarros a par (dia útil)</h2>
  <table>
    <thead><tr><th scope="col">Corredor do metro</th><th scope="col">Autocarros·km</th><th scope="col">Passagens</th><th scope="col">Linhas</th></tr></thead>
    <tbody>{corridor_rows}</tbody>
  </table>
</section>
<p class="note sources">{html.escape(_METHOD_NOTE)}</p>
"""
    if csv_path is not None:
        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        lines.to_csv(csv_path, index=False)
        waste.reference.by_corridor.to_csv(csv_path.with_name(f"{csv_path.stem}_corredores.csv"), index=False)
    return _write(output_path, f"Redundância autocarro × metro: {label}", body)


def measures_table(waste_b: Waste, waste_a: Waste, diff: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    """As `top_n` linhas com mais autocarros·km a par do metro em B e o que lhes aconteceu em A:
    a linha correspondente pelas diferenças de rede (mesmo número ou renumerada), os autocarros·km
    depois, o estado e o aviso SMTUC."""
    b = line_table(waste_b)
    b = b[b["km_metro"] > 0].head(top_n)
    after_km = line_table(waste_a).set_index("line")["km_metro"]
    match = diff[diff["linha_antes"].astype(str) != ""].set_index("linha_antes")
    rows = []
    for r in b.itertuples(index=False):
        line = str(r.line)
        m = match.loc[line] if line in match.index else None
        line_after = str(m["linha_depois"]) if m is not None else ""
        km_after = float(after_km.get(line_after, 0.0)) if line_after else 0.0
        rows.append({
            "linha": line,
            "linha_depois": line_after,
            "km_metro_antes": float(r.km_metro),
            "km_metro_depois": km_after,
            "estado": str(m["estado"]) if m is not None else "",
            "aviso": str(m.get("aviso", "") or "") if m is not None else "",
        })
    return pd.DataFrame(rows, columns=["linha", "linha_depois", "km_metro_antes", "km_metro_depois", "estado", "aviso"])


def create_measures_html(
    output_path: Path | str,
    waste_b: Waste,
    waste_a: Waste,
    diff: pd.DataFrame,
    label_b: str,
    label_a: str,
    top_n: int = 15,
    csv_path: Path | str | None = None,
) -> str:
    """O que o horário de `waste_a` fez às linhas mais redundantes de `waste_b`."""
    sb, sa = waste_b.summary(), waste_a.summary()
    table = measures_table(waste_b, waste_a, diff, top_n)
    lb, la = html.escape(label_b), html.escape(label_a)

    def total_row(name: str, key: str, decimals: int = 0) -> str:
        b, a = sb[key], sa[key]
        trend = _trend(b, a, "lower", decimals)
        cls = f' class="trend-{trend}"' if trend else ""
        return (f"<tr><th scope=\"row\">{html.escape(name)}</th><td>{_fmt_number(b, decimals)}</td>"
                f"<td>{_fmt_number(a, decimals)}</td><td{cls}>{_fmt_delta(b, a, decimals, '')}</td></tr>")

    totals = (
        total_row("Autocarros·km a par do metro, dia útil", "dia_km_metro")
        + total_row("Autocarros·hora a par do metro, dia útil", "dia_horas_metro")
        + total_row("Autocarros·km a par do metro, ano (estimativa)", "ano_km_metro")
        + total_row("t CO2 a par do metro, ano (estimativa)", "ano_t_co2")
    )
    in_top = float(table["km_metro_antes"].sum())
    in_top_after = float(table["km_metro_depois"].sum())

    def line_cell(r) -> str:
        if r.linha_depois and r.linha_depois != r.linha:
            return f"{html.escape(r.linha)} → {html.escape(r.linha_depois)}"
        return html.escape(r.linha)

    rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{line_cell(r)}</th>"
        f"<td>{_fmt_number(r.km_metro_antes)}</td>"
        f"<td>{_fmt_number(r.km_metro_depois) if r.linha_depois else '—'}</td>"
        f"{_delta_cell(r.km_metro_antes, r.km_metro_depois)}"
        f"<td class=\"text\">{html.escape(r.estado or 'sem correspondência')}</td>"
        f"<td class=\"text\">{html.escape(r.aviso)}</td>"
        "</tr>"
        for r in table.itertuples(index=False)
    )
    body = f"""
<section>
  <h2>A par do metro: {lb} → {la}</h2>
  <table>
    <thead><tr><th scope="col">Indicador</th><th scope="col">{lb}</th><th scope="col">{la}</th><th scope="col">Diferença</th></tr></thead>
    <tbody>{totals}</tbody>
  </table>
</section>
<section>
  <h2>As {len(table)} linhas mais redundantes de {lb}</h2>
  <table>
    <thead><tr><th scope="col">Linha</th><th scope="col">Autocarros·km/dia<br><span>{lb}</span></th><th scope="col">Autocarros·km/dia<br><span>{la}</span></th><th scope="col">Diferença</th><th scope="col">O que mudou na linha</th><th scope="col">Aviso SMTUC</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="note">Estas linhas faziam {_fmt_number(in_top)} autocarros·km por dia útil a par do metro; depois fazem {_fmt_number(in_top_after)}. Uma linha cortada conta 0. O estado vem das diferenças de rede linha a linha (mesmo número, ou renumerada pelas paragens).</p>
</section>
<p class="note sources">{html.escape(_METHOD_NOTE)}</p>
"""
    if csv_path is not None:
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(csv_path, index=False)
    return _write(output_path, f"O que mudou nas linhas mais redundantes: {label_b} → {label_a}", body)


def _delta_cell(before: float, after: float, decimals: int = 0) -> str:
    trend = _trend(before, after, "lower", decimals)
    cls = f' class="trend-{trend}"' if trend else ""
    return f"<td{cls}>{_fmt_delta(before, after, decimals, '')}</td>"



def temporal_overlap_pct(metrics: pd.DataFrame) -> tuple[float | None, pd.Series]:
    """Overlap temporal de uma tabela de métricas por linha: total (passagens com metro a <= X min
    / candidatos espaciais, a regra do resumo do overlap) e por linha (temporal_overlaps_pct)."""
    count = pd.to_numeric(metrics["temporal_overlaps_count"], errors="coerce").fillna(0.0)
    cand = pd.to_numeric(metrics["temporal_spatial_candidates_count"], errors="coerce").fillna(0.0)
    total = 100.0 * float(count.sum()) / float(cand.sum()) if cand.sum() > 0 else None
    per_line = pd.to_numeric(metrics["temporal_overlaps_pct"], errors="coerce")
    per_line.index = metrics["line"].astype(str)
    return total, per_line


def create_extension_html(
    output_path: Path | str,
    waste_before: Waste,
    waste_after: Waste,
    stations: tuple[str, ...],
    label_before: str,
    label_after: str,
    temporal: dict[str, pd.DataFrame],
    top_n: int = 15,
    csv_path: Path | str | None = None,
) -> str:
    """O que o metro de `waste_after` (estações novas `stations`) faz à redundância de
    `waste_before`, com o mesmo SMTUC. `temporal` = {nome do cenário: métricas por linha} pela
    ordem das colunas (antes, depois e, se houver, a sensibilidade). Com `csv_path`, grava a tabela
    de todas as linhas (metro_extension_increase + overlap temporal por cenário) nesse CSV e os
    corredores das estações novas em `<csv>_corredores.csv`."""
    sb, sa = waste_before.summary(), waste_after.summary()
    table = metro_extension_increase(waste_before, waste_after, stations)
    corridors = new_station_corridors(waste_after, stations)
    shown = table[table["delta_km"] > 0].head(top_n)
    lb, la = html.escape(label_before), html.escape(label_after)
    temporal_pct = {name: temporal_overlap_pct(m) for name, m in temporal.items()}

    def total_row(name: str, before: float, after: float, decimals: int = 0) -> str:
        return (f"<tr><th scope=\"row\">{html.escape(name)}</th><td>{_fmt_number(before, decimals)}</td>"
                f"<td>{_fmt_number(after, decimals)}</td>{_delta_cell(before, after, decimals)}</tr>")

    totals = (
        total_row("Autocarros·km a par do metro, dia útil", sb["dia_km_metro"], sa["dia_km_metro"])
        + total_row("Autocarros·hora a par do metro, dia útil", sb["dia_horas_metro"], sa["dia_horas_metro"])
        + total_row("Autocarros·hora a par do metro, ano (estimativa)", sb["ano_horas_metro"], sa["ano_horas_metro"])
        + total_row("t CO2 a par do metro, ano (estimativa)", sb["ano_t_co2"], sa["ano_t_co2"])
    )
    new_day_h = float(table["horas_novas"].sum())
    new_year_h = float(table["ano_horas_novas"].sum())
    n_lines_new = int((table["horas_novas"] > 0).sum())

    top_km = float(shown["delta_km"].max()) if not shown.empty else 0.0
    t_heads = "".join(f"<th scope=\"col\">Overlap temporal<br><span>{html.escape(n)}</span></th>" for n in temporal_pct)

    def t_cells(line: str) -> str:
        cells = []
        for _, per_line in temporal_pct.values():
            value = per_line.get(line)
            cells.append(f"<td>{_fmt_number(None if value is None or value != value else float(value), 0, '%')}</td>")
        return "".join(cells)

    rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{html.escape(str(r.line))}</th>"
        f"<td>{_fmt_number(r.km_antes)}</td>"
        f"<td>{_fmt_number(r.km_depois)}</td>"
        f"<td class=\"barcell\">{_bar(r.delta_km, top_km)}<span class=\"barval\">+{_fmt_number(r.delta_km)}</span></td>"
        f"<td>{_fmt_number(r.horas_novas, 1)}</td>"
        f"<td>{_fmt_number(r.ano_horas_novas)}</td>"
        f"<td>{_fmt_number(r.ano_delta_t_co2, 1)}</td>"
        f"{t_cells(str(r.line))}"
        f"<td class=\"text\">{html.escape(str(r.estacoes_novas))}</td>"
        "</tr>"
        for r in shown.itertuples(index=False)
    )
    top_c = float(corridors["km_metro"].max()) if not corridors.empty else 0.0
    corridor_rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{html.escape(_corridor_label(r.station_a, r.station_b))}</th>"
        f"<td class=\"barcell\">{_bar(r.km_metro, top_c)}<span class=\"barval\">{_fmt_number(r.km_metro)}</span></td>"
        f"<td>{_fmt_number(r.horas_metro, 1)}</td>"
        f"<td>{r.passagens}</td>"
        f"<td class=\"text\">{html.escape(str(r.linhas).replace(';', ', '))}</td>"
        "</tr>"
        for r in corridors.itertuples(index=False)
    )
    temporal_rows = "".join(
        f"<tr><th scope=\"row\">{html.escape(name)}</th><td>{_fmt_number(total, 1, '%')}</td></tr>"
        for name, (total, _) in temporal_pct.items()
    )
    station_list = html.escape(", ".join(stations))
    body = f"""
<section>
  <h2>A par do metro: {lb} → {la}</h2>
  <table>
    <thead><tr><th scope="col">Indicador</th><th scope="col">{lb}</th><th scope="col">{la}</th><th scope="col">Diferença</th></tr></thead>
    <tbody>{totals}</tbody>
  </table>
  <p class="note">O horário SMTUC é o mesmo nos dois: a diferença vem só das estações novas ({station_list}). Nos corredores com uma estação nova numa ponta correm {_fmt_number(new_day_h, 1)} autocarros·hora por dia útil, de {n_lines_new} linhas ({_fmt_number(new_year_h)} por ano, estimativa): é a capacidade que fica ao lado da linha nova.</p>
</section>
<section>
  <h2>As linhas que passam a correr mais a par do metro</h2>
  <table>
    <thead><tr><th scope="col">Linha</th><th scope="col">Autocarros·km/dia<br><span>{lb}</span></th><th scope="col">Autocarros·km/dia<br><span>{la}</span></th><th scope="col">Aumento</th><th scope="col">Horas/dia nos corredores novos</th><th scope="col">Horas/ano nos corredores novos</th><th scope="col">t CO2/ano a mais</th>{t_heads}<th scope="col">Estações novas por onde passa</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="note">Overlap temporal da linha = passagens nas paragens a par do metro com um metro a ≤ 5 min. A sensibilidade (menos viagens do metro na linha nova) não muda a redundância espacial, que só depende da distância às estações; muda só o overlap temporal.</p>
</section>
<section>
  <h2>Corredores das estações novas (dia útil)</h2>
  <table>
    <thead><tr><th scope="col">Corredor do metro</th><th scope="col">Autocarros·km</th><th scope="col">Autocarros·hora</th><th scope="col">Passagens</th><th scope="col">Linhas</th></tr></thead>
    <tbody>{corridor_rows}</tbody>
  </table>
</section>
<section>
  <h2>Overlap temporal de toda a rede, por horário do metro</h2>
  <table class="counts">
    <thead><tr><th scope="col">Cenário</th><th scope="col">Passagens a par do metro com um metro a ≤ 5 min</th></tr></thead>
    <tbody>{temporal_rows}</tbody>
  </table>
</section>
<p class="note sources">{html.escape(_METHOD_NOTE)}</p>
"""
    if csv_path is not None:
        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        out = table.copy()
        for name, (_, per_line) in temporal_pct.items():
            out[f"overlap_temporal_pct | {name}"] = out["line"].astype(str).map(per_line)
        out.to_csv(csv_path, index=False)
        corridors.to_csv(csv_path.with_name(f"{csv_path.stem}_corredores.csv"), index=False)
    return _write(output_path, f"O que o metro novo torna redundante: {label_before} → {label_after}", body)
