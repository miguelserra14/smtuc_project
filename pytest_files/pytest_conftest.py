"""Histórico: NÃO é carregado automaticamente pelo pytest.

O pytest só descobre ficheiros chamados literalmente "conftest.py" (e apenas em diretórios
acima dos testes) - "pytest_conftest.py" nunca teve esse nome nem essa localização, por isso
nunca foi executado por nada. O mecanismo real que põe "src/" em sys.path é a opção nativa
`pythonpath = src` em pytest.ini (raiz do repo). Este ficheiro fica só como referência.
"""

from __future__ import annotations

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
