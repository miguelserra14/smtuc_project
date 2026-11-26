"""Modelo de src/config_local.py - valores locais/privados que NÃO vão para o git.

Copia este ficheiro para `src/config_local.py` (já está no .gitignore) e preenche. Só podes
sobrepor constantes que já existam em src/config.py; nomes desconhecidos são avisados e ignorados.
Os valores carregados ficam listados em `config.LOCAL_OVERRIDES`.
"""

# Coordenadas pessoais (lat, lon) usadas pelos testes de percurso em test_overlap.py. Sem este
# ficheiro, config.py usa pontos públicos (Estação Coimbra-B e Polo I).
# HOME_COORD = (40.0, -8.0)
# WORK_COORD = (40.0, -8.0)

# Chave CARTO para o mapa base Positron (gratuita, uso não comercial: https://carto.com/basemaps/apikey).
# Sem ela os mapas usam o Esri Light Gray. Depois de a pôr: python scripts/regenerate.py
# BASEMAP_CARTO_KEY = "a-tua-chave"
