"""Página "O que mudou na rede SMTUC" (N1.3): a tabela de `overlap.network_diff` formatada.

Usa a mesma casca da página de comparação de cenários (templates/scenario_comparison.html: sem
recursos externos, fundo claro para viver num iframe dos slides e da parede FeedNPlay). Tudo o
que vem dos dados é escapado. Grava também o CSV completo, para se poder conferir linha a linha.
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from overlap.network_diff import ROUTE_CHANGE_MIN_STOPS, STATUS_ORDER, STOP_MOVE_MAX_M, line_sort_key, summarize

from .io import _read_template
from .scenario_comparison import _fmt_delta, _fmt_number

_STATUS_LABEL = {
    "cortada": "Cortadas",
    "renumerada": "Renumeradas",
    "nova": "Novas",
    "percurso alterado": f"Percurso alterado (≥ {ROUTE_CHANGE_MIN_STOPS} paragens retiradas ou novas)",
    "ajuste de paragens": f"Ajuste de paragens (menos de {ROUTE_CHANGE_MIN_STOPS}, ou paragens deslocadas)",
    "só horário": "Só o horário (mesmas paragens)",
    "igual": "Iguais",
}


def _num(value: object) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)


def _km(value: object) -> str:
    number = _num(value)
    return _fmt_number(number / 1000 if number is not None else None, 1)


def _line_cell(row: pd.Series) -> str:
    before, after = row["linha_antes"], row["linha_depois"]
    if before and after and before == after:
        label = before
    else:
        label = f"{before or '—'} → {after or '—'}"
    name = row["nome_depois"] or row["nome_antes"]
    small = f'<br><span class="name">{html.escape(str(name))}</span>' if name else ""
    return f'<th scope="row">{html.escape(str(label))}{small}</th>'


def _changed_rows(diff: pd.DataFrame) -> str:
    out = []
    for _, row in diff[~diff["estado"].isin(["igual", "só horário"])].iterrows():
        stops = (
            f"{row['paragens_mantidas']} / {row['paragens_deslocadas']} / "
            f"{row['paragens_retiradas']} / {row['paragens_novas']}"
        )
        trips = f"{row['viagens_antes']} → {row['viagens_depois']}"
        overlap = f"{_km(row.get('overlap_extension_m_antes'))} → {_km(row.get('overlap_extension_m_depois'))}"
        out.append(
            "<tr>"
            f"{_line_cell(row)}"
            f"<td class=\"text\">{html.escape(str(row['estado']))}</td>"
            f"<td>{html.escape(trips)}</td>"
            f"<td>{html.escape(stops)}</td>"
            f"<td>{html.escape(overlap)}</td>"
            f"<td class=\"text\">{html.escape(str(row.get('aviso', '') or ''))}</td>"
            "</tr>"
        )
    return "".join(out)


def _line_list(diff: pd.DataFrame, status: str) -> str:
    lines = sorted((b or a for b, a in zip(diff.loc[diff["estado"] == status, "linha_antes"],
                                             diff.loc[diff["estado"] == status, "linha_depois"])), key=line_sort_key)
    return ", ".join(html.escape(str(line)) for line in lines) or "nenhuma"


def _render_body(diff: pd.DataFrame, before_label: str, after_label: str, note_html: str) -> str:
    summary = summarize(diff)
    b, a = html.escape(before_label), html.escape(after_label)
    status_rows = "".join(
        f"<tr><th scope=\"row\">{html.escape(_STATUS_LABEL[s])}</th><td>{summary['estados'][s]}</td></tr>"
        for s in STATUS_ORDER
    )
    ext_b = summary.get("overlap_extension_m_antes")
    ext_a = summary.get("overlap_extension_m_depois")
    totals = (
        f"<tr><th scope=\"row\">Linhas com viagens no dia</th><td>{summary['linhas_antes']}</td><td>{summary['linhas_depois']}</td>"
        f"<td>{_fmt_delta(summary['linhas_antes'], summary['linhas_depois'], 0, '')}</td></tr>"
        f"<tr><th scope=\"row\">Viagens no dia</th><td>{_fmt_number(summary['viagens_antes'])}</td><td>{_fmt_number(summary['viagens_depois'])}</td>"
        f"<td>{_fmt_delta(summary['viagens_antes'], summary['viagens_depois'], 0, '')}</td></tr>"
    )
    if ext_b is not None and ext_a is not None:
        totals += (
            "<tr><th scope=\"row\">Extensão a par do metro (soma das linhas com viagens no dia)</th>"
            f"<td>{_fmt_number(ext_b / 1000, 1, 'km')}</td><td>{_fmt_number(ext_a / 1000, 1, 'km')}</td>"
            f"<td>{_fmt_delta(ext_b / 1000, ext_a / 1000, 1, 'km')}</td></tr>"
        )
    sources = sorted({url for urls in diff.get("aviso_fonte", pd.Series(dtype=str)) for url in str(urls).split() if url})
    sources_html = (
        '<p class="note">Avisos SMTUC: ' + " · ".join(f"<code>{html.escape(u)}</code>" for u in sources) + "</p>"
        if sources else ""
    )
    return f"""
<section>
  <h2>Resumo: {b} → {a}</h2>
  <table>
    <thead><tr><th scope="col">Indicador</th><th scope="col">{b}</th><th scope="col">{a}</th><th scope="col">Diferença</th></tr></thead>
    <tbody>{totals}</tbody>
  </table>
  <table class="counts">
    <thead><tr><th scope="col">Linhas</th><th scope="col">N.º</th></tr></thead>
    <tbody>{status_rows}</tbody>
  </table>
</section>
<section>
  <h2>Linhas que mudaram</h2>
  <table>
    <thead><tr><th scope="col">Linha</th><th scope="col">Estado</th><th scope="col">Viagens no dia</th><th scope="col">Paragens<br><span>mantidas / deslocadas / retiradas / novas</span></th><th scope="col">A par do metro (km)</th><th scope="col">Aviso SMTUC</th></tr></thead>
    <tbody>{_changed_rows(diff)}</tbody>
  </table>
  <p class="note">Só o horário: {_line_list(diff, "só horário")}. Iguais: {_line_list(diff, "igual")}.</p>
  {sources_html}
</section>
<p class="note sources">{note_html}</p>
"""


def create_network_diff_html(
    output_path: Path | str,
    diff: pd.DataFrame,
    before_label: str,
    after_label: str,
    note_html: str = "",
    csv_path: Path | str | None = None,
) -> str:
    """Escreve a página (e, se `csv_path`, a tabela completa em CSV). `note_html` é a nota final
    (método e fontes) e NÃO é escapada: só texto do chamador, nunca dados."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    title = f"O que mudou na rede SMTUC: {before_label} → {after_label}"
    page = _read_template("scenario_comparison.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__BODY__", _render_body(diff, before_label, after_label, note_html))
    output_path.write_text(page, encoding="utf-8")
    if csv_path is not None:
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        diff.to_csv(csv_path, index=False)
    return str(output_path)


def default_note_html(day_before: str, day_after: str) -> str:
    """Nota de método das diferenças de rede (texto fixo do projeto, não dados)."""
    days = day_after if day_before == day_after else f"{day_before} e {day_after}"
    return (
        f"Só linhas com viagens no dia de referência ({html.escape(days)}). Linha = número público "
        "(route_short_name); paragem = código da paragem (stop_code), que se mantém entre horários. "
        f"Uma paragem trocada por outra a ≤ {STOP_MOVE_MAX_M:.0f} m conta como deslocada, não como "
        "mudança de percurso. A extensão a par do metro é a das métricas por linha de cada cenário. "
        "O horário Ep212 é de março de 2026: as diferenças incluem também a reestruturação de 14/06 "
        "(linhas 5, 5T, 5F, 33 e 33R), assinalada como anterior ao Como Vou. Dados: SMTUC / "
        "Município de Coimbra; avisos em smtuc.pt."
    )
