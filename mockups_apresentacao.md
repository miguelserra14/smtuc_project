# Mockups da apresentação

A apresentação foi pensada para um ecrã grande e horizontal, com uma lógica de leitura muito próxima de uma dashboard editorial: cada slide deve ter uma ideia dominante, uma visualização principal e um pequeno bloco de apoio com texto curto. A estrutura abaixo privilegia a clareza visual e evita slides demasiado densos, porque o objetivo não é ler tudo no ecrã, mas guiar a leitura com ritmo e hierarquia.

## 1. Introdução

Este primeiro ecrã deve funcionar como abertura forte. O fundo pode usar uma imagem ou composição abstrata relacionada com Coimbra e transporte, mas sem competir com o título. O centro do slide deve conter o nome do projeto, com uma linha secundária a explicar a tese principal. Os nomes, a instituição e os logótipos devem ficar alinhados numa barra inferior discreta, para não roubar peso à mensagem inicial.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                          SMTUC: a caminho da complementaridade              │
│                                                                              │
│              Como o Metrobus mudou a mobilidade em Coimbra                  │
│              e o que o SMTUC pode adaptar já                                │
│                                                                              │
│                                                                              │
│                                                           [logótipos]       │
│                                                     nome | curso | data      │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. Overview da metodologia

Este slide deve mostrar, em simultâneo, a origem dos dados e a primeira leitura espacial de Coimbra. A melhor solução é dividir o ecrã em duas metades: à esquerda, um bloco curto com o pipeline metodológico; à direita, um mapa ou composição com os mapas de população, para mostrar logo a dimensão territorial do problema. Se houver espaço, um pequeno friso inferior pode listar as fontes usadas: SMTUC, Metrobus, população, locais de trabalho e locais de convívio.

```text
┌───────────────────────────────┬──────────────────────────────────────────────┐
│ METODOLOGIA                   │ MAPA PRINCIPAL                               │
│                               │                                              │
│ SMTUC + Metrobus + população  │  [mapa população Coimbra]                     │
│ + locais de trabalho +        │  [mapa heatmap / densidade]                   │
│ locais de convívio            │                                              │
│                               │                                              │
│ 1. recolha                    │                                              │
│ 2. limpeza                    │                                              │
│ 3. métricas                   │                                              │
│ 4. visualização               │                                              │
└───────────────────────────────┴──────────────────────────────────────────────┘
```

## 3. Métrica de subserviço e isócronas

Aqui o foco deve ser a taxa de subserviço. O slide precisa de explicar, de forma simples, que a métrica não é só uma contagem de paragens ou passagens, mas uma forma de relacionar população com oferta de serviço. Visualmente, este é o momento ideal para mostrar os dois mapas existentes com a métrica, colocados lado a lado, e reservar uma zona complementar para a visualização das isócronas. Como o objetivo é alargar a leitura a trabalho e convívio, essa nota deve aparecer como uma chamada curta no próprio slide, para justificar a próxima iteração da visualização.

```text
┌───────────────────────┬───────────────────────┬─────────────────────────────┐
│ MAPA 1                │ MAPA 2                │ ISÓCRONAS                   │
│ taxa de subserviço    │ taxa de subserviço    │ áreas servidas              │
│ visão global          │ detalhe / corte       │ + trabalho + convívio       │
│                       │                       │                             │
│ [choropleth]          │ [heatmap / detalhe]   │ [isochronas]                │
└───────────────────────┴───────────────────────┴─────────────────────────────┘
```

## 4. Overlap SMTUC / Metrobus

Este deve ser um dos slides mais visuais da apresentação, porque é aqui que a tese fica mais evidente. A composição ideal é um mapa amplo e dominante, mostrando as áreas de maior overlap, acompanhado por um painel lateral com a leitura das linhas mais sobrepostas. O slide não deve parecer uma tabela; deve parecer uma prova visual de onde a redundância cresceu e onde a rede perdeu originalidade. Se for necessário, o resumo temporal pode entrar como uma faixa inferior pequena, quase como legenda expandida.

```text
┌───────────────────────────────────────────────────────┬─────────────────────┐
│ MAPA DE OVERLAP                                       │ LINHAS / LEITURA    │
│                                                       │                     │
│ [isochronas + zonas de overlap]                       │ Top linhas          │
│ [marcação de corredores principais]                   │ Bottom linhas       │
│                                                       │ Impacto temporal    │
│                                                       │                     │
└───────────────────────────────────────────────────────┴─────────────────────┘
```

## 5. Integração Portagem e Portela

Esta secção deve ser apresentada como comparação direta entre o estado atual e a versão otimizada do 54. O ideal é usar dois slides ou um slide duplo em que cada sentido da linha tenha o mesmo tratamento visual: à esquerda a versão atual, à direita a versão melhorada. Dentro de cada metade, a hierarquia deve ser sempre a mesma, para o público perceber rapidamente o que mudou nos horários, nas esperas e na coordenação com o Metrobus. A comparação deve sublinhar diferença, não acumular informação.

```text
┌───────────────────────────────┬───────────────────────────────┐
│ PORTAGEM                      │ PORTELA                       │
│                               │                               │
│ versão atual do 54            │ versão atual do 54            │
│ [heatmaps / espera]           │ [heatmaps / espera]           │
│                               │                               │
│ versão otimizada              │ versão otimizada              │
│ [melhores horários]           │ [melhores horários]           │
└───────────────────────────────┴───────────────────────────────┘
```

## 6. Conclusões finais

O slide final deve ser limpo e muito legível. A melhor solução é um ecrã com uma conclusão principal no centro e três blocos menores com as mensagens-chave: onde o Metrobus mudou a rede, onde o SMTUC deve adaptar-se e qual é o próximo passo analítico ou de desenho. Este é também o melhor momento para fechar com uma frase forte, curta e memorável, em vez de repetir o relatório inteiro.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ CONCLUSÃO PRINCIPAL                                                          │
│                                                                              │
│ O Metrobus alterou a mobilidade em Coimbra e o SMTUC precisa de se adaptar. │
│                                                                              │
│  [impacto na rede]    [adaptação do SMTUC]    [próximos passos]             │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 7. Agradecimentos

O fecho deve ser minimalista. Um ecrã escuro ou neutro, com agradecimentos, nomes e logótipos pequenos, é suficiente. Se houver tempo, pode incluir uma linha final de contacto ou uma frase curta de encerramento, mas sem competir com a conclusão anterior.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                                Obrigado                                      │
│                                                                              │
│                    nomes | instituição | contactos                           │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Notas de execução visual

Em ecrã grande, a regra principal é manter o texto curto e deixar a visualização respirar. Os slides devem usar margens largas, títulos grandes e uma grelha consistente de 2 ou 3 colunas, consoante o conteúdo. As transições devem ser discretas e funcionais, preferencialmente fades curtos ou mudanças secas entre secções, para não distraírem da leitura das visualizações. Sempre que possível, a apresentação deve entrar diretamente na visualização e só depois trazer a explicação oral, porque o foco deste trabalho é mostrar a mudança da mobilidade, não apenas descrevê-la.
