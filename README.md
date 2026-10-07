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

## Reservas de hoteis

O sistema de Reservas envia somente registros criados depois da implantacao para
`dashboard_hoteis`, usando o UUID permanente da reserva e `INSERT ... ON CONFLICT DO UPDATE`.
As linhas historicas do dashboard permanecem sem UUID e nao sao alteradas. Reservas
sincronizadas sao somente leitura no editor manual do dashboard; novas edicoes devem
ser feitas no sistema de Reservas, que atualiza o mesmo registro automaticamente.

## Velocidade

O dashboard de Velocidade usa uma linha por viagem para calcular velocidade media
ponderada, duracao, tempo parado, SLA e eventos de excesso. Os dados podem ser
incluidos manualmente ou em lote em `Adicionar dados > Velocidade`.

Nessa aba tambem estao disponiveis modelos de importacao em Excel e CSV. O modelo
Excel inclui as abas `Importacao`, `Exemplo` e `Instrucoes`; preencha a aba
`Importacao` antes de enviar o arquivo.
