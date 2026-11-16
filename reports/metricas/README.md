# Números de controlo: antes e depois de cada troca de dados

Gerados por `scripts/snapshot_metrics.py` e `scripts/search_phase_shift.py`. Os ficheiros não se substituem: cada troca de dados acrescenta um snapshot novo e o diff contra o anterior.

| Ficheiro | O que é |
|---|---|
| `sintetico.csv` | **Antes** (D0.2, 2026-11-16): SMTUC Ep212 + Metro **sintético** fase 1 |
| `sintetico_fase2.csv` | Metro sintético da fase 2 com o SMTUC Ep212 a 2026-05-11 (slide da fase 2 até à D2.7; sem esperas da 54) |
| `oficial_fase2.csv` | **Fase 2 oficial** (D2.7): SMTUC Ep225 + Metro NeTEx AGIT a 2026-11-09, cenário `fase2`, com as esperas da 54 |
| `diff_sintetico_fase2_vs_oficial_fase2.csv` | Diferenças do slide da fase 2 ao trocar o sintético pelo oficial |
| `oficial_fase1.csv` | **Depois** (D1 passo 4, 2026-11-16): SMTUC Ep212 + **GTFS oficial** do Metro (fase 1), ainda com os desvios da 54 do sintético (−11 / −10) e o critério de busca antigo |
| `diff_sintetico_vs_oficial_fase1.csv` | Todas as diferenças entre os dois (305 números) |
| `oficial_fase1_desvios.csv` | O mesmo com os desvios **decididos** (−10 / 0) e o critério novo |
| `oficial_fase1_d24.csv` | D2.4 (mesmos dados): a 38 conta em Portagem com origem própria (Santa Clara) e as paragens do nó incluem as que ficam a ≤ 250 m. É a linha de base atual (`test_snapshot_metrics.py`) |
| `diff_oficial_fase1_desvios_vs_d24.csv` | Diferenças da D2.4 (19 números: só esperas em Portagem e a busca de fase) |
| `busca_fase_54_oficial_fase1_com_38.csv` | Busca de desvio no cenário `antes` com a 38: daria 0 / −10 |
| `busca_fase_54_fase2_oficial.csv` | Busca de desvio na rede da **fase 2 oficial** (cenário `fase2_oficial`): −10 / 0, os valores adotados |
| `diff_oficial_fase1_vs_desvios.csv` | Diferenças da decisão dos desvios (26 números: só as propostas e a busca) |
| `busca_fase_54_sintetico.csv` | Busca de desvio da 54 no sintético, com transbordo a pé (passo 0.2: −11 / −9) |
| `busca_fase_54_sintetico_sem_transbordo.csv` | Idem com a regra antiga (transbordo 0): reproduz os −16 / −8 originais |
| `busca_fase_54_oficial_fase1.csv` | Busca de desvio da 54 com o Metro oficial, critério antigo (−20..+20 nas duas propostas) |
| `busca_fase_54_oficial_fase1_alargada_40.csv` | Idem de −40 a +40: mostra os ótimos espúrios fora de meio ciclo (−28 / +28) |
| `busca_fase_54_oficial_fase1_meio_ciclo.csv` | Busca com o critério **atual** (meio ciclo; sem regressões e menor espera total): −10 / 0 |

Para reproduzir: `python scripts/snapshot_metrics.py diff reports/metricas/sintetico.csv reports/metricas/oficial_fase1.csv`.

## Metro sintético → GTFS oficial (fase 1)

Só mudou o metro. SMTUC, BGRI, dia de referência (2026-05-11, 08:20) e parâmetros são iguais.

Verificação independente no ficheiro bruto oficial: 291 viagens por dia útil; 62 chegadas a Portagem vindas de Portela e 57 a Portela vindas de Portagem, iguais aos PDFs; 142 partidas de Portagem sentido Vale das Flores, com intervalo mediano de 7 min.

**Esperas da 54 no horário atual** (mediana em min; cobertura = % com espera ≤ 10 min):

| Sentido | Sintético | Oficial |
|---|---|---|
| Portagem metro→autocarro | 27 (24 %) | 26,0 (21 %) |
| Portagem autocarro→metro | 12 (43 %) | **2 (90 %)** |
| Portela metro→autocarro | 16 (23 %) | 15,3 (21 %) |
| Portela autocarro→metro | 14 (43 %) | **7,7 (67 %)** |

- **Autocarro→metro melhora muito** porque o sintético não tinha os vaivéns urbanos Portagem ↔ Vale das Flores (172 por dia útil no oficial, contando os dois sentidos).
- **Metro→autocarro quase não muda**: é a 54 (de 40 em 40 min) que limita a espera.
- **Transbordos a pé**: Portagem 1,40 min (32 m; antes 1,28) e Portela 2,42 min (113 m; antes 2,39).

**Overlap**:
- Temporal: 58,9 % → **92,3 %** dos candidatos espaciais (8255 → 14 115 ocorrências), por haver muito mais metros.
- Espacial: paragens em overlap 52 → 59; extensão de linhas SMTUC em overlap 85,4 → 103,6 km. As coordenadas são as oficiais, e há uma paragem nova (Alto de São João).
- Linhas com overlap: 68 → 68.

**Isócronas e população**: tempo médio ponderado 39,4 → 39,5 min; população a ≤ 10 min do estádio 14 441 → 14 141; população sem oferta 13 705 → 13 701. Variações abaixo de 3 %.

**Busca de desvio da 54** (ranking: mais sentidos melhorados, depois menos regressões, depois menor soma de medianas):

| Proposta | Sintético | Oficial |
|---|---|---|
| Otimizado (mesmas viagens) | −11: 3 melhorados / 1 regressão | −11: **2 / 2** (soma 50,2); −10: 1 / 0 (soma 50,2) |
| Melhorado (2.º autocarro, 20 min) | −9: 3 / 1; −10: 2 / 0 | −18: **3 / 1** (soma 39,4); −20: 2 / 0 (soma 34,7) |

## Decisão dos desvios (2026-11-16)

O critério de busca mudou:

- **Antes:** mais sentidos melhorados primeiro, com −20..+20 nas duas propostas.
- **Agora:** a busca fica em meio ciclo de cada proposta (±20 no otimizado, ±10 no melhorado). Escolhe-se o desvio que **não piora nenhum sentido**, com a menor espera total, e em empate o mais pequeno.

Com o critério antigo, os desvios grandes ganhavam por efeito de borda (a 1.ª ou a última viagem do dia a entrar ou sair) e aceitavam piorar um sentido para melhorar outro.

| Proposta | Desvio | Efeito (mediana, min) | Soma |
|---|---|---|---|
| Otimizado (mesmas viagens) | **−10** (era −11) | Portagem metro→autocarro 26,0 → 25,2; os outros 3 sentidos iguais | 50,2 |
| Melhorado (2.º autocarro, 20 min) | **0** (era −10) | Portagem metro→autocarro 26,0 → 15,0; os outros 3 sentidos iguais | 40,0 |

Com a regra antiga do transbordo (0 min), os desvios seriam −13 / −3.

## D2.4 e D2.6: linha 38 e desvios na rede da fase 2 (2026-11-16)

Decisões do utilizador:
- A 38 fica no nó de Portagem com **origem própria**. Antes partilhava a origem da 54 ("Portela do Mondego"), onde nunca passa, e contribuía 0 passagens. Agora conta no sentido Santa Clara → Polo II, que chega a Portagem vindo da margem esquerda, como a 54 vinda de Portela: 14 passagens por dia útil, com 3,23 min de transbordo a pé.
- Em Portagem, autocarro→metro continua a contar **só o sentido Vale das Flores/Serpins** (o da fase 1), mesmo na fase 2.
- **Um só par de desvios** para todos os cenários: −10 / 0, o ótimo da rede da fase 2.

Efeito no `antes` (`diff_oficial_fase1_desvios_vs_d24.csv`):
- Portagem metro→autocarro passa de 26,0 para 19,0 min de mediana, porque a 38 junta passagens à 54.
- Portagem autocarro→metro passa de 2 para 4 min, porque as chegadas da 38 são na paragem do Parque Manuel Braga, mais longe.
- Portela não muda.

Uma linha com viagens no dia que nunca passa no nó depois da sua origem passa a ser um **erro**. Antes contribuía 0 passagens sem aviso.

Busca na fase 2 oficial (`busca_fase_54_fase2_oficial.csv`):
- **Otimizado −10:** melhora 3 dos 4 sentidos sem piorar nenhum (soma das medianas 49,5 → 48,6).
- **Melhorado 0:** nenhum desvio evita piorar um sentido; o 0 é o de menor espera total (38,0).
- **No `antes`:** a busca daria 0 / −10. O −10 do otimizado só perde lá 0,1 min num sentido.

## Metro sintético → oficial na fase 2 (D2.7, 2026-11-16)

Mudam o metro (NeTEx oficial), o SMTUC (Ep225) e o dia (2026-11-09). Os números do slide da fase 2 passam a ser oficiais:
- **Overlap temporal:** 82,6 % → 97,8 % dos candidatos espaciais.
- **Overlap espacial:** estações em overlap 88 → 94 e linhas SMTUC com overlap 94 → 86. A extensão em overlap fica igual (338 km). O salto face aos 104 km da fase 1 vem da rede da fase 2 (Baixa, Coimbra B) e já existia no sintético.
- **Isócronas e população:** o tempo médio ponderado a partir do estádio passa de 37,9 para 35,7 min; as partidas por dia sobem 1,5 %.
- **Esperas da 54** (novas no slide): Portagem metro→autocarro 19,0 min e autocarro→metro 4,5 min; Portela 19,8 e 6,3 min (mediana).
