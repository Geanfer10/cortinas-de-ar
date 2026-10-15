# Cortinas de Ar – Controle de Limpeza

Painel do PCM da Goiás Verde (Luziânia) que mostra a situação de limpeza das 14 cortinas de ar da indústria.
Os dados vêm do quadro **🌬️ Cortinas de Ar – Limpeza** no Monday (board `18435679675`).

## Como funciona

```
Monday (quadro)  →  GitHub Actions (a cada 1 h)  →  data/latest.json  →  index.html (GitHub Pages / TV)
```

- A equipe registra cada limpeza na coluna **Última Limpeza** do Monday.
- A coluna **Próxima Limpeza** é calculada no próprio Monday (Última + Periodicidade).
- A automação `.github/workflows/atualizar.yml` roda de hora em hora, busca o quadro e grava `data/latest.json`.
- O `index.html` lê esse arquivo a cada 5 minutos e recalcula os dias sozinho.

## Estados no painel

| Estado | Regra |
|---|---|
| Vencida | passou da data da próxima limpeza |
| A vencer | faltam 10 dias ou menos |
| Em dia | faltam mais de 10 dias |
| Sem registro | cortina operando sem data de última limpeza |
| Fora de operação | Situação diferente de "Operando" no Monday |

## Estrutura

```
index.html                       painel
data/latest.json                 situação atual (gerado pela automação)
data/historico.json              limpezas registradas + foto diária da conformidade (gerado pela automação)
scripts/atualizar_monday.py      busca o quadro no Monday (só biblioteca padrão do Python)
.github/workflows/atualizar.yml  automação de hora em hora
```

## Configuração (uma vez)

1. **Secret do token**: Settings → Secrets and variables → Actions → New repository secret
   Nome: `MONDAY_API_TOKEN` · Valor: o token da API do Monday (o mesmo usado nos painéis de Geradores e Filtros).
2. **Permissão da automação**: Settings → Actions → General → Workflow permissions → marcar **Read and write permissions**.
3. **GitHub Pages**: Settings → Pages → Source: *Deploy from a branch* → Branch `main` / pasta `/ (root)`.
4. **Primeira execução**: aba Actions → "Atualizar dados do Monday" → **Run workflow**.

> A pasta `.github/workflows` começa com ponto e some ao arrastar pelo Windows.
> Crie o arquivo pelo botão **Add file → Create new file** digitando o nome `.github/workflows/atualizar.yml` e cole o conteúdo.

## Ajustes rápidos

- Prazo de alerta "A vencer": `ALERTA_DIAS` no `index.html`.
- Frequência da automação: linha `cron` em `atualizar.yml`.
- Se criar ou renomear colunas no Monday, atualize os IDs em `COL` no `scripts/atualizar_monday.py`.
