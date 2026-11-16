"""Impressão digital de um feed GTFS em disco: identifica de forma curta e estável os dados com
que um número foi calculado (testes com valores fixos, snapshots de métricas).

Só entram os ficheiros que definem a rede e os horários; as quebras de linha são normalizadas
(CRLF/LF não muda a impressão digital, para o git no Windows não a alterar).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FEED_FILES = ("routes.txt", "trips.txt", "stop_times.txt", "stops.txt", "calendar.txt", "calendar_dates.txt")


def feed_fingerprint(folder: Path) -> str | None:
    """sha256 (16 hex) dos FEED_FILES de `folder`; None se a pasta não tiver trips.txt."""
    folder = Path(folder)
    if not (folder / "trips.txt").exists():
        return None
    h = hashlib.sha256()
    for name in FEED_FILES:
        path = folder / name
        h.update(name.encode())
        h.update(path.read_bytes().replace(b"\r\n", b"\n") if path.exists() else b"<ausente>")
    return h.hexdigest()[:16]
