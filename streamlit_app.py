from __future__ import annotations

import base64
import calendar
import hashlib
import html
import importlib
import json
import math
import os
import re
import subprocess
import unicodedata
import zipfile
from io import BytesIO
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("JR_SKIP_WARM_CACHE", "1")

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import app as backend
from route_pdf import parse_route_pdf

# O Streamlit pode recarregar este arquivo sem reiniciar o processo Python.
# Nesse intervalo, o modulo ``app`` pode continuar em memoria na versao anterior
# ao deploy. Recarregue-o quando a tela depender de recursos ou colunas novas.
_backend_features_ready = all(
    hasattr(backend, feature)
    for feature in (
        "load_rodagem_rota",
        "load_aluguel_veiculos",
        "upsert_dashboard_records",
        "append_missing_dashboard_records",
        "load_alertas_vex",
        "load_velocidade",
        "load_rotas",
        "load_rota_entregas",
        "import_route_manifests",
        "auto_complete_freighter_routes",
        "update_route_operation",
        "update_route_history_rows",
    )
)
_backend_aluguel_period_ready = {"Inicio", "Fim"}.issubset(
    set(getattr(backend, "_ALUGUEL_VEICULOS_COLUMNS", []))
)
_backend_aluguel_monthly_ready = getattr(backend, "BACKEND_BUILD_VERSION", "") == "aluguel-multiplicar-meses-v1"
_backend_pedagio_chart_ready = getattr(backend, "PEDAGIO_CHART_VERSION", "") == "all-types-v1"
_backend_routes_ready = getattr(backend, "ROUTES_BUILD_VERSION", "") == "rotas-pdf-v15"
if not _backend_features_ready or not _backend_aluguel_period_ready or not _backend_aluguel_monthly_ready or not _backend_pedagio_chart_ready or not _backend_routes_ready:
    backend = importlib.reload(backend)


JR_BLUE = "#1C2D6B"
JR_RED = "#BE1E2D"
MUTED = "#6B7280"
CARD_BORDER = "#c2d2f3"
LOGO_PATH = Path(__file__).parent / "static" / "logo-jr.png"
CURRENT_YEAR = date.today().year
APP_VERSION = "route-manifests-pdf-v18"
RANK_ROUTES_ENABLED = True
ROUTE_CACHE_TTL_SECONDS = max(int(os.environ.get("JR_ROUTE_CACHE_TTL_SECONDS", "180") or 180), 30)
DATA_EDITOR_PAGE_SIZE = 100
DATA_EDITOR_ALL_PAGES = "__todos_os_registros__"
TABLE_FILTER_EMPTY_LABEL = "Sem informação"
BR_TZ = ZoneInfo("America/Sao_Paulo")
FREIGHT_UNLOAD_KG_PER_HOUR = 350.0
FREIGHT_AVERAGE_SPEED_KMH = 80.0
FREIGHT_HOTEL_DAY_HOURS = 10.0
FREIGHT_WORKDAY_HOURS = 8.0
FREIGHT_REFERENCE_CREW_SIZE = 2.0
FREIGHT_FLEET_AVERAGE_LABEL = "Média da frota (sem placa)"
CATEGORY_OPTIONS = ["Transporte", "Freteiro", "Empilhadeira", "Estoque", "Vex", "Equipamento"]
CADASTRO_TABS = ["Placas", "Rotas", "Empilhadeiras", "Combustível", "KM mensal", "Manutenção", "Pneus", "Hotéis", "Peso", "Velocidade", "Pedágio/Extras", "Aluguel de veículos"]
PEDAGIO_TIPO_OPTIONS = ["Pedágio", "Extras", "Táxi", "IPVA", "Seguro", "Licenciamento", "DPVAT", "Outros"]
PEDAGIO_OPTIONAL_PLATE_TYPES = {"Extras", "Táxi"}
BACKUP_INTERVAL_DAYS = 7
BACKUP_TABLES = [
    ("placas", "Placas", "placas", backend.load_placas),
    (
        "salarios_transporte",
        "Salários Transporte",
        "salarios_transporte",
        backend.load_salarios_transporte,
    ),
    ("combustivel", "Combustível", "combustivel", backend.load_combustivel),
    ("combustivel_km", "KM mensal", "km_mensal", backend.load_combustivel_km),
    ("empilhadeira_horas", "Horas empilhadeiras", "horas_empilhadeiras", backend.load_empilhadeira_horas),
    ("combustiveis", "Combustíveis", "combustiveis", backend.load_combustiveis),
    ("postos", "Postos", "postos", backend.load_postos),
    ("manutencao", "Manutenção", "manutencao", backend.load_manutencao),
    ("pneus", "Pneus", "pneus", backend.load_pneus),
    ("hoteis", "Hotéis", "hoteis", backend.load_hoteis),
    ("peso", "Peso", "peso", backend.load_peso),
    ("rodagem_rota", "Rodagem por rota", "rodagem_por_rota", backend.load_rodagem_rota),
    ("rotas", "Rotas importadas", "rotas", backend.load_rotas),
    ("rota_entregas", "Entregas das rotas", "rota_entregas", backend.load_rota_entregas),
    ("pedagio", "Pedágio e Extras", "pedagio_extras", backend.load_pedagio),
    ("aluguel_veiculos", "Aluguel de Veículos Vex", "aluguel_veiculos_vex", backend.load_aluguel_veiculos),
    ("alertas_vex", "Alertas Vex", "alertas_vex", backend.load_alertas_vex),
    ("velocidade", "Velocidade", "velocidade", backend.load_velocidade),
]

PLOTLY_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "displayModeBar": True,
    "scrollZoom": False,
    "toImageButtonOptions": {
        "format": "png",
        "filename": "grafico-jr-dashboard",
        "scale": 3,
    },
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}

MONTH_NAMES = [
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]
MONTH_ABBR = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
YEAR_SERIES_COLORS = [JR_BLUE, JR_RED, "#0F766E", "#D97706", "#7C3AED", "#4B5563", "#9CA3AF"]

ROUTES = {
    "combustivel": backend.data_comb,
    "manutencao": backend.data_manu,
    "hoteis": backend.data_hoteis,
    "pedagio": backend.data_pedagio,
    "vex": backend.data_vex,
    "frota": backend.data_frota,
    "alertas": backend.data_alertas_vex,
    "velocidade": backend.data_velocidade,
    "rotas": backend.data_rotas,
    "overview": backend.data_overview,
    "overview_options": backend.data_overview_options,
}

DASHBOARD_META = {
    "combustivel": {"label": "Combustível", "color": JR_BLUE, "supports_plate": True},
    "manutencao": {"label": "Manutenção", "color": JR_RED, "supports_plate": True},
    "hoteis": {"label": "Hotéis", "color": "#0F766E", "supports_plate": False},
    "pedagio": {"label": "Pedágio/Extras", "color": "#D97706", "supports_plate": True},
    "vex": {"label": "Vex", "color": "#7C3AED", "supports_plate": True},
    "frota": {"label": "Ranking da frota", "color": JR_BLUE, "supports_plate": True},
    "velocidade": {"label": "Velocidade", "color": "#0F766E", "supports_plate": True},
    "rotas": {"label": "Rotas", "color": JR_RED, "supports_plate": True},
}
COMPARE_ALLOWED_ROUTES = {"combustivel", "manutencao", "pedagio"}

COMPARE_SERIES = {
    "combustivel": {
        "monthly": ("custo_mensal", "Mes", "Custo"),
        "weekly": ("gasto_semana", "Dia", "Custo"),
        "plate": ("gasto_por_placa", "PLACA", "Custo"),
    },
    "manutencao": {
        "monthly": ("custo_mensal", "Mes", "Custo"),
        "weekly": ("custo_semana", "Dia", "Custo"),
        "plate": ("gasto_por_placa", "PLACA", "Custo"),
    },
    "hoteis": {
        "monthly": ("valor_mensal", "Mes", "Valor"),
        "weekly": ("valor_semana", "Dia", "Valor"),
        "plate": None,
    },
    "pedagio": {
        "monthly": ("custo_mensal", "Mes", "Custo"),
        "weekly": ("custo_semana", "Dia", "Custo"),
        "plate": ("gasto_por_placa", "PLACA", "Custo"),
    },
    "vex": {
        "monthly": ("mensal_total", "Mes", "Valor"),
        "weekly": None,
        "plate": ("gasto_por_placa", "PLACA", "Valor"),
    },
}

RANK_ORDER_OPTIONS = {
    "total": "Gasto total",
    "combustivel": "Combustível",
    "manutencao": "Manutenção",
    "pedagio": "Pedágio/Extras",
    "diarias": "Diárias",
    "peso": "Peso",
    "valor_entregas": "Valor entregas",
    "dias_servico": "Dias de serviço",
}


def logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

        :root {{
          color-scheme: light;
          --jr-blue: {JR_BLUE};
          --jr-red: {JR_RED};
          --muted: {MUTED};
          --card-border: {CARD_BORDER};
          --radius: 14px;
          --glass-bg: rgba(255,255,255,.32);
          --glass-bg-strong: rgba(255,255,255,.48);
          --glass-border: rgba(255,255,255,.84);
          --glass-blue-border: rgba(194,210,243,.58);
          --glass-refraction: linear-gradient(135deg, rgba(255,255,255,.68), rgba(255,255,255,.20) 44%, rgba(217,228,255,.18) 72%, rgba(255,255,255,.48));
          --glass-shadow: 0 24px 60px rgba(16,24,40,.10), inset 0 1px 0 rgba(255,255,255,.98), inset 0 -20px 46px rgba(255,255,255,.18), inset 18px 0 32px rgba(255,255,255,.10);
          --glass-shadow-soft: 0 14px 34px rgba(16,24,40,.075), inset 0 1px 0 rgba(255,255,255,.94), inset 0 -16px 34px rgba(255,255,255,.14);
          --glass-blur: none;
          --glass-hover-shadow: 0 32px 82px rgba(16,24,40,.17), 0 12px 30px rgba(28,45,107,.11), inset 0 1px 0 rgba(255,255,255,1), inset 0 -24px 58px rgba(255,255,255,.24), inset 22px 0 42px rgba(255,255,255,.14);
        }}

        html, body, [class*="css"] {{
          font-family: "Inter", sans-serif;
        }}

        html,
        body,
        .stApp {{
          color-scheme: light !important;
          scroll-behavior: auto !important;
          max-width: 100%;
          overflow-x: hidden;
        }}

        /*
         * O dashboard foi desenhado com uma paleta clara. Estes estilos evitam
         * que o tema escuro do navegador/Streamlit altere somente os controles
         * nativos e deixe a interface com dois temas misturados.
         */
        .stApp div[data-baseweb="select"] > div,
        .stApp div[data-baseweb="input"] > div,
        .stApp div[data-baseweb="textarea"],
        .stApp [data-testid="stTextInput"] input,
        .stApp [data-testid="stNumberInput"] input,
        .stApp [data-testid="stDateInput"] input,
        .stApp [data-testid="stTimeInput"] input,
        .stApp textarea {{
          background-color: #fff !important;
          color: var(--jr-blue) !important;
          -webkit-text-fill-color: var(--jr-blue) !important;
          border-color: rgba(194,210,243,.90) !important;
        }}

        .stApp div[data-baseweb="select"] *,
        .stApp div[data-baseweb="input"] *,
        .stApp div[data-baseweb="textarea"] *,
        .stApp [data-testid="stTextInput"] input::placeholder,
        .stApp [data-testid="stNumberInput"] input::placeholder,
        .stApp [data-testid="stDateInput"] input::placeholder,
        .stApp textarea::placeholder {{
          color: var(--jr-blue) !important;
          -webkit-text-fill-color: var(--jr-blue) !important;
        }}

        .stApp div[data-baseweb="select"] svg,
        .stApp div[data-baseweb="input"] svg {{
          color: var(--jr-blue) !important;
          fill: var(--jr-blue) !important;
        }}

        div[data-baseweb="popover"],
        div[data-baseweb="popover"] > div,
        div[data-baseweb="menu"],
        ul[role="listbox"],
        li[role="option"] {{
          color-scheme: light !important;
          background-color: #fff !important;
          color: var(--jr-blue) !important;
        }}

        li[role="option"]:hover,
        li[role="option"][aria-selected="true"] {{
          background-color: #f1f5ff !important;
          color: var(--jr-blue) !important;
        }}

        .stApp [data-testid="stCheckbox"] label > span:first-child {{
          color-scheme: light !important;
          background-color: #fff;
          border-radius: 4px;
        }}

        .stApp [data-testid="stFileUploaderDropzone"],
        .stApp [data-testid="stFileUploaderFile"],
        .stApp [data-testid="stExpander"],
        .stApp details,
        .stApp summary {{
          color-scheme: light !important;
          background-color: rgba(255,255,255,.92) !important;
          color: var(--jr-blue) !important;
        }}

        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] {{
          scroll-behavior: auto !important;
          max-width: 100%;
          overflow-x: visible;
        }}

        .stApp {{
          background: linear-gradient(180deg, #fbfdff 0%, #f5f7fc 100%);
          color: var(--jr-blue);
          position: relative;
          overflow-x: hidden;
        }}

        .stApp::before,
        .stApp::after {{
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          z-index: 0;
          background-repeat: repeat;
          will-change: auto;
        }}

        .stApp::before {{
          opacity: .72;
          filter: none;
          background-image:
            radial-gradient(circle at 7% 14%, rgba(28,45,107,.32) 0 1px, transparent 2.1px),
            radial-gradient(circle at 18% 78%, rgba(28,45,107,.20) 0 1.4px, transparent 2.5px),
            radial-gradient(circle at 31% 43%, rgba(255,255,255,.78) 0 1px, transparent 2px),
            radial-gradient(circle at 42% 19%, rgba(28,45,107,.26) 0 1.2px, transparent 2.4px),
            radial-gradient(circle at 55% 68%, rgba(28,45,107,.18) 0 1.5px, transparent 2.7px),
            radial-gradient(circle at 69% 32%, rgba(255,255,255,.68) 0 1px, transparent 2.2px),
            radial-gradient(circle at 76% 91%, rgba(28,45,107,.25) 0 1px, transparent 2.2px),
            radial-gradient(circle at 88% 53%, rgba(28,45,107,.18) 0 1.6px, transparent 2.8px),
            radial-gradient(circle at 96% 23%, rgba(28,45,107,.30) 0 1.1px, transparent 2.3px);
          background-size: 620px 540px;
          animation: none;
        }}

        .stApp::after {{
          opacity: .64;
          filter: none;
          background-image:
            radial-gradient(circle at 11% 37%, rgba(190,30,45,.24) 0 1.2px, transparent 2.4px),
            radial-gradient(circle at 21% 9%, rgba(190,30,45,.15) 0 1px, transparent 2.2px),
            radial-gradient(circle at 34% 84%, rgba(190,30,45,.20) 0 1.4px, transparent 2.7px),
            radial-gradient(circle at 48% 28%, rgba(255,255,255,.72) 0 1px, transparent 2.1px),
            radial-gradient(circle at 58% 61%, rgba(190,30,45,.18) 0 1.1px, transparent 2.3px),
            radial-gradient(circle at 73% 16%, rgba(190,30,45,.24) 0 1.5px, transparent 2.8px),
            radial-gradient(circle at 81% 74%, rgba(255,255,255,.62) 0 1px, transparent 2.1px),
            radial-gradient(circle at 93% 47%, rgba(190,30,45,.17) 0 1.3px, transparent 2.5px);
          background-size: 760px 610px;
          animation: none;
        }}

        @keyframes jr-particles-drift {{
          from {{ transform: translate3d(-5vw, -4vh, 0) rotate(.001deg); }}
          to {{ transform: translate3d(16vw, 13vh, 0) rotate(.001deg); }}
        }}

        @keyframes jr-particles-float {{
          from {{ transform: translate3d(14vw, 11vh, 0) rotate(.001deg); }}
          to {{ transform: translate3d(-18vw, -14vh, 0) rotate(.001deg); }}
        }}

        @media (prefers-reduced-motion: reduce) {{
          .stApp::before,
          .stApp::after {{
            animation: none;
          }}
        }}

        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"],
        .block-container {{
          background: transparent;
          position: relative;
          z-index: 1;
        }}

        header[data-testid="stHeader"],
        #MainMenu,
        footer {{
          visibility: hidden;
          height: 0;
        }}

        .block-container {{
          padding: 0 24px 40px;
          max-width: 1400px;
        }}

        .jr-topbar {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          flex-wrap: wrap;
          padding: 18px 32px;
          margin: 0 calc(50% - 50vw) -2px;
          width: 100vw;
          max-width: 100vw;
          box-sizing: border-box;
          background: var(--jr-blue);
          box-shadow:
            0 4px 12px rgba(0,0,0,.2);
          clip-path: none;
          position: sticky;
          top: 0;
          z-index: 10;
        }}

        .jr-brand {{
          display: flex;
          align-items: center;
          gap: 14px;
        }}

        .jr-logo {{
          width: 44px;
          height: 44px;
          object-fit: contain;
        }}

        .jr-topbar h1 {{
          margin: 0;
          color: #fff;
          font-size: 22px;
          line-height: 1.2;
          font-weight: 800;
          letter-spacing: .2px;
        }}

        .jr-back {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 38px;
          padding: 8px 16px;
          border-radius: 8px;
          background: var(--jr-red);
          color: #fff !important;
          font-size: 14px;
          font-weight: 700;
          text-decoration: none !important;
          box-shadow: 0 3px 8px rgba(0,0,0,.12);
        }}

        .st-key-comb_filterbar,
        .st-key-manu_filterbar,
        .st-key-hotel_filterbar,
        .st-key-ped_filterbar,
        .st-key-vex_filterbar,
        .st-key-vel_filterbar,
        .st-key-rank_filterbar {{
          background: var(--jr-blue);
          margin: -2px calc(50% - 50vw) 58px;
          width: 100vw;
          max-width: 100vw;
          padding: 2px 32px 18px;
          box-sizing: border-box;
          box-shadow:
            0 4px 12px rgba(0,0,0,.2);
          clip-path: none;
          position: sticky;
          top: 80px;
          z-index: 9;
          isolation: isolate;
          overflow: visible;
        }}

        .st-key-comb_filterbar > div,
        .st-key-manu_filterbar > div,
        .st-key-hotel_filterbar > div,
        .st-key-ped_filterbar > div,
        .st-key-vex_filterbar > div,
        .st-key-vel_filterbar > div,
        .st-key-rank_filterbar > div {{
          position: relative;
          z-index: 1;
        }}

        .st-key-comb_filterbar label,
        .st-key-manu_filterbar label,
        .st-key-hotel_filterbar label,
        .st-key-ped_filterbar label,
        .st-key-vex_filterbar label,
        .st-key-vel_filterbar label,
        .st-key-rank_filterbar label {{
          display: none !important;
        }}

        .st-key-rank_filterbar .st-key-rank_incluir_hoteis,
        .st-key-rank_filterbar .st-key-rank_incluir_salario {{
          width: 100%;
          height: 38px;
          display: flex;
          align-items: stretch;
          margin-top: 0;
          padding-top: 0;
          transform: translateY(-8px);
        }}

        .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-rank_incluir_hoteis),
        .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]):has(.st-key-rank_incluir_salario) {{
          align-self: flex-start;
          padding-top: 0 !important;
        }}

        .st-key-rank_filterbar .st-key-rank_incluir_hoteis > div,
        .st-key-rank_filterbar .st-key-rank_incluir_salario > div {{
          width: 100%;
        }}

        .st-key-rank_filterbar .st-key-rank_incluir_hoteis [data-testid="stCheckbox"],
        .st-key-rank_filterbar .st-key-rank_incluir_salario [data-testid="stCheckbox"] {{
          width: 100%;
          height: 38px;
          display: flex;
          align-items: stretch;
          margin: 0;
        }}

        .st-key-rank_filterbar .st-key-rank_incluir_hoteis label,
        .st-key-rank_filterbar .st-key-rank_incluir_salario label {{
          display: inline-flex !important;
          width: 100%;
          height: 38px;
          min-height: 38px;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 0 10px;
          border: 1px solid rgba(255,255,255,.25);
          border-radius: 8px;
          background: rgba(255,255,255,.96);
          color: var(--jr-blue);
          box-shadow: 0 3px 8px rgba(0,0,0,.12);
          font-weight: 800;
          box-sizing: border-box;
        }}

        .st-key-rank_filterbar .st-key-rank_incluir_hoteis p,
        .st-key-rank_filterbar .st-key-rank_incluir_salario p {{
          color: var(--jr-blue);
          font-size: 13px;
          font-weight: 800;
          line-height: 1;
          margin: 0;
        }}

        .st-key-rank_route_popover [data-testid="stPopover"] > button,
        .st-key-rank_month_popover [data-testid="stPopover"] > button,
        .st-key-rank_plate_popover [data-testid="stPopover"] > button {{
          width: 100%;
          min-height: 38px;
          justify-content: space-between;
          border: 1px solid rgba(255,255,255,.25);
          border-radius: 8px;
          background: #fff;
          color: var(--jr-blue);
          box-shadow: 0 3px 8px rgba(0,0,0,.12);
          font-weight: 600;
        }}

        .st-key-rank_route_popover [data-testid="stPopover"] > button:hover,
        .st-key-rank_month_popover [data-testid="stPopover"] > button:hover,
        .st-key-rank_plate_popover [data-testid="stPopover"] > button:hover {{
          border-color: rgba(194,210,243,.95);
          background: #fff;
          color: var(--jr-blue);
        }}

        div[data-testid="stPopoverBody"]:has(.st-key-rank_mes) {{
          width: min(440px, calc(100vw - 24px));
          min-width: min(440px, calc(100vw - 24px));
          padding: 14px;
        }}

        .st-key-rank_mes button {{
          min-width: 82px;
          justify-content: center;
          border-radius: 8px !important;
          font-weight: 700;
        }}

        div[data-testid="stPopoverBody"]:has(.st-key-rank_placa) {{
          width: min(390px, calc(100vw - 24px));
          min-width: min(390px, calc(100vw - 24px));
          padding: 14px;
        }}

        .st-key-rank_placa div[data-baseweb="select"] > div {{
          min-height: 44px;
          border: 1px solid rgba(194,210,243,.95) !important;
          border-radius: 9px;
          background: #fff !important;
          box-shadow: none !important;
        }}

        .st-key-rank_placa div[data-baseweb="select"] input {{
          flex: 1 1 220px !important;
          width: 100% !important;
          min-width: 220px !important;
          opacity: 1 !important;
          visibility: visible !important;
          color: var(--jr-blue) !important;
          -webkit-text-fill-color: var(--jr-blue) !important;
          caret-color: var(--jr-red) !important;
          background: transparent !important;
          font-size: 14px !important;
          font-weight: 600 !important;
          text-shadow: none !important;
        }}

        .st-key-rank_placa div[data-baseweb="select"] input::placeholder {{
          opacity: .72 !important;
          color: var(--muted) !important;
          -webkit-text-fill-color: var(--muted) !important;
        }}

        .st-key-rank_placa span[data-baseweb="tag"] {{
          background: var(--jr-red) !important;
          border-radius: 7px !important;
        }}

        .st-key-comb_filterbar div[data-baseweb="select"] > div,
        .st-key-manu_filterbar div[data-baseweb="select"] > div,
        .st-key-hotel_filterbar div[data-baseweb="select"] > div,
        .st-key-ped_filterbar div[data-baseweb="select"] > div,
        .st-key-vex_filterbar div[data-baseweb="select"] > div,
        .st-key-vel_filterbar div[data-baseweb="select"] > div,
        .st-key-rank_filterbar div[data-baseweb="select"] > div {{
          min-height: 38px;
          border-radius: 8px;
          border: 1px solid rgba(255,255,255,.25);
          background: #fff;
          box-shadow: 0 3px 8px rgba(0,0,0,.12);
        }}

        .st-key-comb_filterbar [data-testid="stHorizontalBlock"],
        .st-key-manu_filterbar [data-testid="stHorizontalBlock"],
        .st-key-hotel_filterbar [data-testid="stHorizontalBlock"],
        .st-key-ped_filterbar [data-testid="stHorizontalBlock"],
        .st-key-vex_filterbar [data-testid="stHorizontalBlock"],
        .st-key-vel_filterbar [data-testid="stHorizontalBlock"],
        .st-key-rank_filterbar [data-testid="stHorizontalBlock"] {{
          gap: 12px;
          align-items: stretch;
          flex-wrap: wrap !important;
        }}

        .st-key-comb_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
        .st-key-manu_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
        .st-key-hotel_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
        .st-key-ped_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
        .st-key-vex_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
        .st-key-vel_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
        .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]) {{
          flex: 1 1 150px !important;
          min-width: 145px !important;
          max-width: none !important;
        }}

        .st-key-rank_filterbar {{
          margin-bottom: 34px;
          padding: 6px 18px 12px;
        }}

        .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]) > div,
        .st-key-rank_filterbar .stButton,
        .st-key-rank_filterbar [data-testid="stPopover"] {{
          width: 100%;
        }}

        @media (min-width: 1550px) {{
          .st-key-rank_filterbar [data-testid="stHorizontalBlock"] {{
            display: grid !important;
            grid-template-columns: .65fr 1fr 1.05fr 1.1fr 1.15fr .78fr .82fr 1fr .88fr .68fr;
            gap: 8px !important;
            align-items: start;
          }}

          .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]) {{
            width: 100% !important;
            min-width: 0 !important;
            max-width: none !important;
            flex: none !important;
          }}
        }}

        @media (min-width: 781px) and (max-width: 1549px) {{
          .st-key-rank_filterbar [data-testid="stHorizontalBlock"] {{
            display: grid !important;
            grid-template-columns: .7fr 1fr 1fr 1fr 1fr;
            gap: 8px !important;
            align-items: start;
          }}

          .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]) {{
            width: 100% !important;
            min-width: 0 !important;
            max-width: none !important;
            flex: none !important;
          }}
        }}

        .filter-back {{
          display: inline-flex;
          width: 100%;
          min-height: 38px;
          align-items: center;
          justify-content: center;
          border-radius: 8px;
          background: var(--jr-red);
          color: #fff !important;
          font-size: 14px;
          font-weight: 800;
          text-decoration: none !important;
          box-shadow: 0 3px 8px rgba(190,30,45,.25);
          white-space: nowrap;
        }}

        .home-wrapper {{
          max-width: 1100px;
          margin: 0 auto;
          padding: 0 0 48px;
          display: flex;
          flex-direction: column;
          gap: 48px;
        }}

        .home-header {{
          max-width: 1100px;
          margin: 0 auto 48px;
          background:
            linear-gradient(145deg, rgba(255,255,255,.78), rgba(255,255,255,.52)),
            rgba(255,255,255,.58);
          border: 1px solid rgba(255,255,255,.78);
          border-radius: 18px;
          padding: 40px;
          box-shadow:
            0 22px 54px rgba(16,24,40,.10),
            inset 0 1px 0 rgba(255,255,255,.78);
          backdrop-filter: blur(22px) saturate(145%);
          -webkit-backdrop-filter: blur(22px) saturate(145%);
          display: flex;
          flex-direction: column;
          gap: 28px;
          position: relative;
          overflow: hidden;
          isolation: isolate;
        }}

        .home-header::before {{
          content: "";
          position: absolute;
          left: -140px;
          bottom: -130px;
          width: 520px;
          height: 330px;
          background:
            radial-gradient(ellipse at 28% 72%, rgba(190,30,45,.24), rgba(190,30,45,.12) 34%, transparent 68%),
            radial-gradient(ellipse at 58% 52%, rgba(190,30,45,.13), transparent 62%);
          filter: blur(3px);
          z-index: 0;
        }}

        .home-header::after {{
          content: "";
          position: absolute;
          right: -60px;
          top: -60px;
          width: 220px;
          height: 220px;
          background-image: radial-gradient(circle, rgba(190,30,45,.18) 1.2px, transparent 1.8px);
          background-size: 18px 18px;
          opacity: .52;
          transform: rotate(12deg);
          filter: drop-shadow(0 0 6px rgba(190,30,45,.22));
          z-index: 0;
        }}

        .home-brand {{
          display: flex;
          align-items: flex-start;
          gap: 24px;
          position: relative;
          z-index: 1;
        }}

        .home-logo {{
          width: 72px;
          height: 72px;
          border-radius: 16px;
          box-shadow: 0 8px 22px rgba(0,0,0,0.12);
          object-fit: contain;
        }}

        .home-eyebrow {{
          margin: 0;
          font-size: 13px;
          text-transform: uppercase;
          letter-spacing: .18em;
          color: var(--muted);
          font-weight: 600;
        }}

        .home-header h1 {{
          margin: 0;
          font-size: 34px;
          font-weight: 800;
          color: var(--jr-blue);
        }}

        .home-title-row {{
          display: flex;
          align-items: center;
          flex-wrap: wrap;
          gap: 12px;
          margin: 4px 0 12px;
        }}

        .home-freight-link {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 34px;
          padding: 0 14px;
          border-radius: 999px;
          background: var(--jr-red);
          color: #fff !important;
          font-size: 12px;
          font-weight: 800;
          text-decoration: none !important;
          white-space: nowrap;
          box-shadow: 0 8px 18px rgba(190,30,45,.20);
        }}

        .home-freight-link:hover {{
          background: #a51924;
        }}

        .home-subtitle {{
          margin: 0;
          font-size: 16px;
          color: #4B5563;
          max-width: 560px;
        }}

        .home-cta,
        .home-outline {{
          align-self: flex-start;
          border-radius: 999px;
          text-decoration: none !important;
          font-weight: 700;
          position: relative;
          z-index: 1;
        }}

        .home-cta {{
          background: var(--jr-red);
          color: #fff !important;
          padding: 12px 24px;
          box-shadow: 0 10px 24px rgba(190,30,45,0.25);
        }}

        .home-header-actions {{
          position: absolute;
          top: 24px;
          right: 24px;
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 8px;
          z-index: 2;
        }}

        .home-last-update {{
          margin: 0;
          padding: 4px 9px;
          border-radius: 999px;
          background: rgba(255,255,255,.70);
          border: 1px solid rgba(28,45,107,.10);
          color: rgba(28,45,107,.62);
          font-size: 10.5px;
          line-height: 1.25;
          font-weight: 700;
          white-space: nowrap;
          backdrop-filter: blur(10px);
        }}

        .home-admin-link {{
          min-height: 38px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 0 16px;
          border-radius: 999px;
          border: 1.5px solid rgba(28,45,107,.16);
          background: rgba(255,255,255,.86);
          color: var(--jr-blue) !important;
          font-size: 13px;
          font-weight: 800;
          text-decoration: none !important;
          box-shadow: 0 10px 24px rgba(16,24,40,.10);
          backdrop-filter: blur(10px);
        }}

        .home-alert-link {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 27px;
          padding: 0 11px;
          border-radius: 999px;
          background: rgba(190,30,45,.10);
          border: 1px solid rgba(190,30,45,.24);
          color: var(--jr-red) !important;
          font-size: 11px;
          font-weight: 800;
          text-decoration: none !important;
        }}

        .st-key-alertas_shell {{
          max-width: 1180px;
          margin: 28px auto 48px;
        }}

        .st-key-frete_shell {{
          max-width: 1120px;
          margin: 30px auto 52px;
        }}

        .frete-intro {{
          margin-bottom: 20px;
          padding: 26px 28px;
          border: 1px solid rgba(194,210,243,.72);
          border-radius: 18px;
          background: rgba(255,255,255,.72);
          box-shadow: 0 10px 28px rgba(16,24,40,.08);
        }}

        .frete-intro h2 {{
          margin: 0 0 8px;
          color: var(--jr-blue);
          font-size: clamp(24px, 3vw, 34px);
        }}

        .frete-intro p {{
          max-width: 780px;
          margin: 0;
          color: #4B5563;
          line-height: 1.6;
        }}

        .frete-mode-active {{
          display: flex;
          min-height: 58px;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 12px 16px;
          border: 1.5px solid rgba(190,30,45,.34);
          border-radius: 14px;
          background: rgba(190,30,45,.07);
          color: var(--jr-blue);
          font-weight: 800;
        }}

        .frete-mode-active span {{
          padding: 4px 9px;
          border-radius: 999px;
          background: var(--jr-red);
          color: #fff;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: .05em;
        }}

        .st-key-frete_mode_disabled button {{
          min-height: 58px;
          border-radius: 14px;
          font-weight: 800;
        }}

        .st-key-frete_form {{
          margin-top: 20px;
          padding: 24px;
          border: 1px solid rgba(194,210,243,.66);
          border-radius: 18px;
          background: rgba(255,255,255,.74);
          box-shadow: 0 10px 28px rgba(16,24,40,.08);
        }}

        .st-key-frete_form [data-testid="stForm"] {{
          border: 0;
          padding: 0;
          background: transparent;
        }}

        .frete-result-hero {{
          margin-top: 22px;
          padding: 28px;
          border-radius: 18px;
          background: linear-gradient(135deg, #17265d, var(--jr-blue));
          color: #fff;
          box-shadow: 0 16px 34px rgba(28,45,107,.22);
        }}

        .frete-result-grid {{
          display: grid;
          grid-template-columns: 1.25fr .75fr;
          gap: 28px;
          align-items: stretch;
        }}

        .frete-result-item--cost {{
          display: flex;
          flex-direction: column;
          justify-content: center;
          padding-left: 28px;
          border-left: 1px solid rgba(255,255,255,.24);
        }}

        .frete-result-label {{
          margin: 0 0 8px;
          font-size: 12px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .08em;
          opacity: .78;
        }}

        .frete-result-value {{
          margin: 0;
          font-size: clamp(34px, 6vw, 54px);
          font-weight: 900;
          line-height: 1;
        }}

        .frete-result-value--cost {{
          font-size: clamp(28px, 4vw, 40px);
          color: #fff;
        }}

        .frete-result-note {{
          margin: 12px 0 0;
          color: rgba(255,255,255,.82);
          font-size: 13px;
        }}

        .frete-breakdown {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
          gap: 14px;
          margin: 16px 0 0;
        }}

        .frete-breakdown-card {{
          padding: 18px;
          border: 1px solid rgba(194,210,243,.62);
          border-radius: 14px;
          background: rgba(255,255,255,.82);
          box-shadow: 0 6px 18px rgba(16,24,40,.06);
        }}

        .frete-breakdown-card p {{
          margin: 0 0 8px;
          color: var(--muted);
          font-size: 11px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .05em;
        }}

        .frete-breakdown-card strong {{
          color: var(--jr-blue);
          font-size: 22px;
        }}

        .frete-memory {{
          margin-top: 16px;
          padding: 18px 20px;
          border-left: 4px solid var(--jr-red);
          border-radius: 12px;
          background: rgba(255,255,255,.72);
          color: #4B5563;
          line-height: 1.65;
        }}

        .frete-memory strong {{
          color: var(--jr-blue);
        }}

        .st-key-cadastro_shell {{
          max-width: 1120px;
          margin: 28px auto 48px;
          padding: 28px;
          border: 1px solid rgba(255,255,255,.74);
          border-radius: var(--radius);
          background: rgba(255,255,255,.76);
          box-shadow: 0 8px 22px rgba(16,24,40,.10);
          backdrop-filter: blur(14px);
        }}

        .st-key-cadastro_shell [data-testid="stForm"] {{
          border: 1.5px solid var(--card-border);
          border-radius: var(--radius);
          background: rgba(255,255,255,.82);
          padding: 22px;
          box-shadow: 0 12px 28px rgba(16,24,40,.10);
        }}

        .st-key-cadastro_tabs [role="radiogroup"] {{
          gap: 0;
          border-bottom: 1px solid rgba(15,23,42,.14);
          overflow-x: auto;
          padding-bottom: 0;
        }}

        .st-key-cadastro_tabs [role="radiogroup"] label {{
          min-height: 42px;
          padding: 0 12px;
          border-radius: 0;
          border: 0 !important;
          border-bottom: 2px solid transparent !important;
          background: transparent !important;
          color: rgba(15,23,42,.78);
          font-size: 14px;
          white-space: nowrap;
          box-shadow: none !important;
        }}

        .st-key-cadastro_tabs [role="radiogroup"] label:has(input:checked) {{
          color: #ff4650 !important;
          border-bottom-color: #ff4650 !important;
        }}

        .st-key-cadastro_shell .stButton > button,
        .st-key-cadastro_shell [data-testid="stFormSubmitButton"] button {{
          min-height: 42px;
          border-radius: 999px;
          font-weight: 800;
        }}

        .home-total-section {{
          background: rgba(244,247,253,0.68);
          border: 1px solid rgba(255,255,255,0.7);
          border-radius: var(--radius);
          padding: 32px;
          box-shadow: 0 6px 18px rgba(0,0,0,0.08);
          backdrop-filter: blur(12px);
        }}

        .st-key-home_total_section {{
          max-width: 1100px;
          margin: 0 auto 28px;
          background: rgba(244,247,253,0.68);
          border: 1px solid rgba(255,255,255,0.7);
          border-radius: var(--radius);
          padding: 32px;
          box-shadow: 0 6px 18px rgba(0,0,0,0.08);
          backdrop-filter: blur(12px);
        }}

        .st-key-home_total_section div[data-baseweb="select"] > div {{
          min-height: 34px;
          border-radius: 14px;
          border: 1px solid rgba(28,45,107,0.15);
          background: #fff;
          box-shadow: 0 4px 10px rgba(0,0,0,0.05);
        }}

        .st-key-home_total_section div[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
          min-height: 38px;
          padding-top: 4px;
          padding-bottom: 4px;
          align-items: flex-start;
        }}

        .st-key-home_total_section div[data-testid="stMultiSelect"] span[data-baseweb="tag"] {{
          max-width: 58px;
          min-height: 22px;
          margin: 2px 3px 2px 0;
          border-radius: 9px;
        }}

        .st-key-home_total_section div[data-testid="stMultiSelect"] span[data-baseweb="tag"] span {{
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 11px;
        }}

        .st-key-home_total_section .stButton > button {{
          min-height: 34px;
          border-radius: 999px;
          box-shadow: 0 8px 20px rgba(190,30,45,0.2);
        }}

        .home-export-bar {{
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
          margin: 6px 0 12px;
        }}

        .home-export-btn {{
          min-height: 40px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border: 1.5px solid var(--card-border);
          background: #f8f9ff;
          color: var(--jr-blue);
          font-weight: 800;
          border-radius: 12px;
          box-shadow: 0 8px 16px rgba(16,24,40,0.08);
        }}

        .home-total-grid,
        .kpis {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 20px;
        }}

        .home-total-stack {{
          display: grid;
          gap: 16px;
        }}

        .home-km-strip {{
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 12px;
          align-items: stretch;
        }}

        .home-total-card,
        .kpi {{
          background:
            linear-gradient(150deg, rgba(255,255,255,.92), rgba(255,255,255,.66)),
            rgba(255,255,255,.70);
          border: 1px solid rgba(194,210,243,.72);
          border-radius: 16px;
          padding: 18px 24px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          box-shadow:
            0 18px 44px rgba(16,24,40,.10),
            inset 0 1px 0 rgba(255,255,255,.82);
          backdrop-filter: blur(18px) saturate(140%);
          -webkit-backdrop-filter: blur(18px) saturate(140%);
        }}

        .home-total-card {{
          position: relative;
          overflow: hidden;
          min-height: 136px;
          border: 1px solid rgba(194,210,243,.72);
          box-shadow:
            0 18px 40px rgba(16,24,40,0.11),
            inset 0 1px 0 rgba(255,255,255,.88);
        }}

        .home-total-card::before {{
          content: "";
          position: absolute;
          inset: 0 0 auto 0;
          height: 4px;
          background: var(--home-accent, var(--jr-blue));
        }}

        .home-total-card::after {{
          content: "";
          position: absolute;
          top: -72px;
          right: -48px;
          width: 170px;
          height: 170px;
          border-radius: 999px;
          background: radial-gradient(circle, var(--home-glow, rgba(28,45,107,.13)), rgba(255,255,255,0) 68%);
          pointer-events: none;
        }}

        .home-total-card > * {{
          position: relative;
          z-index: 1;
        }}

        .home-total-card--money {{
          --home-accent: var(--jr-red);
          --home-glow: rgba(190,30,45,.16);
        }}

        .home-total-card--weight {{
          --home-accent: var(--jr-blue);
          --home-glow: rgba(28,45,107,.14);
        }}

        .home-total-card--vex {{
          --home-accent: #7C3AED;
          --home-glow: rgba(124,58,237,.15);
        }}

        .home-total-card--km {{
          min-height: 56px;
          padding: 12px 18px;
          flex-direction: row;
          align-items: center;
          justify-content: center;
          gap: 12px;
          border: 1px solid rgba(194,210,243,.9);
          border-radius: 12px;
          box-shadow: 0 10px 24px rgba(16,24,40,0.09);
        }}

        .home-total-card--km::before,
        .home-total-card--km::after {{
          display: none;
        }}

        .kpis {{
          margin: 18px 0 28px;
          gap: 28px;
        }}

        @media (min-width: 1200px) {{
          .st-key-frota_kpis .kpis {{
            grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
          }}
        }}

        .st-key-frota_kpis .kpi-section {{
          grid-column: 1 / -1;
        }}

        .kpi-sections {{
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 24px;
          margin: 18px 0 28px;
        }}

        .kpi-section--summary {{
          grid-column: 1 / -1;
        }}

        .kpi-section {{
          border: 1px solid rgba(194,210,243,.9);
          border-radius: var(--radius);
          padding: 18px;
          background: rgba(255,255,255,.46);
          box-shadow: 0 12px 28px rgba(16,24,40,0.08);
        }}

        .kpi-section-title {{
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 0 0 16px;
          color: var(--jr-blue);
          font-size: 13px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .05em;
        }}

        .kpi-section-title::before {{
          content: "";
          width: 32px;
          height: 4px;
          border-radius: 999px;
          background: var(--section-accent, var(--jr-red));
        }}

        .kpi-section .kpis {{
          margin: 0;
          gap: 18px;
        }}

        .kpi {{
          padding: 24px;
          min-height: 116px;
          align-items: center;
          justify-content: center;
          text-align: center;
          position: relative;
          overflow: hidden;
        }}

        .kpi::before {{
          content: "";
          position: absolute;
          inset: 0 0 auto 0;
          height: 4px;
          background: var(--kpi-accent, var(--jr-red));
        }}

        .home-total-label,
        .kpi-title {{
          margin: 0;
          font-size: 12px;
          letter-spacing: .05em;
          text-transform: uppercase;
          color: var(--muted);
          font-weight: 700;
          width: 100%;
          text-align: center;
        }}

        .home-total-card:not(.home-total-card--km) .home-total-label {{
          text-align: left;
          font-size: 13px;
          font-weight: 900;
          letter-spacing: .055em;
          color: #6B7280;
        }}

        .home-total-value {{
          margin: 0;
          font-size: 28px;
          font-weight: 800;
          color: var(--jr-blue);
          line-height: 1.2;
        }}

        .home-total-card:not(.home-total-card--km) .home-total-value {{
          position: relative;
          z-index: 1;
          margin-top: 8px;
          font-size: clamp(22px, 2vw, 30px);
          font-weight: 950;
          letter-spacing: 0;
          color: var(--home-accent, var(--jr-blue));
        }}

        .home-total-status {{
          margin: 0;
          font-size: 12px;
          color: #4B5563;
        }}

        .home-total-card:not(.home-total-card--km) .home-total-status {{
          position: relative;
          z-index: 1;
          margin-top: 8px;
          max-width: 360px;
          color: #4B5563;
          font-size: 14px;
          line-height: 1.55;
        }}

        .home-total-card--km .home-total-label,
        .home-total-card--km .home-total-status {{
          width: auto;
          text-align: left;
          font-size: 13px;
          font-weight: 900;
          letter-spacing: 0;
          text-transform: none;
          line-height: 1;
        }}

        .home-total-card--km .home-total-value {{
          color: var(--jr-red);
          font-size: 24px;
          line-height: 1;
          font-weight: 950;
        }}

        @media (max-width: 760px) {{
          .home-km-strip {{
            grid-template-columns: 1fr;
          }}

          .home-total-card--km {{
            justify-content: flex-start;
          }}
        }}

        .home-filter-row {{
          margin-top: 24px;
        }}

        .kpi-value {{
          font-size: clamp(18px, 1.8vw, 26px);
          font-weight: 800;
          color: var(--kpi-accent, var(--jr-red));
          line-height: 1.05;
          margin-top: 8px;
          overflow-wrap: anywhere;
          width: 100%;
          text-align: center;
        }}

        .home-grid {{
          max-width: 1100px;
          margin: 0 auto;
          display: grid;
          gap: 28px;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }}

        .home-card {{
          background:
            linear-gradient(145deg, rgba(255,255,255,.76), rgba(255,255,255,.48)),
            rgba(255,255,255,.58);
          border: 1px solid rgba(255,255,255,.82);
          border-radius: 18px;
          padding: 32px;
          box-shadow:
            0 22px 48px rgba(16,24,40,.10),
            inset 0 1px 0 rgba(255,255,255,.86);
          backdrop-filter: blur(22px) saturate(145%);
          -webkit-backdrop-filter: blur(22px) saturate(145%);
          display: flex;
          flex-direction: column;
          gap: 20px;
          position: relative;
          overflow: hidden;
          min-height: 330px;
          color: inherit !important;
          text-decoration: none !important;
          cursor: pointer;
          transition:
            transform .18s ease,
            box-shadow .18s ease,
            border-color .18s ease,
            background .18s ease;
        }}

        .home-card:hover {{
          transform: translateY(-4px);
          border-color: rgba(194,210,243,.96);
          box-shadow:
            0 28px 64px rgba(16,24,40,.14),
            inset 0 1px 0 rgba(255,255,255,.90);
        }}

        .home-card:focus-visible {{
          outline: 3px solid rgba(190,30,45,.26);
          outline-offset: 3px;
        }}

        .home-card::after {{
          content: "";
          position: absolute;
          inset: 0;
          background:
            radial-gradient(circle at 88% 8%, rgba(255,255,255,.72), transparent 18%),
            linear-gradient(140deg, rgba(28,45,107,0.06), transparent 65%);
          pointer-events: none;
        }}

        .home-card > * {{
          position: relative;
          z-index: 1;
        }}

        .home-chip {{
          display: inline-flex;
          align-self: flex-start;
          background: rgba(28,45,107,0.08);
          border: 1px solid rgba(255,255,255,.72);
          color: var(--jr-blue);
          padding: 6px 14px;
          border-radius: 999px;
          font-size: 13px;
          font-weight: 700;
          letter-spacing: .04em;
          margin-bottom: 12px;
        }}

        .home-card h2 {{
          margin: 0;
          font-size: 22px;
          color: var(--jr-blue);
        }}

        .home-card-text,
        .home-list,
        .home-footer p {{
          color: #4B5563;
          font-size: 15px;
        }}

        .home-list {{
          margin: 0;
          padding-left: 20px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }}

        .home-link {{
          margin-top: auto;
          align-self: flex-start;
          font-weight: 800;
          color: var(--jr-blue) !important;
          text-decoration: none !important;
          transition: transform .18s ease, color .18s ease;
        }}

        .home-card:hover .home-link {{
          transform: translateX(3px);
          color: var(--jr-red) !important;
        }}

        .home-footer {{
          max-width: 1100px;
          margin: 48px auto 0;
          background:
            linear-gradient(145deg, rgba(255,255,255,.76), rgba(255,255,255,.48)),
            rgba(255,255,255,.58);
          border: 1px solid rgba(255,255,255,.82);
          border-radius: 18px;
          padding: 36px;
          box-shadow:
            0 22px 48px rgba(16,24,40,.10),
            inset 0 1px 0 rgba(255,255,255,.86);
          backdrop-filter: blur(22px) saturate(145%);
          -webkit-backdrop-filter: blur(22px) saturate(145%);
        }}

        .home-footer h3 {{
          margin: 0 0 16px;
          font-size: 20px;
          color: var(--jr-blue);
        }}

        div[data-testid="stVerticalBlockBorderWrapper"] {{
          background:
            linear-gradient(150deg, rgba(255,255,255,.92), rgba(255,255,255,.68)),
            rgba(255,255,255,.70);
          border: 1px solid rgba(194,210,243,.76);
          border-radius: 16px;
          box-shadow:
            0 18px 44px rgba(16,24,40,.10),
            inset 0 1px 0 rgba(255,255,255,.84);
          backdrop-filter: blur(18px) saturate(140%);
          -webkit-backdrop-filter: blur(18px) saturate(140%);
        }}

        .chart-title {{
          margin: 0 0 8px;
          font-size: 12px;
          font-weight: 800;
          color: var(--jr-blue);
          position: relative;
          padding-bottom: 10px;
        }}

        .chart-title::after {{
          content: "";
          position: absolute;
          left: 0;
          bottom: 0;
          width: 32px;
          height: 3px;
          background: var(--jr-red);
          border-radius: 2px;
        }}

        .footer-note {{
          color: var(--muted);
          font-size: 13px;
          text-align: center;
          padding: 24px;
          margin-top: 40px;
          border-top: 1px solid #e5e7eb;
        }}

        div[data-testid="stSelectbox"] label,
        div[data-testid="stMultiSelect"] label {{
          color: var(--jr-blue);
          font-weight: 800;
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: .04em;
        }}

        .stButton > button {{
          background: var(--jr-red);
          color: #fff;
          border: none;
          border-radius: 10px;
          font-weight: 800;
          box-shadow: 0 3px 8px rgba(190,30,45,.25);
          white-space: nowrap;
        }}

        .stButton > button:hover {{
          color: #fff;
          border: none;
          background: #a51924;
        }}

        [class*="_export_"] button,
        [class*="_toggle_"] button {{
          background: #f8f9ff !important;
          color: var(--jr-blue) !important;
          border: 1.5px solid var(--card-border) !important;
          border-radius: 12px !important;
          box-shadow: 0 8px 16px rgba(16,24,40,0.08) !important;
        }}

        [class*="_download_"] button {{
          background: var(--jr-blue) !important;
          color: #fff !important;
          border: none !important;
          border-radius: 12px !important;
        }}

        [class*="_dashboard_controls"] {{
          margin: 14px 0 22px;
          padding: 0;
          border: 1px solid rgba(194,210,243,.85);
          border-radius: 14px;
          background: rgba(255,255,255,.70);
          box-shadow: 0 14px 34px rgba(16,24,40,.10);
          backdrop-filter: blur(12px);
          overflow: hidden;
        }}

        [class*="_dashboard_controls"] details {{
          border: 0 !important;
          background: transparent !important;
        }}

        [class*="_dashboard_controls"] summary {{
          min-height: 46px;
          padding: 0 16px !important;
          color: var(--jr-blue) !important;
          font-weight: 800 !important;
          border-bottom: 1px solid rgba(194,210,243,.72);
        }}

        [class*="_dashboard_controls"] details > div {{
          padding: 14px 16px 16px;
        }}

        .control-row-label {{
          margin: 2px 0 8px;
          color: var(--muted);
          font-size: 11px;
          font-weight: 800;
          letter-spacing: .06em;
          text-transform: uppercase;
        }}

        .control-row-spacer {{
          height: 12px;
        }}

        [class*="_dashboard_controls"] [data-testid="stHorizontalBlock"] {{
          gap: 10px;
          flex-wrap: wrap !important;
          align-items: stretch;
        }}

        [class*="_dashboard_controls"] :is([data-testid="column"], [data-testid="stColumn"]) {{
          display: flex;
          flex-direction: column;
          justify-content: stretch;
        }}

        [class*="_dashboard_controls"] .stButton,
        [class*="_dashboard_controls"] [data-testid="stDownloadButton"],
        [class*="_dashboard_controls"] [data-testid="stCheckbox"] {{
          width: 100%;
        }}

        [class*="_dashboard_controls"] .stButton > button,
        [class*="_dashboard_controls"] [data-testid="stDownloadButton"] button {{
          min-height: 40px;
        }}

        [class*="_dashboard_controls"] [data-testid="stCheckbox"] label {{
          width: 100%;
          min-height: 44px;
          display: inline-flex;
          align-items: center;
          justify-content: flex-start;
          gap: 8px;
          padding: 8px 12px;
          border: 1.5px solid var(--card-border);
          border-radius: 12px;
          background: rgba(248,249,255,.92);
          color: var(--jr-blue);
          box-shadow: 0 6px 12px rgba(16,24,40,0.08);
          font-weight: 800;
          box-sizing: border-box;
        }}

        [class*="_dashboard_controls"] [data-testid="stCheckbox"] p {{
          font-size: 12px;
          line-height: 1.2;
          font-weight: 800;
          color: var(--jr-blue);
        }}

        .table-counter-grid {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: stretch;
          margin: 12px 0 8px;
        }}

        .table-counter-card {{
          display: inline-flex;
          align-items: center;
          gap: 10px;
          margin: 0;
          padding: 10px 14px;
          border: 1px solid rgba(194,210,243,.9);
          border-radius: 12px;
          background: rgba(255,255,255,.78);
          box-shadow: 0 10px 22px rgba(16,24,40,.08);
          color: var(--muted);
          font-size: 13px;
          font-weight: 800;
        }}

        .table-counter-card--metric {{
          min-width: 168px;
        }}

        .table-counter-card strong {{
          color: var(--jr-red);
          font-size: 22px;
          line-height: 1;
          font-weight: 950;
        }}

        .ranking-header {{
          display: grid;
          grid-template-columns: .45fr .9fr repeat(4, 1.05fr) .85fr .75fr .8fr;
          gap: 12px;
          align-items: center;
          padding: 12px 16px;
          margin: 8px 0 10px;
          border: 1px solid rgba(194,210,243,.88);
          border-radius: 12px;
          background: rgba(255,255,255,.74);
          color: var(--muted);
          font-size: 11px;
          font-weight: 900;
          letter-spacing: .06em;
          text-transform: uppercase;
          box-shadow: 0 10px 24px rgba(16,24,40,.08);
        }}

        .st-key-frota_ranking_table [data-testid="stExpander"] {{
          border: 1px solid rgba(194,210,243,.95);
          border-radius: 12px;
          background: rgba(255,255,255,.84);
          box-shadow: 0 10px 24px rgba(16,24,40,.08);
          overflow: hidden;
        }}

        .st-key-frota_ranking_table [data-testid="stExpander"] details {{
          border: 0 !important;
          background: transparent !important;
        }}

        .st-key-frota_ranking_table [data-testid="stExpander"] summary {{
          min-height: 60px;
          padding: 0 18px !important;
          border-bottom: 1px solid rgba(194,210,243,.58);
        }}

        .st-key-frota_ranking_table [data-testid="stExpander"] summary p {{
          color: var(--jr-blue);
          font-weight: 900;
          font-size: 16px;
          line-height: 1.35;
        }}

        .ranking-native-table {{
          display: flex;
          flex-direction: column;
          gap: 10px;
        }}

        .ranking-native-row {{
          border: 1px solid rgba(194,210,243,.95);
          border-radius: 12px;
          background: rgba(255,255,255,.84) !important;
          box-shadow: 0 8px 18px rgba(16,24,40,.07);
          overflow: hidden;
        }}

        .ranking-native-row > summary {{
          min-height: 58px;
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 0 18px;
          border-bottom: 1px solid transparent;
          color: var(--jr-blue);
          cursor: pointer;
          font-size: 15px;
          line-height: 1.35;
          font-weight: 900;
          list-style: none;
        }}

        .ranking-native-row > summary::-webkit-details-marker {{
          display: none;
        }}

        .ranking-native-row > summary::before {{
          content: "›";
          flex: 0 0 auto;
          font-size: 22px;
          line-height: 1;
          transform: rotate(0deg);
          transition: transform .16s ease;
        }}

        .ranking-native-row[open] > summary {{
          border-bottom-color: rgba(194,210,243,.58);
        }}

        .ranking-native-row[open] > summary::before {{
          transform: rotate(90deg);
        }}

        .ranking-native-content {{
          padding: 14px 18px 18px;
        }}

        .ranking-detail-grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px;
          padding: 4px 0 8px;
        }}

        .ranking-detail-card {{
          min-height: 74px;
          padding: 12px;
          border: 1px solid rgba(194,210,243,.82);
          border-radius: 10px;
          background: linear-gradient(145deg, #fff, #f9fbff);
        }}

        .ranking-detail-label {{
          margin: 0 0 6px;
          color: var(--muted);
          font-size: 10px;
          font-weight: 900;
          letter-spacing: .06em;
          text-transform: uppercase;
        }}

        .ranking-detail-value {{
          margin: 0;
          color: var(--jr-red);
          font-size: 19px;
          line-height: 1.15;
          font-weight: 900;
        }}

        .ranking-row-summary,
        .ranking-versus-grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px;
          margin: 4px 0 14px;
        }}

        .ranking-row-summary {{
          grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
        }}

        .ranking-summary-item,
        .ranking-versus-card {{
          border: 1px solid rgba(194,210,243,.9);
          border-radius: 12px;
          background: #fff;
          box-shadow: 0 8px 18px rgba(16,24,40,.08);
          overflow: hidden;
        }}

        .ranking-summary-item {{
          padding: 12px;
        }}

        .ranking-summary-label {{
          margin: 0 0 5px;
          color: var(--muted);
          font-size: 10px;
          font-weight: 900;
          text-transform: uppercase;
          letter-spacing: .06em;
        }}

        .ranking-summary-value {{
          margin: 0;
          color: var(--jr-blue);
          font-size: 17px;
          font-weight: 900;
          line-height: 1.15;
        }}

        .ranking-versus-title {{
          margin: 18px 0 10px;
          color: var(--jr-blue);
          font-size: 18px;
          font-weight: 900;
        }}

        .ranking-versus-card {{
          padding: 16px;
          border-top: 4px solid var(--jr-blue);
        }}

        .ranking-versus-card h3 {{
          margin: 0 0 12px;
          color: var(--jr-blue);
          font-size: 18px;
          font-weight: 900;
        }}

        .ranking-versus-metric {{
          display: flex;
          justify-content: space-between;
          gap: 12px;
          padding: 8px 0;
          border-top: 1px solid rgba(229,231,235,.95);
          color: var(--jr-blue);
          font-size: 13px;
          font-weight: 800;
        }}

        .ranking-versus-metric span:first-child {{
          color: var(--muted);
          font-weight: 800;
        }}

        .ranking-versus-metric span:last-child {{
          color: var(--jr-red);
          text-align: right;
          font-weight: 900;
        }}

        .route-compare-card {{
          border-top-color: var(--route-accent, var(--jr-blue));
        }}

        .route-compare-card h3 {{
          color: var(--route-accent, var(--jr-blue));
        }}

        .route-compare-metric--gain span:last-child {{
          color: #15803d;
        }}

        .route-compare-metric--ratio span:last-child {{
          color: #d97706;
          font-size: 15px;
        }}

        .route-compare-note {{
          margin: -4px 0 14px;
          color: var(--muted);
          font-size: 13px;
          font-weight: 700;
        }}

        .st-key-frota_route_hotel_controls {{
          margin: 0 0 16px;
          padding: 14px;
          border: 1px solid rgba(194,210,243,.76);
          border-radius: 12px;
          background: rgba(255,255,255,.62);
          box-shadow: 0 8px 20px rgba(16,24,40,.06);
        }}

        .st-key-frota_route_hotel_controls [data-testid="stMarkdownContainer"] p {{
          margin: 0;
          color: var(--jr-blue);
          font-size: 12px;
          font-weight: 900;
        }}

        .st-key-frota_route_hotel_controls [data-testid="stToggle"] {{
          min-height: 42px;
          padding: 7px 10px;
          border: 1px solid rgba(194,210,243,.62);
          border-radius: 9px;
          background: rgba(255,255,255,.72);
        }}

        .st-key-frota_route_hotel_controls [data-testid="stToggle"] label {{
          width: 100%;
          color: var(--jr-blue);
          font-weight: 800;
        }}

        .route-compare-card-heading {{
          display: flex;
          gap: 10px;
          align-items: flex-start;
          justify-content: space-between;
        }}

        .route-compare-hotel-status {{
          flex: 0 0 auto;
          padding: 4px 8px;
          border-radius: 999px;
          background: rgba(15,118,110,.10);
          color: #0f766e;
          font-size: 10px;
          font-weight: 900;
          white-space: nowrap;
        }}

        .ranking-difference {{
          margin: 0 0 16px;
          padding: 16px;
          border: 1.5px solid rgba(194,210,243,.95);
          border-top: 4px solid var(--jr-red);
          border-radius: 12px;
          background: rgba(255,255,255,.92);
          box-shadow: 0 10px 24px rgba(16,24,40,.10);
        }}

        .ranking-difference h3 {{
          margin: 0 0 12px;
          color: var(--jr-blue);
          font-size: 17px;
          font-weight: 900;
        }}

        .ranking-difference-grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 10px;
        }}

        .ranking-difference-item {{
          padding: 12px;
          border-radius: 10px;
          background: #f8faff;
          border: 1px solid rgba(194,210,243,.72);
        }}

        .ranking-difference-label {{
          margin: 0 0 6px;
          color: var(--muted);
          font-size: 10px;
          font-weight: 900;
          letter-spacing: .06em;
          text-transform: uppercase;
        }}

        .ranking-difference-value {{
          margin: 0;
          color: var(--jr-red);
          font-size: 20px;
          line-height: 1.15;
          font-weight: 900;
        }}

        .ranking-difference-note {{
          margin: 4px 0 0;
          color: var(--jr-blue);
          font-size: 12px;
          font-weight: 800;
        }}

        .ranking-empty {{
          margin: 18px 0;
          padding: 18px;
          border: 1px solid rgba(194,210,243,.9);
          border-radius: 12px;
          background: rgba(255,255,255,.72);
          color: var(--muted);
          font-weight: 700;
        }}

        .dominance-panel {{
          margin-top: 14px;
          padding: 16px;
          border: 1px solid rgba(194,210,243,.80);
          border-radius: 14px;
          background:
            linear-gradient(150deg, rgba(255,255,255,.88), rgba(255,255,255,.62)),
            rgba(255,255,255,.70);
          box-shadow: inset 0 1px 0 rgba(255,255,255,.84);
        }}

        .dominance-title {{
          margin: 0 0 6px;
          color: var(--jr-blue);
          font-size: 15px;
          font-weight: 900;
        }}

        .dominance-note {{
          margin: 0 0 14px;
          color: var(--muted);
          font-size: 13px;
          font-weight: 700;
        }}

        .dominance-cities {{
          display: grid;
          gap: 8px;
          max-height: 360px;
          overflow-y: auto;
          padding-right: 4px;
        }}

        .dominance-city-row {{
          display: grid;
          grid-template-columns: minmax(130px, 1.25fr) minmax(82px, .75fr) repeat(3, minmax(84px, auto));
          gap: 10px;
          align-items: center;
          padding: 10px 12px;
          border: 1px solid rgba(194,210,243,.62);
          border-radius: 10px;
          background: rgba(255,255,255,.64);
        }}

        .dominance-city-row--head {{
          background: rgba(28,45,107,.06);
          border-color: rgba(194,210,243,.84);
        }}

        .dominance-city-name {{
          color: var(--jr-blue);
          font-weight: 900;
        }}

        .dominance-city-plate {{
          color: var(--jr-blue);
          font-size: 12px;
          font-weight: 900;
          white-space: nowrap;
        }}

        .dominance-city-metric {{
          color: var(--jr-red);
          font-size: 12px;
          font-weight: 900;
          text-align: right;
          white-space: nowrap;
        }}

        .dominance-panel--routes {{
          margin-top: 18px;
          padding: 20px;
          overflow: visible;
        }}

        .dominance-route-heading {{
          display: flex;
          gap: 18px;
          align-items: flex-start;
          justify-content: space-between;
          margin-bottom: 14px;
        }}

        .dominance-route-heading .dominance-title,
        .dominance-route-heading .dominance-note {{
          margin-bottom: 0;
        }}

        .dominance-route-heading .dominance-note {{
          margin-top: 6px;
        }}

        .dominance-route-count {{
          flex: 0 0 auto;
          padding: 7px 11px;
          border: 1px solid rgba(194,210,243,.72);
          border-radius: 999px;
          background: rgba(28,45,107,.06);
          color: var(--jr-blue);
          font-size: 11px;
          font-weight: 900;
          white-space: nowrap;
        }}

        .dominance-route-table {{
          max-height: 520px;
          gap: 7px;
          overflow-y: auto;
          scrollbar-gutter: stable;
          padding: 0 7px 2px 0;
        }}

        .dominance-route-table::-webkit-scrollbar {{
          width: 8px;
        }}

        .dominance-route-table::-webkit-scrollbar-track {{
          border-radius: 999px;
          background: rgba(28,45,107,.05);
        }}

        .dominance-route-table::-webkit-scrollbar-thumb {{
          border-radius: 999px;
          background: rgba(28,45,107,.26);
        }}

        .dominance-route-row {{
          min-height: 46px;
          grid-template-columns: minmax(240px, 1.6fr) minmax(90px, .65fr) repeat(3, minmax(90px, .55fr));
        }}

        .dominance-route-row--head {{
          position: sticky;
          top: 0;
          z-index: 2;
          min-height: 40px;
          background: rgba(244,247,253,.96) !important;
          box-shadow: 0 5px 12px rgba(28,45,107,.08) !important;
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
        }}

        .jr-topbar {{
          background:
            linear-gradient(135deg, rgba(28,45,107,.95), rgba(28,45,107,.82)),
            rgba(28,45,107,.88);
          border-bottom: 0;
          box-shadow:
            0 18px 44px rgba(7,15,40,.26),
            inset 0 1px 0 rgba(255,255,255,.14);
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
        }}

        .st-key-comb_filterbar,
        .st-key-manu_filterbar,
        .st-key-hotel_filterbar,
        .st-key-ped_filterbar,
        .st-key-vex_filterbar,
        .st-key-vel_filterbar,
        .st-key-rank_filterbar {{
          background:
            linear-gradient(135deg, rgba(28,45,107,.95), rgba(28,45,107,.82)),
            rgba(28,45,107,.88);
          border-bottom: 0;
          box-shadow:
            0 18px 44px rgba(7,15,40,.24);
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
        }}

        .home-header,
        .home-card,
        .home-footer,
        .st-key-cadastro_shell,
        .st-key-home_total_section,
        div[data-testid="stVerticalBlockBorderWrapper"],
        [class*="_dashboard_controls"],
        .kpi-section,
        .kpi,
        .home-total-card,
        .table-counter-card,
        .ranking-header,
        .st-key-frota_ranking_table [data-testid="stExpander"],
        .ranking-native-row,
        .ranking-detail-card,
        .ranking-summary-item,
        .ranking-versus-card,
        .ranking-difference,
        .ranking-difference-item,
        .ranking-empty,
        .dominance-panel,
        .dominance-city-row {{
          background:
            linear-gradient(145deg, rgba(255,255,255,.64), rgba(255,255,255,.30)),
            var(--glass-bg) !important;
          border-color: var(--glass-border) !important;
          box-shadow: var(--glass-shadow-soft) !important;
          backdrop-filter: var(--glass-blur);
          -webkit-backdrop-filter: var(--glass-blur);
        }}

        .home-header,
        .home-card,
        .home-footer,
        .home-total-card,
        .kpi,
        div[data-testid="stVerticalBlockBorderWrapper"] {{
          box-shadow: var(--glass-shadow) !important;
        }}

        .home-total-card,
        .kpi,
        .ranking-detail-card,
        .ranking-summary-item,
        .ranking-versus-card,
        .ranking-difference-item,
        .table-counter-card,
        .dominance-city-row {{
          border-color: rgba(194,210,243,.54) !important;
        }}

        .st-key-cadastro_shell [data-testid="stForm"] {{
          background:
            linear-gradient(145deg, rgba(255,255,255,.56), rgba(255,255,255,.28)),
            rgba(255,255,255,.40) !important;
          border-color: rgba(194,210,243,.56) !important;
          box-shadow: var(--glass-shadow-soft) !important;
          backdrop-filter: var(--glass-blur);
          -webkit-backdrop-filter: var(--glass-blur);
        }}

        .home-card,
        .home-total-card,
        .kpi,
        .ranking-detail-card,
        .ranking-versus-card,
        .dominance-panel,
        div[data-testid="stVerticalBlockBorderWrapper"] {{
          position: relative;
          overflow: hidden;
          isolation: isolate;
          transform: none;
          background-clip: padding-box;
          will-change: auto;
          transition:
            transform .28s cubic-bezier(.2,.8,.2,1),
            box-shadow .28s cubic-bezier(.2,.8,.2,1),
            border-color .28s ease,
            background .28s ease;
        }}

        .home-card::before,
        .home-total-card::after,
        .kpi::after,
        .ranking-detail-card::after,
        .ranking-versus-card::after,
        .dominance-panel::after,
        div[data-testid="stVerticalBlockBorderWrapper"]::after {{
          content: "";
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          border-radius: inherit;
          pointer-events: none;
          background:
            radial-gradient(circle at 16% 0%, rgba(255,255,255,.92), rgba(255,255,255,0) 22%),
            radial-gradient(circle at 92% 12%, rgba(255,255,255,.54), rgba(255,255,255,0) 18%),
            linear-gradient(112deg, rgba(255,255,255,0) 7%, rgba(255,255,255,.78) 19%, rgba(255,255,255,.12) 32%, rgba(255,255,255,0) 48%),
            linear-gradient(180deg, rgba(255,255,255,.46), rgba(255,255,255,.04) 42%, rgba(255,255,255,0) 72%);
          background-size: 100% 100%, 100% 100%, 190% 100%, 100% 100%;
          background-position: center, center, -84% 0, center;
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,.96),
            inset 0 0 0 1px rgba(255,255,255,.18),
            inset 0 -18px 38px rgba(255,255,255,.12);
          opacity: .66;
          transform: translateX(-8%) skewX(-10deg);
          transition:
            transform .72s cubic-bezier(.2,.8,.2,1),
            background-position .72s cubic-bezier(.2,.8,.2,1),
            opacity .28s ease,
            box-shadow .28s ease;
          z-index: 0;
          mix-blend-mode: screen;
        }}

        .home-card:hover,
        .home-total-card:hover,
        .kpi:hover,
        .ranking-detail-card:hover,
        .ranking-versus-card:hover,
        .dominance-panel:hover,
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
          background:
            linear-gradient(145deg, rgba(255,255,255,.68), rgba(255,255,255,.34)),
            var(--glass-bg) !important;
          border-color: rgba(194,210,243,.82) !important;
          box-shadow: 0 14px 30px rgba(16,24,40,.10) !important;
          backdrop-filter: var(--glass-blur);
          -webkit-backdrop-filter: var(--glass-blur);
          filter: none;
          transform: none;
        }}

        .home-card:hover::before,
        .home-total-card:hover::after,
        .kpi:hover::after,
        .ranking-detail-card:hover::after,
        .ranking-versus-card:hover::after,
        .dominance-panel:hover::after,
        div[data-testid="stVerticalBlockBorderWrapper"]:hover::after {{
          animation: none !important;
          opacity: .54;
          background-position: center, center, -84% 0, center;
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,.96),
            inset 0 0 0 1px rgba(255,255,255,.18),
            inset 0 -18px 38px rgba(255,255,255,.12);
          transform: translateX(-8%) skewX(-10deg);
        }}

        .st-key-frota_route_compare:hover,
        .st-key-frota_route_compare div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
          transform: none !important;
          filter: none !important;
          backdrop-filter: none !important;
          -webkit-backdrop-filter: none !important;
        }}

        .route-compare-card:hover {{
          transform: none !important;
          filter: none !important;
          background:
            linear-gradient(145deg, rgba(255,255,255,.68), rgba(255,255,255,.34)),
            var(--glass-bg) !important;
          border-color: rgba(194,210,243,.82) !important;
          box-shadow: 0 14px 30px rgba(16,24,40,.10) !important;
          backdrop-filter: var(--glass-blur) !important;
          -webkit-backdrop-filter: var(--glass-blur) !important;
        }}

        .route-compare-card:hover::after,
        .st-key-frota_route_compare:hover::after,
        .st-key-frota_route_compare div[data-testid="stVerticalBlockBorderWrapper"]:hover::after {{
          animation: none !important;
          opacity: .54 !important;
          transform: translateX(-8%) skewX(-10deg) !important;
          background-position: center, center, -84% 0, center !important;
        }}

        .route-compare-card:hover > * {{
          filter: none !important;
          transform: none !important;
        }}

        .home-card > *,
        .home-total-card > *,
        .kpi > *,
        .ranking-detail-card > *,
        .ranking-versus-card > *,
        .dominance-panel > *,
        div[data-testid="stVerticalBlockBorderWrapper"] > * {{
          position: relative;
          z-index: 1;
        }}

        div[data-baseweb="select"] > div,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input,
        div[data-testid="stDateInput"] input,
        textarea {{
          background: rgba(255,255,255,.58) !important;
          border: 1px solid rgba(255,255,255,.72) !important;
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,.90),
            0 8px 20px rgba(16,24,40,.07) !important;
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
        }}

        [class*="_export_"] button,
        [class*="_toggle_"] button,
        [data-testid="stDownloadButton"] button {{
          background:
            linear-gradient(145deg, rgba(255,255,255,.66), rgba(255,255,255,.30)),
            rgba(255,255,255,.48) !important;
          border-color: rgba(194,210,243,.62) !important;
          box-shadow:
            0 12px 28px rgba(16,24,40,.10),
            inset 0 1px 0 rgba(255,255,255,.90) !important;
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
        }}

        [class*="_dashboard_controls"] [data-testid="stDownloadButton"] button,
        .st-key-home_download_ready button {{
          background:
            linear-gradient(135deg, rgba(28,45,107,.96), rgba(28,45,107,.86)),
            var(--jr-blue) !important;
          color: #fff !important;
          border-color: rgba(255,255,255,.26) !important;
          box-shadow:
            0 14px 34px rgba(28,45,107,.22),
            inset 0 1px 0 rgba(255,255,255,.20) !important;
        }}

        [class*="_sheet_download_data"] button {{
          background:
            linear-gradient(135deg, rgba(28,45,107,.98), rgba(28,45,107,.88)),
            var(--jr-blue) !important;
          color: #fff !important;
          border-color: rgba(28,45,107,.82) !important;
          box-shadow:
            0 12px 28px rgba(28,45,107,.20),
            inset 0 1px 0 rgba(255,255,255,.20) !important;
        }}

        [class*="_sheet_download_data"] button *,
        [class*="_sheet_download_data"] button:hover * {{
          color: #fff !important;
        }}

        [class*="_sheet_download_example"] button {{
          background: rgba(255,255,255,.92) !important;
          color: var(--jr-blue) !important;
          border: 1.5px solid rgba(28,45,107,.34) !important;
          box-shadow:
            0 12px 28px rgba(16,24,40,.10),
            inset 0 1px 0 rgba(255,255,255,.96) !important;
        }}

        [class*="_sheet_download_example"] button *,
        [class*="_sheet_download_example"] button:hover * {{
          color: var(--jr-blue) !important;
        }}

        .stButton > button {{
          box-shadow:
            0 14px 30px rgba(190,30,45,.22),
            inset 0 1px 0 rgba(255,255,255,.24);
        }}

        /* Modo de renderização leve: evita repinturas caras durante o scroll. */
        .stApp::before,
        .stApp::after,
        .home-header::before,
        .home-header::after,
        .home-card::before,
        .home-total-card::after,
        .kpi::after,
        .ranking-detail-card::after,
        .ranking-versus-card::after,
        .dominance-panel::after,
        div[data-testid="stVerticalBlockBorderWrapper"]::after {{
          content: none !important;
          display: none !important;
        }}

        .jr-topbar,
        .st-key-comb_filterbar,
        .st-key-manu_filterbar,
        .st-key-hotel_filterbar,
        .st-key-ped_filterbar,
        .st-key-vex_filterbar,
        .st-key-vel_filterbar,
        .st-key-rank_filterbar {{
          box-shadow: 0 3px 10px rgba(7,15,40,.16) !important;
        }}

        .home-header,
        .home-card,
        .home-footer,
        .home-total-card,
        .st-key-cadastro_shell,
        .st-key-home_total_section,
        div[data-testid="stVerticalBlockBorderWrapper"],
        [class*="_dashboard_controls"],
        .kpi-section,
        .kpi,
        .table-counter-card,
        .ranking-header,
        .ranking-native-row,
        .ranking-detail-card,
        .ranking-summary-item,
        .ranking-versus-card,
        .ranking-difference,
        .ranking-difference-item,
        .ranking-empty,
        .dominance-panel,
        .dominance-city-row {{
          box-shadow: 0 3px 10px rgba(16,24,40,.07) !important;
          backdrop-filter: none !important;
          -webkit-backdrop-filter: none !important;
          transition: none !important;
          will-change: auto !important;
        }}

        div[data-testid="stPlotlyChart"] {{
          contain: layout paint style;
        }}

        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stPlotlyChart"]),
        .ranking-native-row {{
          content-visibility: auto;
          contain-intrinsic-size: auto 420px;
        }}

        .ranking-native-row {{
          contain-intrinsic-size: auto 58px;
        }}

        .ranking-native-row[open] {{
          content-visibility: visible;
          contain-intrinsic-size: auto;
        }}

        @media (max-width: 780px) {{
          .block-container {{
            padding: 0 10px 30px;
          }}

          .jr-topbar {{
            margin: 0 calc(50% - 50vw);
            width: 100vw;
            max-width: 100vw;
            padding: 10px 12px;
            position: static;
          }}

          .st-key-comb_filterbar,
          .st-key-manu_filterbar,
          .st-key-hotel_filterbar,
          .st-key-ped_filterbar,
          .st-key-vex_filterbar,
          .st-key-vel_filterbar,
          .st-key-rank_filterbar {{
            margin: 0 calc(50% - 50vw) 18px;
            width: 100vw;
            max-width: 100vw;
            padding: 8px 10px 10px;
            position: static;
            overflow: visible;
          }}

          .st-key-comb_filterbar [data-testid="stHorizontalBlock"],
          .st-key-manu_filterbar [data-testid="stHorizontalBlock"],
          .st-key-hotel_filterbar [data-testid="stHorizontalBlock"],
          .st-key-ped_filterbar [data-testid="stHorizontalBlock"],
          .st-key-vex_filterbar [data-testid="stHorizontalBlock"],
          .st-key-vel_filterbar [data-testid="stHorizontalBlock"],
          .st-key-rank_filterbar [data-testid="stHorizontalBlock"] {{
            flex-wrap: nowrap !important;
            align-items: stretch;
            gap: 8px;
            overflow-x: auto;
            overflow-y: visible;
            padding: 2px 2px 8px;
            scroll-snap-type: x proximity;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: thin;
          }}

          .st-key-comb_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-manu_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-hotel_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-ped_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-vex_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-vel_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]) {{
            flex: 0 0 clamp(132px, 43vw, 190px) !important;
            min-width: clamp(132px, 43vw, 190px) !important;
            max-width: clamp(132px, 43vw, 190px) !important;
            scroll-snap-align: start;
          }}

          .st-key-comb_filterbar div[data-baseweb="select"] > div,
          .st-key-manu_filterbar div[data-baseweb="select"] > div,
          .st-key-hotel_filterbar div[data-baseweb="select"] > div,
          .st-key-ped_filterbar div[data-baseweb="select"] > div,
          .st-key-vex_filterbar div[data-baseweb="select"] > div,
          .st-key-vel_filterbar div[data-baseweb="select"] > div,
          .st-key-rank_filterbar div[data-baseweb="select"] > div {{
            min-height: 36px;
          }}

          .st-key-comb_filterbar span[data-baseweb="tag"],
          .st-key-manu_filterbar span[data-baseweb="tag"],
          .st-key-hotel_filterbar span[data-baseweb="tag"],
          .st-key-ped_filterbar span[data-baseweb="tag"],
          .st-key-vex_filterbar span[data-baseweb="tag"],
          .st-key-vel_filterbar span[data-baseweb="tag"],
          .st-key-rank_filterbar span[data-baseweb="tag"] {{
            max-width: 74px;
            min-height: 22px;
          }}

          .st-key-comb_filterbar span[data-baseweb="tag"] span,
          .st-key-manu_filterbar span[data-baseweb="tag"] span,
          .st-key-hotel_filterbar span[data-baseweb="tag"] span,
          .st-key-ped_filterbar span[data-baseweb="tag"] span,
          .st-key-vex_filterbar span[data-baseweb="tag"] span,
          .st-key-vel_filterbar span[data-baseweb="tag"] span,
          .st-key-rank_filterbar span[data-baseweb="tag"] span {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-size: 11px;
          }}

          .jr-topbar h1 {{
            font-size: 17px;
          }}

          .home-wrapper {{
            padding: 20px 0 36px;
            gap: 24px;
          }}

          .home-header,
          .home-total-section,
          .home-card,
          .home-footer {{
            padding: 20px;
          }}

          .home-brand {{
            flex-direction: column;
          }}

          .home-header-actions {{
            position: relative;
            top: auto;
            right: auto;
            align-self: flex-start;
            align-items: flex-start;
          }}

          .home-header h1 {{
            font-size: 28px;
          }}

          .home-title-row {{
            align-items: flex-start;
          }}

          .frete-breakdown {{
            grid-template-columns: 1fr;
          }}

          .frete-result-grid {{
            grid-template-columns: 1fr;
            gap: 22px;
          }}

          .frete-result-item--cost {{
            padding: 20px 0 0;
            border-top: 1px solid rgba(255,255,255,.24);
            border-left: 0;
          }}

          .home-total-grid,
          .kpi-sections,
          .kpis,
          .home-grid,
          .home-export-bar {{
            grid-template-columns: 1fr;
          }}

          [class*="_dashboard_controls"] {{
            margin: 10px 0 18px;
          }}

          [class*="_dashboard_controls"] summary {{
            min-height: 42px;
            padding: 0 12px !important;
          }}

          [class*="_dashboard_controls"] details > div {{
            padding: 12px;
          }}

          [class*="_dashboard_controls"] :is([data-testid="column"], [data-testid="stColumn"]) {{
            flex: 1 1 calc(50% - 8px) !important;
            min-width: min(180px, 100%) !important;
          }}

          [class*="_dashboard_controls"] [data-testid="stCheckbox"] label {{
            min-height: 40px;
            padding: 7px 10px;
          }}

          .ranking-header {{
            display: none;
          }}

          .st-key-frota_ranking_table [data-testid="stExpander"] summary p {{
            font-size: 12px;
          }}

          .ranking-native-row > summary {{
            min-height: 52px;
            padding: 8px 12px;
            font-size: 12px;
          }}

          .ranking-native-content {{
            padding: 10px 12px 14px;
          }}

          .dominance-city-row {{
            grid-template-columns: 1fr;
            gap: 4px;
          }}

          .dominance-city-metric {{
            text-align: left;
          }}

          .dominance-panel--routes {{
            padding: 14px;
          }}

          .dominance-route-heading {{
            display: block;
          }}

          .dominance-route-count {{
            display: inline-block;
            margin-top: 10px;
          }}

          .dominance-route-table {{
            max-height: 560px;
            padding-right: 5px;
          }}

          .dominance-route-row {{
            grid-template-columns: 1fr;
            gap: 6px;
            padding: 12px;
          }}

          .dominance-route-row--head {{
            display: none;
          }}

          .dominance-route-row:not(.dominance-route-row--head) > span {{
            display: flex;
            gap: 12px;
            align-items: center;
            justify-content: space-between;
            text-align: right;
          }}

          .dominance-route-row:not(.dominance-route-row--head) > span::before {{
            content: attr(data-label);
            color: var(--muted);
            font-size: 10px;
            font-weight: 900;
            letter-spacing: .05em;
            text-transform: uppercase;
          }}
        }}

        @media (max-width: 560px) {{
          .st-key-comb_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-manu_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-hotel_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-ped_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-vex_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-vel_filterbar :is([data-testid="column"], [data-testid="stColumn"]),
          .st-key-rank_filterbar :is([data-testid="column"], [data-testid="stColumn"]) {{
            flex-basis: 150px !important;
            min-width: 150px !important;
            max-width: 150px !important;
          }}

          .filter-back,
          .st-key-comb_filterbar .stButton > button,
          .st-key-manu_filterbar .stButton > button,
          .st-key-hotel_filterbar .stButton > button,
          .st-key-ped_filterbar .stButton > button,
          .st-key-vex_filterbar .stButton > button,
          .st-key-vel_filterbar .stButton > button,
          .st-key-rank_filterbar .stButton > button {{
            min-height: 36px;
            padding-left: 8px;
            padding-right: 8px;
            font-size: 12px;
          }}

          [class*="_dashboard_controls"] :is([data-testid="column"], [data-testid="stColumn"]) {{
            flex: 1 1 100% !important;
            min-width: 100% !important;
          }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def enable_numeric_input_overwrite() -> None:
    """Faz o primeiro numero digitado substituir o valor atual do campo."""
    components.html(
        """
        <script>
        (() => {
          const parentWindow = window.parent;
          const parentDocument = parentWindow.document;
          const marker = "__jrNumericOverwriteEnabled";
          if (parentDocument[marker]) return;

          const numberInput = (target) => {
            if (!(target instanceof parentWindow.HTMLInputElement)) return null;
            return target.closest('[data-testid="stNumberInput"]') ? target : null;
          };
          const arm = (input) => {
            if (!input || input.disabled || input.readOnly) return;
            input.dataset.jrReplaceOnType = "1";
            parentWindow.setTimeout(() => {
              try { input.select(); } catch (_) {}
            }, 0);
          };

          parentDocument.addEventListener("focusin", (event) => arm(numberInput(event.target)), true);
          parentDocument.addEventListener("pointerdown", (event) => arm(numberInput(event.target)), true);
          parentDocument.addEventListener("keydown", (event) => {
            const input = numberInput(event.target);
            if (!input || input.dataset.jrReplaceOnType !== "1") return;
            if (event.ctrlKey || event.metaKey || event.altKey || !/^[0-9.,-]$/.test(event.key)) return;
            input.dataset.jrReplaceOnType = "0";
            input.value = "";
          }, true);

          parentDocument[marker] = true;
        })();
        </script>
        """,
        height=0,
        scrolling=False,
    )


def _freeze_route_params(params: dict[str, object] | None = None) -> tuple[tuple[str, object], ...]:
    params = params or {}
    clean_items: list[tuple[str, object]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str) and value in ("", "Todos"):
            continue
        if isinstance(value, (list, tuple, set)):
            values = tuple(item for item in value if item not in (None, "", "Todos"))
            if values:
                clean_items.append((key, values))
        else:
            clean_items.append((key, value))
    return tuple(sorted(clean_items))


@st.cache_data(ttl=ROUTE_CACHE_TTL_SECONDS, show_spinner=False)
def _route_json_cached(route: str, frozen_params: tuple[tuple[str, object], ...], version: str) -> dict:
    func = ROUTES[route]
    params = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in frozen_params
    }
    return func(params) or {}


def clear_cached_reads() -> None:
    try:
        _route_json_cached.clear()
    except Exception:
        pass


def route_json(route: str, params: dict[str, object] | None = None) -> dict:
    # A escrita local atualiza esse cache imediatamente; nas leituras comuns,
    # reutiliza-lo evita uma consulta extra ao Neon para cada bloco da pagina.
    database_version = backend.dashboard_data_version()
    version = f"{APP_VERSION}:{database_version!r}"
    return _route_json_cached(route, _freeze_route_params(params), version)


def route_json_uncached(route: str, params: dict[str, object] | None = None) -> dict:
    func = ROUTES[route]
    clean_params: dict[str, object] = {}
    for key, value in _freeze_route_params(params):
        clean_params[key] = list(value) if isinstance(value, tuple) else value
    return func(clean_params) or {}


def page_param() -> str:
    value = st.query_params.get("page", "home")
    if isinstance(value, list):
        value = value[0] if value else "home"
    return str(value or "home").lower()


def navigate(page: str) -> None:
    st.query_params["page"] = page
    st.rerun()


def fmt_brl(value: object, *, compact_threshold: float = 1000.0) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if abs(number) >= compact_threshold:
        integer = int(number) if number >= 0 else -int(abs(number))
        formatted = f"{integer:,}".replace(",", ".")
        return f"R$ {formatted}"
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def fmt_brl_compact(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f"{number:,.0f}".replace(",", ".")
    return f"R$ {formatted}"


def fmt_brl_big(value: object, *, threshold: float = 1000.0) -> str:
    return fmt_brl(value, compact_threshold=threshold)


def fmt_num(value: object, decimals: int = 0) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f"{number:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if decimals == 0:
        return formatted.split(",")[0]
    return formatted


def fmt_percent(value: object, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{fmt_num(number, decimals)}%"


def fmt_duration_minutes(value: object) -> str:
    if value is None:
        return "—"
    try:
        minutes = max(float(value), 0.0)
    except (TypeError, ValueError):
        return "—"
    if minutes < 60:
        return f"{fmt_num(minutes, 1)} min"
    hours = int(minutes // 60)
    remaining = int(round(minutes - hours * 60))
    if remaining == 60:
        hours += 1
        remaining = 0
    return f"{hours}h {remaining:02d}min"


def fmt_peso(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if abs(number) >= 1000:
        tons = int(number / 1000) if number >= 0 else -int(abs(number) / 1000)
        return f"{fmt_num(tons)} ton"
    return f"{fmt_num(number, 2)} kg"


def _freight_reference(totals: dict) -> dict[str, float]:
    """Transforma os totais historicos do dashboard em tarifas de referencia."""
    total_cost = max(float(totals.get("total") or 0.0), 0.0)
    salary_cost = max(float(totals.get("salario_transporte") or 0.0), 0.0)
    hotel_cost = max(float(totals.get("hoteis") or 0.0), 0.0)
    hotel_reservations = max(float(totals.get("hoteis_reservas") or 0.0), 0.0)
    hotel_days = max(float(totals.get("dias_hoteis") or 0.0), 0.0)
    hotel_daily_rate = max(float(totals.get("hoteis_media_reserva") or 0.0), 0.0)
    if not hotel_daily_rate and hotel_reservations:
        hotel_daily_rate = hotel_cost / hotel_reservations
    if not hotel_daily_rate and hotel_days:
        hotel_daily_rate = hotel_cost / hotel_days
    operating_cost = max(total_cost - salary_cost - hotel_cost, 0.0)
    total_km = max(float(totals.get("km_total") or 0.0), 0.0)
    service_days = max(
        float(totals.get("salario_transporte_dias") or totals.get("dias_servico") or 0.0),
        0.0,
    )
    return {
        "operating_cost": operating_cost,
        "salary_cost": salary_cost,
        "hotel_cost": hotel_cost,
        "hotel_reservations": hotel_reservations,
        "hotel_daily_rate": hotel_daily_rate,
        "total_km": total_km,
        "service_days": service_days,
        "rate_per_km": operating_cost / total_km if total_km else 0.0,
        "rate_per_employee_hour": (
            salary_cost
            / service_days
            / FREIGHT_REFERENCE_CREW_SIZE
            / FREIGHT_WORKDAY_HOURS
            if service_days and salary_cost
            else 0.0
        ),
    }


def _freight_plate_reference(row: dict, general: dict[str, float]) -> dict[str, float | str]:
    total_cost = max(float(row.get("total") or 0.0), 0.0)
    salary_cost = max(float(row.get("salario_transporte") or 0.0), 0.0)
    operating_cost = max(total_cost - salary_cost, 0.0)
    total_km = max(float(row.get("km_total") or 0.0), 0.0)
    service_days = max(float(row.get("dias_servico") or 0.0), 0.0)

    has_plate_km_rate = bool(total_km and operating_cost)
    has_plate_hourly_rate = bool(service_days and salary_cost)
    general_rate_per_km = float(general.get("rate_per_km") or 0.0)
    direct_rate_per_km = (
        operating_cost / total_km
        if has_plate_km_rate
        else general_rate_per_km
    )
    return {
        "rate_per_km": direct_rate_per_km,
        "direct_rate_per_km": direct_rate_per_km,
        "hotel_daily_rate": float(general.get("hotel_daily_rate") or 0.0),
        "rate_per_employee_hour": (
            salary_cost
            / service_days
            / FREIGHT_REFERENCE_CREW_SIZE
            / FREIGHT_WORKDAY_HOURS
            if has_plate_hourly_rate
            else float(general.get("rate_per_employee_hour") or 0.0)
        ),
        "km_rate_source": "placa" if has_plate_km_rate else "média da frota",
        "hourly_rate_source": "placa" if has_plate_hourly_rate else "média da equipe",
        "plate_km": total_km,
        "plate_operating_cost": operating_cost,
    }


def _calculate_freight_quote(
    reference: dict[str, float],
    *,
    weight_kg: float,
    distance_km: float,
    employees: int,
    employee_hourly_rate: float,
    margin_percent: float,
    include_hotels: bool,
) -> dict[str, float]:
    employee_count = max(int(employees), 1)
    unload_hours = max(weight_kg, 0.0) / FREIGHT_UNLOAD_KG_PER_HOUR
    travel_hours = max(distance_km, 0.0) / FREIGHT_AVERAGE_SPEED_KMH
    total_operation_hours = unload_hours + travel_hours
    unload_employee_hours = unload_hours * employee_count
    travel_employee_hours = travel_hours * employee_count
    employee_hours = total_operation_hours * employee_count
    hourly_rate = max(employee_hourly_rate, 0.0)
    unload_labor_cost = unload_employee_hours * hourly_rate
    travel_labor_cost = travel_employee_hours * hourly_rate
    team_cost = unload_labor_cost + travel_labor_cost
    distance_component = max(distance_km, 0.0) * reference["rate_per_km"]
    hotel_daily_rate = max(float(reference.get("hotel_daily_rate") or 0.0), 0.0)
    hotel_days = (
        int(total_operation_hours // FREIGHT_HOTEL_DAY_HOURS)
        if include_hotels
        else 0
    )
    hotel_cost = hotel_days * hotel_daily_rate
    estimated_cost = distance_component + team_cost + hotel_cost
    margin_value = estimated_cost * max(margin_percent, 0.0) / 100.0
    suggested_freight = estimated_cost + margin_value
    return {
        "unload_labor_cost": unload_labor_cost,
        "travel_labor_cost": travel_labor_cost,
        "team_cost": team_cost,
        "distance_component": distance_component,
        "hotel_days": float(hotel_days),
        "hotel_daily_rate": hotel_daily_rate,
        "hotel_cost": hotel_cost,
        "unload_hours": unload_hours,
        "travel_hours": travel_hours,
        "total_operation_hours": total_operation_hours,
        "employee_hours": employee_hours,
        "estimated_cost": estimated_cost,
        "margin_value": margin_value,
        "suggested_freight": suggested_freight,
    }


@st.cache_data(ttl=600, show_spinner=False)
def last_update_label(version: str) -> str:
    root = Path(__file__).resolve().parent
    dt: datetime | None = None
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "log", "-1", "--format=%cI"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
        if output:
            dt = datetime.fromisoformat(output.replace("Z", "+00:00"))
    except Exception:
        dt = None
    if dt is None:
        mtimes = [Path(__file__).stat().st_mtime]
        backend_path = root / "app.py"
        if backend_path.exists():
            mtimes.append(backend_path.stat().st_mtime)
        dt = datetime.fromtimestamp(max(mtimes), tz=BR_TZ)
    return dt.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M")


def bar_value_text(value: object, *, currency: bool = True) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if abs(number) < 0.005:
        return ""
    return fmt_brl_compact(number) if currency else fmt_num(number)


def h(text: object) -> str:
    escaped = html.escape(clean_text(text), quote=True)
    return escaped.encode("ascii", "xmlcharrefreplace").decode("ascii")


def clean_text(text: object) -> str:
    value = str(text if text is not None else "")
    if any(marker in value for marker in ("Ã", "Â", "â€", "â€¢")):
        for _ in range(2):
            try:
                decoded = value.encode("latin1").decode("utf-8")
            except UnicodeError:
                break
            if decoded == value:
                break
            value = decoded
        replacements = {
            "Ã¡": "á",
            "Ã¢": "â",
            "Ã£": "ã",
            "Ã©": "é",
            "Ãª": "ê",
            "Ã­": "í",
            "Ã³": "ó",
            "Ã´": "ô",
            "Ãµ": "õ",
            "Ãº": "ú",
            "Ã§": "ç",
            "Â©": "©",
            "â€¢": "•",
        }
        for bad, good in replacements.items():
            value = value.replace(bad, good)
    broken = r"[\ufffd\u25a1\u25af?]"

    def same_case(match: re.Match, replacement: str) -> str:
        original = match.group(0)
        if original.isupper():
            return replacement.upper()
        if original[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    word_replacements = [
        (fr"combust{broken}vel", "combustível"),
        (fr"manuten{broken}+o", "manutenção"),
        (fr"ped{broken}gio", "pedágio"),
        (fr"hot{broken}is", "hotéis"),
        (fr"servi{broken}os", "serviços"),
        (fr"lan{broken}amento", "lançamento"),
        (fr"edi{broken}+o", "edição"),
        (fr"gr{broken}fico", "gráfico"),
        (fr"p{broken}gina", "página"),
        (fr"m{broken}dia", "média"),
        (fr"m{broken}dio", "médio"),
        (fr"m{broken}s", "mês"),
        (fr"{broken}ltimos", "últimos"),
    ]
    for pattern, replacement in word_replacements:
        value = re.sub(pattern, lambda match, repl=replacement: same_case(match, repl), value, flags=re.IGNORECASE)

    value = re.sub(fr"\s*{broken}\s*", " - ", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip()


def export_text(text: object) -> str:
    value = clean_text(text)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.encode("ascii", "ignore").decode("ascii")


def selected_or_default(options: list, current: object | None = None, *, default_current_year: bool = False) -> object:
    all_options = ["Todos", *[item for item in options if item != "Todos"]]
    if current in all_options:
        return current
    if default_current_year and CURRENT_YEAR in all_options:
        return CURRENT_YEAR
    if default_current_year and str(CURRENT_YEAR) in all_options:
        return str(CURRENT_YEAR)
    return "Todos"


def last_closed_month() -> tuple[int, int]:
    first_day = date.today().replace(day=1)
    closed = first_day - timedelta(days=1)
    return closed.year, closed.month


def last_closed_year_default(options: list, current: object | None = None) -> object:
    all_options = ["Todos", *[item for item in options if item != "Todos"]]
    if current in all_options:
        return current
    year, _month = last_closed_month()
    if year in all_options:
        return year
    if str(year) in all_options:
        return str(year)
    return selected_or_default(options, current, default_current_year=True)


def default_closed_month_selection(options: list, year_value: object) -> list[object]:
    closed_year, closed_month = last_closed_month()
    if year_value not in (closed_year, str(closed_year)):
        return ["Todos"]
    selected: list[object] = []
    for option in options:
        if option == "Todos":
            continue
        key = parse_month_key(option, closed_year)
        if key and key[0] == closed_year and 1 <= key[1] <= closed_month:
            selected.append(option)
            continue
        try:
            month_number = int(option)
        except (TypeError, ValueError):
            continue
        if 1 <= month_number <= closed_month:
            selected.append(option)
    return selected or ["Todos"]


def month_label(value: object) -> str:
    if value == "Todos":
        return "Todos"
    try:
        month = int(value)
    except (TypeError, ValueError):
        return str(value)
    if 1 <= month <= 12:
        return f"{month:02d} - {MONTH_NAMES[month - 1]}"
    return str(value)


def month_filter_label(value: object) -> str:
    if value == "Todos":
        return "Todos"
    key = parse_month_key(value)
    if not key:
        return str(value)
    year, month = key
    return f"{MONTH_ABBR[month - 1]}/{str(year)[-2:]}"


def compact_month_label(value: object) -> str:
    if value == "Todos":
        return "Todos"
    try:
        month = int(value)
    except (TypeError, ValueError):
        key = parse_month_key(value)
        if not key:
            return str(value)
        _year, month = key
    if 1 <= month <= 12:
        return MONTH_ABBR[month - 1]
    return str(value)


def select_all_label(label: str):
    return lambda value: f"{label} (Todos)" if value == "Todos" else str(value)


def unique_filter_options(options: list[object]) -> list[object]:
    cleaned: list[object] = []
    seen: set[str] = set()
    for item in options or []:
        if item is None or item == "Todos":
            continue
        text = str(item).strip()
        if not text or text.lower() in {"nan", "none", "nat", "<na>"}:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def normalize_multiselect(values: list[object], previous: list[object] | None = None) -> list[object]:
    values = list(values or [])
    previous = list(previous or [])
    if not values:
        return ["Todos"]
    if "Todos" in values and len(values) > 1:
        if "Todos" in previous and len(previous) == 1:
            return [item for item in values if item != "Todos"] or ["Todos"]
        if "Todos" not in previous:
            return ["Todos"]
        return [item for item in values if item != "Todos"] or ["Todos"]
    return values


def sync_multiselect_selection(key: str) -> None:
    previous_key = f"{key}__previous"
    normalized = normalize_multiselect(
        st.session_state.get(key, []),
        st.session_state.get(previous_key, ["Todos"]),
    )
    st.session_state[key] = normalized
    st.session_state[previous_key] = normalized


def query_mes(values: list[object]) -> list[str]:
    cleaned = normalize_multiselect(values)
    if cleaned == ["Todos"]:
        return ["Todos"]
    return [str(item) for item in cleaned]


def query_multiselect(values: list[object]) -> list[str]:
    cleaned = normalize_multiselect(values)
    if cleaned == ["Todos"]:
        return ["Todos"]
    return [str(item) for item in cleaned]


def topbar(title: str, *, back: bool = True) -> None:
    logo = logo_data_uri()
    back_html = '<a class="jr-back" href="?page=home" target="_self">&larr; Voltar</a>' if back else ""
    st.markdown(
        f"""
        <header class="jr-topbar">
          <div class="jr-brand">
            <img class="jr-logo" src="{logo}" alt="JR">
            <h1>{h(title)}</h1>
          </div>
          {back_html}
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(items: list[tuple]) -> None:
    def card_html(item: tuple) -> str:
        label, value = item[0], item[1]
        color = item[2] if len(item) > 2 and item[2] else JR_RED
        return f'<div class="kpi" style="--kpi-accent: {h(color)}"><div class="kpi-title">{h(label)}</div><div class="kpi-value">{h(value)}</div></div>'

    has_sections = any(len(item) > 3 and item[3] for item in items)
    if not has_sections:
        st.html(f'<section class="kpis">{"".join(card_html(item) for item in items)}</section>')
        return

    sections: dict[str, dict[str, object]] = {}
    for item in items:
        section = clean_text(item[3] if len(item) > 3 and item[3] else "Resumo").strip() or "Resumo"
        color = item[2] if len(item) > 2 and item[2] else JR_RED
        sections.setdefault(section, {"color": color, "items": []})
        sections[section]["items"].append(item)

    section_html = []
    for section, payload in sections.items():
        color = payload["color"]
        cards = "".join(card_html(item) for item in payload["items"])
        summary_class = " kpi-section--summary" if section == "Comparativo geral" else ""
        section_html.append(
            f'<section class="kpi-section{summary_class}" style="--section-accent: {h(color)}">'
            f'<h3 class="kpi-section-title">{h(section)}</h3>'
            f'<div class="kpis">{cards}</div>'
            f'</section>'
        )
    st.html(f'<div class="kpi-sections">{"".join(section_html)}</div>')


def render_home_totals(cards: list[tuple[str, str, str]]) -> None:
    compact_km_labels = {"KM total", "Transporte", "Vex"}
    regular_before: list[str] = []
    regular_after: list[str] = []
    km_body: list[str] = []
    seen_km = False

    def _home_card(label: str, value: str, status: str, *, km: bool = False) -> str:
        if km:
            extra_class = " home-total-card--km"
        elif label == "Peso total":
            extra_class = " home-total-card--weight"
        elif label == "Gasto Vex":
            extra_class = " home-total-card--vex"
        elif label.startswith("Gasto"):
            extra_class = " home-total-card--money"
        else:
            extra_class = ""
        return (
            f'<div class="home-total-card home-total-card--secondary{extra_class}">'
            f'<p class="home-total-label">{h(label)}</p>'
            f'<p class="home-total-value">{h(value)}</p>'
            f'<p class="home-total-status">{h(status)}</p>'
            "</div>"
        )

    for label, value, status in cards:
        if label in compact_km_labels:
            seen_km = True
            km_body.append(_home_card(label, value, status, km=True))
        elif seen_km:
            regular_after.append(_home_card(label, value, status))
        else:
            regular_before.append(_home_card(label, value, status))

    html_parts = []
    if regular_before:
        html_parts.append(f'<div class="home-total-grid">{"".join(regular_before)}</div>')
    if km_body:
        html_parts.append(f'<div class="home-km-strip">{"".join(km_body)}</div>')
    if regular_after:
        html_parts.append(f'<div class="home-total-grid">{"".join(regular_after)}</div>')
    st.markdown(f'<div class="home-total-stack">{"".join(html_parts)}</div>', unsafe_allow_html=True)


def apply_theme(fig: go.Figure, *, height: int = 360, margin: dict | None = None) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="#fff",
        plot_bgcolor="#fff",
        font={"family": "Inter, sans-serif", "color": JR_BLUE},
        colorway=[JR_BLUE, JR_RED, "#4B5563", "#9CA3AF"],
        height=height,
        margin=margin or {"l": 60, "r": 30, "t": 28, "b": 62},
        hovermode="closest",
    )
    fig.update_xaxes(gridcolor="#e5e7eb", zerolinecolor="#e5e7eb", linecolor="#e5e7eb")
    fig.update_yaxes(gridcolor="#e5e7eb", zerolinecolor="#e5e7eb", linecolor="#e5e7eb")
    return fig


def figure_meta(fig: go.Figure) -> dict:
    return dict(fig.layout.meta) if isinstance(fig.layout.meta, dict) else {}


def update_figure_meta(fig: go.Figure, **values) -> go.Figure:
    meta = figure_meta(fig)
    meta.update(values)
    fig.update_layout(meta=meta)
    return fig


def _compare_chart_full_width(series_count: int) -> bool:
    return series_count >= 3


def parse_month_key(value: object, fallback_year: object | None = None) -> tuple[int, int] | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.notna(parsed):
        return int(parsed.year), int(parsed.month)
    for idx, abbr in enumerate(MONTH_ABBR, start=1):
        if abbr in text:
            year = None
            digits = "".join(ch if ch.isdigit() else " " for ch in text).split()
            if digits:
                year = int(digits[-1])
                if year < 100:
                    year += 2000
            elif fallback_year not in (None, "Todos"):
                try:
                    year = int(fallback_year)
                except (TypeError, ValueError):
                    year = None
            if year:
                return year, idx
    return None


def format_month_for_chart(value: object, *, include_year: bool = True, fallback_year: object | None = None) -> str:
    key = parse_month_key(value, fallback_year)
    if not key:
        return str(value)
    year, month = key
    label = MONTH_ABBR[month - 1]
    return f"{label}/{str(year)[-2:]}" if include_year else label


def sorted_series(data: dict, label_key: str, value_key: str, *, include_year: bool = True, fallback_year=None) -> tuple[list[str], list[float]]:
    labels = list(data.get(label_key, []) or [])
    values = list(data.get(value_key, []) or [])
    rows = []
    for index, label in enumerate(labels):
        value = values[index] if index < len(values) else 0
        key = parse_month_key(label, fallback_year)
        order = (key[0] * 100 + key[1]) if key and include_year else (key[1] if key else index)
        rows.append((order, index, label, float(value or 0)))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [format_month_for_chart(item[2], include_year=include_year, fallback_year=fallback_year) for item in rows], [item[3] for item in rows]


def yearly_month_series(data: dict, label_key: str, value_key: str, *, fallback_year=None) -> list[dict]:
    labels = list(data.get(label_key, []) or [])
    values = list(data.get(value_key, []) or [])
    grouped: dict[int, dict[int, float]] = {}
    for index, label in enumerate(labels):
        key = parse_month_key(label, fallback_year)
        if not key:
            continue
        year, month = key
        value = values[index] if index < len(values) else 0
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0.0
        grouped.setdefault(year, {})
        grouped[year][month] = grouped[year].get(month, 0.0) + number

    series = []
    for index, year in enumerate(sorted(grouped)):
        months = sorted(grouped[year])
        series.append(
            {
                "label": str(year),
                "color": YEAR_SERIES_COLORS[index % len(YEAR_SERIES_COLORS)],
                "raw_labels": [f"{year}-{month:02d}" for month in months],
                "values": [grouped[year][month] for month in months],
            }
        )
    return series


def yearly_month_line_chart(data: dict, label_key: str, value_key: str, *, fallback_year=None) -> go.Figure:
    return multi_line_chart(yearly_month_series(data, label_key, value_key, fallback_year=fallback_year), include_year=False, fallback_year=fallback_year)


def yearly_month_bar_chart(
    data: dict,
    label_key: str,
    value_key: str,
    *,
    fallback_year=None,
    currency: bool = True,
) -> go.Figure:
    return multi_bar_chart(
        yearly_month_series(data, label_key, value_key, fallback_year=fallback_year),
        currency=currency,
        label_mode="month",
        fallback_year=fallback_year,
    )


def line_chart(labels: list[str], values: list[float]) -> go.Figure:
    values = [float(value or 0) for value in values]
    if values:
        min_value = min(values)
        max_value = max(values)
        padding = (max_value - min_value) * 0.14 if max_value != min_value else max(1, abs(max_value) * 0.08)
        y_range = [max(0, min_value - padding), max_value + padding]
    else:
        y_range = None
    text_positions = []
    for index, value in enumerate(values):
        previous = values[index - 1] if index > 0 else None
        following = values[index + 1] if index + 1 < len(values) else None
        if previous is None and following is None:
            position = "top center"
        elif previous is None:
            position = "top left" if value >= following else "bottom left"
        elif following is None:
            position = "top right" if value >= previous else "bottom right"
        elif value <= previous and value <= following:
            position = "bottom center"
        elif value >= previous and value >= following:
            position = "top center"
        elif following > value:
            position = "top left"
        else:
            position = "top right"
        text_positions.append(position)
    fig = go.Figure(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers+text",
            line={"color": JR_BLUE, "width": 3},
            marker={"color": JR_RED, "size": 7},
            text=[fmt_brl_compact(value) for value in values],
            textposition=text_positions,
            textfont={"size": 11, "color": "#111827"},
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>R$ %{y:,.2f}<extra></extra>",
        )
    )
    fig.update_xaxes(tickangle=-30, type="category")
    fig.update_yaxes(title="R$", range=y_range, automargin=True)
    return apply_theme(fig, height=370, margin={"l": 60, "r": 60, "t": 58, "b": 60})


def bar_chart(
    labels: list,
    values: list,
    *,
    horizontal: bool = False,
    sort_desc: bool = False,
    currency: bool = True,
    show_text: bool = False,
    height: int | None = None,
    marker_colors: list[str] | None = None,
) -> go.Figure:
    rows = [(str(label), float(value or 0)) for label, value in zip(labels or [], values or [])]
    if sort_desc:
        rows.sort(key=lambda item: item[1], reverse=True)
    labels_clean = [item[0] for item in rows]
    values_clean = [item[1] for item in rows]
    text = None
    if show_text:
        text = [bar_value_text(value, currency=currency) for value in values_clean]

    if horizontal:
        chart_height = height or max(320, 95 + len(labels_clean) * 30)
        fig = go.Figure(
            go.Bar(
                x=values_clean,
                y=labels_clean,
                orientation="h",
                marker={"color": marker_colors or JR_BLUE},
                text=text,
                textposition="outside" if show_text else "none",
                textfont={"size": 11, "color": JR_BLUE},
                cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>R$ %{x:,.2f}<extra></extra>" if currency else "<b>%{y}</b><br>%{x:,.0f}<extra></extra>",
            )
        )
        max_value = max(values_clean) if values_clean else 0
        fig.update_xaxes(
            range=[0, max_value * (1.32 if show_text else 1.08)] if max_value else None,
            tickprefix="R$ " if currency else "",
            rangemode="tozero",
        )
        fig.update_yaxes(autorange="reversed", automargin=True, tickfont={"size": 11})
        fig = apply_theme(fig, height=chart_height, margin={"l": 130, "r": 95 if show_text else 45, "t": 20, "b": 45})
        fig.update_layout(meta={"jr_horizontal_bar": True, "jr_row_count": len(labels_clean)})
        return fig

    chart_height = height or 340
    fig = go.Figure(
        go.Bar(
            x=labels_clean,
            y=values_clean,
            marker={"color": marker_colors or JR_BLUE},
            text=text,
            textposition="outside" if show_text else "none",
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>R$ %{y:,.2f}<extra></extra>" if currency else "<b>%{x}</b><br>%{y:,.0f}<extra></extra>",
        )
    )
    max_value = max(values_clean) if values_clean else 0
    fig.update_xaxes(tickangle=-30, automargin=True, type="category")
    fig.update_yaxes(
        title="R$" if currency else "",
        tickprefix="R$ " if currency else "",
        range=[0, max_value * (1.18 if show_text else 1.08)] if max_value else None,
        rangemode="tozero",
    )
    return apply_theme(fig, height=chart_height)


def pie_chart(labels: list, values: list, *, hole: float = 0.45, show_values: bool = False) -> go.Figure:
    values_clean = [float(value or 0) for value in values or []]
    value_labels = [fmt_brl_compact(value) for value in values_clean]
    fig = go.Figure(
        go.Pie(
            labels=labels or [],
            values=values_clean,
            customdata=value_labels,
            hole=hole,
            textinfo="percent" if not show_values else "none",
            texttemplate="%{customdata}<br>%{percent}" if show_values else None,
            textposition="auto" if show_values else "inside",
            insidetextfont={"color": "#ffffff", "size": 12},
            outsidetextfont={"color": JR_BLUE, "size": 12},
            automargin=True,
            hovertemplate="<b>%{label}</b><br>%{customdata}<br>%{percent}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=True, legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.2})
    return apply_theme(fig, height=360, margin={"l": 16, "r": 16, "t": 30, "b": 90})


def metric_line_chart(
    labels: list,
    values: list,
    *,
    unit: str,
    decimals: int = 1,
    color: str = JR_BLUE,
) -> go.Figure:
    labels_clean = [clean_text(label) for label in labels or []]
    values_clean = [float(value or 0) for value in values or []]
    value_text = [f"{fmt_num(value, decimals)} {unit}".strip() for value in values_clean]
    max_value = max(values_clean) if values_clean else 0.0
    fig = go.Figure(
        go.Scatter(
            x=labels_clean,
            y=values_clean,
            mode="lines+markers+text",
            line={"color": color, "width": 3},
            marker={"color": JR_RED, "size": 7},
            text=value_text,
            textposition="top center",
            textfont={"size": 10, "color": JR_BLUE},
            cliponaxis=False,
            hovertemplate=f"<b>%{{x}}</b><br>%{{y:.{decimals}f}} {unit}<extra></extra>",
        )
    )
    fig.update_xaxes(tickangle=-30, type="category")
    fig.update_yaxes(
        ticksuffix=f" {unit}" if unit else "",
        range=[0, max_value * 1.2] if max_value else None,
        rangemode="tozero",
        automargin=True,
    )
    return apply_theme(fig, height=370, margin={"l": 70, "r": 70, "t": 60, "b": 65})


def metric_bar_chart(
    labels: list,
    values: list,
    *,
    unit: str,
    decimals: int = 1,
    horizontal: bool = False,
    sort_desc: bool = False,
    color: str = JR_BLUE,
) -> go.Figure:
    rows = [(clean_text(label), float(value or 0)) for label, value in zip(labels or [], values or [])]
    if sort_desc:
        rows.sort(key=lambda item: item[1], reverse=True)
    labels_clean = [item[0] for item in rows]
    values_clean = [item[1] for item in rows]
    value_text = [f"{fmt_num(value, decimals)} {unit}".strip() for value in values_clean]
    max_value = max(values_clean) if values_clean else 0.0

    if horizontal:
        fig = go.Figure(
            go.Bar(
                x=values_clean,
                y=labels_clean,
                orientation="h",
                marker={"color": color},
                text=value_text,
                textposition="outside",
                textfont={"size": 11, "color": JR_BLUE},
                cliponaxis=False,
                hovertemplate=f"<b>%{{y}}</b><br>%{{x:.{decimals}f}} {unit}<extra></extra>",
            )
        )
        fig.update_xaxes(
            ticksuffix=f" {unit}" if unit else "",
            range=[0, max_value * 1.34] if max_value else None,
            rangemode="tozero",
        )
        fig.update_yaxes(autorange="reversed", automargin=True, tickfont={"size": 11})
        fig = apply_theme(
            fig,
            height=max(340, 100 + len(labels_clean) * 34),
            margin={"l": 150, "r": 110, "t": 25, "b": 50},
        )
        return update_figure_meta(fig, jr_horizontal_bar=True, jr_row_count=len(labels_clean))

    fig = go.Figure(
        go.Bar(
            x=labels_clean,
            y=values_clean,
            marker={"color": color},
            text=value_text,
            textposition="outside",
            textfont={"size": 10, "color": JR_BLUE},
            cliponaxis=False,
            hovertemplate=f"<b>%{{x}}</b><br>%{{y:.{decimals}f}} {unit}<extra></extra>",
        )
    )
    fig.update_xaxes(tickangle=-30, type="category", automargin=True)
    fig.update_yaxes(
        ticksuffix=f" {unit}" if unit else "",
        range=[0, max_value * 1.2] if max_value else None,
        rangemode="tozero",
    )
    return apply_theme(fig, height=360, margin={"l": 70, "r": 55, "t": 60, "b": 70})


def peso_pie_chart(labels: list, values: list, city_counts: list | None = None, city_summaries: dict | None = None) -> go.Figure:
    values_clean = [float(value or 0) for value in values or []]
    counts = list(city_counts or [])
    summaries = city_summaries or {}
    labels_clean = [str(label) for label in labels or []]
    customdata = []
    for index, value in enumerate(values_clean):
        label = labels_clean[index] if index < len(labels_clean) else ""
        count = int(counts[index] or 0) if index < len(counts) else 0
        if count > 0 and summaries.get(label):
            customdata.append(f"{fmt_peso(value)} em {count} cidade(s)<br>Cidades: {h(summaries[label])}")
        elif count > 0:
            customdata.append(f"{fmt_peso(value)} em {count} cidade(s)")
        else:
            customdata.append(fmt_peso(value))
    fig = go.Figure(
        go.Pie(
            labels=labels or [],
            values=values_clean,
            customdata=customdata,
            hole=0.45,
            textinfo="percent",
            textposition="inside",
            hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
            marker={"colors": [JR_BLUE, JR_RED, "#D97706", "#64748B", "#3158B7", "#E66C7A", "#8892A6"]},
        )
    )
    fig.update_layout(showlegend=True, legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.2})
    return apply_theme(fig, height=380, margin={"l": 16, "r": 16, "t": 30, "b": 92})


def _series_color(route: str) -> str:
    return DASHBOARD_META.get(route, {}).get("color", JR_BLUE)


def _series_label(route: str) -> str:
    return DASHBOARD_META.get(route, {}).get("label", route.title())


def _ordered_month_labels(series: list[dict], *, include_year: bool, fallback_year) -> list[str]:
    labels: dict[str, tuple[int, int]] = {}
    fallback_order = 0
    for item in series:
        for raw_label in item.get("raw_labels", []):
            formatted = format_month_for_chart(raw_label, include_year=include_year, fallback_year=fallback_year)
            key = parse_month_key(raw_label, fallback_year)
            if key:
                order = ((key[0] * 100 + key[1]) if include_year else key[1], 0)
            else:
                fallback_order += 1
                order = (999999, fallback_order)
            labels.setdefault(formatted, order)
    return [label for label, _ in sorted(labels.items(), key=lambda item: item[1])]


def _ordered_day_labels(series: list[dict]) -> list[str]:
    labels: dict[str, tuple[int, int, int]] = {}
    fallback_order = 0
    for item in series:
        for raw_label in item.get("raw_labels", []):
            text = clean_text(raw_label).strip()
            parts = text.split("/")
            try:
                day = int(parts[0])
                month = int(parts[1]) if len(parts) > 1 else 0
                order = (month, day, 0)
            except (TypeError, ValueError):
                fallback_order += 1
                order = (99, 99, fallback_order)
            labels.setdefault(text, order)
    return [label for label, _ in sorted(labels.items(), key=lambda item: item[1])]


def _series_value_map(
    labels: list,
    values: list,
    *,
    label_formatter=None,
) -> dict[str, float]:
    mapped: dict[str, float] = {}
    for index, raw_label in enumerate(labels or []):
        label = label_formatter(raw_label) if label_formatter else clean_text(raw_label).strip()
        value = values[index] if index < len(values or []) else 0
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0.0
        mapped[label] = mapped.get(label, 0.0) + number
    return mapped


def multi_line_chart(series: list[dict], *, include_year: bool = True, fallback_year=None) -> go.Figure:
    clean_series = [item for item in series if item.get("raw_labels")]
    series_count = len(clean_series)
    if not clean_series:
        return line_chart([], [])
    if series_count == 1:
        item = clean_series[0]
        labels, values = sorted_series(
            {"Mes": item.get("raw_labels", []), "Valor": item.get("values", [])},
            "Mes",
            "Valor",
            include_year=include_year,
            fallback_year=fallback_year,
        )
        return line_chart(labels, values)

    ordered_labels = _ordered_month_labels(clean_series, include_year=include_year, fallback_year=fallback_year)
    fig = go.Figure()
    all_values = []
    for item in clean_series:
        value_map = _series_value_map(
            item.get("raw_labels", []),
            item.get("values", []),
            label_formatter=lambda raw: format_month_for_chart(raw, include_year=include_year, fallback_year=fallback_year),
        )
        values = [value_map.get(label, 0.0) for label in ordered_labels]
        all_values.extend(values)
        color = item.get("color", JR_BLUE)
        fig.add_trace(
            go.Scatter(
                x=ordered_labels,
                y=values,
                name=item.get("label", ""),
                mode="lines+markers",
                line={"color": color, "width": 3},
                marker={"color": color, "size": 7},
                hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>R$ %{y:,.2f}<extra></extra>",
            )
        )
    max_value = max(all_values) if all_values else 0
    fig.update_xaxes(tickangle=-30, type="category")
    fig.update_yaxes(title="R$", range=[0, max_value * 1.12] if max_value else None, automargin=True)
    fig.update_layout(showlegend=True, legend={"orientation": "h", "x": 0, "y": 1.14})
    fig = apply_theme(fig, height=430 if _compare_chart_full_width(series_count) else 370, margin={"l": 60, "r": 40, "t": 78, "b": 70})
    return update_figure_meta(fig, jr_compare_series_count=series_count, jr_full_width=_compare_chart_full_width(series_count))


def monthly_cost_gain_line_chart(
    monthly_cost: dict,
    monthly_gain: dict,
    *,
    include_year: bool,
    fallback_year=None,
) -> go.Figure:
    def clear_value_label(value: float) -> str:
        absolute = abs(value)
        if absolute >= 1_000_000:
            number = f"{value / 1_000_000:.1f}".replace(".", ",")
            return f"R$ {number} mi"
        if absolute >= 1_000:
            number = f"{value / 1_000:.0f}".replace(".", ",")
            return f"R$ {number} mil"
        return fmt_brl_compact(value)

    series = [
        {
            "label": "Gasto total",
            "color": JR_RED,
            "raw_labels": monthly_cost.get("Mes", []) or [],
            "values": monthly_cost.get("Valor", []) or [],
        },
        {
            "label": "Ganho das entregas",
            "color": "#15803D",
            "raw_labels": monthly_gain.get("Mes", []) or [],
            "values": monthly_gain.get("Valor", []) or [],
        },
    ]
    ordered_labels = _ordered_month_labels(
        series,
        include_year=include_year,
        fallback_year=fallback_year,
    )
    value_maps = [
        _series_value_map(
            item["raw_labels"],
            item["values"],
            label_formatter=lambda raw: format_month_for_chart(
                raw,
                include_year=include_year,
                fallback_year=fallback_year,
            ),
        )
        for item in series
    ]
    cost_values = [value_maps[0].get(label, 0.0) for label in ordered_labels]
    gain_values = [value_maps[1].get(label, 0.0) for label in ordered_labels]
    cost_percentages = [
        (cost / gain * 100.0) if gain else None
        for cost, gain in zip(cost_values, gain_values)
    ]
    percentage_labels = [fmt_percent(value) if value is not None else "—" for value in cost_percentages]
    positive_values = [
        value
        for value in (*cost_values, *gain_values)
        if value > 0
    ]
    fig = go.Figure()
    for index, (item, value_map) in enumerate(zip(series, value_maps)):
        values = [value_map.get(label, 0.0) for label in ordered_labels]
        plotted_values = [value if value > 0 else None for value in values]
        money_labels = [clear_value_label(value) if value > 0 else "" for value in values]
        is_cost = index == 0
        point_labels = [
            f"<b>{money}</b><br>{percentage_labels[point_index]}"
            if is_cost and money
            else (f"<b>{money}</b>" if money else "")
            for point_index, money in enumerate(money_labels)
        ]
        fig.add_trace(
            go.Scatter(
                x=ordered_labels,
                y=plotted_values,
                name=item["label"],
                mode="lines+markers+text",
                line={"color": item["color"], "width": 3},
                marker={
                    "color": item["color"],
                    "size": 9,
                    "line": {"color": "#FFFFFF", "width": 1.5},
                },
                text=point_labels,
                textposition="top center",
                textfont={"color": "#111827", "size": 11, "family": "Inter, sans-serif"},
                customdata=percentage_labels if is_cost else None,
                cliponaxis=False,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>%{x}<br>R$ %{y:,.2f}"
                    "<br>Custo sobre o ganho: %{customdata}<extra></extra>"
                    if is_cost
                    else "<b>%{fullData.name}</b><br>%{x}<br>R$ %{y:,.2f}<extra></extra>"
                ),
            )
        )
    fig.update_xaxes(tickangle=-30, type="category")
    yaxis = {
        "title": "Valor (R$)",
        "type": "log",
        "automargin": True,
        "gridcolor": "#E2E8F0",
    }
    if positive_values:
        lower_bound = math.log10(min(positive_values)) - 0.32
        upper_bound = math.log10(max(positive_values)) + 0.38
        tick_values = [
            multiplier * (10 ** exponent)
            for exponent in range(math.floor(lower_bound), math.ceil(upper_bound) + 1)
            for multiplier in (1, 2, 5)
            if lower_bound <= math.log10(multiplier * (10 ** exponent)) <= upper_bound
        ]
        yaxis["range"] = [lower_bound, upper_bound]
        yaxis["tickvals"] = tick_values
        yaxis["ticktext"] = [clear_value_label(value) for value in tick_values]
    fig.update_layout(
        showlegend=True,
        hovermode="x unified",
        legend={"orientation": "h", "x": 0, "y": 1.15, "itemsizing": "constant"},
        yaxis=yaxis,
    )
    return apply_theme(fig, height=410, margin={"l": 88, "r": 58, "t": 88, "b": 64})


def multi_bar_chart(
    series: list[dict],
    *,
    horizontal: bool = False,
    sort_desc: bool = False,
    currency: bool = True,
    height: int | None = None,
    label_mode: str = "day",
    fallback_year=None,
    include_year: bool = False,
) -> go.Figure:
    clean_series = [item for item in series if item.get("raw_labels")]
    series_count = len(clean_series)
    if not clean_series:
        return bar_chart([], [], horizontal=horizontal, currency=currency)
    if series_count == 1:
        item = clean_series[0]
        labels = item.get("raw_labels", [])
        values = item.get("values", [])
        if label_mode == "month":
            labels, values = sorted_series(
                {"Mes": labels, "Valor": values},
                "Mes",
                "Valor",
                include_year=include_year,
                fallback_year=fallback_year,
            )
        return bar_chart(
            labels,
            values,
            horizontal=horizontal,
            sort_desc=sort_desc,
            currency=currency,
            show_text=horizontal or label_mode == "month",
            height=height,
            marker_colors=[item.get("color", JR_BLUE)] * len(labels),
        )

    if horizontal:
        totals: dict[str, float] = {}
        maps = []
        for item in clean_series:
            value_map = _series_value_map(item.get("raw_labels", []), item.get("values", []))
            maps.append(value_map)
            for label, value in value_map.items():
                totals[label] = totals.get(label, 0.0) + value
        ordered_labels = list(totals.keys())
        if sort_desc:
            ordered_labels.sort(key=lambda label: totals.get(label, 0.0), reverse=True)
        row_height = 54 if _compare_chart_full_width(series_count) else 34
        chart_height = height or max(500 if _compare_chart_full_width(series_count) else 360, 92 + len(ordered_labels) * row_height)
        fig = go.Figure()
        max_value = 0.0
        text_size = 13 if _compare_chart_full_width(series_count) else 10
        for item, value_map in zip(clean_series, maps):
            values = [value_map.get(label, 0.0) for label in ordered_labels]
            text = [bar_value_text(value, currency=currency) for value in values]
            max_value = max(max_value, max(values) if values else 0.0)
            fig.add_trace(
                go.Bar(
                    x=values,
                    y=ordered_labels,
                    orientation="h",
                    name=item.get("label", ""),
                    marker={"color": item.get("color", JR_BLUE)},
                    text=text,
                    textposition="outside",
                    textfont={"size": text_size, "color": item.get("color", JR_BLUE)},
                    cliponaxis=False,
                    hovertemplate="<b>%{fullData.name}</b><br>%{y}<br>R$ %{x:,.2f}<extra></extra>"
                    if currency
                    else "<b>%{fullData.name}</b><br>%{y}<br>%{x:,.0f}<extra></extra>",
                )
            )
        fig.update_layout(
            barmode="group",
            bargap=0.28 if _compare_chart_full_width(series_count) else 0.18,
            bargroupgap=0.08,
            showlegend=True,
            legend={"orientation": "h", "x": 0.02, "y": 1.03, "yanchor": "bottom", "font": {"size": 13}},
        )
        fig.update_xaxes(tickprefix="R$ " if currency else "", range=[0, max_value * 1.34] if max_value else None, rangemode="tozero")
        fig.update_yaxes(autorange="reversed", automargin=True, tickfont={"size": 11})
        fig = apply_theme(fig, height=chart_height, margin={"l": 140, "r": 120, "t": 34, "b": 50})
        return update_figure_meta(
            fig,
            jr_horizontal_bar=True,
            jr_row_count=len(ordered_labels),
            jr_compare_series_count=series_count,
            jr_full_width=_compare_chart_full_width(series_count),
        )

    label_formatter = None
    if label_mode == "month":
        ordered_labels = _ordered_month_labels(clean_series, include_year=include_year, fallback_year=fallback_year)
        label_formatter = lambda raw: format_month_for_chart(raw, include_year=include_year, fallback_year=fallback_year)
    else:
        ordered_labels = _ordered_day_labels(clean_series)
    if not ordered_labels:
        ordered_labels = [label for item in clean_series for label in item.get("raw_labels", [])]
    fig = go.Figure()
    max_value = 0.0
    text_size = 13 if _compare_chart_full_width(series_count) else 10
    for item in clean_series:
        value_map = _series_value_map(item.get("raw_labels", []), item.get("values", []), label_formatter=label_formatter)
        values = [value_map.get(label, 0.0) for label in ordered_labels]
        text = [bar_value_text(value, currency=currency) for value in values]
        max_value = max(max_value, max(values) if values else 0.0)
        fig.add_trace(
            go.Bar(
                x=ordered_labels,
                y=values,
                name=item.get("label", ""),
                marker={"color": item.get("color", JR_BLUE)},
                text=text,
                textposition="outside",
                textfont={"size": text_size, "color": item.get("color", JR_BLUE)},
                cliponaxis=False,
                hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>R$ %{y:,.2f}<extra></extra>"
                if currency
                else "<b>%{fullData.name}</b><br>%{x}<br>%{y:,.0f}<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="group",
        bargap=0.24 if _compare_chart_full_width(series_count) else 0.18,
        bargroupgap=0.08,
        showlegend=True,
        legend={"orientation": "h", "x": 0.02, "y": 1.05, "yanchor": "bottom", "font": {"size": 13 if _compare_chart_full_width(series_count) else 11}},
    )
    fig.update_xaxes(tickangle=-30, automargin=True, type="category")
    fig.update_yaxes(
        title="R$" if currency else "",
        tickprefix="R$ " if currency else "",
        range=[0, max_value * (1.38 if _compare_chart_full_width(series_count) else 1.26)] if max_value else None,
        rangemode="tozero",
    )
    chart_height = height or (460 if _compare_chart_full_width(series_count) else 360)
    fig = apply_theme(fig, height=chart_height, margin={"l": 66, "r": 52, "t": 54 if _compare_chart_full_width(series_count) else 88, "b": 74})
    return update_figure_meta(fig, jr_compare_series_count=series_count, jr_full_width=_compare_chart_full_width(series_count))


def report_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
        "FreeSansBold.ttf" if bold else "FreeSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    *,
    font: ImageFont.ImageFont,
    fill: str,
    max_width: int,
    line_gap: int = 6,
) -> int:
    words = export_text(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    x, y = xy
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + line_gap
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def draw_centered_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    y: int,
    *,
    font: ImageFont.ImageFont,
    fill: str,
    max_width: int,
    line_gap: int = 6,
) -> int:
    words = export_text(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + line_gap
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        draw.text((center_x - (bbox[2] - bbox[0]) // 2, y), line, font=font, fill=fill)
        y += line_height
    return y


def _hex_rgb(color: str) -> tuple[int, int, int]:
    value = clean_text(color or "").strip().lstrip("#")
    if len(value) != 6:
        value = JR_RED.lstrip("#")
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return _hex_rgb(JR_RED)


def _paste_rgba(base: Image.Image, layer: Image.Image) -> None:
    base.paste(layer.convert("RGB"), (0, 0), layer.getchannel("A"))


def draw_liquid_export_card(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    *,
    radius: int = 22,
    accent: str = JR_RED,
    outline: str = "#cbd9ff",
) -> None:
    x1, y1, x2, y2 = box
    accent_rgb = _hex_rgb(accent)
    outline_rgb = _hex_rgb(outline)

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (x1 + 10, y1 + 14, x2 + 10, y2 + 16),
        radius=radius + 2,
        fill=(28, 45, 107, 34),
    )
    shadow_draw.rounded_rectangle(
        (x1 + 4, y1 + 7, x2 + 4, y2 + 8),
        radius=radius,
        fill=(194, 210, 243, 72),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    _paste_rgba(canvas, shadow)

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.rounded_rectangle(
        box,
        radius=radius,
        fill=(255, 255, 255, 236),
        outline=(*outline_rgb, 228),
        width=2,
    )
    layer_draw.rounded_rectangle(
        (x1 + 2, y1 + 2, x2 - 2, y1 + 7),
        radius=radius,
        fill=(*accent_rgb, 190),
    )
    layer_draw.rounded_rectangle(
        (x1 + 3, y1 + 3, x2 - 3, y2 - 3),
        radius=radius - 2,
        outline=(255, 255, 255, 178),
        width=1,
    )
    _paste_rgba(canvas, layer)


def horizontal_bar_row_count(fig: go.Figure) -> int:
    meta = figure_meta(fig)
    if meta.get("jr_horizontal_bar"):
        try:
            return int(meta.get("jr_row_count") or 0)
        except (TypeError, ValueError):
            return 0
    for trace in fig.data:
        if getattr(trace, "type", "") == "bar" and getattr(trace, "orientation", None) == "h":
            return len(getattr(trace, "y", []) or [])
    return 0


def chart_scroll_height(fig: go.Figure) -> int | None:
    row_count = horizontal_bar_row_count(fig)
    if row_count <= 10:
        return None
    meta = figure_meta(fig)
    try:
        series_count = int(meta.get("jr_compare_series_count") or 1)
    except (TypeError, ValueError):
        series_count = 1
    return 560 if series_count >= 3 else 420


def chart_prefers_full_width(fig: go.Figure) -> bool:
    return bool(figure_meta(fig).get("jr_full_width"))


def export_ready_figure(fig: go.Figure, *, max_horizontal_rows: int = 10) -> go.Figure:
    export_fig = go.Figure(fig)
    for trace in export_fig.data:
        if getattr(trace, "type", "") != "bar" or getattr(trace, "orientation", None) != "h":
            continue
        labels = list(getattr(trace, "y", []) or [])
        if len(labels) <= max_horizontal_rows:
            continue
        trace.y = labels[:max_horizontal_rows]
        trace.x = list(getattr(trace, "x", []) or [])[:max_horizontal_rows]
        if getattr(trace, "text", None) is not None:
            trace.text = list(trace.text)[:max_horizontal_rows]
        marker_color = getattr(trace.marker, "color", None)
        if isinstance(marker_color, (list, tuple)):
            trace.marker.color = list(marker_color)[:max_horizontal_rows]
        export_fig.update_layout(height=max(420, 95 + max_horizontal_rows * 30))
    return export_fig


def compose_home_export_image(
    cards: list[tuple[str, str, str]],
    *,
    include_header: bool,
) -> Image.Image:
    width = 1500
    margin = 54
    gap = 28
    bg = "#ffffff"
    panel = "#ffffff"
    line = "#cbd9ff"
    shadow = "#e4ebf8"
    card_cols = min(3, len(cards)) if cards else 1
    card_width = (width - margin * 2 - gap * (card_cols - 1)) // card_cols
    card_height = 205
    header_height = 140 if include_header else 0
    height = margin + header_height + card_height + margin
    canvas = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(canvas)
    y = margin

    if include_header:
        if LOGO_PATH.exists():
            try:
                logo = Image.open(LOGO_PATH).convert("RGBA").resize((64, 64))
                canvas.paste(logo, (margin, y), logo)
            except Exception:
                logo = None
        draw.text((margin + 84, y + 4), export_text("Dashboards operacionais"), font=report_font(36, bold=True), fill=JR_BLUE)
        draw_wrapped_text(
            draw,
            "Monitoramento consolidado do JR Dashboard.",
            (margin + 84, y + 56),
            font=report_font(20),
            fill=MUTED,
            max_width=760,
        )
        y += header_height

    for index, (label, value, status) in enumerate(cards):
        x = margin + index * (card_width + gap)
        label_upper = export_text(label).upper()
        accent = "#7C3AED" if "VEX" in label_upper else JR_RED if "GASTO" in label_upper else JR_BLUE
        draw_liquid_export_card(canvas, (x, y, x + card_width, y + card_height), radius=18, accent=accent, outline=line)
        center_x = x + card_width // 2
        draw_centered_wrapped_text(
            draw,
            label_upper,
            center_x,
            y + 26,
            font=report_font(20, bold=True),
            fill=MUTED,
            max_width=card_width - 60,
            line_gap=5,
        )
        value_text = export_text(value)
        value_font = report_font(30, bold=True)
        value_bbox = draw.textbbox((0, 0), value_text, font=value_font)
        draw.text((center_x - (value_bbox[2] - value_bbox[0]) // 2, y + 95), value_text, font=value_font, fill=accent)
        draw_centered_wrapped_text(
            draw,
            status,
            center_x,
            y + 138,
            font=report_font(16),
            fill="#374151",
            max_width=card_width - 52,
            line_gap=4,
        )

    return canvas


def compose_export_image(
    kpis: list[tuple[str, str]],
    charts: list[tuple[str, go.Figure]],
    *,
    title: str,
    include_cards: bool,
    include_charts: bool,
) -> Image.Image:
    _ = title
    width = 1800
    margin = 58
    gap = 28
    bg = "#ffffff"
    panel = "#ffffff"
    line = "#cbd9ff"
    text = JR_BLUE
    shadow = "#e4ebf8"
    card_cols = min(3, len(kpis)) if include_cards and kpis else 1
    card_width = (width - margin * 2 - gap * (card_cols - 1)) // card_cols if card_cols else 0
    card_height = 174
    chart_cols = 2
    chart_card_width = (width - margin * 2 - gap) // chart_cols
    chart_inner_width = chart_card_width - 56
    chart_images: list[tuple[str, Image.Image]] = []

    if include_charts:
        for chart_title, fig in charts:
            try:
                export_fig = export_ready_figure(fig)
                desired_height = max(540, min(780, int(export_fig.layout.height or 460) + 110))
                pie_label_count = 0
                for trace in export_fig.data:
                    if getattr(trace, "type", "") == "pie":
                        pie_label_count = max(pie_label_count, len(getattr(trace, "labels", []) or []))
                if pie_label_count > 10:
                    export_fig.update_layout(showlegend=False)
                    export_fig.update_traces(textinfo="percent", textposition="inside")
                    desired_height = max(desired_height, 600)
                export_fig.update_layout(
                    width=chart_inner_width,
                    height=desired_height,
                    paper_bgcolor="#ffffff",
                    plot_bgcolor="#ffffff",
                    font={"family": "Arial, sans-serif", "size": 17, "color": JR_BLUE},
                    margin={"l": 80, "r": 42, "t": 34, "b": 84},
                )
                export_fig.update_xaxes(tickfont={"size": 16}, title_font={"size": 18})
                export_fig.update_yaxes(tickfont={"size": 16}, title_font={"size": 18})
                export_fig.update_traces(textfont={"size": 15})
                png = export_fig.to_image(
                    format="png",
                    width=chart_inner_width,
                    height=desired_height,
                    scale=1,
                )
                chart_images.append((chart_title, Image.open(BytesIO(png)).convert("RGB")))
            except Exception:
                desired_height = 540
                placeholder = Image.new("RGB", (chart_inner_width, desired_height), "#ffffff")
                draw = ImageDraw.Draw(placeholder)
                draw.text(
                    (32, 32),
                    f"Não foi possível renderizar: {export_text(chart_title)}",
                    font=report_font(26, bold=True),
                    fill=JR_RED,
                )
                chart_images.append((chart_title, placeholder))

    rows = 0
    if include_cards and kpis:
        rows = (len(kpis) + card_cols - 1) // card_cols
    height = margin
    if rows:
        height += rows * card_height + (rows - 1) * gap
        if include_charts and chart_images:
            height += gap + 10
    if include_charts and chart_images:
        chart_row_heights = []
        for row_start in range(0, len(chart_images), chart_cols):
            row_items = chart_images[row_start : row_start + chart_cols]
            chart_row_heights.append(max(image.height for _, image in row_items) + 92)
        height += sum(chart_row_heights) + gap * max(0, len(chart_row_heights) - 1)
    height += margin
    if height < 500:
        height = 500

    canvas = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(canvas)
    y = margin

    if include_cards and kpis:
        for index, item in enumerate(kpis):
            label, value = item[0], item[1]
            accent = item[2] if len(item) > 2 and item[2] else JR_RED
            row = index // card_cols
            col = index % card_cols
            x = margin + col * (card_width + gap)
            card_y = y + row * (card_height + gap)
            draw_liquid_export_card(
                canvas,
                (x, card_y, x + card_width, card_y + card_height),
                radius=20,
                accent=accent,
                outline=line,
            )
            draw_wrapped_text(
                draw,
                export_text(label).upper(),
                (x + 30, card_y + 28),
                font=report_font(22, bold=True),
                fill=MUTED,
                max_width=card_width - 60,
                line_gap=4,
            )
            value_size = 42
            value_text = export_text(value)
            if len(value_text) > 18:
                value_size = 36
            if len(value_text) > 28:
                value_size = 31
            value_font = report_font(value_size, bold=True)
            value_bbox = draw.textbbox((0, 0), value_text, font=value_font)
            value_x = x + (card_width - (value_bbox[2] - value_bbox[0])) // 2
            draw.text((value_x, card_y + 104), value_text, font=value_font, fill=accent)
        y += rows * card_height + (rows - 1) * gap
        if include_charts and chart_images:
            y += gap + 10

    if include_charts and chart_images:
        for row_start in range(0, len(chart_images), chart_cols):
            row_items = chart_images[row_start : row_start + chart_cols]
            row_height = max(image.height for _, image in row_items) + 92
            for col, (chart_title, image) in enumerate(row_items):
                x = margin + col * (chart_card_width + gap)
                chart_y = y
                draw_liquid_export_card(
                    canvas,
                    (x, chart_y, x + chart_card_width, chart_y + row_height),
                    radius=22,
                    accent=JR_RED,
                    outline=line,
                )
                draw.text((x + 28, chart_y + 24), export_text(chart_title), font=report_font(30, bold=True), fill=text)
                canvas.paste(image, (x + 28, chart_y + 72))
            y += row_height + gap
        y -= gap

    return canvas.crop((0, 0, width, min(height, y + margin)))


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def image_to_pdf_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PDF", resolution=120.0)
    return buffer.getvalue()


def export_file_name(prefix: str, scope: str, ext: str) -> str:
    return f"{prefix}-{scope}.{ext}"


def chart_card(title: str, fig: go.Figure, *, key: str) -> None:
    # O botao de camera do Plotly usa exatamente o layout exibido no navegador.
    # Force fundos opacos para o PNG nunca herdar transparencias do tema do site.
    fig.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
    with st.container(border=True):
        st.html(f'<div class="chart-title">{h(title)}</div>')
        scroll_height = chart_scroll_height(fig)
        if scroll_height:
            with st.container(height=scroll_height, border=False):
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key)
        else:
            st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key)


def chart_grid(charts: list[tuple[str, go.Figure]], *, key_prefix: str = "chart") -> None:
    index = 0
    while index < len(charts):
        title, fig = charts[index]
        if chart_prefers_full_width(fig):
            chart_card(title, fig, key=f"{key_prefix}_{index}")
            index += 1
            continue

        if index + 1 < len(charts) and not chart_prefers_full_width(charts[index + 1][1]):
            row_items = charts[index : index + 2]
            scroll_heights = [chart_scroll_height(item[1]) for item in row_items]
            visible_scroll_heights = [height for height in scroll_heights if height]
            row_height = (
                max(visible_scroll_heights)
                if visible_scroll_heights
                else max(int(item[1].layout.height or 360) for item in row_items)
            )
            for (_row_title, row_fig), scroll_height in zip(row_items, scroll_heights):
                if not scroll_height:
                    row_fig.update_layout(height=row_height)
            cols = st.columns(2)
            for offset, (col, item) in enumerate(zip(cols, row_items)):
                with col:
                    chart_card(item[0], item[1], key=f"{key_prefix}_{index + offset}")
            index += 2
        else:
            chart_card(title, fig, key=f"{key_prefix}_{index}")
            index += 1


def kpi_control_label(item: tuple) -> str:
    label = clean_text(item[1])
    section = clean_text(item[4] if len(item) > 4 and item[4] else "").strip()
    return f"{section} - {label}" if section else label


def dashboard_controls(
    key_prefix: str,
    *,
    title: str,
    kpis: list[tuple],
    charts: list[tuple[str, str, go.Figure]],
) -> tuple[bool, bool, list[tuple], list[tuple[str, str, go.Figure]]]:
    hide_cards_key = f"{key_prefix}_hide_cards"
    hide_charts_key = f"{key_prefix}_hide_charts"
    export_ready_key = f"{key_prefix}_export_ready"
    st.session_state.setdefault(hide_cards_key, False)
    st.session_state.setdefault(hide_charts_key, False)
    ready_file = st.session_state.get(export_ready_key)
    if ready_file and ready_file.get("version") != APP_VERSION:
        st.session_state.pop(export_ready_key, None)

    with st.container(key=f"{key_prefix}_dashboard_controls"):
        with st.expander("Controles", expanded=False):
            export_jobs = [
                ("cards_png", "Cards PNG", "cards", "png"),
                ("cards_pdf", "Cards PDF", "cards", "pdf"),
                ("charts_png", "Gráficos PNG", "graficos", "png"),
                ("charts_pdf", "Gráficos PDF", "graficos", "pdf"),
                ("page_png", "Página PNG", "pagina", "png"),
                ("page_pdf", "Página PDF", "pagina", "pdf"),
            ]
            selected_kpis_preview = [
                (kpi_control_label(item), item[2], item[3] if len(item) > 3 and item[3] else JR_RED)
                for item in kpis
                if st.session_state.get(f"{key_prefix}_visible_{item[0]}", True)
            ]
            selected_charts_preview = [
                (chart_title, fig)
                for item_id, chart_title, fig in charts
                if st.session_state.get(f"{key_prefix}_visible_{item_id}", True)
            ]

            st.markdown('<div class="control-row-label">Exportar</div>', unsafe_allow_html=True)
            buttons = st.columns(6)
            for col, (job_id, label, scope, ext) in zip(buttons, export_jobs):
                with col:
                    if st.button(clean_text(label), key=f"{key_prefix}_export_{job_id}", width="stretch"):
                        include_cards = scope == "cards" or (scope == "pagina" and not st.session_state[hide_cards_key])
                        include_charts = scope == "graficos" or (scope == "pagina" and not st.session_state[hide_charts_key])
                        if not include_cards and not include_charts:
                            st.warning("Nada selecionado para exportar.")
                        elif include_cards and not selected_kpis_preview and not include_charts:
                            st.warning("Nenhum card selecionado para exportar.")
                        elif include_charts and not selected_charts_preview and not include_cards:
                            st.warning("Nenhum gráfico selecionado para exportar.")
                        elif include_cards and include_charts and not selected_kpis_preview and not selected_charts_preview:
                            st.warning("Nenhum item selecionado para exportar.")
                        else:
                            with st.spinner("Gerando arquivo..."):
                                image = compose_export_image(
                                    selected_kpis_preview,
                                    selected_charts_preview,
                                    title=title,
                                    include_cards=include_cards,
                                    include_charts=include_charts,
                                )
                                data = image_to_png_bytes(image) if ext == "png" else image_to_pdf_bytes(image)
                                st.session_state[export_ready_key] = {
                                    "data": data,
                                    "file_name": export_file_name(key_prefix, scope, ext),
                                    "mime": "image/png" if ext == "png" else "application/pdf",
                                    "version": APP_VERSION,
                                }

            ready = st.session_state.get(export_ready_key)
            if ready:
                st.download_button(
                    "Baixar arquivo gerado",
                    data=ready["data"],
                    file_name=ready["file_name"],
                    mime=ready["mime"],
                    key=f"{key_prefix}_download_ready",
                    width="stretch",
                )

            st.markdown('<div class="control-row-spacer"></div><div class="control-row-label">Exibir</div>', unsafe_allow_html=True)
            toggles = st.columns(2)
            with toggles[0]:
                toggle_label = "Mostrar cards" if st.session_state[hide_cards_key] else "Ocultar cards"
                if st.button(clean_text(toggle_label), key=f"{key_prefix}_toggle_cards", width="stretch"):
                    st.session_state[hide_cards_key] = not st.session_state[hide_cards_key]
                    st.rerun()
            with toggles[1]:
                toggle_label = "Mostrar gráficos" if st.session_state[hide_charts_key] else "Ocultar gráficos"
                if st.button(clean_text(toggle_label), key=f"{key_prefix}_toggle_charts", width="stretch"):
                    st.session_state[hide_charts_key] = not st.session_state[hide_charts_key]
                    st.rerun()

            st.markdown('<div class="control-row-spacer"></div><div class="control-row-label">Itens</div>', unsafe_allow_html=True)
            checkbox_items = [("cards", item[0], kpi_control_label(item)) for item in kpis]
            checkbox_items.extend(("charts", item_id, label) for item_id, label, _ in charts)
            checkbox_cols = 4
            for index in range(0, len(checkbox_items), checkbox_cols):
                cols = st.columns(checkbox_cols)
                for col, (_, item_id, label) in zip(cols, checkbox_items[index : index + checkbox_cols]):
                    state_key = f"{key_prefix}_visible_{item_id}"
                    st.session_state.setdefault(state_key, True)
                    with col:
                        st.checkbox(clean_text(label), key=state_key)

    show_cards = not st.session_state[hide_cards_key]
    show_charts = not st.session_state[hide_charts_key]
    visible_kpis = [item for item in kpis if st.session_state.get(f"{key_prefix}_visible_{item[0]}", True)]
    visible_charts = [item for item in charts if st.session_state.get(f"{key_prefix}_visible_{item[0]}", True)]
    return show_cards, show_charts, visible_kpis, visible_charts


def render_controlled_dashboard(
    key_prefix: str,
    *,
    title: str,
    kpis: list[tuple],
    charts: list[tuple[str, str, go.Figure]],
) -> None:
    show_cards, show_charts, visible_kpis, visible_charts = dashboard_controls(
        key_prefix,
        title=title,
        kpis=kpis,
        charts=charts,
    )
    if show_cards and visible_kpis:
        render_kpis([(item[1], item[2], item[3] if len(item) > 3 else None, item[4] if len(item) > 4 else None) for item in visible_kpis])
    if show_charts and visible_charts:
        chart_grid([(chart_title, fig) for _, chart_title, fig in visible_charts], key_prefix=f"{key_prefix}_chart")


def filter_controls(
    route: str,
    *,
    extra_filters: list[tuple[str, str, list]],
    key_prefix: str,
    all_data: dict | None = None,
    allow_compare: bool = True,
) -> tuple[dict[str, object], dict]:
    all_data = all_data if all_data is not None else route_json(route, {"ano": "Todos", "mes": ["Todos"]})
    years = all_data.get("anos", []) or []
    year_options = ["Todos", *years]
    year_default = last_closed_year_default(years, st.session_state.get(f"{key_prefix}_ano"))
    year_index = year_options.index(year_default) if year_default in year_options else 0

    with st.container(key=f"{key_prefix}_filterbar"):
        filter_widths = [1.1 if len(label) > 10 else 1.0 for _, label, _ in extra_filters]
        compare_options = (
            [key for key in DASHBOARD_META if key in COMPARE_ALLOWED_ROUTES and key != route]
            if allow_compare
            else []
        )
        widths = [0.85, 1.25, *filter_widths]
        if allow_compare:
            widths.append(1.35)
        widths.extend([1.05, 0.8])
        filter_cols = st.columns(widths)
        with filter_cols[0]:
            ano = st.selectbox(
                "Ano",
                year_options,
                index=year_index,
                key=f"{key_prefix}_ano",
                format_func=select_all_label("Ano"),
                label_visibility="collapsed",
            )

        month_data = all_data if ano == "Todos" else route_json(route, {"ano": ano, "mes": ["Todos"]})
        meses = unique_filter_options(month_data.get("meses", []) or [])
        mes_options = ["Todos", *meses]
        mes_key = f"{key_prefix}_mes"
        mes_previous_key = f"{mes_key}__previous"
        mes_state_exists = mes_key in st.session_state
        current_meses = (
            st.session_state.get(mes_key, ["Todos"])
            if mes_state_exists
            else default_closed_month_selection(mes_options, ano)
        )
        current_meses = [item for item in current_meses if item in mes_options] or ["Todos"]
        if mes_state_exists and st.session_state.get(mes_key) != current_meses:
            st.session_state[mes_key] = current_meses
            st.session_state[mes_previous_key] = current_meses
        if mes_previous_key not in st.session_state:
            st.session_state[mes_previous_key] = current_meses
        with filter_cols[1]:
            mes_kwargs = {
                "key": mes_key,
                "on_change": sync_multiselect_selection,
                "args": (mes_key,),
                "format_func": month_filter_label,
                "label_visibility": "collapsed",
            }
            if not mes_state_exists:
                mes_kwargs["default"] = current_meses
            meses_selected = st.multiselect("Mês", mes_options, **mes_kwargs)
            meses_selected = normalize_multiselect(meses_selected, st.session_state.get(mes_previous_key, ["Todos"]))

        params: dict[str, object] = {"ano": None if ano == "Todos" else ano, "mes": query_mes(meses_selected)}
        for idx, (param_name, label, options) in enumerate(extra_filters, start=2):
            options = unique_filter_options(options)
            state_key = f"{key_prefix}_{param_name}"
            current = st.session_state.get(state_key)
            if current in ("Todos", "") or current not in options:
                current = None
                st.session_state[state_key] = None
            with filter_cols[idx]:
                selected = st.selectbox(
                    label,
                    options,
                    index=None,
                    key=state_key,
                    placeholder=f"{label} (Todos)",
                    label_visibility="collapsed",
                )
                params[param_name] = "Todos" if selected is None else selected

        compare_selected = []
        if allow_compare:
            compare_key = f"{key_prefix}_compare"
            compare_state_exists = compare_key in st.session_state
            compare_current = [item for item in st.session_state.get(compare_key, []) if item in compare_options]
            if compare_state_exists and st.session_state.get(compare_key) != compare_current:
                st.session_state[compare_key] = compare_current
            compare_kwargs = {
                "key": compare_key,
                "format_func": lambda value: DASHBOARD_META.get(value, {}).get("label", value),
                "label_visibility": "collapsed",
                "placeholder": "Comparar",
            }
            if not compare_state_exists:
                compare_kwargs["default"] = []
            with filter_cols[-3]:
                compare_selected = st.multiselect("Comparar", compare_options, **compare_kwargs)

        with filter_cols[-2]:
            if st.button("Limpar filtros", key=f"{key_prefix}_clear", width="stretch"):
                for state_key in list(st.session_state.keys()):
                    if state_key.startswith(f"{key_prefix}_"):
                        del st.session_state[state_key]
                st.rerun()
        with filter_cols[-1]:
            st.markdown('<a class="filter-back" href="?page=home" target="_self">&larr; Voltar</a>', unsafe_allow_html=True)

    for key, value in list(params.items()):
        if value == "Todos":
            params[key] = None
    all_data = dict(all_data)
    all_data["_compare"] = [item for item in compare_selected if item in compare_options]
    return params, all_data


def compare_query_params(route: str, params: dict[str, object]) -> dict[str, object]:
    query: dict[str, object] = {}
    if params.get("ano") is not None:
        query["ano"] = params.get("ano")
    if params.get("mes") is not None:
        query["mes"] = params.get("mes")
    if params.get("categoria") is not None:
        query["categoria"] = params.get("categoria")
    if params.get("segmento") is not None:
        query["segmento"] = params.get("segmento")
    if DASHBOARD_META.get(route, {}).get("supports_plate") and params.get("placa"):
        query["placa"] = params.get("placa")
    return query


def compare_bundle(
    current_route: str,
    current_data: dict,
    params: dict[str, object],
    selected_routes: list[str],
) -> list[tuple[str, dict]]:
    bundle = [(current_route, current_data)]
    for route in selected_routes:
        if route == current_route or route not in COMPARE_ALLOWED_ROUTES or route not in DASHBOARD_META:
            continue
        try:
            data = route_json(route, compare_query_params(route, params))
        except Exception:
            data = {}
        bundle.append((route, data))
    return bundle


def compare_chart_series(bundle: list[tuple[str, dict]], metric: str) -> list[dict]:
    series = []
    for route, data in bundle:
        config = COMPARE_SERIES.get(route, {}).get(metric)
        if not config:
            continue
        source_key, label_key, value_key = config
        source = data.get(source_key, {}) if isinstance(data, dict) else {}
        labels = list(source.get(label_key, []) or [])
        values = list(source.get(value_key, []) or [])
        series.append(
            {
                "route": route,
                "label": _series_label(route),
                "color": _series_color(route),
                "raw_labels": labels,
                "values": values,
            }
        )
    return series


def frota_plate_compare_bundle(params: dict[str, object], selected_plates: list[str]) -> list[tuple[str, dict, str]]:
    bundle = []
    for index, plate in enumerate(selected_plates):
        plate_params = dict(params)
        plate_params["placa"] = [plate]
        plate_params["incluir_hoteis"] = False
        try:
            data = route_json("frota", plate_params)
        except Exception:
            data = {}
        bundle.append((plate, data, YEAR_SERIES_COLORS[index % len(YEAR_SERIES_COLORS)]))
    return bundle


def frota_route_compare_bundle(
    params: dict[str, object],
    selected_routes: list[str],
    hotel_by_route: dict[str, bool] | None = None,
) -> list[tuple[str, dict, str]]:
    bundle = []
    for index, route_name in enumerate(selected_routes):
        route_params = dict(params)
        route_params["rota"] = [route_name]
        if hotel_by_route is not None:
            route_params["incluir_hoteis"] = bool(hotel_by_route.get(route_name, False))
        try:
            data = route_json("frota", route_params)
        except Exception:
            data = {}
        bundle.append((route_name, data, YEAR_SERIES_COLORS[index % len(YEAR_SERIES_COLORS)]))
    return bundle


def frota_route_comparison_html(
    bundle: list[tuple[str, dict, str]],
    *,
    hide_fuel: bool = False,
    show_daily: bool = False,
    show_hotels: bool = False,
    show_heading: bool = True,
) -> str:
    route_rows = []
    for route_name, data, color in bundle:
        totals = data.get("totais", {}) if isinstance(data, dict) else {}
        hotel_enabled = (
            bool(totals.get("inclui_hoteis"))
            if "inclui_hoteis" in totals
            else show_hotels
        )
        route_row = {
            "rota": route_name,
            "color": color,
            "placas": totals.get("placas"),
            "entregas": totals.get("entregas"),
            "ganho": totals.get("valor_peso"),
            "total": totals.get("total"),
            "combustivel": totals.get("combustivel"),
            "manutencao": totals.get("manutencao"),
            "manutencao_diaria": totals.get("manutencao_diaria"),
            "dias_na_rota": totals.get("dias_na_rota"),
            "pedagio": totals.get("pedagio"),
            "gasto_diarias": totals.get("gasto_diarias"),
            "dias_trabalhados": totals.get("dias_trabalhados"),
            "salario_transporte": totals.get("salario_transporte"),
            "hoteis": totals.get("hoteis"),
            "hoteis_diaria": totals.get("hoteis_diaria"),
            "dias_hoteis": totals.get("dias_hoteis"),
            "hotel_enabled": hotel_enabled,
            "peso": totals.get("peso_total"),
        }
        delivery_value = _ranking_float(route_row, "ganho")
        route_row["percentual_custo"] = (
            _ranking_float(route_row, "total") / delivery_value * 100
            if delivery_value > 0
            else None
        )
        route_rows.append(route_row)
    if len(route_rows) < 2:
        return ""

    highest_gain = max(route_rows, key=lambda row: _ranking_float(row, "ganho"))
    lowest_cost = min(route_rows, key=lambda row: _ranking_float(row, "total"))
    highest_weight = max(route_rows, key=lambda row: _ranking_float(row, "peso"))
    routes_with_delivery_value = [
        row for row in route_rows if _ranking_float(row, "ganho") > 0
    ]
    highlights = [
        ("Maior ganho das entregas", highest_gain, "ganho", fmt_brl_big),
        ("Menor gasto total", lowest_cost, "total", fmt_brl_big),
        ("Maior peso transportado", highest_weight, "peso", fmt_peso),
    ]
    if routes_with_delivery_value:
        lowest_cost_ratio = min(
            routes_with_delivery_value,
            key=lambda row: _ranking_float(row, "percentual_custo"),
        )
        highlights.insert(
            2,
            ("Menor custo sobre entregas", lowest_cost_ratio, "percentual_custo", fmt_percent),
        )
    highlight_html = "".join(
        '<div class="ranking-difference-item">'
        f'<p class="ranking-difference-label">{h(label)}</p>'
        f'<p class="ranking-difference-value">{h(formatter(row.get(key)))}</p>'
        f'<p class="ranking-difference-note">{h(row.get("rota") or "Sem rota")}</p>'
        "</div>"
        for label, row, key, formatter in highlights
    )

    metrics = [
        ("Placas", "placas", fmt_num, ""),
        ("Número de entregas", "entregas", fmt_num, ""),
        ("Ganho das entregas", "ganho", fmt_brl_big, " route-compare-metric--gain"),
        ("Gasto total da rota", "total", fmt_brl_big, ""),
        ("Custo sobre o valor das entregas", "percentual_custo", fmt_percent, " route-compare-metric--ratio"),
    ]
    if not hide_fuel:
        metrics.append(("Combustível", "combustivel", fmt_brl_big, ""))
    metrics.extend(
        [
            ("Manutenção estimada", "manutencao", fmt_brl_big, ""),
            ("Dias na rota", "dias_na_rota", fmt_num, ""),
            ("Pedágio/Extras", "pedagio", fmt_brl_big, ""),
        ]
    )
    if show_daily:
        metrics.extend(
            [
                ("Gasto com diárias com freteiro", "gasto_diarias", fmt_brl_big, ""),
                ("Dias trabalhados", "dias_trabalhados", fmt_num, ""),
            ]
        )
    if any(_ranking_float(row, "salario_transporte") > 0 for row in route_rows):
        metrics.append(
            (
                "Salário do Transporte",
                "salario_transporte",
                fmt_brl_big,
                "",
            )
        )
    metrics.append(("Peso total", "peso", fmt_peso, ""))

    cards = []
    for row in route_rows:
        row_metrics = list(metrics)
        if row.get("hotel_enabled"):
            row_metrics[-1:-1] = [
                ("Hotéis estimados", "hoteis", fmt_brl_big, ""),
                ("Média diária geral de hotéis", "hoteis_diaria", fmt_brl_big, ""),
                ("Dias aplicados aos hotéis", "dias_hoteis", fmt_num, ""),
            ]
        body = "".join(
            f'<div class="ranking-versus-metric{modifier}"><span>{h(label)}</span>'
            f'<span>{h(formatter(row.get(key)))}</span></div>'
            for label, key, formatter, modifier in row_metrics
        )
        hotel_status = (
            '<span class="route-compare-hotel-status">Hotel incluído</span>'
            if row.get("hotel_enabled")
            else ""
        )
        cards.append(
            f'<article class="ranking-versus-card route-compare-card" style="--route-accent:{h(row["color"])}">'
            '<div class="route-compare-card-heading">'
            f'<h3>{h(row.get("rota") or "Sem rota")}</h3>{hotel_status}'
            f'</div>{body}</article>'
        )

    heading = (
        '<h2 class="ranking-versus-title">Comparativo entre rotas</h2>'
        '<p class="route-compare-note">Valores calculados separadamente para cada rota nos mesmos filtros de período, categoria e placa.</p>'
        if show_heading
        else ""
    )
    return (
        heading
        + '<section class="ranking-difference">'
        '<h3>Destaques das rotas selecionadas</h3>'
        f'<div class="ranking-difference-grid">{highlight_html}</div>'
        "</section>"
        f'<section class="ranking-versus-grid">{"".join(cards)}</section>'
    )


def _route_hotel_toggle_key(route_name: str) -> str:
    route_hash = hashlib.sha1(str(route_name).encode("utf-8")).hexdigest()[:12]
    return f"rank_compare_hotel_{route_hash}"


@st.fragment
def render_frota_route_compare(
    params: dict[str, object],
    selected_routes: list[str],
    *,
    default_include_hotels: bool,
    hide_fuel: bool,
    show_daily: bool,
) -> None:
    st.html(
        '<h2 class="ranking-versus-title">Comparativo entre rotas</h2>'
        '<p class="route-compare-note">Ative ou desative os hotéis separadamente para cada rota.</p>'
    )
    hotel_by_route: dict[str, bool] = {}
    with st.container(key="frota_route_hotel_controls"):
        st.markdown("HOTÉIS INCLUÍDOS NO CUSTO DE CADA ROTA")
        columns = st.columns(min(len(selected_routes), 3))
        for index, route_name in enumerate(selected_routes):
            toggle_key = _route_hotel_toggle_key(route_name)
            with columns[index % len(columns)]:
                hotel_by_route[route_name] = st.toggle(
                    f"Incluir hotel — {route_name}",
                    value=default_include_hotels,
                    key=toggle_key,
                )

    route_compare = frota_route_compare_bundle(
        params,
        selected_routes,
        hotel_by_route,
    )
    st.html(
        frota_route_comparison_html(
            route_compare,
            hide_fuel=hide_fuel,
            show_daily=show_daily,
            show_heading=False,
        )
    )


def frota_plate_monthly_series(bundle: list[tuple[str, dict, str]], source_key: str, value_key: str) -> list[dict]:
    series = []
    for plate, data, color in bundle:
        source = data.get(source_key, {}) if isinstance(data, dict) else {}
        series.append(
            {
                "route": "frota",
                "label": plate,
                "color": color,
                "raw_labels": list(source.get("Mes", []) or []),
                "values": list(source.get(value_key, []) or []),
            }
        )
    return series


def color_kpis(
    kpis: list[tuple],
    route: str,
    *,
    prefix: bool = False,
    exclude_ids: set[str] | None = None,
    section: str | None = None,
) -> list[tuple]:
    color = _series_color(route)
    route_label = _series_label(route)
    exclude_ids = exclude_ids or set()
    colored = []
    for item in kpis:
        item_id, label, value = item[0], item[1], item[2]
        if item_id in exclude_ids:
            continue
        display_label = f"{route_label} - {label}" if prefix else label
        if section:
            colored.append((item_id, display_label, value, color, section))
        else:
            colored.append((item_id, display_label, value, color))
    return colored


def _compare_total(route: str, data: dict) -> float:
    key = {
        "combustivel": "custo_total",
        "manutencao": "custo_total",
        "hoteis": "valor_total",
        "pedagio": "custo_total",
        "vex": "total_vex",
    }.get(route)
    if not key:
        return 0.0
    try:
        return float(data.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _compare_media(route: str, data: dict) -> float:
    key = {
        "combustivel": "media_mensal",
        "manutencao": "media_mensal",
        "hoteis": "media_mensal",
        "pedagio": "media_mensal",
    }.get(route)
    if not key:
        return 0.0
    try:
        return float(data.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def compare_combined_kpis(bundle: list[tuple[str, dict]]) -> list[tuple]:
    total = sum(_compare_total(route, data) for route, data in bundle)
    media = sum(_compare_media(route, data) for route, data in bundle)
    return [
        ("compare_total_geral", "Total comparado (R$)", fmt_brl(total), JR_RED, "Comparativo geral"),
        ("compare_media_geral", "Média mensal comparada (R$)", fmt_brl(media), JR_RED, "Comparativo geral"),
    ]


def compare_kpi_cards(bundle: list[tuple[str, dict]]) -> list[tuple]:
    cards: list[tuple] = []
    for route, data in bundle:
        color = _series_color(route)
        label = _series_label(route)
        if route == "combustivel":
            route_cards = [
                ("total", "Total (R$)", fmt_brl(data.get("custo_total"))),
                ("media_mensal", "Média mensal (R$)", fmt_brl(data.get("media_mensal"))),
                ("km", "KM total", fmt_num(data.get("km_total"))),
                ("litros", "Total litros", fmt_num(data.get("litros_total"))),
                ("custo_km", "Custo médio por KM", fmt_brl(data.get("custo_por_km"))),
                ("kml", "Média KM/L", f"{fmt_num(data.get('km_por_litro'), 2)} km/L"),
                ("custo_litro", "Custo médio por litro", fmt_brl(data.get("custo_por_litro"))),
            ]
        elif route == "manutencao":
            route_cards = [
                ("custo_total", "Custo total (R$)", fmt_brl(data.get("custo_total"))),
                ("media_mensal", "Média mensal (R$)", fmt_brl(data.get("media_mensal"))),
                ("servicos", "Serviços", fmt_num(data.get("total_servicos"))),
                ("ticket", "Ticket médio", fmt_brl(data.get("media_servico"))),
            ]
        elif route == "hoteis":
            route_cards = [
                ("valor_total", "Valor total (R$)", fmt_brl(data.get("valor_total"))),
                ("media_mensal", "Média mensal", fmt_brl(data.get("media_mensal"))),
                ("reservas", "Reservas", fmt_num(data.get("reservas_total"))),
                ("nao_planejadas", "Reservas não planejadas", fmt_num(data.get("reservas_nao_planejadas"))),
                ("media_reserva", "Média por reserva", fmt_brl(data.get("valor_medio_reserva"))),
                ("sabados", "Gasto aos sábados (R$)", fmt_brl(data.get("valor_sabado"))),
                ("nao_planejado", "Gasto não planejado (R$)", fmt_brl(data.get("valor_nao_planejado"))),
            ]
        elif route == "pedagio":
            route_cards = [
                ("gasto_total", "Gasto total (R$)", fmt_brl(data.get("custo_total"))),
                ("media_mensal", "Média mensal (R$)", fmt_brl(data.get("media_mensal"))),
                ("pedagio", "Gasto pedágio", fmt_brl(data.get("gasto_pedagio"))),
                ("ipva", "Gasto IPVA", fmt_brl(data.get("gasto_ipva"))),
                ("seguro", "Gasto seguro", fmt_brl(data.get("gasto_seguro"))),
                ("seguros", "Seguros", fmt_num(data.get("qtd_seguro"))),
                ("media_valores", "Média de valores", fmt_brl(data.get("media_valores", data.get("ticket_medio")))),
            ]
        elif route == "vex":
            route_cards = [
                ("gasto_vex", "Gasto Vex total (R$)", fmt_brl(data.get("total_vex"))),
                ("combustivel", "Combustível Vex (R$)", fmt_brl(data.get("combustivel_total"))),
                ("km_total", "KM total", fmt_num(data.get("km_total"))),
                ("litros_total", "Total litros", fmt_num(data.get("litros_total"))),
                ("custo_km", "Custo por KM", fmt_brl(data.get("custo_por_km"))),
                ("media_kml", "Média KM/L", fmt_num(data.get("km_por_litro"), 2)),
                ("custo_litro", "Custo médio por litro", fmt_brl(data.get("custo_por_litro"))),
                ("manutencao", "Manutenção Vex (R$)", fmt_brl(data.get("manutencao_total"))),
                ("pedagio", "Pedágio Vex (R$)", fmt_brl(data.get("pedagio_total"))),
                ("aluguel_veiculos", "Aluguel de veículos Vex (R$)", fmt_brl(data.get("aluguel_veiculos_total"))),
            ]
        else:
            route_cards = []
        cards.extend((f"compare_{route}_{item_id}", card_label, value, color, label) for item_id, card_label, value in route_cards)
    return cards


def frota_filter_controls(seed: dict) -> dict[str, object]:
    years = seed.get("anos", []) or []
    year_options = ["Todos", *years]
    year_default = last_closed_year_default(years, st.session_state.get("rank_ano"))
    year_index = year_options.index(year_default) if year_default in year_options else 0

    with st.container(key="rank_filterbar"):
        cols = st.columns([0.65, 1.0, 1.05, 1.1, 1.15, 0.78, 0.82, 1.0, 0.88, 0.68])
        with cols[0]:
            ano = st.selectbox(
                "Ano",
                year_options,
                index=year_index,
                key="rank_ano",
                format_func=select_all_label("Ano"),
                label_visibility="collapsed",
            )

        month_seed = seed if ano == "Todos" else route_json("frota", {"ano": ano, "mes": ["Todos"]})
        meses = unique_filter_options(month_seed.get("meses", []) or [])
        mes_key = "rank_mes"
        mes_state_exists = mes_key in st.session_state
        current_meses = (
            st.session_state.get(mes_key, [])
            if mes_state_exists
            else default_closed_month_selection(["Todos", *meses], ano)
        )
        if not isinstance(current_meses, list):
            current_meses = [current_meses] if current_meses else []
        current_meses = [item for item in current_meses if item != "Todos" and item in meses]
        if mes_state_exists and st.session_state.get(mes_key) != current_meses:
            st.session_state[mes_key] = current_meses
        month_button_label = (
            "Mês (Todos)"
            if not current_meses
            else month_filter_label(current_meses[0])
            if len(current_meses) == 1
            else f"{len(current_meses)} meses selecionados"
        )
        with cols[1]:
            with st.popover(
                month_button_label,
                key="rank_month_popover",
                help="Selecione um ou mais meses. Sem seleção, todos os meses são considerados.",
                use_container_width=True,
            ):
                st.caption("CALENDÁRIO DE MESES")
                if st.button("Usar todos os meses", key="rank_month_all", width="stretch"):
                    st.session_state[mes_key] = []
                    st.rerun()
                mes_kwargs = {
                    "key": mes_key,
                    "selection_mode": "multi",
                    "format_func": month_filter_label,
                    "label_visibility": "collapsed",
                    "width": "stretch",
                }
                if not mes_state_exists:
                    mes_kwargs["default"] = current_meses
                meses_selected = st.pills("Meses", meses, **mes_kwargs) or []
                if meses_selected:
                    st.caption(f"{len(meses_selected)} mês(es) selecionado(s).")
                else:
                    st.caption("Todos os meses estão incluídos.")

        category_options = ["Todos", *unique_filter_options(seed.get("categorias", []) or [])]
        categoria_default = [item for item in ("Transporte", "Freteiro") if item in category_options] or ["Todos"]
        categoria_key = "rank_categoria"
        categoria_previous_key = f"{categoria_key}__previous"
        categoria_state_exists = categoria_key in st.session_state
        categoria_current = st.session_state.get(categoria_key, categoria_default)
        if not isinstance(categoria_current, list):
            categoria_current = [categoria_current]
        categoria_current = [item for item in categoria_current if item in category_options] or categoria_default
        if categoria_state_exists and st.session_state.get(categoria_key) != categoria_current:
            st.session_state[categoria_key] = categoria_current
            st.session_state[categoria_previous_key] = categoria_current
        if categoria_previous_key not in st.session_state:
            st.session_state[categoria_previous_key] = categoria_current
        with cols[2]:
            categoria_kwargs = {
                "key": categoria_key,
                "on_change": sync_multiselect_selection,
                "args": (categoria_key,),
                "format_func": select_all_label("Categoria"),
                "label_visibility": "collapsed",
                "placeholder": "Categoria (Todos)",
            }
            if not categoria_state_exists:
                categoria_kwargs["default"] = categoria_current
            categoria_selected = st.multiselect("Categoria", category_options, **categoria_kwargs)
            categoria_selected = normalize_multiselect(categoria_selected, st.session_state.get(categoria_previous_key, ["Todos"]))
        categoria_param = query_multiselect(categoria_selected)
        only_freteiro = categoria_param == ["Freteiro"]
        include_salary = bool(st.session_state.get("rank_incluir_salario", True))
        include_hoteis = bool(st.session_state.get("rank_incluir_hoteis", False))

        route_seed_params = {
            "ano": None if ano == "Todos" else ano,
            "mes": query_mes(meses_selected),
            "categoria": categoria_param,
            "incluir_salario": include_salary,
            "incluir_hoteis": include_hoteis,
            "ordenar_por": "total",
        }
        route_seed = route_json(
            "frota",
            route_seed_params,
        )
        route_options_base = unique_filter_options(route_seed.get("rotas", []) or [])
        route_cost_rows = (
            route_seed.get("custo_ganho_rotas", {}).get("rotas", [])
            if isinstance(route_seed.get("custo_ganho_rotas"), dict)
            else []
        )
        route_cost_map = {
            str(row.get("rota")): row
            for row in route_cost_rows
            if isinstance(row, dict) and str(row.get("rota") or "").strip()
        }
        route_monthly_rows = (
            route_seed.get("custo_ganho_rotas", {}).get("mensal", [])
            if isinstance(route_seed.get("custo_ganho_rotas"), dict)
            else []
        )
        route_alert_rows = [
            row
            for row in route_monthly_rows
            if isinstance(row, dict) and row.get("nivel") in {"amarelo", "vermelho"}
        ]
        route_worst_alert: dict[str, dict] = {}
        for row in route_alert_rows:
            route_name = str(row.get("rota") or "")
            previous = route_worst_alert.get(route_name)
            row_score = (
                2 if row.get("nivel") == "vermelho" else 1,
                bool(row.get("sem_ganho")),
                float(row.get("percentual") or 0.0),
            )
            previous_score = (
                2 if previous and previous.get("nivel") == "vermelho" else 1 if previous else 0,
                bool(previous and previous.get("sem_ganho")),
                float(previous.get("percentual") or 0.0) if previous else 0.0,
            )
            if previous is None or row_score > previous_score:
                route_worst_alert[route_name] = row
        route_key = "rank_rota_selecao"
        route_state_exists = route_key in st.session_state
        current_routes = st.session_state.get(route_key, [])
        if not isinstance(current_routes, list):
            current_routes = [current_routes] if current_routes else []
        current_routes = [item for item in current_routes if item in route_options_base]
        if not RANK_ROUTES_ENABLED:
            current_routes = []
        if route_state_exists and st.session_state.get(route_key) != current_routes:
            st.session_state[route_key] = current_routes
        route_button_label = (
            "Rotas desativadas"
            if not RANK_ROUTES_ENABLED
            else "Rota (Todos)"
            if not current_routes
            else str(current_routes[0])
            if len(current_routes) == 1
            else f"{len(current_routes)} rotas selecionadas"
        )
        with cols[3]:
            with st.popover(
                route_button_label,
                key="rank_route_popover",
                help=(
                    "O filtro de rotas está temporariamente desativado."
                    if not RANK_ROUTES_ENABLED
                    else "Mostra somente as rotas da nova importação por PDF. Sem seleção, são usados os totais gerais do período."
                ),
                disabled=not RANK_ROUTES_ENABLED,
                use_container_width=True,
            ):
                route_order = st.selectbox(
                    "Ordenar rotas",
                    ["custo_ganho", "alfabetica"],
                    key="rank_route_order",
                    format_func=lambda value: (
                        "Maior custo sobre ganho" if value == "custo_ganho" else "Ordem alfabética"
                    ),
                )
                st.caption("Os percentuais usam somente os meses que possuem rotas importadas.")
                route_options = list(route_options_base)
                if route_order == "custo_ganho":
                    route_options.sort(
                        key=lambda route: (
                            bool(route_cost_map.get(str(route), {}).get("sem_ganho")),
                            float(route_cost_map.get(str(route), {}).get("percentual") or 0.0),
                            float(route_cost_map.get(str(route), {}).get("custo") or 0.0),
                        ),
                        reverse=True,
                    )
                else:
                    route_options.sort(key=lambda route: str(route).casefold())

                def route_filter_label(route: object) -> str:
                    row = route_cost_map.get(str(route), {})
                    alert = route_worst_alert.get(str(route), {})
                    alert_prefix = "🔴 " if alert.get("nivel") == "vermelho" else "🟡 " if alert else ""
                    if row.get("sem_ganho"):
                        return f"{alert_prefix}{route} — sem ganho"
                    percentage = row.get("percentual")
                    return (
                        f"{alert_prefix}{route} — {fmt_percent(percentage)}"
                        if percentage is not None
                        else f"{alert_prefix}{route}"
                    )

                route_kwargs = {
                    "key": route_key,
                    "selection_mode": "multi",
                    "format_func": route_filter_label,
                    "label_visibility": "collapsed",
                    "width": "stretch",
                }
                if not route_state_exists:
                    route_kwargs["default"] = current_routes
                routes_selected = st.pills("Rotas", route_options, **route_kwargs) or []
                if route_alert_rows:
                    with st.expander("Alertas mensais de custo sobre ganho", expanded=False):
                        critical_lines = []
                        warning_lines = []
                        for row in sorted(
                            route_alert_rows,
                            key=lambda item: (
                                str(item.get("rota") or "").casefold(),
                                str(item.get("mes") or ""),
                            ),
                        ):
                            percentage = (
                                "sem ganho registrado"
                                if row.get("sem_ganho")
                                else fmt_percent(row.get("percentual"))
                            )
                            line = (
                                f"- **{row.get('rota') or 'Sem rota'} · {month_filter_label(row.get('mes'))}:** "
                                f"{percentage}"
                            )
                            if row.get("nivel") == "vermelho":
                                critical_lines.append(line)
                            else:
                                warning_lines.append(line)
                        if critical_lines:
                            st.error("\n\n".join(critical_lines), icon="🚨")
                        if warning_lines:
                            st.warning("\n\n".join(warning_lines), icon="⚠️")
        route_param = (
            [str(item) for item in routes_selected]
            if RANK_ROUTES_ENABLED and routes_selected
            else ["Todos"]
        )

        plate_seed = (
            route_seed
            if route_param == ["Todos"]
            else route_json("frota", {**route_seed_params, "rota": route_param})
        )
        plate_options = unique_filter_options(plate_seed.get("placas", []) or [])
        plate_key = "rank_placa"
        plate_state_exists = plate_key in st.session_state
        current_plates = st.session_state.get(plate_key, [])
        if not isinstance(current_plates, list):
            current_plates = [current_plates] if current_plates else []
        current_plates = [item for item in current_plates if item != "Todos" and item in plate_options]
        if plate_state_exists and st.session_state.get(plate_key) != current_plates:
            st.session_state[plate_key] = current_plates
        plate_button_label = (
            "Placa (Todas)"
            if not current_plates
            else str(current_plates[0])
            if len(current_plates) == 1
            else f"{len(current_plates)} placas selecionadas"
        )
        with cols[4]:
            with st.popover(
                plate_button_label,
                key="rank_plate_popover",
                help="Busque e selecione uma ou mais placas. Sem seleção, todas são consideradas.",
                use_container_width=True,
            ):
                st.caption("BUSCAR E SELECIONAR PLACAS")
                plate_kwargs = {
                    "key": plate_key,
                    "label_visibility": "collapsed",
                    "placeholder": "Digite a placa para buscar",
                    "width": "stretch",
                }
                if not plate_state_exists:
                    plate_kwargs["default"] = current_plates
                placas_selected = st.multiselect("Placas", plate_options, **plate_kwargs)
                components.html(
                    """
                    <script>
                    (() => {
                      const parentDocument = window.parent.document;
                      const focusPlateSearch = () => {
                        const inputs = Array.from(
                          parentDocument.querySelectorAll(
                            '.st-key-rank_placa input[role="combobox"]'
                          )
                        ).filter((input) => input.offsetParent !== null && !input.disabled);
                        const input = inputs.at(-1);
                        if (!input) return false;
                        input.focus({ preventScroll: true });
                        input.select();
                        return parentDocument.activeElement === input;
                      };

                      let attempts = 0;
                      const timer = window.setInterval(() => {
                        attempts += 1;
                        if (focusPlateSearch() || attempts >= 30) {
                          window.clearInterval(timer);
                        }
                      }, 50);
                      window.setTimeout(focusPlateSearch, 0);
                    })();
                    </script>
                    """,
                    height=0,
                    scrolling=False,
                )
                if placas_selected:
                    st.caption(f"{len(placas_selected)} placa(s) selecionada(s).")
                else:
                    st.caption("Todas as placas estão incluídas.")

        with cols[5]:
            include_hoteis = st.checkbox(
                "Incluir hotéis",
                value=include_hoteis,
                key="rank_incluir_hoteis",
                label_visibility="visible",
            )

        with cols[6]:
            include_salary = st.checkbox(
                "Incluir salário",
                value=include_salary,
                key="rank_incluir_salario",
                label_visibility="visible",
            )

        order_options = [key for key in RANK_ORDER_OPTIONS if not (only_freteiro and key == "combustivel")]
        order_current = st.session_state.get("rank_ordenar_por", "total")
        if order_current not in order_options:
            order_current = "total"
            st.session_state["rank_ordenar_por"] = order_current
        with cols[7]:
            ordenar_por = st.selectbox(
                "Ordenar por",
                order_options,
                index=order_options.index(order_current),
                key="rank_ordenar_por",
                format_func=lambda value: f"Ordenar: {RANK_ORDER_OPTIONS.get(value, value)}",
                label_visibility="collapsed",
            )

        with cols[8]:
            if st.button("Limpar filtros", key="rank_clear", width="stretch"):
                for state_key in list(st.session_state.keys()):
                    if state_key.startswith("rank_"):
                        del st.session_state[state_key]
                st.rerun()
        with cols[9]:
            st.markdown('<a class="filter-back" href="?page=home" target="_self">&larr; Voltar</a>', unsafe_allow_html=True)

    return {
        "ano": None if ano == "Todos" else ano,
        "mes": query_mes(meses_selected),
        "categoria": categoria_param,
        "rota": route_param,
        "incluir_hoteis": include_hoteis,
        "incluir_salario": include_salary,
        "placa": ["Todos"] if not placas_selected else [str(item) for item in placas_selected],
        "ordenar_por": ordenar_por,
    }


def ranking_summary_html(
    row: dict,
    *,
    hide_fuel: bool = False,
    show_daily: bool = False,
    show_route_maintenance_daily: bool = False,
) -> str:
    items = [
        ("Posição", f"#{int(row.get('rank') or 0):02d}"),
        ("Placa", row.get("placa") or "Sem placa"),
        ("Total", fmt_brl_big(row.get("total"))),
        ("Manutenção", fmt_brl_big(row.get("manutencao"))),
        ("Pedágio/Extras", fmt_brl_big(row.get("pedagio"))),
        ("Peso", fmt_peso(row.get("peso_total"))),
    ]
    if show_route_maintenance_daily:
        items[4:4] = [
            ("Manutenção por dia", fmt_brl_big(row.get("manutencao_diaria"))),
            ("Dias na rota", fmt_num(row.get("dias_na_rota"))),
        ]
    if show_daily and str(row.get("categoria") or "") == "Freteiro":
        items[3:3] = [
            ("Gasto com diárias com freteiro", fmt_brl_big(row.get("gasto_diarias"))),
            ("Dias trabalhados", fmt_num(row.get("dias_trabalhados"))),
        ]
    if _ranking_float(row, "salario_transporte") > 0:
        items[3:3] = [
            ("Salário do Transporte", fmt_brl_big(row.get("salario_transporte"))),
        ]
    if not hide_fuel:
        items.insert(3, ("Combustível", fmt_brl_big(row.get("combustivel"))))
    return "".join(
        f'<div class="ranking-summary-item"><p class="ranking-summary-label">{h(label)}</p><p class="ranking-summary-value">{h(value)}</p></div>'
        for label, value in items
    )


def ranking_detail_html(
    row: dict,
    *,
    hide_fuel: bool = False,
    show_daily: bool = False,
    show_route_maintenance_daily: bool = False,
) -> str:
    items = [
        ("Gasto total", fmt_brl_big(row.get("total"))),
        ("Manutenção", fmt_brl_big(row.get("manutencao"))),
        ("Pedágio/Extras", fmt_brl_big(row.get("pedagio"))),
        ("Peso", fmt_peso(row.get("peso_total"))),
        ("Valor entregas", fmt_brl_big(row.get("valor_peso"))),
        ("Serviços", fmt_num(row.get("servicos"))),
        ("Pedágio/Extras", fmt_num(row.get("despesas_pedagio"))),
    ]
    if show_route_maintenance_daily:
        items[2:2] = [
            ("Manutenção por dia", fmt_brl_big(row.get("manutencao_diaria"))),
            ("Dias na rota", fmt_num(row.get("dias_na_rota"))),
        ]
    if show_daily and str(row.get("categoria") or "") == "Freteiro":
        items[1:1] = [
            ("Valor da diária", fmt_brl_big(row.get("diaria"))),
            ("Dias trabalhados", fmt_num(row.get("dias_trabalhados"))),
            ("Gasto com diárias com freteiro", fmt_brl_big(row.get("gasto_diarias"))),
        ]
    if _ranking_float(row, "salario_transporte") > 0:
        items[1:1] = [
            ("Salário do Transporte", fmt_brl_big(row.get("salario_transporte"))),
        ]
    if not hide_fuel:
        items[1:1] = [
            ("Combustível", fmt_brl_big(row.get("combustivel"))),
            ("KM total", fmt_num(row.get("km_total"))),
            ("Litros", fmt_num(row.get("litros_total"))),
            ("Custo total por KM", fmt_brl(row.get("custo_por_km"))),
            ("Combustível por KM", fmt_brl(row.get("combustivel_por_km"))),
            ("Média KM/L", f"{fmt_num(row.get('km_por_litro'), 2)} km/L"),
            ("Custo por litro", fmt_brl(row.get("custo_por_litro"))),
            ("Abastecimentos", fmt_num(row.get("abastecimentos"))),
        ]
    cards = "".join(
        f'<div class="ranking-detail-card"><p class="ranking-detail-label">{h(label)}</p><p class="ranking-detail-value">{h(value)}</p></div>'
        for label, value in items
    )
    return (
        '<div class="ranking-row-summary">'
        f'{ranking_summary_html(row, hide_fuel=hide_fuel, show_daily=show_daily, show_route_maintenance_daily=show_route_maintenance_daily)}'
        '</div>'
        f'<div class="ranking-detail-grid">{cards}</div>'
    )


def ranking_row_label(
    row: dict,
    *,
    hide_fuel: bool = False,
    show_daily: bool = False,
    show_route_maintenance_daily: bool = False,
) -> str:
    def money(value: object) -> str:
        return fmt_brl_big(value).replace("$", r"\$")

    parts = [
        f"{int(row.get('rank') or 0):02d} | {row.get('placa') or 'Sem placa'}",
        f"Total {money(row.get('total'))}",
        f"Manutenção {money(row.get('manutencao'))}",
        f"Pedágio/Extras {money(row.get('pedagio'))}",
        f"Peso {fmt_peso(row.get('peso_total'))}",
    ]
    if show_route_maintenance_daily:
        parts.insert(
            3,
            f"Manut./dia {money(row.get('manutencao_diaria'))} ({fmt_num(row.get('dias_na_rota'))} dias)",
        )
    if show_daily and str(row.get("categoria") or "") == "Freteiro":
        parts.insert(
            2,
            f"Diárias {money(row.get('gasto_diarias'))} ({fmt_num(row.get('dias_trabalhados'))} dias)",
        )
    if _ranking_float(row, "salario_transporte") > 0:
        parts.insert(2, f"Salário Transporte {money(row.get('salario_transporte'))}")
    if not hide_fuel:
        parts.insert(2, f"Combustível {money(row.get('combustivel'))}")
        parts.extend([f"KM {fmt_num(row.get('km_total'))}", f"Litros {fmt_num(row.get('litros_total'))}"])
    return " | ".join(parts)


def ranking_native_table_html(
    rows: list[dict],
    *,
    hide_fuel: bool = False,
    show_daily: bool = False,
    show_route_maintenance_daily: bool = False,
) -> str:
    rendered_rows = []
    for row in rows:
        label = ranking_row_label(
            row,
            hide_fuel=hide_fuel,
            show_daily=show_daily,
            show_route_maintenance_daily=show_route_maintenance_daily,
        ).replace(r"\$", "$")
        detail = ranking_detail_html(
            row,
            hide_fuel=hide_fuel,
            show_daily=show_daily,
            show_route_maintenance_daily=show_route_maintenance_daily,
        )
        rendered_rows.append(
            '<details class="ranking-native-row">'
            f'<summary>{h(label)}</summary>'
            f'<div class="ranking-native-content">{detail}</div>'
            '</details>'
        )
    return f'<div class="ranking-native-table">{"".join(rendered_rows)}</div>'


def _ranking_float(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def ranking_difference_html(
    rows: list[dict],
    *,
    hide_fuel: bool = False,
    show_daily: bool = False,
    show_route_maintenance_daily: bool = False,
) -> str:
    if len(rows) < 2:
        return ""
    metrics = [
        ("Diferença total", "total", fmt_brl_big),
        ("Manutenção", "manutencao", fmt_brl_big),
        ("Pedágio/Extras", "pedagio", fmt_brl_big),
        ("Peso", "peso_total", fmt_peso),
    ]
    if show_route_maintenance_daily:
        metrics[2:2] = [
            ("Manutenção por dia", "manutencao_diaria", fmt_brl_big),
            ("Dias na rota", "dias_na_rota", fmt_num),
        ]
    if show_daily:
        metrics[1:1] = [
            ("Gasto com diárias com freteiro", "gasto_diarias", fmt_brl_big),
            ("Dias trabalhados", "dias_trabalhados", fmt_num),
        ]
    if any(_ranking_float(row, "salario_transporte") > 0 for row in rows):
        metrics[1:1] = [
            ("Salário do Transporte", "salario_transporte", fmt_brl_big),
        ]
    if not hide_fuel:
        metrics[1:1] = [
            ("Combustível", "combustivel", fmt_brl_big),
            ("KM total", "km_total", fmt_num),
            ("Litros", "litros_total", fmt_num),
            ("Custo/KM", "custo_por_km", fmt_brl),
            ("KM/L", "km_por_litro", lambda value: f"{fmt_num(value, 2)} km/L"),
        ]
    items = []
    for label, key, formatter in metrics:
        ordered = sorted(rows, key=lambda row: _ranking_float(row, key), reverse=True)
        high, low = ordered[0], ordered[-1]
        diff = abs(_ranking_float(high, key) - _ranking_float(low, key))
        note = f"{high.get('placa') or 'Sem placa'} acima de {low.get('placa') or 'Sem placa'}"
        items.append(
            f'<div class="ranking-difference-item"><p class="ranking-difference-label">{h(label)}</p>'
            f'<p class="ranking-difference-value">{h(formatter(diff))}</p>'
            f'<p class="ranking-difference-note">{h(note)}</p></div>'
        )
    return (
        '<section class="ranking-difference">'
        '<h3>Diferença entre as placas selecionadas</h3>'
        f'<div class="ranking-difference-grid">{"".join(items)}</div>'
        '</section>'
    )


def ranking_versus_html(
    rows: list[dict],
    *,
    hide_fuel: bool = False,
    show_daily: bool = False,
    show_route_maintenance_daily: bool = False,
) -> str:
    metrics = [
        ("Total", "total", fmt_brl_big),
        ("Manutenção", "manutencao", fmt_brl_big),
        ("Pedágio/Extras", "pedagio", fmt_brl_big),
        ("Peso", "peso_total", fmt_peso),
        ("Valor entregas", "valor_peso", fmt_brl_big),
    ]
    if show_route_maintenance_daily:
        metrics[2:2] = [
            ("Manutenção por dia", "manutencao_diaria", fmt_brl_big),
            ("Dias na rota", "dias_na_rota", fmt_num),
        ]
    if show_daily:
        metrics[1:1] = [
            ("Valor da diária", "diaria", fmt_brl_big),
            ("Dias trabalhados", "dias_trabalhados", fmt_num),
            ("Gasto com diárias com freteiro", "gasto_diarias", fmt_brl_big),
        ]
    if any(_ranking_float(row, "salario_transporte") > 0 for row in rows):
        metrics[1:1] = [
            ("Salário do Transporte", "salario_transporte", fmt_brl_big),
        ]
    if not hide_fuel:
        metrics[1:1] = [
            ("Combustível", "combustivel", fmt_brl_big),
            ("KM total", "km_total", fmt_num),
            ("Litros", "litros_total", fmt_num),
            ("Custo/KM", "custo_por_km", fmt_brl),
            ("KM/L", "km_por_litro", lambda value: f"{fmt_num(value, 2)} km/L"),
        ]
    cards = []
    for row in rows:
        body = "".join(
            f'<div class="ranking-versus-metric"><span>{h(label)}</span><span>{h(formatter(row.get(key)))}</span></div>'
            for label, key, formatter in metrics
        )
        cards.append(f'<article class="ranking-versus-card"><h3>{h(row.get("placa") or "Sem placa")}</h3>{body}</article>')
    return f'<h2 class="ranking-versus-title">Versus entre placas</h2><section class="ranking-versus-grid">{"".join(cards)}</section>'


def selected_plotly_label(event, labels: list[str]) -> str | None:
    try:
        points = event.selection.points
    except AttributeError:
        points = (event or {}).get("selection", {}).get("points", []) if isinstance(event, dict) else []
    if not points:
        return None
    point = points[0]
    label = point.get("label") or point.get("x")
    if label:
        return str(label)
    point_index = point.get("point_index", point.get("pointIndex"))
    try:
        return labels[int(point_index)]
    except (TypeError, ValueError, IndexError):
        return None


def dominance_cities_html(placa: str, cidades: list[dict]) -> str:
    city_rows = [item for item in cidades if str(item.get("placa") or "") == placa]
    city_rows = sorted(city_rows, key=lambda item: float(item.get("peso") or 0), reverse=True)
    if not city_rows:
        return (
            '<div class="dominance-panel">'
            f'<p class="dominance-title">{h(placa)}</p>'
            '<p class="dominance-note">Essa placa aparece no peso total, mas ainda não há cidades dominadas por ela nos dados filtrados.</p>'
            '</div>'
        )

    rows_html = []
    for item in city_rows:
        rows_html.append(
            '<div class="dominance-city-row">'
            f'<span class="dominance-city-name">{h(item.get("cidade") or "Sem cidade")}</span>'
            f'<span class="dominance-city-metric">{h(fmt_peso(item.get("peso")))}</span>'
            f'<span class="dominance-city-metric">{h(fmt_num(item.get("participacao"), 2))}%</span>'
            f'<span class="dominance-city-metric">total {h(fmt_peso(item.get("peso_cidade")))}</span>'
            '</div>'
        )
    return (
        '<div class="dominance-panel">'
        f'<p class="dominance-title">Cidades dominadas por {h(placa)}</p>'
        f'<p class="dominance-note">{len(city_rows)} cidade(s), ordenadas pelo maior peso dominante.</p>'
        f'<div class="dominance-cities">{"".join(rows_html)}</div>'
        '</div>'
    )


def dominance_route_ranking_html(rotas: list[dict]) -> str:
    route_rows = sorted(rotas or [], key=lambda item: float(item.get("peso") or 0), reverse=True)
    if not route_rows:
        return (
            '<div class="dominance-panel dominance-panel--routes">'
            '<p class="dominance-title">Ranking de peso por rota e placa</p>'
            '<p class="dominance-note">Ainda não há rotas com peso para os filtros selecionados.</p>'
            '</div>'
        )

    rows_html = [
        '<div class="dominance-city-row dominance-city-row--head dominance-route-row dominance-route-row--head">'
        '<span class="dominance-city-name">Rota</span>'
        '<span class="dominance-city-plate">Placa</span>'
        '<span class="dominance-city-metric">Peso</span>'
        '<span class="dominance-city-metric">Dominio</span>'
        '<span class="dominance-city-metric">Total rota</span>'
        '</div>'
    ]
    for index, item in enumerate(route_rows, start=1):
        rows_html.append(
            '<div class="dominance-city-row dominance-route-row">'
            f'<span class="dominance-city-name" data-label="Rota">{index:02d} - {h(item.get("rota") or "Sem rota")}</span>'
            f'<span class="dominance-city-plate" data-label="Placa">{h(item.get("placa") or "Sem placa")}</span>'
            f'<span class="dominance-city-metric" data-label="Peso">{h(fmt_peso(item.get("peso")))}</span>'
            f'<span class="dominance-city-metric" data-label="Domínio">{h(fmt_num(item.get("participacao"), 2))}%</span>'
            f'<span class="dominance-city-metric" data-label="Total rota">{h(fmt_peso(item.get("peso_rota")))}</span>'
            '</div>'
        )
    return (
        '<div class="dominance-panel dominance-panel--routes">'
        '<div class="dominance-route-heading">'
        '<div>'
        '<p class="dominance-title">Ranking de peso por rota e placa</p>'
        '<p class="dominance-note">Todas as placas de cada rota aparecem em ordem de peso nos filtros selecionados.</p>'
        '</div>'
        f'<span class="dominance-route-count">{len(route_rows)} resultado(s)</span>'
        '</div>'
        f'<div class="dominance-cities dominance-route-table">{"".join(rows_html)}</div>'
        '</div>'
    )


def peso_bar_chart(labels: list, values: list) -> go.Figure:
    rows = [(str(label), float(value or 0)) for label, value in zip(labels or [], values or [])]
    values_clean = [item[1] for item in rows]
    labels_clean = [item[0] for item in rows]
    text = [fmt_peso(value) for value in values_clean]
    fig = go.Figure(
        go.Bar(
            x=labels_clean,
            y=values_clean,
            marker={"color": JR_BLUE},
            text=text,
            textposition="outside",
            textfont={"size": 11, "color": JR_BLUE},
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        )
    )
    max_value = max(values_clean) if values_clean else 0
    fig.update_xaxes(tickangle=-30, type="category")
    fig.update_yaxes(title="kg", range=[0, max_value * 1.16] if max_value else None, automargin=True)
    return apply_theme(fig, height=370, margin={"l": 60, "r": 48, "t": 58, "b": 70})


def dominance_city_summaries(cidades: list[dict], *, limit: int = 10) -> dict[str, str]:
    grouped: dict[str, list[dict]] = {}
    for item in cidades:
        placa = str(item.get("placa") or "")
        if placa:
            grouped.setdefault(placa, []).append(item)
    summaries = {}
    for placa, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: float(item.get("peso") or 0), reverse=True)
        names = [str(item.get("cidade") or "Sem cidade") for item in ordered[:limit]]
        remaining = max(len(ordered) - len(names), 0)
        suffix = f" +{remaining}" if remaining else ""
        summaries[placa] = ", ".join(names) + suffix
    return summaries


def render_frota() -> None:
    topbar("JR DASHBOARD • Ranking de caminhões", back=False)
    seed = route_json("frota", {"ano": "Todos", "mes": ["Todos"], "ordenar_por": "total"})
    params = frota_filter_controls(seed)
    data = route_json("frota", params)
    totais = data.get("totais", {}) or {}
    selected_categories = [str(item) for item in (params.get("categoria") or []) if item not in (None, "", "Todos")]
    selected_routes = [str(item) for item in (params.get("rota") or []) if item not in (None, "", "Todos")]
    selected_plates = [str(item) for item in (params.get("placa") or []) if item not in (None, "", "Todos")]
    freteiro_mode = selected_categories == ["Freteiro"]
    include_hoteis = bool(totais.get("inclui_hoteis") or params.get("incluir_hoteis"))
    ranking = data.get("ranking", []) or []
    show_daily = (
        freteiro_mode
        or float(totais.get("gasto_diarias") or 0) > 0
        or any(float(row.get("diaria") or 0) > 0 for row in ranking)
    )
    show_route_maintenance_daily = bool(selected_routes)

    if selected_routes:
        weight_label = "Peso total da rota" if len(selected_routes) == 1 else "Peso total das rotas"
    elif selected_plates:
        weight_label = "Peso total da placa" if len(selected_plates) == 1 else "Peso total das placas"
    else:
        weight_label = "Peso total geral"

    delivery_value = _ranking_float(totais, "valor_peso")
    cost_percentage = (
        _ranking_float(totais, "total") / delivery_value * 100
        if delivery_value > 0
        else None
    )
    summary_kpis = [
        ("Placas no ranking", fmt_num(totais.get("placas")), JR_BLUE),
        ("Número de entregas", fmt_num(totais.get("entregas")), JR_BLUE),
        ("Dias de serviço", fmt_num(totais.get("dias_servico")), JR_BLUE),
        ("Custo sobre o ganho das entregas", fmt_percent(cost_percentage), "#D97706"),
        ("Ganho das entregas", fmt_brl_big(totais.get("valor_peso")), "#15803D"),
        (weight_label, fmt_peso(totais.get("peso_total")), JR_BLUE),
    ]
    operation_kpis = []
    if not freteiro_mode:
        operation_kpis = [
            ("Combustível", fmt_brl_big(totais.get("combustivel")), JR_BLUE),
            ("Litros", fmt_num(totais.get("litros_total")), JR_BLUE),
            ("KM total", fmt_num(totais.get("km_total")), JR_BLUE),
            ("Média KM/L", f"{fmt_num(totais.get('km_por_litro'), 2)} km/L", JR_RED),
        ]

    if selected_routes and selected_plates:
        maintenance_total_label = (
            "Manutenção estimada da placa na rota"
            if len(selected_plates) == 1
            else "Manutenção estimada das placas nas rotas"
        )
    elif selected_routes:
        maintenance_total_label = (
            "Manutenção estimada das placas da rota"
            if len(selected_routes) == 1
            else "Manutenção estimada das placas nas rotas"
        )
    else:
        maintenance_total_label = "Manutenção total no período"
    cost_kpis = [
        ("Gasto total", fmt_brl_big(totais.get("total")), JR_RED),
        ("Custo total por KM", fmt_brl(totais.get("custo_por_km")), JR_RED),
        ("Média mensal de gastos", fmt_brl_big(totais.get("media_mensal")), "#0F766E"),
        (maintenance_total_label, fmt_brl_big(totais.get("manutencao")), JR_RED),
        ("Pedágio/Extras", fmt_brl_big(totais.get("pedagio")), "#D97706"),
    ]
    if show_daily:
        cost_kpis.append(
            (
                "Gasto com diárias com freteiro",
                fmt_brl_big(totais.get("gasto_diarias")),
                "#7C3AED",
            )
        )
    if _ranking_float(totais, "salario_transporte") > 0:
        if selected_routes:
            salary_label = (
                "Salário do Transporte rateado na rota"
                if len(selected_routes) == 1
                else "Salário do Transporte rateado nas rotas"
            )
        elif selected_plates:
            salary_label = (
                "Salário do Transporte rateado na placa"
                if len(selected_plates) == 1
                else "Salário do Transporte rateado nas placas"
            )
        else:
            salary_label = "Salário do Transporte no período"
        cost_kpis.append(
            (
                salary_label,
                fmt_brl_big(totais.get("salario_transporte")),
                "#4B5563",
            )
        )
    if include_hoteis:
        hotel_total_label = "Hotéis estimados nas rotas" if selected_routes else "Hotéis total no período"
        hotel_daily_label = (
            "Média diária geral de hotéis"
            if selected_routes
            else "Hotéis/dia"
        )
        cost_kpis.extend(
            [
                (hotel_total_label, fmt_brl_big(totais.get("hoteis")), "#0F766E"),
                (hotel_daily_label, fmt_brl_big(totais.get("hoteis_diaria")), "#0F766E"),
            ]
        )

    kpi_items = [
        *(item + ("Custos do período",) for item in cost_kpis),
        *(item + ("Operação",) for item in operation_kpis),
        *(item + ("Resultado e produção",) for item in summary_kpis),
    ]
    with st.container(key="frota_kpis"):
        render_kpis(kpi_items)

    if selected_routes and not freteiro_mode:
        st.info(
            "Combustível das rotas: os abastecimentos são ligados pela placa e pelo período da viagem. "
            "Quando existe mais de uma rota possível, o sistema compara o local do posto com as cidades "
            "atendidas; sem cidade identificável, usa a rota mais próxima no tempo e informa abaixo.",
            icon="⛽",
        )

    route_km_warnings = data.get("avisos_rodagem_rota", []) or []
    if selected_routes and route_km_warnings:
        st.warning("Revise os dados usados no cálculo das rotas:")
        for warning in route_km_warnings[:8]:
            st.write(f"- {warning}")
        if len(route_km_warnings) > 8:
            st.write(f"...mais {len(route_km_warnings) - 8} aviso(s).")

    if len(selected_routes) >= 2:
        with st.container(key="frota_route_compare"):
            render_frota_route_compare(
                params,
                selected_routes,
                default_include_hotels=include_hoteis,
                hide_fuel=freteiro_mode,
                show_daily=show_daily,
            )

    if not ranking:
        st.markdown('<div class="ranking-empty">Nenhum caminhão encontrado para os filtros selecionados.</div>', unsafe_allow_html=True)
        footer("Ranking calculado com dados de combustível, manutenção, diárias e pedágio/extras do Neon. © JR")
        return

    plate_compare = frota_plate_compare_bundle(params, selected_plates) if len(selected_plates) >= 2 else []
    if len(selected_plates) >= 2:
        selected_set = set(selected_plates)
        versus_rows = [row for row in ranking if row.get("placa") in selected_set]
        st.html(
            ranking_difference_html(
                versus_rows,
                hide_fuel=freteiro_mode,
                show_daily=show_daily,
                show_route_maintenance_daily=show_route_maintenance_daily,
            )
            + ranking_versus_html(
                versus_rows,
                hide_fuel=freteiro_mode,
                show_daily=show_daily,
                show_route_maintenance_daily=show_route_maintenance_daily,
            )
        )

    show_monthly_gain = st.toggle(
        "Comparar gasto com ganho das entregas por mês",
        value=False,
        key="rank_compare_monthly_gain",
        help="Exibe gasto total e ganho das entregas lado a lado no primeiro gráfico.",
    )
    include_year = params.get("ano") is None
    fallback_year = params.get("ano")
    total_labels, total_values = sorted_series(
        data.get("mensal_total", {}),
        "Mes",
        "Valor",
        include_year=include_year,
        fallback_year=fallback_year,
    )
    peso_labels, peso_values = sorted_series(
        data.get("peso_mensal", {}),
        "Mes",
        "Peso",
        include_year=include_year,
        fallback_year=fallback_year,
    )
    km_labels, km_values = sorted_series(
        data.get("km_mensal", {}),
        "Mes",
        "Km Rodados",
        include_year=include_year,
        fallback_year=fallback_year,
    )
    litros_labels, litros_values = sorted_series(
        data.get("litros_mensal", {}),
        "Mes",
        "Litros",
        include_year=include_year,
        fallback_year=fallback_year,
    )
    if plate_compare:
        total_monthly_fig = multi_line_chart(
            frota_plate_monthly_series(plate_compare, "mensal_total", "Valor"),
            include_year=include_year,
            fallback_year=fallback_year,
        )
        km_monthly_fig = multi_bar_chart(
            frota_plate_monthly_series(plate_compare, "km_mensal", "Km Rodados"),
            currency=False,
            label_mode="month",
            fallback_year=fallback_year,
        )
        litros_monthly_fig = multi_bar_chart(
            frota_plate_monthly_series(plate_compare, "litros_mensal", "Litros"),
            currency=False,
            label_mode="month",
            fallback_year=fallback_year,
        )
        peso_monthly_fig = multi_bar_chart(
            frota_plate_monthly_series(plate_compare, "peso_mensal", "Peso"),
            currency=False,
            label_mode="month",
            fallback_year=fallback_year,
        )
    else:
        total_monthly_fig = (
            yearly_month_line_chart(data.get("mensal_total", {}), "Mes", "Valor", fallback_year=fallback_year)
            if include_year
            else line_chart(total_labels, total_values)
        )
        peso_monthly_fig = (
            yearly_month_bar_chart(data.get("peso_mensal", {}), "Mes", "Peso", fallback_year=fallback_year, currency=False)
            if include_year
            else peso_bar_chart(peso_labels, peso_values)
        )
        km_monthly_fig = (
            yearly_month_bar_chart(data.get("km_mensal", {}), "Mes", "Km Rodados", fallback_year=fallback_year, currency=False)
            if include_year
            else bar_chart(km_labels, km_values, currency=False, show_text=True)
        )
        litros_monthly_fig = (
            yearly_month_bar_chart(data.get("litros_mensal", {}), "Mes", "Litros", fallback_year=fallback_year, currency=False)
            if include_year
            else bar_chart(litros_labels, litros_values, currency=False, show_text=True)
        )
    total_monthly_title = "Gasto total por mês"
    if show_monthly_gain:
        monthly_cost = data.get("mensal_total", {}) or {}
        monthly_gain = data.get("ganho_mensal", {}) or {}
        total_monthly_fig = monthly_cost_gain_line_chart(
            monthly_cost,
            monthly_gain,
            include_year=include_year,
            fallback_year=fallback_year,
        )
        total_monthly_title = "Gasto e ganho das entregas por mês"
    chart_items = [
        (total_monthly_title, total_monthly_fig),
        ("Peso por mês", peso_monthly_fig),
    ]
    if not freteiro_mode:
        chart_items[1:1] = [
            ("KM por mês", km_monthly_fig),
            ("Litros por mês", litros_monthly_fig),
        ]
    chart_grid(chart_items, key_prefix="rank_chart")

    dominancia = data.get("dominancia_peso", {}) or {}
    rotas_dominadas = dominancia.get("rotas", []) or []
    if rotas_dominadas:
        st.html(dominance_route_ranking_html(rotas_dominadas))

    with st.container(key="frota_ranking_table"):
        st.html(
            ranking_native_table_html(
                ranking,
                hide_fuel=freteiro_mode,
                show_daily=show_daily,
                show_route_maintenance_daily=show_route_maintenance_daily,
            )
        )
    footer("Ranking calculado com dados de combustível, manutenção, diárias e pedágio/extras do Neon. © JR")


def render_calculadora_frete() -> None:
    topbar("JR DASHBOARD • Calculadora de frete", back=True)
    with st.container(key="frete_shell"):
        st.html(
            """
            <section class="frete-intro">
              <h2>Quanto cobrar pelo frete?</h2>
              <p>Use a média da frota ou escolha um caminhão específico. O tempo da viagem considera velocidade média de 80 km/h, a descarga considera a produtividade média de 350 kg por hora e o hotel da dupla conta uma diária a cada 10 horas completas de operação.</p>
            </section>
            """
        )

        mode_cols = st.columns(2)
        with mode_cols[0]:
            st.html(
                '<div class="frete-mode-active">Base histórica do dashboard <span>Ativa</span></div>'
            )
        with mode_cols[1], st.container(key="frete_mode_disabled"):
            st.button(
                "Outra modalidade — em breve",
                disabled=True,
                width="stretch",
                key="frete_other_mode",
                help="Esta modalidade permanece desativada.",
            )

        include_hotels = st.checkbox(
            "Incluir hotéis no cálculo",
            value=True,
            key="frete_include_hotels",
            help="Inclui uma diária média de quarto duplo a cada 10 horas completas de viagem + descarga. O valor já cobre motorista e ajudante.",
        )

        historical = route_json(
            "frota",
            {
                "categoria": ["Transporte", "Freteiro"],
                "incluir_hoteis": include_hotels,
                "incluir_salario": True,
                "ordenar_por": "total",
            },
        )
        totals = historical.get("totais") or {}
        general_reference = _freight_reference(totals)
        ranking = historical.get("ranking") or []
        rows_by_plate = {
            str(row.get("placa") or "").strip(): row
            for row in ranking
            if str(row.get("placa") or "").strip()
        }
        plate_options = [FREIGHT_FLEET_AVERAGE_LABEL, *sorted(rows_by_plate)]

        with st.container(key="frete_form"):
            st.markdown("### Dados do frete")
            vehicle_choice = st.selectbox(
                "Base de cálculo do caminhão",
                plate_options,
                index=0,
                key="frete_plate",
                help="Use a média da frota ou escolha uma placa para aplicar o histórico específico do caminhão.",
            ) or FREIGHT_FLEET_AVERAGE_LABEL
            selected_plate = (
                None
                if vehicle_choice == FREIGHT_FLEET_AVERAGE_LABEL
                else vehicle_choice
            )
            st.caption(
                "Na distância, informe ida + volta. O salário por hora vem do histórico, "
                "mas pode ser ajustado para esta simulação."
            )

            selected_row = rows_by_plate.get(str(selected_plate or ""), {})
            plate_reference = _freight_plate_reference(selected_row, general_reference)
            default_hourly_rate = float(plate_reference["rate_per_employee_hour"] or 0.0)
            if default_hourly_rate <= 0:
                st.warning(
                    "A base escolhida não possui salário histórico calculável. "
                    "Informe abaixo o salário por funcionário/hora para incluir o peso no custo."
                )
            input_cols = st.columns(3)
            with input_cols[0]:
                weight_kg = st.number_input(
                    "Peso da carga (kg)",
                    min_value=0.0,
                    value=1000.0,
                    step=100.0,
                    format="%.2f",
                    key="frete_weight_kg",
                )
                employees = st.number_input(
                    "Funcionários na descarga",
                    min_value=1,
                    max_value=20,
                    value=2,
                    step=1,
                    key="frete_employees",
                )
            with input_cols[1]:
                distance_km = st.number_input(
                    "Distância total (km)",
                    min_value=0.0,
                    value=100.0,
                    step=10.0,
                    format="%.1f",
                    key="frete_distance_km",
                )
                employee_hourly_rate = st.number_input(
                    "Salário por funcionário/hora (R$)",
                    min_value=0.0,
                    value=default_hourly_rate,
                    step=1.0,
                    format="%.2f",
                    key=f"frete_hourly_rate_{selected_plate or 'sem_placa'}",
                    help="Média calculada pelos salários do Transporte, considerando jornada de 8 horas.",
                )
            with input_cols[2]:
                margin_percent = st.number_input(
                    "Margem de segurança (%)",
                    min_value=0.0,
                    max_value=100.0,
                    value=10.0,
                    step=1.0,
                    format="%.1f",
                    key="frete_margin_percent",
                    help="Percentual aplicado sobre o custo estimado da operação.",
                )
                st.write("")
                st.button(
                    "Atualizar cálculo",
                    type="primary",
                    width="stretch",
                    key="frete_refresh",
                )
            st.caption("O resultado usa sempre os valores atuais. Confirme a digitação com Enter ou saia do campo.")

        st.session_state.pop("frete_quote_inputs_v2", None)
        result_plate = selected_plate or FREIGHT_FLEET_AVERAGE_LABEL
        quote_inputs = {
            "weight_kg": float(weight_kg),
            "distance_km": float(distance_km),
            "employees": int(employees),
            "employee_hourly_rate": float(employee_hourly_rate),
            "margin_percent": float(margin_percent),
            "include_hotels": bool(include_hotels),
        }
        quote = _calculate_freight_quote(plate_reference, **quote_inputs)
        st.html(
            f"""
            <section class="frete-result-hero">
              <div class="frete-result-grid">
                <div class="frete-result-item">
                  <p class="frete-result-label">Frete sugerido</p>
                  <p class="frete-result-value">{h(fmt_brl(quote['suggested_freight'], compact_threshold=float('inf')))}</p>
                  <p class="frete-result-note">Base: {h(result_plate)} · hotéis {"incluídos" if include_hotels else "excluídos"} · margem de {h(fmt_num(quote_inputs['margin_percent'], 1))}% incluída.</p>
                </div>
                <div class="frete-result-item frete-result-item--cost">
                  <p class="frete-result-label">Custo estimado</p>
                  <p class="frete-result-value frete-result-value--cost">{h(fmt_brl(quote['estimated_cost'], compact_threshold=float('inf')))}</p>
                  <p class="frete-result-note">Caminhão + equipe + hotel por {h(fmt_num(quote['total_operation_hours'], 2))} h, sem margem.</p>
                </div>
              </div>
            </section>
            <section class="frete-breakdown">
              <div class="frete-breakdown-card"><p>Custo do caminhão na distância</p><strong>{h(fmt_brl(quote['distance_component'], compact_threshold=float('inf')))}</strong></div>
              <div class="frete-breakdown-card"><p>Custo da equipe</p><strong>{h(fmt_brl(quote['team_cost'], compact_threshold=float('inf')))}</strong></div>
              <div class="frete-breakdown-card"><p>Hotel da dupla — {h(fmt_num(quote['hotel_days']))} diária(s)</p><strong>{h(fmt_brl(quote['hotel_cost'], compact_threshold=float('inf')))}</strong></div>
              <div class="frete-breakdown-card"><p>Tempo de viagem a 80 km/h</p><strong>{h(fmt_num(quote['travel_hours'], 2))} h</strong></div>
              <div class="frete-breakdown-card"><p>Tempo de descarga a 350 kg/h</p><strong>{h(fmt_num(quote['unload_hours'], 2))} h</strong></div>
            </section>
            <div class="frete-memory">
              <strong>Memória do cálculo:</strong> viagem: {h(fmt_num(quote_inputs['distance_km'], 1))} km ÷ 80 km/h = {h(fmt_num(quote['travel_hours'], 2))} h. Descarga: {h(fmt_num(quote_inputs['weight_kg'], 2))} kg ÷ 350 kg/h = {h(fmt_num(quote['unload_hours'], 2))} h. Tempo total: {h(fmt_num(quote['total_operation_hours'], 2))} h. Com {h(fmt_num(quote_inputs['employees']))} funcionário(s), são {h(fmt_num(quote['employee_hours'], 2))} horas-pessoa × {h(fmt_brl(quote_inputs['employee_hourly_rate'], compact_threshold=float('inf')))} = {h(fmt_brl(quote['team_cost'], compact_threshold=float('inf')))} de equipe. Hotel da dupla: {h(fmt_num(quote['hotel_days']))} diária(s) completa(s) de 10 h × {h(fmt_brl(quote['hotel_daily_rate'], compact_threshold=float('inf')))} = {h(fmt_brl(quote['hotel_cost'], compact_threshold=float('inf')))}. A diária já cobre motorista e ajudante, sem multiplicar pelo número de funcionários. Somando {h(fmt_brl(quote['distance_component'], compact_threshold=float('inf')))} do caminhão + equipe + hotel, o custo estimado é {h(fmt_brl(quote['estimated_cost'], compact_threshold=float('inf')))}; a margem acrescenta {h(fmt_brl(quote['margin_value'], compact_threshold=float('inf')))}.
            </div>
            """
        )

        years = historical.get("anos") or []
        period_label = (
            f"{min(years)} a {max(years)}"
            if len(years) > 1
            else str(years[0])
            if years
            else "histórico disponível"
        )
        with st.expander("Ver tarifas e dados usados", expanded=False):
            rate_cols = st.columns(4)
            rate_cols[0].metric(
                "Base selecionada",
                vehicle_choice,
            )
            rate_cols[1].metric(
                "Custo direto por km",
                fmt_brl(plate_reference["direct_rate_per_km"], compact_threshold=float("inf")),
            )
            rate_cols[2].metric(
                "Diária média da dupla",
                fmt_brl(plate_reference["hotel_daily_rate"], compact_threshold=float("inf")),
            )
            rate_cols[3].metric(
                "Funcionário por hora",
                fmt_brl(plate_reference["rate_per_employee_hour"], compact_threshold=float("inf")),
            )
            hotel_explanation = (
                f"O tempo total de {fmt_num(quote['total_operation_hours'], 2)} h contém "
                f"{fmt_num(quote['hotel_days'])} bloco(s) completo(s) de 10 h. Portanto, são "
                f"{fmt_num(quote['hotel_days'])} diária(s) × "
                f"{fmt_brl(quote['hotel_daily_rate'], compact_threshold=float('inf'))} = "
                f"{fmt_brl(quote['hotel_cost'], compact_threshold=float('inf'))} de hotel para a dupla."
                if include_hotels
                else "Os hotéis estão desmarcados e, por isso, não acrescentam nenhum valor ao custo estimado."
            )
            st.info(
                f"**Como o hotel foi calculado:** {hotel_explanation} "
                "Menos de 10 h não gera diária; de 10 h até menos de 20 h gera 1 diária; "
                "de 20 h até menos de 30 h gera 2 diárias, e assim por diante. "
                "Cada diária corresponde a um quarto duplo para motorista + ajudante; o valor não é multiplicado pela equipe. "
                "O hotel é somado separadamente e não altera o custo por km da placa."
            )
            st.markdown(
                "**Custos separados:** o custo do caminhão é a distância × o custo direto por km. "
                "A equipe usa o tempo de viagem + descarga × funcionários × salário/hora. "
                "O hotel usa os blocos completos de 10 horas × a média histórica por reserva da dupla."
            )
            st.caption(
                f"Base: {period_label}. O custo por km usa {plate_reference['km_rate_source']} e reúne combustível, "
                f"manutenção, pedágio/extras e diárias de freteiros. Hotéis {('incluídos por tempo' if include_hotels else 'excluídos')}; "
                f"histórico de hospedagens: {fmt_brl(general_reference['hotel_cost'])} em {fmt_num(general_reference['hotel_reservations'])} reservas da dupla. "
                f"A tarifa por hora usa {plate_reference['hourly_rate_source']}, jornada de 8 horas e equipe histórica "
                "de motorista + ajudante. Velocidade média: 80 km/h. Produtividade média da descarga: 350 kg por hora."
            )

    footer("Estimativa calculada com o histórico operacional do Neon. Confira pedágios e condições especiais antes de fechar. © JR")


def render_home() -> None:
    logo = logo_data_uri()
    last_update = h(last_update_label(APP_VERSION))
    st.markdown('<main class="home-wrapper">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <header class="home-header">
          <div class="home-header-actions">
            <p class="home-last-update">&Uacute;ltima atualiza&ccedil;&atilde;o: {last_update}</p>
            <a class="home-alert-link" href="?page=alertas" target="_self">&#9888; Alertas</a>
            <a class="home-admin-link" href="?page=cadastro" target="_self">Adicionar dados</a>
          </div>
          <div class="home-brand">
            <img src="{logo}" alt="JR" class="home-logo">
            <div>
              <p class="home-eyebrow">JR Ferragens &amp; Madeiras</p>
              <div class="home-title-row">
                <h1>Dashboards operacionais</h1>
                <a class="home-freight-link" href="?page=calculadora-frete" target="_self">Calculadora de frete</a>
              </div>
              <p class="home-subtitle">Monitore velocidade, combustível, manutenção, hospedagens e despesas de pedágio/extras em tempo real, com dados centralizados no Neon.</p>
            </div>
          </div>
          <a class="home-cta" href="#dashboards">Explorar dashboards</a>
        </header>
        """,
        unsafe_allow_html=True,
    )

    overview_options_all = route_json("overview_options")
    year_options = ["Todos", *(overview_options_all.get("anos_disponiveis", []) or [])]
    default_year = last_closed_year_default(overview_options_all.get("anos_disponiveis", []) or [])
    ano_state = st.session_state.get("home_ano", default_year)
    ano = ano_state if ano_state in year_options else default_year
    months_seed = overview_options_all
    if ano != "Todos":
        months_seed = {
            "meses_disponiveis": (
                overview_options_all.get("meses_por_ano", {}).get(str(ano), [])
            )
        }
    month_options = ["Todos", *(months_seed.get("meses_disponiveis", []) or [])]
    home_mes_exists = "home_mes" in st.session_state
    home_mes_previous_key = "home_mes__previous"
    current_months = (
        st.session_state.get("home_mes", ["Todos"])
        if home_mes_exists
        else default_closed_month_selection(month_options, ano)
    )
    current_months = [item for item in current_months if item in month_options] or ["Todos"]
    if home_mes_exists and st.session_state.get("home_mes") != current_months:
        st.session_state["home_mes"] = current_months
        st.session_state[home_mes_previous_key] = current_months
    if home_mes_previous_key not in st.session_state:
        st.session_state[home_mes_previous_key] = current_months
    meses = normalize_multiselect(current_months, st.session_state.get(home_mes_previous_key, ["Todos"]))

    overview_params: dict[str, object] = {}
    if ano != "Todos":
        overview_params["ano"] = ano
    if meses != ["Todos"]:
        overview_months = [f"{int(ano)}-{int(item):02d}" for item in meses] if ano != "Todos" else [int(item) for item in meses]
        overview_params["mes"] = overview_months
    overview = route_json("overview", overview_params)
    filter_text = ""
    if ano != "Todos":
        filter_text = f"Filtro aplicado: {ano}."
    if meses != ["Todos"]:
        month_text = ", ".join(MONTH_NAMES[int(item) - 1] for item in meses)
        filter_text = f"Filtro aplicado: {month_text}/{ano}." if ano != "Todos" else f"Filtro aplicado: {month_text}."
    suffix = filter_text or "Cálculo baseado nos dados mais recentes do banco."
    home_total_cards = [
        ("Gasto consolidado", fmt_brl(overview.get("total_geral")), suffix),
        ("Peso total", fmt_peso(overview.get("peso_total")), "Somatório dos pesos lançados nas entregas."),
        ("KM rodado", fmt_num(overview.get("km_total")), "Somatório dos quilômetros rodados no filtro aplicado."),
        (
            "Gasto transporte",
            fmt_brl(overview.get("total_transporte")),
            "Despesas do Transporte, salários e diárias de freteiros.",
        ),
        ("Gasto Vex", fmt_brl(overview.get("total_vex")), 'Somatório das despesas marcadas como "Vex".'),
    ]

    home_total_cards = [
        home_total_cards[0],
        home_total_cards[1],
        ("KM total", fmt_num(overview.get("km_total")), "km rodados"),
        ("Transporte", fmt_num(overview.get("km_transporte")), "km"),
        ("Vex", fmt_num(overview.get("km_vex")), "km"),
        *home_total_cards[3:],
    ]

    with st.container(key="home_total_section"):
        ready_key = "home_export_ready"
        ready_file = st.session_state.get(ready_key)
        if ready_file and ready_file.get("version") != APP_VERSION:
            st.session_state.pop(ready_key, None)

        export_cols = st.columns(2)
        export_options = [
            ("cards", "Exportar cards (PNG)", False),
            ("pagina", "Exportar página (PNG)", True),
        ]
        for col, (scope, label, include_header) in zip(export_cols, export_options):
            with col:
                if st.button(label, key=f"home_export_{scope}_png", width="stretch"):
                    image = compose_home_export_image(home_total_cards, include_header=include_header)
                    st.session_state[ready_key] = {
                        "data": image_to_png_bytes(image),
                        "file_name": export_file_name("home", scope, "png"),
                        "mime": "image/png",
                        "version": APP_VERSION,
                    }
        ready_file = st.session_state.get(ready_key)
        if ready_file:
            st.download_button(
                "Baixar arquivo gerado",
                data=ready_file["data"],
                file_name=ready_file["file_name"],
                mime=ready_file["mime"],
                key="home_download_ready",
                width="stretch",
            )

        render_home_totals(home_total_cards)
        st.markdown('<div class="home-filter-row"></div>', unsafe_allow_html=True)
        cols = st.columns([0.55, 1.35, 1.4])
        with cols[0]:
            st.selectbox("Ano", year_options, index=year_options.index(ano), key="home_ano")
        with cols[1]:
            home_mes_kwargs = {
                "format_func": compact_month_label,
                "key": "home_mes",
                "on_change": sync_multiselect_selection,
                "args": ("home_mes",),
            }
            if not home_mes_exists:
                home_mes_kwargs["default"] = current_months
            st.multiselect("Mês", month_options, **home_mes_kwargs)
        with cols[2]:
            st.write("")
            st.write("")
            if st.button("Limpar filtro", key="home_clear", width="stretch"):
                for key in ("home_ano", "home_mes", "home_mes__previous"):
                    st.session_state.pop(key, None)
                st.rerun()

    st.markdown(
        """
        <section id="dashboards" class="home-grid">
          <a class="home-card" href="?page=rotas" target="_self" aria-label="Abrir dashboard Rotas">
            <div><span class="home-chip">Rotas</span><h2>Manifestos, entregas e motoristas</h2></div>
            <p class="home-card-text">Pesquise todos os dados extraídos dos PDFs e acompanhe cada rota por placa, motorista e dia.</p>
            <ul class="home-list"><li>Ranking de motoristas, placas, rotas e cidades</li><li>Saída, retorno, duração e KM realizados</li><li>Clientes, pedidos, endereços, peso e valores das entregas</li></ul>
            <span class="home-link">Abrir dashboard &rarr;</span>
          </a>
          <a class="home-card" href="?page=frota" target="_self" aria-label="Abrir dashboard Ranking">
            <div><span class="home-chip">Ranking</span><h2>Ranking de gastos por caminhão</h2></div>
            <p class="home-card-text">Veja todos os caminhões em formato de tabela, do maior para o menor gasto, com detalhamento por placa.</p>
            <ul class="home-list"><li>Ordenação por combustível, manutenção, pedágio/extras ou total</li><li>Métricas individuais dentro da própria linha</li><li>Filtros por ano, mês e categoria</li></ul>
            <span class="home-link">Abrir dashboard &rarr;</span>
          </a>
          <a class="home-card" href="?page=combustivel" target="_self" aria-label="Abrir dashboard Combustível">
            <div><span class="home-chip">Combustível</span><h2>Consumo, custo e eficiência da frota</h2></div>
            <p class="home-card-text">Filtros por mês, placa, posto e tipo de combustível com KPIs e gráficos de desempenho.</p>
            <ul class="home-list"><li>KPIs automáticos de custo, km e litros</li><li>Comparativo por posto e tipo de combustível</li><li>Histórico mensal de consumo e gastos</li></ul>
            <span class="home-link">Abrir dashboard &rarr;</span>
          </a>
          <a class="home-card" href="?page=manutencao" target="_self" aria-label="Abrir dashboard Manutenção">
            <div><span class="home-chip">Manutenção</span><h2>Gestão de oficinas e serviços</h2></div>
            <p class="home-card-text">Acompanhe gastos por placa, oficina e mês, com ticket médio atualizado.</p>
            <ul class="home-list"><li>Resumo financeiro com ticket médio</li><li>Distribuição por placa e oficina</li><li>Curva mensal de investimentos</li></ul>
            <span class="home-link">Abrir dashboard &rarr;</span>
          </a>
          <a class="home-card" href="?page=hoteis" target="_self" aria-label="Abrir dashboard Hotéis">
            <div><span class="home-chip">Hotéis</span><h2>Reservas e hospedagens da equipe</h2></div>
            <p class="home-card-text">Filtros por mês, cidade e hotel para entender os investimentos em hospedagem.</p>
            <ul class="home-list"><li>KPIs automáticos de valor total, reservas e médias</li><li>Ranking por cidade e hotel/pousada</li><li>Histórico mensal dos gastos com hospedagem</li></ul>
            <span class="home-link">Abrir dashboard &rarr;</span>
          </a>
          <a class="home-card" href="?page=pedagio" target="_self" aria-label="Abrir dashboard Pedágio e Extras">
            <div><span class="home-chip">Pedágio &amp; Extras</span><h2>Pedágio e custos extras da frota</h2></div>
            <p class="home-card-text">Acompanhe quanto cada placa consome com pedágio, seguros e tributos, com KPIs dinâmicos.</p>
            <ul class="home-list"><li>Resumo mensal consolidado por tipo de despesa</li><li>Comparativo por placa e categoria</li><li>Filtros rápidos por mês, placa e tipo</li></ul>
            <span class="home-link">Abrir dashboard &rarr;</span>
          </a>
          <a class="home-card" href="?page=vex" target="_self" aria-label="Abrir dashboard Vex">
            <div><span class="home-chip">Vex</span><h2>Gastos exclusivos da categoria Vex</h2></div>
            <p class="home-card-text">Visão consolidada dos custos Vex, com filtros por ano e mês.</p>
            <ul class="home-list"><li>Totais Vex por área</li><li>Evolução mensal dos gastos</li><li>Resumo centralizado da categoria</li></ul>
            <span class="home-link">Abrir dashboard &rarr;</span>
          </a>
        </section>
        </main>
        """,
        unsafe_allow_html=True,
    )


def _entry_month(value: date) -> str:
    return f"{value.year}-{value.month:02d}"


def _aluguel_cycle_dates(inicio: date, fim: date) -> list[date]:
    """Retorna uma data representativa de cada mês incluído na locação."""
    if not inicio or not fim or fim < inicio:
        return []
    months = pd.period_range(start=inicio, end=fim, freq="M")
    return [max(inicio, month.start_time.date()) for month in months]


def _aluguel_one_cycle_end(inicio: date) -> date:
    month_index = inicio.month
    year = inicio.year + month_index // 12
    month = month_index % 12 + 1
    day = min(inicio.day, calendar.monthrange(year, month)[1])
    return date(year, month, day) - timedelta(days=1)


def _aluguel_period_rows(
    inicio: date,
    fim: date,
    placa: str,
    fornecedor: str,
    valor_mensal: float,
    observacao: str,
) -> list[dict]:
    cycle_dates = _aluguel_cycle_dates(inicio, fim)
    return [
        {
            "Data": cycle_date,
            "Mes": _entry_month(cycle_date),
            "Inicio": inicio,
            "Fim": fim,
            "PLACA": placa,
            "Fornecedor": fornecedor,
            "Custo": valor_mensal,
            "Observacao": observacao,
            "Categoria": "Vex",
        }
        for cycle_date in cycle_dates
    ]


def _entry_required_missing(row: dict, fields: list[str]) -> list[str]:
    missing = []
    for field in fields:
        value = row.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing


def _entry_field_label(field: str) -> str:
    labels = {
        "PLACA": "Placa",
        "OFICINA": "Oficina",
        "POSTOS": "Posto",
        "Combustivel": "Combustível",
        "Data": "Data",
        "Custo": "Custo",
        "Tipo": "Tipo",
    }
    return labels.get(field, field)


def _save_entry(
    dataset: str,
    row: dict,
    *,
    required: list[str],
    success: str,
    replace_keys: list[str] | None = None,
    reset_table_key: str | None = None,
) -> bool:
    missing = _entry_required_missing(row, required)
    if missing:
        st.warning("Preencha os campos obrigatórios: " + ", ".join(_entry_field_label(field) for field in missing))
        return False
    try:
        backend.save_dashboard_record(dataset, row, replace_keys=replace_keys)
    except Exception as exc:
        st.error("Não foi possível salvar no Neon.")
        st.exception(exc)
        return False
    clear_cached_reads()
    if reset_table_key:
        _clear_table_filter_state(reset_table_key)
        _reset_dataset_editor(reset_table_key)
    st.success(success)
    return True


def _registered_plate_map() -> dict[str, str]:
    try:
        df = backend.load_placas()
    except Exception:
        return {}
    if df.empty or "PLACA" not in df.columns:
        return {}
    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        placa = clean_text(row.get("PLACA")).strip().upper()
        categoria = clean_text(row.get("Categoria") or "Transporte").strip()
        if placa:
            normalized = categoria.lower()
            if "ESTOQUE" in placa:
                mapping[placa] = "Estoque"
            elif "EMPILHADEIRA" in placa:
                mapping[placa] = "Empilhadeira"
            elif normalized == "empilhadeira":
                mapping[placa] = "Empilhadeira"
            elif normalized == "estoque":
                mapping[placa] = "Estoque"
            elif normalized == "vex":
                mapping[placa] = "Vex"
            elif "fret" in normalized:
                mapping[placa] = "Freteiro"
            elif normalized == "equipamento":
                mapping[placa] = "Equipamento"
            else:
                mapping[placa] = "Transporte"
    return dict(sorted(mapping.items()))


def _registered_plate_daily_map() -> dict[str, float]:
    try:
        df = backend.load_placas()
    except Exception:
        return {}
    if df.empty or "PLACA" not in df.columns or "Diaria" not in df.columns:
        return {}
    rates: dict[str, float] = {}
    for _, row in df.iterrows():
        placa = clean_text(row.get("PLACA")).strip().upper()
        diaria = _parse_brl_number(row.get("Diaria")) or 0.0
        if placa:
            rates[placa] = max(float(diaria), 0.0)
    return dict(sorted(rates.items()))


def _plate_editor_token(plate_map: dict[str, str], daily_map: dict[str, float] | None = None) -> str:
    daily_map = daily_map or {}
    raw = "|".join(
        f"{placa}:{categoria}:{daily_map.get(placa, 0.0):.2f}"
        for placa, categoria in sorted(plate_map.items())
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _reset_plate_editor() -> None:
    st.session_state["cad_placas_editor_nonce"] = st.session_state.get("cad_placas_editor_nonce", 0) + 1


def _clear_stale_plate_editor_state(active_key: str) -> None:
    for key in list(st.session_state.keys()):
        if key == "cad_placas_editor" or (key.startswith("cad_placas_editor_") and key != active_key):
            del st.session_state[key]


def _filter_plate_table(table: pd.DataFrame, editor_token: str) -> pd.DataFrame:
    with st.expander("Filtros da tabela", expanded=True):
        search = st.text_input(
            "Buscar",
            key=f"cad_placas_search_{editor_token}",
            placeholder="Digite para buscar placa ou categoria",
        )
    if not search.strip():
        return table
    needle = search.strip().lower()
    search_columns = [column for column in ["Placa atual", "Placa", "Categoria", "Diaria (R$)"] if column in table.columns]
    searchable = table[search_columns].astype("string").fillna("").apply(lambda col: col.str.lower())
    mask = searchable.apply(lambda row: any(needle in value for value in row), axis=1)
    return table.loc[mask].copy()


def _registered_text_options(loader, column: str) -> list[str]:
    try:
        df = loader()
    except Exception:
        return []
    if df.empty or column not in df.columns:
        return []
    options = []
    for value in df[column].dropna().tolist():
        text = clean_text(value).strip()
        if text:
            options.append(text)
    return sorted(set(options))


def _select_or_create_text(
    label: str,
    options: list[str],
    prefix: str,
    create_label: str,
    manual_label: str,
    *,
    placeholder: str = "",
    preferred: str | None = None,
) -> str:
    clean_options = [option for option in options if option]
    if not clean_options:
        return st.text_input(label, placeholder=placeholder, key=f"{prefix}_manual_only")
    select_options = [*clean_options, create_label]
    selected_index = 0
    if preferred:
        preferred_norm = clean_text(preferred).strip().lower()
        selected_index = next(
            (idx for idx, option in enumerate(select_options) if clean_text(option).strip().lower() == preferred_norm),
            0,
        )
        state_key = f"{prefix}_select"
        init_key = f"{prefix}_preferred_initialized"
        if not st.session_state.get(init_key):
            st.session_state[state_key] = select_options[selected_index]
            st.session_state[init_key] = True
    selected = st.selectbox(label, select_options, index=selected_index, key=f"{prefix}_select")
    if selected == create_label:
        return st.text_input(manual_label, placeholder=placeholder, key=f"{prefix}_manual")
    return selected


def _plate_fields(prefix: str, plate_map: dict[str, str] | None = None) -> tuple[str, str]:
    plate_map = plate_map if plate_map is not None else _registered_plate_map()
    options = [*plate_map.keys(), "Cadastrar nova placa"]
    selected = st.selectbox(
        "Placa",
        options,
        index=None,
        placeholder="Selecione uma placa",
        key=f"{prefix}_placa_select",
    )
    if selected == "Cadastrar nova placa":
        placa = st.text_input("Nova placa", placeholder="ABC1D23", key=f"{prefix}_placa_manual").upper()
        categoria_key = f"{prefix}_categoria_manual"
        plate_text = clean_text(placa).upper()
        default_categoria = "Estoque" if "ESTOQUE" in plate_text else ("Empilhadeira" if "EMPILHADEIRA" in plate_text else "Transporte")
        if default_categoria in {"Empilhadeira", "Estoque"} and st.session_state.get(categoria_key, "Transporte") == "Transporte":
            st.session_state[categoria_key] = default_categoria
        categoria = st.selectbox("Categoria da placa", CATEGORY_OPTIONS, index=CATEGORY_OPTIONS.index(default_categoria), key=categoria_key)
        return placa, categoria
    if selected is None:
        st.text_input("Categoria da placa", value="", disabled=True, key=f"{prefix}_categoria_empty")
        return "", "Transporte"
    categoria = plate_map.get(selected, "Transporte")
    st.text_input("Categoria da placa", value=categoria, disabled=True, key=f"{prefix}_categoria_locked")
    return selected, categoria


def _save_registered_plate(placa: str, categoria: str) -> bool:
    if not placa:
        st.warning("Selecione ou cadastre uma placa.")
        return False
    try:
        diaria = _registered_plate_daily_map().get(clean_text(placa).strip().upper(), 0.0)
        backend.save_dashboard_record(
            "placas",
            {"PLACA": placa, "Categoria": categoria, "Diaria": diaria},
            replace_keys=["PLACA"],
        )
    except Exception as exc:
        st.error("Não foi possível salvar a placa no Neon.")
        st.exception(exc)
        return False
    clear_cached_reads()
    return True


def _save_text_registry(dataset: str, column: str, value: str, success: str) -> bool:
    text = clean_text(value).strip()
    if not text:
        st.warning("Informe um valor para cadastrar.")
        return False
    try:
        backend.save_dashboard_record(dataset, {column: text}, replace_keys=[column])
    except Exception as exc:
        st.error("Não foi possível salvar no Neon.")
        st.exception(exc)
        return False
    clear_cached_reads()
    st.success(success)
    return True


def _edit_registered_plate(old_plate: str, new_plate: str, categoria: str) -> bool:
    if not old_plate or not new_plate:
        st.warning("Selecione a placa e informe o nome correto.")
        return False
    try:
        backend.rename_plate(old_plate, new_plate, categoria)
    except Exception as exc:
        st.error("Não foi possível editar a placa no Neon.")
        st.exception(exc)
        return False
    clear_cached_reads()
    st.success("Placa atualizada nos cadastros e lançamentos.")
    return True


def _save_plate_sheet(
    original_map: dict[str, str],
    edited: pd.DataFrame,
    original_daily_map: dict[str, float] | None = None,
) -> bool:
    if edited is None or edited.empty:
        st.warning("Informe pelo menos uma placa.")
        return False

    rows = []
    final_categories: dict[str, str] = {}
    final_daily_rates: dict[str, float] = {}
    original_daily_map = original_daily_map or {}
    for _, row in edited.iterrows():
        old_plate = clean_text(row.get("Placa atual")).strip().upper()
        new_plate = clean_text(row.get("Placa")).strip().upper()
        categoria = clean_text(row.get("Categoria") or "Transporte").strip()
        if not old_plate and not new_plate:
            continue
        if not new_plate:
            st.warning("Existe uma linha sem placa preenchida.")
            return False
        normalized = categoria.lower()
        if normalized == "vex":
            categoria_final = "Vex"
        elif "fret" in normalized:
            categoria_final = "Freteiro"
        elif normalized == "empilhadeira":
            categoria_final = "Empilhadeira"
        elif normalized == "estoque":
            categoria_final = "Estoque"
        elif normalized == "equipamento":
            categoria_final = "Equipamento"
        else:
            categoria_final = "Transporte"
        diaria = _parse_brl_number(row.get("Diaria (R$)")) or 0.0
        if diaria < 0:
            st.warning(f"A diária de {new_plate} não pode ser negativa.")
            return False
        if categoria_final != "Freteiro":
            diaria = 0.0
        final_categories[new_plate] = categoria_final
        final_daily_rates[new_plate] = round(float(diaria), 2)
        rows.append((old_plate, new_plate))

    if not rows:
        st.warning("Informe pelo menos uma placa.")
        return False

    changed = False
    try:
        for old_plate, new_plate in rows:
            categoria = final_categories.get(new_plate, "Transporte")
            diaria = final_daily_rates.get(new_plate, 0.0)
            if old_plate:
                if (
                    old_plate == new_plate
                    and original_map.get(old_plate, "Transporte") == categoria
                    and round(float(original_daily_map.get(old_plate, 0.0)), 2) == diaria
                ):
                    continue
                backend.rename_plate(old_plate, new_plate, categoria, diaria)
                changed = True
            else:
                backend.save_dashboard_record(
                    "placas",
                    {"PLACA": new_plate, "Categoria": categoria, "Diaria": diaria},
                    replace_keys=["PLACA"],
                )
                changed = True
    except Exception as exc:
        st.error("Não foi possível salvar a tabela de placas no Neon.")
        st.exception(exc)
        return False

    _reset_plate_editor()
    if changed:
        clear_cached_reads()
        st.success("Tabela de placas salva.")
    else:
        st.info("Nenhuma alteração para salvar.")
    st.rerun()
    return True


def _editor_empty_value(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return not value.strip()
    return False


ROW_ID_COLUMN = "Linha"


def _prepare_editor_rows(dataset: str, edited: pd.DataFrame, columns: list[str], required: list[str]) -> list[dict] | None:
    if edited is None:
        return []

    rows: list[dict] = []
    for idx, row in edited.iterrows():
        item = {column: row.get(column) for column in columns}
        if all(_editor_empty_value(value) for value in item.values()):
            continue
        if "Data" in item and not _editor_empty_value(item.get("Data")):
            item["Mes"] = _entry_month(item["Data"])
        missing = [column for column in required if _editor_empty_value(item.get(column))]
        if missing:
            st.warning(f"Linha {idx + 1}: preencha {', '.join(missing)}.")
            return None
        rows.append(item)
    return rows


def _prepare_editor_records(edited: pd.DataFrame, columns: list[str], required: list[str]) -> list[tuple[int | None, dict]] | None:
    if edited is None:
        return []

    records: list[tuple[int | None, dict]] = []
    for idx, row in edited.iterrows():
        item = {column: row.get(column) for column in columns}
        if all(_editor_empty_value(value) for value in item.values()):
            continue
        if "Data" in item and not _editor_empty_value(item.get("Data")):
            item["Mes"] = _entry_month(item["Data"])
        missing = [column for column in required if _editor_empty_value(item.get(column))]
        if missing:
            st.warning(f"Linha {idx + 1}: preencha {', '.join(missing)}.")
            return None

        row_id = row.get(ROW_ID_COLUMN)
        try:
            row_id = int(row_id) if not _editor_empty_value(row_id) else None
        except (TypeError, ValueError):
            row_id = None
        records.append((row_id, item))
    return records


def _merge_filtered_editor_rows(
    original_table: pd.DataFrame,
    edited: pd.DataFrame,
    columns: list[str],
    required: list[str],
    visible_row_ids: set[int],
) -> list[dict] | None:
    records = _prepare_editor_records(edited, columns, required)
    if records is None:
        return None

    edited_by_id = {row_id: item for row_id, item in records if row_id is not None}
    new_rows = [item for row_id, item in records if row_id is None]
    merged: list[dict] = []

    for idx, row in original_table.reset_index(drop=True).iterrows():
        row_id = idx + 1
        if row_id in visible_row_ids:
            if row_id in edited_by_id:
                merged.append(edited_by_id[row_id])
            continue
        merged.append({column: row.get(column) for column in columns})

    merged.extend(new_rows)
    return merged


def _reset_dataset_editor(key_prefix: str) -> None:
    key = f"{key_prefix}_editor_nonce"
    st.session_state[key] = st.session_state.get(key, 0) + 1


def _validate_velocity_editor_rows(rows: list[dict]) -> bool:
    for index, row in enumerate(rows, start=1):
        saida = pd.to_datetime(row.get("Saida"), errors="coerce")
        chegada = pd.to_datetime(row.get("Chegada"), errors="coerce")
        distancia = _parse_brl_number(row.get("Distancia Km"))
        tempo_parado = _parse_brl_number(row.get("Tempo Parado Min")) or 0.0
        eventos = _parse_brl_number(row.get("Eventos Excesso"))

        if pd.isna(saida) or pd.isna(chegada) or chegada <= saida:
            st.warning(f"Linha {index}: a chegada deve ser posterior a saida.")
            return False
        if distancia is None or distancia <= 0:
            st.warning(f"Linha {index}: a distancia deve ser maior que zero.")
            return False
        duration_minutes = (chegada - saida).total_seconds() / 60.0
        if tempo_parado < 0 or tempo_parado >= duration_minutes:
            st.warning(f"Linha {index}: o tempo parado deve ser menor que a duracao total da viagem.")
            return False
        if eventos is not None and (eventos < 0 or not float(eventos).is_integer()):
            st.warning(f"Linha {index}: eventos de excesso deve ser um numero inteiro nao negativo.")
            return False
    return True


def _save_dataset_editor(
    dataset: str,
    edited: pd.DataFrame,
    columns: list[str],
    required: list[str],
    key_prefix: str,
    original_table: pd.DataFrame,
    visible_row_ids: set[int],
) -> bool:
    try:
        if visible_row_ids and len(visible_row_ids) < len(original_table):
            records = _prepare_editor_records(edited, columns, required)
            if records is None:
                return False

            visible_original = []
            original_reset = original_table.reset_index(drop=True)
            for row_id in sorted(visible_row_ids):
                idx = row_id - 1
                if 0 <= idx < len(original_reset):
                    visible_original.append({column: original_reset.iloc[idx].get(column) for column in columns})

            rows = [item for _row_id, item in records]
            if dataset == "velocidade" and not _validate_velocity_editor_rows(rows):
                return False
            if visible_original:
                backend.delete_matching_dashboard_records(dataset, visible_original)
            if rows:
                backend.append_dashboard_records(dataset, rows)
        else:
            rows = _merge_filtered_editor_rows(original_table, edited, columns, required, visible_row_ids)
            if rows is None:
                return False
            if dataset == "velocidade" and not _validate_velocity_editor_rows(rows):
                return False
            backend.replace_dashboard_records(dataset, rows)
    except Exception as exc:
        st.error("Não foi possível salvar a tabela no Neon.")
        st.exception(exc)
        return False
    _reset_dataset_editor(key_prefix)
    clear_cached_reads()
    st.success("Tabela salva no Neon.")
    st.rerun()
    return True


def _filter_text_options(series: pd.Series) -> list[str]:
    if series is None or series.empty:
        return []
    values = series.astype("string").fillna("").str.strip()
    empty_mask = (values == "") | values.str.lower().isin(["nan", "none", "nat", "<na>"])
    options = sorted(values.loc[~empty_mask].unique().tolist())
    if bool(empty_mask.any()):
        options.append(TABLE_FILTER_EMPTY_LABEL)
    return options


def _filter_text_labels(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype="string")
    labels = series.astype("string").fillna("").str.strip()
    empty_mask = (labels == "") | labels.str.lower().isin(["nan", "none", "nat", "<na>"])
    return labels.mask(empty_mask, TABLE_FILTER_EMPTY_LABEL)


def _parse_filter_dates(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype="datetime64[ns]")
    parsed_values = []
    for value in series:
        text = str(value or "").strip()
        if not text or text.lower() in {"nan", "none", "nat", "<na>"}:
            parsed_values.append(pd.NaT)
            continue
        dayfirst = bool(re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", text))
        parsed_values.append(pd.to_datetime(value, errors="coerce", dayfirst=dayfirst))
    return pd.Series(parsed_values, index=series.index)


def _filter_date_labels(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype="string")
    parsed = _parse_filter_dates(series)
    fallback = series.astype("string").fillna("").str.strip()
    labels = parsed.dt.strftime("%d/%m/%Y").astype("string")
    labels = labels.where(parsed.notna(), fallback)
    return labels.fillna("").astype("string").str.strip()


def _filter_date_options(series: pd.Series) -> list[str]:
    labels = _filter_date_labels(series)
    if labels.empty:
        return []
    empty_mask = (labels == "") | labels.str.lower().isin(["nan", "none", "nat", "<na>"])
    valid = labels.loc[~empty_mask]
    rows = []
    for index, label in enumerate(valid.drop_duplicates().tolist()):
        parsed = pd.to_datetime(label, format="%d/%m/%Y", errors="coerce", dayfirst=True)
        order = parsed.toordinal() if pd.notna(parsed) else 10**9 + index
        rows.append((order, label))
    rows.sort(key=lambda item: (item[0], item[1]))
    options = [label for _, label in rows]
    if bool(empty_mask.any()):
        options.append(TABLE_FILTER_EMPTY_LABEL)
    return options


def _sort_table_recent_first(table: pd.DataFrame) -> pd.DataFrame:
    if table is None or table.empty:
        return table

    sorted_table = table.copy()
    order_column = None
    if "Data" in sorted_table.columns:
        order_column = "__jr_recent_date"
        sorted_table[order_column] = _parse_filter_dates(sorted_table["Data"])
    elif "Mes" in sorted_table.columns:
        order_column = "__jr_recent_month"
        sorted_table[order_column] = pd.to_datetime(
            sorted_table["Mes"].astype("string").str.strip(),
            errors="coerce",
        )

    sort_columns = []
    ascending = []
    if order_column:
        sort_columns.append(order_column)
        ascending.append(False)
    if ROW_ID_COLUMN in sorted_table.columns:
        sort_columns.append(ROW_ID_COLUMN)
        ascending.append(False)
    if not sort_columns:
        return sorted_table

    sorted_table = sorted_table.sort_values(
        sort_columns,
        ascending=ascending,
        na_position="last",
        kind="mergesort",
    )
    if order_column:
        sorted_table = sorted_table.drop(columns=[order_column])
    return sorted_table


def _ordered_table_filter_columns(table: pd.DataFrame, filter_columns: list[str]) -> list[str]:
    active = [column for column in list(filter_columns or []) if column != "Data"]
    if "Data" not in table.columns:
        return active
    if "Mes" in active:
        active.insert(active.index("Mes") + 1, "Data")
    else:
        active.insert(0, "Data")
    return active


def _sync_filter_selection_options(key: str, options: list[str]) -> None:
    if key not in st.session_state:
        return
    current = st.session_state.get(key) or []
    if not isinstance(current, list):
        current = list(current)
    allowed = set(options)
    normalized = [item for item in current if item in allowed]
    if normalized != current:
        st.session_state[key] = normalized


def _clear_table_filter_state(key_prefix: str) -> None:
    for key in list(st.session_state.keys()):
        if key == f"{key_prefix}_search" or key.startswith(f"{key_prefix}_filter_"):
            del st.session_state[key]


def _apply_table_filters(table: pd.DataFrame, columns: list[str], key_prefix: str, filter_columns: list[str]) -> pd.DataFrame:
    filtered = table.copy()
    with st.expander("Filtros da tabela", expanded=False):
        search = st.text_input("Buscar", key=f"{key_prefix}_search", placeholder="Digite para buscar em qualquer coluna")
        if search.strip():
            needle = search.strip().lower()
            search_frame = filtered[columns].astype("string").fillna("").apply(lambda col: col.str.lower())
            mask = search_frame.apply(lambda row: any(needle in value for value in row), axis=1)
            filtered = filtered.loc[mask].copy()

        active_filter_columns = _ordered_table_filter_columns(table, filter_columns)
        if active_filter_columns:
            filter_cols = st.columns(min(4, len(active_filter_columns)))
            for idx, column in enumerate(active_filter_columns):
                if column not in table.columns:
                    continue
                is_date_filter = column == "Data"
                options = _filter_date_options(filtered[column]) if is_date_filter else _filter_text_options(filtered[column])
                filter_key = f"{key_prefix}_filter_{column}"
                _sync_filter_selection_options(filter_key, options)
                with filter_cols[idx % len(filter_cols)]:
                    selected = st.multiselect("Dia" if is_date_filter else column, options, key=filter_key)
                if selected:
                    if is_date_filter:
                        values = _filter_date_labels(filtered[column])
                        empty_mask = (values == "") | values.str.lower().isin(["nan", "none", "nat", "<na>"])
                        values = values.mask(empty_mask, TABLE_FILTER_EMPTY_LABEL)
                    else:
                        values = _filter_text_labels(filtered[column])
                    filtered = filtered.loc[values.isin(selected)].copy()

        st.button("Limpar filtros", key=f"{key_prefix}_clear_filters", on_click=_clear_table_filter_state, args=(key_prefix,))
    return filtered


def _selected_table_filter_label(key_prefix: str, column: str) -> str:
    selected = st.session_state.get(f"{key_prefix}_filter_{column}") or []
    selected = [clean_text(item).strip() for item in selected if clean_text(item).strip()]
    if not selected:
        return ""
    if len(selected) <= 3:
        return ", ".join(selected)
    return f"{', '.join(selected[:3])} +{len(selected) - 3}"


def _render_table_plate_counter(filtered_table: pd.DataFrame, key_prefix: str) -> None:
    if filtered_table.empty or "PLACA" not in filtered_table.columns:
        return
    placas = filtered_table["PLACA"].astype("string").fillna("").str.strip()
    placas = placas[(placas != "") & (~placas.str.lower().isin(["nan", "none", "nat", "<na>"]))]
    count = int(placas.nunique())
    mes_label = _selected_table_filter_label(key_prefix, "Mes")
    dia_label = _selected_table_filter_label(key_prefix, "Data")
    scope = f"Mês {mes_label}" if mes_label else "Resultado filtrado"
    if dia_label:
        scope = f"{scope} - Dia {dia_label}"
    plural = "placa" if count == 1 else "placas"
    cards = [
        (
            '<div class="table-counter-card">'
            f"<span>{h(scope)}</span>"
            f"<strong>{count}</strong>"
            f"<span>{plural} diferentes</span>"
            "</div>"
        )
    ]

    if "Km Rodados" in filtered_table.columns:
        km_values = filtered_table["Km Rodados"].apply(lambda value: _parse_brl_number(value) or 0.0)
        km_total = float(km_values.sum())
        cards.append(
            (
                '<div class="table-counter-card table-counter-card--metric">'
                "<span>KM total</span>"
                f"<strong>{h(fmt_num(km_total))}</strong>"
                "<span>km rodados</span>"
                "</div>"
            )
        )

        if "Categoria" in filtered_table.columns:
            categorias = filtered_table["Categoria"].astype("string").fillna("").map(clean_text).str.strip()
        else:
            plate_map = _registered_plate_map()
            row_plates = filtered_table["PLACA"].astype("string").fillna("").map(clean_text).str.strip().str.upper()
            categorias = row_plates.map(lambda placa: plate_map.get(placa, "Transporte"))

        normalized = categorias.astype("string").fillna("").str.lower().str.strip()
        for label, key in (("Transporte", "transporte"), ("Vex", "vex")):
            sector_total = float(km_values.loc[normalized == key].sum())
            cards.append(
                (
                    '<div class="table-counter-card table-counter-card--metric">'
                    f"<span>{h(label)}</span>"
                    f"<strong>{h(fmt_num(sector_total))}</strong>"
                    "<span>km</span>"
                    "</div>"
                )
            )

    st.markdown(
        f"""<div class="table-counter-grid">{''.join(cards)}</div>""",
        unsafe_allow_html=True,
    )


def _format_delete_value(value: object) -> str:
    if _editor_empty_value(value):
        return ""
    if isinstance(value, (datetime, date, pd.Timestamp)):
        try:
            return pd.to_datetime(value).strftime("%d/%m/%Y")
        except Exception:
            return clean_text(value)
    return clean_text(value).strip()


def _delete_option_label(row: pd.Series, columns: list[str]) -> str:
    row_id = row.get(ROW_ID_COLUMN)
    parts = []
    for column in columns:
        value = _format_delete_value(row.get(column))
        if value:
            parts.append(value)
        if len(parts) >= 5:
            break
    summary = " | ".join(parts) if parts else "linha sem dados"
    return f"Linha {row_id} - {summary}"


def _render_delete_record_control(dataset: str, filtered_table: pd.DataFrame, columns: list[str], key_prefix: str, nonce: int) -> None:
    if filtered_table.empty or ROW_ID_COLUMN not in filtered_table.columns:
        return

    row_ids = pd.to_numeric(filtered_table[ROW_ID_COLUMN], errors="coerce").dropna().astype(int).tolist()
    if not row_ids:
        return

    rows_by_id = {}
    labels = {}
    for _, row in filtered_table.iterrows():
        try:
            row_id = int(row.get(ROW_ID_COLUMN))
        except (TypeError, ValueError):
            continue
        rows_by_id[row_id] = row
        labels[row_id] = _delete_option_label(row, columns)

    with st.expander("Apagar lançamento", expanded=False):
        selected_id = st.selectbox(
            "Escolha a linha para apagar",
            row_ids,
            format_func=lambda value: labels.get(value, f"Linha {value}"),
            key=f"{key_prefix}_delete_select_{nonce}",
        )
        if st.button("Apagar lançamento selecionado", type="primary", width="stretch", key=f"{key_prefix}_delete_button_{nonce}"):
            row = rows_by_id.get(selected_id)
            if row is None:
                st.warning("Selecione um lançamento válido.")
                return
            item = {column: row.get(column) for column in columns}
            try:
                deleted = backend.delete_matching_dashboard_records(dataset, [item])
            except Exception as exc:
                st.error("Não foi possível apagar esse lançamento no Neon.")
                st.exception(exc)
                return
            _reset_dataset_editor(key_prefix)
            clear_cached_reads()
            st.success(f"{deleted} lançamento(s) apagado(s).")
            st.rerun()


@st.fragment
def _render_dataset_editor(
    dataset: str,
    loader,
    columns: list[str],
    required: list[str],
    key_prefix: str,
    column_config: dict,
    filter_columns: list[str],
) -> None:
    try:
        df = loader()
    except Exception as exc:
        st.error("Não foi possível carregar a tabela do Neon.")
        st.exception(exc)
        return

    table = df[[column for column in columns if column in df.columns]].copy() if not df.empty else pd.DataFrame(columns=columns)
    for column in columns:
        if column not in table.columns:
            table[column] = pd.NA
    table = table[columns]
    table = table.reset_index(drop=True)
    table.insert(0, ROW_ID_COLUMN, range(1, len(table) + 1))

    last_success = st.session_state.pop(f"{key_prefix}_last_success", None)
    if last_success:
        st.success(last_success)

    st.markdown("#### Tabela cadastrada")
    filtered_table = _apply_table_filters(table, columns, key_prefix, filter_columns)
    filtered_table = _sort_table_recent_first(filtered_table)
    _render_table_plate_counter(filtered_table, key_prefix)

    total_rows = len(filtered_table)
    page_count = max(1, (total_rows + DATA_EDITOR_PAGE_SIZE - 1) // DATA_EDITOR_PAGE_SIZE)
    page_key = f"{key_prefix}_editor_page"
    raw_current_page = st.session_state.get(page_key, 1)
    if raw_current_page == DATA_EDITOR_ALL_PAGES:
        current_page = DATA_EDITOR_ALL_PAGES
    else:
        try:
            current_page = int(raw_current_page or 1)
        except (TypeError, ValueError):
            current_page = 1
            st.session_state[page_key] = current_page
        if current_page < 1 or current_page > page_count:
            current_page = 1
            st.session_state[page_key] = current_page
    if page_count > 1:
        page_options = [*range(1, page_count + 1), DATA_EDITOR_ALL_PAGES]
        page = st.selectbox(
            "Página da tabela",
            page_options,
            key=page_key,
            format_func=lambda value: (
                f"Todos os registros ({total_rows})"
                if value == DATA_EDITOR_ALL_PAGES
                else f"Página {value} de {page_count}"
            ),
        )
    else:
        page = 1
    if page == DATA_EDITOR_ALL_PAGES:
        start_row = 0
        end_row = total_rows
    else:
        start_row = (int(page) - 1) * DATA_EDITOR_PAGE_SIZE
        end_row = min(start_row + DATA_EDITOR_PAGE_SIZE, total_rows)
    editor_table = filtered_table.iloc[start_row:end_row].copy()
    if total_rows:
        if page == DATA_EDITOR_ALL_PAGES:
            st.caption(f"Exibindo todos os {total_rows} registros filtrados. Os mais recentes aparecem primeiro.")
        else:
            st.caption(f"Exibindo registros {start_row + 1} a {end_row} de {total_rows}. Os mais recentes aparecem primeiro.")

    visible_row_ids = set(pd.to_numeric(editor_table[ROW_ID_COLUMN], errors="coerce").dropna().astype(int).tolist())
    nonce = st.session_state.get(f"{key_prefix}_editor_nonce", 0)
    _render_delete_record_control(dataset, editor_table, columns, key_prefix, nonce)
    editor_config = {ROW_ID_COLUMN: st.column_config.NumberColumn("Linha")}
    editor_config.update(column_config)
    edited = st.data_editor(
        editor_table,
        width="stretch",
        height=420,
        hide_index=True,
        num_rows="dynamic",
        disabled=[ROW_ID_COLUMN],
        column_config=editor_config,
        key=f"{key_prefix}_sheet_editor_{nonce}",
    )
    if st.button("Salvar tabela", type="primary", width="stretch", key=f"{key_prefix}_sheet_save_{nonce}"):
        _save_dataset_editor(dataset, edited, columns, required, key_prefix, table[columns], visible_row_ids)


def _date_col(label: str = "Data"):
    return st.column_config.DateColumn(label, format="DD/MM/YYYY")


def _datetime_col(label: str):
    return st.column_config.DatetimeColumn(label, format="DD/MM/YYYY HH:mm")


def _money_col(label: str):
    return st.column_config.NumberColumn(label, min_value=0.0, step=0.01, format="R$ %.2f")


def _number_col(label: str, *, step: float = 1.0, format: str | None = None):
    return st.column_config.NumberColumn(label, min_value=0.0, step=step, format=format)


def _normalize_sheet_header(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in text.upper() if ch.isalnum())


def _parse_brl_number(value: object) -> float | None:
    if _editor_empty_value(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_text(value)
    text = text.replace("R$", "").replace("\u00a0", " ").strip()
    text = "".join(ch for ch in text if ch.isdigit() or ch in ",.-")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_sheet_date(value: object) -> tuple[date, str] | None:
    if _editor_empty_value(value):
        return None
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.notna(parsed):
        parsed_date = date(int(parsed.year), int(parsed.month), int(parsed.day))
        return parsed_date, f"{parsed_date.year}-{parsed_date.month:02d}"

    return None


def _parse_sheet_datetime(value: object, base_date: date) -> datetime | None:
    if _editor_empty_value(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().replace(tzinfo=None)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, datetime_time):
        return datetime.combine(base_date, value)
    if isinstance(value, date):
        return datetime.combine(value, datetime_time.min)

    text = clean_text(value).strip()
    time_match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if time_match:
        hour, minute, second = (int(part or 0) for part in time_match.groups())
        try:
            return datetime.combine(base_date, datetime_time(hour, minute, second))
        except ValueError:
            return None

    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(tzinfo=None)


def _sheet_datetime_is_time_only(value: object) -> bool:
    if isinstance(value, datetime_time):
        return True
    if isinstance(value, (datetime, pd.Timestamp, date)):
        return False
    return bool(re.fullmatch(r"\s*\d{1,2}:\d{2}(?::\d{2})?\s*", clean_text(value)))


def _parse_sheet_month(value: object) -> tuple[str, date] | None:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower().strip()
    is_full_date = bool(
        re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text)
        or re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", text)
    )
    if not isinstance(value, str) or is_full_date:
        parsed_date = _parse_sheet_date(value)
        if parsed_date:
            data, mes = parsed_date
            return mes, date(data.year, data.month, 1)
    month = None
    month_names = {
        "jan": 1,
        "janeiro": 1,
        "fev": 2,
        "fevereiro": 2,
        "mar": 3,
        "marco": 3,
        "abr": 4,
        "abril": 4,
        "mai": 5,
        "maio": 5,
        "jun": 6,
        "junho": 6,
        "jul": 7,
        "julho": 7,
        "ago": 8,
        "agosto": 8,
        "set": 9,
        "setembro": 9,
        "out": 10,
        "outubro": 10,
        "nov": 11,
        "novembro": 11,
        "dez": 12,
        "dezembro": 12,
    }
    for label, number in month_names.items():
        if label in text:
            month = number
            break

    digits = [int(part) for part in "".join(ch if ch.isdigit() else " " for ch in text).split()]
    year = None
    if month is not None and digits:
        year = digits[-1]
    elif len(digits) >= 2:
        if digits[0] > 31:
            year, month = digits[0], digits[1]
        else:
            month, year = digits[0], digits[-1]
    if year is not None and year < 100:
        year += 2000
    if not year or not month or not (1 <= month <= 12):
        return None
    return f"{year}-{month:02d}", date(year, month, 1)


COMBUSTIVEL_SHEET_ALIASES = {
    "DATA": ["DATA", "DT"],
    "LITROS": ["LITROS", "LITRO"],
    "CUSTO": ["CUSTO", "VALOR"],
    "COMBUSTIVEL": ["COMBUSTIVEL", "COMBUSTVEL", "COMBUSTI", "COMBUST"],
    "POSTOS": ["POSTOS", "POSTO"],
    "PLACA": ["PLACA", "PLACAS"],
}

KM_SHEET_ALIASES = {
    "PLACA": ["PLACA", "PLACAS"],
    "KM": ["KM", "KMRODADOS", "KMMES", "KMDOMES"],
    "MES": ["MES", "MS"],
}

PEDAGIO_SHEET_ALIASES = {
    "PLACA": ["PLACA", "PLACAS"],
    "TIPO": ["TIPO"],
    "CUSTO": ["CUSTO", "VALOR"],
    "MES": ["MES", "MS"],
}

ALUGUEL_VEICULOS_SHEET_ALIASES = {
    "INICIO": ["INICIO", "DATAINICIO", "DE", "DATA", "DT"],
    "FIM": ["FIM", "DATAFIM", "ATE"],
    "PLACA": ["PLACA", "VEICULO", "VEICULOPLACA", "PLACAVEICULO"],
    "CUSTO": ["CUSTO", "VALOR", "VALORMENSAL", "VALORTOTAL", "ALUGUEL"],
}

HOTEIS_SHEET_ALIASES = {
    "DATA": ["DATA", "DT"],
    "CIDADE": ["CIDADE"],
    "VALOR": ["VALOR", "CUSTO"],
    "HOTEL": ["HOTELPOUSADA", "HOTEL", "POUSADA"],
}

ALERTAS_VEX_SHEET_ALIASES = {
    "PLACA": ["PLACA", "VEICULO", "VEICULOPLACA"],
    "DATAHORA": ["DATAEHORA", "DATAHORA", "DATA", "DATETIME"],
    "LOCAL": ["LOCAL", "LOCALIZACAO", "CIDADE"],
    "IGN": ["IGN", "IGNICAO", "STATUSIGN", "STATUSIGNICAO"],
}

PESO_SHEET_ALIASES = {
    "DATA": ["DATA", "DT"],
    "CIDADE": ["CIDADE"],
    "ROTA": ["ROTA"],
    "PESO": ["PESO"],
    "PLACA": ["PLACA", "PLACAS"],
}

PESO_ROUTE_SHEET_ALIASES = {
    "DATA": ["DATA", "DT"],
    "PLACA": ["PLACA", "PLACAS"],
    "ROTA": ["ROTA"],
}

RODAGEM_ROTA_SHEET_ALIASES = {
    "KM": ["KM", "KMRODADOS", "KMROTA"],
    "MES": ["MES", "MS"],
    "ROTA": ["ROTA"],
    "PLACA": ["PLACA", "PLACAS"],
}

VELOCIDADE_SHEET_ALIASES = {
    "DATA": ["DATA", "DT"],
    "PLACA": ["PLACA", "PLACAS"],
    "SAIDA": ["SAIDA", "INICIO", "HORASAIDA", "DATAHORASAIDA"],
    "CHEGADA": ["CHEGADA", "FIM", "HORACHEGADA", "DATAHORACHEGADA"],
    "DISTANCIAKM": ["DISTANCIAKM", "DISTANCIA", "KMVIAGEM", "KM"],
}

VELOCIDADE_EXPORT_COLUMNS = [
    ("Data", "DATA"),
    ("Identificador", "IDENTIFICADOR"),
    ("PLACA", "PLACA"),
    ("Motorista", "MOTORISTA"),
    ("Rota", "ROTA"),
    ("Origem", "ORIGEM"),
    ("Destino", "DESTINO"),
    ("Saida", "SAIDA"),
    ("Chegada", "CHEGADA"),
    ("Distancia Km", "DISTANCIA_KM"),
    ("Tempo Parado Min", "TEMPO_PARADO_MIN"),
    ("Meta Minutos", "META_MINUTOS"),
    ("Velocidade Maxima", "VELOCIDADE_MAXIMA"),
    ("Limite KmH", "LIMITE_KMH"),
    ("Eventos Excesso", "EVENTOS_EXCESSO"),
    ("Observacao", "OBSERVACAO"),
]


@st.cache_data(show_spinner=False, max_entries=64)
def _sheet_xlsx_bytes(df: pd.DataFrame, sheet_name: str) -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill

    export_df = df.copy()
    for column in export_df.columns:
        normalized_column = _normalize_sheet_header(column)
        if normalized_column == "DATA":
            parsed = pd.to_datetime(export_df[column], errors="coerce")
            export_df[column] = parsed.map(lambda value: value.date() if pd.notna(value) else None)
        elif normalized_column in {"SAIDA", "CHEGADA"}:
            parsed = pd.to_datetime(export_df[column], errors="coerce")
            export_df[column] = parsed.map(lambda value: value.to_pydatetime() if pd.notna(value) else None)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        worksheet = writer.sheets[sheet_name[:31]]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        header_fill = PatternFill("solid", fgColor="1C2D6B")
        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center")

        for position, column in enumerate(export_df.columns, start=1):
            normalized_column = _normalize_sheet_header(column)
            if normalized_column == "DATA":
                for row in worksheet.iter_rows(min_row=2, min_col=position, max_col=position):
                    row[0].number_format = "DD/MM/YYYY"
            elif normalized_column in {"SAIDA", "CHEGADA"}:
                for row in worksheet.iter_rows(min_row=2, min_col=position, max_col=position):
                    row[0].number_format = "DD/MM/YYYY HH:MM"

        for column_cells in worksheet.columns:
            values = [str(cell.value) if cell.value is not None else "" for cell in column_cells]
            width = min(max((len(value) for value in values), default=10) + 2, 42)
            worksheet.column_dimensions[column_cells[0].column_letter].width = max(width, 12)

    return output.getvalue()


@st.cache_data(show_spinner=False, max_entries=8)
def _peso_workbook_bytes(entregas: pd.DataFrame, rodagem_rota: pd.DataFrame) -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame, header_color in (
            ("ENTREGAS", entregas.copy(), "1C2D6B"),
            ("RODAGEM POR ROTA", rodagem_rota.copy(), "FFF200"),
        ):
            if "DATA" in frame.columns:
                parsed = pd.to_datetime(frame["DATA"], errors="coerce")
                frame["DATA"] = parsed.map(lambda value: value.date() if pd.notna(value) else None)
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                cell.fill = PatternFill("solid", fgColor=header_color)
                cell.font = Font(color="000000" if header_color == "FFF200" else "FFFFFF", bold=True)
                cell.alignment = Alignment(horizontal="center")
            if "DATA" in frame.columns:
                data_column = list(frame.columns).index("DATA") + 1
                for row in worksheet.iter_rows(min_row=2, min_col=data_column, max_col=data_column):
                    row[0].number_format = "DD/MM/YYYY"
            for column_cells in worksheet.columns:
                values = [str(cell.value) if cell.value is not None else "" for cell in column_cells]
                width = min(max((len(value) for value in values), default=10) + 2, 42)
                worksheet.column_dimensions[column_cells[0].column_letter].width = max(width, 12)
@st.cache_data(show_spinner=False, max_entries=2)
def _velocity_model_xlsx_bytes() -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill

    columns = [target for _source, target in VELOCIDADE_EXPORT_COLUMNS]
    example = pd.DataFrame(
        [
            {
                "DATA": date.today(),
                "IDENTIFICADOR": "VIAGEM-001",
                "PLACA": "ABC1D23",
                "MOTORISTA": "MOTORISTA EXEMPLO",
                "ROTA": "ROTA EXEMPLO",
                "ORIGEM": "ORIGEM EXEMPLO",
                "DESTINO": "DESTINO EXEMPLO",
                "SAIDA": datetime.combine(date.today(), datetime_time(8, 0)),
                "CHEGADA": datetime.combine(date.today(), datetime_time(10, 0)),
                "DISTANCIA_KM": 120.0,
                "TEMPO_PARADO_MIN": 15.0,
                "META_MINUTOS": 135.0,
                "VELOCIDADE_MAXIMA": 82.0,
                "LIMITE_KMH": 80.0,
                "EVENTOS_EXCESSO": 1,
                "OBSERVACAO": "Linha apenas demonstrativa",
            }
        ],
        columns=columns,
    )
    instructions = pd.DataFrame(
        [
            ("DATA", "Obrigatorio", "Data de referencia da viagem (DD/MM/AAAA)."),
            ("IDENTIFICADOR", "Opcional", "Codigo unico do pedido, entrega ou viagem."),
            ("PLACA", "Obrigatorio", "Placa do veiculo."),
            ("MOTORISTA", "Opcional", "Nome do motorista."),
            ("ROTA", "Opcional", "Nome ou codigo da rota."),
            ("ORIGEM / DESTINO", "Opcional", "Pontos inicial e final."),
            ("SAIDA / CHEGADA", "Obrigatorio", "Data e hora no formato DD/MM/AAAA HH:MM."),
            ("DISTANCIA_KM", "Obrigatorio", "Distancia positiva percorrida na viagem."),
            ("TEMPO_PARADO_MIN", "Opcional", "Minutos parados durante a viagem; use zero quando nao houver."),
            ("META_MINUTOS", "Opcional", "Duracao maxima planejada para calcular o SLA."),
            ("VELOCIDADE_MAXIMA", "Opcional", "Maior velocidade registrada na viagem, em km/h."),
            ("LIMITE_KMH", "Opcional", "Limite de velocidade usado no acompanhamento."),
            ("EVENTOS_EXCESSO", "Opcional", "Quantidade de eventos acima do limite."),
            ("OBSERVACAO", "Opcional", "Comentario livre."),
        ],
        columns=["CAMPO", "PREENCHIMENTO", "ORIENTACAO"],
    )

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(columns=columns).to_excel(writer, sheet_name="Importacao", index=False)
        example.to_excel(writer, sheet_name="Exemplo", index=False)
        instructions.to_excel(writer, sheet_name="Instrucoes", index=False)
        header_fill = PatternFill("solid", fgColor="1C2D6B")
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = Font(color="FFFFFF", bold=True)
                cell.alignment = Alignment(horizontal="center")
            for column_cells in worksheet.columns:
                values = [str(cell.value) if cell.value is not None else "" for cell in column_cells]
                width = min(max((len(value) for value in values), default=10) + 2, 52)
                worksheet.column_dimensions[column_cells[0].column_letter].width = max(width, 13)
        for sheet_name in ("Importacao", "Exemplo"):
            worksheet = writer.sheets[sheet_name]
            for position, column in enumerate(columns, start=1):
                normalized_column = _normalize_sheet_header(column)
                if normalized_column == "DATA":
                    for row in worksheet.iter_rows(min_row=2, min_col=position, max_col=position):
                        row[0].number_format = "DD/MM/YYYY"
                elif normalized_column in {"SAIDA", "CHEGADA"}:
                    for row in worksheet.iter_rows(min_row=2, min_col=position, max_col=position):
                        row[0].number_format = "DD/MM/YYYY HH:MM"
    return output.getvalue()


@st.cache_data(show_spinner=False, max_entries=4)
def _backup_zip_bytes(version_token: tuple[tuple[str, str], ...]) -> bytes:
    del version_token
    generated_at = datetime.now(BR_TZ)
    summary_rows = []
    files: list[tuple[str, bytes]] = []
    for dataset, label, file_prefix, loader in BACKUP_TABLES:
        try:
            df = loader()
            if df is None:
                df = pd.DataFrame()
            df = df.reset_index(drop=True)
            status = "OK"
            error = ""
        except Exception as exc:
            df = pd.DataFrame()
            status = "Erro"
            error = clean_text(exc)
        summary_rows.append(
            {
                "Tabela": label,
                "Arquivo": f"{file_prefix}.xlsx",
                "Registros": int(len(df)),
                "Status": status,
                "Erro": error,
            }
        )
        if status == "OK":
            files.append((f"{file_prefix}.xlsx", _sheet_xlsx_bytes(df, label)))

    summary = pd.DataFrame(summary_rows)
    manifest = pd.DataFrame(
        [
            {"Campo": "Gerado em", "Valor": generated_at.strftime("%d/%m/%Y %H:%M:%S")},
            {"Campo": "Total de tabelas", "Valor": len(BACKUP_TABLES)},
            {"Campo": "Total de arquivos", "Valor": len(files)},
        ]
    )

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as backup_zip:
        backup_zip.writestr("resumo_backup.xlsx", _sheet_xlsx_bytes(pd.concat([manifest, summary], ignore_index=True), "Resumo"))
        for file_name, data in files:
            backup_zip.writestr(file_name, data)
    return output.getvalue()


def _backup_due(last_downloaded: datetime | None) -> bool:
    if last_downloaded is None:
        return True
    if last_downloaded.tzinfo is None:
        last_downloaded = last_downloaded.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - last_downloaded.astimezone(timezone.utc)
    return elapsed.days >= BACKUP_INTERVAL_DAYS


def _format_backup_datetime(value: datetime | None) -> str:
    if value is None:
        return "Nunca"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M")


def _backup_downloaded_callback() -> None:
    try:
        backend.mark_backup_downloaded()
        st.session_state["backup_last_marked_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        st.session_state["backup_mark_error"] = clean_text(exc)


@st.fragment
def _render_backup_panel() -> None:
    try:
        status = backend.get_backup_status()
        last_downloaded = status.get("last_downloaded_datetime")
        status_error = ""
    except Exception as exc:
        last_downloaded = None
        status_error = clean_text(exc)

    due = _backup_due(last_downloaded)
    with st.expander("Backup de segurança", expanded=due):
        if due:
            st.warning("Recomendado baixar o backup semanal dos dados.")
        else:
            st.info(f"Último backup registrado: {_format_backup_datetime(last_downloaded)}.")
        if status_error:
            st.caption(f"Não foi possível consultar a data do último backup: {status_error}")

        file_date = datetime.now(BR_TZ).strftime("%Y-%m-%d_%H-%M")
        backup_version = backend.dashboard_data_version(
            [dataset for dataset, _label, _file_prefix, _loader in BACKUP_TABLES]
        )
        st.download_button(
            "Baixar backup completo (.zip)",
            data=lambda version=backup_version: _backup_zip_bytes(version),
            file_name=f"backup_jr_dashboard_{file_date}.zip",
            mime="application/zip",
            key="cadastro_backup_download",
            on_click=_backup_downloaded_callback,
            width="stretch",
        )

        mark_error = st.session_state.pop("backup_mark_error", "")
        if mark_error:
            st.caption(f"O backup foi gerado, mas não foi possível registrar a data: {mark_error}")
        st.caption("O arquivo ZIP contém uma planilha por tabela e um resumo com a contagem de registros.")


def _sheet_export_frame(df: pd.DataFrame, columns: list[tuple[str, str]]) -> pd.DataFrame:
    exported = pd.DataFrame(index=df.index)
    for source, target in columns:
        exported[target] = df[source] if source in df.columns else None
    return exported.reset_index(drop=True)


def _sheet_export_month_options(df: pd.DataFrame) -> list[str]:
    if df.empty or "Mes" not in df.columns:
        return []
    values = df["Mes"].astype("string").fillna("").str.strip()
    months = [value for value in values.drop_duplicates().tolist() if parse_month_key(value)]
    return sorted(months, key=lambda value: parse_month_key(value) or (0, 0), reverse=True)


def _render_sheet_downloads(
    loader,
    columns: list[tuple[str, str]],
    example: dict[str, object],
    *,
    key_prefix: str,
    file_prefix: str,
    sheet_name: str,
) -> None:
    try:
        current_df = loader()
        if current_df is None:
            current_df = pd.DataFrame()
    except Exception as exc:
        current_df = pd.DataFrame()
        st.warning("Não foi possível carregar os dados cadastrados para exportação.")
        st.caption(str(exc))

    selected_month = None
    month_options = _sheet_export_month_options(current_df)
    if month_options:
        current_month = date.today().strftime("%Y-%m")
        default_index = month_options.index(current_month) if current_month in month_options else 0
        selected_month = st.selectbox(
            "Mês para exportar",
            month_options,
            index=default_index,
            format_func=month_filter_label,
            key=f"{key_prefix}_export_month",
        )
        month_values = current_df["Mes"].astype("string").fillna("").str.strip()
        current_df = current_df.loc[month_values.eq(selected_month)].copy()
    else:
        st.caption("Nenhum mês cadastrado para exportar.")

    data_frame = _sheet_export_frame(current_df, columns)
    example_frame = pd.DataFrame([example], columns=[target for _, target in columns])
    data_file_name = f"{file_prefix}_dados_{selected_month}.xlsx" if selected_month else f"{file_prefix}_dados.xlsx"
    download_columns = st.columns(2)
    with download_columns[0]:
        st.download_button(
            "Baixar planilha com dados",
            data=lambda frame=data_frame, name=sheet_name: _sheet_xlsx_bytes(frame, name),
            file_name=data_file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_download_data",
            on_click="ignore",
            width="stretch",
        )
    with download_columns[1]:
        st.download_button(
            "Baixar planilha de exemplo",
            data=lambda frame=example_frame, name=sheet_name: _sheet_xlsx_bytes(frame, name),
            file_name=f"{file_prefix}_exemplo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_download_example",
            on_click="ignore",
            width="stretch",
        )
    if selected_month:
        st.caption(
            f"A planilha com dados contém {len(data_frame)} registro(s) de {month_filter_label(selected_month)}. "
            "Os dois arquivos usam o formato aceito abaixo."
        )
    else:
        st.caption(f"A planilha com dados contém {len(data_frame)} registro(s). Os dois arquivos usam o formato aceito abaixo.")


def _read_uploaded_sheet(
    uploaded_file,
    aliases: dict[str, list[str]],
    *,
    sheet_names: list[str] | None = None,
    fallback_to_active: bool = True,
    preferred_sheet: str | None = None,
) -> pd.DataFrame:
    name = clean_text(getattr(uploaded_file, "name", "")).lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(uploaded_file, sep=None, engine="python", header=None)
        return _detect_sheet_header(raw, aliases)
    raw = _read_uploaded_excel_rows(
        uploaded_file,
        aliases,
        sheet_names=sheet_names,
        fallback_to_active=fallback_to_active,
        preferred_sheet=preferred_sheet,
    )
    if raw.empty:
        return pd.DataFrame()
    return _detect_sheet_header(raw, aliases)


def _read_uploaded_excel_rows(
    uploaded_file,
    aliases: dict[str, list[str]],
    *,
    sheet_names: list[str] | None = None,
    fallback_to_active: bool = True,
    preferred_sheet: str | None = None,
) -> pd.DataFrame:
    from openpyxl import load_workbook

    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
    worksheet = None
    if preferred_sheet and preferred_sheet in workbook.sheetnames:
        worksheet = workbook[preferred_sheet]
    elif sheet_names:
        accepted = {_normalize_sheet_header(name) for name in sheet_names}
        worksheet = next(
            (item for item in workbook.worksheets if _normalize_sheet_header(item.title) in accepted),
            None,
        )
    if worksheet is None and fallback_to_active:
        worksheet = workbook.active
    if worksheet is None:
        workbook.close()
        return pd.DataFrame()
    rows: list[list[object]] = []
    header_found = False
    blank_after_header = 0
    for row in worksheet.iter_rows(values_only=True):
        values = list(row)
        has_value = any(not _editor_empty_value(value) for value in values)
        rows.append(values)

        if not header_found:
            normalized = [_normalize_sheet_header(value) for value in values]
            header_found = all(any(alias in normalized for alias in field_aliases) for field_aliases in aliases.values())
            continue

        if has_value:
            blank_after_header = 0
        else:
            blank_after_header += 1
            if blank_after_header >= 50:
                break

    workbook.close()
    return pd.DataFrame(rows)


def _detect_sheet_header(raw: pd.DataFrame, aliases: dict[str, list[str]]) -> pd.DataFrame:
    for idx, row in raw.iterrows():
        normalized = [_normalize_sheet_header(value) for value in row.tolist()]
        if all(any(alias in normalized for alias in field_aliases) for field_aliases in aliases.values()):
            df = raw.iloc[idx + 1 :].copy()
            df.columns = [clean_text(value).strip() or f"Coluna {pos + 1}" for pos, value in enumerate(row.tolist())]
            return df.dropna(how="all").reset_index(drop=True)

    raw = raw.copy()
    raw.columns = [clean_text(value).strip() or f"Coluna {idx + 1}" for idx, value in enumerate(raw.iloc[0].tolist())]
    return raw.iloc[1:].dropna(how="all").reset_index(drop=True)


def _alertas_vex_rows_from_sheet(
    df: pd.DataFrame,
    plate_map: dict[str, str],
) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}

    def resolve(*aliases: str):
        return next((header_map[alias] for alias in aliases if alias in header_map), None)

    plate_column = resolve("PLACA", "VEICULO", "VEICULOPLACA")
    datetime_column = resolve("DATAEHORA", "DATAHORA", "DATA", "DATETIME")
    location_column = resolve("LOCAL", "LOCALIZACAO", "CIDADE")
    ign_column = resolve("IGN", "IGNICAO", "STATUSIGN", "STATUSIGNICAO")
    missing = [
        label
        for column, label in (
            (plate_column, "PLACA"),
            (datetime_column, "DATA E HORA"),
            (location_column, "LOCAL"),
            (ign_column, "IGN"),
        )
        if column is None
    ]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        placa = clean_text(row.get(plate_column)).strip().upper()
        raw_datetime = row.get(datetime_column)
        local = clean_text(row.get(location_column)).strip()
        ign = clean_text(row.get(ign_column)).strip()
        timestamp = pd.to_datetime(raw_datetime, dayfirst=True, errors="coerce")
        if not placa and _editor_empty_value(raw_datetime) and not local and not ign:
            continue
        missing_row = []
        if not placa:
            missing_row.append("PLACA")
        if pd.isna(timestamp):
            missing_row.append("DATA E HORA")
        if not local:
            missing_row.append("LOCAL")
        if not ign:
            missing_row.append("IGN")
        registered_category = plate_map.get(placa)
        if registered_category and registered_category != "Vex":
            errors.append(f"Linha {idx + 2}: a placa {placa} não pertence à categoria Vex.")
            continue
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue
        rows.append(
            {
                "Data": timestamp.to_pydatetime(),
                "Mes": timestamp.strftime("%Y-%m"),
                "PLACA": placa,
                "Local": local,
                "IGN": ign,
                "Categoria": "Vex",
            }
        )
    return rows, errors


def _alertas_vex_only_alert_rows(rows: list[dict]) -> list[dict]:
    active_values = {"LIGADO", "ON", "1", "TRUE", "SIM"}
    return [
        row
        for row in rows
        if pd.to_datetime(row.get("Data"), errors="coerce").dayofweek in (5, 6)
        and _normalize_sheet_header(row.get("IGN")) in active_values
    ]


def _pedagio_rows_from_sheet(df: pd.DataFrame, plate_map: dict[str, str]) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    aliases = {
        "DATA": ["DATA", "DT"],
        "PLACA": ["PLACA", "PLACAS"],
        "TIPO": ["TIPO"],
        "CUSTO": ["CUSTO", "VALOR"],
        "MES": ["MES", "MS"],
    }
    resolved = {field: next((header_map[key] for key in keys if key in header_map), None) for field, keys in aliases.items()}
    labels = {"PLACA": "PLACA", "TIPO": "TIPO", "CUSTO": "Custo", "MES": "MES"}
    missing = [label for field, label in labels.items() if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    optional_plate_types = {_normalize_sheet_header(value) for value in PEDAGIO_OPTIONAL_PLATE_TYPES}
    for idx, row in df.iterrows():
        placa = clean_text(row.get(resolved["PLACA"])).strip().upper()
        tipo = clean_text(row.get(resolved["TIPO"])).strip()
        custo = _parse_brl_number(row.get(resolved["CUSTO"]))
        mes_info = _parse_sheet_month(row.get(resolved["MES"]))
        data_info = _parse_sheet_date(row.get(resolved.get("DATA"))) if resolved.get("DATA") else None

        if not placa and not tipo and custo is None and mes_info is None and data_info is None:
            continue
        missing_row = []
        if not placa and _normalize_sheet_header(tipo) not in optional_plate_types:
            missing_row.append("PLACA")
        if not tipo:
            missing_row.append("TIPO")
        if custo is None:
            missing_row.append("Custo")
        if mes_info is None:
            missing_row.append("MES")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        mes, month_start = mes_info
        data = data_info[0] if data_info else month_start
        rows.append(
            {
                "Data": data,
                "Mes": mes,
                "PLACA": placa,
                "Tipo": tipo,
                "Custo": custo,
                "Categoria": plate_map.get(placa, "Transporte"),
            }
        )
    return rows, errors


def _aluguel_veiculos_rows_from_sheet(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}

    def resolve(*aliases: str):
        return next((header_map[alias] for alias in aliases if alias in header_map), None)

    inicio_column = resolve("INICIO", "DATAINICIO", "DE", "DATA", "DT")
    fim_column = resolve("FIM", "DATAFIM", "ATE")
    placa_column = resolve("PLACA", "VEICULO", "VEICULOPLACA", "PLACAVEICULO")
    custo_column = resolve("CUSTO", "VALOR", "VALORMENSAL", "VALORTOTAL", "ALUGUEL")
    fornecedor_column = resolve("FORNECEDOR", "LOCADORA", "EMPRESA", "FORNECEDORLOCADORA")
    observacao_column = resolve("OBSERVACAO", "OBS", "DESCRICAO")
    missing = [
        label
        for column, label in (
            (inicio_column, "INICIO"),
            (fim_column, "FIM"),
            (placa_column, "PLACA/VEICULO"),
            (custo_column, "VALOR MENSAL"),
        )
        if column is None
    ]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        inicio_info = _parse_sheet_date(row.get(inicio_column))
        fim_info = _parse_sheet_date(row.get(fim_column))
        placa = clean_text(row.get(placa_column)).strip().upper()
        custo = _parse_brl_number(row.get(custo_column))
        fornecedor = clean_text(row.get(fornecedor_column)).strip() if fornecedor_column else ""
        observacao = clean_text(row.get(observacao_column)).strip() if observacao_column else ""
        if inicio_info is None and fim_info is None and not placa and custo is None and not fornecedor and not observacao:
            continue
        missing_row = []
        if inicio_info is None:
            missing_row.append("INICIO")
        if fim_info is None:
            missing_row.append("FIM")
        if not placa:
            missing_row.append("PLACA/VEICULO")
        if custo is None:
            missing_row.append("VALOR MENSAL")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue
        inicio = inicio_info[0]
        fim = fim_info[0]
        if fim < inicio:
            errors.append(f"Linha {idx + 2}: FIM deve ser igual ou posterior ao INICIO.")
            continue
        rows.extend(
            _aluguel_period_rows(
                inicio,
                fim,
                placa,
                fornecedor,
                custo,
                observacao,
            )
        )
    return rows, errors


def _combustivel_rows_from_sheet(df: pd.DataFrame, plate_map: dict[str, str]) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    aliases = {
        "DATA": ["DATA", "DT"],
        "LITROS": ["LITROS", "LITRO"],
        "CUSTO": ["CUSTO", "VALOR"],
        "COMBUSTIVEL": ["COMBUSTIVEL", "COMBUSTVEL", "COMBUSTI", "COMBUST"],
        "POSTOS": ["POSTOS", "POSTO"],
        "PLACA": ["PLACA", "PLACAS"],
    }
    resolved = {field: next((header_map[key] for key in keys if key in header_map), None) for field, keys in aliases.items()}
    labels = {
        "DATA": "Data",
        "LITROS": "Litros",
        "CUSTO": "Custo",
        "COMBUSTIVEL": "Combustivel",
        "POSTOS": "Postos",
        "PLACA": "Placa",
    }
    missing = [labels[field] for field in labels if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        data_info = _parse_sheet_date(row.get(resolved["DATA"]))
        litros = _parse_brl_number(row.get(resolved["LITROS"]))
        custo = _parse_brl_number(row.get(resolved["CUSTO"]))
        combustivel = _sheet_text(row, resolved.get("COMBUSTIVEL"))
        posto = _sheet_text(row, resolved.get("POSTOS"), upper=True)
        placa_raw = _sheet_text(row, resolved.get("PLACA"), upper=True)
        placa_normalizada = backend._normalize_plate_value(placa_raw)
        placa = "" if pd.isna(placa_normalizada) else str(placa_normalizada)

        if not any([data_info, litros is not None, custo is not None, combustivel, posto, placa_raw]):
            continue

        missing_row = []
        if data_info is None:
            missing_row.append("Data")
        if litros is None:
            missing_row.append("Litros")
        if custo is None:
            missing_row.append("Custo")
        if not combustivel:
            missing_row.append("Combustivel")
        if not posto:
            missing_row.append("Postos")
        if not placa:
            missing_row.append("Placa")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        data, mes = data_info
        rows.append(
            {
                "Data": data,
                "Mes": mes,
                "Litros": litros,
                "Custo": custo,
                "Combustivel": combustivel,
                "POSTOS": posto,
                "PLACA": placa,
                "Categoria": plate_map.get(placa, "Transporte"),
            }
        )
    return rows, errors


def _km_rows_from_sheet(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    aliases = {
        "PLACA": ["PLACA", "PLACAS"],
        "KM": ["KM", "KMRODADOS", "KMMES", "KMDOMES"],
        "MES": ["MES", "MS"],
    }
    resolved = {field: next((header_map[key] for key in keys if key in header_map), None) for field, keys in aliases.items()}
    labels = {"PLACA": "Placa", "KM": "KM", "MES": "MES"}
    missing = [labels[field] for field in labels if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        placa_raw = _sheet_text(row, resolved.get("PLACA"), upper=True)
        placa_normalizada = backend._normalize_plate_value(placa_raw)
        placa = "" if pd.isna(placa_normalizada) else str(placa_normalizada)
        km = _parse_brl_number(row.get(resolved["KM"]))
        mes_info = _parse_sheet_month(row.get(resolved["MES"]))

        if not any([placa_raw, km is not None, mes_info]):
            continue

        missing_row = []
        if not placa:
            missing_row.append("Placa")
        if km is None:
            missing_row.append("KM")
        if mes_info is None:
            missing_row.append("MES")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        mes, _data = mes_info
        rows.append({"Mes": mes, "PLACA": placa, "Km Rodados": km})
    return rows, errors


def _rodagem_rota_rows_from_sheet(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    if df is None or df.empty:
        return [], []
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    resolved = {
        field: next((header_map[key] for key in aliases if key in header_map), None)
        for field, aliases in RODAGEM_ROTA_SHEET_ALIASES.items()
    }
    labels = {"KM": "KM", "MES": "MÊS", "ROTA": "ROTA", "PLACA": "PLACA"}
    missing = [labels[field] for field in labels if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando na aba RODAGEM POR ROTA: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        km = _parse_brl_number(row.get(resolved["KM"]))
        mes_info = _parse_sheet_month(row.get(resolved["MES"]))
        rota = _sheet_text(row, resolved.get("ROTA"), upper=True)
        placa_raw = _sheet_text(row, resolved.get("PLACA"), upper=True)
        placa_normalizada = backend._normalize_plate_value(placa_raw)
        placa = "" if pd.isna(placa_normalizada) else str(placa_normalizada)

        if not any([km is not None, mes_info, rota, placa_raw]):
            continue
        missing_row = []
        if km is None or km <= 0:
            missing_row.append("KM maior que zero")
        if mes_info is None:
            missing_row.append("MÊS")
        if not rota:
            missing_row.append("ROTA")
        if not placa:
            missing_row.append("PLACA")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        mes, _data = mes_info
        rows.append({"Mes": mes, "Rota": rota, "PLACA": placa, "Km Rodados": float(km)})

    if not rows:
        return [], errors
    grouped = (
        pd.DataFrame(rows)
        .groupby(["Mes", "Rota", "PLACA"], as_index=False)["Km Rodados"]
        .sum()
        .sort_values(["Mes", "Rota", "PLACA"])
    )
    return grouped.to_dict("records"), errors


def _sheet_text(row: pd.Series, column: str | None, *, upper: bool = False) -> str:
    if not column:
        return ""
    value = row.get(column)
    if pd.isna(value):
        return ""
    text = clean_text(value).strip()
    return text.upper() if upper else text


def _velocity_rows_from_sheet(df: pd.DataFrame, plate_map: dict[str, str]) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    aliases = {
        **VELOCIDADE_SHEET_ALIASES,
        "IDENTIFICADOR": ["IDENTIFICADOR", "VIAGEM", "VIAGEMID", "PEDIDO", "PEDIDOID"],
        "MOTORISTA": ["MOTORISTA", "CONDUTOR"],
        "ROTA": ["ROTA"],
        "ORIGEM": ["ORIGEM"],
        "DESTINO": ["DESTINO", "CIDADE"],
        "TEMPOPARADOMIN": ["TEMPOPARADOMIN", "PARADOMIN", "MINUTOSPARADO"],
        "METAMINUTOS": ["METAMINUTOS", "METAMIN", "PRAZOMINUTOS", "PRAZOMIN"],
        "VELOCIDADEMAXIMA": ["VELOCIDADEMAXIMA", "VELOCIDADEMAX", "MAXIMAKMH", "VMAX"],
        "LIMITEKMH": ["LIMITEKMH", "LIMITEVELOCIDADE", "LIMITE"],
        "EVENTOSEXCESSO": ["EVENTOSEXCESSO", "EXCESSOS", "QTDExCESSOS".upper()],
        "OBSERVACAO": ["OBSERVACAO", "OBS", "COMENTARIO"],
    }
    resolved = {
        field: next((header_map[key] for key in field_aliases if key in header_map), None)
        for field, field_aliases in aliases.items()
    }
    required_labels = {
        "DATA": "DATA",
        "PLACA": "PLACA",
        "SAIDA": "SAIDA",
        "CHEGADA": "CHEGADA",
        "DISTANCIAKM": "DISTANCIA_KM",
    }
    missing = [label for field, label in required_labels.items() if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        data_info = _parse_sheet_date(row.get(resolved["DATA"]))
        placa_raw = _sheet_text(row, resolved.get("PLACA"), upper=True)
        placa_normalizada = backend._normalize_plate_value(placa_raw)
        placa = "" if pd.isna(placa_normalizada) else str(placa_normalizada)
        distancia = _parse_brl_number(row.get(resolved["DISTANCIAKM"]))
        identificador = _sheet_text(row, resolved.get("IDENTIFICADOR"), upper=True)
        motorista = _sheet_text(row, resolved.get("MOTORISTA"), upper=True)
        rota = _sheet_text(row, resolved.get("ROTA"), upper=True)
        origem = _sheet_text(row, resolved.get("ORIGEM"), upper=True)
        destino = _sheet_text(row, resolved.get("DESTINO"), upper=True)
        observacao = _sheet_text(row, resolved.get("OBSERVACAO"))
        tempo_parado = _parse_brl_number(row.get(resolved.get("TEMPOPARADOMIN"))) if resolved.get("TEMPOPARADOMIN") else 0.0
        meta_minutos = _parse_brl_number(row.get(resolved.get("METAMINUTOS"))) if resolved.get("METAMINUTOS") else None
        velocidade_maxima = _parse_brl_number(row.get(resolved.get("VELOCIDADEMAXIMA"))) if resolved.get("VELOCIDADEMAXIMA") else None
        limite_kmh = _parse_brl_number(row.get(resolved.get("LIMITEKMH"))) if resolved.get("LIMITEKMH") else None
        eventos_excesso = _parse_brl_number(row.get(resolved.get("EVENTOSEXCESSO"))) if resolved.get("EVENTOSEXCESSO") else None

        if not any([data_info, placa_raw, distancia is not None, identificador, motorista, rota, origem, destino]):
            continue

        missing_row = []
        if data_info is None:
            missing_row.append("DATA")
        if not placa:
            missing_row.append("PLACA")
        if distancia is None or distancia <= 0:
            missing_row.append("DISTANCIA_KM positiva")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        data_value, mes = data_info
        saida_raw = row.get(resolved["SAIDA"])
        chegada_raw = row.get(resolved["CHEGADA"])
        saida = _parse_sheet_datetime(saida_raw, data_value)
        chegada = _parse_sheet_datetime(chegada_raw, data_value)
        if saida is None or chegada is None:
            invalid_fields = []
            if saida is None:
                invalid_fields.append("SAIDA")
            if chegada is None:
                invalid_fields.append("CHEGADA")
            errors.append(f"Linha {idx + 2}: data/hora invalida em {', '.join(invalid_fields)}.")
            continue
        if (
            chegada <= saida
            and _sheet_datetime_is_time_only(saida_raw)
            and _sheet_datetime_is_time_only(chegada_raw)
        ):
            chegada += timedelta(days=1)
        duration_minutes = (chegada - saida).total_seconds() / 60.0
        if duration_minutes <= 0:
            errors.append(f"Linha {idx + 2}: CHEGADA deve ser posterior a SAIDA.")
            continue

        tempo_parado = float(tempo_parado or 0.0)
        if tempo_parado < 0 or tempo_parado >= duration_minutes:
            errors.append(f"Linha {idx + 2}: TEMPO_PARADO_MIN deve ser menor que a duracao da viagem.")
            continue
        if meta_minutos is not None and meta_minutos <= 0:
            errors.append(f"Linha {idx + 2}: META_MINUTOS deve ser positiva.")
            continue
        if velocidade_maxima is not None and velocidade_maxima < 0:
            errors.append(f"Linha {idx + 2}: VELOCIDADE_MAXIMA nao pode ser negativa.")
            continue
        if limite_kmh is not None and limite_kmh <= 0:
            errors.append(f"Linha {idx + 2}: LIMITE_KMH deve ser positivo.")
            continue
        if eventos_excesso is not None and eventos_excesso < 0:
            errors.append(f"Linha {idx + 2}: EVENTOS_EXCESSO nao pode ser negativo.")
            continue
        if eventos_excesso is not None and not float(eventos_excesso).is_integer():
            errors.append(f"Linha {idx + 2}: EVENTOS_EXCESSO deve ser um numero inteiro.")
            continue

        rows.append(
            {
                "Data": data_value,
                "Mes": mes,
                "Identificador": identificador,
                "PLACA": placa,
                "Categoria": plate_map.get(placa, "Transporte"),
                "Motorista": motorista,
                "Rota": rota,
                "Origem": origem,
                "Destino": destino,
                "Saida": saida,
                "Chegada": chegada,
                "Distancia Km": float(distancia),
                "Tempo Parado Min": tempo_parado,
                "Meta Minutos": float(meta_minutos) if meta_minutos is not None else None,
                "Velocidade Maxima": float(velocidade_maxima) if velocidade_maxima is not None else None,
                "Limite KmH": float(limite_kmh) if limite_kmh is not None else None,
                "Eventos Excesso": int(eventos_excesso) if eventos_excesso is not None else None,
                "Observacao": observacao,
            }
        )
    return rows, errors


def _hoteis_rows_from_sheet(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    aliases = {
        "DATA": ["DATA", "DT"],
        "MOTORISTA": ["MOTORISTA"],
        "AJUDANTE": ["AJUDANTE"],
        "CIDADE": ["CIDADE"],
        "VALOR": ["VALOR", "CUSTO"],
        "HOTEL": ["HOTELPOUSADA", "HOTEL", "POUSADA"],
        "DIAS": ["DIAS", "DIA"],
        "TIPO": ["TIPO"],
    }
    resolved = {field: next((header_map[key] for key in keys if key in header_map), None) for field, keys in aliases.items()}
    labels = {"DATA": "DATA", "CIDADE": "CIDADE", "VALOR": "VALOR", "HOTEL": "HOTEL/POUSADA"}
    missing = [labels[field] for field in labels if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        data_info = _parse_sheet_date(row.get(resolved["DATA"]))
        motorista = _sheet_text(row, resolved.get("MOTORISTA"), upper=True)
        ajudante = _sheet_text(row, resolved.get("AJUDANTE"), upper=True)
        cidade = _sheet_text(row, resolved.get("CIDADE"), upper=True)
        hotel = _sheet_text(row, resolved.get("HOTEL"), upper=True)
        valor = _parse_brl_number(row.get(resolved["VALOR"]))
        dias = _parse_brl_number(row.get(resolved.get("DIAS"))) if resolved.get("DIAS") else 1.0
        tipo = _sheet_text(row, resolved.get("TIPO"), upper=True) or "Hospedagem"

        if not any([data_info, motorista, ajudante, cidade, hotel, valor is not None]):
            continue
        missing_row = []
        if data_info is None:
            missing_row.append("DATA")
        if not cidade:
            missing_row.append("CIDADE")
        if valor is None:
            missing_row.append("VALOR")
        if not hotel:
            missing_row.append("HOTEL/POUSADA")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        data, mes = data_info
        rows.append(
            {
                "Data": data,
                "Mes": mes,
                "Valor": valor,
                "Dias": dias if dias is not None else 1.0,
                "Motorista": motorista,
                "Ajudante": ajudante,
                "Cidade": cidade,
                "Hotel": hotel,
                "Tipo": tipo,
                "Categoria": "Transporte",
            }
        )
    return rows, errors


def _peso_rows_from_sheet(df: pd.DataFrame, plate_map: dict[str, str]) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    aliases = {
        "DATA": ["DATA", "DT"],
        "CIDADE": ["CIDADE"],
        "ROTA": ["ROTA"],
        "PESO": ["PESO"],
        "VALOR": ["VALOR", "CUSTO"],
        "PLACA": ["PLACA", "PLACAS"],
    }
    resolved = {field: next((header_map[key] for key in keys if key in header_map), None) for field, keys in aliases.items()}
    labels = {"DATA": "DATA", "PESO": "PESO", "PLACA": "PLACA"}
    missing = [labels[field] for field in labels if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        data_info = _parse_sheet_date(row.get(resolved["DATA"]))
        cidade = _sheet_text(row, resolved.get("CIDADE"), upper=True)
        rota = _sheet_text(row, resolved.get("ROTA"), upper=True)
        peso = _parse_brl_number(row.get(resolved["PESO"]))
        valor = _parse_brl_number(row.get(resolved.get("VALOR"))) if resolved.get("VALOR") else 0.0
        placa_raw = _sheet_text(row, resolved.get("PLACA"), upper=True)
        placa_normalizada = backend._normalize_plate_value(placa_raw)
        placa = "" if pd.isna(placa_normalizada) else str(placa_normalizada)

        if not any([data_info, cidade, peso is not None, valor not in (None, 0.0), placa_raw]):
            continue
        missing_row = []
        if data_info is None:
            missing_row.append("DATA")
        if peso is None:
            missing_row.append("PESO")
        if not placa:
            missing_row.append("PLACA")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        data, mes = data_info
        rows.append(
            {
                "Data": data,
                "Mes": mes,
                "Cidade": cidade,
                "Rota": rota,
                "Peso": peso,
                "Valor": valor if valor is not None else 0.0,
                "PLACA": placa,
                "Categoria": plate_map.get(placa, "Transporte"),
            }
        )
    return rows, errors


def _peso_route_rows_from_sheet(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    header_map = {_normalize_sheet_header(column): column for column in df.columns}
    resolved = {
        field: next((header_map[key] for key in aliases if key in header_map), None)
        for field, aliases in PESO_ROUTE_SHEET_ALIASES.items()
    }
    missing = [field for field in ("DATA", "PLACA", "ROTA") if resolved.get(field) is None]
    if missing:
        return [], [f"Colunas faltando: {', '.join(missing)}."]

    rows: list[dict] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        data_info = _parse_sheet_date(row.get(resolved["DATA"]))
        placa_raw = _sheet_text(row, resolved.get("PLACA"), upper=True)
        placa_normalizada = backend._normalize_plate_value(placa_raw)
        placa = "" if pd.isna(placa_normalizada) else str(placa_normalizada)
        rota = _sheet_text(row, resolved.get("ROTA"), upper=True)
        if data_info is None and not placa and not rota:
            continue

        missing_row = []
        if data_info is None:
            missing_row.append("DATA")
        if not placa:
            missing_row.append("PLACA")
        if missing_row:
            errors.append(f"Linha {idx + 2}: preencher {', '.join(missing_row)}.")
            continue

        data, _ = data_info
        rows.append({"Data": data, "PLACA": placa, "Rota": rota})
    return rows, errors


def _clear_hoteis_last_import() -> None:
    st.session_state.pop("cad_hotel_last_import_rows", None)
    st.session_state.pop("cad_hotel_last_import_count", None)


def _undo_hoteis_last_import() -> None:
    rows = st.session_state.get("cad_hotel_last_import_rows") or []
    if not rows:
        st.warning("Não há importação recente para apagar.")
        return
    try:
        deleted = backend.delete_matching_dashboard_records("hoteis", rows)
    except Exception as exc:
        st.error("Não foi possível apagar a última importação.")
        st.exception(exc)
        return
    _clear_hoteis_last_import()
    _reset_dataset_editor("cad_hotel_table")
    clear_cached_reads()
    st.success(f"{deleted} hospedagem(ns) apagada(s).")
    st.rerun()


@st.fragment
def _render_hoteis_sheet_import() -> None:
    last_rows = st.session_state.get("cad_hotel_last_import_rows") or []
    if last_rows:
        last_count = st.session_state.get("cad_hotel_last_import_count", len(last_rows))
        st.warning(f"Última importação por planilha: {last_count} hospedagem(ns).")
        undo_col, clear_col = st.columns([1, 1])
        with undo_col:
            if st.button("Apagar última importação", type="primary", width="stretch", key="cad_hotel_undo_import"):
                _undo_hoteis_last_import()
        with clear_col:
            if st.button("Manter importação", width="stretch", key="cad_hotel_keep_import"):
                _clear_hoteis_last_import()
                st.rerun()

    with st.expander("Adicionar hotéis por planilha", expanded=False):
        _render_sheet_downloads(
            backend.load_hoteis,
            [
                ("Data", "DATA"),
                ("Motorista", "MOTORISTA"),
                ("Ajudante", "AJUDANTE"),
                ("Cidade", "CIDADE"),
                ("Valor", "VALOR"),
                ("Hotel", "HOTEL/POUSADA"),
                ("Dias", "DIAS"),
                ("Tipo", "TIPO"),
            ],
            {
                "DATA": date.today(),
                "MOTORISTA": "MOTORISTA EXEMPLO",
                "AJUDANTE": "AJUDANTE EXEMPLO",
                "CIDADE": "SAO PAULO",
                "VALOR": 250.0,
                "HOTEL/POUSADA": "HOTEL EXEMPLO",
                "DIAS": 1,
                "TIPO": "Hospedagem",
            },
            key_prefix="cad_hotel_sheet",
            file_prefix="hoteis",
            sheet_name="Hotéis",
        )
        uploaded = st.file_uploader("Enviar planilha", type=["xlsx", "csv"], key="cad_hotel_upload")
        if uploaded is None:
            return

        try:
            raw_df = _read_uploaded_sheet(uploaded, HOTEIS_SHEET_ALIASES)
        except Exception as exc:
            st.error("Não foi possível ler a planilha. Envie um arquivo .xlsx ou .csv.")
            st.exception(exc)
            return

        rows, errors = _hoteis_rows_from_sheet(raw_df)
        if errors:
            st.warning("Revise a planilha antes de importar.")
            for error in errors[:8]:
                st.write(error)
            if len(errors) > 8:
                st.write(f"...mais {len(errors) - 8} erro(s).")
            return
        if not rows:
            st.warning("Nenhuma linha válida encontrada na planilha.")
            return

        preview = pd.DataFrame(rows)
        st.dataframe(
            preview[["Data", "Mes", "Cidade", "Hotel", "Motorista", "Ajudante", "Valor"]].rename(columns={"Mes": "Mês"}),
            width="stretch",
            hide_index=True,
        )
        if st.button(f"Importar {len(rows)} hospedagem(ns)", type="primary", width="stretch", key="cad_hotel_import_sheet"):
            imported_rows: list[dict] = []
            skipped_rows = 0
            try:
                with st.spinner("Conferindo os registros existentes e salvando a planilha completa..."):
                    imported_rows, skipped_rows = backend.append_missing_dashboard_records(
                        "hoteis",
                        rows,
                        update_plate_registry=False,
                    )
            except Exception as exc:
                st.error(
                    "A importação foi cancelada sem salvar um lote incompleto. "
                    "Tente novamente; os registros já existentes não serão duplicados."
                )
                st.exception(exc)
                return
            if imported_rows:
                st.session_state["cad_hotel_last_import_rows"] = imported_rows
                st.session_state["cad_hotel_last_import_count"] = len(imported_rows)
            else:
                _clear_hoteis_last_import()
            _reset_dataset_editor("cad_hotel_table")
            clear_cached_reads()
            st.success(
                f"{len(imported_rows)} hospedagem(ns) nova(s) importada(s) e "
                f"{skipped_rows} já existente(s) mantida(s)."
            )
            st.rerun()


def _clear_peso_last_import() -> None:
    st.session_state.pop("cad_peso_last_import_rows", None)
    st.session_state.pop("cad_peso_last_import_count", None)


def _undo_peso_last_import() -> None:
    rows = st.session_state.get("cad_peso_last_import_rows") or []
    if not rows:
        st.warning("Não há importação recente para apagar.")
        return
    try:
        deleted = backend.delete_matching_dashboard_records("peso", rows)
    except Exception as exc:
        st.error("Não foi possível apagar a última importação.")
        st.exception(exc)
        return
    _clear_peso_last_import()
    _reset_dataset_editor("cad_peso_table")
    clear_cached_reads()
    st.success(f"{deleted} entrega(s) apagada(s).")
    st.rerun()


def _render_peso_import_summary(preview: pd.DataFrame) -> None:
    count = int(preview.shape[0])
    peso_total = float(pd.to_numeric(preview.get("Peso"), errors="coerce").fillna(0).sum()) if "Peso" in preview.columns else 0.0
    valor_total = float(pd.to_numeric(preview.get("Valor"), errors="coerce").fillna(0).sum()) if "Valor" in preview.columns else 0.0
    cards = [
        (
            '<div class="table-counter-card table-counter-card--metric">'
            "<span>Importando</span>"
            f"<strong>{h(fmt_num(count))}</strong>"
            "<span>entrega(s)</span>"
            "</div>"
        ),
        (
            '<div class="table-counter-card table-counter-card--metric">'
            "<span>Peso total</span>"
            f"<strong>{h(fmt_peso(peso_total))}</strong>"
            "<span>na planilha</span>"
            "</div>"
        ),
        (
            '<div class="table-counter-card table-counter-card--metric">'
            "<span>Valor total</span>"
            f"<strong>{h(fmt_brl(valor_total))}</strong>"
            "<span>na planilha</span>"
            "</div>"
        ),
    ]
    st.markdown(f"""<div class="table-counter-grid">{''.join(cards)}</div>""", unsafe_allow_html=True)


def _render_peso_workbook_downloads() -> None:
    try:
        deliveries = backend.load_peso()
        route_km = backend.load_rodagem_rota()
    except Exception as exc:
        deliveries = pd.DataFrame()
        route_km = pd.DataFrame()
        st.warning("Não foi possível carregar todos os dados para exportação.")
        st.caption(clean_text(exc))

    month_frames = [
        frame[["Mes"]]
        for frame in (deliveries, route_km)
        if frame is not None and not frame.empty and "Mes" in frame.columns
    ]
    month_source = pd.concat(month_frames, ignore_index=True) if month_frames else pd.DataFrame(columns=["Mes"])
    month_options = _sheet_export_month_options(month_source)
    selected_month = None
    if month_options:
        current_month = date.today().strftime("%Y-%m")
        default_index = month_options.index(current_month) if current_month in month_options else 0
        selected_month = st.selectbox(
            "Mês para exportar",
            month_options,
            index=default_index,
            format_func=month_filter_label,
            key="cad_peso_sheet_export_month",
        )
        if not deliveries.empty and "Mes" in deliveries.columns:
            deliveries = deliveries.loc[deliveries["Mes"].astype("string").eq(selected_month)].copy()
        if not route_km.empty and "Mes" in route_km.columns:
            route_km = route_km.loc[route_km["Mes"].astype("string").eq(selected_month)].copy()

    deliveries_frame = _sheet_export_frame(
        deliveries,
        [("Data", "DATA"), ("Cidade", "CIDADE"), ("Rota", "ROTA"), ("Peso", "PESO"), ("Valor", "VALOR"), ("PLACA", "PLACA")],
    )
    route_frame = _sheet_export_frame(
        route_km,
        [("Km Rodados", "KM"), ("Mes", "MÊS"), ("Rota", "ROTA"), ("PLACA", "PLACA")],
    )
    example_deliveries = pd.DataFrame(
        [{"DATA": date.today(), "CIDADE": "SAO PAULO", "ROTA": "ROTA EXEMPLO", "PESO": 1250.5, "VALOR": 180.0, "PLACA": "ABC1D23"}]
    )
    example_route = pd.DataFrame(
        [{"KM": 1000.0, "MÊS": month_filter_label(date.today().strftime("%Y-%m")), "ROTA": "ROTA EXEMPLO", "PLACA": "ABC1D23"}]
    )
    data_name = f"peso_dados_{selected_month}.xlsx" if selected_month else "peso_dados.xlsx"
    columns = st.columns(2)
    with columns[0]:
        st.download_button(
            "Baixar planilha com dados",
            data=lambda: _peso_workbook_bytes(deliveries_frame, route_frame),
            file_name=data_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="cad_peso_sheet_download_data",
            on_click="ignore",
            width="stretch",
        )
    with columns[1]:
        st.download_button(
            "Baixar planilha de exemplo",
            data=lambda: _peso_workbook_bytes(example_deliveries, example_route),
            file_name="peso_exemplo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="cad_peso_sheet_download_example",
            on_click="ignore",
            width="stretch",
        )
    st.caption(
        f"Arquivo com {len(deliveries_frame)} entrega(s) e {len(route_frame)} rodagem(ns) por rota. "
        "Use as abas ENTREGAS e RODAGEM POR ROTA."
    )


@st.fragment
def _render_peso_sheet_import(plate_map: dict[str, str]) -> None:
    last_rows = st.session_state.get("cad_peso_last_import_rows") or []
    if last_rows:
        last_count = st.session_state.get("cad_peso_last_import_count", len(last_rows))
        st.warning(f"Última importação por planilha: {last_count} entrega(s).")
        undo_col, clear_col = st.columns([1, 1])
        with undo_col:
            if st.button("Apagar última importação", type="primary", width="stretch", key="cad_peso_undo_import"):
                _undo_peso_last_import()
        with clear_col:
            if st.button("Manter importação", width="stretch", key="cad_peso_keep_import"):
                _clear_peso_last_import()
                st.rerun()

    with st.expander("Adicionar peso por planilha", expanded=False):
        _render_peso_workbook_downloads()
        uploaded = st.file_uploader("Enviar planilha", type=["xlsx", "csv"], key="cad_peso_upload")
        if uploaded is None:
            return

        try:
            raw_df = _read_uploaded_sheet(
                uploaded,
                PESO_SHEET_ALIASES,
                sheet_names=["ENTREGAS", "PESO"],
            )
            uploaded_name = clean_text(getattr(uploaded, "name", "")).lower()
            route_raw_df = (
                pd.DataFrame()
                if uploaded_name.endswith(".csv")
                else _read_uploaded_sheet(
                    uploaded,
                    RODAGEM_ROTA_SHEET_ALIASES,
                    sheet_names=["RODAGEM POR ROTA"],
                    fallback_to_active=False,
                )
            )
        except Exception as exc:
            st.error("Não foi possível ler a planilha. Envie um arquivo .xlsx ou .csv.")
            st.exception(exc)
            return

        rows, errors = _peso_rows_from_sheet(raw_df, plate_map)
        route_rows, route_errors = _rodagem_rota_rows_from_sheet(route_raw_df)
        errors.extend(route_errors)
        if errors:
            st.warning("Revise a planilha antes de importar.")
            for error in errors[:8]:
                st.write(error)
            if len(errors) > 8:
                st.write(f"...mais {len(errors) - 8} erro(s).")
            return
        if not rows and not route_rows:
            st.warning("Nenhuma linha válida encontrada na planilha.")
            return

        if rows:
            preview = pd.DataFrame(rows)
            st.markdown("**Entregas**")
            st.dataframe(
                preview[["Data", "Mes", "Cidade", "Rota", "PLACA", "Peso", "Valor", "Categoria"]].rename(
                    columns={"Mes": "Mês", "PLACA": "Placa"}
                ),
                width="stretch",
                hide_index=True,
            )
            _render_peso_import_summary(preview)
        if route_rows:
            st.markdown("**Rodagem por rota**")
            st.dataframe(pd.DataFrame(route_rows), width="stretch", hide_index=True)
            st.caption(
                "Combinações repetidas de Mês + Rota + Placa foram somadas. "
                "Ao importar novamente, o valor cadastrado para a mesma combinação será substituído."
            )
        button_label = f"Importar {len(rows)} entrega(s) e {len(route_rows)} rodagem(ns)"
        if st.button(button_label, type="primary", width="stretch", key="cad_peso_import_sheet"):
            imported_rows: list[dict] = []
            skipped_rows = 0
            try:
                with st.spinner("Conferindo os registros existentes e salvando a planilha completa..."):
                    if rows:
                        imported_rows, skipped_rows = backend.append_missing_dashboard_records(
                            "peso",
                            rows,
                            update_plate_registry=False,
                        )
                    if route_rows:
                        backend.upsert_dashboard_records(
                            "rodagem_rota",
                            route_rows,
                            replace_keys=["Mes", "Rota", "PLACA"],
                        )
            except Exception as exc:
                st.error(
                    "A importação foi cancelada sem salvar um lote incompleto. "
                    "Tente novamente; os registros já existentes não serão duplicados."
                )
                st.exception(exc)
                return
            if imported_rows:
                st.session_state["cad_peso_last_import_rows"] = imported_rows
                st.session_state["cad_peso_last_import_count"] = len(imported_rows)
            else:
                _clear_peso_last_import()
            _reset_dataset_editor("cad_peso_table")
            _reset_dataset_editor("cad_rodagem_rota_table")
            clear_cached_reads()
            st.success(
                f"{len(imported_rows)} entrega(s) nova(s) importada(s), "
                f"{skipped_rows} já existente(s) mantida(s) e "
                f"{len(route_rows)} rodagem(ns) por rota salva(s)."
            )
            st.rerun()


@st.fragment
def _render_peso_route_import() -> None:
    last_success = st.session_state.pop("cad_peso_route_last_success", None)
    if last_success:
        st.success(last_success)

    with st.expander("Importar somente rotas", expanded=False):
        st.info(
            "Cada linha de rota sera ligada a um registro de Peso com a mesma data e placa. "
            "Somente a coluna Rota sera alterada; os demais dados permanecem como estao."
        )
        st.caption(
            "Use as colunas DATA, PLACA e ROTA. "
            "A ROTA pode ficar vazia. Quando a mesma placa tiver varias entregas no dia, "
            "mantenha as linhas na mesma ordem da planilha de Peso."
        )
        _render_sheet_downloads(
            backend.load_peso_route_template,
            [("Data", "DATA"), ("PLACA", "PLACA"), ("Rota", "ROTA")],
            {"DATA": date.today(), "PLACA": "ABC1D23", "ROTA": "ROTA EXEMPLO"},
            key_prefix="cad_peso_route_sheet",
            file_prefix="rotas_peso",
            sheet_name="Rotas",
        )

        upload_nonce = int(st.session_state.get("cad_peso_route_upload_nonce", 0))
        uploaded = st.file_uploader(
            "Enviar planilha de rotas",
            type=["xlsx", "csv"],
            key=f"cad_peso_route_upload_{upload_nonce}",
        )
        if uploaded is None:
            return

        try:
            raw_df = _read_uploaded_sheet(uploaded, PESO_ROUTE_SHEET_ALIASES)
        except Exception as exc:
            st.error("Não foi possível ler a planilha. Envie um arquivo .xlsx ou .csv.")
            st.exception(exc)
            return

        rows, errors = _peso_route_rows_from_sheet(raw_df)
        if errors:
            st.warning("Revise a planilha antes de importar.")
            for error in errors[:8]:
                st.write(error)
            if len(errors) > 8:
                st.write(f"...mais {len(errors) - 8} erro(s).")
            return
        if not rows:
            st.warning("Nenhuma rota válida encontrada na planilha.")
            return

        try:
            preview_result = backend.preview_peso_route_updates(rows)
        except Exception as exc:
            st.error("Não foi possível conferir as rotas com os pesos cadastrados.")
            st.warning(clean_text(exc))
            return

        match_errors = preview_result.get("errors") or []
        if match_errors:
            st.warning("Nenhum dado foi alterado. Corrija estas diferenças antes de importar:")
            for error in match_errors[:12]:
                st.write(error)
            if len(match_errors) > 12:
                st.write(f"...mais {len(match_errors) - 12} diferenca(s).")
            return

        match_warnings = preview_result.get("warnings") or []
        if match_warnings:
            st.warning("Estas linhas não possuem registro de peso e serão ignoradas:")
            for warning in match_warnings[:12]:
                st.write(warning)
            if len(match_warnings) > 12:
                st.write(f"...mais {len(match_warnings) - 12} aviso(s).")

        matches = preview_result.get("matches") or []
        preview = pd.DataFrame(matches)
        if preview.empty:
            st.warning("Não há registros de peso correspondentes a esta planilha.")
            return

        route_targets = len(
            {(str(row.get("Data")), str(row.get("PLACA"))) for row in rows}
        )
        ignored_rows = max(len(rows) - len(preview), 0)
        preview_display = preview.rename(
            columns={
                "RotaAtual": "Rota atual",
                "Rota": "Nova rota",
                "PLACAInformada": "Placa informada",
                "PLACA": "Placa cadastrada",
            }
        )
        preview_columns = [
            "Data",
            "Placa informada",
            "Placa cadastrada",
            "Rota atual",
            "Nova rota",
            "Cidade",
            "Peso",
            "Valor",
        ]
        adjusted_plates = (
            preview_display.loc[
                preview_display["Placa informada"].astype("string")
                != preview_display["Placa cadastrada"].astype("string"),
                ["Placa informada", "Placa cadastrada"],
            ]
            .drop_duplicates()
            .to_dict("records")
        )
        if adjusted_plates:
            adjustments = ", ".join(
                f"{item['Placa informada']} -> {item['Placa cadastrada']}"
                for item in adjusted_plates
            )
            st.info(f"Diferenças de digitação reconhecidas: {adjustments}.")
        st.success(
            f"{len(rows)} linha(s) conferida(s) em "
            f"{route_targets} combinação(ões) de data e placa. "
            f"A prévia abaixo mostra o pareamento com {len(preview)} registro(s) de peso."
        )
        st.dataframe(
            preview_display[[column for column in preview_columns if column in preview_display.columns]],
            width="stretch",
            hide_index=True,
        )
        if st.button(
            (
                f"Atualizar {len(preview)} registro(s) e ignorar {ignored_rows} linha(s)"
                if ignored_rows
                else f"Atualizar rota em {len(preview)} registro(s)"
            ),
            type="primary",
            width="stretch",
            key="cad_peso_route_import_confirm",
        ):
            try:
                with st.spinner("Conferindo os registros e salvando todas as rotas..."):
                    updated = backend.update_peso_routes(rows)
            except Exception as exc:
                st.error("A importação foi cancelada sem deixar uma atualização parcial de rotas.")
                st.warning(clean_text(exc))
                return
            _reset_dataset_editor("cad_peso_table")
            clear_cached_reads()
            st.session_state["cad_peso_route_upload_nonce"] = upload_nonce + 1
            st.session_state["cad_peso_route_last_success"] = (
                f"{updated} registro(s) de peso atualizado(s). "
                f"{max(len(rows) - updated, 0)} linha(s) sem correspondencia ignorada(s). "
                "Os demais dados foram preservados."
                if len(rows) > updated
                else f"{updated} registro(s) de peso atualizado(s). Os demais dados foram preservados."
            )
            st.rerun()


def _render_rodagem_rota_management(plate_map: dict[str, str]) -> None:
    with st.expander("Rodagem mensal em KM por rota", expanded=False):
        st.info(
            "Informe quanto cada placa rodou em uma rota no mês. O combustível da rota será calculado "
            "pelo custo mensal de combustível por KM da placa multiplicado por esta rodagem."
        )
        with st.form("form_rodagem_rota", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                month_date = st.date_input(
                    "Mês de referência",
                    value=date.today().replace(day=1),
                    key="cad_rodagem_rota_mes",
                )
            with c2:
                rota = st.text_input("Rota", key="cad_rodagem_rota_rota").strip().upper()
            with c3:
                placa = st.selectbox(
                    "Placa",
                    list(plate_map),
                    index=None,
                    placeholder="Selecione uma placa",
                    key="cad_rodagem_rota_placa",
                )
            with c4:
                km_rota = st.number_input(
                    "KM rodados na rota",
                    min_value=0.01,
                    step=10.0,
                    format="%.2f",
                    key="cad_rodagem_rota_km",
                )
                submitted = st.form_submit_button("Salvar rodagem", type="primary", width="stretch")
            if submitted:
                _save_entry(
                    "rodagem_rota",
                    {
                        "Mes": _entry_month(month_date),
                        "Rota": rota,
                        "PLACA": placa,
                        "Km Rodados": km_rota,
                    },
                    required=["Mes", "Rota", "PLACA", "Km Rodados"],
                    replace_keys=["Mes", "Rota", "PLACA"],
                    reset_table_key="cad_rodagem_rota_table",
                    success="Rodagem mensal da rota salva.",
                )

        uploaded = st.file_uploader(
            "Importar somente rodagem por rota",
            type=["xlsx", "csv"],
            key="cad_rodagem_rota_upload",
        )
        if uploaded is not None:
            try:
                raw_df = _read_uploaded_sheet(
                    uploaded,
                    RODAGEM_ROTA_SHEET_ALIASES,
                    sheet_names=["RODAGEM POR ROTA"],
                )
                route_rows, errors = _rodagem_rota_rows_from_sheet(raw_df)
            except Exception as exc:
                st.error("Não foi possível ler a rodagem por rota.")
                st.exception(exc)
                route_rows, errors = [], []
            if errors:
                st.warning("Revise a planilha antes de importar.")
                for error in errors[:8]:
                    st.write(error)
                if len(errors) > 8:
                    st.write(f"...mais {len(errors) - 8} erro(s).")
            elif route_rows:
                st.dataframe(pd.DataFrame(route_rows), width="stretch", hide_index=True)
                if st.button(
                    f"Importar {len(route_rows)} rodagem(ns)",
                    type="primary",
                    width="stretch",
                    key="cad_rodagem_rota_import",
                ):
                    try:
                        with st.spinner("Salvando toda a planilha de rodagem..."):
                            backend.upsert_dashboard_records(
                                "rodagem_rota",
                                route_rows,
                                replace_keys=["Mes", "Rota", "PLACA"],
                            )
                    except Exception as exc:
                        st.error("A importação foi cancelada sem deixar uma rodagem parcial.")
                        st.exception(exc)
                    else:
                        _reset_dataset_editor("cad_rodagem_rota_table")
                        clear_cached_reads()
                        st.success(f"{len(route_rows)} rodagem(ns) por rota salva(s).")
                        st.rerun()

    st.markdown("#### Rodagem por rota cadastrada")
    _render_dataset_editor(
        "rodagem_rota",
        backend.load_rodagem_rota,
        ["Mes", "Rota", "PLACA", "Km Rodados"],
        ["Mes", "Rota", "PLACA", "Km Rodados"],
        "cad_rodagem_rota_table",
        {
            "Mes": st.column_config.TextColumn("Mês"),
            "Rota": st.column_config.TextColumn("Rota"),
            "PLACA": st.column_config.TextColumn("Placa"),
            "Km Rodados": _number_col("KM rodados", step=1.0, format="%.2f"),
        },
        ["Mes", "Rota", "PLACA"],
    )


def _clear_combustivel_last_import() -> None:
    st.session_state.pop("cad_comb_last_import_rows", None)
    st.session_state.pop("cad_comb_last_import_count", None)


def _undo_combustivel_last_import() -> None:
    rows = st.session_state.get("cad_comb_last_import_rows") or []
    if not rows:
        st.warning("Não há importação recente para apagar.")
        return
    try:
        deleted = backend.delete_matching_dashboard_records("combustivel", rows)
    except Exception as exc:
        st.error("Não foi possível apagar a última importação.")
        st.exception(exc)
        return
    _clear_combustivel_last_import()
    _reset_dataset_editor("cad_comb_table")
    clear_cached_reads()
    st.success(f"{deleted} lançamento(s) apagado(s).")
    st.rerun()


@st.fragment
def _render_combustivel_sheet_import(plate_map: dict[str, str]) -> None:
    last_rows = st.session_state.get("cad_comb_last_import_rows") or []
    if last_rows:
        last_count = st.session_state.get("cad_comb_last_import_count", len(last_rows))
        st.warning(f"Última importação por planilha: {last_count} lançamento(s).")
        undo_col, clear_col = st.columns([1, 1])
        with undo_col:
            if st.button("Apagar última importação", type="primary", width="stretch", key="cad_comb_undo_import"):
                _undo_combustivel_last_import()
        with clear_col:
            if st.button("Manter importação", width="stretch", key="cad_comb_keep_import"):
                _clear_combustivel_last_import()
                st.rerun()

    with st.expander("Adicionar combustível por planilha", expanded=False):
        _render_sheet_downloads(
            backend.load_combustivel,
            [
                ("Data", "DATA"),
                ("Litros", "LITROS"),
                ("Custo", "CUSTO"),
                ("Combustivel", "COMBUSTIVEL"),
                ("POSTOS", "POSTOS"),
                ("PLACA", "PLACA"),
            ],
            {
                "DATA": date.today(),
                "LITROS": 45.5,
                "CUSTO": 270.0,
                "COMBUSTIVEL": "DIESEL S10",
                "POSTOS": "POSTO EXEMPLO",
                "PLACA": "ABC1D23",
            },
            key_prefix="cad_comb_sheet",
            file_prefix="combustivel",
            sheet_name="Combustível",
        )
        uploaded = st.file_uploader("Enviar planilha", type=["xlsx", "csv"], key="cad_comb_upload")
        if uploaded is None:
            return

        try:
            raw_df = _read_uploaded_sheet(uploaded, COMBUSTIVEL_SHEET_ALIASES)
        except Exception as exc:
            st.error("Não foi possível ler a planilha. Envie um arquivo .xlsx ou .csv.")
            st.exception(exc)
            return

        rows, errors = _combustivel_rows_from_sheet(raw_df, plate_map)
        if errors:
            st.warning("Revise a planilha antes de importar.")
            for error in errors[:8]:
                st.write(error)
            if len(errors) > 8:
                st.write(f"...mais {len(errors) - 8} erro(s).")
            return
        if not rows:
            st.warning("Nenhuma linha válida encontrada na planilha.")
            return

        preview = pd.DataFrame(rows)
        st.success(f"{len(rows)} lançamento(s) prontos para importar.")
        st.dataframe(
            preview[["Data", "Mes", "PLACA", "Combustivel", "POSTOS", "Litros", "Custo", "Categoria"]].rename(
                columns={"Mes": "Mês", "PLACA": "Placa", "Combustivel": "Combustível", "POSTOS": "Posto"}
            ),
            width="stretch",
            hide_index=True,
        )
        if st.button("Importar combustível", type="primary", width="stretch", key="cad_comb_import_confirm"):
            imported_rows: list[dict] = []
            skipped_rows = 0
            try:
                with st.spinner("Conferindo os registros existentes e salvando a planilha completa..."):
                    imported_rows, skipped_rows = backend.append_missing_dashboard_records(
                        "combustivel",
                        rows,
                        update_plate_registry=False,
                    )
            except Exception as exc:
                st.error(
                    "A importação foi cancelada sem salvar um lote incompleto. "
                    "Tente novamente; os registros já existentes não serão duplicados."
                )
                st.exception(exc)
                return
            if imported_rows:
                st.session_state["cad_comb_last_import_rows"] = imported_rows
                st.session_state["cad_comb_last_import_count"] = len(imported_rows)
            else:
                _clear_combustivel_last_import()
            _reset_dataset_editor("cad_comb_table")
            clear_cached_reads()
            st.success(
                f"{len(imported_rows)} lançamento(s) novo(s) importado(s) e "
                f"{skipped_rows} já existente(s) mantido(s)."
            )
            st.rerun()


@st.fragment
def _render_peso_month_reset() -> None:
    with st.expander("Zerar peso por mês", expanded=False):
        st.warning("Essa ação apaga todos os lançamentos de peso do mês escolhido.")

        anos = [CURRENT_YEAR]
        df_preview = pd.DataFrame()
        try:
            df_preview = backend.load_peso()
            if not df_preview.empty and "Mes" in df_preview.columns:
                parsed_years = pd.to_datetime(df_preview["Mes"], errors="coerce").dt.year.dropna().astype(int).unique().tolist()
                anos = sorted(set(anos) | set(parsed_years), reverse=True)
        except Exception as exc:
            st.info("Não foi possível carregar a tabela de peso para prever os totais, mas a exclusão ainda pode ser tentada.")
            st.caption(str(exc))

        c1, c2 = st.columns(2)
        with c1:
            ano = st.selectbox("Ano", anos, index=0, key="cad_peso_reset_ano")
        with c2:
            mes_num = st.selectbox(
                "Mes",
                list(range(1, 13)),
                index=max(date.today().month - 1, 0),
                format_func=lambda value: f"{value:02d}",
                key="cad_peso_reset_mes",
            )

        mes_key = f"{int(ano)}-{int(mes_num):02d}"
        if not df_preview.empty and "Mes" in df_preview.columns:
            mask = df_preview["Mes"].astype("string").str.strip().eq(mes_key)
            linhas = int(mask.sum())
            peso_total = float(pd.to_numeric(df_preview.loc[mask, "Peso"], errors="coerce").sum()) if "Peso" in df_preview.columns else 0.0
            st.caption(f"{mes_key}: {linhas} lançamento(s), {fmt_peso(peso_total)}.")
        else:
            st.caption(f"Mês selecionado: {mes_key}.")

        confirmar = st.checkbox(f"Confirmo que quero zerar o peso de {mes_key}.", key="cad_peso_reset_confirm")
        if st.button("Zerar mês de peso", type="primary", width="stretch", disabled=not confirmar, key="cad_peso_reset_button"):
            try:
                delete_month = getattr(backend, "delete_dashboard_month", None)
                if callable(delete_month):
                    deleted = delete_month("peso", mes_key)
                else:
                    if df_preview.empty:
                        raise RuntimeError("A tabela de peso não foi carregada para apagar pelo modo compatível.")
                    fallback = df_preview.copy()
                    month_mask = fallback["Mes"].astype("string").str.strip().eq(mes_key) if "Mes" in fallback.columns else pd.Series(False, index=fallback.index)
                    if "Data" in fallback.columns:
                        data_period = pd.to_datetime(fallback["Data"], errors="coerce").dt.to_period("M").astype("string")
                        month_mask = month_mask | data_period.eq(mes_key)
                    rows = fallback.loc[month_mask].to_dict("records")
                    deleted = backend.delete_matching_dashboard_records("peso", rows) if rows else 0
            except Exception as exc:
                st.error("Não foi possível zerar esse mês no Neon.")
                st.exception(exc)
                return
            _reset_dataset_editor("cad_peso_table")
            clear_cached_reads()
            st.success(f"{deleted} lançamento(s) de peso apagado(s) em {mes_key}.")
            st.rerun()


def _clear_pedagio_last_import() -> None:
    st.session_state.pop("cad_ped_last_import_rows", None)
    st.session_state.pop("cad_ped_last_import_count", None)


def _undo_pedagio_last_import() -> None:
    rows = st.session_state.get("cad_ped_last_import_rows") or []
    if not rows:
        st.warning("Não há importação recente para apagar.")
        return
    try:
        deleted = backend.delete_matching_dashboard_records("pedagio", rows)
    except Exception as exc:
        st.error("Não foi possível apagar a última importação.")
        st.exception(exc)
        return
    _clear_pedagio_last_import()
    _reset_dataset_editor("cad_ped_table")
    clear_cached_reads()
    st.success(f"{deleted} lançamento(s) apagado(s).")
    st.rerun()


def _append_records_in_batches(dataset: str, rows: list[dict], *, batch_size: int = 100) -> list[dict]:
    imported: list[dict] = []
    total = len(rows)
    progress = st.progress(0, text="Preparando envio...")
    status = st.empty()

    for start in range(0, total, batch_size):
        batch = rows[start : start + batch_size]
        batch_number = (start // batch_size) + 1
        batch_total = (total + batch_size - 1) // batch_size
        status.info(f"Enviando lote {batch_number}/{batch_total} ({start + 1}-{min(start + len(batch), total)} de {total})...")
        backend.append_dashboard_records(dataset, batch, update_plate_registry=False)
        imported.extend(batch)
        progress.progress(min(len(imported) / total, 1.0), text=f"{len(imported)} de {total} lancamentos enviados")

    status.empty()
    progress.empty()
    clear_cached_reads()
    return imported


def _save_records_with_replace_in_batches(dataset: str, rows: list[dict], replace_keys: list[str], *, batch_size: int = 100) -> list[dict]:
    imported: list[dict] = []
    total = len(rows)
    progress = st.progress(0, text="Preparando envio...")
    status = st.empty()

    for start in range(0, total, batch_size):
        batch = rows[start : start + batch_size]
        batch_number = (start // batch_size) + 1
        batch_total = (total + batch_size - 1) // batch_size
        status.info(f"Enviando lote {batch_number}/{batch_total} ({start + 1}-{min(start + len(batch), total)} de {total})...")
        for row in batch:
            backend.save_dashboard_record(dataset, row, replace_keys=replace_keys)
        imported.extend(batch)
        progress.progress(min(len(imported) / total, 1.0), text=f"{len(imported)} de {total} registros enviados")

    status.empty()
    progress.empty()
    clear_cached_reads()
    return imported


def _clear_velocity_last_import() -> None:
    st.session_state.pop("cad_vel_last_import_rows", None)
    st.session_state.pop("cad_vel_last_import_count", None)


def _undo_velocity_last_import() -> None:
    rows = st.session_state.get("cad_vel_last_import_rows") or []
    if not rows:
        st.warning("Nao ha importacao recente para apagar.")
        return
    try:
        deleted = backend.delete_matching_dashboard_records("velocidade", rows)
    except Exception as exc:
        st.error("Nao foi possivel apagar a ultima importacao de velocidade.")
        st.exception(exc)
        return
    _clear_velocity_last_import()
    _reset_dataset_editor("cad_vel_table")
    clear_cached_reads()
    st.success(f"{deleted} viagem(ns) apagada(s).")
    st.rerun()


def _velocity_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    return _sheet_export_frame(df, VELOCIDADE_EXPORT_COLUMNS)


def _velocity_preview_metrics(rows: list[dict]) -> tuple[float, float, float | None]:
    distance_total = 0.0
    movement_minutes = 0.0
    sla_values: list[bool] = []
    for row in rows:
        saida = pd.to_datetime(row.get("Saida"), errors="coerce")
        chegada = pd.to_datetime(row.get("Chegada"), errors="coerce")
        distance = float(row.get("Distancia Km") or 0.0)
        stopped = float(row.get("Tempo Parado Min") or 0.0)
        if pd.notna(saida) and pd.notna(chegada) and chegada > saida:
            duration = (chegada - saida).total_seconds() / 60.0
            movement = max(duration - stopped, 0.0)
            if distance > 0 and movement > 0:
                distance_total += distance
                movement_minutes += movement
            target = row.get("Meta Minutos")
            if target is not None and float(target) > 0:
                sla_values.append(duration <= float(target))
    average_speed = distance_total / (movement_minutes / 60.0) if movement_minutes > 0 else 0.0
    sla = (sum(sla_values) / len(sla_values) * 100.0) if sla_values else None
    return distance_total, average_speed, sla


@st.fragment
def _render_velocity_sheet_import(plate_map: dict[str, str]) -> None:
    last_rows = st.session_state.get("cad_vel_last_import_rows") or []
    if last_rows:
        last_count = st.session_state.get("cad_vel_last_import_count", len(last_rows))
        st.warning(f"Ultima importacao por planilha: {last_count} viagem(ns).")
        undo_col, keep_col = st.columns(2)
        with undo_col:
            if st.button("Apagar ultima importacao", type="primary", width="stretch", key="cad_vel_undo_import"):
                _undo_velocity_last_import()
        with keep_col:
            if st.button("Manter importacao", width="stretch", key="cad_vel_keep_import"):
                _clear_velocity_last_import()
                st.rerun()

    with st.expander("Importar viagens e exportar modelos", expanded=True):
        st.caption(
            "Cada linha representa uma viagem. SAIDA e CHEGADA aceitam data e hora; "
            "quando forem informadas apenas horas e a chegada for menor, o sistema considera o dia seguinte."
        )
        model_columns = [target for _source, target in VELOCIDADE_EXPORT_COLUMNS]
        empty_model = pd.DataFrame(columns=model_columns)
        model_downloads = st.columns(2)
        with model_downloads[0]:
            st.download_button(
                "Baixar modelo Excel",
                data=_velocity_model_xlsx_bytes,
                file_name="modelo_velocidade.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="cad_vel_model_xlsx",
                on_click="ignore",
                width="stretch",
            )
        with model_downloads[1]:
            st.download_button(
                "Baixar modelo CSV",
                data=empty_model.to_csv(index=False).encode("utf-8-sig"),
                file_name="modelo_velocidade.csv",
                mime="text/csv",
                key="cad_vel_model_csv",
                on_click="ignore",
                width="stretch",
            )
        st.caption("O Excel inclui abas de importacao, exemplo preenchido e instrucoes de cada campo.")

        try:
            current_df = backend.load_velocidade()
        except Exception as exc:
            current_df = pd.DataFrame()
            st.caption(f"Os modelos estao disponiveis, mas os dados cadastrados nao puderam ser carregados: {clean_text(exc)}")
        export_df = _velocity_export_frame(current_df)
        data_downloads = st.columns(2)
        with data_downloads[0]:
            st.download_button(
                "Exportar dados cadastrados (Excel)",
                data=lambda frame=export_df: _sheet_xlsx_bytes(frame, "Velocidade"),
                file_name="velocidade_dados.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="cad_vel_data_xlsx",
                on_click="ignore",
                width="stretch",
            )
        with data_downloads[1]:
            st.download_button(
                "Exportar dados cadastrados (CSV)",
                data=export_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="velocidade_dados.csv",
                mime="text/csv",
                key="cad_vel_data_csv",
                on_click="ignore",
                width="stretch",
            )

        uploaded = st.file_uploader("Enviar planilha preenchida", type=["xlsx", "csv"], key="cad_vel_upload")
        if uploaded is None:
            return
        try:
            raw_df = _read_uploaded_sheet(
                uploaded,
                VELOCIDADE_SHEET_ALIASES,
                preferred_sheet="Importacao",
            )
        except Exception as exc:
            st.error("Nao foi possivel ler a planilha. Envie o modelo em .xlsx ou .csv.")
            st.exception(exc)
            return

        rows, errors = _velocity_rows_from_sheet(raw_df, plate_map)
        if errors:
            st.warning("Revise a planilha antes de importar. Nenhum dado foi salvo.")
            for error in errors[:12]:
                st.write(error)
            if len(errors) > 12:
                st.write(f"...mais {len(errors) - 12} erro(s).")
            return
        if not rows:
            st.warning("Nenhuma viagem valida encontrada na planilha.")
            return

        preview = pd.DataFrame(rows)
        distance_total, average_speed, sla = _velocity_preview_metrics(rows)
        sla_text = fmt_percent(sla, 1) if sla is not None else "sem meta"
        st.success(
            f"{len(rows)} viagem(ns) pronta(s): {fmt_num(distance_total, 1)} km, "
            f"velocidade media ponderada de {fmt_num(average_speed, 1)} km/h e SLA {sla_text}."
        )
        preview_columns = [
            "Data",
            "Identificador",
            "PLACA",
            "Motorista",
            "Rota",
            "Saida",
            "Chegada",
            "Distancia Km",
            "Tempo Parado Min",
            "Meta Minutos",
        ]
        st.dataframe(preview[preview_columns].head(100), width="stretch", hide_index=True)
        if len(preview) > 100:
            st.caption(f"Previa limitada às primeiras 100 de {len(preview)} linhas.")
        if st.button(f"Importar {len(rows)} viagem(ns)", type="primary", width="stretch", key="cad_vel_import_confirm"):
            try:
                with st.spinner(f"Importando {len(rows)} viagem(ns) em uma unica transacao..."):
                    backend.append_dashboard_records(
                        "velocidade",
                        rows,
                        update_plate_registry=True,
                    )
                clear_cached_reads()
                imported_rows = rows
            except Exception as exc:
                st.error("Nao foi possivel importar as viagens para o Neon.")
                st.caption("Nenhuma linha desta importacao foi salva; corrija o problema e tente novamente.")
                st.exception(exc)
                return
            st.session_state["cad_vel_last_import_rows"] = imported_rows
            st.session_state["cad_vel_last_import_count"] = len(imported_rows)
            _reset_dataset_editor("cad_vel_table")
            st.success(f"{len(imported_rows)} viagem(ns) importada(s).")
            st.rerun()


@st.fragment
def _render_km_sheet_import() -> None:
    with st.expander("Adicionar KM mensal por planilha", expanded=False):
        _render_sheet_downloads(
            backend.load_combustivel_km,
            [("PLACA", "PLACA"), ("Km Rodados", "KM"), ("Mes", "MES")],
            {"PLACA": "ABC1D23", "KM": 2500.0, "MES": date.today().strftime("%Y-%m")},
            key_prefix="cad_km_sheet",
            file_prefix="km_mensal",
            sheet_name="KM mensal",
        )
        uploaded = st.file_uploader("Enviar planilha", type=["xlsx", "csv"], key="cad_km_upload")
        if uploaded is None:
            return

        try:
            raw_df = _read_uploaded_sheet(uploaded, KM_SHEET_ALIASES)
        except Exception as exc:
            st.error("Não foi possível ler a planilha. Envie um arquivo .xlsx ou .csv.")
            st.exception(exc)
            return

        rows, errors = _km_rows_from_sheet(raw_df)
        if errors:
            st.warning("Revise a planilha antes de importar.")
            for error in errors[:8]:
                st.write(error)
            if len(errors) > 8:
                st.write(f"...mais {len(errors) - 8} erro(s).")
            return
        if not rows:
            st.warning("Nenhuma linha válida encontrada na planilha.")
            return

        substituir = st.checkbox("Substituir KM se já existir o mesmo mês e placa", value=True, key="cad_km_import_replace")
        preview = pd.DataFrame(rows)
        st.success(f"{len(rows)} registro(s) prontos para importar.")
        st.dataframe(
            preview[["Mes", "PLACA", "Km Rodados"]].rename(columns={"Mes": "Mês", "PLACA": "Placa"}),
            width="stretch",
            hide_index=True,
        )
        if st.button("Importar KM mensal", type="primary", width="stretch", key="cad_km_import_confirm"):
            skipped_rows = 0
            try:
                with st.spinner("Conferindo os registros existentes e salvando a planilha completa..."):
                    if substituir:
                        backend.upsert_dashboard_records(
                            "combustivel_km",
                            rows,
                            replace_keys=["Mes", "PLACA"],
                        )
                        imported_rows = rows
                    else:
                        imported_rows, skipped_rows = backend.append_missing_dashboard_records(
                            "combustivel_km",
                            rows,
                            update_plate_registry=False,
                        )
            except Exception as exc:
                st.error(
                    "A importação foi cancelada sem salvar um lote incompleto. "
                    "Tente novamente; os registros já existentes não serão duplicados."
                )
                st.exception(exc)
                return
            _reset_dataset_editor("cad_km_table")
            clear_cached_reads()
            if substituir:
                st.success(f"{len(imported_rows)} registro(s) de KM salvo(s) ou substituido(s).")
            else:
                st.success(
                    f"{len(imported_rows)} registro(s) de KM novo(s) importado(s) e "
                    f"{skipped_rows} já existente(s) mantido(s)."
                )
            st.rerun()


def _clear_aluguel_last_import() -> None:
    st.session_state.pop("cad_aluguel_last_import_rows", None)
    st.session_state.pop("cad_aluguel_last_import_count", None)


def _undo_aluguel_last_import() -> None:
    rows = st.session_state.get("cad_aluguel_last_import_rows") or []
    if not rows:
        st.warning("Não há importação recente para apagar.")
        return
    try:
        deleted = backend.delete_matching_dashboard_records("aluguel_veiculos", rows)
    except Exception as exc:
        st.error("Não foi possível apagar a última importação de aluguéis.")
        st.exception(exc)
        return
    _clear_aluguel_last_import()
    _reset_dataset_editor("cad_aluguel_table")
    clear_cached_reads()
    st.success(f"{deleted} aluguel(is) apagado(s).")
    st.rerun()


def _load_aluguel_periods_for_export() -> pd.DataFrame:
    """Reúne as mensalidades no período original para exportação."""
    df = backend.load_aluguel_veiculos().copy()
    if df.empty:
        return df
    data = pd.to_datetime(df.get("Data"), errors="coerce")
    for column in ("Inicio", "Fim"):
        values = pd.to_datetime(df.get(column), errors="coerce") if column in df else data.copy()
        df[column] = values.fillna(data)
    contract_columns = ["Inicio", "Fim", "PLACA", "Fornecedor", "Observacao"]
    for column in ("PLACA", "Fornecedor", "Observacao"):
        df[column] = df.get(column, pd.Series(index=df.index, dtype="string")).astype("string").fillna("")
    df["Custo"] = pd.to_numeric(df.get("Custo"), errors="coerce").fillna(0.0)
    periods = df.groupby(contract_columns, dropna=False, as_index=False)["Custo"].first()
    inicio = pd.to_datetime(periods["Inicio"], errors="coerce")
    periods["Mes"] = inicio.dt.strftime("%Y-%m").astype("string")
    return periods.reset_index(drop=True)


@st.fragment
def _render_aluguel_sheet_import() -> None:
    last_rows = st.session_state.get("cad_aluguel_last_import_rows") or []
    if last_rows:
        last_count = st.session_state.get("cad_aluguel_last_import_count", len(last_rows))
        st.warning(f"Última importação por planilha: {last_count} aluguel(is) de veículo(s).")
        undo_col, clear_col = st.columns(2)
        with undo_col:
            if st.button("Apagar última importação", type="primary", width="stretch", key="cad_aluguel_undo_import"):
                _undo_aluguel_last_import()
        with clear_col:
            if st.button("Manter importação", width="stretch", key="cad_aluguel_keep_import"):
                _clear_aluguel_last_import()
                st.rerun()

    with st.expander("Adicionar aluguel de veículos por planilha", expanded=False):
        example_start = date.today()
        _render_sheet_downloads(
            _load_aluguel_periods_for_export,
            [
                ("Inicio", "INICIO"),
                ("Fim", "FIM"),
                ("PLACA", "PLACA/VEICULO"),
                ("Fornecedor", "FORNECEDOR/LOCADORA"),
                ("Custo", "VALOR MENSAL"),
                ("Observacao", "OBSERVACAO"),
            ],
            {
                "INICIO": example_start,
                "FIM": _aluguel_one_cycle_end(example_start),
                "PLACA/VEICULO": "ABC1D23",
                "FORNECEDOR/LOCADORA": "LOCADORA EXEMPLO",
                "VALOR MENSAL": 2500.0,
                "OBSERVACAO": "Aluguel mensal",
            },
            key_prefix="cad_aluguel_sheet",
            file_prefix="aluguel_veiculos_vex",
            sheet_name="Aluguel Veiculos Vex",
        )
        uploaded = st.file_uploader("Enviar planilha", type=["xlsx", "csv"], key="cad_aluguel_upload")
        if uploaded is None:
            return
        try:
            raw_df = _read_uploaded_sheet(uploaded, ALUGUEL_VEICULOS_SHEET_ALIASES)
        except Exception as exc:
            st.error("Não foi possível ler a planilha. Envie um arquivo .xlsx ou .csv.")
            st.exception(exc)
            return
        rows, errors = _aluguel_veiculos_rows_from_sheet(raw_df)
        if errors:
            st.warning("Revise a planilha antes de importar.")
            for error in errors[:8]:
                st.write(error)
            if len(errors) > 8:
                st.write(f"...mais {len(errors) - 8} erro(s).")
            return
        if not rows:
            st.warning("Nenhuma linha válida encontrada na planilha.")
            return
        preview = pd.DataFrame(rows)
        st.dataframe(
            preview[["Inicio", "Fim", "Data", "Mes", "PLACA", "Fornecedor", "Custo", "Observacao"]].rename(
                columns={"Inicio": "Início", "Mes": "Mês", "PLACA": "Placa", "Observacao": "Observação"}
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"A planilha gerou {len(rows)} mensalidade(s). O VALOR MENSAL de cada linha foi repetido "
            "em todos os meses de INÍCIO a FIM."
        )
        if st.button(
            f"Importar {len(rows)} mensalidade(s)",
            type="primary",
            width="stretch",
            key="cad_aluguel_import_sheet",
        ):
            try:
                with st.spinner("Conferindo registros e salvando a planilha completa..."):
                    imported_rows, skipped_rows = backend.append_missing_dashboard_records(
                        "aluguel_veiculos",
                        rows,
                        update_plate_registry=False,
                    )
            except Exception as exc:
                st.error(
                    "A importação foi cancelada sem salvar um lote incompleto. "
                    "Tente novamente; os registros existentes não serão duplicados."
                )
                st.exception(exc)
                return
            if imported_rows:
                st.session_state["cad_aluguel_last_import_rows"] = imported_rows
                st.session_state["cad_aluguel_last_import_count"] = len(imported_rows)
            else:
                _clear_aluguel_last_import()
            _reset_dataset_editor("cad_aluguel_table")
            clear_cached_reads()
            st.success(
                f"{len(imported_rows)} mensalidade(s) nova(s) importada(s) e "
                f"{skipped_rows} já existente(s) mantido(s)."
            )
            st.rerun()


@st.fragment
def _render_pedagio_sheet_import(plate_map: dict[str, str]) -> None:
    last_rows = st.session_state.get("cad_ped_last_import_rows") or []
    if last_rows:
        last_count = st.session_state.get("cad_ped_last_import_count", len(last_rows))
        st.warning(f"Última importação por planilha: {last_count} lançamento(s).")
        undo_col, clear_col = st.columns([1, 1])
        with undo_col:
            if st.button("Apagar última importação", type="primary", width="stretch", key="cad_ped_undo_import"):
                _undo_pedagio_last_import()
        with clear_col:
            if st.button("Manter importação", width="stretch", key="cad_ped_keep_import"):
                _clear_pedagio_last_import()
                st.rerun()

    with st.expander("Adicionar pedágio/extras por planilha", expanded=False):
        _render_sheet_downloads(
            backend.load_pedagio,
            [("Data", "DATA"), ("PLACA", "PLACA"), ("Tipo", "TIPO"), ("Custo", "CUSTO"), ("Mes", "MES")],
            {
                "DATA": date.today(),
                "PLACA": "ABC1D23",
                "TIPO": "Pedágio",
                "CUSTO": 35.9,
                "MES": date.today().strftime("%Y-%m"),
            },
            key_prefix="cad_ped_sheet",
            file_prefix="pedagio_extras",
            sheet_name="Pedágio e Extras",
        )
        uploaded = st.file_uploader("Enviar planilha", type=["xlsx", "csv"], key="cad_ped_upload")
        if uploaded is None:
            return

        try:
            raw_df = _read_uploaded_sheet(uploaded, PEDAGIO_SHEET_ALIASES)
        except Exception as exc:
            st.error("Não foi possível ler a planilha. Envie um arquivo .xlsx ou .csv.")
            st.exception(exc)
            return

        rows, errors = _pedagio_rows_from_sheet(raw_df, plate_map)
        if errors:
            st.warning("Revise a planilha antes de importar.")
            for error in errors[:8]:
                st.write(error)
            if len(errors) > 8:
                st.write(f"...mais {len(errors) - 8} erro(s).")
            return
        if not rows:
            st.warning("Nenhuma linha válida encontrada na planilha.")
            return

        preview = pd.DataFrame(rows)
        st.dataframe(
            preview[["Mes", "PLACA", "Categoria", "Tipo", "Custo"]].rename(columns={"Mes": "Mês", "PLACA": "Placa"}),
            width="stretch",
            hide_index=True,
        )
        if st.button(f"Importar {len(rows)} lançamentos", type="primary", width="stretch", key="cad_ped_import_sheet"):
            imported_rows: list[dict] = []
            skipped_rows = 0
            try:
                with st.spinner("Conferindo os registros existentes e salvando a planilha completa..."):
                    imported_rows, skipped_rows = backend.append_missing_dashboard_records(
                        "pedagio",
                        rows,
                        update_plate_registry=False,
                    )
            except Exception as exc:
                st.error(
                    "A importação foi cancelada sem salvar um lote incompleto. "
                    "Tente novamente; os registros já existentes não serão duplicados."
                )
                st.exception(exc)
                return
            if imported_rows:
                st.session_state["cad_ped_last_import_rows"] = imported_rows
                st.session_state["cad_ped_last_import_count"] = len(imported_rows)
            else:
                _clear_pedagio_last_import()
            _reset_dataset_editor("cad_ped_table")
            clear_cached_reads()
            st.success(
                f"{len(imported_rows)} lançamento(s) novo(s) importado(s) e "
                f"{skipped_rows} já existente(s) mantido(s)."
            )
            st.rerun()


@st.fragment
def _render_seguro_period_adjustment() -> None:
    with st.expander("Ajustar seguros para 10/2025 a 10/2026", expanded=False):
        try:
            df = backend.load_pedagio()
        except Exception as exc:
            st.error("Não foi possível carregar os seguros para prever a alteração.")
            st.exception(exc)
            return

        if df.empty or "Tipo" not in df.columns:
            st.info("Nenhum lançamento de pedágio/extra encontrado.")
            return

        with st.expander("Definir valor de seguro por placa", expanded=False):
            plate_map = _registered_plate_map()
            seguro_df = df[df["Tipo"].astype("string").fillna("").map(clean_text).eq("Seguro")].copy()
            current_values: dict[tuple[str, str], float] = {}
            if not seguro_df.empty and "PLACA" in seguro_df.columns and "Custo" in seguro_df.columns:
                group_columns = ["PLACA"]
                if "Categoria" in seguro_df.columns:
                    group_columns.append("Categoria")
                for keys, group in seguro_df.groupby(group_columns, dropna=False):
                    if not isinstance(keys, tuple):
                        keys = (keys,)
                    key_map = dict(zip(group_columns, keys))
                    placa = clean_text(key_map.get("PLACA")).strip().upper()
                    categoria = clean_text(key_map.get("Categoria") or plate_map.get(placa, "Transporte")).strip() or "Transporte"
                    if not placa:
                        continue
                    if "Mes" in group.columns:
                        monthly = pd.to_numeric(group.get("Custo"), errors="coerce").groupby(group["Mes"].astype("string").fillna("")).sum()
                        value = float(monthly.mean()) if len(monthly) > 1 else float(monthly.sum())
                    else:
                        value = float(pd.to_numeric(group.get("Custo"), errors="coerce").sum())
                    current_values[(placa, categoria)] = value

            editor_rows = []
            used_keys = set()
            for placa, categoria in plate_map.items():
                key = (placa, categoria)
                used_keys.add(key)
                editor_rows.append({"PLACA": placa, "Categoria": categoria, "Valor seguro": round(current_values.get(key, 0.0), 2)})
            for (placa, categoria), value in sorted(current_values.items()):
                if (placa, categoria) not in used_keys:
                    editor_rows.append({"PLACA": placa, "Categoria": categoria, "Valor seguro": round(value, 2)})

            if not editor_rows:
                st.info("Cadastre placas antes de definir os seguros.")
            else:
                st.caption("Preencha o valor de seguro de cada placa. Ao salvar, os seguros antigos de 10/2025 a 10/2026 serão substituídos por estes valores.")
                edited = st.data_editor(
                    pd.DataFrame(editor_rows),
                    width="stretch",
                    hide_index=True,
                    disabled=["PLACA", "Categoria"],
                    column_config={
                        "Valor seguro": st.column_config.NumberColumn("Valor seguro", min_value=0.0, step=1.0, format="R$ %.2f"),
                    },
                    key="cad_ped_seguro_placa_editor",
                )
                total_editor = float(pd.to_numeric(edited.get("Valor seguro"), errors="coerce").fillna(0).sum())
                st.info(f"Total informado por placa: {fmt_brl(total_editor)}.")
                confirm_values = st.checkbox(
                    "Confirmo que quero substituir os seguros do período pelos valores acima, por placa.",
                    key="cad_ped_seguro_placa_confirm",
                )
                if st.button(
                    "Salvar seguros por placa",
                    type="primary",
                    width="stretch",
                    disabled=not confirm_values,
                    key="cad_ped_seguro_placa_save",
                ):
                    records = []
                    for row in edited.to_dict("records"):
                        value = float(pd.to_numeric(pd.Series([row.get("Valor seguro")]), errors="coerce").fillna(0).iloc[0])
                        if value <= 0:
                            continue
                        records.append({"PLACA": row.get("PLACA"), "Categoria": row.get("Categoria"), "Custo": value})
                    try:
                        result = backend.replace_pedagio_seguros_por_placa(records, "2025-10", "2026-10")
                    except Exception as exc:
                        st.error("Não foi possível salvar os seguros por placa no Neon.")
                        st.exception(exc)
                        return
                    clear_cached_reads()
                    _reset_dataset_editor("cad_ped_table")
                    st.session_state["cad_ped_table_last_success"] = (
                        f"Seguros recriados por placa: {result.get('plates', 0)} placa(s), {result.get('inserted', 0)} lançamento(s)."
                    )
                    st.rerun()

        type_options = unique_filter_options(df["Tipo"].astype("string").fillna("").map(clean_text).tolist())
        month_options = unique_filter_options(df["Mes"].astype("string").fillna("").tolist()) if "Mes" in df.columns else []
        default_types = ["Seguro"] if "Seguro" in type_options else []
        selected_types = st.multiselect(
            "Tipo atual dos lançamentos que devem virar seguro",
            type_options,
            default=default_types,
            key="cad_ped_seguro_period_source_types",
        )
        selected_months = st.multiselect(
            "Meses atuais desses lançamentos",
            month_options,
            default=[],
            placeholder="Todos os meses",
            key="cad_ped_seguro_period_source_months",
        )

        candidates = df.copy()
        if selected_types:
            candidates = candidates[candidates["Tipo"].astype("string").fillna("").map(clean_text).isin(selected_types)]
        else:
            candidates = candidates.iloc[0:0]
        if selected_months and "Mes" in candidates.columns:
            candidates = candidates[candidates["Mes"].astype("string").fillna("").isin(selected_months)]

        total = int(candidates.shape[0])
        plate_count = (
            int(candidates["PLACA"].astype("string").fillna("").str.strip().replace("", pd.NA).dropna().nunique())
            if total and "PLACA" in candidates.columns
            else 0
        )
        total_value = float(pd.to_numeric(candidates.get("Custo"), errors="coerce").sum()) if total and "Custo" in candidates.columns else 0.0
        st.info(
            f"Seleção atual: {total} lançamento(s), {plate_count} placa(s), total {fmt_brl(total_value)}. "
            "Ao confirmar, eles serão somados por placa e mensalizados de 2025-10 até 2026-10 sem misturar valores entre placas."
        )
        if total:
            preview_columns = [column for column in ["Data", "Mes", "PLACA", "Categoria", "Tipo", "Custo"] if column in candidates.columns]
            st.dataframe(candidates[preview_columns].head(30), width="stretch", hide_index=True)
        confirm = st.checkbox(
            "Confirmo que a seleção acima deve virar seguro mensal de 2025-10 a 2026-10, calculado por placa.",
            key="cad_ped_seguro_period_confirm",
        )
        if st.button(
            "Ajustar seguros",
            type="primary",
            width="stretch",
            disabled=not confirm or total == 0,
            key="cad_ped_seguro_period_apply",
        ):
            try:
                result = backend.redistribute_pedagio_seguros_period(
                    "2025-10",
                    "2026-10",
                    source_tipos=selected_types,
                    source_meses=selected_months,
                )
            except Exception as exc:
                st.error("Não foi possível ajustar os seguros no Neon.")
                st.exception(exc)
                return
            clear_cached_reads()
            _reset_dataset_editor("cad_ped_table")
            st.session_state["cad_ped_table_last_success"] = (
                f"{result.get('deleted', 0)} lançamento(s) original(is) de {result.get('plates', 0)} placa(s) viraram {result.get('updated', 0)} lançamento(s) mensais de seguro por placa."
            )
            st.rerun()


@st.fragment
def _render_pedagio_reset_options() -> None:
    with st.expander("Zerar Pedágio/Extras por mês", expanded=False):
        st.warning(
            "Essa ação apaga todos os lançamentos de pedágio, extras, táxi, IPVA e seguros do mês escolhido. "
            "O gráfico Gasto mensal não inclui lançamentos da área Vex; esses valores aparecem separados abaixo."
        )

        try:
            df_preview = backend.load_pedagio()
        except Exception as exc:
            st.info("Não foi possível carregar os lançamentos para selecionar um mês.")
            st.caption(str(exc))
            df_preview = pd.DataFrame()

        month_options = _sheet_export_month_options(df_preview)
        if not month_options:
            st.caption("Nenhum mês cadastrado para zerar.")
        else:
            current_month = date.today().strftime("%Y-%m")
            default_index = month_options.index(current_month) if current_month in month_options else 0
            selected_month = st.selectbox(
                "Mês para zerar",
                month_options,
                index=default_index,
                format_func=month_filter_label,
                key="cad_ped_reset_month",
            )

            month_values = df_preview["Mes"].astype("string").fillna("").str.strip()
            selected_rows = df_preview.loc[month_values.eq(selected_month)]
            selected_count = int(selected_rows.shape[0])
            selected_total = float(pd.to_numeric(selected_rows.get("Custo"), errors="coerce").sum())

            chart_rows = selected_rows.copy()
            if "Categoria" in chart_rows.columns:
                category_values = chart_rows["Categoria"].astype("string").fillna("").map(clean_text).str.casefold()
                chart_rows = chart_rows.loc[category_values.ne("vex")]
            chart_count = int(chart_rows.shape[0])
            chart_total = float(pd.to_numeric(chart_rows.get("Custo"), errors="coerce").sum())
            additional_count = selected_count - chart_count
            additional_total = selected_total - chart_total

            selected_label = month_filter_label(selected_month)
            st.caption(
                f"{selected_label}: o gráfico Gasto mensal mostra {chart_count} lançamento(s), total {fmt_brl(chart_total)}."
            )
            if additional_count:
                st.caption(
                    f"Também serão apagados {additional_count} lançamento(s) da área Vex, "
                    f"total {fmt_brl(additional_total)}. Total completo a apagar: {fmt_brl(selected_total)}."
                )

            confirmar_mes = st.checkbox(
                f"Confirmo que quero apagar todos os lançamentos de Pedágio/Extras de {selected_label}.",
                key=f"cad_ped_reset_month_confirm_{selected_month}",
            )
            if st.button(
                f"Zerar Pedágio/Extras de {selected_label}",
                type="primary",
                width="stretch",
                disabled=not confirmar_mes or selected_count == 0,
                key=f"cad_ped_reset_month_button_{selected_month}",
            ):
                try:
                    deleted = backend.delete_dashboard_month("pedagio", selected_month)
                except Exception as exc:
                    st.error(f"Não foi possível zerar Pedágio/Extras de {selected_label} no Neon.")
                    st.exception(exc)
                    return
                _clear_pedagio_last_import()
                _reset_dataset_editor("cad_ped_table")
                clear_cached_reads()
                st.success(f"{deleted} lançamento(s) de Pedágio/Extras apagado(s) de {selected_label}.")
                st.rerun()

    with st.expander("Zerar todo Pedágio/Extras", expanded=False):
        st.warning("Essa ação apaga todos os lançamentos de pedágio, extras, táxi, IPVA e seguros. Use somente se for recadastrar tudo manualmente.")
        count = None
        try:
            df_preview = backend.load_pedagio()
            count = int(df_preview.shape[0])
        except Exception as exc:
            st.caption(f"Não foi possível contar os lançamentos antes de apagar: {exc}")
        if count is not None:
            st.caption(f"Total atual: {count} lançamento(s).")
        confirmar = st.checkbox("Confirmo que quero apagar toda a tabela de Pedágio/Extras.", key="cad_ped_reset_all_confirm")
        if st.button("Zerar todo Pedágio/Extras", type="primary", width="stretch", disabled=not confirmar, key="cad_ped_reset_all_button"):
            try:
                deleted = backend.delete_dashboard_all("pedagio")
            except Exception as exc:
                st.error("Não foi possível zerar Pedágio/Extras no Neon.")
                st.exception(exc)
                return
            _clear_pedagio_last_import()
            _reset_dataset_editor("cad_ped_table")
            clear_cached_reads()
            st.success(f"{deleted} lançamento(s) de Pedágio/Extras apagado(s).")
            st.rerun()


def _render_route_pdf_import(plate_map: dict[str, str]) -> None:
    st.markdown("### Importar rotas em grande escala por PDF")
    st.caption(
        "Cada PDF cria ou atualiza uma rota independente. Cabeçalho, carga, placa, motorista, veículo, "
        "peso, clientes, pedidos, cidades, endereços, vendedores, valores e demais textos encontrados são registrados. "
        "O peso usado na rota é sempre a soma dos pesos dos pedidos. Nada desta importação é lançado em Peso."
    )
    if message := st.session_state.pop("route_import_message", None):
        st.success(message)
    uploaded_files = st.file_uploader(
        "Selecione os manifestos de rota",
        type=["pdf"],
        accept_multiple_files=True,
        key="cad_rotas_pdf_files",
        help="Você pode selecionar muitos PDFs de uma vez. Reenviar o mesmo manifesto não duplica a rota.",
    )
    if not uploaded_files:
        st.info("Envie um ou mais PDFs para conferir a prévia antes de importar.")
        return

    parsed_routes: list[dict] = []
    parsed_deliveries: list[dict] = []
    parse_errors: list[str] = []
    parse_warnings: list[str] = []
    with st.spinner("Lendo os manifestos..."):
        for uploaded in uploaded_files:
            try:
                route, deliveries, warnings = parse_route_pdf(uploaded.getvalue(), uploaded.name, plate_map)
                parsed_routes.append(route)
                parsed_deliveries.extend(deliveries)
                parse_warnings.extend(f"{uploaded.name}: {warning}" for warning in warnings)
            except Exception as exc:
                parse_errors.append(f"{uploaded.name}: {exc}")

    if parse_errors:
        st.error("Alguns arquivos não puderam ser lidos:\n- " + "\n- ".join(parse_errors))
    for warning in parse_warnings:
        st.warning(warning)
    if not parsed_routes:
        return

    route_preview_columns = [
        "Arquivo", "Previsao", "Rota", "Carga", "PLACA", "Motorista", "Veiculo",
        "Peso Carga", "Peso Manifesto", "Entregas", "Status",
    ]
    st.markdown("#### Prévia das rotas")
    st.dataframe(
        pd.DataFrame(parsed_routes)[route_preview_columns],
        width="stretch",
        hide_index=True,
        column_config={
            "Previsao": st.column_config.DatetimeColumn("Previsão", format="DD/MM/YYYY"),
            "Peso Carga": _number_col("Soma dos pedidos (kg)", format="%.3f"),
            "Peso Manifesto": _number_col("Peso informado no PDF (kg)", format="%.3f"),
        },
    )
    with st.expander(f"Ver {len(parsed_deliveries)} entrega(s) extraída(s)"):
        delivery_preview = pd.DataFrame(parsed_deliveries)
        visible = [
            "Carga", "Documento", "Cliente Codigo", "Cliente", "Pedido", "Vendedor", "Ordem",
            "Carrinho", "Cidade", "Endereco", "Peso Pedido", "Valor Nota", "Forma Recebimento",
            "Valor Recebimento", "Corte", "Pagina",
        ]
        st.dataframe(
            delivery_preview[visible] if not delivery_preview.empty else delivery_preview,
            width="stretch",
            hide_index=True,
        )

    if st.button(
        f"Importar {len(parsed_routes)} rota(s) e {len(parsed_deliveries)} entrega(s)",
        type="primary",
        width="stretch",
        key="cad_rotas_pdf_import",
    ):
        try:
            result = backend.import_route_manifests(parsed_routes, parsed_deliveries)
        except Exception as exc:
            st.error("Não foi possível importar as rotas no Neon.")
            st.exception(exc)
            return
        clear_cached_reads()
        freighter_count = int(result.get("freteiros_concluidos", 0))
        freighter_message = (
            f" {freighter_count} rota(s) de freteiro foram concluídas automaticamente, sem KM."
            if freighter_count
            else ""
        )
        st.session_state["route_import_message"] = (
            f"Importação concluída: {result['rotas']} rota(s) e {result['entregas']} entrega(s) registradas."
            f"{freighter_message}"
        )
        st.rerun()


def _route_row_datetime(row: pd.Series, column: str, fallback: datetime) -> datetime:
    value = pd.to_datetime(row.get(column), errors="coerce")
    if pd.isna(value):
        return fallback
    return value.to_pydatetime()


def _route_journey_defaults(row: pd.Series) -> dict[date, tuple[datetime_time, datetime_time]]:
    raw = row.get("Jornadas")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    try:
        journeys = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    defaults: dict[date, tuple[datetime_time, datetime_time]] = {}
    for journey in journeys if isinstance(journeys, list) else []:
        start = pd.to_datetime(journey.get("saida"), errors="coerce")
        stop = pd.to_datetime(journey.get("parada"), errors="coerce")
        if pd.notna(start) and pd.notna(stop):
            defaults[start.date()] = (
                start.time().replace(second=0, microsecond=0),
                stop.time().replace(second=0, microsecond=0),
            )
    return defaults


def _previous_available_route_id(
    ordered_ids: list[str],
    current_id: str,
    completed_ids: set[str],
) -> str | None:
    try:
        current_index = ordered_ids.index(current_id)
    except ValueError:
        current_index = 0
    previous_ids = reversed(ordered_ids[:current_index])
    following_ids = ordered_ids[current_index + 1 :]
    return next(
        (route_id for route_id in [*previous_ids, *following_ids] if route_id not in completed_ids),
        None,
    )


def _render_route_completion(plate_map: dict[str, str]) -> None:
    st.markdown("### Finalizar dados operacionais da rota")
    st.caption(
        "Complete a saída real e o retorno. O KM é obrigatório para a frota própria. As rotas de freteiros são "
        "concluídas automaticamente, sem KM, usando 07:00–17:00 quando o PDF não informa horários. "
        "Esses campos alimentam o cálculo de duração, dias e os rankings de motorista, placa e rota."
    )
    auto_complete_key = "route_freighters_auto_completed_v1"
    auto_result = {"updated": 0}
    if not st.session_state.get(auto_complete_key, False):
        try:
            auto_result = backend.auto_complete_freighter_routes()
        except Exception as exc:
            st.error(f"Não foi possível concluir automaticamente as rotas de freteiros: {exc}")
        finally:
            # A importação já conclui novos freteiros. Esta varredura existe
            # apenas para registros antigos e não precisa rodar a cada rerun.
            st.session_state[auto_complete_key] = True
    auto_completed = int(auto_result.get("updated", 0))
    if auto_completed:
        clear_cached_reads()
        st.success(
            f"{auto_completed} rota(s) de freteiro foram concluídas automaticamente com os horários padrão e sem KM."
        )
    try:
        routes = backend.load_rotas()
    except Exception as exc:
        st.error("Não foi possível carregar as rotas importadas.")
        st.exception(exc)
        return
    if routes.empty:
        st.info("Importe o primeiro manifesto para liberar o preenchimento operacional.")
        return

    pending_count = int(routes["Status"].astype("string").fillna("").str.casefold().eq("pendente").sum())
    completed_count = max(int(routes["Rota ID"].nunique()) - pending_count, 0)
    pending_cols = st.columns(3)
    pending_cols[0].metric("Rotas pendentes", fmt_num(pending_count))
    pending_cols[1].metric("Rotas concluídas", fmt_num(completed_count))
    pending_cols[2].metric("Total importado", fmt_num(routes["Rota ID"].nunique()))
    completion_message = st.session_state.pop("route_completion_message", "")
    if completion_message:
        st.success(completion_message)
    if pending_count:
        st.warning(f"Ainda faltam preencher {pending_count} rota(s).")
    else:
        st.success("Todas as rotas importadas foram concluídas.")

    route_mode = st.radio(
        "Área de preenchimento",
        ["Preencher pendentes", "Editar concluídas"],
        horizontal=True,
        label_visibility="collapsed",
        key="route_completion_mode",
    )
    editing_completed = route_mode == "Editar concluídas"
    all_routes = routes.copy()
    status_values = routes["Status"].astype("string").fillna("").str.strip().str.casefold()
    target_mask = status_values.str.startswith("conclu") if editing_completed else status_values.eq("pendente")
    routes = routes.loc[target_mask].copy()
    if routes.empty:
        if editing_completed:
            st.info("Ainda não há rotas concluídas para editar.")
        else:
            st.info("Não há rotas pendentes para preencher. Use a aba Editar concluídas para fazer correções.")
        return

    if editing_completed:
        routes = routes.sort_values(
            ["Atualizado Em", "Data", "Rota"],
            ascending=[False, False, True],
            na_position="last",
        ).reset_index(drop=True)
    else:
        routes = routes.sort_values(["Data", "Rota"], ascending=[False, True]).reset_index(drop=True)
    label_map: dict[str, str] = {}
    for _, row in routes.iterrows():
        route_id = clean_text(row.get("Rota ID"))
        date_value = pd.to_datetime(row.get("Data"), errors="coerce")
        date_label = date_value.strftime("%d/%m/%Y") if pd.notna(date_value) else "sem data"
        label_map[route_id] = (
            f"{clean_text(row.get('Status'))} · {date_label} · {clean_text(row.get('Rota'))} · "
            f"{clean_text(row.get('PLACA'))} · carga {clean_text(row.get('Carga'))}"
        )
    selector_key = "cad_route_edit_id" if editing_completed else "cad_route_complete_id"
    requested_route_id = st.session_state.pop("route_completion_requested_id", None)
    if requested_route_id in label_map:
        st.session_state[selector_key] = requested_route_id
    if st.session_state.get(selector_key) not in label_map:
        st.session_state.pop(selector_key, None)
    selected_id = st.selectbox(
        "Rota concluída para editar" if editing_completed else "Rota para preencher",
        list(label_map),
        format_func=lambda value: label_map.get(value, value),
        key=selector_key,
    )
    row = routes.loc[routes["Rota ID"].astype("string") == selected_id].iloc[0]
    base_date = pd.to_datetime(row.get("Previsao"), errors="coerce")
    if pd.isna(base_date):
        base_date = pd.to_datetime(row.get("Data"), errors="coerce")
    if pd.isna(base_date):
        base_date = pd.Timestamp.now()
    departure_default = _route_row_datetime(row, "Saida", base_date.replace(hour=7, minute=0).to_pydatetime())
    return_default = _route_row_datetime(row, "Retorno", departure_default + timedelta(hours=10))
    current_plate = clean_text(row.get("PLACA")).upper()
    plate_options = sorted(set([*plate_map.keys(), current_plate]) - {""})

    with st.container(border=True, key=f"route_complete_container_{selected_id}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            plate = st.selectbox(
                "Placa",
                plate_options,
                index=plate_options.index(current_plate) if current_plate in plate_options else 0,
                key=f"route_plate_{selected_id}",
            )
            driver = st.text_input(
                "Motorista",
                value=clean_text(row.get("Motorista")),
                key=f"route_driver_{selected_id}",
            )
            selected_category = plate_map.get(plate, clean_text(row.get("Categoria") or "Transporte"))
            is_freighter = clean_text(selected_category).strip().lower() == "freteiro"
            st.caption(f"Categoria da placa: {selected_category}")
        with c2:
            departure_date = st.date_input(
                "Data de saída",
                value=departure_default.date(),
                key=f"route_departure_date_{selected_id}",
            )
        with c3:
            return_date = st.date_input(
                "Data de retorno",
                value=return_default.date(),
                key=f"route_return_date_{selected_id}",
            )

        journey_payload: list[dict] = []
        schedule_valid = True
        route_day_count = (return_date - departure_date).days + 1
        if route_day_count <= 0:
            st.error("A data de retorno não pode ser anterior à data de saída.")
            schedule_valid = False
        elif route_day_count > 31:
            st.error("A rota pode ter no máximo 31 dias para o preenchimento das jornadas.")
            schedule_valid = False
        else:
            stored_journeys = _route_journey_defaults(row)
            st.markdown("**Saídas e paradas por dia**")
            st.caption(
                "Informe somente o período trabalhado em cada dia. O intervalo entre a parada de um dia e a "
                "saída do dia seguinte não será contado como hora em operação."
            )
            total_operation_hours = 0.0
            for day_index in range(route_day_count):
                journey_date = departure_date + timedelta(days=day_index)
                stored_times = stored_journeys.get(journey_date)
                default_start = (
                    stored_times[0]
                    if stored_times
                    else departure_default.time().replace(second=0, microsecond=0)
                    if day_index == 0
                    else datetime_time(7, 0)
                )
                default_stop = (
                    stored_times[1]
                    if stored_times
                    else return_default.time().replace(second=0, microsecond=0)
                    if day_index == route_day_count - 1
                    else datetime_time(17, 0)
                )
                day_col, start_col, stop_col = st.columns([1.2, 1, 1])
                day_col.markdown(f"**Dia {day_index + 1}**  \n{journey_date.strftime('%d/%m/%Y')}")
                with start_col:
                    day_start = st.time_input(
                        f"Saída · dia {day_index + 1}",
                        value=default_start,
                        key=f"route_journey_start_{selected_id}_{journey_date.isoformat()}",
                    )
                with stop_col:
                    day_stop = st.time_input(
                        f"Parada · dia {day_index + 1}",
                        value=default_stop,
                        key=f"route_journey_stop_{selected_id}_{journey_date.isoformat()}",
                    )
                start_dt = datetime.combine(journey_date, day_start)
                stop_dt = datetime.combine(journey_date, day_stop)
                if stop_dt <= start_dt:
                    st.error(f"No dia {day_index + 1}, a parada deve ser posterior à saída.")
                    schedule_valid = False
                else:
                    total_operation_hours += (stop_dt - start_dt).total_seconds() / 3600.0
                journey_payload.append(
                    {
                        "data": journey_date.isoformat(),
                        "saida": start_dt.isoformat(),
                        "parada": stop_dt.isoformat(),
                    }
                )
            first_route_start = pd.to_datetime(journey_payload[0]["saida"])
            final_route_stop = pd.to_datetime(journey_payload[-1]["parada"])
            total_trip_hours = max((final_route_stop - first_route_start).total_seconds() / 3600.0, 0.0)
            st.info(
                f"Resumo: {route_day_count} dia(s) · Tempo de viagem: {fmt_num(total_trip_hours, 2)} hora(s), "
                "incluindo as noites · Horas trabalhadas: "
                f"{fmt_num(total_operation_hours, 2)} hora(s), sem os intervalos noturnos."
            )

        route_dates = pd.to_datetime(all_routes["Data"], errors="coerce")
        if "Previsao" in all_routes.columns:
            route_dates = route_dates.fillna(pd.to_datetime(all_routes["Previsao"], errors="coerce"))
        same_plate_day = (
            all_routes["PLACA"].astype("string").fillna("").str.strip().str.upper().eq(plate.strip().upper())
            & route_dates.dt.date.eq(base_date.date())
        )
        matching_ids = set(all_routes.loc[same_plate_day, "Rota ID"].astype("string"))
        duplicate_count = len(matching_ids | {selected_id})
        if duplicate_count > 1:
            st.info(
                f"Esta placa aparece em {duplicate_count} rotas no dia {base_date.strftime('%d/%m/%Y')}. "
                "As mesmas saídas e paradas serão aplicadas a todas. O KM informado abaixo deve ser o total da "
                "placa no dia e será dividido igualmente entre essas rotas."
            )
        if is_freighter:
            km = None
            st.info(
                "Esta rota de freteiro já é salva automaticamente sem KM. Use o botão abaixo somente se quiser "
                "corrigir os horários, o motorista ou a observação."
            )
        else:
            grouped_km = pd.to_numeric(all_routes.loc[same_plate_day, "KM Rodados"], errors="coerce")
            stored_km = grouped_km.sum(min_count=1)
            if selected_id not in matching_ids:
                selected_km = pd.to_numeric(row.get("KM Rodados"), errors="coerce")
                if pd.notna(selected_km):
                    stored_km = (float(stored_km) if pd.notna(stored_km) else 0.0) + float(selected_km)
            km = st.number_input(
                "KM total da placa no dia" if duplicate_count > 1 else "KM feitos para realizar a rota",
                min_value=0.0,
                value=float(stored_km) if pd.notna(stored_km) else 0.0,
                step=1.0,
                format="%.1f",
                key=f"route_km_{selected_id}",
            )
        raw_observation = row.get("Observacao")
        observation_default = "" if pd.isna(raw_observation) else clean_text(raw_observation)
        observation = st.text_area(
            "Observação operacional",
            value=observation_default,
            key=f"route_observation_{selected_id}",
        )
        if editing_completed:
            submit_label = "Salvar alterações do freteiro" if is_freighter else "Salvar alterações da rota"
        else:
            submit_label = "Atualizar dados do freteiro" if is_freighter else "Salvar e concluir rota"
        submitted = st.button(
            submit_label,
            type="primary",
            width="stretch",
            disabled=not schedule_valid,
            key=f"route_submit_{selected_id}",
        )
        if submitted:
            try:
                first_departure = pd.to_datetime(journey_payload[0]["saida"]).to_pydatetime()
                final_stop = pd.to_datetime(journey_payload[-1]["parada"]).to_pydatetime()
                result = backend.update_route_operation(
                    selected_id,
                    saida=first_departure,
                    retorno=final_stop,
                    km_rodados=km,
                    placa=plate,
                    motorista=driver,
                    observacao=observation,
                    jornadas=journey_payload,
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                updated_count = int(result.get("updated", 1))
                if not editing_completed:
                    completed_ids = set(result.get("route_ids") or [selected_id])
                    next_route_id = _previous_available_route_id(
                        list(label_map),
                        selected_id,
                        completed_ids,
                    )
                    if next_route_id:
                        st.session_state["route_completion_requested_id"] = next_route_id
                if editing_completed:
                    message = (
                        f"Alterações salvas em {updated_count} rota(s) desta placa. Tempo de viagem: "
                        f"{fmt_num(result.get('tempo_viagem_horas'), 2)} hora(s); horas trabalhadas: "
                        f"{fmt_num(result.get('horas_operacao'), 2)} hora(s), em "
                        f"{fmt_num(result.get('dias_operacao'))} dia(s)."
                    )
                elif is_freighter and updated_count > 1:
                    message = (
                        f"{updated_count} rotas desta placa foram concluídas com o mesmo horário, sem KM por ser "
                        "freteiro. Duração, dias e rankings foram atualizados."
                    )
                elif is_freighter:
                    message = "Rota de freteiro concluída sem KM. Duração, dias e rankings foram atualizados."
                elif updated_count > 1:
                    message = (
                        f"{updated_count} rotas desta placa foram concluídas com as mesmas jornadas. "
                        f"Os {fmt_num(result.get('km_total'), 1)} km totais foram divididos igualmente: "
                        f"{fmt_num(result.get('km_per_route'), 1)} km em cada rota. "
                        f"Tempo de viagem: {fmt_num(result.get('tempo_viagem_horas'), 2)} hora(s); "
                        f"horas trabalhadas: {fmt_num(result.get('horas_operacao'), 2)} hora(s), em "
                        f"{fmt_num(result.get('dias_operacao'))} dia(s)."
                    )
                else:
                    message = (
                        f"Rota concluída em {fmt_num(result.get('dias_operacao'))} dia(s). Tempo de viagem: "
                        f"{fmt_num(result.get('tempo_viagem_horas'), 2)} hora(s); horas trabalhadas: "
                        f"{fmt_num(result.get('horas_operacao'), 2)} hora(s). KM e rankings foram atualizados."
                    )
                st.session_state["route_completion_message"] = message
                st.rerun()

    with st.expander("Ver todos os dados extraídos desta rota", expanded=False):
        route_display = row.to_frame(name="Valor").reset_index().rename(columns={"index": "Campo"})
        st.dataframe(route_display, width="stretch", hide_index=True)
        try:
            deliveries = backend.load_rota_entregas()
            deliveries = deliveries[deliveries["Rota ID"].astype("string") == selected_id]
        except Exception:
            deliveries = pd.DataFrame()
        st.markdown(f"**Entregas: {len(deliveries)}**")
        st.dataframe(deliveries, width="stretch", hide_index=True)


def _route_history_edit_value(column: str, value):
    if column in {"Saida", "Retorno"}:
        parsed = pd.to_datetime(value, errors="coerce")
        return parsed.isoformat() if pd.notna(parsed) else None
    if column == "KM Rodados":
        parsed = pd.to_numeric(value, errors="coerce")
        return round(float(parsed), 6) if pd.notna(parsed) and float(parsed) > 0 else None
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return clean_text(value).strip()


def _render_route_history(plate_map: dict[str, str]) -> None:
    st.markdown("### Histórico das últimas alterações")
    st.caption(
        "As rotas mais recentemente importadas ou alteradas aparecem primeiro. Edite os campos operacionais "
        "diretamente na planilha e clique em salvar. O status é recalculado automaticamente. Para uma rota de "
        "vários dias, use o formulário acima para informar separadamente a saída e a parada de cada dia."
    )
    try:
        routes = backend.load_rotas()
    except Exception as exc:
        st.error("Não foi possível carregar o histórico das rotas.")
        st.exception(exc)
        return
    if routes.empty:
        st.info("O histórico aparecerá depois da primeira importação.")
        return

    routes = routes.copy()
    updated_at = pd.to_datetime(routes.get("Atualizado Em"), errors="coerce", utc=True)
    imported_at = pd.to_datetime(routes.get("Importado Em"), errors="coerce", utc=True)
    routes["Última alteração"] = (
        updated_at.fillna(imported_at).dt.tz_convert(BR_TZ).dt.tz_localize(None)
    )
    routes["_Foi alterada"] = updated_at.notna()
    routes = routes.sort_values(
        ["Última alteração", "_Foi alterada", "Data", "Rota ID"],
        ascending=[False, False, False, False],
        na_position="last",
        kind="mergesort",
    ).reset_index(drop=True)

    limit_options: list[object] = [25, 50, 100, "Todas"]
    limit = st.selectbox(
        "Quantidade de alterações exibidas",
        limit_options,
        index=1,
        key="route_history_limit",
    )
    if limit != "Todas":
        routes = routes.head(int(limit)).copy()

    columns = [
        "Rota ID",
        "Última alteração",
        "Status",
        "Previsao",
        "Rota",
        "Carga",
        "PLACA",
        "Categoria",
        "Motorista",
        "Saida",
        "Retorno",
        "KM Rodados",
        "Observacao",
    ]
    history = routes[columns].copy()
    history["Observacao"] = history["Observacao"].astype("string").fillna("").replace("<NA>", "")
    latest_value = history["Última alteração"].max()
    history_token = hashlib.sha1(
        f"{len(history)}|{latest_value}|{APP_VERSION}".encode("utf-8")
    ).hexdigest()[:12]
    plate_options = sorted(set([*plate_map.keys(), *history["PLACA"].dropna().astype(str).tolist()]) - {""})
    edited = st.data_editor(
        history,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=["Rota ID", "Última alteração", "Status", "Previsao", "Rota", "Carga", "Categoria"],
        column_config={
            "Rota ID": st.column_config.TextColumn("ID"),
            "Última alteração": st.column_config.DatetimeColumn("Última alteração", format="DD/MM/YYYY HH:mm"),
            "Status": st.column_config.TextColumn("Status"),
            "Previsao": st.column_config.DatetimeColumn("Previsão", format="DD/MM/YYYY"),
            "Rota": st.column_config.TextColumn("Rota"),
            "Carga": st.column_config.TextColumn("Carga"),
            "PLACA": st.column_config.SelectboxColumn("Placa", options=plate_options, required=True),
            "Categoria": st.column_config.TextColumn("Categoria"),
            "Motorista": st.column_config.TextColumn("Motorista", required=True),
            "Saida": _datetime_col("Saída"),
            "Retorno": _datetime_col("Retorno"),
            "KM Rodados": _number_col("KM rodados", format="%.1f"),
            "Observacao": st.column_config.TextColumn("Observação"),
        },
        key=f"route_history_editor_{history_token}",
    )

    if st.button(
        "Salvar alterações da planilha",
        type="primary",
        width="stretch",
        key=f"route_history_save_{history_token}",
    ):
        editable_columns = ["PLACA", "Motorista", "Saida", "Retorno", "KM Rodados", "Observacao"]
        originals = {
            clean_text(row["Rota ID"]): row
            for _, row in history.iterrows()
        }
        changed_rows: list[dict] = []
        for _, edited_row in edited.iterrows():
            route_id = clean_text(edited_row.get("Rota ID"))
            original = originals.get(route_id)
            if original is None:
                continue
            changed = any(
                _route_history_edit_value(column, edited_row.get(column))
                != _route_history_edit_value(column, original.get(column))
                for column in editable_columns
            )
            if changed:
                changed_rows.append(
                    {
                        "Rota ID": route_id,
                        **{column: edited_row.get(column) for column in editable_columns},
                    }
                )
        if not changed_rows:
            st.info("Nenhuma alteração foi feita na planilha.")
        else:
            try:
                result = backend.update_route_history_rows(changed_rows)
            except Exception as exc:
                st.error(f"Não foi possível salvar o histórico: {exc}")
            else:
                clear_cached_reads()
                st.success(f"{result['updated']} rota(s) atualizada(s) pela planilha.")
                st.rerun()


def _render_route_registry(plate_map: dict[str, str]) -> None:
    with st.container(border=True):
        _render_route_pdf_import(plate_map)
    with st.container(border=True):
        _render_route_completion(plate_map)
    st.info("A pesquisa completa e os rankings ficam no dashboard Rotas, acessível pela página inicial.")
    with st.container(border=True):
        _render_route_history(plate_map)


def render_cadastro() -> None:
    topbar("JR DASHBOARD • Adicionar dados", back=True)
    enable_numeric_input_overwrite()
    with st.container(key="cadastro_shell"):
        _render_backup_panel()
        if st.session_state.get("cadastro_active_tab") not in CADASTRO_TABS:
            st.session_state["cadastro_active_tab"] = "Placas"
        with st.container(key="cadastro_tabs"):
            active_tab = st.radio(
                "Área de cadastro",
                CADASTRO_TABS,
                horizontal=True,
                label_visibility="collapsed",
                key="cadastro_active_tab",
            )
        plate_map = _registered_plate_map()

        if active_tab == "Placas":
            with st.container(border=True):
                st.markdown("#### Salário mensal total do Transporte")
                st.caption(
                    "Cadastre o valor total da folha salarial do Transporte em cada mês. "
                    "O ranking divide esse valor pelos dias trabalhados no mês e aplica o valor diário "
                    "à quantidade de dias distintos da rota selecionada."
                )
                with st.form("form_salario_transporte", clear_on_submit=True):
                    salary_col1, salary_col2, salary_col3 = st.columns([1.0, 1.2, 1.0])
                    with salary_col1:
                        salario_mes_data = st.date_input(
                            "Mês de referência",
                            value=date.today().replace(day=1),
                            key="cad_salario_transporte_mes",
                        )
                    with salary_col2:
                        salario_valor = st.number_input(
                            "Salário mensal total (R$)",
                            min_value=0.0,
                            step=100.0,
                            format="%.2f",
                            key="cad_salario_transporte_valor",
                        )
                    with salary_col3:
                        st.write("")
                        salario_submitted = st.form_submit_button(
                            "Salvar salário mensal",
                            type="primary",
                            width="stretch",
                        )
                    if salario_submitted:
                        _save_entry(
                            "salarios_transporte",
                            {
                                "Mes": _entry_month(salario_mes_data),
                                "Valor": salario_valor,
                            },
                            required=["Mes", "Valor"],
                            replace_keys=["Mes"],
                            success="Salário mensal do Transporte salvo.",
                        )

                _render_dataset_editor(
                    "salarios_transporte",
                    backend.load_salarios_transporte,
                    ["Mes", "Valor"],
                    ["Mes", "Valor"],
                    "cad_salarios_transporte_table",
                    {
                        "Mes": st.column_config.TextColumn(
                            "Mês",
                            help="Use o formato AAAA-MM.",
                        ),
                        "Valor": _money_col("Salário mensal total"),
                    },
                    ["Mes"],
                )

            with st.form("form_placas", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns([1.2, 1.0, 1.0, 1.0])
                with c1:
                    placa = st.text_input("Placa", placeholder="ABC1D23", key="cad_placa_nome").upper()
                with c2:
                    plate_text = clean_text(placa).upper()
                    default_categoria = "Estoque" if "ESTOQUE" in plate_text else ("Empilhadeira" if "EMPILHADEIRA" in plate_text else "Transporte")
                    if default_categoria in {"Empilhadeira", "Estoque"} and st.session_state.get("cad_placa_categoria", "Transporte") == "Transporte":
                        st.session_state["cad_placa_categoria"] = default_categoria
                    categoria = st.selectbox("Categoria", CATEGORY_OPTIONS, index=CATEGORY_OPTIONS.index(default_categoria), key="cad_placa_categoria")
                with c3:
                    diaria = st.number_input(
                        "Diária do freteiro (R$)",
                        min_value=0.0,
                        step=10.0,
                        format="%.2f",
                        key="cad_placa_diaria",
                        help="Esse valor será cobrado uma vez por dia em que a placa Freteiro aparecer nas entregas.",
                    )
                with c4:
                    st.write("")
                    submitted = st.form_submit_button("Cadastrar placa", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "placas",
                        {
                            "PLACA": placa,
                            "Categoria": categoria,
                            "Diaria": diaria if categoria == "Freteiro" else 0.0,
                        },
                        required=["PLACA", "Categoria"],
                        replace_keys=["PLACA"],
                        success="Placa cadastrada/atualizada.",
                    )

            plate_map = _registered_plate_map()
            plate_daily_map = _registered_plate_daily_map()
            if plate_map:
                editor_token = _plate_editor_token(plate_map, plate_daily_map)
                editor_nonce = st.session_state.get("cad_placas_editor_nonce", 0)
                editor_key = f"cad_placas_editor_{editor_token}_{editor_nonce}"
                _clear_stale_plate_editor_state(editor_key)
                table = pd.DataFrame(
                    [
                        {
                            "Placa atual": placa,
                            "Placa": placa,
                            "Categoria": categoria,
                            "Diaria (R$)": plate_daily_map.get(placa, 0.0),
                        }
                        for placa, categoria in plate_map.items()
                    ]
                )
                filtered_table = _filter_plate_table(table, editor_token)
                edited_plates = st.data_editor(
                    filtered_table,
                    width="stretch",
                    hide_index=True,
                    num_rows="dynamic",
                    disabled=["Placa atual"],
                    column_config={
                        "Placa atual": st.column_config.TextColumn("Placa atual"),
                        "Placa": st.column_config.TextColumn("Placa"),
                        "Categoria": st.column_config.SelectboxColumn(
                            "Categoria",
                            options=CATEGORY_OPTIONS,
                            required=True,
                        ),
                        "Diaria (R$)": st.column_config.NumberColumn(
                            "Diária (R$)",
                            min_value=0.0,
                            step=10.0,
                            format="R$ %.2f",
                            help="Usada somente nas placas da categoria Freteiro.",
                        ),
                    },
                    key=editor_key,
                )
                save_key = f"cad_placas_sheet_save_{editor_token}_{editor_nonce}"
                if st.button("Salvar tabela de placas", type="primary", width="stretch", key=save_key):
                    _save_plate_sheet(plate_map, edited_plates, plate_daily_map)
            else:
                st.info("Cadastre a primeira placa para liberar a edição.")

        if active_tab == "Rotas":
            _render_route_registry(plate_map)

        if active_tab == "Empilhadeiras":
            with st.form("form_empilhadeiras", clear_on_submit=True):
                c1, c2, c3 = st.columns([1.2, 1.0, 1.0])
                with c1:
                    empilhadeira = st.text_input("Nome da empilhadeira", placeholder="EMPILHADEIRA 01", key="cad_empilhadeira_nome").upper()
                with c2:
                    st.text_input("Categoria", value="Empilhadeira", disabled=True, key="cad_empilhadeira_categoria")
                with c3:
                    st.write("")
                    submitted = st.form_submit_button("Cadastrar empilhadeira", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "placas",
                        {"PLACA": empilhadeira, "Categoria": "Empilhadeira"},
                        required=["PLACA"],
                        replace_keys=["PLACA"],
                        success="Empilhadeira cadastrada/atualizada.",
                    )

            plate_map = _registered_plate_map()
            empilhadeira_options = [placa for placa, categoria in plate_map.items() if categoria == "Empilhadeira"]
            if not empilhadeira_options:
                st.info("Cadastre a primeira empilhadeira para liberar manutenção e marcador de horas.")
            else:
                st.markdown("#### Manutenção da empilhadeira")
                with st.form("form_empilhadeira_manutencao", clear_on_submit=True):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        data = st.date_input("Data", value=date.today(), key="cad_emp_manu_data")
                        placa = st.selectbox(
                            "Empilhadeira",
                            empilhadeira_options,
                            index=None,
                            placeholder="Selecione uma empilhadeira",
                            key="cad_emp_manu_placa",
                        )
                    with c2:
                        oficina = st.text_input("Oficina/serviço", key="cad_emp_manu_oficina")
                        st.text_input("Categoria", value="Empilhadeira", disabled=True, key="cad_emp_manu_categoria")
                    with c3:
                        custo = st.number_input("Custo", min_value=0.0, step=10.0, format="%.2f", key="cad_emp_manu_custo")
                        submitted = st.form_submit_button("Salvar manutenção", type="primary", width="stretch")
                    if submitted:
                        _save_entry(
                            "manutencao",
                            {
                                "Data": data,
                                "Mes": _entry_month(data),
                                "Custo": custo,
                                "PLACA": placa,
                                "OFICINA": oficina,
                                "Categoria": "Empilhadeira",
                            },
                            required=["Data", "PLACA", "OFICINA"],
                            success="Manutenção de empilhadeira salva.",
                        )

                st.markdown("#### Marcador de horas")
                with st.form("form_empilhadeira_horas", clear_on_submit=True):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        ano = st.number_input("Ano", min_value=2020, max_value=2100, value=CURRENT_YEAR, step=1, key="cad_emp_horas_ano")
                        mes = st.selectbox("Mês", list(range(1, 13)), index=date.today().month - 1, format_func=month_label, key="cad_emp_horas_mes")
                    with c2:
                        placa = st.selectbox(
                            "Empilhadeira",
                            empilhadeira_options,
                            index=None,
                            placeholder="Selecione uma empilhadeira",
                            key="cad_emp_horas_placa",
                        )
                    with c3:
                        horas = st.number_input("Horas do mês", min_value=0.0, step=1.0, format="%.1f", key="cad_emp_horas_total")
                        substituir = st.checkbox("Substituir se já existir", value=True, key="cad_emp_horas_replace")
                        submitted = st.form_submit_button("Salvar horas", type="primary", width="stretch")
                    if submitted:
                        _save_entry(
                            "empilhadeira_horas",
                            {"Mes": f"{int(ano)}-{int(mes):02d}", "PLACA": placa, "Horas": horas},
                            required=["Mes", "PLACA"],
                            replace_keys=["Mes", "PLACA"] if substituir else None,
                            success="Horas da empilhadeira salvas.",
                        )

                st.markdown("#### Empilhadeiras cadastradas")
                st.dataframe(
                    pd.DataFrame({"Empilhadeira": empilhadeira_options, "Categoria": ["Empilhadeira"] * len(empilhadeira_options)}),
                    width="stretch",
                    hide_index=True,
                )

                try:
                    manutencoes_emp = backend.load_manutencao()
                except Exception as exc:
                    st.error("Não foi possível carregar as manutenções de empilhadeiras.")
                    st.exception(exc)
                    manutencoes_emp = pd.DataFrame()
                if not manutencoes_emp.empty and "Categoria" in manutencoes_emp.columns:
                    manutencoes_emp = manutencoes_emp[
                        manutencoes_emp["Categoria"].astype("string").str.lower().fillna("") == "empilhadeira"
                    ].copy()
                st.markdown("#### Manutenções de empilhadeiras")
                st.dataframe(
                    manutencoes_emp[["Data", "Mes", "PLACA", "OFICINA", "Custo"]]
                    if not manutencoes_emp.empty
                    else pd.DataFrame(columns=["Data", "Mes", "PLACA", "OFICINA", "Custo"]),
                    width="stretch",
                    hide_index=True,
                )

                _render_dataset_editor(
                    "empilhadeira_horas",
                    backend.load_empilhadeira_horas,
                    ["Mes", "PLACA", "Horas"],
                    ["Mes", "PLACA"],
                    "cad_emp_horas_table",
                    {
                        "Mes": st.column_config.TextColumn("Mês"),
                        "PLACA": st.column_config.TextColumn("Empilhadeira"),
                        "Horas": _number_col("Horas"),
                    },
                    ["Mes", "PLACA"],
                )

        if active_tab == "Combustível":
            combustivel_options = _registered_text_options(backend.load_combustiveis, "Combustivel")
            posto_options = _registered_text_options(backend.load_postos, "POSTOS")
            _render_combustivel_sheet_import(plate_map)

            r1, r2 = st.columns(2)
            with r1:
                with st.form("form_cadastrar_combustivel_tipo", clear_on_submit=True):
                    novo_combustivel = st.text_input("Cadastrar combustível", placeholder="Diesel S10", key="cad_tipo_combustivel")
                    submit_combustivel = st.form_submit_button("Cadastrar combustível", type="primary", width="stretch")
                    if submit_combustivel:
                        if _save_text_registry("combustiveis", "Combustivel", novo_combustivel, "Combustível cadastrado."):
                            combustivel_options = _registered_text_options(backend.load_combustiveis, "Combustivel")
            with r2:
                with st.form("form_cadastrar_posto", clear_on_submit=True):
                    novo_posto = st.text_input("Cadastrar posto", placeholder="Posto JR", key="cad_posto_nome")
                    submit_posto = st.form_submit_button("Cadastrar posto", type="primary", width="stretch")
                    if submit_posto:
                        if _save_text_registry("postos", "POSTOS", novo_posto, "Posto cadastrado."):
                            posto_options = _registered_text_options(backend.load_postos, "POSTOS")

            if combustivel_options or posto_options:
                with st.expander("Ver combustíveis e postos cadastrados"):
                    l1, l2 = st.columns(2)
                    with l1:
                        st.dataframe(pd.DataFrame({"Combustível": combustivel_options}), width="stretch", hide_index=True)
                    with l2:
                        st.dataframe(pd.DataFrame({"Posto": posto_options}), width="stretch", hide_index=True)

            with st.form("form_combustivel", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_comb_data")
                    placa, categoria = _plate_fields("cad_comb", plate_map)
                with c2:
                    combustivel = _select_or_create_text(
                        "Combustível",
                        combustivel_options,
                        "cad_comb_combustivel",
                        "Cadastrar novo combustível",
                        "Novo combustível",
                        placeholder="Diesel S10",
                        preferred="Diesel S10",
                    )
                    posto = _select_or_create_text(
                        "Posto",
                        posto_options,
                        "cad_comb_posto",
                        "Cadastrar novo posto",
                        "Novo posto",
                        placeholder="Posto JR",
                        preferred="POSTO NICODEMOS",
                    )
                with c3:
                    litros = st.number_input("Litros", min_value=0.0, step=0.01, format="%.2f", key="cad_comb_litros")
                    custo = st.number_input("Custo total", min_value=0.0, step=0.01, format="%.2f", key="cad_comb_custo")
                    submitted = st.form_submit_button("Salvar combustível", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "combustivel",
                        {
                            "Data": data,
                            "Mes": _entry_month(data),
                            "Litros": litros,
                            "Custo": custo,
                            "Combustivel": combustivel,
                            "POSTOS": posto,
                            "PLACA": placa,
                            "Categoria": categoria,
                        },
                        required=["Data", "PLACA", "Combustivel", "POSTOS"],
                        success="Lançamento de combustível salvo.",
                    )
            _render_dataset_editor(
                "combustivel",
                backend.load_combustivel,
                ["Data", "Mes", "PLACA", "Categoria", "Combustivel", "POSTOS", "Litros", "Custo"],
                ["Data", "PLACA", "Combustivel", "POSTOS"],
                "cad_comb_table",
                {
                    "Data": _date_col(),
                    "Mes": st.column_config.TextColumn("Mês"),
                    "PLACA": st.column_config.TextColumn("Placa"),
                    "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS, required=True),
                    "Combustivel": st.column_config.TextColumn("Combustível"),
                    "POSTOS": st.column_config.TextColumn("Posto"),
                    "Litros": _number_col("Litros", step=0.01, format="%.2f"),
                    "Custo": _money_col("Custo"),
                },
                ["Mes", "PLACA", "Categoria", "Combustivel", "POSTOS"],
            )

        if active_tab == "KM mensal":
            _render_km_sheet_import()

            with st.form("form_km_mensal", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ano = st.number_input("Ano", min_value=2020, max_value=2100, value=CURRENT_YEAR, step=1, key="cad_km_ano")
                with c2:
                    mes = st.selectbox("Mês", list(range(1, 13)), index=date.today().month - 1, format_func=month_label, key="cad_km_mes")
                    placa, categoria = _plate_fields("cad_km", plate_map)
                with c3:
                    km = st.number_input("KM do mês", min_value=0.0, step=1.0, key="cad_km_total")
                    substituir = st.checkbox("Substituir se já existir", value=True, key="cad_km_replace")
                    submitted = st.form_submit_button("Salvar KM mensal", type="primary", width="stretch")
                if submitted:
                    if _save_registered_plate(placa, categoria):
                        _save_entry(
                            "combustivel_km",
                            {"Mes": f"{int(ano)}-{int(mes):02d}", "PLACA": placa, "Km Rodados": km},
                            required=["Mes", "PLACA"],
                            replace_keys=["Mes", "PLACA"] if substituir else None,
                            success="KM mensal salvo.",
                        )

            _render_dataset_editor(
                "combustivel_km",
                backend.load_combustivel_km,
                ["Mes", "PLACA", "Km Rodados"],
                ["Mes", "PLACA"],
                "cad_km_table",
                {
                    "Mes": st.column_config.TextColumn("Mês"),
                    "PLACA": st.column_config.TextColumn("Placa"),
                    "Km Rodados": _number_col("KM rodados"),
                },
                ["Mes", "PLACA"],
            )

        if active_tab == "Manutenção":
            with st.form("form_manutencao", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_manu_data")
                    placa, categoria = _plate_fields("cad_manu", plate_map)
                with c2:
                    oficina = st.text_input("Oficina", key="cad_manu_oficina")
                with c3:
                    custo = st.number_input("Custo", min_value=0.0, step=10.0, format="%.2f", key="cad_manu_custo")
                    submitted = st.form_submit_button("Salvar manutenção", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "manutencao",
                        {
                            "Data": data,
                            "Mes": _entry_month(data),
                            "Custo": custo,
                            "PLACA": placa,
                            "OFICINA": oficina,
                            "Categoria": categoria,
                        },
                        required=["Data", "PLACA", "OFICINA"],
                        success="Lançamento de manutenção salvo.",
                        reset_table_key="cad_manu_table",
                    )

            _render_dataset_editor(
                "manutencao",
                backend.load_manutencao,
                ["Data", "Mes", "PLACA", "Categoria", "OFICINA", "Custo"],
                ["Data", "PLACA", "OFICINA"],
                "cad_manu_table",
                {
                    "Data": _date_col(),
                    "Mes": st.column_config.TextColumn("Mês"),
                    "PLACA": st.column_config.TextColumn("Placa"),
                    "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS, required=True),
                    "OFICINA": st.column_config.TextColumn("Oficina"),
                    "Custo": _money_col("Custo"),
                },
                ["Mes", "PLACA", "Categoria", "OFICINA"],
            )

        if active_tab == "Pneus":
            with st.form("form_pneus", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_pneu_data")
                    placa, categoria = _plate_fields("cad_pneu", plate_map)
                with c2:
                    fornecedor = st.text_input(
                        "Fornecedor",
                        placeholder="Digite o nome do fornecedor",
                        key="cad_pneu_fornecedor",
                    )
                    observacao = st.text_input("Observação", key="cad_pneu_observacao")
                with c3:
                    custo = st.number_input("Custo", min_value=0.0, step=10.0, format="%.2f", key="cad_pneu_custo")
                    submitted = st.form_submit_button("Salvar pneu", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "pneus",
                        {
                            "Data": data,
                            "Mes": _entry_month(data),
                            "PLACA": placa,
                            "Categoria": categoria,
                            "Fornecedor": fornecedor,
                            "Custo": custo,
                            "Observacao": observacao,
                        },
                        required=["Data", "Fornecedor", "Custo"],
                        success="Lançamento de pneu salvo.",
                    )

            _render_dataset_editor(
                "pneus",
                backend.load_pneus,
                ["Data", "Mes", "PLACA", "Categoria", "Fornecedor", "Custo", "Observacao"],
                ["Data", "Fornecedor"],
                "cad_pneu_table",
                {
                    "Data": _date_col(),
                    "Mes": st.column_config.TextColumn("Mês"),
                    "PLACA": st.column_config.TextColumn("Placa"),
                    "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS),
                    "Fornecedor": st.column_config.TextColumn("Fornecedor"),
                    "Custo": _money_col("Custo"),
                    "Observacao": st.column_config.TextColumn("Observação"),
                },
                ["Mes", "PLACA", "Categoria", "Fornecedor"],
            )

        if active_tab == "Hotéis":
            _render_hoteis_sheet_import()

            with st.form("form_hoteis", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_hotel_data")
                    cidade = st.text_input("Cidade", key="cad_hotel_cidade")
                    hotel = st.text_input("Hotel/Pousada", key="cad_hotel_nome")
                with c2:
                    motorista = st.text_input("Motorista", key="cad_hotel_motorista")
                    ajudante = st.text_input("Ajudante", key="cad_hotel_ajudante")
                    tipo = st.text_input("Tipo", placeholder="Hospedagem", key="cad_hotel_tipo")
                with c3:
                    dias = st.number_input("Dias", min_value=0.0, step=1.0, key="cad_hotel_dias")
                    valor = st.number_input("Valor", min_value=0.0, step=10.0, format="%.2f", key="cad_hotel_valor")
                    submitted = st.form_submit_button("Salvar hotel", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "hoteis",
                        {
                            "Data": data,
                            "Mes": _entry_month(data),
                            "Valor": valor,
                            "Dias": dias,
                            "Motorista": motorista,
                            "Ajudante": ajudante,
                            "Cidade": cidade,
                            "Hotel": hotel,
                            "Tipo": tipo,
                            "Categoria": "Transporte",
                        },
                        required=["Data", "Cidade", "Hotel"],
                        success="Reserva/hospedagem salva.",
                    )

            _render_dataset_editor(
                "hoteis",
                backend.load_hoteis_manual,
                ["Data", "Mes", "Cidade", "Hotel", "Tipo", "Motorista", "Ajudante", "Dias", "Valor", "Categoria"],
                ["Data", "Cidade", "Hotel"],
                "cad_hotel_table",
                {
                    "Data": _date_col(),
                    "Mes": st.column_config.TextColumn("Mês"),
                    "Cidade": st.column_config.TextColumn("Cidade"),
                    "Hotel": st.column_config.TextColumn("Hotel/Pousada"),
                    "Tipo": st.column_config.TextColumn("Tipo"),
                    "Motorista": st.column_config.TextColumn("Motorista"),
                    "Ajudante": st.column_config.TextColumn("Ajudante"),
                    "Dias": _number_col("Dias"),
                    "Valor": _money_col("Valor"),
                    "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS, required=True),
                },
                ["Mes", "Cidade", "Hotel", "Tipo", "Motorista", "Categoria"],
            )

        if active_tab == "Peso":
            _render_peso_sheet_import(plate_map)
            _render_peso_month_reset()

            with st.form("form_peso", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_peso_data")
                    placa, categoria = _plate_fields("cad_peso", plate_map)
                with c2:
                    cidade = st.text_input("Cidade", key="cad_peso_cidade")
                    rota = st.text_input("Rota", key="cad_peso_rota")
                with c3:
                    peso = st.number_input("Peso", min_value=0.0, step=1.0, format="%.3f", key="cad_peso_peso")
                    valor = st.number_input("Valor", min_value=0.0, step=10.0, format="%.2f", key="cad_peso_valor")
                    submitted = st.form_submit_button("Salvar peso", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "peso",
                        {
                            "Data": data,
                            "Mes": _entry_month(data),
                            "Cidade": cidade,
                            "Rota": rota,
                            "Peso": peso,
                            "Valor": valor,
                            "PLACA": placa,
                            "Categoria": categoria,
                        },
                        required=["Data", "PLACA", "Cidade", "Peso"],
                        success="Lancamento de peso salvo.",
                    )

            _render_dataset_editor(
                "peso",
                backend.load_peso,
                ["Data", "Mes", "Cidade", "Rota", "PLACA", "Categoria", "Peso", "Valor"],
                ["Data", "PLACA", "Cidade"],
                "cad_peso_table",
                {
                    "Data": _date_col(),
                    "Mes": st.column_config.TextColumn("Mês"),
                    "Cidade": st.column_config.TextColumn("Cidade"),
                    "Rota": st.column_config.TextColumn("Rota"),
                    "PLACA": st.column_config.TextColumn("Placa"),
                    "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS, required=True),
                    "Peso": _number_col("Peso"),
                    "Valor": _money_col("Valor"),
                },
                ["Mes", "Cidade", "Rota", "PLACA", "Categoria"],
            )

        if active_tab == "Velocidade":
            st.info(
                "Uma linha representa uma viagem. A velocidade media usa distancia dividida pelo tempo em movimento "
                "(duracao total menos o tempo parado). A meta em minutos alimenta o indicador de SLA."
            )
            _render_velocity_sheet_import(plate_map)

            with st.form("form_velocidade", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_vel_data")
                    identificador = st.text_input("Identificador da viagem", key="cad_vel_identificador")
                    placa, categoria = _plate_fields("cad_vel", plate_map)
                with c2:
                    motorista = st.text_input("Motorista", key="cad_vel_motorista")
                    rota = st.text_input("Rota", key="cad_vel_rota")
                    origem = st.text_input("Origem", key="cad_vel_origem")
                with c3:
                    destino = st.text_input("Destino", key="cad_vel_destino")
                    hora_saida = st.time_input("Hora de saida", value=datetime_time(8, 0), key="cad_vel_saida")
                    data_chegada = st.date_input("Data da chegada", value=data, key="cad_vel_chegada_data")
                with c4:
                    hora_chegada = st.time_input("Hora de chegada", value=datetime_time(10, 0), key="cad_vel_chegada")
                    distancia = st.number_input("Distancia (km)", min_value=0.0, step=1.0, format="%.2f", key="cad_vel_distancia")
                    tempo_parado = st.number_input("Tempo parado (min)", min_value=0.0, step=5.0, format="%.1f", key="cad_vel_parado")

                metric_cols = st.columns(4)
                with metric_cols[0]:
                    meta_minutos = st.number_input(
                        "Meta da viagem (min)",
                        min_value=0.0,
                        step=5.0,
                        format="%.1f",
                        help="Deixe zero quando nao houver meta de duracao.",
                        key="cad_vel_meta",
                    )
                with metric_cols[1]:
                    informar_telemetria = st.checkbox("Informar telemetria", key="cad_vel_telemetria")
                    velocidade_maxima = st.number_input(
                        "Velocidade maxima (km/h)",
                        min_value=0.0,
                        step=1.0,
                        format="%.1f",
                        disabled=not informar_telemetria,
                        key="cad_vel_maxima",
                    )
                with metric_cols[2]:
                    limite_kmh = st.number_input(
                        "Limite acompanhado (km/h)",
                        min_value=0.0,
                        step=1.0,
                        format="%.1f",
                        disabled=not informar_telemetria,
                        key="cad_vel_limite",
                    )
                with metric_cols[3]:
                    eventos_excesso = st.number_input(
                        "Eventos de excesso",
                        min_value=0,
                        step=1,
                        disabled=not informar_telemetria,
                        key="cad_vel_excessos",
                    )
                observacao = st.text_area("Observacao", key="cad_vel_observacao")
                submitted = st.form_submit_button("Salvar viagem", type="primary", width="stretch")

                if submitted:
                    saida = datetime.combine(data, hora_saida)
                    chegada = datetime.combine(data_chegada, hora_chegada)
                    duration_minutes = (chegada - saida).total_seconds() / 60.0
                    if not placa:
                        st.warning("Selecione ou cadastre uma placa.")
                    elif distancia <= 0:
                        st.warning("Informe uma distancia maior que zero.")
                    elif duration_minutes <= 0:
                        st.warning("A chegada deve ser posterior a saida.")
                    elif tempo_parado >= duration_minutes:
                        st.warning("O tempo parado deve ser menor que a duracao total da viagem.")
                    elif informar_telemetria and (velocidade_maxima <= 0 or limite_kmh <= 0):
                        st.warning("Preencha a velocidade maxima e o limite acompanhado para usar a telemetria.")
                    else:
                        _save_entry(
                            "velocidade",
                            {
                                "Data": data,
                                "Mes": _entry_month(data),
                                "Identificador": identificador,
                                "PLACA": placa,
                                "Categoria": categoria,
                                "Motorista": motorista,
                                "Rota": rota,
                                "Origem": origem,
                                "Destino": destino,
                                "Saida": saida,
                                "Chegada": chegada,
                                "Distancia Km": distancia,
                                "Tempo Parado Min": tempo_parado,
                                "Meta Minutos": meta_minutos if meta_minutos > 0 else None,
                                "Velocidade Maxima": velocidade_maxima if informar_telemetria else None,
                                "Limite KmH": limite_kmh if informar_telemetria else None,
                                "Eventos Excesso": eventos_excesso if informar_telemetria else None,
                                "Observacao": observacao,
                            },
                            required=["Data", "PLACA", "Saida", "Chegada", "Distancia Km"],
                            success="Viagem de velocidade salva.",
                            reset_table_key="cad_vel_table",
                        )

            velocity_columns = [source for source, _target in VELOCIDADE_EXPORT_COLUMNS]
            velocity_columns.insert(1, "Mes")
            velocity_columns.insert(4, "Categoria")
            _render_dataset_editor(
                "velocidade",
                backend.load_velocidade,
                velocity_columns,
                ["Data", "PLACA", "Saida", "Chegada", "Distancia Km"],
                "cad_vel_table",
                {
                    "Data": _date_col(),
                    "Mes": st.column_config.TextColumn("Mes"),
                    "Identificador": st.column_config.TextColumn("Identificador"),
                    "PLACA": st.column_config.TextColumn("Placa"),
                    "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS, required=True),
                    "Motorista": st.column_config.TextColumn("Motorista"),
                    "Rota": st.column_config.TextColumn("Rota"),
                    "Origem": st.column_config.TextColumn("Origem"),
                    "Destino": st.column_config.TextColumn("Destino"),
                    "Saida": _datetime_col("Saida"),
                    "Chegada": _datetime_col("Chegada"),
                    "Distancia Km": _number_col("Distancia (km)", step=0.1, format="%.2f"),
                    "Tempo Parado Min": _number_col("Tempo parado (min)", step=1.0, format="%.1f"),
                    "Meta Minutos": _number_col("Meta (min)", step=1.0, format="%.1f"),
                    "Velocidade Maxima": _number_col("Velocidade maxima", step=0.1, format="%.1f"),
                    "Limite KmH": _number_col("Limite (km/h)", step=0.1, format="%.1f"),
                    "Eventos Excesso": _number_col("Eventos de excesso", step=1.0, format="%.0f"),
                    "Observacao": st.column_config.TextColumn("Observacao"),
                },
                ["Mes", "Identificador", "PLACA", "Categoria", "Motorista", "Rota", "Origem", "Destino"],
            )

        if active_tab == "Pedágio/Extras":
            _render_pedagio_sheet_import(plate_map)
            _render_pedagio_reset_options()

            with st.form("form_pedagio", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c2:
                    tipo = st.selectbox("Tipo", PEDAGIO_TIPO_OPTIONS, key="cad_ped_tipo")
                plate_required = tipo not in PEDAGIO_OPTIONAL_PLATE_TYPES
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_ped_data")
                    if plate_required:
                        placa, categoria = _plate_fields("cad_ped", plate_map)
                    else:
                        st.text_input("Placa", value="Sem placa", disabled=True, key="cad_ped_no_plate")
                        st.text_input("Categoria da placa", value="Transporte", disabled=True, key="cad_ped_no_plate_categoria")
                        placa, categoria = None, "Transporte"
                with c3:
                    custo = st.number_input("Custo", min_value=0.0, step=10.0, format="%.2f", key="cad_ped_custo")
                    submitted = st.form_submit_button("Salvar pedágio/extra", type="primary", width="stretch")
                required = ["Data", "Tipo"] if not plate_required else ["Data", "PLACA", "Tipo"]
                if submitted:
                    _save_entry(
                        "pedagio",
                        {
                            "Data": data,
                            "Mes": _entry_month(data),
                            "PLACA": placa,
                            "Tipo": tipo,
                            "Custo": custo,
                            "Categoria": categoria,
                        },
                        required=required,
                        success="Lançamento de pedágio/extra salvo.",
                    )
            _render_seguro_period_adjustment()
            _render_dataset_editor(
                "pedagio",
                backend.load_pedagio,
                ["Data", "Mes", "PLACA", "Categoria", "Tipo", "Custo"],
                ["Data", "Tipo"],
                "cad_ped_table",
                {
                    "Data": _date_col(),
                    "Mes": st.column_config.TextColumn("Mês"),
                    "PLACA": st.column_config.TextColumn("Placa"),
                    "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS, required=True),
                    "Tipo": st.column_config.SelectboxColumn("Tipo", options=PEDAGIO_TIPO_OPTIONS, required=True),
                    "Custo": _money_col("Custo"),
                },
                ["Mes", "PLACA", "Categoria", "Tipo"],
            )

        if active_tab == "Aluguel de veículos":
            _render_aluguel_sheet_import()
            st.info("Os valores cadastrados aqui entram exclusivamente no dashboard Vex.")

            vex_plates = {placa for placa, categoria in plate_map.items() if categoria == "Vex"}
            try:
                aluguel_df = backend.load_aluguel_veiculos()
                if not aluguel_df.empty and "PLACA" in aluguel_df.columns:
                    vex_plates.update(
                        clean_text(value).strip().upper()
                        for value in aluguel_df["PLACA"].dropna().tolist()
                        if clean_text(value).strip()
                    )
            except Exception:
                pass
            vex_plates = sorted(vex_plates)
            with st.form("form_aluguel_veiculos", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    inicio = st.date_input("Início da locação", value=date.today(), key="cad_aluguel_inicio")
                    fim = st.date_input(
                        "Fim da locação",
                        value=_aluguel_one_cycle_end(date.today()),
                        key="cad_aluguel_fim",
                    )
                with c2:
                    vehicle_options = [*vex_plates, "Cadastrar novo veículo"]
                    selected_vehicle = st.selectbox(
                        "Placa/veículo",
                        vehicle_options,
                        index=None,
                        placeholder="Selecione ou cadastre o veículo",
                        key="cad_aluguel_placa_select",
                    )
                    if selected_vehicle == "Cadastrar novo veículo":
                        placa = st.text_input(
                            "Nova placa/identificação",
                            placeholder="ABC1D23",
                            key="cad_aluguel_placa_manual",
                        ).upper()
                    else:
                        placa = selected_vehicle or ""
                    fornecedor = st.text_input(
                        "Fornecedor/locadora",
                        placeholder="Nome da locadora",
                        key="cad_aluguel_fornecedor",
                    )
                with c3:
                    custo = st.number_input(
                        "Valor mensal",
                        min_value=0.0,
                        step=100.0,
                        format="%.2f",
                        key="cad_aluguel_custo",
                    )
                    observacao = st.text_input(
                        "Observação",
                        placeholder="Ex.: aluguel mensal",
                        key="cad_aluguel_observacao",
                    )
                cycles = _aluguel_cycle_dates(inicio, fim)
                if cycles:
                    st.caption(
                        f"{len(cycles)} mês(es) × {fmt_brl(custo)} = {fmt_brl(custo * len(cycles))} • "
                        "Categoria Vex."
                    )
                submitted = st.form_submit_button("Salvar mensalidades", type="primary", width="stretch")
                if submitted:
                    if not placa:
                        st.warning("Preencha a placa/veículo.")
                    elif fim < inicio:
                        st.warning("O fim da locação deve ser igual ou posterior ao início.")
                    else:
                        rows = _aluguel_period_rows(inicio, fim, placa, fornecedor, custo, observacao)
                        try:
                            with st.spinner("Salvando todas as mensalidades do período..."):
                                imported_rows, skipped_rows = backend.append_missing_dashboard_records(
                                    "aluguel_veiculos",
                                    rows,
                                    update_plate_registry=False,
                                )
                        except Exception as exc:
                            st.error("Não foi possível salvar as mensalidades no Neon.")
                            st.exception(exc)
                        else:
                            clear_cached_reads()
                            _clear_table_filter_state("cad_aluguel_table")
                            _reset_dataset_editor("cad_aluguel_table")
                            st.session_state["cad_aluguel_table_last_success"] = (
                                f"{len(imported_rows)} mensalidade(s) salva(s); "
                                f"{skipped_rows} já existente(s) mantida(s)."
                            )
                            st.rerun()

            _render_dataset_editor(
                "aluguel_veiculos",
                backend.load_aluguel_veiculos,
                ["Data", "Mes", "Inicio", "Fim", "PLACA", "Fornecedor", "Custo", "Observacao"],
                ["Data", "Inicio", "Fim", "PLACA", "Custo"],
                "cad_aluguel_table",
                {
                    "Data": _date_col("Início da mensalidade"),
                    "Mes": st.column_config.TextColumn("Mês"),
                    "Inicio": _date_col("Início da locação"),
                    "Fim": _date_col("Fim da locação"),
                    "PLACA": st.column_config.TextColumn("Placa/veículo"),
                    "Fornecedor": st.column_config.TextColumn("Fornecedor/locadora"),
                    "Custo": _money_col("Valor mensal"),
                    "Observacao": st.column_config.TextColumn("Observação"),
                },
                ["Mes", "Inicio", "Fim", "PLACA", "Fornecedor", "Observacao"],
            )


def render_combustivel() -> None:
    topbar("JR DASHBOARD • Combustível", back=False)
    seed = route_json("combustivel", {"ano": "Todos", "mes": ["Todos"]})
    if "comb_categoria" not in st.session_state and "Transporte" in (seed.get("segmentos", []) or []):
        st.session_state["comb_categoria"] = "Transporte"
    params, filter_state = filter_controls(
        "combustivel",
        extra_filters=[
            ("categoria", "Categoria", seed.get("segmentos", []) or []),
            ("placa", "Placa", seed.get("placas", []) or []),
            ("posto", "Posto", seed.get("postos", []) or []),
            ("combustivel", "Combustível", seed.get("combustiveis", []) or []),
        ],
        key_prefix="comb",
        all_data=seed,
    )
    data = route_json("combustivel", params)
    kpis = [
        ("total", "Total (R$)", fmt_brl(data.get("custo_total"))),
        ("media_mensal", "Média mensal (R$)", fmt_brl(data.get("media_mensal"))),
        ("km_total", "KM total", fmt_num(data.get("km_total"))),
        ("litros_total", "Total litros", fmt_num(data.get("litros_total"))),
        ("custo_km", "Custo médio por KM", fmt_brl(data.get("custo_por_km"))),
        ("media_kml", "Média KM/L", f"{fmt_num(data.get('km_por_litro'), 2)} km/L"),
        ("custo_litro", "Custo médio por litro", fmt_brl(data.get("custo_por_litro"))),
    ]
    include_year = params.get("ano") is None
    fallback_year = params.get("ano")
    mensal_labels, mensal_values = sorted_series(data.get("custo_mensal", {}), "Mes", "Custo", include_year=include_year, fallback_year=fallback_year)
    km_labels, km_values = sorted_series(data.get("km_mensal", {}), "Mes", "Km Rodados", include_year=include_year, fallback_year=fallback_year)
    litros_labels, litros_values = sorted_series(data.get("litros_mensal", {}), "Mes", "Litros", include_year=include_year, fallback_year=fallback_year)
    compare_selected = filter_state.get("_compare", [])
    compare_data = compare_bundle("combustivel", data, params, compare_selected)
    if compare_selected:
        kpis = compare_combined_kpis(compare_data) + color_kpis(kpis, "combustivel", section=_series_label("combustivel")) + compare_kpi_cards(compare_data[1:])
    monthly_fig = (
        multi_line_chart(compare_chart_series(compare_data, "monthly"), include_year=include_year, fallback_year=fallback_year)
        if compare_selected
        else yearly_month_line_chart(data.get("custo_mensal", {}), "Mes", "Custo", fallback_year=fallback_year)
        if include_year
        else line_chart(mensal_labels, mensal_values)
    )
    weekly_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "weekly"))
        if compare_selected
        else bar_chart(data.get("gasto_semana", {}).get("Dia", []), data.get("gasto_semana", {}).get("Custo", []))
    )
    plate_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "plate"), horizontal=True, sort_desc=True)
        if compare_selected
        else bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)
    )
    charts = [
        ("gasto_mes", "Gasto total por mês", monthly_fig),
        ("gasto_semana", "Gasto semanal (últimos 7 dias)", weekly_fig),
        ("gasto_posto", "Gasto por posto", pie_chart(data.get("gasto_por_posto", {}).get("POSTOS", []), data.get("gasto_por_posto", {}).get("Custo", []))),
        ("gasto_combustivel", "Gasto por combustível", pie_chart(data.get("gasto_por_combustivel", {}).get("Combustivel", []), data.get("gasto_por_combustivel", {}).get("Custo", []))),
        ("gasto_placa", "Gasto por placa", plate_fig),
        (
            "km_mes",
            "KM por mês",
            yearly_month_bar_chart(data.get("km_mensal", {}), "Mes", "Km Rodados", fallback_year=fallback_year, currency=False)
            if include_year
            else bar_chart(km_labels, km_values, currency=False, show_text=True),
        ),
        (
            "litros_mes",
            "Litros por mês",
            yearly_month_bar_chart(data.get("litros_mensal", {}), "Mes", "Litros", fallback_year=fallback_year, currency=False)
            if include_year
            else bar_chart(litros_labels, litros_values, currency=False, show_text=True),
        ),
    ]
    render_controlled_dashboard("comb", title="JR Dashboard - Combustível", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_manutencao() -> None:
    topbar("JR DASHBOARD • Manutenção", back=False)
    seed = route_json("manutencao", {"ano": "Todos", "mes": ["Todos"]})
    params, filter_state = filter_controls(
        "manutencao",
        extra_filters=[
            ("placa", "Placa", seed.get("placas", []) or []),
            ("oficina", "Oficina", seed.get("oficinas", []) or []),
            ("segmento", "Categoria", seed.get("segmentos", []) or []),
        ],
        key_prefix="manu",
        all_data=seed,
    )
    data = route_json("manutencao", params)
    kpis = [
        ("custo_total", "Custo total (R$)", fmt_brl(data.get("custo_total"))),
        ("servicos", "Serviços", fmt_num(data.get("total_servicos"))),
        ("ticket_medio", "Ticket médio", fmt_brl(data.get("media_servico"))),
        ("media_mensal", "Média mensal (R$)", fmt_brl(data.get("media_mensal"))),
    ]
    include_year = params.get("ano") is None
    mensal_labels, mensal_values = sorted_series(data.get("custo_mensal", {}), "Mes", "Custo", include_year=include_year, fallback_year=params.get("ano"))
    compare_selected = filter_state.get("_compare", [])
    compare_data = compare_bundle("manutencao", data, params, compare_selected)
    if compare_selected:
        kpis = compare_combined_kpis(compare_data) + color_kpis(kpis, "manutencao", section=_series_label("manutencao")) + compare_kpi_cards(compare_data[1:])
    monthly_fig = (
        multi_line_chart(compare_chart_series(compare_data, "monthly"), include_year=include_year, fallback_year=params.get("ano"))
        if compare_selected
        else yearly_month_line_chart(data.get("custo_mensal", {}), "Mes", "Custo", fallback_year=params.get("ano"))
        if include_year
        else line_chart(mensal_labels, mensal_values)
    )
    weekly_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "weekly"))
        if compare_selected
        else bar_chart(data.get("custo_semana", {}).get("Dia", []), data.get("custo_semana", {}).get("Custo", []))
    )
    plate_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "plate"), horizontal=True, sort_desc=True)
        if compare_selected
        else bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)
    )
    charts = [
        ("gasto_placa", "Gasto por placa", plate_fig),
        ("gasto_oficina", "Gasto por oficina", bar_chart(data.get("gasto_por_oficina", {}).get("OFICINA", []), data.get("gasto_por_oficina", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)),
        ("gasto_mensal", "Gasto mensal", monthly_fig),
        ("gasto_semana", "Gasto semanal (últimos 7 dias)", weekly_fig),
    ]
    render_controlled_dashboard("manu", title="JR Dashboard - Manutenção", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_hoteis() -> None:
    topbar("JR DASHBOARD • Reservas de Hotéis", back=False)
    seed = route_json("hoteis", {"ano": "Todos", "mes": ["Todos"]})
    params, filter_state = filter_controls(
        "hoteis",
        extra_filters=[
            ("segmento", "Categoria", seed.get("segmentos", []) or []),
            ("cidade", "Cidade", seed.get("cidades", []) or []),
            ("hotel", "Hotel/Pousada", seed.get("hoteis", []) or []),
        ],
        key_prefix="hotel",
        all_data=seed,
    )
    data = route_json("hoteis", params)
    kpis = [
        ("valor_total", "Valor total (R$)", fmt_brl(data.get("valor_total"))),
        ("reservas", "Reservas", fmt_num(data.get("reservas_total"))),
        ("reservas_nao_planejadas", "Reservas não planejadas", fmt_num(data.get("reservas_nao_planejadas"))),
        ("media_reserva", "Média por reserva", fmt_brl(data.get("valor_medio_reserva"))),
        ("media_mensal", "Média mensal", fmt_brl(data.get("media_mensal"))),
        ("sabados", "Gasto aos sábados (R$)", fmt_brl(data.get("valor_sabado"))),
        ("nao_planejado", "Gasto não planejado (R$)", fmt_brl(data.get("valor_nao_planejado"))),
    ]
    include_year = params.get("ano") is None
    mensal_labels, mensal_values = sorted_series(data.get("valor_mensal", {}), "Mes", "Valor", include_year=include_year, fallback_year=params.get("ano"))
    week = data.get("valor_semana", {})
    week_colors = []
    for is_unplanned in week.get("NaoPlanejada", []) or []:
        week_colors.append("#F59E0B" if is_unplanned else JR_BLUE)
    compare_selected = filter_state.get("_compare", [])
    compare_data = compare_bundle("hoteis", data, params, compare_selected)
    if compare_selected:
        kpis = compare_combined_kpis(compare_data) + color_kpis(kpis, "hoteis", section=_series_label("hoteis")) + compare_kpi_cards(compare_data[1:])
    monthly_fig = (
        multi_line_chart(compare_chart_series(compare_data, "monthly"), include_year=include_year, fallback_year=params.get("ano"))
        if compare_selected
        else yearly_month_line_chart(data.get("valor_mensal", {}), "Mes", "Valor", fallback_year=params.get("ano"))
        if include_year
        else line_chart(mensal_labels, mensal_values)
    )
    weekly_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "weekly"))
        if compare_selected
        else bar_chart(week.get("Dia", []), week.get("Valor", []), marker_colors=week_colors or None)
    )
    charts = [
        ("valor_mensal", "Valor mensal", monthly_fig),
        ("valor_semanal", "Valor semanal (últimos 7 dias)", weekly_fig),
        ("valor_cidade", "Valor por cidade", bar_chart(data.get("valor_por_cidade", {}).get("Cidade", []), data.get("valor_por_cidade", {}).get("Valor", []), horizontal=True, sort_desc=True, show_text=True)),
        ("valor_hotel", "Valor por hotel/pousada", bar_chart(data.get("valor_por_hotel", {}).get("Hotel", []), data.get("valor_por_hotel", {}).get("Valor", []), horizontal=True, sort_desc=True, show_text=True)),
    ]
    render_controlled_dashboard("hotel", title="JR Dashboard - Reservas de Hotéis", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_pedagio() -> None:
    topbar("JR DASHBOARD • Pedágio/Extras", back=False)
    seed = route_json("pedagio", {"ano": "Todos", "mes": ["Todos"]})
    params, filter_state = filter_controls(
        "pedagio",
        extra_filters=[
            ("placa", "Placa", seed.get("placas", []) or []),
            ("tipo", "Tipo", seed.get("tipos", []) or []),
            ("segmento", "Segmento", seed.get("segmentos", []) or []),
        ],
        key_prefix="ped",
        all_data=seed,
    )
    data = route_json("pedagio", params)
    kpis = [
        ("gasto_total", "Gasto total (R$)", fmt_brl(data.get("custo_total"))),
        ("media_mensal", "Média mensal (R$)", fmt_brl(data.get("media_mensal"))),
        ("gasto_pedagio", "Gasto pedágio", fmt_brl(data.get("gasto_pedagio"))),
        ("gasto_ipva", "Gasto IPVA", fmt_brl(data.get("gasto_ipva"))),
        ("gasto_seguro", "Gasto seguro", fmt_brl(data.get("gasto_seguro"))),
        ("seguros", "Seguros", fmt_num(data.get("qtd_seguro"))),
        ("media_valores", "Média de valores", fmt_brl(data.get("media_valores", data.get("ticket_medio")))),
    ]
    include_year = params.get("ano") is None
    mensal_labels, mensal_values = sorted_series(data.get("custo_mensal", {}), "Mes", "Custo", include_year=include_year, fallback_year=params.get("ano"))
    compare_selected = filter_state.get("_compare", [])
    compare_data = compare_bundle("pedagio", data, params, compare_selected)
    if compare_selected:
        kpis = compare_combined_kpis(compare_data) + color_kpis(kpis, "pedagio", section=_series_label("pedagio")) + compare_kpi_cards(compare_data[1:])
    monthly_fig = (
        multi_line_chart(compare_chart_series(compare_data, "monthly"), include_year=include_year, fallback_year=params.get("ano"))
        if compare_selected
        else yearly_month_line_chart(data.get("custo_mensal", {}), "Mes", "Custo", fallback_year=params.get("ano"))
        if include_year
        else line_chart(mensal_labels, mensal_values)
    )
    weekly_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "weekly"))
        if compare_selected
        else bar_chart(data.get("custo_semana", {}).get("Dia", []), data.get("custo_semana", {}).get("Custo", []))
    )
    plate_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "plate"), horizontal=True, sort_desc=True)
        if compare_selected
        else bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)
    )
    charts = [
        ("gasto_mensal", "Gasto mensal", monthly_fig),
        ("gasto_semana", "Gasto semanal (últimos 7 dias)", weekly_fig),
        ("gasto_tipo", "Gasto por tipo", pie_chart(data.get("gasto_por_tipo", {}).get("Tipo", []), data.get("gasto_por_tipo", {}).get("Custo", []))),
        ("gasto_placa", "Gasto por placa", plate_fig),
    ]
    render_controlled_dashboard("ped", title="JR Dashboard - Pedágio/Extras", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_vex() -> None:
    topbar("JR DASHBOARD • Vex", back=False)
    seed = route_json("vex", {"ano": "Todos", "mes": ["Todos"]})
    params, filter_state = filter_controls(
        "vex",
        extra_filters=[("placa", "Placa", seed.get("placas", []) or [])],
        key_prefix="vex",
        all_data=seed,
    )
    data = route_json("vex", params)
    kpis = [
        ("gasto_vex", "Gasto Vex total (R$)", fmt_brl(data.get("total_vex"))),
        ("combustivel_vex", "Combustível Vex (R$)", fmt_brl(data.get("combustivel_total"))),
        ("km_total", "KM total", fmt_num(data.get("km_total"))),
        ("litros_total", "Total litros", fmt_num(data.get("litros_total"))),
        ("custo_km", "Custo por KM", fmt_brl(data.get("custo_por_km"))),
        ("media_kml", "Média KM/L", fmt_num(data.get("km_por_litro"), 2)),
        ("custo_litro", "Custo médio por litro", fmt_brl(data.get("custo_por_litro"))),
        ("manutencao_vex", "Manutenção Vex (R$)", fmt_brl(data.get("manutencao_total"))),
        ("pedagio_vex", "Pedágio Vex (R$)", fmt_brl(data.get("pedagio_total"))),
        ("aluguel_veiculos_vex", "Aluguel de veículos Vex (R$)", fmt_brl(data.get("aluguel_veiculos_total"))),
    ]
    include_year = params.get("ano") is None
    fallback_year = params.get("ano")
    mensal_labels, mensal_values = sorted_series(data.get("mensal_total", {}), "Mes", "Valor", include_year=include_year, fallback_year=fallback_year)
    km_labels, km_values = sorted_series(data.get("km_mensal", {}), "Mes", "Km Rodados", include_year=include_year, fallback_year=fallback_year)
    litros_labels, litros_values = sorted_series(data.get("litros_mensal", {}), "Mes", "Litros", include_year=include_year, fallback_year=fallback_year)
    aluguel_labels, aluguel_values = sorted_series(data.get("aluguel_mensal", {}), "Mes", "Custo", include_year=include_year, fallback_year=fallback_year)
    compare_selected = filter_state.get("_compare", [])
    compare_data = compare_bundle("vex", data, params, compare_selected)
    if compare_selected:
        kpis = compare_combined_kpis(compare_data) + color_kpis(kpis, "vex", section=_series_label("vex")) + compare_kpi_cards(compare_data[1:])
    monthly_fig = (
        multi_line_chart(compare_chart_series(compare_data, "monthly"), include_year=include_year, fallback_year=fallback_year)
        if compare_selected
        else yearly_month_line_chart(data.get("mensal_total", {}), "Mes", "Valor", fallback_year=fallback_year)
        if include_year
        else line_chart(mensal_labels, mensal_values)
    )
    plate_fig = (
        multi_bar_chart(compare_chart_series(compare_data, "plate"), horizontal=True, sort_desc=True)
        if compare_selected
        else bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Valor", []), horizontal=True, sort_desc=True, show_text=True)
    )
    charts = [
        ("gasto_mensal", "Gasto Vex mensal", monthly_fig),
        (
            "km_mes",
            "KM Vex por mês",
            yearly_month_bar_chart(data.get("km_mensal", {}), "Mes", "Km Rodados", fallback_year=fallback_year, currency=False)
            if include_year
            else bar_chart(km_labels, km_values, currency=False, show_text=True),
        ),
        (
            "litros_mes",
            "Litros Vex por mês",
            yearly_month_bar_chart(data.get("litros_mensal", {}), "Mes", "Litros", fallback_year=fallback_year, currency=False)
            if include_year
            else bar_chart(litros_labels, litros_values, currency=False, show_text=True),
        ),
        (
            "gasto_area",
            "Gasto Vex por área",
            pie_chart(
                data.get("por_area", {}).get("Area", []),
                data.get("por_area", {}).get("Valor", []),
                hole=0,
                show_values=True,
            ),
        ),
        (
            "aluguel_mes",
            "Aluguel de veículos Vex por mês",
            yearly_month_line_chart(data.get("aluguel_mensal", {}), "Mes", "Custo", fallback_year=fallback_year)
            if include_year
            else line_chart(aluguel_labels, aluguel_values),
        ),
        ("gasto_placa", "Gasto Vex por placa", plate_fig),
    ]
    render_controlled_dashboard("vex", title="JR Dashboard - Vex", kpis=kpis, charts=charts)
    footer("Dados Vex consolidados pelo Neon. © JR")


def render_alertas() -> None:
    topbar("JR DASHBOARD • Alertas Vex", back=True)
    with st.container(key="alertas_shell"):
        st.markdown("## Alertas de uso dos veículos Vex")
        st.caption("São sinalizados automaticamente os registros com IGN ligado ocorridos aos sábados ou domingos.")

        with st.expander("Importar alertas de utilização", expanded=False):
            st.caption(
                "Envie uma planilha `.xlsx` ou `.csv` com as colunas PLACA, DATA E HORA, LOCAL e IGN. "
                "Somente usos com IGN ligado aos sábados ou domingos serão importados."
            )
            example = pd.DataFrame(
                [{"PLACA": "ABC1D23", "DATA E HORA": "01/08/2026 08:30:00", "LOCAL": "JR Carmo do Cajuru", "IGN": "ligado"}]
            )
            st.download_button(
                "Baixar planilha de exemplo",
                data=lambda: _sheet_xlsx_bytes(example, "Alertas Vex"),
                file_name="exemplo_alertas_vex.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="alertas_download_example",
                width="stretch",
            )
            upload_nonce_key = "alertas_vex_upload_nonce"
            st.session_state.setdefault(upload_nonce_key, 0)
            uploaded = st.file_uploader(
                "Enviar planilha",
                type=["xlsx", "csv"],
                key=f"alertas_vex_upload_{st.session_state[upload_nonce_key]}",
            )
            if uploaded is not None:
                try:
                    raw_df = _read_uploaded_sheet(uploaded, ALERTAS_VEX_SHEET_ALIASES)
                    rows, errors = _alertas_vex_rows_from_sheet(raw_df, _registered_plate_map())
                except Exception as exc:
                    st.error("Não foi possível ler a planilha.")
                    st.exception(exc)
                else:
                    if errors:
                        st.warning("Revise a planilha antes de importar.")
                        for error in errors[:12]:
                            st.write(error)
                        if len(errors) > 12:
                            st.write(f"...mais {len(errors) - 12} erro(s).")
                    elif not rows:
                        st.warning("Nenhuma utilização válida foi encontrada.")
                    else:
                        alert_rows = _alertas_vex_only_alert_rows(rows)
                        if not alert_rows:
                            st.success(
                                "A planilha foi conferida e não possui uso com IGN ligado aos sábados ou domingos. "
                                "Nenhum registro será importado."
                            )
                        else:
                            preview = pd.DataFrame(alert_rows)
                            preview.insert(
                                0,
                                "Dia",
                                pd.to_datetime(preview["Data"], errors="coerce").dt.dayofweek.map({5: "Sábado", 6: "Domingo"}),
                            )
                            st.dataframe(
                                preview[["Dia", "PLACA", "Data", "Local", "IGN"]].rename(columns={"PLACA": "Placa"}),
                                width="stretch",
                                hide_index=True,
                                height=260,
                            )
                            st.warning(
                                f"{len(alert_rows)} alerta(s) encontrado(s). "
                                f"As outras {len(rows) - len(alert_rows)} linha(s) não serão importadas."
                            )
                        if alert_rows and st.button(
                            f"Importar {len(alert_rows)} alerta(s)",
                            type="primary",
                            width="stretch",
                            key="alertas_vex_import_confirm",
                        ):
                            existing = backend.load_alertas_vex()
                            existing_keys = {
                                (
                                    pd.to_datetime(row.Data, errors="coerce"),
                                    clean_text(row.PLACA).strip().upper(),
                                    clean_text(row.Local).strip(),
                                    clean_text(row.IGN).strip().lower(),
                                )
                                for row in existing.itertuples(index=False)
                            }
                            new_rows = [
                                row
                                for row in alert_rows
                                if (
                                    pd.to_datetime(row["Data"], errors="coerce"),
                                    clean_text(row["PLACA"]).strip().upper(),
                                    clean_text(row["Local"]).strip(),
                                    clean_text(row["IGN"]).strip().lower(),
                                )
                                not in existing_keys
                            ]
                            if new_rows:
                                try:
                                    imported, skipped = backend.append_missing_dashboard_records(
                                        "alertas_vex",
                                        new_rows,
                                        update_plate_registry=False,
                                    )
                                except Exception as exc:
                                    st.error("Não foi possível salvar os dados de alerta no Neon.")
                                    st.exception(exc)
                                    return
                                clear_cached_reads()
                                st.success(f"{len(imported)} alerta(s) importado(s); {skipped} já existente(s).")
                            else:
                                st.info("Todos os registros dessa planilha já estão cadastrados.")
                            # Usa uma nova chave no próximo ciclo para limpar o
                            # arquivo já processado do campo de upload.
                            st.session_state[upload_nonce_key] += 1
                            st.rerun()

        seed = route_json("alertas")
        filter_cols = st.columns([0.8, 1.1, 1.4, 1.0])
        year_options = ["Todos", *(seed.get("anos", []) or [])]
        plate_options = ["Todos", *(seed.get("placas", []) or [])]
        with filter_cols[0]:
            ano = st.selectbox("Ano", year_options, key="alertas_ano")
        month_options = ["Todos"]
        if ano != "Todos":
            month_options.extend([f"{int(ano)}-{month:02d}" for month in range(1, 13)])
        with filter_cols[1]:
            mes = st.selectbox("Mês", month_options, format_func=month_filter_label, key="alertas_mes")
        with filter_cols[2]:
            placa = st.selectbox("Placa Vex", plate_options, key="alertas_placa")
        with filter_cols[3]:
            st.write("")
            st.write("")
            if st.button("Limpar filtros", key="alertas_clear", width="stretch"):
                for key in ("alertas_ano", "alertas_mes", "alertas_placa"):
                    st.session_state.pop(key, None)
                st.rerun()

        params: dict[str, object] = {}
        if ano != "Todos":
            params["ano"] = ano
        if mes != "Todos":
            params["mes"] = [mes]
        if placa != "Todos":
            params["placa"] = placa
        data = route_json("alertas", params)

        render_kpis(
            [
                ("Veículos com alerta", fmt_num(data.get("placas_alerta")), JR_RED),
                ("Dias com alerta", fmt_num(data.get("dias_alerta")), "#D97706"),
                ("Alertas cadastrados", fmt_num(data.get("registros_total")), JR_BLUE),
            ]
        )

        ranking = pd.DataFrame(data.get("ranking_placas") or [])
        st.markdown("### Veículos com mais dias de alerta")
        if ranking.empty:
            st.info("Nenhum veículo com alerta para os filtros selecionados.")
        else:
            st.dataframe(
                ranking.rename(columns={"PLACA": "Placa", "Dias": "Dias com alerta"}),
                width="stretch",
                hide_index=True,
                height=min(422, 72 + len(ranking) * 35),
            )

        alerts = pd.DataFrame(data.get("alertas") or [])
        st.markdown("### Ocorrências de sábado e domingo")
        if alerts.empty:
            st.success("Nenhum uso de veículo Vex no fim de semana para os filtros selecionados.")
        else:
            st.warning(f"Foram encontradas {len(alerts)} ocorrência(s) no fim de semana.")
            st.dataframe(
                alerts[["Dia", "Data", "PLACA", "Local", "IGN"]].rename(columns={"PLACA": "Placa"}),
                width="stretch",
                hide_index=True,
                height=min(500, 72 + len(alerts) * 35),
            )

        with st.expander(f"Todas as ocorrências importadas ({data.get('registros_total', 0)})", expanded=False):
            records = pd.DataFrame(data.get("registros") or [])
            if records.empty:
                st.info("Nenhuma ocorrência de alerta cadastrada para os filtros selecionados.")
            else:
                st.dataframe(
                    records[["Data", "PLACA", "Local", "IGN"]].rename(columns={"PLACA": "Placa"}),
                    width="stretch",
                    hide_index=True,
                    height=460,
                )
    footer("Alertas gerados automaticamente a partir das utilizações dos veículos Vex. © JR")
def _render_velocity_details(params: dict[str, object]) -> None:
    with st.expander("Dados detalhados e exportacao", expanded=False):
        try:
            details = backend.velocidade_detalhes(params)
        except Exception as exc:
            st.warning("Nao foi possivel carregar os detalhes das viagens.")
            st.caption(clean_text(exc))
            return
        if details is None or details.empty:
            st.info("Nenhuma viagem encontrada para os filtros selecionados.")
            return

        export_details = details.copy()
        export_downloads = st.columns(2)
        with export_downloads[0]:
            st.download_button(
                "Exportar resultado filtrado (Excel)",
                data=lambda frame=export_details: _sheet_xlsx_bytes(frame, "KPIs velocidade"),
                file_name="kpis_velocidade_filtrados.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="vel_details_xlsx",
                on_click="ignore",
                width="stretch",
            )
        with export_downloads[1]:
            st.download_button(
                "Exportar resultado filtrado (CSV)",
                data=export_details.to_csv(index=False).encode("utf-8-sig"),
                file_name="kpis_velocidade_filtrados.csv",
                mime="text/csv",
                key="vel_details_csv",
                on_click="ignore",
                width="stretch",
            )

        total_rows = len(details)
        page_count = max(1, (total_rows + DATA_EDITOR_PAGE_SIZE - 1) // DATA_EDITOR_PAGE_SIZE)
        if page_count > 1:
            page = st.selectbox(
                "Pagina dos detalhes",
                list(range(1, page_count + 1)),
                format_func=lambda value: f"Pagina {value} de {page_count}",
                key="vel_details_page",
            )
        else:
            page = 1
        start = (int(page) - 1) * DATA_EDITOR_PAGE_SIZE
        end = min(start + DATA_EDITOR_PAGE_SIZE, total_rows)
        display = details.iloc[start:end].copy()
        if "Dentro da Meta" in display.columns:
            display["Dentro da Meta"] = display["Dentro da Meta"].map(
                lambda value: "Sem meta" if pd.isna(value) else "Sim" if bool(value) else "Nao"
            )
        st.caption(f"Exibindo registros {start + 1} a {end} de {total_rows}.")
        st.dataframe(
            display,
            width="stretch",
            height=430,
            hide_index=True,
            column_config={
                "Data": _date_col(),
                "Saida": _datetime_col("Saida"),
                "Chegada": _datetime_col("Chegada"),
                "Distancia Km": st.column_config.NumberColumn("Distancia (km)", format="%.2f"),
                "Duracao Total Min": st.column_config.NumberColumn("Duracao total (min)", format="%.1f"),
                "Movimento Min": st.column_config.NumberColumn("Movimento (min)", format="%.1f"),
                "Velocidade Km/h": st.column_config.NumberColumn("Velocidade (km/h)", format="%.1f"),
                "Atraso Min": st.column_config.NumberColumn("Atraso (min)", format="%.1f"),
            },
        )


def render_velocidade() -> None:
    topbar("JR DASHBOARD • Velocidade", back=False)
    seed = route_json("velocidade", {"ano": "Todos", "mes": ["Todos"]})
    params, _filter_state = filter_controls(
        "velocidade",
        extra_filters=[
            ("categoria", "Categoria", seed.get("categorias", []) or seed.get("segmentos", []) or []),
            ("placa", "Placa", seed.get("placas", []) or []),
            ("motorista", "Motorista", seed.get("motoristas", []) or []),
            ("rota", "Rota", seed.get("rotas", []) or []),
        ],
        key_prefix="vel",
        all_data=seed,
        allow_compare=False,
    )
    data = route_json("velocidade", params)
    valid_trips = int(data.get("viagens_validas") or 0)

    def speed_text(value: object) -> str:
        if value is None or valid_trips == 0:
            return "—"
        return f"{fmt_num(value, 1)} km/h"

    kpis = [
        ("viagens", "Viagens cadastradas", fmt_num(data.get("total_registros")), "#0F766E", "Operacao"),
        ("validas", "Viagens calculadas", fmt_num(valid_trips), "#0F766E", "Operacao"),
        ("distancia", "Distancia total", f"{fmt_num(data.get('distancia_total'), 1)} km", "#0F766E", "Operacao"),
        ("velocidade_media", "Velocidade media ponderada", speed_text(data.get("velocidade_media")), JR_BLUE, "Velocidade"),
        ("velocidade_maxima", "Maior velocidade registrada", speed_text(data.get("velocidade_maxima")), JR_BLUE, "Velocidade"),
        ("tempo_medio", "Tempo medio em rota", fmt_duration_minutes(data.get("tempo_medio_min")), "#7C3AED", "Tempo"),
        ("movimento_medio", "Tempo medio em movimento", fmt_duration_minutes(data.get("movimento_medio_min")), "#7C3AED", "Tempo"),
        ("parado_medio", "Tempo medio parado", fmt_duration_minutes(data.get("parado_medio_min")), "#7C3AED", "Tempo"),
        ("sla", "Viagens dentro da meta", fmt_percent(data.get("sla_percentual"), 1), "#D97706", "Metas e seguranca"),
        ("atraso", "Atraso medio", fmt_duration_minutes(data.get("atraso_medio_min")), "#D97706", "Metas e seguranca"),
        (
            "sem_excesso",
            "Viagens sem excesso",
            fmt_percent(data.get("viagens_sem_excesso_percentual"), 1),
            JR_RED,
            "Metas e seguranca",
        ),
        (
            "eventos_100km",
            "Eventos de excesso / 100 km",
            "—" if data.get("eventos_excesso_por_100_km") is None else fmt_num(data.get("eventos_excesso_por_100_km"), 2),
            JR_RED,
            "Metas e seguranca",
        ),
    ]

    include_year = params.get("ano") is None
    fallback_year = params.get("ano")
    speed_month_labels, speed_month_values = sorted_series(
        data.get("velocidade_mensal", {}),
        "Mes",
        "Velocidade Km/h",
        include_year=include_year,
        fallback_year=fallback_year,
    )
    sla_month_labels, sla_month_values = sorted_series(
        data.get("sla_mensal", {}),
        "Mes",
        "SLA %",
        include_year=include_year,
        fallback_year=fallback_year,
    )
    trip_month_labels, trip_month_values = sorted_series(
        data.get("viagens_mensal", {}),
        "Mes",
        "Viagens",
        include_year=include_year,
        fallback_year=fallback_year,
    )
    charts = [
        (
            "velocidade_mensal",
            "Velocidade media ponderada por mes",
            metric_line_chart(speed_month_labels, speed_month_values, unit="km/h", decimals=1, color="#0F766E"),
        ),
        (
            "sla_mensal",
            "Cumprimento da meta por mes",
            metric_line_chart(sla_month_labels, sla_month_values, unit="%", decimals=1, color="#D97706"),
        ),
        (
            "velocidade_placa",
            "Velocidade media por placa",
            metric_bar_chart(
                data.get("velocidade_por_placa", {}).get("PLACA", []),
                data.get("velocidade_por_placa", {}).get("Velocidade Km/h", []),
                unit="km/h",
                decimals=1,
                horizontal=True,
                sort_desc=True,
                color="#0F766E",
            ),
        ),
        (
            "tempo_rota",
            "Tempo medio por rota",
            metric_bar_chart(
                data.get("tempo_por_rota", {}).get("Rota", []),
                data.get("tempo_por_rota", {}).get("Tempo Medio Min", []),
                unit="min",
                decimals=1,
                horizontal=True,
                sort_desc=True,
                color="#7C3AED",
            ),
        ),
        (
            "viagens_mensal",
            "Viagens por mes",
            metric_bar_chart(trip_month_labels, trip_month_values, unit="viagens", decimals=0, color=JR_BLUE),
        ),
        (
            "distancia_rota",
            "Distancia percorrida por rota",
            metric_bar_chart(
                data.get("distancia_por_rota", {}).get("Rota", []),
                data.get("distancia_por_rota", {}).get("Distancia Km", []),
                unit="km",
                decimals=1,
                horizontal=True,
                sort_desc=True,
                color=JR_BLUE,
            ),
        ),
    ]
    render_controlled_dashboard("vel", title="JR Dashboard - Velocidade", kpis=kpis, charts=charts)
    _render_velocity_details(params)
    footer("Velocidade calculada por viagem com base na distancia e no tempo em movimento. © JR")


def render_rotas() -> None:
    topbar("JR Dashboard - Rotas")
    st.markdown("## Rotas, entregas e desempenho operacional")
    st.caption(
        "Dados importados dos manifestos em PDF e complementados com saída, retorno e KM reais. "
        "O peso total é sempre a soma dos pedidos. A pesquisa consulta tanto a rota quanto clientes, "
        "pedidos, endereços, cidades, vendedores e observações."
    )

    options = route_json("rotas")
    search = st.text_input(
        "Pesquisar em todos os dados",
        placeholder="Ex.: cliente, pedido, carga, cidade, endereço, motorista, placa ou rota",
        key="routes_search",
    )
    f1, f2, f3 = st.columns(3)
    with f1:
        year_options = ["Todos", *(options.get("anos") or [])]
        year = st.selectbox("Ano", year_options, key="routes_year")
        statuses = st.multiselect("Status", options.get("status") or [], key="routes_status")
    with f2:
        month_options = options.get("meses") or []
        months = st.multiselect(
            "Mês",
            month_options,
            format_func=lambda value: month_label(int(str(value).split("-")[-1])) if "-" in str(value) else str(value),
            key="routes_months",
        )
        plates = st.multiselect("Placa", options.get("placas") or [], key="routes_plates")
    with f3:
        drivers = st.multiselect("Motorista", options.get("motoristas") or [], key="routes_drivers")
        route_names = st.multiselect("Rota", options.get("rotas") or [], key="routes_names")

    params: dict[str, object] = {}
    if year != "Todos":
        params["ano"] = year
    if months:
        params["mes"] = months
    if statuses:
        params["status"] = statuses
    if plates:
        params["placa"] = plates
    if drivers:
        params["motorista"] = drivers
    if route_names:
        params["rota"] = route_names
    if search.strip():
        params["busca"] = search.strip()
    data = route_json("rotas", params)

    render_kpis(
        [
            ("Rotas", fmt_num(data.get("total_rotas"), decimals=0), JR_BLUE),
            ("Concluídas", fmt_num(data.get("rotas_concluidas"), decimals=0), "#0F766E"),
            ("Pendentes", fmt_num(data.get("rotas_pendentes"), decimals=0), JR_RED),
            ("Entregas", fmt_num(data.get("entregas_total"), decimals=0), JR_BLUE),
            ("Peso dos pedidos", fmt_peso(data.get("peso_total")), "#7C3AED"),
            ("KM realizados", fmt_num(data.get("km_total"), decimals=1), "#D97706"),
            ("Tempo de viagem", fmt_num(data.get("horas_total"), decimals=1), "#0F766E"),
            ("Horas trabalhadas", fmt_num(data.get("horas_trabalhadas_total"), decimals=1), "#2563EB"),
        ]
    )

    st.markdown("### Rankings")
    rank_driver, rank_plate, rank_route, rank_city = st.tabs(
        ["Motoristas", "Placas", "Rotas", "Cidades atendidas"]
    )
    with rank_driver:
        st.caption("Ordenado primeiro por rotas concluídas, depois por quantidade de rotas e KM realizados.")
        st.dataframe(pd.DataFrame(data.get("ranking_motoristas") or []), width="stretch", hide_index=True)
    with rank_plate:
        st.dataframe(pd.DataFrame(data.get("ranking_placas") or []), width="stretch", hide_index=True)
    with rank_route:
        st.dataframe(pd.DataFrame(data.get("ranking_rotas") or []), width="stretch", hide_index=True)
    with rank_city:
        st.dataframe(pd.DataFrame(data.get("ranking_cidades") or []), width="stretch", hide_index=True)

    route_records = data.get("rotas_detalhes") or []
    delivery_records = data.get("entregas_detalhes") or []
    routes_df = pd.DataFrame(route_records)
    deliveries_df = pd.DataFrame(delivery_records)
    st.markdown("### Rotas encontradas")
    if routes_df.empty:
        st.info("Nenhuma rota encontrada para os filtros informados.")
    else:
        route_visible = [
            "Status", "Data", "Previsao", "Rota", "Carga", "PLACA", "Motorista", "Veiculo",
            "Peso Carga", "Peso Manifesto", "Entregas", "Saida", "Retorno", "Tempo Viagem Horas",
            "Horas Trabalhadas", "Dias Rota", "KM Rodados", "Arquivo",
        ]
        route_visible = [column for column in route_visible if column in routes_df.columns]
        st.dataframe(routes_df[route_visible], width="stretch", hide_index=True)

        label_map = {}
        for row in route_records:
            route_id = clean_text(row.get("Rota ID"))
            label_map[route_id] = (
                f"{clean_text(row.get('Status'))} · {clean_text(row.get('Rota'))} · "
                f"{clean_text(row.get('PLACA'))} · carga {clean_text(row.get('Carga'))}"
            )
        selected_id = st.selectbox(
            "Abrir detalhes completos da rota",
            list(label_map),
            format_func=lambda value: label_map.get(value, value),
            key="routes_detail_id",
        )
        selected_route = next(row for row in route_records if clean_text(row.get("Rota ID")) == selected_id)
        detail_table = pd.DataFrame(
            [{"Campo": key, "Valor": value} for key, value in selected_route.items() if key != "Texto Extraido"]
        )
        st.dataframe(detail_table, width="stretch", hide_index=True)
        selected_deliveries = (
            deliveries_df[deliveries_df["Rota ID"].astype("string") == selected_id]
            if not deliveries_df.empty and "Rota ID" in deliveries_df.columns
            else pd.DataFrame()
        )
        st.markdown(f"#### Entregas da rota ({len(selected_deliveries)})")
        st.dataframe(selected_deliveries, width="stretch", hide_index=True)
        with st.expander("Texto integral extraído do PDF"):
            st.text(selected_route.get("Texto Extraido") or "Sem texto armazenado.")

    footer("Manifestos de rota armazenados separadamente dos lançamentos de Peso. © JR")


def footer(text: str) -> None:
    st.markdown(f'<div class="footer-note">{h(text)}</div>', unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="JR Dashboard", page_icon=str(LOGO_PATH), layout="wide")
    inject_css()
    page = page_param()
    try:
        if page == "combustivel":
            render_combustivel()
        elif page == "manutencao":
            render_manutencao()
        elif page == "hoteis":
            render_hoteis()
        elif page == "pedagio":
            render_pedagio()
        elif page == "vex":
            render_vex()
        elif page == "alertas":
            render_alertas()
        elif page == "velocidade":
            render_velocidade()
        elif page in {"rotas", "rota"}:
            render_rotas()
        elif page in {"calculadora-frete", "frete"}:
            render_calculadora_frete()
        elif page in {"frota", "ranking"}:
            render_frota()
        elif page in {"cadastro", "dados"}:
            render_cadastro()
        else:
            render_home()
    except Exception as exc:
        st.error("Não foi possível carregar este dashboard. Configure o DATABASE_URL do Neon nos Secrets do Streamlit e tente novamente.")
        st.exception(exc)


if __name__ == "__main__":
    main()
