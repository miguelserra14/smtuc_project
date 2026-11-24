"""Carrega um script de `scripts/` como módulo (a pasta não é um pacote), para os testes.

O módulo fica em `sys.modules`: todos os testes da sessão veem o MESMO objeto, por isso um
`monkeypatch.setattr(modulo, ...)` num teste aplica-se ao código que o próprio script chama.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def load_script(name: str) -> ModuleType:
    """`load_script("regenerate")` -> o módulo de scripts/regenerate.py."""
    key = f"scripts_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module
