# JR Dashboard em Streamlit

Dashboard operacional da JR Ferragens & Madeiras em Streamlit, com dados lidos diretamente do Neon/Postgres.

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

Sem esse Secret no Streamlit Cloud, o app nao consegue ler o Neon e os dados ficam indisponiveis.

4. Inicie o Streamlit:
   ```bash
   streamlit run streamlit_app.py
   ```

## Dados

O app le somente do Neon/Postgres. Para obrigar esse modo tambem no ambiente local, use:

```bash
set JR_DATA_SOURCE=database
```

Os arquivos de dados antigos nao fazem parte do deploy do Streamlit.
