"""Todo o texto dos slides da apresentação (títulos, descrições, legendas, listas, etc.).

Consumido por `_default_presentation_tabs()` em `dashboard.py`, que por sua vez alimenta tanto
`presentation_dashboard.html` (mockups) como `feednplay_dashboard.html` (parede FeedNPlay) - os
dois partilham exatamente o mesmo conteúdo. Para mudar o texto que aparece em qualquer slide,
edita só este ficheiro; não é preciso mexer em `dashboard.py` nem nos templates.

Uma exceção: a chave "stats" do slide "overlap" não vive aqui - é calculada em tempo real a
partir de `outputs/overlap/line_metrics_db.csv` (ver `_load_overlap_stats` em `dashboard.py`) e
só é anexada ao voo, porque são dados, não texto editável à mão.
"""

from __future__ import annotations

from typing import Any

PRESENTATION_TABS: list[dict[str, Any]] = [
    # --- Slide 1: Introdução ---------------------------------------------------------------
    {
        "id": "intro",
        "label": "Introdução",
        "kind": "hero",
        "eyebrow": "Apresentação final",
        "title": "SMTUC: A caminho da complementaridade",
        "subtitle": "Como o Metrobus mudou a mobilidade em Coimbra e o que o SMTUC pode adaptar já",
        "lead": "As obras ainda não estão acabadas, mas o estudo já está encaminhado e já há bastante que pode ser feito com impacto tangível.",
        "chips": ["Metrobus", "SMTUC", "Coimbra", "Urgência em setembro"],
        "highlights": [
            "Mudança estrutural da mobilidade",
            "Resposta já possível com os dados que existem",
            "Janela de oportunidade para a entrada de caloiros",
        ],
    },
    # --- Slide 2: Metodologia ----------------------------------------------------------------
    {
        "id": "metodologia",
        "label": "Metodologia",
        "kind": "methodology",
        "description": "Como os dados de SMTUC, Metrobus e população entram no mesmo fluxo de análise.",
        "note": "Cruza-se oferta de transporte, população e contexto urbano para perceber onde a rede mudou e onde o SMTUC pode ajustar-se já.",
        "steps": ["Recolha", "Limpeza", "Métricas", "Visualização"],
        "source_tags": ["SMTUC", "Metrobus", "População", "Locais de trabalho", "Locais de convívio"],
        "iframes": [
            {
                "title": "Heatmap de população",
                "src": "population/bgri.html?show=heatmap",
                "caption": "Distribuição da população por Coimbra.",
            },
            {
                "title": "Índice de subserviço",
                "src": "population/bgri.html?show=choropleth",
                "caption": "Primeira leitura da pressão de serviço.",
            },
        ],
    },
    # --- Slide 3: Subserviço + Isócronas -----------------------------------------------------
    {
        "id": "subservico",
        "label": "Subserviço + Isócronas",
        "kind": "three-up",
        "description": "A métrica de subserviço e a leitura territorial das isócronas.",
        "note": "A taxa de subserviço relaciona população com oferta e ajuda a perceber onde o serviço está mais pressionado. As isócronas devem passar a incluir também locais de trabalho e convívio.",
        "iframes": [
            {
                "title": "Mapa global de subserviço",
                "src": "population/bgri.html?show=choropleth",
                "caption": "Índice de subserviço em Coimbra.",
            },
            {
                "title": "Subserviço a 2 km",
                "src": "population/bgri.html?show=stadium",
                "caption": "Leitura de detalhe da pressão territorial.",
            },
            {
                "title": "Isócronas dinâmicas",
                "src": "overlap/overlap_reachability_now.html",
                "caption": "Cobertura, acessibilidade e overlap temporal.",
            },
        ],
    },
    # --- Slide 4: Overlap ("stats" é anexado em tempo real, ver dashboard.py) ----------------
    {
        "id": "overlap",
        "label": "Overlap",
        "kind": "overlap",
        "description": "Onde a rede SMTUC e o Metrobus mais se sobrepõem.",
        "note": "Este bloco mostra onde existe redundância espacial e temporal. A leitura deve ser visual, direta e rápida.",
        "iframes": [
            {
                "title": "Reachability e overlap temporal",
                "src": "overlap/overlap_reachability_now.html",
                "caption": "Mapa principal com cobertura e temporalidade.",
            },
            {
                "title": "Mapa de linhas sobrepostas",
                "src": "overlap/overlap_lines_map.html",
                "caption": "Linhas com maior e menor overlap.",
            },
        ],
    },
    # --- Slide 4b: Overlap + Isócronas com a fase 2 ("stats" também anexado em tempo real, mas a
    # partir de um cache próprio - ver _OVERLAP_TAB_METRICS_PATH em dashboard.py) --------------
    {
        "id": "overlap_fase2",
        "label": "Overlap (Fase 2)",
        "kind": "overlap",
        "description": "O mesmo overlap e isócronas, mas já com a extensão da fase 2 do Metrobus (Aeminium + ramais Coimbra B/República, inauguração prevista em setembro).",
        "note": "Dados provisórios (data/metrobus_fase2, ainda não é o feed oficial) - serve para antecipar como o overlap e a cobertura mudam quando a fase 2 abrir, enquanto o resto da apresentação usa os dados atuais (pré-fase 2).",
        "iframes": [
            {
                "title": "Reachability e overlap temporal (fase 2)",
                "src": "overlap/overlap_reachability_now_fase2.html",
                "caption": "Mesma leitura do slide anterior, recalculada com a extensão da fase 2.",
            },
            {
                "title": "Mapa de linhas sobrepostas (fase 2)",
                "src": "overlap/overlap_lines_map_fase2.html",
                "caption": "Linhas SMTUC com maior e menor overlap face à rede já com a fase 2.",
            },
        ],
    },
    # --- Slide 5: Integração (Portagem/Portela) ----------------------------------------------
    {
        "id": "integracao",
        "label": "Integração",
        "kind": "comparison",
        "description": "Comparação Portagem e Portela com a linha 54.",
        "note": "A versão otimizada ainda é um objetivo do projeto, por isso o foco aqui é mostrar o estado atual e a direção de melhoria: menos espera, melhor coordenação e horários mais úteis.",
        "columns": [
            {
                "title": "Portagem",
                "subtitle": "Linha 54 + 38",
                "current": {
                    "title": "Estado atual",
                    "src": "integration/portagem/l54_38_all.html",
                    "caption": "Integração atual no sentido Portela → Portagem.",
                },
                "optimized": [
                    "Reduzir tempos de espera no transbordo",
                    "Ajustar horários ao Metrobus",
                    "Evidenciar a correspondência entre modos",
                ],
            },
            {
                "title": "Portela",
                "subtitle": "Linha 54",
                "current": {
                    "title": "Estado atual",
                    "src": "integration/portela/l54_all.html",
                    "caption": "Integração atual no sentido Portagem → Portela.",
                },
                "optimized": [
                    "Simplificar o percurso de ligação",
                    "Reorganizar a cadência horária",
                    "Mostrar melhor o ganho tangível para o utilizador",
                ],
            },
        ],
    },
    # --- Slide 6: Conclusões -----------------------------------------------------------------
    {
        "id": "conclusao",
        "label": "Conclusões",
        "kind": "closing",
        "description": "O que a apresentação quer deixar claro no final.",
        "headline": "O Metrobus alterou a mobilidade em Coimbra e o SMTUC precisa de se adaptar.",
        "points": [
            "Há já impacto tangível que pode ser mostrado antes de as obras terminarem.",
            "O reforço do SMTUC deve responder ao novo contexto, não competir com ele.",
            "Setembro é a oportunidade para demonstrar a nova era da mobilidade em Coimbra.",
        ],
    },
    # --- Slide 7: Agradecimentos -------------------------------------------------------------
    {
        "id": "agradecimentos",
        "label": "Agradecimentos",
        "kind": "thanks",
        "description": "Fecho minimalista e limpo para o ecrã final.",
        "title": "Obrigado",
        "subtitle": "Nomes, instituição e contactos",
        "contacts": ["Nome 1", "Nome 2", "Curso / Unidade curricular", "Setembro 2026"],
    },
]
