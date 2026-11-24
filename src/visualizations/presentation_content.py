"""Todo o texto dos slides da apresentação (títulos, descrições, legendas, listas, etc.).

Consumido por `_default_presentation_tabs()` em `dashboard.py`, que por sua vez alimenta tanto
`presentation_dashboard.html` (mockups) como `feednplay_dashboard.html` (parede FeedNPlay) - os
dois partilham exatamente o mesmo conteúdo. Para mudar o texto que aparece em qualquer slide,
edita só este ficheiro; não é preciso mexer em `dashboard.py` nem nos templates.

Uma exceção: a chave "stats" do slide "overlap" não vive aqui - é calculada em tempo real a
partir de `outputs/overlap/line_metrics_db.csv` (ver `load_overlap_stats` em `dashboard.py`) e
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
        "title": "SMTUC: A caminho da complementaridade",
        "subtitle": "Como o Metrobus mudou a mobilidade em Coimbra e o que o SMTUC pode adaptar já",
        "lead": "As obras ainda não estão acabadas, mas o estudo já está encaminhado e já há bastante que pode ser feito com impacto tangível.",
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
    # partir de um cache próprio - ver _OVERLAP_TAB_SCENARIO em dashboard.py) --------------
    {
        "id": "overlap_fase2",
        "label": "Overlap (Fase 2)",
        "kind": "overlap",
        "description": "O mesmo overlap e isócronas, mas já com a extensão da fase 2 do Metrobus (Aeminium + ramais Coimbra B/República, inauguração prevista em setembro).",
        "note": "Dados oficiais: Metro Mondego (NeTEx de 11/11/2026; fase 2 em operação desde 10/09/2026) e SMTUC (horário Ep225, desde 18/09/2026), num dia útil de referência a 09/11/2026 - o resto da apresentação usa a rede antes da fase 2. Dados: AGIT / dados.gov.pt (CC BY 4.0).",
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
    # --- Slide 4c: Antes vs Fase 2 (D2.5) ------------------------------------------------------
    # "table" é a página gerada por regenerate_comparison_html (números dos snapshots de
    # scripts/snapshot_metrics.py, os mesmos de reports/metricas/); "iframes" ficam lado a lado.
    {
        "id": "antes_vs_fase2",
        "label": "Antes vs Fase 2",
        "kind": "scenario-compare",
        "description": "O que mudou entre a rede antes da fase 2 e a rede em vigor, num dia útil de cada cenário.",
        "note": "Entre os dois cenários mudam o metro e o horário do SMTUC (Ep212 → Ep225). Com a fase 2 há muito mais rede SMTUC a par do metro; a 54 continua a passar de 40 em 40 min e só um 2.º autocarro corta a espera de quem sai do metro em Portagem.",
        "table": {
            "title": "Indicadores lado a lado",
            "src": "comparacao/antes_vs_fase2.html",
            "caption": "Overlap, acessibilidade a partir do estádio, população sem oferta e esperas da linha 54.",
        },
        "iframes": [
            {
                "title": "Linhas sobrepostas: antes",
                "src": "overlap/overlap_lines_map.html",
                "caption": "Rede antes da fase 2 (11/05/2026).",
            },
            {
                "title": "Linhas sobrepostas: fase 2",
                "src": "overlap/overlap_lines_map_fase2.html",
                "caption": "Rede com a fase 2 (09/11/2026).",
            },
        ],
    },
    # --- Slide 5: Integração (Portagem/Portela) ----------------------------------------------
    # "scenarios" (opcional, por coluna): botões que trocam o iframe entre cenários; o primeiro é
    # o que abre (= "current.src").
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
                "scenarios": [
                    {"label": "Antes", "src": "integration/portagem/l54_38_all.html"},
                    {"label": "Fase 2", "src": "integration/portagem_fase2/l54_38_all.html"},
                ],
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
                "scenarios": [
                    {"label": "Antes", "src": "integration/portela/l54_all.html"},
                    {"label": "Fase 2", "src": "integration/portela_fase2/l54_all.html"},
                ],
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
        "title": "Obrigado",
        "subtitle": "Miguel Serra, DEI-FCTUC, 2026",
        "contacts": ["miguel.serra@student.dei.uc.pt"],
    },
]
