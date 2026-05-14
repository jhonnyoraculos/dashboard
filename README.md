# JR Dashboard em Streamlit

Dashboard operacional da JR Ferragens & Madeiras em Streamlit, reutilizando a mesma leitura e limpeza das planilhas do app Flask original.

## Como rodar

1. Crie e ative um ambiente virtual:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

3. Inicie o Streamlit:
   ```bash
   streamlit run streamlit_app.py
   ```

4. Abra o endereço mostrado no terminal, normalmente `http://localhost:8501`.

## Dados

As planilhas em `data/` continuam sendo a fonte dos indicadores:

- `combustivel.xlsx`
- `manutencao.xlsx`
- `reserva de hoteis.xlsx`
- `pedagio seguro e ipva.xlsx`

O arquivo `app.py` foi preservado como backend de leitura, normalização e agregação. A interface Streamlit fica em `streamlit_app.py`.
