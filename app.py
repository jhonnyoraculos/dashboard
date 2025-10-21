from flask import Flask, render_template, jsonify, request
import pandas as pd
import unicodedata
import os
import threading
from pathlib import Path

app = Flask(__name__)

BASE_PATH = Path(__file__).parent / "data"
DATA_COMB = BASE_PATH / "combustivel.xlsx"
DATA_MANU = BASE_PATH / "manutencao.xlsx"
DATA_HOTEIS = BASE_PATH / "reserva de hoteis.xlsx"
DATA_PEDAGIO = BASE_PATH / "pedagio seguro e ipva.xlsx"
_PEDAGIO_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}
_COMBUSTIVEL_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}
_MANUTENCAO_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}
_HOTEIS_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove colunas artificiais e normaliza nomes em ASCII."""
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    rename_map = {}
    keep_cols = []
    for col in df.columns:
        normal = unicodedata.normalize("NFKD", str(col)).encode("ascii", "ignore").decode("ascii")
        cleaned = normal.strip()
        if cleaned == "" or cleaned.lower() == "nan":
            continue
        keep_cols.append(col)
        rename_map[col] = cleaned
    df = df.loc[:, keep_cols]
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


def _weekly_series(df: pd.DataFrame, date_col: str, value_col: str, label: str) -> dict:
    today = pd.Timestamp.today().normalize()
    start_default = today - pd.Timedelta(days=6)
    default_index = pd.date_range(start_default, today, freq="D")
    template = {
        "Dia": default_index.strftime("%d/%m").tolist(),
        "DiaISO": default_index.strftime("%Y-%m-%d").tolist(),
        label: [0.0] * len(default_index),
    }

    if df.empty or date_col not in df.columns or value_col not in df.columns:
        return template

    dates = pd.to_datetime(df[date_col], errors="coerce")
    values = pd.to_numeric(df[value_col], errors="coerce")
    valid = dates.notna() & values.notna()
    if not valid.any():
        return template

    data = pd.DataFrame(
        {
            "data": dates.loc[valid].dt.normalize(),
            "valor": values.loc[valid].astype("float64"),
        }
    )
    data = data.dropna()
    if data.empty:
        return template

    start = start_default
    end = today
    index = default_index

    window_mask = data["data"].between(start, end)
    if not window_mask.any():
        end = data["data"].max()
        if pd.isna(end):
            return template
        start = end - pd.Timedelta(days=6)
        index = pd.date_range(start, end, freq="D")
        template = {
            "Dia": index.strftime("%d/%m").tolist(),
            label: [0.0] * len(index),
        }
        window_mask = data["data"].between(start, end)
        if not window_mask.any():
            return template

    grouped = data.loc[window_mask].groupby("data")["valor"].sum()
    grouped = grouped.reindex(index, fill_value=0.0).astype("float64")
    return {
        "Dia": index.strftime("%d/%m").tolist(),
        "DiaISO": index.strftime("%Y-%m-%d").tolist(),
        label: grouped.round(2).tolist(),
    }


def _to_numeric_currency(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    cleaned = series.astype("string").str.strip()
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    cleaned = cleaned.str.replace("R$", "", regex=False).str.replace("\u00a0", "", regex=False)
    cleaned = cleaned.str.replace(" ", "", regex=False)

    mask_comma = cleaned.str.contains(",", regex=False, na=False)
    cleaned.loc[mask_comma] = (
        cleaned.loc[mask_comma]
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    cleaned.loc[~mask_comma] = cleaned.loc[~mask_comma].str.replace(",", ".", regex=False)

    return pd.to_numeric(cleaned, errors="coerce")


def _normalize_ascii(value):
    if pd.isna(value):
        return value
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").strip()


def _canonical_tipo(value):
    if pd.isna(value):
        return None
    text = _normalize_ascii(value).upper()
    if not text:
        return None
    if "PEDAG" in text:
        return "Pedagio"
    if "IPVA" in text:
        return "IPVA"
    if "SEGUR" in text or "APOLI" in text or "APOLICE" in text:
        return "Seguro"
    if "LICENCI" in text:
        return "Licenciamento"
    if "DPVAT" in text:
        return "DPVAT"
    return text.title()


def load_combustivel() -> pd.DataFrame:
    def _empty() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "Data",
            "Mes",
            "Km Rodados",
            "Litros",
            "Custo",
            "Combustivel",
            "POSTOS",
            "PLACA",
            "Categoria",
        ])

    cache = _COMBUSTIVEL_CACHE
    lock = cache["lock"]

    with lock:
        try:
            mtime = DATA_COMB.stat().st_mtime
        except FileNotFoundError:
            cache["mtime"] = None
            cache["df"] = None
            return _empty()
        except PermissionError:
            print("Aviso: sem permissao para ler planilha de combustivel. Verifique se o arquivo esta aberto.")
            cached = cache.get("df")
            if cached is not None:
                return cached.copy()
            return _empty()

        cached = cache.get("df")
        if cached is not None and cache.get("mtime") == mtime:
            return cached.copy()

        try:
            df = pd.read_excel(DATA_COMB, sheet_name=0, header=1)
        except PermissionError:
            print("Aviso: sem permissao para ler planilha de combustivel. Verifique se o arquivo esta aberto.")
            if cached is not None:
                return cached.copy()
            return _empty()
        except Exception as exc:
            print(f"Aviso: falha ao ler planilha de combustivel: {exc}")
            if cached is not None:
                return cached.copy()
            return _empty()

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

        vex_col = next((col for col in df.columns if col.lower() == "vex"), None)
        if vex_col:
            df[vex_col] = df[vex_col].astype("string").str.strip()
            df["Categoria"] = df[vex_col].apply(lambda value: "Vex" if pd.notna(value) and value != "" else "Transporte")
        else:
            df["Categoria"] = "Transporte"

        cache["mtime"] = mtime
        cache["df"] = df.copy()
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
        "segmentos": _unique_sorted(df, "Categoria"),
        "gasto_semana": _weekly_series(df, "Data", "Custo", "Custo"),
    }


def load_manutencao() -> pd.DataFrame:
    def _empty() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "Data",
            "Mes",
            "Custo",
            "PLACA",
            "OFICINA",
            "Categoria",
        ])

    cache = _MANUTENCAO_CACHE
    lock = cache["lock"]

    with lock:
        try:
            mtime = DATA_MANU.stat().st_mtime
        except FileNotFoundError:
            cache["mtime"] = None
            cache["df"] = None
            return _empty()
        except PermissionError:
            print("Aviso: sem permissao para ler planilha de manutencao. Verifique se o arquivo esta aberto.")
            cached = cache.get("df")
            if cached is not None:
                return cached.copy()
            return _empty()

        cached = cache.get("df")
        if cached is not None and cache.get("mtime") == mtime:
            return cached.copy()

        try:
            df = pd.read_excel(DATA_MANU, sheet_name=0, header=1)
        except PermissionError:
            print("Aviso: sem permissao para ler planilha de manutencao. Verifique se o arquivo esta aberto.")
            if cached is not None:
                return cached.copy()
            return _empty()
        except Exception as exc:
            print(f"Aviso: falha ao ler planilha de manutencao: {exc}")
            if cached is not None:
                return cached.copy()
            return _empty()

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

        vex_col = next((col for col in df.columns if col.lower() == "vex"), None)
        if vex_col:
            df[vex_col] = df[vex_col].astype("string").str.strip()
            df["Categoria"] = df[vex_col].apply(lambda value: "Vex" if pd.notna(value) and value != "" else "Transporte")
        else:
            df["Categoria"] = "Transporte"

        cache["mtime"] = mtime
        cache["df"] = df.copy()
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
        "segmentos": _unique_sorted(df, "Categoria"),
        "custo_semana": _weekly_series(df, "Data", "Custo", "Custo"),
    }


def load_hoteis() -> pd.DataFrame:
    def _empty() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "Data",
            "Valor",
            "Dias",
            "Mes",
            "Motorista",
            "Ajudante",
            "Cidade",
            "Hotel",
            "Tipo",
        ])

    cache = _HOTEIS_CACHE
    lock = cache["lock"]

    with lock:
        try:
            mtime = DATA_HOTEIS.stat().st_mtime
        except FileNotFoundError:
            cache["mtime"] = None
            cache["df"] = None
            return _empty()
        except PermissionError:
            print("Aviso: sem permissao para ler planilha de hoteis. Verifique se o arquivo esta aberto.")
            cached = cache.get("df")
            if cached is not None:
                return cached.copy()
            return _empty()

        cached = cache.get("df")
        if cached is not None and cache.get("mtime") == mtime:
            return cached.copy()

        try:
            df = pd.read_excel(DATA_HOTEIS, sheet_name=0, header=4)
        except PermissionError:
            print("Aviso: sem permissao para ler planilha de hoteis. Verifique se o arquivo esta aberto.")
            if cached is not None:
                return cached.copy()
            return _empty()
        except Exception as exc:
            print(f"Aviso: falha ao ler planilha de hoteis: {exc}")
            if cached is not None:
                return cached.copy()
            return _empty()

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

        cache["mtime"] = mtime
        cache["df"] = df.copy()
        return df.copy()


def agg_hoteis(df: pd.DataFrame) -> dict:
    reservas = df[df["Data"].notna()].copy() if "Data" in df.columns else df.copy()
    valor_total = float(reservas["Valor"].fillna(0).sum()) if "Valor" in reservas else 0.0
    reservas_total = int(reservas.shape[0])
    meses_distintos = reservas["Mes"].dropna().unique() if "Mes" in reservas else []
    media_mensal = float(valor_total / len(meses_distintos)) if len(meses_distintos) else 0.0
    valor_medio_reserva = float(valor_total / reservas_total) if reservas_total else 0.0
    if "Data" in reservas.columns and "Valor" in reservas.columns:
        mask_sabado = reservas["Data"].dt.dayofweek == 5
        valor_sabado = float(reservas.loc[mask_sabado, "Valor"].fillna(0).sum())
    else:
        valor_sabado = 0.0

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
        "valor_semana": _weekly_series(reservas, "Data", "Valor", "Valor"),
        "valor_sabado": valor_sabado,
    }


def load_pedagio() -> pd.DataFrame:
    def _empty() -> pd.DataFrame:
        return pd.DataFrame(columns=['PLACA', 'Tipo', 'Custo', 'Mes', 'Data', 'Categoria'])

    cache = _PEDAGIO_CACHE
    lock = cache['lock']

    with lock:
        if not DATA_PEDAGIO.exists():
            cache['mtime'] = None
            cache['df'] = None
            return _empty()

        try:
            mtime = DATA_PEDAGIO.stat().st_mtime
        except PermissionError:
            print('Aviso: sem permissao para ler planilha de pedagio/seguro/IPVA. Verifique se o arquivo esta aberto.')
            cached_df = cache.get('df')
            if cached_df is not None:
                return cached_df.copy(deep=False)
            return _empty()

        cached_df = cache.get('df')
        if cached_df is not None and cache.get('mtime') == mtime:
            return cached_df.copy(deep=False)

        try:
            raw = pd.read_excel(DATA_PEDAGIO, sheet_name=0, header=None, engine='openpyxl')
        except PermissionError:
            print('Aviso: sem permissao para ler planilha de pedagio/seguro/IPVA. Verifique se o arquivo esta aberto.')
            cached_df = cache.get('df')
            if cached_df is not None:
                return cached_df.copy(deep=False)
            return _empty()
        except Exception as exc:
            print(f'Aviso: falha ao ler planilha de pedagio/seguro/IPVA: {exc}')
            cached_df = cache.get('df')
            if cached_df is not None:
                return cached_df.copy(deep=False)
            return _empty()

        expected_core = {'TIPO', 'CUSTO'}
        header_idx = None
        for idx in range(min(len(raw), 10)):
            row = raw.iloc[idx]
            normalized = set()
            for value in row.tolist():
                if pd.isna(value):
                    continue
                normalized.add(_normalize_ascii(value).upper())
            has_placa = any(label in normalized for label in ('PLACA', 'PLACAS'))
            if has_placa and expected_core.issubset(normalized):
                header_idx = idx
                break

        if header_idx is None:
            print('Aviso: cabecalho da planilha de pedagio/seguro/IPVA nao encontrado.')
            return _empty()

        df = raw.iloc[header_idx + 1 :].copy()
        df.columns = raw.iloc[header_idx]
        df = df.dropna(how='all').reset_index(drop=True)
        df = _clean_columns(df)

        rename_map = {}
        for col in df.columns:
            col_norm = _normalize_ascii(col).upper()
            if col_norm in {'PLACA', 'PLACAS'}:
                rename_map[col] = 'PLACA'
            elif col_norm == 'TIPO':
                rename_map[col] = 'Tipo'
            elif col_norm in {'CUSTO', 'VALOR', 'VALORES'}:
                rename_map[col] = 'Custo'
            elif col_norm == 'MES':
                rename_map[col] = 'Mes'
            elif col_norm == 'DATA':
                rename_map[col] = 'Data'
            elif col_norm == 'VEX':
                rename_map[col] = 'Vex'
            elif col_norm in {'DESCRICAO', 'DESCRICAO'}:
                rename_map[col] = 'Descricao'
            elif col_norm in {'SEGURADORA', 'FORNECEDOR'}:
                rename_map[col] = 'Fornecedor'

        if rename_map:
            df = df.rename(columns=rename_map)

        if 'Custo' in df.columns:
            df['Custo'] = _to_numeric_currency(df['Custo'])
        else:
            df['Custo'] = pd.Series(pd.NA, index=df.index, dtype='float64')

        if 'Tipo' in df.columns:
            df['Tipo'] = df['Tipo'].apply(_canonical_tipo).astype('string')
        else:
            df['Tipo'] = pd.Series(pd.NA, index=df.index, dtype='string')

        if 'PLACA' in df.columns:
            df['PLACA'] = (
                df['PLACA']
                .apply(_normalize_ascii)
                .astype('string')
                .str.upper()
                .replace({'': pd.NA})
            )
        else:
            df['PLACA'] = pd.Series(pd.NA, index=df.index, dtype='string')

        if 'Mes' in df.columns:
            mes_raw = df['Mes']
            mes_dt = pd.to_datetime(mes_raw, errors='coerce')
            df['Mes'] = mes_dt.dt.to_period('M').astype('string')
            missing_mes = df['Mes'].isna() | (df['Mes'] == '')
            if missing_mes.any():
                alt = (
                    mes_raw.astype('string')
                    .str.strip()
                    .str.replace(' ', '', regex=False)
                    .str.replace('.', '/', regex=False)
                    .str.replace('-', '/', regex=False)
                )
                alt_dt = pd.to_datetime(alt, errors='coerce')
                valid_alt = missing_mes & alt_dt.notna()
                df.loc[valid_alt, 'Mes'] = alt_dt[valid_alt].dt.to_period('M').astype('string')
                df.loc[missing_mes & ~valid_alt, 'Mes'] = alt.loc[missing_mes & ~valid_alt]
        else:
            df['Mes'] = pd.Series(pd.NA, index=df.index, dtype='string')

        if 'Data' in df.columns:
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
            empty_mes = df['Mes'].isna() | (df['Mes'] == '')
            df.loc[empty_mes, 'Mes'] = df.loc[empty_mes, 'Data'].dt.to_period('M').astype('string')

        vex_col = next((col for col in df.columns if col.lower() == 'vex'), None)
        if vex_col:
            df[vex_col] = df[vex_col].astype('string').str.strip()
            df['Categoria'] = df[vex_col].apply(lambda value: 'Vex' if pd.notna(value) and value != '' else 'Transporte')
        elif 'Categoria' not in df.columns:
            df['Categoria'] = 'Transporte'

        df = df[df['Custo'].notna()].copy()
        df['Tipo'] = df['Tipo'].fillna('Outros')

        result = df.copy()
        cache['mtime'] = mtime
        cache['df'] = result
        return result.copy(deep=False)



def agg_pedagio(df: pd.DataFrame) -> dict:
    registros = df.shape[0]
    custo_total = float(df["Custo"].sum()) if "Custo" in df else 0.0
    meses_distintos = df["Mes"].dropna().unique() if "Mes" in df else []
    media_mensal = float(custo_total / len(meses_distintos)) if len(meses_distintos) else 0.0
    media_valores = float(custo_total / registros) if registros else 0.0

    if "Tipo" in df.columns and not df.empty:
        tipo_totais = df.groupby("Tipo", dropna=False)["Custo"].sum()
    else:
        tipo_totais = pd.Series(dtype="float64")

    gasto_pedagio = float(tipo_totais.get("Pedagio", 0.0))
    gasto_ipva = float(tipo_totais.get("IPVA", 0.0))
    gasto_seguro = float(tipo_totais.get("Seguro", 0.0))

    resultado = {
        "custo_total": custo_total,
        "total_lancamentos": registros,
        "media_mensal": media_mensal,
        "ticket_medio": media_valores,
        "media_valores": media_valores,
        "gasto_pedagio": gasto_pedagio,
        "gasto_ipva": gasto_ipva,
        "gasto_seguro": gasto_seguro,
        "custo_mensal": _group_sum(df, "Mes", "Custo", sort_by="group"),
        "gasto_por_tipo": _group_sum(df, "Tipo", "Custo"),
        "gasto_por_placa": _group_sum(df, "PLACA", "Custo"),
        "meses": _unique_sorted(df, "Mes"),
        "tipos": _unique_sorted(df, "Tipo"),
        "placas": _unique_sorted(df, "PLACA"),
    }

    if "Categoria" in df.columns:
        resultado["segmentos"] = _unique_sorted(df, "Categoria")
        resultado["gasto_por_categoria"] = _group_sum(df, "Categoria", "Custo")
    else:
        resultado["segmentos"] = []
        resultado["gasto_por_categoria"] = {"Categoria": [], "Custo": []}

    resultado["custo_semana"] = _weekly_series(df, "Data", "Custo", "Custo")
    return resultado





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


@app.route("/pedagio")
def pedagio_page():
    return render_template("pedagio.html")


@app.route("/data/combustivel")
def data_comb():
    df = load_combustivel()

    mes = request.args.get("mes")
    placa = request.args.get("placa")
    posto = request.args.get("posto")
    combustivel = request.args.get("combustivel")
    segmento = request.args.get("segmento")

    if mes and mes != "Todos":
        df = df[df["Mes"] == mes]
    if placa and placa != "Todos":
        df = df[df["PLACA"] == placa]
    if posto and posto != "Todos":
        df = df[df["POSTOS"] == posto]
    if combustivel and combustivel != "Todos":
        df = df[df["Combustivel"] == combustivel]
    if segmento and segmento != "Todos" and "Categoria" in df.columns:
        df = df[df["Categoria"] == segmento]

    return jsonify(agg_combustivel(df))


@app.route("/data/manutencao")
def data_manu():
    df = load_manutencao()

    mes = request.args.get("mes")
    placa = request.args.get("placa")
    oficina = request.args.get("oficina")
    segmento = request.args.get("segmento")

    if mes and mes != "Todos":
        df = df[df["Mes"] == mes]
    if placa and placa != "Todos":
        df = df[df["PLACA"] == placa]
    if oficina and oficina != "Todos":
        df = df[df["OFICINA"] == oficina]
    if segmento and segmento != "Todos" and "Categoria" in df.columns:
        df = df[df["Categoria"] == segmento]

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


@app.route("/data/pedagio")
def data_pedagio():
    df = load_pedagio()

    mes = request.args.get("mes")
    placa = request.args.get("placa")
    tipo = request.args.get("tipo")
    segmento = request.args.get("segmento")

    if mes and mes != "Todos":
        df = df[df["Mes"] == mes]
    if placa and placa != "Todos":
        df = df[df["PLACA"] == placa]
    if tipo and tipo != "Todos":
        df = df[df["Tipo"] == tipo]
    if segmento and segmento != "Todos" and "Categoria" in df.columns:
        df = df[df["Categoria"] == segmento]

    return jsonify(agg_pedagio(df))


def _warm_data_caches() -> None:
    loaders = (
        (load_combustivel, "combustivel"),
        (load_manutencao, "manutencao"),
        (load_hoteis, "hoteis"),
        (load_pedagio, "pedagio/seguro/IPVA"),
    )
    for loader, label in loaders:
        try:
            loader()
        except Exception as exc:  # pragma: no cover
            print(f"Aviso: nao foi possivel pre-carregar {label} ({exc})")


threading.Thread(target=_warm_data_caches, daemon=True).start()


def _safe_total(loader, aggregator, key: str) -> dict:
    try:
        df = loader()
    except PermissionError:
        return {"status": "erro", "motivo": "permissao", "valor": None}
    except FileNotFoundError:
        return {"status": "erro", "motivo": "arquivo_nao_encontrado", "valor": None}
    except Exception as exc:  # pragma: no cover
        return {"status": "erro", "motivo": str(exc), "valor": None}

    try:
        valor = float(aggregator(df).get(key, 0.0))
    except Exception as exc:  # pragma: no cover
        return {"status": "erro", "motivo": str(exc), "valor": None}

    return {"status": "ok", "motivo": None, "valor": valor}


def compute_overview_totals() -> dict:
    areas = {
        "combustivel": (load_combustivel, agg_combustivel, "custo_total"),
        "manutencao": (load_manutencao, agg_manutencao, "custo_total"),
        "hoteis": (load_hoteis, agg_hoteis, "valor_total"),
        "pedagio": (load_pedagio, agg_pedagio, "custo_total"),
    }

    detalhes = {}
    total_geral = 0.0

    for nome, (loader, aggregator, chave) in areas.items():
        resultado = _safe_total(loader, aggregator, chave)
        detalhes[nome] = resultado
        if resultado["valor"] is not None:
            total_geral += resultado["valor"]

    detalhes["total_geral"] = total_geral if total_geral else 0.0
    return detalhes


@app.route("/data/overview")
def data_overview():
    return jsonify(compute_overview_totals())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
