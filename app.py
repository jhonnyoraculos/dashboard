from __future__ import annotations

import concurrent.futures
import json
import os
import re
import threading
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd


STREAMLIT_APP_MODULE = "streamlit_app"


def _running_as_streamlit_entrypoint() -> bool:
    if __name__ != "__main__":
        return False
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return False
    return get_script_run_ctx() is not None


if _running_as_streamlit_entrypoint():
    os.environ.setdefault("JR_SKIP_WARM_CACHE", "1")
    from streamlit_app import main as streamlit_main
    import streamlit as st

    streamlit_main()
    st.stop()


DB_TABLES = {
    "combustivel": "dashboard_combustivel",
    "combustivel_km": "dashboard_combustivel_km",
    "manutencao": "dashboard_manutencao",
    "hoteis": "dashboard_hoteis",
    "pedagio": "dashboard_pedagio",
    "placas": "dashboard_placas",
}
DB_METADATA_TABLE = "dashboard_metadata"
_DB_ENGINE = None

_PEDAGIO_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}
_COMBUSTIVEL_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}
_MANUTENCAO_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}
_HOTEIS_CACHE = {"mtime": None, "df": None, "lock": threading.Lock()}
_OVERVIEW_CACHE = {"mtimes": None, "dados": None}
_CACHE_MAP = {
    "combustivel": _COMBUSTIVEL_CACHE,
    "manutencao": _MANUTENCAO_CACHE,
    "hoteis": _HOTEIS_CACHE,
    "pedagio": _PEDAGIO_CACHE,
}

_COMBUSTIVEL_COLUMNS = [
    "Data",
    "Mes",
    "Km Rodados",
    "Litros",
    "Custo",
    "Combustivel",
    "POSTOS",
    "PLACA",
    "Categoria",
]
_COMBUSTIVEL_KM_COLUMNS = ["Mes", "PLACA", "Km Rodados"]
_MANUTENCAO_COLUMNS = ["Data", "Mes", "Custo", "PLACA", "OFICINA", "Categoria"]
_HOTEIS_COLUMNS = [
    "Data",
    "Valor",
    "Dias",
    "Mes",
    "Motorista",
    "Ajudante",
    "Cidade",
    "Hotel",
    "Tipo",
    "Categoria",
]
_PEDAGIO_COLUMNS = ["PLACA", "Tipo", "Custo", "Mes", "Data", "Categoria"]
_PLACAS_COLUMNS = ["PLACA", "Categoria"]


def _database_url() -> str | None:
    for key in ("DATABASE_URL", "NEON_DATABASE_URL"):
        value = os.environ.get(key)
        if value:
            return value.strip()
    try:
        import streamlit as st

        for key in ("DATABASE_URL", "NEON_DATABASE_URL"):
            value = st.secrets.get(key)
            if value:
                return str(value).strip()
    except Exception:
        pass
    return None


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return f"postgresql+psycopg://{url[len('postgresql://'):]}"
    if url.startswith("postgres://"):
        return f"postgresql+psycopg://{url[len('postgres://'):]}"
    return url


def _db_engine():
    global _DB_ENGINE
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL/NEON_DATABASE_URL nao configurada. Configure o Secret do Neon no Streamlit.")
    if _DB_ENGINE is None:
        from sqlalchemy import create_engine

        _DB_ENGINE = create_engine(_normalize_database_url(url), pool_pre_ping=True)
    return _DB_ENGINE


def _db_metadata(key: str, default=None):
    try:
        from sqlalchemy import text

        query = text(f'SELECT value_json FROM "{DB_METADATA_TABLE}" WHERE "key" = :key')
        rows = pd.read_sql_query(query, _db_engine(), params={"key": key})
    except Exception:
        return default
    if rows.empty:
        return default
    try:
        return json.loads(rows.iloc[0]["value_json"])
    except Exception:
        return default


def _db_version(dataset: str):
    return _db_metadata(f"{dataset}.version", _db_metadata("import.version", "database"))


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _read_database_table(dataset: str, columns: list[str], *, date_columns: list[str] | None = None) -> pd.DataFrame:
    table = DB_TABLES[dataset]
    try:
        from sqlalchemy import text

        df = pd.read_sql_query(text(f'SELECT * FROM "{table}"'), _db_engine())
    except Exception as exc:
        raise RuntimeError(f'Nao foi possivel ler a tabela "{table}" no Neon.') from exc

    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    if date_columns:
        for column in date_columns:
            if column in df.columns:
                df[column] = pd.to_datetime(df[column], errors="coerce")

    df = df[columns + [column for column in df.columns if column not in columns]]
    df.attrs["anos_sheets"] = _db_metadata(f"{dataset}.anos_sheets", [])
    return df.copy()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _metadata_value(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _write_metadata(conn, key: str, value) -> None:
    from sqlalchemy import text

    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {_quote_identifier(DB_METADATA_TABLE)} (
                "key" TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            INSERT INTO {_quote_identifier(DB_METADATA_TABLE)} ("key", value_json, updated_at)
            VALUES (:key, :value_json, CURRENT_TIMESTAMP)
            ON CONFLICT (key)
            DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"key": key, "value_json": _metadata_value(value)},
    )


def _clear_dataset_cache(dataset: str) -> None:
    if dataset == "combustivel_km":
        targets = ["combustivel"]
    elif dataset == "placas":
        targets = ["combustivel", "manutencao", "pedagio"]
    else:
        targets = [dataset]
    for target in targets:
        cache = _CACHE_MAP.get(target)
        if not cache:
            continue
        cache["mtime"] = None
        cache["df"] = None
        if target == "combustivel":
            cache["km_rodados_mensal"] = None
    _OVERVIEW_CACHE["mtimes"] = None
    _OVERVIEW_CACHE["dados"] = None


def _normalize_insert_value(value):
    if isinstance(value, str) and value.strip() in ("", "Todos"):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _prepare_insert_row(dataset: str, row: dict) -> dict:
    columns_by_dataset = {
        "combustivel": _COMBUSTIVEL_COLUMNS,
        "combustivel_km": _COMBUSTIVEL_KM_COLUMNS,
        "manutencao": _MANUTENCAO_COLUMNS,
        "hoteis": _HOTEIS_COLUMNS,
        "pedagio": _PEDAGIO_COLUMNS,
        "placas": _PLACAS_COLUMNS,
    }
    columns = columns_by_dataset[dataset]
    prepared = {column: _normalize_insert_value(row.get(column)) for column in columns}

    if prepared.get("Data") is not None and not prepared.get("Mes"):
        dt = pd.to_datetime(prepared["Data"], errors="coerce")
        if pd.notna(dt):
            prepared["Mes"] = dt.to_period("M").strftime("%Y-%m")

    if "PLACA" in prepared:
        prepared["PLACA"] = _normalize_insert_value(_normalize_plate_value(prepared["PLACA"]))
        if dataset == "placas" and not _is_plate_identifier(prepared["PLACA"]):
            prepared["PLACA"] = None
    if "Tipo" in prepared and dataset == "pedagio":
        prepared["Tipo"] = _normalize_tipo_value(prepared["Tipo"])
    if "Categoria" in prepared:
        categoria = str(prepared["Categoria"] or "Transporte").strip()
        prepared["Categoria"] = "Vex" if categoria.lower() == "vex" else "Transporte"

    for column, value in list(prepared.items()):
        if isinstance(value, str):
            value = value.strip()
            prepared[column] = value or None
    return prepared


def _ensure_dataset_table(conn, dataset: str) -> None:
    if dataset != "placas":
        return

    from sqlalchemy import text

    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {_quote_identifier(DB_TABLES["placas"])} (
                "PLACA" TEXT PRIMARY KEY,
                "Categoria" TEXT NOT NULL
            )
            """
        )
    )


def save_dashboard_record(dataset: str, row: dict, *, replace_keys: list[str] | None = None) -> str:
    if dataset not in DB_TABLES:
        raise ValueError(f"Dataset invalido: {dataset}")

    from sqlalchemy import text

    prepared = _prepare_insert_row(dataset, row)
    columns = [column for column, value in prepared.items() if value is not None]
    if not columns:
        raise ValueError("Nenhum dado valido para salvar.")

    table = _quote_identifier(DB_TABLES[dataset])
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    value_sql = ", ".join(f":{column}" for column in columns)
    version = datetime.now(timezone.utc).isoformat()

    plate_registry_changed = dataset == "placas"
    with _db_engine().begin() as conn:
        _ensure_dataset_table(conn, dataset)
        if replace_keys:
            keys = [key for key in replace_keys if key in prepared and prepared.get(key) is not None]
            if keys:
                where_sql = " AND ".join(f"{_quote_identifier(key)} = :replace_{key}" for key in keys)
                conn.execute(
                    text(f"DELETE FROM {table} WHERE {where_sql}"),
                    {f"replace_{key}": prepared[key] for key in keys},
                )
        conn.execute(text(f"INSERT INTO {table} ({column_sql}) VALUES ({value_sql})"), {column: prepared[column] for column in columns})
        if dataset in {"combustivel", "manutencao", "pedagio"} and prepared.get("PLACA") and prepared.get("Categoria"):
            plate_registry_changed = True
            _ensure_dataset_table(conn, "placas")
            placas_table = _quote_identifier(DB_TABLES["placas"])
            conn.execute(text(f"DELETE FROM {placas_table} WHERE \"PLACA\" = :placa"), {"placa": prepared["PLACA"]})
            conn.execute(
                text(f"INSERT INTO {placas_table} (\"PLACA\", \"Categoria\") VALUES (:placa, :categoria)"),
                {"placa": prepared["PLACA"], "categoria": prepared["Categoria"]},
            )
            _write_metadata(conn, "placas.version", version)
        _write_metadata(conn, f"{dataset}.version", version)
        _write_metadata(conn, "import.version", version)

    _clear_dataset_cache("placas" if plate_registry_changed else dataset)
    return version


def _normalize_ascii(value):
    if pd.isna(value):
        return value
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").strip()


def _normalize_plate_value(value):
    if pd.isna(value):
        return pd.NA
    text = _normalize_ascii(value).upper()
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text in {"NAN", "NONE", "NAT", "<NA>"}:
        return pd.NA
    if "SEM" in text and "PLACA" in text:
        return "SEM PLACA"
    compact = re.sub(r"[^A-Z0-9]", "", text)
    match = re.search(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}|[A-Z]{3}[0-9]{4}", compact)
    if match:
        return match.group(0)
    return text


def _is_plate_identifier(value) -> bool:
    if pd.isna(value):
        return False
    text = str(value).strip().upper()
    if text == "SEM PLACA":
        return True
    return bool(re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}|[A-Z]{3}[0-9]{4}", text))


def _normalize_plate_series(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="string")
    return series.apply(_normalize_plate_value).astype("string")


def _normalize_text_column(df: pd.DataFrame, column: str) -> None:
    if column not in df.columns:
        return
    series = df[column].astype("string").str.strip()
    series = series.mask(series.str.lower().isin(["", "nan", "none", "nat", "<na>"]), pd.NA)
    df[column] = series


def _normalize_category_column(df: pd.DataFrame, *, default: str = "Transporte") -> None:
    if "Categoria" not in df.columns:
        df["Categoria"] = default
        return
    _normalize_text_column(df, "Categoria")
    df["Categoria"] = df["Categoria"].fillna(default)
    normalized = df["Categoria"].astype("string").str.strip().str.lower()
    df["Categoria"] = normalized.map({"vex": "Vex", "transporte": "Transporte"}).fillna(df["Categoria"])


def _normalize_tipo_value(value):
    if pd.isna(value):
        return "Outros"
    text = _normalize_ascii(value).upper()
    if not text:
        return "Outros"
    if "PEDAG" in text:
        return "Pedagio"
    if "IPVA" in text:
        return "IPVA"
    if "SEGUR" in text or "APOLI" in text:
        return "Seguro"
    if "LICENCI" in text:
        return "Licenciamento"
    if "DPVAT" in text:
        return "DPVAT"
    return str(value).strip().title()


def _read_plate_registry() -> pd.DataFrame:
    try:
        df = _read_database_table("placas", _PLACAS_COLUMNS)
    except Exception:
        return _empty(_PLACAS_COLUMNS)
    if df.empty:
        return _empty(_PLACAS_COLUMNS)
    df = df[_PLACAS_COLUMNS].copy()
    df["PLACA"] = _normalize_plate_series(df["PLACA"])
    _normalize_category_column(df)
    df = df.dropna(subset=["PLACA"]).drop_duplicates(subset=["PLACA"], keep="last")
    df = df[df["PLACA"].apply(_is_plate_identifier)]
    return df


def _apply_plate_categories(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "PLACA" not in df.columns:
        return df
    registry = _read_plate_registry()
    if registry.empty:
        return df
    mapping = dict(zip(registry["PLACA"].astype("string"), registry["Categoria"].astype("string")))
    if not mapping:
        return df
    df = df.copy()
    if "Categoria" not in df.columns:
        df["Categoria"] = "Transporte"
    mapped = df["PLACA"].astype("string").map(mapping)
    mask = mapped.notna()
    df.loc[mask, "Categoria"] = mapped.loc[mask]
    return df


def _derived_plate_registry() -> pd.DataFrame:
    frames = []
    for loader in (load_combustivel, load_manutencao, load_pedagio):
        try:
            df = loader()
        except Exception:
            continue
        if df.empty or "PLACA" not in df.columns:
            continue
        cols = ["PLACA", "Categoria"] if "Categoria" in df.columns else ["PLACA"]
        frame = df[cols].copy()
        if "Categoria" not in frame.columns:
            frame["Categoria"] = "Transporte"
        frames.append(frame)
    if not frames:
        return _empty(_PLACAS_COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    df["PLACA"] = _normalize_plate_series(df["PLACA"])
    _normalize_category_column(df)
    df = df.dropna(subset=["PLACA"])
    df = df[df["PLACA"].apply(_is_plate_identifier)]
    if df.empty:
        return _empty(_PLACAS_COLUMNS)
    grouped = (
        df.groupby("PLACA", as_index=False)["Categoria"]
        .agg(lambda values: "Vex" if any(str(value).strip().lower() == "vex" for value in values) else "Transporte")
    )
    return grouped.sort_values("PLACA").reset_index(drop=True)


def load_placas() -> pd.DataFrame:
    derived = _derived_plate_registry()
    registered = _read_plate_registry()
    frames = [df for df in (derived, registered) if not df.empty]
    if not frames:
        return _empty(_PLACAS_COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    df["PLACA"] = _normalize_plate_series(df["PLACA"])
    _normalize_category_column(df)
    df = df.dropna(subset=["PLACA"]).drop_duplicates(subset=["PLACA"], keep="last")
    df = df[df["PLACA"].apply(_is_plate_identifier)]
    return df[_PLACAS_COLUMNS].sort_values("PLACA").reset_index(drop=True)


def _normalize_mes(df: pd.DataFrame) -> None:
    if "Mes" not in df.columns:
        df["Mes"] = pd.NA

    mes_raw = df["Mes"]
    mes_text = mes_raw.astype("string").str.strip()
    mes_dt = pd.to_datetime(mes_raw, errors="coerce")
    valid_mes = mes_dt.notna()
    if valid_mes.any():
        mes_text.loc[valid_mes] = mes_dt.loc[valid_mes].dt.to_period("M").astype(str)

    if "Data" in df.columns:
        data_dt = pd.to_datetime(df["Data"], errors="coerce")
        empty_mes = mes_text.isna() | mes_text.str.lower().isin(["", "nan", "none", "nat", "<na>"])
        valid_data = empty_mes & data_dt.notna()
        if valid_data.any():
            mes_text.loc[valid_data] = data_dt.loc[valid_data].dt.to_period("M").astype(str)

    mes_text = mes_text.mask(mes_text.str.lower().isin(["", "nan", "none", "nat", "<na>"]), pd.NA)
    df["Mes"] = mes_text


def _group_sum(
    df: pd.DataFrame,
    group_col: str,
    value_col: str = "Custo",
    *,
    sort_by: str = "value",
) -> dict:
    if df is None or df.empty or group_col not in df.columns or value_col not in df.columns:
        return {group_col: [], value_col: []}

    data = df.dropna(subset=[group_col]).copy()
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
    data = data.dropna(subset=[value_col])
    if data.empty:
        return {group_col: [], value_col: []}

    grouped = data.groupby(group_col, as_index=False)[value_col].sum()
    if sort_by == "group":
        grouped = grouped.sort_values(group_col)
    else:
        grouped = grouped.sort_values(value_col, ascending=False)
    return grouped.to_dict(orient="list")


def _unique_sorted(df: pd.DataFrame, column: str) -> list:
    if df is None or column not in df.columns:
        return []
    series = df[column].dropna()
    if series.empty:
        return []
    series = series.astype("string").str.strip()
    series = series[(series != "") & (~series.str.lower().isin(["nan", "none", "nat", "<na>"]))]
    return sorted(series.unique().tolist())


def _unique_years(df: pd.DataFrame) -> list[int]:
    if df is None or "Mes" not in df.columns:
        return []
    periodos = pd.to_datetime(df["Mes"], errors="coerce")
    return sorted({int(ano) for ano in periodos.dt.year.dropna().unique()})


def _parse_int(value, *, min_value: int | None = None, max_value: int | None = None) -> int | None:
    if isinstance(value, (list, tuple)):
        value = next((item for item in value if item not in (None, "", "Todos")), None)
    if value in (None, "", "Todos"):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if min_value is not None and parsed < min_value:
        return None
    if max_value is not None and parsed > max_value:
        return None
    return parsed


def _normalize_categoria(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="string")
    return series.astype("string").fillna("").str.strip().str.lower()


def _exclude_vex(df: pd.DataFrame) -> pd.DataFrame:
    if "Categoria" not in df.columns:
        return df
    mask = _normalize_categoria(df["Categoria"]) != "vex"
    return df.loc[mask].copy()


def _only_vex(df: pd.DataFrame) -> pd.DataFrame:
    if "Categoria" not in df.columns:
        return df.iloc[0:0].copy()
    mask = _normalize_categoria(df["Categoria"]) == "vex"
    return df.loc[mask].copy()


def _filter_by_period(
    df: pd.DataFrame,
    *,
    ano: int | None = None,
    mes: int | None = None,
    meses: list[int] | None = None,
) -> pd.DataFrame:
    meses = meses or []
    if df.empty or "Mes" not in df.columns or (ano is None and mes is None and not meses):
        return df
    periodos = pd.to_datetime(df["Mes"], errors="coerce")
    mask = periodos.notna()
    if ano is not None:
        mask &= periodos.dt.year == ano
    if mes is not None:
        mask &= periodos.dt.month == mes
    if meses:
        mask &= periodos.dt.month.isin(meses)
    return df.loc[mask].copy()


def _as_list(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return list(raw)
    return [raw]


def _parse_mes_list(raw) -> list[str]:
    meses: list[str] = []
    for value in _as_list(raw):
        if value in (None, "", "Todos"):
            continue
        for part in str(value).split(","):
            mes = part.strip()
            if mes and mes.lower() != "todos":
                meses.append(mes)
    return meses


def _parse_mes_int_list(raw) -> list[int]:
    meses: list[int] = []
    for value in _as_list(raw):
        if value in (None, "", "Todos"):
            continue
        for part in str(value).split(","):
            try:
                num = int(part)
            except (TypeError, ValueError):
                continue
            if 1 <= num <= 12:
                meses.append(num)
    return meses


def _param(params: dict | None, key: str):
    if not params:
        return None
    value = params.get(key)
    if isinstance(value, (list, tuple)):
        return next((item for item in value if item not in (None, "")), None)
    return value


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

    data = pd.DataFrame({"data": dates.loc[valid].dt.normalize(), "valor": values.loc[valid].astype("float64")})
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
        template = {"Dia": index.strftime("%d/%m").tolist(), "DiaISO": index.strftime("%Y-%m-%d").tolist(), label: [0.0] * len(index)}
        window_mask = data["data"].between(start, end)
        if not window_mask.any():
            return template

    grouped = data.loc[window_mask].groupby("data")["valor"].sum()
    grouped = grouped.reindex(index, fill_value=0.0).astype("float64")
    return {"Dia": index.strftime("%d/%m").tolist(), "DiaISO": index.strftime("%Y-%m-%d").tolist(), label: grouped.round(2).tolist()}


def _finalize_common(
    df: pd.DataFrame,
    *,
    date_columns: list[str] | None = None,
    numeric_columns: list[str] | None = None,
    text_columns: list[str] | None = None,
    plate_columns: list[str] | None = None,
    default_category: str = "Transporte",
) -> pd.DataFrame:
    df = df.copy()
    for column in date_columns or []:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")
    for column in numeric_columns or []:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in text_columns or []:
        _normalize_text_column(df, column)
    for column in plate_columns or []:
        if column in df.columns:
            df[column] = _normalize_plate_series(df[column])
    _normalize_category_column(df, default=default_category)
    _normalize_mes(df)
    return df


def load_combustivel() -> pd.DataFrame:
    cache = _COMBUSTIVEL_CACHE
    with cache["lock"]:
        version = (_db_version("combustivel"), _db_version("combustivel_km"))
        cached = cache.get("df")
        if cached is not None and cache.get("mtime") == version:
            return cached.copy()

        df = _read_database_table("combustivel", _COMBUSTIVEL_COLUMNS, date_columns=["Data"])
        df = _finalize_common(
            df,
            date_columns=["Data"],
            numeric_columns=["Km Rodados", "Litros", "Custo"],
            text_columns=["Combustivel", "POSTOS"],
            plate_columns=["PLACA"],
        )
        df = _apply_plate_categories(df)

        try:
            km = _read_database_table("combustivel_km", _COMBUSTIVEL_KM_COLUMNS)
            km = _finalize_common(km, numeric_columns=["Km Rodados"], plate_columns=["PLACA"])
            km = km.dropna(subset=["Mes", "Km Rodados"])
        except Exception:
            km = _empty(_COMBUSTIVEL_KM_COLUMNS)
        cache["km_rodados_mensal"] = km[_COMBUSTIVEL_KM_COLUMNS].copy()
        cache["mtime"] = version
        cache["df"] = df.copy()
        return df.copy()


def agg_combustivel(df: pd.DataFrame, *, km_override: pd.DataFrame | None = None) -> dict:
    custo_total = float(pd.to_numeric(df.get("Custo"), errors="coerce").sum()) if "Custo" in df else 0.0
    if km_override is not None and "Km Rodados" in km_override.columns:
        km_total = float(pd.to_numeric(km_override["Km Rodados"], errors="coerce").sum())
    else:
        km_total = float(pd.to_numeric(df.get("Km Rodados"), errors="coerce").sum()) if "Km Rodados" in df else 0.0
    litros_total = float(pd.to_numeric(df.get("Litros"), errors="coerce").sum()) if "Litros" in df else 0.0
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
        "km_mensal": _group_sum(km_override, "Mes", "Km Rodados", sort_by="group") if km_override is not None else _group_sum(df, "Mes", "Km Rodados", sort_by="group"),
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
    cache = _MANUTENCAO_CACHE
    with cache["lock"]:
        version = _db_version("manutencao")
        cached = cache.get("df")
        if cached is not None and cache.get("mtime") == version:
            return cached.copy()

        df = _read_database_table("manutencao", _MANUTENCAO_COLUMNS, date_columns=["Data"])
        df = _finalize_common(
            df,
            date_columns=["Data"],
            numeric_columns=["Custo"],
            text_columns=["OFICINA"],
            plate_columns=["PLACA"],
        )
        df = _apply_plate_categories(df)
        cache["mtime"] = version
        cache["df"] = df.copy()
        return df.copy()


def agg_manutencao(df: pd.DataFrame) -> dict:
    custo_total = float(pd.to_numeric(df.get("Custo"), errors="coerce").sum()) if "Custo" in df else 0.0
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
    cache = _HOTEIS_CACHE
    with cache["lock"]:
        version = _db_version("hoteis")
        cached = cache.get("df")
        if cached is not None and cache.get("mtime") == version:
            return cached.copy()

        df = _read_database_table("hoteis", _HOTEIS_COLUMNS, date_columns=["Data"])
        df = _finalize_common(
            df,
            date_columns=["Data"],
            numeric_columns=["Valor", "Dias"],
            text_columns=["Motorista", "Ajudante", "Cidade", "Hotel", "Tipo"],
        )
        df["Categoria"] = "Transporte"
        cache["mtime"] = version
        cache["df"] = df.copy()
        return df.copy()


def agg_hoteis(df: pd.DataFrame) -> dict:
    reservas = df[df["Data"].notna()].copy() if "Data" in df.columns else df.copy()
    if "Data" in reservas.columns:
        reservas["Data"] = pd.to_datetime(reservas["Data"], errors="coerce")
    valor_total = float(pd.to_numeric(reservas.get("Valor"), errors="coerce").fillna(0).sum()) if "Valor" in reservas else 0.0
    reservas_total = int(reservas.shape[0])
    meses_distintos = reservas["Mes"].dropna().unique() if "Mes" in reservas else []
    media_mensal = float(valor_total / len(meses_distintos)) if len(meses_distintos) else 0.0
    valor_medio_reserva = float(valor_total / reservas_total) if reservas_total else 0.0
    col_nao_planejada = next(
        (
            col
            for col in reservas.columns
            if str(col).strip().upper().replace(" ", "") in {"NAOPLANEJADA", "NAOPLANEJADAS"}
        ),
        None,
    )
    if col_nao_planejada:
        flag_series = pd.to_numeric(reservas[col_nao_planejada], errors="coerce").fillna(0)
        reservas = reservas.assign(_NaoPlanejada=flag_series.astype("int64"))
    else:
        reservas = reservas.assign(_NaoPlanejada=0)

    if "Data" in reservas.columns and "Valor" in reservas.columns:
        mask_sabado = reservas["Data"].dt.dayofweek.isin([4, 5]).fillna(False)
        mask_nao_planejada = reservas["_NaoPlanejada"] == 1
        mask_nao_planejada_total = mask_nao_planejada | mask_sabado
        valor_sabado = float(reservas.loc[mask_sabado, "Valor"].fillna(0).sum())
        valor_nao_planejado = float(reservas.loc[mask_nao_planejada_total, "Valor"].fillna(0).sum())
        reservas_nao_planejadas = int(mask_nao_planejada_total.sum())
    else:
        valor_sabado = 0.0
        valor_nao_planejado = 0.0
        reservas_nao_planejadas = 0

    semanal = _weekly_series(reservas, "Data", "Valor", "Valor")
    if "DiaISO" in semanal:
        nao_planejada_por_dia = (
            reservas.loc[reservas["_NaoPlanejada"] == 1, "Data"].dt.normalize().value_counts()
            if "Data" in reservas.columns
            else pd.Series(dtype="int64")
        )
        semanal["NaoPlanejada"] = [
            bool(nao_planejada_por_dia.get(pd.to_datetime(iso, errors="coerce").normalize(), 0))
            if pd.notna(pd.to_datetime(iso, errors="coerce"))
            else False
            for iso in semanal["DiaISO"]
        ]
    else:
        semanal["NaoPlanejada"] = []

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
        "valor_semana": semanal,
        "valor_sabado": valor_sabado,
        "valor_nao_planejado": valor_nao_planejado,
        "reservas_nao_planejadas": reservas_nao_planejadas,
    }


def load_pedagio() -> pd.DataFrame:
    cache = _PEDAGIO_CACHE
    with cache["lock"]:
        version = _db_version("pedagio")
        cached = cache.get("df")
        if cached is not None and cache.get("mtime") == version:
            return cached.copy(deep=False)

        df = _read_database_table("pedagio", _PEDAGIO_COLUMNS, date_columns=["Data"])
        df = _finalize_common(
            df,
            date_columns=["Data"],
            numeric_columns=["Custo"],
            text_columns=["Tipo"],
            plate_columns=["PLACA"],
        )
        df = _apply_plate_categories(df)
        if "Tipo" in df.columns:
            df["Tipo"] = df["Tipo"].apply(_normalize_tipo_value).astype("string")
        df["Tipo"] = df["Tipo"].fillna("Outros")
        cache["mtime"] = version
        cache["df"] = df.copy()
        return df.copy(deep=False)


def agg_pedagio(df: pd.DataFrame) -> dict:
    registros = df.shape[0]
    custo_total = float(pd.to_numeric(df.get("Custo"), errors="coerce").sum()) if "Custo" in df else 0.0
    meses_distintos = df["Mes"].dropna().unique() if "Mes" in df else []
    media_mensal = float(custo_total / len(meses_distintos)) if len(meses_distintos) else 0.0
    media_valores = float(custo_total / registros) if registros else 0.0

    tipo_totais = df.groupby("Tipo", dropna=False)["Custo"].sum() if "Tipo" in df.columns and not df.empty else pd.Series(dtype="float64")
    resultado = {
        "custo_total": custo_total,
        "total_lancamentos": registros,
        "media_mensal": media_mensal,
        "ticket_medio": media_valores,
        "media_valores": media_valores,
        "gasto_pedagio": float(tipo_totais.get("Pedagio", 0.0)),
        "gasto_ipva": float(tipo_totais.get("IPVA", 0.0)),
        "gasto_seguro": float(tipo_totais.get("Seguro", 0.0)),
        "custo_mensal": _group_sum(df, "Mes", "Custo", sort_by="group"),
        "gasto_por_tipo": _group_sum(df, "Tipo", "Custo"),
        "gasto_por_placa": _group_sum(df, "PLACA", "Custo"),
        "meses": _unique_sorted(df, "Mes"),
        "tipos": _unique_sorted(df, "Tipo"),
        "placas": _unique_sorted(df, "PLACA"),
        "custo_semana": _weekly_series(df, "Data", "Custo", "Custo"),
    }
    if "Categoria" in df.columns:
        resultado["segmentos"] = _unique_sorted(df, "Categoria")
        resultado["gasto_por_categoria"] = _group_sum(df, "Categoria", "Custo")
    else:
        resultado["segmentos"] = []
        resultado["gasto_por_categoria"] = {"Categoria": [], "Custo": []}
    return resultado


def data_comb(params: dict | None = None) -> dict:
    params = params or {}
    df = _exclude_vex(load_combustivel())
    km_rodados = _COMBUSTIVEL_CACHE.get("km_rodados_mensal")

    ano = _parse_int(_param(params, "ano"))
    meses = _parse_mes_list(params.get("mes"))
    placa = _param(params, "placa")
    posto = _param(params, "posto")
    combustivel = _param(params, "combustivel")
    segmento = _param(params, "segmento")

    if placa and placa != "Todos":
        df = df[df["PLACA"] == _normalize_plate_value(placa)]
    if posto and posto != "Todos":
        df = df[df["POSTOS"] == posto]
    if combustivel and combustivel != "Todos":
        df = df[df["Combustivel"] == combustivel]
    if segmento and segmento != "Todos" and "Categoria" in df.columns:
        df = df[df["Categoria"] == segmento]

    anos_disponiveis = sorted({*_unique_years(df), *df.attrs.get("anos_sheets", [])})
    df_meses = _filter_by_period(df, ano=ano) if ano is not None else df
    meses_disponiveis = _unique_sorted(df_meses, "Mes")

    if ano is not None:
        df = _filter_by_period(df, ano=ano)
    if meses:
        df = df[df["Mes"].isin(meses)]

    km_override = None
    if isinstance(km_rodados, pd.DataFrame) and not km_rodados.empty:
        km_override = km_rodados.copy()
        if placa and placa != "Todos":
            km_override = km_override[km_override["PLACA"] == _normalize_plate_value(placa)]
        if ano is not None:
            km_override = km_override[pd.to_datetime(km_override["Mes"], errors="coerce").dt.year == ano]
        if meses:
            km_override = km_override[km_override["Mes"].isin(meses)]
        if not df.empty and "Mes" in df.columns and "PLACA" in df.columns:
            allowed = df[["Mes", "PLACA"]].dropna().drop_duplicates()
            if not allowed.empty:
                km_override = km_override.merge(allowed, on=["Mes", "PLACA"], how="inner")
        if km_override.empty:
            km_override = None

    resultado = agg_combustivel(df, km_override=km_override if ano == 2026 else None)
    resultado["anos"] = anos_disponiveis
    resultado["meses"] = meses_disponiveis
    return resultado


def data_manu(params: dict | None = None) -> dict:
    params = params or {}
    df = _exclude_vex(load_manutencao())

    ano = _parse_int(_param(params, "ano"))
    meses = _parse_mes_list(params.get("mes"))
    placa = _param(params, "placa")
    oficina = _param(params, "oficina")
    segmento = _param(params, "segmento")

    if placa and placa != "Todos":
        df = df[df["PLACA"] == _normalize_plate_value(placa)]
    if oficina and oficina != "Todos":
        df = df[df["OFICINA"] == oficina]
    if segmento and segmento != "Todos" and "Categoria" in df.columns:
        df = df[df["Categoria"] == segmento]

    anos_disponiveis = sorted({*_unique_years(df), *df.attrs.get("anos_sheets", [])})
    df_meses = _filter_by_period(df, ano=ano) if ano is not None else df
    meses_disponiveis = _unique_sorted(df_meses, "Mes")

    if ano is not None:
        df = _filter_by_period(df, ano=ano)
    if meses:
        df = df[df["Mes"].isin(meses)]

    resultado = agg_manutencao(df)
    resultado["anos"] = anos_disponiveis
    resultado["meses"] = meses_disponiveis
    return resultado


def data_hoteis(params: dict | None = None) -> dict:
    params = params or {}
    df_total = _exclude_vex(load_hoteis())
    totais_gerais = agg_hoteis(df_total)
    df = df_total.copy()

    ano = _parse_int(_param(params, "ano"))
    meses = _parse_mes_list(params.get("mes"))
    cidade = _param(params, "cidade")
    hotel = _param(params, "hotel")

    if cidade and cidade != "Todos":
        df = df[df["Cidade"] == cidade]
    if hotel and hotel != "Todos":
        df = df[df["Hotel"] == hotel]

    anos_disponiveis = sorted({*_unique_years(df), *df.attrs.get("anos_sheets", [])})
    df_meses = _filter_by_period(df, ano=ano) if ano is not None else df
    meses_disponiveis = _unique_sorted(df_meses, "Mes")

    if ano is not None:
        df = _filter_by_period(df, ano=ano)
    if meses:
        df = df[df["Mes"].isin(meses)]

    resultado = agg_hoteis(df)
    resultado["valor_sabado_total"] = totais_gerais.get("valor_sabado", 0.0)
    resultado["valor_nao_planejado_total"] = totais_gerais.get("valor_nao_planejado", 0.0)
    resultado["anos"] = anos_disponiveis
    resultado["meses"] = meses_disponiveis
    return resultado


def data_pedagio(params: dict | None = None) -> dict:
    params = params or {}
    df = _exclude_vex(load_pedagio())

    ano = _parse_int(_param(params, "ano"))
    meses = _parse_mes_list(params.get("mes"))
    placa = _param(params, "placa")
    tipo = _param(params, "tipo")
    segmento = _param(params, "segmento")

    if placa and placa != "Todos":
        df = df[df["PLACA"] == _normalize_plate_value(placa)]
    if tipo and tipo != "Todos":
        df = df[df["Tipo"] == _normalize_tipo_value(tipo)]
    if segmento and segmento != "Todos" and "Categoria" in df.columns:
        df = df[df["Categoria"] == segmento]

    anos_disponiveis = sorted({*_unique_years(df), *df.attrs.get("anos_sheets", [])})
    df_meses = _filter_by_period(df, ano=ano) if ano is not None else df
    meses_disponiveis = _unique_sorted(df_meses, "Mes")

    if ano is not None:
        df = _filter_by_period(df, ano=ano)
    if meses:
        df = df[df["Mes"].isin(meses)]

    resultado = agg_pedagio(df)
    resultado["anos"] = anos_disponiveis
    resultado["meses"] = meses_disponiveis
    return resultado


def data_vex(params: dict | None = None) -> dict:
    params = params or {}
    ano = _parse_int(_param(params, "ano"))
    meses = _parse_mes_list(params.get("mes"))
    placa = _param(params, "placa")

    df_comb = _only_vex(load_combustivel())
    df_manu = _only_vex(load_manutencao())
    df_hoteis = load_hoteis().iloc[0:0].copy()
    df_ped = _only_vex(load_pedagio())
    km_rodados = _COMBUSTIVEL_CACHE.get("km_rodados_mensal")

    anos_disponiveis: set[int] = set()
    for df_src in (df_comb, df_manu, df_hoteis, df_ped):
        anos_disponiveis.update(_unique_years(df_src))
        anos_disponiveis.update(df_src.attrs.get("anos_sheets", []))

    def _meses_disponiveis(*dfs: pd.DataFrame) -> list[str]:
        frames = [df for df in dfs if not df.empty and "Mes" in df.columns]
        if not frames:
            return []
        merged = pd.concat(frames, ignore_index=True)
        return _unique_sorted(merged, "Mes")

    df_meses_base = [df_comb, df_manu, df_hoteis, df_ped]
    if ano is not None:
        df_meses_base = [_filter_by_period(df, ano=ano) for df in df_meses_base]
    meses_disponiveis = _meses_disponiveis(*df_meses_base)

    df_placas_base = [df_comb, df_manu, df_ped]
    if ano is not None:
        df_placas_base = [_filter_by_period(df, ano=ano) for df in df_placas_base]
    if meses:
        df_placas_base = [df[df["Mes"].isin(meses)] for df in df_placas_base]
    frames = [df[["PLACA"]] for df in df_placas_base if "PLACA" in df.columns]
    placas_disponiveis = _unique_sorted(pd.concat(frames, ignore_index=True), "PLACA") if frames else []

    def _apply_filters(df: pd.DataFrame) -> pd.DataFrame:
        if ano is not None:
            df = _filter_by_period(df, ano=ano)
        if meses:
            df = df[df["Mes"].isin(meses)]
        if placa and placa != "Todos" and "PLACA" in df.columns:
            df = df[df["PLACA"] == _normalize_plate_value(placa)]
        return df

    df_comb = _apply_filters(df_comb)
    df_manu = _apply_filters(df_manu)
    df_hoteis = _apply_filters(df_hoteis)
    df_ped = _apply_filters(df_ped)

    km_override = None
    if ano == 2026 and isinstance(km_rodados, pd.DataFrame) and not km_rodados.empty:
        km_override = km_rodados.copy()
        if ano is not None:
            km_override = km_override[pd.to_datetime(km_override["Mes"], errors="coerce").dt.year == ano]
        if meses:
            km_override = km_override[km_override["Mes"].isin(meses)]
        if placa and placa != "Todos":
            km_override = km_override[km_override["PLACA"] == _normalize_plate_value(placa)]
        if not df_comb.empty and "Mes" in df_comb.columns and "PLACA" in df_comb.columns:
            allowed = df_comb[["Mes", "PLACA"]].dropna().drop_duplicates()
            if not allowed.empty:
                km_override = km_override.merge(allowed, on=["Mes", "PLACA"], how="inner")

    total_comb = float(pd.to_numeric(df_comb.get("Custo"), errors="coerce").sum()) if "Custo" in df_comb else 0.0
    if km_override is not None and "Km Rodados" in km_override.columns:
        km_total = float(pd.to_numeric(km_override["Km Rodados"], errors="coerce").sum())
    else:
        km_total = float(pd.to_numeric(df_comb.get("Km Rodados"), errors="coerce").sum()) if "Km Rodados" in df_comb else 0.0
    litros_total = float(pd.to_numeric(df_comb.get("Litros"), errors="coerce").sum()) if "Litros" in df_comb else 0.0
    total_manu = float(pd.to_numeric(df_manu.get("Custo"), errors="coerce").sum()) if "Custo" in df_manu else 0.0
    total_hoteis = 0.0
    total_ped = float(pd.to_numeric(df_ped.get("Custo"), errors="coerce").sum()) if "Custo" in df_ped else 0.0
    total_vex = total_comb + total_manu + total_hoteis + total_ped

    monthly_map: dict[str, float] = {}
    for src, key in (
        (_group_sum(df_comb, "Mes", "Custo", sort_by="group"), "Custo"),
        (_group_sum(df_manu, "Mes", "Custo", sort_by="group"), "Custo"),
        (_group_sum(df_ped, "Mes", "Custo", sort_by="group"), "Custo"),
    ):
        for mes_val, valor in zip(src.get("Mes", []), src.get(key, [])):
            monthly_map[mes_val] = monthly_map.get(mes_val, 0.0) + float(valor or 0)

    placa_totais: dict[str, float] = {}
    for df_src, col_valor in ((df_comb, "Custo"), (df_manu, "Custo"), (df_ped, "Custo")):
        if df_src.empty or "PLACA" not in df_src.columns or col_valor not in df_src.columns:
            continue
        df_val = df_src.dropna(subset=["PLACA"]).copy()
        df_val[col_valor] = pd.to_numeric(df_val[col_valor], errors="coerce")
        for placa_val, total in df_val.groupby("PLACA")[col_valor].sum().items():
            key = str(placa_val).strip()
            placa_totais[key] = placa_totais.get(key, 0.0) + float(total or 0.0)

    placas_ordenadas = sorted(placa_totais.items(), key=lambda item: item[1], reverse=True)
    meses_sorted = sorted(monthly_map.keys())
    return {
        "anos": sorted(anos_disponiveis),
        "meses": meses_disponiveis,
        "placas": placas_disponiveis,
        "total_vex": round(total_vex, 2),
        "combustivel_total": round(total_comb, 2),
        "manutencao_total": round(total_manu, 2),
        "hoteis_total": round(total_hoteis, 2),
        "pedagio_total": round(total_ped, 2),
        "km_total": round(km_total, 2),
        "litros_total": round(litros_total, 2),
        "km_por_litro": round((km_total / litros_total) if litros_total else 0.0, 3),
        "custo_por_km": round((total_comb / km_total) if km_total else 0.0, 4),
        "custo_por_litro": round((total_comb / litros_total) if litros_total else 0.0, 4),
        "mensal_total": {"Mes": meses_sorted, "Valor": [round(monthly_map[mes], 2) for mes in meses_sorted]},
        "por_area": {"Area": ["Combustivel", "Manutencao", "Pedagio"], "Valor": [round(total_comb, 2), round(total_manu, 2), round(total_ped, 2)]},
        "gasto_por_placa": {"PLACA": [item[0] for item in placas_ordenadas], "Valor": [round(item[1], 2) for item in placas_ordenadas]},
    }


def _warm_data_caches(*, blocking: bool = False) -> None:
    loaders = (
        (load_combustivel, "combustivel"),
        (load_manutencao, "manutencao"),
        (load_hoteis, "hoteis"),
        (load_pedagio, "pedagio/seguro/IPVA"),
    )

    def _run() -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(loaders)) as pool:
            future_map = {pool.submit(loader): label for loader, label in loaders}
            for future, label in future_map.items():
                try:
                    future.result()
                except Exception as exc:  # pragma: no cover
                    print(f"Aviso: nao foi possivel pre-carregar {label} ({exc})")

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()


if os.environ.get("JR_SKIP_WARM_CACHE", "").strip().lower() not in {"1", "true", "yes"}:
    _warm_data_caches(blocking=os.environ.get("WARM_CACHE_SYNC", "").strip().lower() in {"1", "true", "yes"})


def _safe_total(
    loader,
    aggregator,
    key: str,
    value_col: str | None = None,
    *,
    ano: int | None = None,
    mes: int | None = None,
    meses: list[int] | None = None,
) -> dict:
    try:
        df = loader()
    except Exception as exc:  # pragma: no cover
        return {"status": "erro", "motivo": str(exc), "valor": None, "categorias": None, "anos_sheets": []}

    periodos_disponiveis: list[str] = []
    anos_sheets = df.attrs.get("anos_sheets", [])
    if "Mes" in df.columns:
        period_series = pd.to_datetime(df["Mes"], errors="coerce").dt.to_period("M")
        periodos_disponiveis = sorted({str(periodo) for periodo in period_series.dropna().unique()})

    df = _filter_by_period(df, ano=ano, mes=mes, meses=meses or [])
    try:
        resumo = aggregator(df)
    except Exception as exc:  # pragma: no cover
        return {"status": "erro", "motivo": str(exc), "valor": None, "categorias": None, "anos_sheets": anos_sheets}

    valor = float(resumo.get(key, 0.0)) if resumo else 0.0
    categorias = None
    if value_col and value_col in df.columns and "Categoria" in df.columns:
        df_categoria = df.copy()
        df_categoria[value_col] = pd.to_numeric(df_categoria[value_col], errors="coerce")
        grupos = (
            df_categoria.groupby(
                df_categoria["Categoria"].astype("string").str.strip().str.title().replace({"": "Outros"}).fillna("Outros")
            )[value_col].sum()
        )
        if not grupos.empty:
            categorias = {categoria: float(valor_cat) for categoria, valor_cat in grupos.items() if pd.notna(valor_cat)}

    return {
        "status": "ok",
        "motivo": None,
        "valor": valor,
        "categorias": categorias,
        "periodos": periodos_disponiveis,
        "anos_sheets": anos_sheets,
    }


def compute_overview_totals(*, ano: int | None = None, mes: int | None = None, meses_lista: list[int] | None = None) -> dict:
    ano = _parse_int(ano)
    mes = _parse_int(mes, min_value=1, max_value=12)
    meses_lista = list(meses_lista or [])
    if mes is not None and mes not in meses_lista:
        meses_lista.append(mes)

    areas = {
        "combustivel": (load_combustivel, agg_combustivel, "custo_total", "Custo"),
        "manutencao": (load_manutencao, agg_manutencao, "custo_total", "Custo"),
        "hoteis": (load_hoteis, agg_hoteis, "valor_total", "Valor"),
        "pedagio": (load_pedagio, agg_pedagio, "custo_total", "Custo"),
    }

    chave_cache = tuple(_CACHE_MAP[nome]["mtime"] for nome in ("combustivel", "manutencao", "hoteis", "pedagio"))
    use_cache = ano is None and mes is None and not meses_lista
    if use_cache and _OVERVIEW_CACHE["mtimes"] == chave_cache and _OVERVIEW_CACHE["dados"] is not None:
        return _OVERVIEW_CACHE["dados"]

    detalhes = {}
    total_geral = 0.0
    segmento_totais = defaultdict(float)
    periodos_unicos: set[str] = set()
    anos_extra: set[int] = set()
    max_workers = len(areas) if ano is None and mes is None else 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_safe_total, loader, aggregator, chave, valor_col, ano=ano, mes=mes, meses=meses_lista): nome
            for nome, (loader, aggregator, chave, valor_col) in areas.items()
        }
        for future in concurrent.futures.as_completed(future_map):
            nome = future_map[future]
            resultado = future.result()
            detalhes[nome] = resultado
            if resultado["valor"] is not None:
                total_geral += resultado["valor"]
            for categoria, valor in (resultado.get("categorias") or {}).items():
                segmento_totais[categoria] += valor
            for periodo in resultado.get("periodos") or []:
                if periodo:
                    periodos_unicos.add(periodo)
            for ano_sheet in resultado.get("anos_sheets") or []:
                try:
                    anos_extra.add(int(ano_sheet))
                except (TypeError, ValueError):
                    continue

    segmentos_dict = {categoria: float(valor) for categoria, valor in segmento_totais.items()}
    periodos_ordenados = sorted(periodos_unicos)
    anos_disponiveis = sorted({int(p.split("-")[0]) for p in periodos_ordenados if "-" in p})
    if anos_extra:
        anos_disponiveis = sorted(set(anos_disponiveis) | anos_extra)
    periodos_base = periodos_ordenados
    if ano is not None:
        periodos_base = [periodo for periodo in periodos_ordenados if periodo.startswith(f"{ano}-")]
    meses_disponiveis = sorted({int(p.split("-")[1]) for p in periodos_base if "-" in p})

    detalhes["total_geral"] = float(total_geral)
    detalhes["segmentos"] = segmentos_dict
    detalhes["total_transporte"] = segmentos_dict.get("Transporte", 0.0)
    detalhes["total_vex"] = segmentos_dict.get("Vex", 0.0)
    detalhes["periodos_disponiveis"] = periodos_ordenados
    detalhes["anos_disponiveis"] = anos_disponiveis
    detalhes["meses_disponiveis"] = meses_disponiveis
    detalhes["filtro"] = {"ano": ano, "mes": mes, "meses": meses_lista}

    if use_cache:
        _OVERVIEW_CACHE["mtimes"] = tuple(_CACHE_MAP[nome]["mtime"] for nome in ("combustivel", "manutencao", "hoteis", "pedagio"))
        _OVERVIEW_CACHE["dados"] = detalhes
    return detalhes


def data_overview(params: dict | None = None) -> dict:
    params = params or {}
    ano = _parse_int(_param(params, "ano"))
    mes = _parse_int(_param(params, "mes"), min_value=1, max_value=12)
    meses_lista = _parse_mes_int_list(params.get("mes"))
    if mes is not None and mes not in meses_lista:
        meses_lista.append(mes)
    return compute_overview_totals(ano=ano, mes=mes, meses_lista=meses_lista)


def main() -> None:
    from streamlit_app import main as streamlit_main

    os.environ.setdefault("JR_SKIP_WARM_CACHE", "1")
    streamlit_main()


if __name__ == "__main__":
    main()
