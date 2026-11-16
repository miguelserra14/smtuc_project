# Arquivo: feeds do Metro SINTÉTICOS (não oficiais)

Nenhum código lê esta pasta. Fica só para reproduzir os números antigos.

**Estes dados não vêm da Metro Mondego.** Foram feitos à mão, no repositório, a partir de PDFs de horários. O `feed_info.txt` diz `feed_publisher_name = Metro Mondego`, mas isso **não é verdade**: o ficheiro foi deixado como estava para a impressão digital continuar igual à dos registos.

## `metro_fase1/`: Metro fase 1 sintético (arquivado a 2026-11-16, D1 passo 5)

Foi o dataset `metrobus` até à D1. Substituído pelo GTFS oficial em `data/gtfs/metro/fase1_gtfs_20251219/`.

Defeitos conhecidos:
- falta o serviço urbano Vale das Flores ↔ Portagem (172 viagens por dia útil no oficial);
- faltam chegadas à tarde;
- o `calendar.txt` foi copiado do SMTUC;
- quatro paragens da Lousã têm coordenadas erradas (troços a ~320 km/h);
- Casal de Santo António → Serpins: 1077 m a 0 s;
- o `direction_id` está ao contrário do oficial.

Impressão digital: `b3f7170e307f7cc3`.

Números calculados com ele: `reports/metricas/sintetico.csv` e `reports/metricas/busca_fase_54_sintetico*.csv`. Para os reproduzir, aponta `metrobus` para aqui só dentro do processo (o caminho é relativo a `data/gtfs`):

```
python -c "import runpy,sys; sys.path[:0]=['src','.']; import config; config.DATASET_DIRS['metrobus']='../_arquivo/sintetico/metro_fase1'; sys.argv=['s','snapshot','repro','--out','repro.csv']; runpy.run_path('scripts/snapshot_metrics.py', run_name='__main__')"
python scripts/snapshot_metrics.py diff reports/metricas/sintetico.csv repro.csv --check
```

O snapshot precisa da cache de métricas do sintético e recalcula-a numa pasta temporária (alguns minutos).

Verificado a 2026-11-16: com o código atual, os números que só dependem dos dados (secções `linhas`, `overlap_resumo`, `isocrona`, `populacao` e as esperas do horário `atual`) são **iguais**. Diferem só as propostas da 54 e a busca, porque o `sintetico.csv` foi tirado com os desvios −11 / −10 e o critério de busca antigo. Para reproduzir tudo exatamente, usa o código desse momento: `git worktree add <pasta> a12d59c`, com os dados em `data/metrobus`.

## `scripts/`

`fix_metrobus_scrambled_trips.py`: correção única, já aplicada, de viagens baralhadas nos dois feeds sintéticos. Os caminhos que usa já não existem, por isso não volta a correr.

A fase 2 sintética (`data/gtfs/metro/sintetico_fase2/`, ainda usada no slide da fase 2) e o seu gerador (`scripts/generate_metrobus_extension.py`) vêm para aqui na D2.7.
