from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import LINE_METRICS_DB_PATH

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception:  # pragma: no cover - optional dependency guard
    go = None
    make_subplots = None

from .io import _write_readable_plotly_html


def _load_temporal_breakdown_df(metrics_csv: str | Path = LINE_METRICS_DB_PATH) -> pd.DataFrame:
    df = pd.read_csv(metrics_csv)
    cols = ["line", "temporal_overlaps_count", "temporal_overlaps_pct", "temporal_spatial_candidates_count"]
    df = df[cols].copy()
    for col in cols[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df = df[df["temporal_overlaps_count"] > 0]
    return df.sort_values("temporal_overlaps_count", ascending=False).reset_index(drop=True)


def _bucket_top_n(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Mantém as top_n linhas e agrega o resto numa linha "Outras"."""
    if len(df) <= top_n:
        return df.copy()

    head = df.iloc[:top_n].copy()
    tail = df.iloc[top_n:]
    tail_count = float(tail["temporal_overlaps_count"].sum())
    tail_candidates = float(tail["temporal_spatial_candidates_count"].sum())
    tail_pct = (tail_count / tail_candidates * 100.0) if tail_candidates > 0 else 0.0
    outras = pd.DataFrame(
        [
            {
                "line": f"Outras ({len(tail)} linhas)",
                "temporal_overlaps_count": tail_count,
                "temporal_overlaps_pct": tail_pct,
                "temporal_spatial_candidates_count": tail_candidates,
            }
        ]
    )
    return pd.concat([head, outras], ignore_index=True)


def create_temporal_overlap_breakdown_html(
    output_path: Path | str,
    metrics_csv: str | Path = LINE_METRICS_DB_PATH,
    bar_top_n: int = 15,
    pie_top_n: int = 6,
) -> Path:
    """Gera um HTML com pie chart e bar chart do overlap temporal por linha, para comparação direta."""
    if go is None or make_subplots is None:
        raise ImportError("plotly não está disponível para gerar visualizações")

    output_path = Path(output_path)
    df = _load_temporal_breakdown_df(metrics_csv)

    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="Sem dados de overlap temporal disponíveis")
        _write_readable_plotly_html(fig, output_path, title="Overlap Temporal por Linha")
        return output_path

    pie_df = _bucket_top_n(df, pie_top_n)
    bar_df = _bucket_top_n(df, bar_top_n).sort_values("temporal_overlaps_count", ascending=True)
    bar_lines = bar_df["line"].tolist()

    total_events = int(df["temporal_overlaps_count"].sum())
    lines_with_overlap = int(len(df))

    # Alturas em pixels calculadas primeiro (não valores relativos arbitrários) para que o
    # espaço de cada linha do bar chart seja sempre suficiente para mostrar o nome da linha,
    # e para que se possa derivar analiticamente os domains (usados abaixo para dar folga ao
    # título do pie chart e para posicionar a legenda de cor do bar chart).
    pie_height_px = 460.0
    bar_height_px = max(420.0, 26.0 * len(bar_lines) + 160.0)
    vertical_spacing = 0.08
    total_height = pie_height_px + bar_height_px + 120.0

    avail = 1.0 - vertical_spacing
    row1_frac = pie_height_px / (pie_height_px + bar_height_px)
    row1_y0, row1_y1 = 1.0 - row1_frac * avail, 1.0
    row2_y0, row2_y1 = 0.0, row1_y0 - vertical_spacing

    fig = make_subplots(
        rows=2,
        cols=1,
        specs=[[{"type": "domain"}], [{"type": "xy"}]],
        row_heights=[pie_height_px, bar_height_px],
        vertical_spacing=vertical_spacing,
        subplot_titles=(
            f"Top {pie_top_n} linhas + Outras (share do total de eventos)",
            f"Top {bar_top_n} linhas por nº de eventos de overlap temporal",
        ),
    )

    fig.add_trace(
        go.Pie(
            labels=pie_df["line"],
            values=pie_df["temporal_overlaps_count"],
            sort=False,
            textinfo="label+percent",
            textposition="inside",
            hovertemplate="Linha %{label}<br>Eventos: %{value}<br>Share: %{percent}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    # fig.add_trace(row=, col=) sobrepõe qualquer domain passado ao construtor do Pie, por
    # isso a folga entre o título (ancorado no topo do domain) e o próprio gráfico só pode ser
    # aplicada depois, editando o domain já atribuído pelo make_subplots.
    title_gap = 0.05
    fig.update_traces(
        domain=dict(x=[0.12, 0.88], y=[row1_y0, row1_y1 - title_gap]),
        selector=dict(type="pie"),
    )

    fig.add_trace(
        go.Bar(
            x=bar_df["temporal_overlaps_count"],
            y=bar_df["line"],
            orientation="h",
            marker=dict(
                color=bar_df["temporal_overlaps_pct"],
                colorscale="YlOrRd",
                colorbar=dict(
                    title=dict(
                        text="Métrica: % dos candidatos<br>espaciais que tiveram<br>overlap temporal",
                        side="right",
                    ),
                    len=(row2_y1 - row2_y0) * 0.85,
                    y=(row2_y0 + row2_y1) / 2.0,
                ),
            ),
            hovertemplate="Linha %{y}<br>Eventos: %{x}<br>%% sobre candidatos espaciais: %{marker.color:.1f}%<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        title=dict(
            text=(
                f"Breakdown do overlap temporal por linha "
                f"({lines_with_overlap} linhas com overlap, {total_events} eventos no total)"
            ),
            y=0.99,
            yanchor="top",
        ),
        showlegend=False,
        height=int(total_height),
        margin=dict(t=110, b=60, l=60, r=60),
        plot_bgcolor="white",
    )
    fig.update_xaxes(title_text="Nº de eventos de overlap temporal", row=2, col=1)
    fig.update_yaxes(
        type="category",
        tickmode="array",
        tickvals=bar_lines,
        ticktext=bar_lines,
        automargin=True,
        row=2,
        col=1,
    )

    _write_readable_plotly_html(fig, output_path, title="Overlap Temporal por Linha")
    return output_path
