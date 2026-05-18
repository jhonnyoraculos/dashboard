# JR Dashboard em Streamlit

Dashboard operacional da JR Ferragens & Madeiras em Streamlit.

## Como rodar

1. Crie e ative um ambiente virtual:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. Instale as dependencias:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure a connection string do Neon:
   ```bash
   set DATABASE_URL=postgresql://usuario:senha@host/db?sslmode=require
   ```

   No Streamlit Cloud, coloque a mesma chave em `Secrets`:
   ```toml
   DATABASE_URL = "postgresql://usuario:senha@host/db?sslmode=require"
   JR_DATA_SOURCE = "database"
   ```

4. Importe os dados das planilhas para o Neon:
   ```bash
   python scripts/import_to_neon.py
   ```

5. Inicie o Streamlit:
   ```bash
   streamlit run streamlit_app.py
   ```

## Dados

O app agora le do Neon/Postgres quando `DATABASE_URL` ou `NEON_DATABASE_URL` esta configurada.

As planilhas em `data/` ficam apenas como fonte de importacao inicial ou recarga manual:

- `combustivel.xlsx`
- `manutencao.xlsx`
- `reserva de hoteis.xlsx`
- `pedagio seguro e ipva.xlsx`

Para forcar leitura das planilhas localmente, use:

```bash
set JR_DATA_SOURCE=excel
```

Para obrigar leitura do banco, use:

```bash
set JR_DATA_SOURCE=database
```
