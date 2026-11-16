"""Impressões digitais dos feeds GTFS com que os testes de integração "com valores fixos" foram
calibrados (contagens de viagens, frequências, transbordos, desvios de fase...).

Esses valores só fazem sentido para ESTES dados. Quando os feeds mudarem (ex.: dados oficiais
AGIT, Fase D do roadmap), os testes que chamam `require_reference_data(...)` SALTAM em vez de
falhar, com a lista do que mudou. Para os reativar: confirmar os valores novos (correr os
scripts/a regeneração e comparar), atualizar os números nos testes e correr

    python src/tests/reference_data.py

para imprimir as impressões digitais novas e colá-las em REFERENCE_FINGERPRINTS abaixo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_processing.fingerprint import feed_fingerprint

ROOT = Path(__file__).resolve().parents[2]

REFERENCE_FINGERPRINTS: dict[str, str] = {
    # Calibrado a 2026-11-13: SMTUC do repo + Metrobus sintético (pré-fase 2 e fase 2).
    "smtuc": "864ee5237cafc617",
    "metrobus": "b3f7170e307f7cc3",
    "metrobus_fase2": "90417259ec9abc60",
}


def dataset_fingerprint(dataset: str) -> str | None:
    """sha256 (16 hex) dos ficheiros principais da pasta do dataset (gtfs.dataset_dir), com as quebras de linha
    normalizadas (CRLF/LF não muda a impressão digital). None se o dataset não existir."""
    from gtfs_processing.gtfs import dataset_dir

    try:
        folder = dataset_dir(dataset, ROOT)
    except KeyError:
        return None
    return feed_fingerprint(folder)


def require_reference_data(*datasets: str) -> None:
    """Salta o teste se algum dos `datasets` não existir ou não for o feed de referência."""
    problems = []
    for dataset in datasets:
        fp = dataset_fingerprint(dataset)
        if fp is None:
            problems.append(f"{dataset}: não existe")
        elif fp != REFERENCE_FINGERPRINTS.get(dataset):
            problems.append(f"{dataset}: mudou ({fp} != {REFERENCE_FINGERPRINTS.get(dataset)})")
    if problems:
        pytest.skip(
            "valores fixos calibrados para outros dados GTFS - rever e atualizar "
            f"(ver src/tests/reference_data.py): {'; '.join(problems)}"
        )


if __name__ == "__main__":
    for name in REFERENCE_FINGERPRINTS:
        print(f'    "{name}": "{dataset_fingerprint(name)}",')
