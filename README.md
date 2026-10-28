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

## Assistente de IA com Groq

O assistente flutuante esta disponivel em todas as paginas e usa exclusivamente
ferramentas autorizadas e somente leitura para consultar os mesmos calculos do
dashboard. Ele nao recebe acesso a SQL, Python, sistema operacional ou funcoes de
escrita. Dados detalhados, campos pessoais, textos extraidos e arquivos sao
removidos ou resumidos antes de qualquer chamada ao provedor.

Para ativar em producao, adicione estas chaves aos `Secrets` do Streamlit:

```toml
GROQ_API_KEY = "gsk_..."
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-20b"
GROQ_MAX_OUTPUT_TOKENS = 800
GROQ_MAX_TOOL_ROUNDS = 3
GROQ_MAX_CONTINUATIONS = 2
AI_SESSION_MESSAGE_LIMIT = 24
AI_GLOBAL_DAILY_REQUEST_LIMIT = 800
AI_GLOBAL_DAILY_TOKEN_LIMIT = 180000
AI_HISTORY_MESSAGES = 10
```

A chave nunca e enviada ao navegador nem registrada no repositorio. Sem
`GROQ_API_KEY`, o painel exibe o estado de configuracao pendente e todos os
dashboards continuam funcionando normalmente. Consulte `.env.example` para a
configuracao local completa.

Recursos principais:

- contexto da pagina, secao, periodo e filtros ativos;
- consultas reais a KPIs, rankings e series historicas agregadas;
- comparacao de periodos e calculo auditavel de variacoes;
- botao `Analisar este grafico com IA` nos graficos padrao;
- resumo da pagina, perguntas sugeridas e historico durante a sessao;
- proposta de filtros com confirmacao do usuario antes da aplicacao;
- limites de mensagens, requisicoes, tokens, tamanho e rodadas de ferramentas;
- cache de respostas repetidas limitado a sessao atual;
- tratamento de indisponibilidade e limites HTTP 429 da Groq.
- diagnóstico específico para chave, permissão, modelo e tamanho da solicitação;
- contingência automática no modelo `openai/gpt-oss-20b` se o 120B estiver sem capacidade.

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

## Plataforma de rotas

O dashboard de Rotas considera exclusivamente viagens concluidas. Registros
pendentes continuam armazenados para preenchimento, mas nao entram em KPIs,
custos, rankings, graficos, alertas, pesquisas ou relatorios gerenciais.

Os filtros globais aceitam periodos prontos e intervalo personalizado. Quando a
comparacao e ativada, o sistema consulta o intervalo imediatamente anterior com
a mesma quantidade de dias e preserva os filtros de placa, motorista, rota,
categoria e pesquisa.

O custo operacional atribuido usa o custo historico real de combustivel por KM
de cada placa ate a data atual. O combustivel de uma rota e esse valor em R$/KM
multiplicado pelos KM informados na propria rota; nao ha mais associacao por
proximidade de posto, cidade ou horario. Manutencao e pedagio/extras sao
rateados entre rotas da mesma placa e dia; hospedagem usa motorista e data;
salarios usam os dias operacionais; freteiros usam a diaria cadastrada. O
resultado operacional e a receita atribuida menos esses custos disponiveis e
nao deve ser interpretado como lucro liquido contabil. Tributos, depreciacao e
qualquer custo nao cadastrado nao sao estimados artificialmente.

Formulas analiticas adicionais:

- custo por km = custo atribuido / KM informado;
- custo por entrega = custo atribuido / quantidade de entregas;
- custo por tonelada = custo atribuido / peso dos pedidos em toneladas;
- entregas por km = quantidade de entregas / KM informado;
- custo sobre receita = custo atribuido / receita atribuida;
- resultado operacional = receita atribuida - custo atribuido.

Divisoes sem base valida, como freteiro sem KM, permanecem sem valor em vez de
serem substituidas por zero ou por uma distancia inventada.

## Testes

Execute os testes dos principais calculos e exportacoes com:

```bash
python -m unittest discover -s tests -v
```
