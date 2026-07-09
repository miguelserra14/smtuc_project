"""Catálogo de referência de polos de emprego e outros locais concorridos em Coimbra.

O índice de subserviço atual (`operations_population.compute_bgri_population_transport_gap`)
só olha para onde as pessoas VIVEM (população residente BGRI). Este ficheiro é o levantamento
de partida para um dia em que se queira também considerar onde as pessoas TRABALHAM e
CONVIVEM - grandes empregadores, hospitais, centros comerciais, etc.

IMPORTANTE - isto é só um catálogo de referência, ainda NÃO está ligado a nenhum cálculo do
pipeline (`compute_underserved_zones`, `underservice_score`, etc.). É o resultado de duas
rondas de pesquisa na web (a segunda mais aprofundada, com validação cruzada de números),
não de uma fonte oficial única e consolidada - por isso cada entrada tem `fonte` e
`raciocinio` a documentar de onde veio a coordenada e, sobretudo, de onde veio (ou como foi
estimado) o número de pessoas. Ler o `raciocinio` antes de usar qualquer valor daqui para
decisões - várias das contagens de pessoas continuam a ser estimativas proporcionais, não
medições diretas, apesar da segunda ronda de validação ter substituído vários palpites por
âncoras reais (nº de novos alunos por escola, relatórios de contas, mapas de pessoal oficiais).

Ver também `data/points_of_interest.csv` (gerado a partir deste ficheiro via `export_to_csv()`
abaixo) para consulta tabular, e o mapa de overlap de linhas (`create_overlap_lines_map`,
`visualizations/lines_map.py`), que já desenha estes pontos.

Confiança das coordenadas:
- A maioria veio de geocoding direto via Nominatim/OpenStreetMap (fonte razoavelmente fiável,
  mas colaborativa - pode ter imprecisões de alguns metros a poucas dezenas de metros).
- Paço das Escolas (Polo I) e Estação Coimbra-B vieram da Wikipédia (PT), que costuma ser
  fiável para monumentos/infraestruturas conhecidas.
- HUC foi corrigido nesta segunda ronda: a 1ª tentativa (conversão manual de graus/minutos/
  segundos) não batia certo com o Nominatim; encontrou-se agora a entrada direta "Hospitais
  da Universidade de Coimbra - Blocos de Celas" no Nominatim, usada aqui.
- FCDEF reutiliza STADIUM_COORD de `config.py` porque a faculdade funciona dentro do próprio
  Estádio Universitário de Coimbra (Pavilhão 3) - não uma coincidência, é a mesma localização.

Confiança dos números de pessoas (3 níveis, documentados por entrada):
  (a) BOA - headcount oficial direto de uma fonte primária (relatório de contas, mapa de
      pessoal, página institucional com número corrente). Ex.: IPO Coimbra 1.105 (relatório de
      segurança e saúde no trabalho), Câmara Municipal 2.575 (Mapa de Pessoal 2025), Talkdesk
      727 (ranking de empresas), Farmácia UC 1.789 (notícia de maio de 2026).
  (b) MÉDIA - conversão de um indicador direto para o que se quer medir, com uma assunção
      explícita. Ex.: Forum Coimbra (visitantes/ano ÷ 365, ignora sazonalidade e fim de
      semana), Alma Shopping (rácio de área bruta locável face ao Forum, aplicado aos
      visitantes do Forum).
  (c) BAIXA - estimativa proporcional a partir de um total agregado sem "split" oficial por
      edifício/escola, ou um palpite por ordem de grandeza sem indicador direto nenhum. Ex.:
      divisão dos totais da ULS Coimbra e da Universidade de Coimbra pelos seus edifícios,
      Parque Industrial de Taveiro.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import POINTS_OF_INTEREST_CSV


@dataclass(frozen=True)
class PointOfInterest:
    nome: str
    lat: float
    lon: float
    categoria: str  # "emprego" ou "outro"
    pessoas_estimadas: int | None  # None quando não há qualquer estimativa defensável
    confianca: str  # "boa", "media" ou "baixa" - ver docstring do módulo
    fonte: str
    raciocinio: str


POINTS_OF_INTEREST: list[PointOfInterest] = [
    # ------------------------------------------------------------------
    # EMPREGO - saúde (ULS Coimbra, ex-CHUC)
    # ------------------------------------------------------------------
    PointOfInterest(
        nome="Hospitais da Universidade de Coimbra (HUC) - ULS Coimbra",
        lat=40.2199342,
        lon=-8.4084915,
        categoria="emprego",
        pessoas_estimadas=3900,
        confianca="baixa",
        fonte=(
            "https://www.ulscoimbra.min-saude.pt/ (total >10.000 trabalhadores); coordenada "
            "via Nominatim/OSM ('Hospitais da Universidade de Coimbra - Blocos de Celas', "
            "corrigida nesta 2ª ronda - a 1ª tentativa por conversão manual de DMS não batia "
            "certo)"
        ),
        raciocinio=(
            "ULS Coimbra tem >10.000 trabalhadores no TOTAL (2.200 médicos + 3.700 "
            "enfermeiros + 2.000 assistentes operacionais + 1.000 assistentes técnicos = "
            "8.900 mínimo confirmado, '+muitos outros profissionais' sugere ~10.500). Esse "
            "total cobre HUC + Covões + Maternidade + Pediátrico + dezenas de centros de "
            "saúde (ex-ACES) espalhados por VÁRIOS concelhos, não só Coimbra cidade - não há "
            "split oficial por edifício. Estimei que os 4 hospitais citadinos representam "
            "~75% do total (~7.875, cuidados hospitalares são mais intensivos em pessoal que "
            "um centro de saúde) e que o HUC, sendo o bloco central/maior (urgência geral, "
            "maioria do internamento e ambulatório), leva ~50% desse subtotal (~3.900). "
            "Tratar como ordem de grandeza, não medição - não mudou da 1ª ronda por não ter "
            "encontrado nenhum split oficial nesta pesquisa mais aprofundada."
        ),
    ),
    PointOfInterest(
        nome="Hospital Geral - Covões (ULS Coimbra)",
        lat=40.1954461,
        lon=-8.4594402,
        categoria="emprego",
        pessoas_estimadas=2000,
        confianca="baixa",
        fonte="Nominatim/OpenStreetMap (Rua 5 de Outubro, São Martinho do Bispo)",
        raciocinio=(
            "Mesmo racional da entrada do HUC acima: ~25% do subtotal hospitalar da ULS "
            "Coimbra (hospital geral secundário, menor que o HUC). Estimativa proporcional, "
            "sem fonte direta de headcount - não encontrei melhor dado nesta 2ª ronda."
        ),
    ),
    PointOfInterest(
        nome="Maternidade Doutor Daniel de Matos (ULS Coimbra)",
        lat=40.2078940,
        lon=-8.4115287,
        categoria="emprego",
        pessoas_estimadas=950,
        confianca="baixa",
        fonte="Nominatim/OpenStreetMap (Rua Miguel Torga, Calhabé)",
        raciocinio=(
            "NOVA nesta 2ª ronda - não estava no primeiro levantamento. Mesmo racional: ~12% "
            "do subtotal hospitalar da ULS Coimbra (unidade especializada). Sem fonte direta "
            "de headcount."
        ),
    ),
    PointOfInterest(
        nome="Hospital Pediátrico de Coimbra (ULS Coimbra)",
        lat=40.2238157,
        lon=-8.4138231,
        categoria="emprego",
        pessoas_estimadas=1050,
        confianca="baixa",
        fonte="Nominatim/OpenStreetMap (Avenida Afonso Romão)",
        raciocinio=(
            "~13% do subtotal hospitalar da ULS Coimbra estimado à mão (unidade "
            "especializada, mais pequena que HUC/Covões). Tentei confirmar via relatório de "
            "contas nesta 2ª ronda mas não encontrei um número específico para esta unidade - "
            "só o total da ULS."
        ),
    ),
    PointOfInterest(
        nome="IPO Coimbra (Instituto Português de Oncologia)",
        lat=40.217207,
        lon=-8.410050,
        categoria="emprego",
        pessoas_estimadas=1105,
        confianca="boa",
        fonte=(
            "Relatório de Segurança, Higiene e Saúde no Trabalho do IPO Coimbra "
            "(www.ipocoimbra.min-saude.pt/wp-content/uploads/sites/3/2025/05/"
            "relatorio-contas-2024.pdf e relatórios de anos anteriores) - "
            "225 médicos + 293 enfermeiros + outros profissionais"
        ),
        raciocinio=(
            "CORRIGIDO nesta 2ª ronda - na 1ª tentativa não tinha encontrado nada e deixei "
            "None. Agora encontrei o número médio de trabalhadores afetos à unidade no ano: "
            "1.105 (221 homens, 884 mulheres), 225 médicos, 293 enfermeiros. É um dado direto "
            "de um relatório oficial de segurança e saúde no trabalho, boa confiança. Entidade "
            "SEPARADA da ULS Coimbra (não faz parte da fusão de 2024)."
        ),
    ),
    # ------------------------------------------------------------------
    # EMPREGO / ENSINO - Universidade de Coimbra (3 polos + FEUC fisicamente à parte)
    # ------------------------------------------------------------------
    PointOfInterest(
        nome="Universidade de Coimbra - Polo I - Faculdade de Letras",
        lat=40.2075,
        lon=-8.42611,
        categoria="emprego",
        pessoas_estimadas=3000,
        confianca="media",
        fonte="https://pt.wikipedia.org/wiki/Pa%C3%A7o_das_Escolas (coordenadas); notícia institucional ('mais de 3 mil pessoas estudam lá, 20% estrangeiros')",
        raciocinio=(
            "AFINADO nesta 2ª ronda - separei a Faculdade de Letras do resto do Polo I porque "
            "encontrei um número direto para ela ('mais de 3 mil'), em vez de continuar a "
            "tratar o Polo I inteiro como um bloco só."
        ),
    ),
    PointOfInterest(
        nome="Universidade de Coimbra - Polo I - resto (Direito, Psicologia, Reitoria e serviços centrais)",
        lat=40.2075,
        lon=-8.42611,
        categoria="emprego",
        pessoas_estimadas=11500,
        confianca="baixa",
        fonte="https://www.uc.pt/dados/ (total da UC); nenhuma fonte direta por faculdade encontrada para Direito/Psicologia",
        raciocinio=(
            "Universo total da UC ~34.256 (31.256 estudantes + ~3.000 trabalhadores, "
            "uc.pt/dados). Depois de subtrair os totais já sourced individualmente (Letras "
            "3.000, Farmácia 1.789, Medicina 3.000, Economia 2.670, Ciências do Desporto 800) "
            "e a estimativa de FCTUC (Polo II, ver abaixo), sobra este valor para Direito + "
            "Psicologia + Reitoria + serviços centrais, que ficam todos na zona do Polo I. "
            "Tentei em vão encontrar números individuais de Direito e Psicologia nesta 2ª "
            "ronda - nenhuma fonte pública os divulga. Bucket residual, não uma medição."
        ),
    ),
    PointOfInterest(
        nome="Faculdade de Economia da Universidade de Coimbra (FEUC)",
        lat=40.2064,
        lon=-8.4127,
        categoria="emprego",
        pessoas_estimadas=2670,
        confianca="boa",
        fonte="https://www.uc.pt/feuc/contactos-localizacao/ (Av. Dr. Dias da Silva, 165); página institucional (~2.500 estudantes + 130 docentes + 40 funcionários)",
        raciocinio=(
            "NOVA nesta 2ª ronda como ponto separado - a FEUC tem morada própria (Av. Dias da "
            "Silva) fisicamente distinta do Paço das Escolas, apesar de administrativamente "
            "pertencer ao 'Polo I'. Número direto e razoavelmente sólido: ~2.500 estudantes + "
            "130 docentes + 40 funcionários = 2.670. Coordenada aproximada (não geocodifiquei "
            "esta morada especificamente - Av. Dias da Silva fica a sul do Paço das Escolas, "
            "perto do rio; usar com alguma cautela, vale a pena confirmar)."
        ),
    ),
    PointOfInterest(
        nome="Universidade de Coimbra - Polo II - Faculdade de Ciências e Tecnologia (FCTUC)",
        lat=40.1864532,
        lon=-8.4126242,
        categoria="emprego",
        pessoas_estimadas=11500,
        confianca="baixa",
        fonte="Google Maps (coordenadas); Wikipédia PT (confirma ser 'a maior faculdade da UC em nº de professores e estudantes', sem número exato)",
        raciocinio=(
            "FCTUC é confirmada como a maior faculdade única da UC (fonte: Wikipédia), mas "
            "não encontrei um número total publicado nem na 1ª nem na 2ª ronda de pesquisa. "
            "Atribuí ~50% do residual do universo UC (depois de subtrair as faculdades já "
            "sourced) - é a maior fatia do bolo residual, consistente com 'maior faculdade', "
            "mas continua a ser uma estimativa à mão, não uma fonte direta."
        ),
    ),
    PointOfInterest(
        nome="Universidade de Coimbra - Polo III - Faculdade de Medicina (FMUC)",
        lat=40.2194533,
        lon=-8.4176226,
        categoria="emprego",
        pessoas_estimadas=3000,
        confianca="media",
        fonte="Nominatim/OpenStreetMap (Rua Costa Simões, Celas) para coordenadas; página institucional FMUC (~3.000 estudantes de Mestrado Integrado + outros mestrados de saúde)",
        raciocinio=(
            "Número direto da própria faculdade, mas arredondado/aproximado (a fonte diz "
            "'representa cerca de 3.000 estudantes', sem grande precisão). Fica mesmo ao lado "
            "do HUC (Celas) - faz sentido, é o mesmo polo académico-hospitalar."
        ),
    ),
    PointOfInterest(
        nome="Universidade de Coimbra - Polo III - Faculdade de Farmácia (FFUC)",
        lat=40.2194533,
        lon=-8.4176226,
        categoria="emprego",
        pessoas_estimadas=1789,
        confianca="boa",
        fonte="https://www.diariocoimbra.pt/2026/05/13/alunos-de-farmacia-tem-100-de-empregabilidade/ (dado de 12 maio 2026)",
        raciocinio=(
            "CORRIGIDO/SOURCED nesta 2ª ronda - antes estava dentro do bloco genérico do Polo "
            "III. Número direto, recente (maio de 2026) e específico: 1.789 estudantes "
            "inscritos (2 licenciaturas + 9 mestrados + Mestrado Integrado em Ciências "
            "Farmacêuticas com 1.195 + doutoramento). É o número com melhor confiança de todo "
            "este ficheiro."
        ),
    ),
    PointOfInterest(
        nome="Universidade de Coimbra - Faculdade de Ciências do Desporto e Educação Física (FCDEF, no Estádio Universitário)",
        lat=40.203809,
        lon=-8.407904,
        categoria="emprego",
        pessoas_estimadas=800,
        confianca="media",
        fonte="https://www.uc.pt/fcdef/ (>800 estudantes nos 3 ciclos de estudo)",
        raciocinio=(
            "NOVA nesta 2ª ronda. Número direto da própria faculdade ('mais de 800 "
            "estudantes'). Coordenada = STADIUM_COORD já usado em config.py, porque a FCDEF "
            "funciona literalmente dentro do Estádio Universitário de Coimbra (Pavilhão 3) - "
            "não é uma aproximação, é a localização real."
        ),
    ),
    # ------------------------------------------------------------------
    # EMPREGO / ENSINO - Instituto Politécnico de Coimbra (5 escolas espalhadas)
    # ------------------------------------------------------------------
    PointOfInterest(
        nome="IPC - ISEC (Instituto Superior de Engenharia de Coimbra)",
        lat=40.1922988,
        lon=-8.4115939,
        categoria="emprego",
        pessoas_estimadas=3630,
        confianca="baixa",
        fonte="IPC total ~11.000 estudantes (fonte institucional); 904 novos alunos matriculados em 2020/21 (isec.pt) como indicador de dimensão relativa",
        raciocinio=(
            "MELHORADO nesta 2ª ronda - já não é uma % arbitrária. Usei o nº de NOVOS alunos "
            "por escola (2020/21, o único ano com dados comparáveis encontrados: ISEC 904, "
            "ESAC 451, ESTeSC 415, ESEC ~501, ISCAC sem dado → assumi ~450 por semelhança de "
            "dimensão) como proxy da dimensão relativa de cada escola, e distribuí o total do "
            "IPC (~11.000) nessa proporção. ISEC fica com ~33% (904/2.721) = ~3.630. Continua "
            "a ser uma estimativa - os 'novos alunos' não são o total de inscritos e são de "
            "um ano específico, mas é mais defensável que um palpite direto de %."
        ),
    ),
    PointOfInterest(
        nome="IPC - ESEC (Escola Superior de Educação)",
        lat=40.2055099,
        lon=-8.4052702,
        categoria="emprego",
        pessoas_estimadas=2030,
        confianca="baixa",
        fonte="483 novos alunos em 2022/23 (esec.pt) como indicador de dimensão relativa",
        raciocinio="~18% do total do IPC (501/2.721), mesmo método da entrada do ISEC acima.",
    ),
    PointOfInterest(
        nome="IPC - ISCAC (Coimbra Business School)",
        lat=40.2096270,
        lon=-8.4528721,
        categoria="emprego",
        pessoas_estimadas=1820,
        confianca="baixa",
        fonte="Sem dado de novos alunos recente encontrado - assumido comparável a ESEC/ESAC",
        raciocinio=(
            "~17% do total do IPC (450 assumido/2.721), mesmo método. Esta é a entrada menos "
            "fundamentada das 5 escolas do IPC porque não encontrei nenhum número de admissões "
            "recentes para o ISCAC (só um valor histórico de 1996, 1.691 alunos, "
            "demasiado antigo para usar)."
        ),
    ),
    PointOfInterest(
        nome="IPC - ESTeSC (Escola Superior de Tecnologia da Saúde)",
        lat=40.1982491,
        lon=-8.4608486,
        categoria="emprego",
        pessoas_estimadas=1680,
        confianca="baixa",
        fonte="415 novos alunos (estesc.ipc.pt) como indicador de dimensão relativa",
        raciocinio="~15% do total do IPC (415/2.721), mesmo método.",
    ),
    PointOfInterest(
        nome="IPC - ESAC (Escola Superior Agrária, Bencanta)",
        lat=40.2141881,
        lon=-8.4512358,
        categoria="emprego",
        pessoas_estimadas=1820,
        confianca="baixa",
        fonte="451 novos alunos (esac.pt) como indicador de dimensão relativa",
        raciocinio=(
            "~17% do total do IPC (451/2.721), mesmo método. Nota: o resultado do geocoding "
            "classificou a coordenada como paragem de autocarro perto da escola, não o "
            "edifício em si - aproximada, vale a pena confirmar."
        ),
    ),
    # ------------------------------------------------------------------
    # EMPREGO - tecnológico/industrial
    # ------------------------------------------------------------------
    PointOfInterest(
        nome="Instituto Pedro Nunes (IPN) + Talkdesk (mesmo edifício, Edifício IPN D)",
        lat=40.1908676,
        lon=-8.4124102,
        categoria="emprego",
        pessoas_estimadas=1100,
        confianca="baixa",
        fonte=(
            "Nominatim/OpenStreetMap para coordenadas; ranking distrital de empresas (Diário "
            "As Beiras) para Talkdesk"
        ),
        raciocinio=(
            "Sem alteração na 2ª ronda - não encontrei dados novos. Talkdesk Inc. Portugal tem "
            "727 colaboradores segundo o ranking das maiores empresas do distrito (confiança "
            "boa para esta parte, é dado direto). Somei ~350-400 pessoas adicionais como "
            "estimativa grosseira para as restantes empresas incubadas/aceleradas no IPN "
            "(>200 startups desde 1991, sem total de colaboradores atuais publicado) - esta "
            "segunda parte continua a ser um palpite."
        ),
    ),
    PointOfInterest(
        nome="Critical Software (sede atual, Parque Industrial de Taveiro)",
        lat=40.1972592,
        lon=-8.5109848,
        categoria="emprego",
        pessoas_estimadas=650,
        confianca="baixa",
        fonte="Indeed (faixa 501-1.000 colaboradores globais, 13 localizações); Jornal do Centro (mudança prevista)",
        raciocinio=(
            "Sem alteração na 2ª ronda. Ponto médio da faixa 501-1.000 encontrada para a "
            "empresa GLOBAL - não é claramente o headcount só de Coimbra, é o melhor proxy "
            "disponível. Projeto de nova sede no centro da cidade prevê acolher 525 "
            "trabalhadores - quando isso acontecer este ponto deve ser substituído."
        ),
    ),
    PointOfInterest(
        nome="Parque Industrial de Taveiro (restantes ~57 empresas, excluindo Critical Software)",
        lat=40.1972592,
        lon=-8.5109848,
        categoria="emprego",
        pessoas_estimadas=900,
        confianca="baixa",
        fonte="Câmara Municipal de Coimbra (nº de lotes/empresas)",
        raciocinio=(
            "Sem alteração na 2ª ronda - continua a ser a estimativa menos fundamentada deste "
            "ficheiro. ~58 empresas instaladas (178.018 m², 57 lotes); assumindo uma média "
            "grosseira de 15-20 trabalhadores por empresa (maioria PME), menos a Critical "
            "Software já contabilizada em separado. Só uma ordem de grandeza a partir do nº "
            "de lotes, sem qualquer dado de emprego real. NOTA: confirmei nesta ronda que a "
            "nova loja IKEA de Coimbra (ver ponto próprio abaixo) NÃO fica dentro deste "
            "parque - fica no 'Mondego Retail Park', em Taveiro mas um local distinto - não "
            "contar a IKEA aqui."
        ),
    ),
    PointOfInterest(
        nome="Câmara Municipal de Coimbra (Paços do Concelho)",
        lat=40.2111836,
        lon=-8.4287801,
        categoria="emprego",
        pessoas_estimadas=500,
        confianca="baixa",
        fonte="Nominatim/OpenStreetMap para coordenadas; coimbra.pt - Mapa de Pessoal 2025 aprovado prevê 2.575 trabalhadores",
        raciocinio=(
            "CORRIGIDO nesta 2ª ronda - encontrei agora o total OFICIAL: o Mapa de Pessoal "
            "para 2025 (aprovado nov/2024) prevê 2.575 trabalhadores no TOTAL da Câmara "
            "Municipal (confiança boa para este número). MAS este total está disperso por "
            "toda a estrutura municipal - escolas, equipamentos desportivos, bibliotecas, "
            "cemitérios, mercados, etc. - não só o edifício dos Paços do Concelho. O valor "
            "usado aqui (500) é só uma estimativa de quem trabalha NO EDIFÍCIO central "
            "(serviços administrativos, urbanismo, finanças, atendimento) - por isso a "
            "confiança geral desta entrada continua baixa, apesar do total de 2.575 ser "
            "sólido. Se quiseres modelar o emprego municipal completo, precisas de repartir "
            "os 2.575 pelas dezenas de equipamentos municipais, não só este ponto."
        ),
    ),
    # ------------------------------------------------------------------
    # OUTROS LOCAIS CONCORRIDOS (não são emprego, mas geram fluxo diário)
    # ------------------------------------------------------------------
    PointOfInterest(
        nome="Forum Coimbra (centro comercial)",
        lat=40.2114224,
        lon=-8.4432680,
        categoria="outro",
        pessoas_estimadas=23300,
        confianca="media",
        fonte="https://www.noticiasdecoimbra.pt/forum-coimbra-chega-aos-135-milhoes-de-visitantes/ (8,5M visitantes/ano); confirmado 141 lojas, 48.000 m² GLA",
        raciocinio=(
            "8.500.000 visitantes/ano ÷ 365 ≈ 23.300/dia. É uma MÉDIA simples - ignora "
            "sazonalidade (Natal, saldos) e o facto de fins de semana terem tipicamente 2-3x "
            "mais afluência que dias úteis. Sem alteração de valor na 2ª ronda, mas confirmei "
            "141 lojas / 48.000 m² GLA, que usei para calibrar a estimativa do Alma Shopping "
            "abaixo."
        ),
    ),
    PointOfInterest(
        nome="Alma Shopping (centro comercial, ex-Dolce Vita)",
        lat=40.2041918,
        lon=-8.4068611,
        categoria="outro",
        pessoas_estimadas=19800,
        confianca="baixa",
        fonte="https://almashopping.pt/wp-content/uploads/2018/09/AP-Brochura-Alma-Shopping.pdf (114 lojas, 40.840 m² GLA)",
        raciocinio=(
            "CORRIGIDO nesta 2ª ronda - antes estava None. Encontrei a área bruta locável do "
            "Alma Shopping (40.840 m², brochura de 2018, pode estar desatualizada) e do Forum "
            "Coimbra (48.000 m², dado mais recente). Rácio de GLA: 40.840/48.000 ≈ 0,85. "
            "Apliquei esse rácio aos 8,5M visitantes/ano do Forum → ~7,2M/ano ≈ 19.800/dia. "
            "É uma estimativa por analogia (área de retalho como proxy de afluência), não uma "
            "medição - confiança baixa porque assume que a relação entre área e visitantes é "
            "igual nos dois centros, o que pode não ser verdade (localização, mix de lojas, "
            "estacionamento, etc. também importam)."
        ),
    ),
    PointOfInterest(
        nome="CoimbraShopping (centro comercial, Vale das Flores)",
        lat=40.1942091,
        lon=-8.4096513,
        categoria="outro",
        pessoas_estimadas=13100,
        confianca="baixa",
        fonte=(
            "https://news.cision.com/pt/sonae-sierra/ (gerido pela Sonae Sierra, 58 lojas, "
            "27.048 m² GLA); Nominatim/OpenStreetMap para coordenadas (Avenida Mendes Silva, "
            "Vale das Flores, perto do ISEC)"
        ),
        raciocinio=(
            "NOVA nesta 3ª ronda - um 3º centro comercial que faltava no levantamento "
            "original (só tinha Forum e Alma Shopping). Mesmo método do Alma Shopping: rácio "
            "de GLA face ao Forum Coimbra (27.048/48.000 ≈ 0,56) aplicado aos 8,5M "
            "visitantes/ano do Forum → ~4,79M/ano ≈ 13.100/dia. Mesma ressalva de confiança "
            "baixa - é uma estimativa por analogia de área, não uma medição."
        ),
    ),
    PointOfInterest(
        nome="IKEA Coimbra (Mondego Retail Park, Taveiro)",
        lat=40.1972592,
        lon=-8.5109848,
        categoria="outro",
        pessoas_estimadas=None,
        confianca="baixa",
        fonte=(
            "https://www.coimbra.pt/2026/02/ikea-abre-nova-loja-em-coimbra-e-reforca-investimento-na-regiao-centro/ ; "
            "CNN Portugal (abertura dia 30 de julho de 2026)"
        ),
        raciocinio=(
            "NOVA nesta 2ª ronda - descoberta ao pesquisar o Parque Industrial de Taveiro. "
            "Loja ainda NÃO ABERTA à data desta pesquisa (abre a 30 de julho de 2026, hoje é 9 "
            "de julho de 2026) - por isso não há nenhum dado real de afluência. Formato "
            "'pequena mas poderosa' (4.124 m², muito mais pequeno que um IKEA tradicional de "
            "20.000-40.000 m²), 34 colaboradores. Não tentei estimar visitantes/dia por "
            "analogia com outras lojas IKEA porque este formato compacto não é comparável às "
            "lojas-tipo em que esse tipo de dado costuma existir. Coordenada aproximada "
            "(reutilizei a do Parque Industrial de Taveiro - o 'Mondego Retail Park' é um "
            "local distinto mas próximo, na mesma zona de Taveiro; não geocodifiquei "
            "especificamente). Voltar a esta entrada depois de 30 julho 2026, quando abrir."
        ),
    ),
    PointOfInterest(
        nome="IPO Coimbra (Instituto Português de Oncologia) - também local concorrido",
        lat=40.217207,
        lon=-8.410050,
        categoria="outro",
        pessoas_estimadas=None,
        confianca="baixa",
        fonte="ver entrada de emprego do IPO Coimbra acima",
        raciocinio=(
            "Nota de design: o IPO já está listado acima em 'emprego' (1.105 trabalhadores). "
            "Não dupliquei um número aqui para 'doentes/visitantes por dia' porque não "
            "encontrei esse dado - fica None para não inflacionar artificialmente o total "
            "combinando trabalhadores com visitantes sem base. Manter esta entrada é só para "
            "não esquecer que hospitais também atraem fluxo de doentes/acompanhantes distinto "
            "dos seus próprios trabalhadores, caso um dia se queira modelar isso à parte."
        ),
    ),
    PointOfInterest(
        nome="Mercado Municipal D. Pedro V",
        lat=40.2114263,
        lon=-8.4261548,
        categoria="outro",
        pessoas_estimadas=None,
        confianca="baixa",
        fonte="Nominatim/OpenStreetMap (coordenadas apenas)",
        raciocinio=(
            "Sem alteração na 2ª ronda - continuo sem encontrar qualquer dado de afluência "
            "para este mercado, mesmo com pesquisa dedicada. Precisa de contacto direto com a "
            "Câmara Municipal, que o gere, antes de ter um número associado."
        ),
    ),
    PointOfInterest(
        nome="Estação Coimbra-B",
        lat=40.22521,
        lon=-8.4407,
        categoria="outro",
        pessoas_estimadas=1000,
        confianca="baixa",
        fonte="https://pt.wikipedia.org/wiki/Esta%C3%A7%C3%A3o_Ferrovi%C3%A1ria_de_Coimbra-B (coordenadas); estimativa de passageiros de fonte não-oficial",
        raciocinio=(
            "Sem alteração na 2ª ronda - continuo sem confirmar este número junto da CP ou "
            "Infraestruturas de Portugal (fontes oficiais não publicam dados de passageiros "
            "por estação). Tratar como indicativo. Nota separada: os stops de Coimbra-B já "
            "fazem parte do grafo GTFS usado no resto do projeto, por isso incluir isto como "
            "'destino' na população duplica-o parcialmente com o que já é modelado como nó de "
            "transporte - só faz sentido se quiseres tratar explicitamente a estação como "
            "atrator de viagens, não como paragem de origem."
        ),
    ),
]


def export_to_csv(output_path: str | Path = POINTS_OF_INTEREST_CSV) -> Path:
    """Regenera o CSV de consulta tabular a partir de POINTS_OF_INTEREST.

    Correr manualmente sempre que a lista acima for editada - o CSV não se atualiza sozinho.
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["nome", "lat", "lon", "categoria", "pessoas_estimadas", "confianca", "fonte", "raciocinio"])
        for p in POINTS_OF_INTEREST:
            writer.writerow([
                p.nome,
                p.lat,
                p.lon,
                p.categoria,
                p.pessoas_estimadas if p.pessoas_estimadas is not None else "",
                p.confianca,
                p.fonte,
                p.raciocinio,
            ])
    return out_path


# Pontos com confianca="baixa" incluídos manualmente por pedido explícito (2026-07), apesar de
# a estimativa continuar a ser uma divisão proporcional de um total agregado (ver raciocinio de
# cada um em POINTS_OF_INTEREST) - não foram "promovidos" para boa/media, porque isso seria
# fingir uma certeza que a pesquisa não sustenta. É uma escolha deliberada de mostrar estes
# marcos conhecidos na visualização mesmo com a confiança documentada como baixa, não uma
# correção de confiança.
MANUALLY_INCLUDED_LOW_CONFIDENCE_POI: tuple[str, ...] = (
    "Universidade de Coimbra - Polo II - Faculdade de Ciências e Tecnologia (FCTUC)",
    "Hospitais da Universidade de Coimbra (HUC) - ULS Coimbra",
    "Instituto Pedro Nunes (IPN) + Talkdesk (mesmo edifício, Edifício IPN D)",
    "IPC - ISEC (Instituto Superior de Engenharia de Coimbra)",
    "CoimbraShopping (centro comercial, Vale das Flores)",
)


def load_points_of_interest(
    csv_path: str | Path = POINTS_OF_INTEREST_CSV,
    min_confidence: tuple[str, ...] = ("boa", "media"),
    include_names: tuple[str, ...] = MANUALLY_INCLUDED_LOW_CONFIDENCE_POI,
) -> pd.DataFrame:
    """Carrega `data/points_of_interest.csv` e filtra a pontos com confiança >= `min_confidence`
    (mais qualquer nome em `include_names`, independentemente da confiança) e com
    `pessoas_estimadas` preenchido.

    Usado pelas visualizações que sobrepõem polos de interesse ao índice de subserviço -
    por omissão exclui os pontos `confianca="baixa"` (a maioria das estimativas da
    Universidade de Coimbra, IPC, ULS Coimbra por edifício, etc. - ver `raciocinio` de cada
    entrada em POINTS_OF_INTEREST) para não misturar palpites por ordem de grandeza com o
    resto de um índice que, de outra forma, é uma medição direta - exceto os nomes em
    `include_names`, incluídos de propósito mesmo sendo confiança baixa (ver
    MANUALLY_INCLUDED_LOW_CONFIDENCE_POI). Passa `include_names=()` para voltar ao filtro
    estrito por confiança.
    """
    df = pd.read_csv(csv_path)
    mask = df["confianca"].isin(min_confidence)
    if include_names:
        mask = mask | df["nome"].isin(include_names)
    df = df[mask & df["pessoas_estimadas"].notna()].copy()
    df["pessoas_estimadas"] = df["pessoas_estimadas"].astype(float)
    return df.reset_index(drop=True)


if __name__ == "__main__":
    csv_path = export_to_csv()
    print(f"[SUCCESS] CSV regenerado: {csv_path}")
