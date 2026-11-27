"""Todo o texto dos slides da apresentação (títulos, descrições, legendas, listas, etc.).

Consumido por `_default_presentation_tabs()` em `dashboard.py`, que por sua vez alimenta tanto
`presentation_dashboard.html` (mockups) como `feednplay_dashboard.html` (parede FeedNPlay) - os
dois partilham exatamente o mesmo conteúdo. Para mudar o texto que aparece em qualquer slide,
edita só este ficheiro; não é preciso mexer em `dashboard.py` nem nos templates.

Narrativa (decidida a 2026-11-26): abertura -> 1 fase 1 -> 1.5 linha 54 -> 2 Como Vou -> 3 fase 3
-> 4 sugestões -> fecho. Cada secção responde a UMA pergunta com UMA comparação entre degraus da
escada de cenários (`SCENARIO_LADDER`), que diferem numa só coisa - é isto que impede misturar as
três teses (fontes de redundância / impacto das medidas tomadas / redundância por resolver e onde
investir).

Campos comuns a todos os slides, além dos de cada kind:
- "section": id de `SECTIONS`; sem ele o slide é de abertura/fecho e não leva etiqueta de secção.
  Os slides de uma secção ficam seguidos e as secções na ordem de `SECTIONS`.
- "ladder": ids de `SCENARIO_LADDER` que o slide mostra ([X] = um cenário; [X, Y] = comparação
  X -> Y). Obrigatório em todos os slides de uma secção, exceto o divisor: cada slide diz que
  cenário está a mostrar.

Kinds novos desta narrativa:
- "section": divisor de secção (número, pergunta, tese e a escada com a comparação destacada; o
  texto vem de `SECTIONS`, o slide só diz qual);
- "ladder": a escada completa, na abertura;
- "pending": slide ainda por construir - "status" diz em que passo do plano entra, "shows" o que
  vai mostrar.

`dashboard._default_presentation_tabs()` resolve "section"/"ladder" em "section_meta"/
"ladder_meta" (o que os templates leem) e rebenta com ids desconhecidos.

Uma exceção ao "só texto": a chave "stats" dos slides de kind "overlap" não vive aqui - é
calculada em tempo real a partir do cache de métricas por linha do cenário do slide (ver
`load_overlap_stats` e `_OVERLAP_TAB_SCENARIO` em `dashboard.py`), porque são dados.
"""

from __future__ import annotations

from typing import Any

# Natureza de cada degrau: "oficial" (dados oficiais tal e qual), "contrafactual" (dados oficiais
# recombinados: uma rede que não existiu nesse dia) ou "planeado" (horário assumido - leva o selo
# "cenário planeado" em todos os slides que o mostram).
SCENARIO_LADDER: list[dict[str, Any]] = [
    {
        "id": "A",
        "tag": "A",
        "title": "Fase 1",
        "detail": "SMTUC Ep212 + Metro fase 1",
        "day": "11/05/2026",
        "nature": "oficial",
        "status": "existe",
    },
    {
        "id": "A_sem54",
        "tag": "A′",
        "title": "Fase 1 sem a 54",
        "detail": "SMTUC Ep212 sem a linha 54 + Metro fase 1",
        "day": "11/05/2026",
        "nature": "contrafactual",
        "status": "existe",
    },
    {
        "id": "B",
        "tag": "B",
        "title": "Metro novo, rede antiga",
        "detail": "SMTUC Ep212 + Metro fase 2",
        "day": "09/11/2026",
        "nature": "contrafactual",
        "status": "existe",
    },
    {
        "id": "C",
        "tag": "C",
        "title": "Como Vou",
        "detail": "SMTUC Ep225 + Metro fase 2",
        "day": "09/11/2026",
        "nature": "oficial",
        "status": "existe",
    },
    {
        "id": "D",
        "tag": "D",
        "title": "Fase 3",
        "detail": "SMTUC Ep225 + Metro fase 2 + Linha do Hospital",
        "day": "09/11/2026",
        "nature": "planeado",
        "status": "por construir",
    },
    {
        "id": "E",
        "tag": "E",
        "title": "Proposta",
        "detail": "Fase 3 com os autocarros redundantes redirecionados",
        "day": "09/11/2026",
        "nature": "planeado",
        "status": "por construir",
    },
]

# Uma entrada por secção, na ordem da apresentação. "compare" = os degraus que a secção compara
# (destacados no divisor); "context" = degraus mostrados só como contexto (destaque mais fraco).
SECTIONS: list[dict[str, Any]] = [
    {
        "id": "s1",
        "number": "1",
        "title": "Fase 1",
        "period": "set 2025 – set 2026",
        "thesis": "Maiores fontes de redundância",
        "question": "Onde é que o SMTUC e o Metrobus mais se sobrepõem, e quanto custa essa sobreposição?",
        "compare": ["A"],
        "context": [],
        "note": "Só diagnóstico, sem medidas. A fase 1 é representada por um dia útil de maio de 2026, com o horário SMTUC Ep212 (em vigor desde 09/03/2026): não há horários SMTUC oficiais de setembro de 2025 a março de 2026.",
    },
    {
        "id": "s1_5",
        "number": "1.5",
        "title": "Linha 54",
        "period": "desde 23/02/2026",
        "thesis": "Impacto das medidas tomadas",
        "question": "O que acrescentou a linha 54, criada para ligar Portagem e Portela ao metro?",
        "compare": ["A_sem54", "A"],
        "context": [],
        "note": "A 54 (Portagem – Portela, via Polo II) entrou em funcionamento a 23/02/2026, a meio da fase 1 (aviso SMTUC de 18/02/2026). Compara-se a mesma rede com e sem a 54.",
    },
    {
        "id": "s2",
        "number": "2",
        "title": "Como Vou",
        "period": "desde 10/09/2026",
        "thesis": "Impacto das medidas tomadas",
        "question": "O que mudou com a reorganização das linhas SMTUC, separado do que mudou por causa do metro da fase 2?",
        "compare": ["B", "C"],
        "context": ["A"],
        "note": "O metro da fase 2 e o Como Vou entraram no mesmo dia, 10/09/2026, por isso a rede real nunca separou os dois efeitos. O cenário B separa-os: A → B mede só o metro; B → C, com o mesmo metro e o mesmo dia, mede só o horário SMTUC.",
    },
    {
        "id": "s3",
        "number": "3",
        "title": "Fase 3",
        "period": "março 2027",
        "thesis": "Redundância por resolver",
        "question": "Que linhas SMTUC ficam redundantes quando o metro chegar ao hospital, e que redundâncias ficaram por resolver?",
        "compare": ["C", "D"],
        "context": [],
        "note": "A Linha do Hospital prolonga até ao Pediátrico a linha da fase 2 que acaba na República. As estações são as oficiais (mapa do Metro Mondego); o horário é assumido.",
    },
    {
        "id": "s4",
        "number": "4",
        "title": "Sugestões",
        "period": "a partir de março 2027",
        "thesis": "Onde investir",
        "question": "Para onde levar os autocarros que a fase 3 torna redundantes?",
        "compare": ["D", "E"],
        "context": [],
        "note": "A capacidade libertada na secção 3 é o orçamento. Cada proposta é medida com o mesmo painel de indicadores das secções anteriores.",
    },
]

PRESENTATION_TABS: list[dict[str, Any]] = [
    # =====================================================================================
    # Abertura
    # =====================================================================================
    {
        "id": "intro",
        "label": "Introdução",
        "kind": "hero",
        "description": "Do primeiro ano de Metrobus à fase 3.",
        "title": "SMTUC: A caminho da complementaridade",
        "subtitle": "O que o Metrobus mudou em Coimbra, o que o SMTUC já fez e o que deve preparar para a fase 3",
        "lead": "Um ano de Metrobus, duas respostas do SMTUC (a linha 54 e o Como Vou) e a Linha do Hospital a chegar em março de 2027. A análise separa cada passo para medir o efeito de cada um.",
        "highlights": [
            "1 · Fase 1: onde está a redundância",
            "1.5 · Linha 54: o que acrescentou",
            "2 · Como Vou: o que mudou na rede",
            "3 · Fase 3: o que fica redundante com o hospital",
            "4 · Sugestões: para onde levar os autocarros",
        ],
    },
    {
        "id": "metodologia",
        "label": "Metodologia",
        "kind": "methodology",
        "description": "Como os dados de SMTUC, Metrobus e população entram no mesmo fluxo de análise.",
        "note": "Cruzam-se os horários oficiais do SMTUC e do Metro Mondego com a população (Censos 2021) e com os polos de emprego e locais concorridos.",
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
    {
        "id": "cenarios",
        "label": "Cenários",
        "kind": "ladder",
        "description": "Cada secção compara dois cenários que diferem numa só coisa.",
        "note": "Comparar a rede antes e depois de setembro de 2026 mistura duas mudanças: o metro da fase 2 e o Como Vou. A escada separa-as: cada degrau muda uma coisa, cada secção mede um degrau e todas usam o mesmo painel de indicadores (overlap espacial e temporal, acessibilidade, população sem oferta, esperas da 54).",
    },
    # =====================================================================================
    # Secção 1: fase 1 (cenário A) - maiores fontes de redundância
    # =====================================================================================
    {"id": "secao_1", "label": "1 · Fase 1", "kind": "section", "section": "s1"},
    {
        "id": "subservico",
        "label": "População e subserviço",
        "kind": "three-up",
        "section": "s1",
        "ladder": ["A"],
        "description": "Onde vive a população e onde a oferta é mais fraca face a ela.",
        "note": "O índice de subserviço relaciona a população de cada subsecção com a oferta a menos de 500 m. É também o ponto de partida da secção 4: onde falta serviço.",
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
    # "stats" é anexado em tempo real (ver dashboard.py).
    {
        "id": "overlap",
        "label": "Overlap na fase 1",
        "kind": "overlap",
        "section": "s1",
        "ladder": ["A"],
        "description": "Onde a rede SMTUC e o Metrobus se sobrepõem, no espaço e no tempo.",
        "note": "Uma paragem SMTUC está em overlap espacial se ficar a até 3 minutos a pé de uma estação; em overlap temporal se, nessa paragem, passar um metro até 5 minutos antes ou depois do autocarro.",
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
    # N2: páginas de regenerate_redundancy_html (viagem a viagem; números só dos dados).
    {
        "id": "s1_ranking",
        "label": "Maiores fontes de redundância",
        "kind": "scenario-compare",
        "section": "s1",
        "ladder": ["A"],
        "description": "As linhas e os troços do metro onde mais autocarros fazem o mesmo percurso que o metro, e o que isso custa.",
        "note": "Conta-se cada viagem do dia útil, com as suas paragens: um autocarro que passa 60 vezes no mesmo troço pesa 60 vezes. O ano é uma estimativa pela semana-tipo do horário; o CO₂ usa a frota SMTUC repartida por igual pelas linhas. Esta lista é a referência a que as secções 2 e 3 voltam.",
        "table": {
            "title": "Redundância autocarro × metro na fase 1",
            "src": "redundancia/ranking.html",
            "caption": "Autocarros·km, horas e CO₂ a par do metro, por linha e por troço do metro.",
        },
    },
    # =====================================================================================
    # Secção 1.5: linha 54 (A′ -> A) - impacto das medidas tomadas
    # =====================================================================================
    {"id": "secao_1_5", "label": "1.5 · Linha 54", "kind": "section", "section": "s1_5"},
    {
        "id": "s1_5_contributo",
        "label": "O que a 54 acrescenta",
        "kind": "scenario-compare",
        "section": "s1_5",
        "ladder": ["A_sem54", "A"],
        "description": "A mesma rede da fase 1, com e sem a linha 54: só muda essa linha.",
        "note": "Não há horário oficial sem a 54 (começou antes do horário de março), por isso a rede sem ela é o mesmo horário com a linha retirada. O que a 54 traz não está na cobertura nem no estádio: está nas viagens a partir das estações do metro. As isócronas dos nós são a média das partidas da ponta da manhã, para não dependerem de uma hora que calhe ou não com a 54.",
        "table": {
            "title": "Indicadores: fase 1 sem a 54 → fase 1",
            "src": "comparacao/antes_sem54_vs_antes.html",
            "caption": "Overlap, população sem oferta, isócronas do estádio e das estações de Portagem e da Portela, redundância.",
        },
    },
    # "scenarios" (opcional, por coluna): botões que trocam o iframe entre cenários; o primeiro é
    # o que abre (= "current.src"). "optimized" (opcional): cartão por baixo do iframe, com o
    # título "optimized_title" (por omissão "Versão otimizada").
    {
        "id": "integracao",
        "label": "Integração da 54 com o metro",
        "kind": "comparison",
        "section": "s1_5",
        "ladder": ["A"],
        "description": "Esperas no transbordo entre a 54 e o metro, em Portagem e na Portela, na fase 1.",
        "note": "As esperas incluem o tempo a pé entre a paragem e a estação. Mostra-se o horário em vigor na fase 1; as propostas de melhoria ficam para a secção 4.",
        "columns": [
            {
                "title": "Portagem",
                "subtitle": "Linha 54 + 38",
                "current": {
                    "title": "Fase 1",
                    "src": "integration/portagem/l54_38_all.html",
                    "caption": "Fase 1, sentido Portela → Portagem.",
                },
            },
            {
                "title": "Portela",
                "subtitle": "Linha 54",
                "current": {
                    "title": "Fase 1",
                    "src": "integration/portela/l54_all.html",
                    "caption": "Fase 1, sentido Portagem → Portela.",
                },
            },
        ],
    },
    # =====================================================================================
    # Secção 2: Como Vou (B -> C, com A -> B como contexto) - impacto das medidas tomadas
    # =====================================================================================
    {"id": "secao_2", "label": "2 · Como Vou", "kind": "section", "section": "s2"},
    # Páginas de comparação por pares (regenerate_comparison_html, config.COMPARISON_PAIRS): A -> B
    # é só o metro, B -> C só o horário SMTUC. A comparação A -> C (os dois juntos) fica só no
    # separador do dashboard master.
    {
        "id": "efeito_metro",
        "label": "Efeito do metro",
        "kind": "scenario-compare",
        "section": "s2",
        "ladder": ["A", "B"],
        "description": "O que mudou só por causa do metro da fase 2: o horário SMTUC é o mesmo nos dois lados.",
        "note": "Contexto da secção. Com a fase 2 o metro passa a ir à Baixa, a Coimbra B e à República e a correr ao lado de muito mais rede SMTUC - antes de o SMTUC mudar uma única linha.",
        "table": {
            "title": "Indicadores: fase 1 → metro da fase 2 com o horário SMTUC de março",
            "src": "comparacao/antes_vs_fase2_ep212.html",
            "caption": "Overlap, acessibilidade a partir do estádio, população sem oferta e esperas da linha 54.",
        },
        "iframes": [
            {
                "title": "Linhas sobrepostas: fase 1",
                "src": "overlap/overlap_lines_map.html",
                "caption": "Fase 1 (11/05/2026).",
            },
            {
                "title": "Linhas sobrepostas: metro da fase 2, SMTUC Ep212",
                "src": "overlap/overlap_lines_map_fase2_ep212.html",
                "caption": "As mesmas linhas SMTUC, com o metro da fase 2 (09/11/2026).",
            },
        ],
    },
    {
        "id": "s2_rede",
        "label": "O que mudou na rede",
        "kind": "scenario-compare",
        "section": "s2",
        "ladder": ["B", "C"],
        "description": "As linhas SMTUC antes e depois do Como Vou, com o mesmo metro e o mesmo dia.",
        "note": "Linha a linha: cortadas, novas, com percurso alterado ou só com ajustes de paragens. O horário de partida é o de março, por isso as linhas reestruturadas em junho (5, 5T, 5F, 33 e 33R) aparecem assinaladas como anteriores ao Como Vou.",
        "table": {
            "title": "Diferenças de rede, linha a linha",
            "src": "comparacao/rede_fase2_ep212_vs_fase2.html",
            "caption": "Viagens no dia, paragens mantidas / deslocadas / retiradas / novas e extensão a par do metro de cada linha.",
        },
    },
    {
        "id": "como_vou",
        "label": "Efeito do Como Vou",
        "kind": "scenario-compare",
        "section": "s2",
        "ladder": ["B", "C"],
        "description": "O que mudou só por causa do horário SMTUC: o metro e o dia são os mesmos nos dois lados.",
        "note": "Mesmo metro, mesmo dia: a diferença é toda do horário SMTUC - o Como Vou e, antes dele, a reestruturação de junho das linhas 5, 5T, 5F, 33 e 33R.",
        "table": {
            "title": "Indicadores: metro da fase 2 com o horário de março → Como Vou",
            "src": "comparacao/fase2_ep212_vs_fase2.html",
            "caption": "Overlap, acessibilidade a partir do estádio, população sem oferta e esperas da linha 54.",
        },
        "iframes": [
            {
                "title": "Linhas sobrepostas: SMTUC Ep212",
                "src": "overlap/overlap_lines_map_fase2_ep212.html",
                "caption": "Horário SMTUC de março, com o metro da fase 2 (09/11/2026).",
            },
            {
                "title": "Linhas sobrepostas: Como Vou",
                "src": "overlap/overlap_lines_map_fase2.html",
                "caption": "Rede atual (09/11/2026).",
            },
        ],
    },
    # "stats" também anexado em tempo real, a partir do cache do cenário fase2 (ver
    # _OVERLAP_TAB_SCENARIO em dashboard.py).
    {
        "id": "overlap_fase2",
        "label": "Overlap com o Como Vou",
        "kind": "overlap",
        "section": "s2",
        "ladder": ["C"],
        "description": "O overlap e as isócronas na rede atual: metro da fase 2 e horário SMTUC Ep225.",
        "note": "Dados oficiais: Metro Mondego (NeTEx de 11/11/2026; fase 2 em operação desde 10/09/2026) e SMTUC (horário Ep225 do Como Vou, GTFS do Município), num dia útil de referência, 09/11/2026. Dados: AGIT / dados.gov.pt (CC BY 4.0).",
        "iframes": [
            {
                "title": "Reachability e overlap temporal (rede atual)",
                "src": "overlap/overlap_reachability_now_fase2.html",
                "caption": "A mesma leitura do slide da fase 1, na rede atual.",
            },
            {
                "title": "Mapa de linhas sobrepostas (rede atual)",
                "src": "overlap/overlap_lines_map_fase2.html",
                "caption": "Linhas SMTUC com maior e menor overlap face à rede atual.",
            },
        ],
    },
    {
        "id": "s2_redundancias",
        "label": "As maiores redundâncias depois do Como Vou",
        "kind": "scenario-compare",
        "section": "s2",
        "ladder": ["B", "C"],
        "description": "O que o Como Vou fez às linhas que mais corriam a par do metro, e quais ficam no topo depois dele.",
        "note": "Mesmo metro, mesmo dia: a diferença é só do horário SMTUC. Cada linha leva o estado das diferenças de rede e o aviso SMTUC. As que continuam no topo do ranking da rede atual são a redundância por resolver que passa para a secção 3.",
        "table": {
            "title": "As linhas mais redundantes antes do Como Vou, e depois",
            "src": "redundancia/medidas_fase2_ep212_vs_fase2.html",
            "caption": "Autocarros·km por dia útil a par do metro, linha a linha, com o que mudou em cada uma.",
        },
        "iframes": [
            {
                "title": "Ranking da rede atual",
                "src": "redundancia/ranking_fase2.html",
                "caption": "Como Vou (09/11/2026): as linhas e os troços do metro com mais redundância.",
            },
        ],
    },
    {
        "id": "integracao_fase2",
        "label": "A 54 depois do Como Vou",
        "kind": "comparison",
        "section": "s2",
        "ladder": ["B", "C"],
        "description": "Esperas no transbordo entre a 54 e o metro, na rede atual.",
        "note": "O mesmo cálculo da secção 1.5, na rede atual; o botão mostra o mesmo metro com o horário SMTUC de março, para separar o que mudou com o Como Vou. Na Portagem aparece também, só como informação, o sentido norte (para Coimbra B ou República), que só existe com o metro da fase 2.",
        "columns": [
            {
                "title": "Portagem",
                "subtitle": "Linha 54 + 38",
                "current": {
                    "title": "Rede atual",
                    "src": "integration/portagem_fase2/l54_38_all.html",
                    "caption": "Sentido Portela → Portagem.",
                },
                "scenarios": [
                    {"label": "Como Vou (C)", "src": "integration/portagem_fase2/l54_38_all.html"},
                    {"label": "SMTUC de março (B)", "src": "integration/portagem_fase2_ep212/l54_38_all.html"},
                ],
            },
            {
                "title": "Portela",
                "subtitle": "Linha 54",
                "current": {
                    "title": "Rede atual",
                    "src": "integration/portela_fase2/l54_all.html",
                    "caption": "Sentido Portagem → Portela.",
                },
                "scenarios": [
                    {"label": "Como Vou (C)", "src": "integration/portela_fase2/l54_all.html"},
                    {"label": "SMTUC de março (B)", "src": "integration/portela_fase2_ep212/l54_all.html"},
                ],
            },
        ],
    },
    # =====================================================================================
    # Secção 3: fase 3 (C -> D, planeado) - redundância por resolver
    # =====================================================================================
    {"id": "secao_3", "label": "3 · Fase 3", "kind": "section", "section": "s3"},
    {
        "id": "s3_linha",
        "label": "A Linha do Hospital",
        "kind": "pending",
        "section": "s3",
        "ladder": ["C", "D"],
        "status": "Por construir · N3",
        "description": "Cinco estações novas entre a República e o Pediátrico.",
        "shows": [
            "Estações oficiais do Metro Mondego: Sereia, Celas, Polo Ciências da Saúde, Hospitais (HUC) e Pediátrico.",
            "Horário assumido: prolongamento da linha que acaba na República, com a mesma frequência; tempos entre estações calculados pela distância e pela velocidade média do troço Aeminium – República.",
            "Acessibilidade a partir dos Hospitais (HUC), antes e depois da fase 3.",
        ],
    },
    {
        "id": "s3_redundancia",
        "label": "Redundância por resolver",
        "kind": "pending",
        "section": "s3",
        "ladder": ["C", "D"],
        "status": "Por construir · N3",
        "description": "O que o Como Vou deixou ficar e o que a Linha do Hospital acrescenta.",
        "shows": [
            "Redundância que já existe na rede atual e que o Como Vou não resolveu.",
            "Linhas SMTUC que passam a ter overlap com a Linha do Hospital, com a mesma regra das secções anteriores.",
            "Overlap temporal com duas frequências da Linha do Hospital, porque o horário é assumido.",
        ],
    },
    {
        "id": "s3_capacidade",
        "label": "Capacidade libertada",
        "kind": "pending",
        "section": "s3",
        "ladder": ["C", "D"],
        "status": "Por construir · N3",
        "description": "Quantos autocarros a fase 3 permite tirar dos corredores redundantes.",
        "shows": [
            "Autocarros·hora por dia nas passagens redundantes, linha a linha.",
            "Total disponível para redirecionar: é o orçamento da secção 4.",
        ],
    },
    # =====================================================================================
    # Secção 4: sugestões (D -> E, planeado) - onde investir
    # =====================================================================================
    {"id": "secao_4", "label": "4 · Sugestões", "kind": "section", "section": "s4"},
    {
        "id": "s4_onde",
        "label": "Onde investir",
        "kind": "pending",
        "section": "s4",
        "ladder": ["D"],
        "status": "Por construir · N4",
        "description": "Onde falta serviço quando a Linha do Hospital estiver a funcionar.",
        "shows": [
            "Subsecções sem oferta ou com índice de subserviço alto, recalculado com a rede da fase 3 (hoje o índice só existe para a fase 1).",
            "Polos de emprego e locais concorridos longe da rede.",
            "Zonas onde as isócronas mais pioram.",
        ],
    },
    {
        "id": "s4_54",
        "label": "54: o primeiro autocarro a redirecionar",
        "kind": "comparison",
        "section": "s4",
        "ladder": ["C"],
        "description": "As propostas para a 54, medidas na rede atual.",
        "note": "Cada página mostra três horários: o atual, o otimizado (as mesmas viagens, deslocadas) e o melhorado (um 2.º autocarro na linha). O 2.º autocarro pode ser um dos que a fase 3 liberta.",
        "columns": [
            {
                "title": "Portagem",
                "subtitle": "Linha 54 + 38",
                "current": {
                    "title": "Rede atual",
                    "src": "integration/portagem_fase2/l54_38_all.html",
                    "caption": "Atual, otimizado e melhorado, sentido Portela → Portagem.",
                },
                "optimized_title": "Propostas",
                "optimized": [
                    "Melhorado: o 2.º autocarro é a única variante que reduz muito a espera de quem sai do metro.",
                    "Otimizado: deslocar o horário dá um ganho pequeno.",
                    "O 2.º autocarro pode vir dos que a fase 3 liberta.",
                ],
            },
            {
                "title": "Portela",
                "subtitle": "Linha 54",
                "current": {
                    "title": "Rede atual",
                    "src": "integration/portela_fase2/l54_all.html",
                    "caption": "Atual, otimizado e melhorado, sentido Portagem → Portela.",
                },
                "optimized_title": "Propostas",
                "optimized": [
                    "Aqui as duas propostas mudam pouco as esperas.",
                    "O ganho da 54 melhorada concentra-se na Portagem.",
                ],
            },
        ],
    },
    {
        "id": "s4_proposta",
        "label": "Proposta",
        "kind": "pending",
        "section": "s4",
        "ladder": ["D", "E"],
        "status": "Por construir · N4",
        "description": "A rede com os autocarros redirecionados, medida com o mesmo painel.",
        "shows": [
            "Que linhas encurtar ou cortar, e para onde vai cada autocarro.",
            "Painel de indicadores antes e depois da proposta: overlap, acessibilidade, população sem oferta, esperas da 54.",
            "Duas ou três versões, da mais conservadora à mais ambiciosa.",
        ],
    },
    # =====================================================================================
    # Fecho
    # =====================================================================================
    {
        "id": "conclusao",
        "label": "Conclusões",
        "kind": "closing",
        "description": "O que a apresentação quer deixar claro no final.",
        "headline": "Cada fase do metro pede uma resposta do SMTUC, e a da fase 3 pode ser preparada já.",
        "lead": "A fase 1 criou redundância; a 54 e o Como Vou foram as primeiras respostas. A Linha do Hospital vai libertar mais autocarros, e decidir para onde vão antes de março de 2027 é o que transforma redundância em serviço novo.",
        "points": [
            "Separar cada mudança permite medir o efeito de cada medida, em vez de as misturar.",
            "Os autocarros que a fase 3 torna redundantes devem ir para onde falta serviço, não ficar a competir com o metro.",
            "Março de 2027 é a próxima oportunidade: a proposta pode ser preparada e medida antes.",
        ],
    },
    {
        "id": "agradecimentos",
        "label": "Agradecimentos",
        "kind": "thanks",
        "title": "Obrigado",
        "subtitle": "Miguel Serra, DEI-FCTUC, 2026",
        "contacts": ["miguel.serra@student.dei.uc.pt"],
    },
]
