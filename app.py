from flask import Flask, render_template, jsonify, request
import pandas as pd
import unicodedata
import os
from pathlib import Path

app = Flask(__name__)

BASE_PATH = Path(__file__).parent / "data"
DATA_COMB = BASE_PATH / "combustivel.xlsx"
DATA_MANU = BASE_PATH / "manutencao.xlsx"
DATA_HOTEIS = BASE_PATH / "reserva de hoteis.xlsx"


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove colunas artificiais e normaliza nomes em ASCII."""
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    rename_map = {}
    for col in df.columns:
        normal = unicodedata.normalize("NFKD", str(col)).encode("ascii", "ignore").decode("ascii")
        rename_map[col] = normal.strip()
    return df.rename(columns=rename_map)


def _group_sum(
    df: pd.DataFrame,
    group_col: str,
    value_col: str = "Custo",
    *,
    sort_by: str = "value",
) -> dict:
    if df.empty or group_col not in df.columns or value_col not in df.columns:
        return {group_col: [], value_col: []}

    grouped = (
        df.dropna(subset=[group_col])
        .groupby(group_col, as_index=False)[value_col]
        .sum()
    )

    if sort_by == "group" and group_col in grouped.columns:
        grouped = grouped.sort_values(group_col)
    else:
        grouped = grouped.sort_values(value_col, ascending=False)

    return grouped.to_dict(orient="list")


def _unique_sorted(df: pd.DataFrame, column: str) -> list:
    if column not in df.columns:
        return []
    series = df[column].dropna()
    if series.empty:
        return []
    return sorted(series.astype(str).str.strip().unique().tolist())


def load_combustivel() -> pd.DataFrame:
    df = pd.read_excel(DATA_COMB, sheet_name=0, header=1)
    df = _clean_columns(df)

    df = df.rename(columns={
        "COMBUSTIVEL": "Combustivel",
        "MES": "Mes",
    })

    df["Data"] = pd.to_datetime(df.get("Data"), errors="coerce")
    for col in ["Km Rodados", "Litros", "Custo"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")

    df = df.dropna(subset=["Data"]).copy()
    df["Mes"] = df["Data"].dt.to_period("M").astype(str)

    for col in ["Combustivel", "POSTOS", "PLACA"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    return df


def agg_combustivel(df: pd.DataFrame) -> dict:
    custo_total = float(df["Custo"].sum()) if "Custo" in df else 0.0
    km_total = float(df["Km Rodados"].sum()) if "Km Rodados" in df else 0.0
    litros_total = float(df["Litros"].sum()) if "Litros" in df else 0.0
    custo_por_km = (custo_total / km_total) if km_total else 0.0
    km_por_litro = (km_total / litros_total) if litros_total else 0.0
    custo_por_litro = (custo_total / litros_total) if litros_total else 0.0
    meses_distintos = df["Mes"].dropna().unique() if "Mes" in df else []
    media_mensal = float(custo_total / len(meses_distintos)) if len(meses_distintos) else 0.0

    return {
        "km_total": km_total,
        "litros_total": litros_total,
        "custo_total": custo_total,
        "media_mensal": media_mensal,
        "custo_por_km": custo_por_km,
        "km_por_litro": km_por_litro,
        "custo_por_litro": custo_por_litro,
        "custo_mensal": _group_sum(df, "Mes", sort_by="group"),
        "km_mensal": _group_sum(df, "Mes", "Km Rodados", sort_by="group"),
        "litros_mensal": _group_sum(df, "Mes", "Litros", sort_by="group"),
        "gasto_por_posto": _group_sum(df, "POSTOS"),
        "gasto_por_combustivel": _group_sum(df, "Combustivel"),
        "gasto_por_placa": _group_sum(df, "PLACA"),
        "placas": _unique_sorted(df, "PLACA"),
        "postos": _unique_sorted(df, "POSTOS"),
        "combustiveis": _unique_sorted(df, "Combustivel"),
        "meses": _unique_sorted(df, "Mes"),
    }


def load_manutencao() -> pd.DataFrame:
    df = pd.read_excel(DATA_MANU, sheet_name=0, header=1)
    df = _clean_columns(df)

    df = df.rename(columns={
        "PLACAS": "PLACA",
        "MES": "Mes",
        "DATA": "Data",
    })

    df["Data"] = pd.to_datetime(df.get("Data"), errors="coerce")
    if "Mes" in df.columns:
        mes_dt = pd.to_datetime(df["Mes"], errors="coerce")
        df["Data"] = df["Data"].combine_first(mes_dt)

    df["Mes"] = df["Data"].dt.to_period("M").astype(str)
    df["Custo"] = pd.to_numeric(df.get("Custo"), errors="coerce")

    df = df.dropna(subset=["Mes", "Custo"]).copy()
    for col in ["PLACA", "OFICINA"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    return df


def agg_manutencao(df: pd.DataFrame) -> dict:
    custo_total = float(df["Custo"].sum()) if "Custo" in df else 0.0
    total_servicos = int(len(df))
    media_servico = float(custo_total / total_servicos) if total_servicos else 0.0
    meses_distintos = df["Mes"].dropna().unique() if "Mes" in df else []
    media_mensal = float(custo_total / len(meses_distintos)) if len(meses_distintos) else 0.0

    return {
        "custo_total": custo_total,
        "total_servicos": total_servicos,
        "media_servico": media_servico,
        "media_mensal": media_mensal,
        "custo_mensal": _group_sum(df, "Mes", sort_by="group"),
        "gasto_por_placa": _group_sum(df, "PLACA"),
        "gasto_por_oficina": _group_sum(df, "OFICINA"),
        "placas": _unique_sorted(df, "PLACA"),
        "oficinas": _unique_sorted(df, "OFICINA"),
        "meses": _unique_sorted(df, "Mes"),
    }


def load_hoteis() -> pd.DataFrame:
    df = pd.read_excel(DATA_HOTEIS, sheet_name=0, header=4)
    df = _clean_columns(df)

    df = df.rename(columns={
        "DATA": "Data",
        "VALOR": "Valor",
        "HOTEL/POUSADA": "Hotel",
        "MOTORISTA": "Motorista",
        "AJUDANTE": "Ajudante",
        "CIDADE": "Cidade",
        "TIPO": "Tipo",
        "DIAS": "Dias",
    })

    df["Data"] = pd.to_datetime(df.get("Data"), errors="coerce")
    df["Valor"] = pd.to_numeric(df.get("Valor"), errors="coerce")
    df["Dias"] = pd.to_numeric(df.get("Dias"), errors="coerce")

    period = df["Data"].dt.to_period("M")
    df["Mes"] = period.astype(str)
    df.loc[period.isna(), "Mes"] = None

    for col in ["Motorista", "Ajudante", "Cidade", "Hotel", "Tipo"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    return df.copy()


def agg_hoteis(df: pd.DataFrame) -> dict:
    reservas = df[df["Data"].notna()].copy() if "Data" in df.columns else df.copy()
    valor_total = float(reservas["Valor"].fillna(0).sum()) if "Valor" in reservas else 0.0
    reservas_total = int(reservas.shape[0])
    meses_distintos = reservas["Mes"].dropna().unique() if "Mes" in reservas else []
    media_mensal = float(valor_total / len(meses_distintos)) if len(meses_distintos) else 0.0
    valor_medio_reserva = float(valor_total / reservas_total) if reservas_total else 0.0

    return {
        "valor_total": valor_total,
        "reservas_total": reservas_total,
        "media_mensal": media_mensal,
        "valor_medio_reserva": valor_medio_reserva,
        "valor_mensal": _group_sum(reservas, "Mes", "Valor", sort_by="group"),
        "valor_por_cidade": _group_sum(reservas, "Cidade", "Valor"),
        "valor_por_hotel": _group_sum(reservas, "Hotel", "Valor"),
        "meses": _unique_sorted(reservas, "Mes"),
        "cidades": _unique_sorted(reservas, "Cidade"),
        "hoteis": _unique_sorted(reservas, "Hotel"),
    }





@app.route("/")
def home():
    return render_template("home.html")


@app.route("/combustivel")
def comb_page():
    return render_template("combustivel.html")


@app.route("/manutencao")
def manut_page():
    return render_template("manutencao.html")


@app.route("/hoteis")
def hoteis_page():
    return render_template("hoteis.html")


@app.route("/data/combustivel")
def data_comb():
    df = load_combustivel()

    mes = request.args.get("mes")
    placa = request.args.get("placa")
    posto = request.args.get("posto")
    combustivel = request.args.get("combustivel")

    if mes and mes != "Todos":
        df = df[df["Mes"] == mes]
    if placa and placa != "Todos":
        df = df[df["PLACA"] == placa]
    if posto and posto != "Todos":
        df = df[df["POSTOS"] == posto]
    if combustivel and combustivel != "Todos":
        df = df[df["Combustivel"] == combustivel]

    return jsonify(agg_combustivel(df))


@app.route("/data/manutencao")
def data_manu():
    df = load_manutencao()

    mes = request.args.get("mes")
    placa = request.args.get("placa")
    oficina = request.args.get("oficina")

    if mes and mes != "Todos":
        df = df[df["Mes"] == mes]
    if placa and placa != "Todos":
        df = df[df["PLACA"] == placa]
    if oficina and oficina != "Todos":
        df = df[df["OFICINA"] == oficina]

    return jsonify(agg_manutencao(df))


@app.route("/data/hoteis")
def data_hoteis():
    df = load_hoteis()

    mes = request.args.get("mes")
    cidade = request.args.get("cidade")
    hotel = request.args.get("hotel")

    if mes and mes != "Todos":
        df = df[df["Mes"] == mes]
    if cidade and cidade != "Todos":
        df = df[df["Cidade"] == cidade]
    if hotel and hotel != "Todos":
        df = df[df["Hotel"] == hotel]

    return jsonify(agg_hoteis(df))





if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


