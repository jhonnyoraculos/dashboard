
# JR Dashboard — Combustível

Dashboard interativo (Python + HTML + Plotly) para apresentar gastos de combustível da JR.

## Como rodar (VS Code / Windows)

1. **Instale o Python 3.11+** (se ainda não tiver) e garanta que `python` e `pip` funcionam no terminal.
2. Abra esta pasta no VS Code.
3. No terminal do VS Code, crie um virtual env (opcional, mas recomendado):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
4. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
5. Rode o servidor:
   ```bash
   python app.py
   ```
6. Abra o navegador em **http://localhost:5000**.

## Como atualizar os dados

- Substitua o arquivo **`data/combustivel.xlsx`** pela sua planilha.
- O app espera o mesmo layout da planilha enviada (onde a primeira linha útil contém os nomes das colunas e os dados começam logo abaixo).
- As colunas utilizadas são: `Data`, `Km inicial`, `Km final`, `Km Rodados`, `Litros`, `Custo`, `COMBUSTÍVEL`, `POSTOS`, `PLACA`.

## Filtros

- Mês, Placa, Posto e Combustível (no topo). Eles são aplicados **no navegador**, recarregando os gráficos sem precisar reiniciar o servidor.

## Gráficos incluídos

- **Gasto por Placa (Mensal)**
- **Gasto por Posto**
- **Gasto por Combustível**
- **KM por Mês**
- **Litros por Mês**
- **Gasto Total por Mês**
- KPIs: **Total (R$)**, **KM Total**, **Total de Litros**

## Personalização rápida

- Troque o logo em `static/logo-jr.png` (o logo já foi adicionado no canto superior esquerdo).
- Ajuste cores e tipografia em `static/style.css`.
