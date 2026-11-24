"""Raiz do projeto e resolução de caminhos - fonte ÚNICA (antes havia ~12 cópias de
`Path(__file__).resolve().parents[N]`).

Os caminhos em `config.py` (outputs/..., data/...) são RELATIVOS À RAIZ DO PROJETO, não à pasta
onde se corre o comando: abri-los com `Path(caminho)` só funcionava a partir da raiz. Usar
`project_path(...)` sempre que se lê ou escreve um deles. (Continuam relativos em config porque
também servem de URL relativo nos dashboards.)
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(path: str | Path) -> Path:
    """Caminho absoluto: relativo -> a partir de PROJECT_ROOT; absoluto -> sem alterações."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p
