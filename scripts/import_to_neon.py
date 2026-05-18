from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

os.environ.setdefault("JR_SKIP_WARM_CACHE", "1")
os.environ["JR_DATA_SOURCE"] = "excel"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def _clean_for_sql(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned = cleaned.where(pd.notna(cleaned), None)
    return cleaned


def _write_table(engine, table: str, df: pd.DataFrame) -> None:
    _clean_for_sql(df).to_sql(
        table,
        engine,
        if_exists="replace",
        index=False,
        chunksize=1000,
        method="multi",
    )


def _create_index(conn, table: str, columns: list[str], name: str) -> None:
    existing = set(pd.read_sql_query(text(f'SELECT * FROM "{table}" LIMIT 0'), conn).columns)
    selected = [column for column in columns if column in existing]
    if not selected:
        return
    columns_sql = ", ".join(f'"{column}"' for column in selected)
    conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({columns_sql})'))


def _write_metadata(engine, metadata: dict[str, object]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS "{app.DB_METADATA_TABLE}" (
                    "key" TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        for key, value in metadata.items():
            conn.execute(
                text(
                    f"""
                    INSERT INTO "{app.DB_METADATA_TABLE}" ("key", value_json, updated_at)
                    VALUES (:key, :value_json, CURRENT_TIMESTAMP)
                    ON CONFLICT (key)
                    DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {"key": key, "value_json": json.dumps(value, ensure_ascii=False, default=str)},
            )


def import_to_neon() -> dict[str, int]:
    engine = app._db_engine()

    combustivel = app.load_combustivel()
    combustivel_km = app._COMBUSTIVEL_CACHE.get("km_rodados_mensal")
    if combustivel_km is None:
        combustivel_km = pd.DataFrame(columns=["Mes", "PLACA", "Km Rodados"])
    manutencao = app.load_manutencao()
    hoteis = app.load_hoteis()
    pedagio = app.load_pedagio()

    datasets = {
        "combustivel": combustivel,
        "combustivel_km": combustivel_km,
        "manutencao": manutencao,
        "hoteis": hoteis,
        "pedagio": pedagio,
    }

    for dataset, df in datasets.items():
        _write_table(engine, app.DB_TABLES[dataset], df)

    with engine.begin() as conn:
        _create_index(conn, app.DB_TABLES["combustivel"], ["Mes", "PLACA"], "idx_dashboard_combustivel_mes_placa")
        _create_index(conn, app.DB_TABLES["combustivel"], ["Categoria"], "idx_dashboard_combustivel_categoria")
        _create_index(conn, app.DB_TABLES["combustivel_km"], ["Mes", "PLACA"], "idx_dashboard_combustivel_km_mes_placa")
        _create_index(conn, app.DB_TABLES["manutencao"], ["Mes", "PLACA"], "idx_dashboard_manutencao_mes_placa")
        _create_index(conn, app.DB_TABLES["manutencao"], ["Categoria"], "idx_dashboard_manutencao_categoria")
        _create_index(conn, app.DB_TABLES["hoteis"], ["Mes"], "idx_dashboard_hoteis_mes")
        _create_index(conn, app.DB_TABLES["pedagio"], ["Mes", "PLACA"], "idx_dashboard_pedagio_mes_placa")
        _create_index(conn, app.DB_TABLES["pedagio"], ["Categoria"], "idx_dashboard_pedagio_categoria")

    version = datetime.now(timezone.utc).isoformat()
    metadata: dict[str, object] = {
        "import.version": version,
        "import.imported_at": version,
        "import.source": "excel",
    }
    for dataset, df in datasets.items():
        metadata[f"{dataset}.version"] = version
        metadata[f"{dataset}.rows"] = int(len(df))
        metadata[f"{dataset}.anos_sheets"] = df.attrs.get("anos_sheets", [])
    _write_metadata(engine, metadata)

    return {dataset: int(len(df)) for dataset, df in datasets.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa as planilhas do dashboard para o Neon/Postgres.")
    parser.add_argument("--database-url", help="Connection string do Neon. Tambem pode usar DATABASE_URL ou NEON_DATABASE_URL.")
    args = parser.parse_args()

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    if not app._database_url():
        print("DATABASE_URL/NEON_DATABASE_URL nao configurada. Cole a connection string do Neon antes de importar.")
        return 1

    counts = import_to_neon()
    print("Importacao concluida:")
    for dataset, rows in counts.items():
        print(f"- {dataset}: {rows} linhas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
