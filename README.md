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

## Calculadora de frete

A calculadora e acessada pelo atalho ao lado do titulo da pagina inicial. O
usuario pode usar a media da frota ou escolher a placa do caminhao; nesse caso,
o custo direto por km e obtido do historico de combustivel, manutencao,
pedagio/extras e diarias da placa. A viagem usa a velocidade media de
80 km/h, e o peso e convertido em horas de descarga pela produtividade media de
350 kg por hora. O tempo da viagem e o tempo da descarga sao somados e
multiplicados pela quantidade de funcionarios e pelo salario medio por hora,
que pode ser ajustado na simulacao. O resultado separa o custo estimado do
valor sugerido com a margem informada.

Os resultados usam diretamente os valores atuais dos campos; a calculadora nao
mantem uma simulacao anterior depois que peso, distancia ou equipe sao
alterados.

As despesas de hotel podem ser marcadas ou desmarcadas na calculadora. Quando
incluidas, usam o valor medio historico por reserva de quarto duplo, calculado
como valor total dividido pela quantidade de reservas. Essa diaria ja cobre
motorista e ajudante e nao e multiplicada pela quantidade de funcionarios. O
hotel e calculado pelo tempo total da operacao: menos de 10 horas nao gera
diaria; de 10 ate menos de 20 horas gera uma diaria; de 20 ate menos de 30
horas gera duas diarias, e assim por diante.

O resumo separa o custo direto do caminhao por km, o custo da equipe e o hotel.
O salario da equipe e calculado pelo tempo de viagem e descarga, quantidade de
funcionarios e valor por hora. O hotel nao altera o custo por km da placa.
