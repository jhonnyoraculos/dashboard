from __future__ import annotations

import base64
import html
import os
from io import BytesIO
from datetime import date
from pathlib import Path

os.environ.setdefault("JR_SKIP_WARM_CACHE", "1")

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

import app as backend


JR_BLUE = "#1C2D6B"
JR_RED = "#BE1E2D"
MUTED = "#6B7280"
CARD_BORDER = "#c2d2f3"
LOGO_PATH = Path(__file__).parent / "static" / "logo-jr.png"
CURRENT_YEAR = date.today().year
APP_VERSION = "deploy-cad-postos-combustiveis-v1"

PLOTLY_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "scale": 2},
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

ROUTES = {
    "combustivel": backend.data_comb,
    "manutencao": backend.data_manu,
    "hoteis": backend.data_hoteis,
    "pedagio": backend.data_pedagio,
    "vex": backend.data_vex,
    "overview": backend.data_overview,
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
          --jr-blue: {JR_BLUE};
          --jr-red: {JR_RED};
          --muted: {MUTED};
          --card-border: {CARD_BORDER};
          --radius: 14px;
        }}

        html, body, [class*="css"] {{
          font-family: "Inter", sans-serif;
        }}

        html,
        body,
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] {{
          max-width: 100%;
          overflow-x: clip;
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
          position: fixed;
          inset: -18vh -18vw;
          pointer-events: none;
          z-index: 0;
          background-repeat: repeat;
          will-change: transform;
        }}

        .stApp::before {{
          opacity: .72;
          filter: drop-shadow(0 0 5px rgba(28,45,107,.28));
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
          animation: jr-particles-drift 52s linear infinite;
        }}

        .stApp::after {{
          opacity: .64;
          filter: drop-shadow(0 0 7px rgba(190,30,45,.30));
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
          animation: jr-particles-float 71s linear infinite;
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
          margin: 0 0 0;
          width: auto;
          box-sizing: border-box;
          background: var(--jr-blue);
          box-shadow:
            0 4px 12px rgba(0,0,0,.2),
            0 0 0 100vmax var(--jr-blue);
          clip-path: inset(0 -100vmax);
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
        .st-key-vex_filterbar {{
          background: var(--jr-blue);
          margin: 0 0 58px;
          width: auto;
          padding: 0 32px 18px;
          box-sizing: border-box;
          box-shadow:
            0 4px 12px rgba(0,0,0,.2),
            0 0 0 100vmax var(--jr-blue);
          clip-path: inset(0 -100vmax);
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
        .st-key-vex_filterbar > div {{
          position: relative;
          z-index: 1;
        }}

        .st-key-comb_filterbar label,
        .st-key-manu_filterbar label,
        .st-key-hotel_filterbar label,
        .st-key-ped_filterbar label,
        .st-key-vex_filterbar label {{
          display: none !important;
        }}

        .st-key-comb_filterbar div[data-baseweb="select"] > div,
        .st-key-manu_filterbar div[data-baseweb="select"] > div,
        .st-key-hotel_filterbar div[data-baseweb="select"] > div,
        .st-key-ped_filterbar div[data-baseweb="select"] > div,
        .st-key-vex_filterbar div[data-baseweb="select"] > div {{
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
        .st-key-vex_filterbar [data-testid="stHorizontalBlock"] {{
          gap: 12px;
          align-items: stretch;
          flex-wrap: wrap !important;
        }}

        .st-key-comb_filterbar [data-testid="column"],
        .st-key-manu_filterbar [data-testid="column"],
        .st-key-hotel_filterbar [data-testid="column"],
        .st-key-ped_filterbar [data-testid="column"],
        .st-key-vex_filterbar [data-testid="column"] {{
          flex: 1 1 150px !important;
          min-width: 145px !important;
          max-width: none !important;
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
          background: rgba(255,255,255,0.76);
          border: 1px solid rgba(255,255,255,0.74);
          border-radius: var(--radius);
          padding: 40px;
          box-shadow: 0 6px 18px rgba(0,0,0,0.08);
          backdrop-filter: blur(14px);
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
          margin: 4px 0 12px;
          font-size: 34px;
          font-weight: 800;
          color: var(--jr-blue);
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

        .home-admin-link {{
          position: absolute;
          top: 24px;
          right: 24px;
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
          z-index: 2;
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

        .home-total-card,
        .kpi {{
          background: linear-gradient(145deg, rgba(255,255,255,0.94), rgba(255,255,255,0.86));
          border: 1.5px solid var(--card-border);
          border-radius: var(--radius);
          padding: 18px 24px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          box-shadow: 0 12px 28px rgba(16,24,40,0.12);
        }}

        .home-total-card {{
          border: 0;
          box-shadow: 0 14px 32px rgba(16,24,40,0.12);
        }}

        .kpis {{
          margin: 18px 0 28px;
          gap: 28px;
        }}

        .kpi {{
          padding: 24px;
          min-height: 116px;
          align-items: center;
          justify-content: center;
          text-align: center;
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

        .home-total-value {{
          margin: 0;
          font-size: 28px;
          font-weight: 800;
          color: var(--jr-blue);
          line-height: 1.2;
        }}

        .home-total-status {{
          margin: 0;
          font-size: 12px;
          color: #4B5563;
        }}

        .home-filter-row {{
          margin-top: 24px;
        }}

        .kpi-value {{
          font-size: clamp(18px, 1.8vw, 26px);
          font-weight: 800;
          color: var(--jr-red);
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
          background: rgba(255,255,255,0.72);
          border: 1px solid rgba(255,255,255,0.7);
          border-radius: var(--radius);
          padding: 32px;
          box-shadow: 0 6px 18px rgba(0,0,0,0.08);
          backdrop-filter: blur(12px);
          display: flex;
          flex-direction: column;
          gap: 20px;
          position: relative;
          overflow: hidden;
          min-height: 330px;
        }}

        .home-card::after {{
          content: "";
          position: absolute;
          inset: 0;
          background: linear-gradient(140deg, rgba(28,45,107,0.05), transparent 65%);
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
        }}

        .home-footer {{
          max-width: 1100px;
          margin: 48px auto 0;
          background: rgba(255,255,255,0.72);
          border: 1px solid rgba(255,255,255,0.7);
          border-radius: var(--radius);
          padding: 36px;
          box-shadow: 0 6px 18px rgba(0,0,0,0.08);
          backdrop-filter: blur(12px);
        }}

        .home-footer h3 {{
          margin: 0 0 16px;
          font-size: 20px;
          color: var(--jr-blue);
        }}

        div[data-testid="stVerticalBlockBorderWrapper"] {{
          background: linear-gradient(145deg, rgba(255,255,255,0.94), rgba(255,255,255,0.86));
          border: 1.5px solid var(--card-border);
          border-radius: var(--radius);
          box-shadow: 0 12px 28px rgba(16,24,40,0.12);
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

        [class*="_dashboard_controls"] [data-testid="column"] {{
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

        @media (max-width: 780px) {{
          .block-container {{
            padding: 0 10px 30px;
          }}

          .jr-topbar {{
            margin: 0;
            width: auto;
            padding: 10px 12px;
            position: static;
          }}

          .st-key-comb_filterbar,
          .st-key-manu_filterbar,
          .st-key-hotel_filterbar,
          .st-key-ped_filterbar,
          .st-key-vex_filterbar {{
            margin: 0 -10px 18px;
            width: auto;
            padding: 8px 10px 10px;
            position: static;
            overflow: visible;
          }}

          .st-key-comb_filterbar [data-testid="stHorizontalBlock"],
          .st-key-manu_filterbar [data-testid="stHorizontalBlock"],
          .st-key-hotel_filterbar [data-testid="stHorizontalBlock"],
          .st-key-ped_filterbar [data-testid="stHorizontalBlock"],
          .st-key-vex_filterbar [data-testid="stHorizontalBlock"] {{
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

          .st-key-comb_filterbar [data-testid="column"],
          .st-key-manu_filterbar [data-testid="column"],
          .st-key-hotel_filterbar [data-testid="column"],
          .st-key-ped_filterbar [data-testid="column"],
          .st-key-vex_filterbar [data-testid="column"] {{
            flex: 0 0 clamp(132px, 43vw, 190px) !important;
            min-width: clamp(132px, 43vw, 190px) !important;
            max-width: clamp(132px, 43vw, 190px) !important;
            scroll-snap-align: start;
          }}

          .st-key-comb_filterbar div[data-baseweb="select"] > div,
          .st-key-manu_filterbar div[data-baseweb="select"] > div,
          .st-key-hotel_filterbar div[data-baseweb="select"] > div,
          .st-key-ped_filterbar div[data-baseweb="select"] > div,
          .st-key-vex_filterbar div[data-baseweb="select"] > div {{
            min-height: 36px;
          }}

          .st-key-comb_filterbar span[data-baseweb="tag"],
          .st-key-manu_filterbar span[data-baseweb="tag"],
          .st-key-hotel_filterbar span[data-baseweb="tag"],
          .st-key-ped_filterbar span[data-baseweb="tag"],
          .st-key-vex_filterbar span[data-baseweb="tag"] {{
            max-width: 74px;
            min-height: 22px;
          }}

          .st-key-comb_filterbar span[data-baseweb="tag"] span,
          .st-key-manu_filterbar span[data-baseweb="tag"] span,
          .st-key-hotel_filterbar span[data-baseweb="tag"] span,
          .st-key-ped_filterbar span[data-baseweb="tag"] span,
          .st-key-vex_filterbar span[data-baseweb="tag"] span {{
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

          .home-admin-link {{
            position: relative;
            top: auto;
            right: auto;
            align-self: flex-start;
          }}

          .home-header h1 {{
            font-size: 28px;
          }}

          .home-total-grid,
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

          [class*="_dashboard_controls"] [data-testid="column"] {{
            flex: 1 1 calc(50% - 8px) !important;
            min-width: min(180px, 100%) !important;
          }}

          [class*="_dashboard_controls"] [data-testid="stCheckbox"] label {{
            min-height: 40px;
            padding: 7px 10px;
          }}
        }}

        @media (max-width: 560px) {{
          .st-key-comb_filterbar [data-testid="column"],
          .st-key-manu_filterbar [data-testid="column"],
          .st-key-hotel_filterbar [data-testid="column"],
          .st-key-ped_filterbar [data-testid="column"],
          .st-key-vex_filterbar [data-testid="column"] {{
            flex-basis: 150px !important;
            min-width: 150px !important;
            max-width: 150px !important;
          }}

          .filter-back,
          .st-key-comb_filterbar .stButton > button,
          .st-key-manu_filterbar .stButton > button,
          .st-key-hotel_filterbar .stButton > button,
          .st-key-ped_filterbar .stButton > button,
          .st-key-vex_filterbar .stButton > button {{
            min-height: 36px;
            padding-left: 8px;
            padding-right: 8px;
            font-size: 12px;
          }}

          [class*="_dashboard_controls"] [data-testid="column"] {{
            flex: 1 1 100% !important;
            min-width: 100% !important;
          }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def route_json(route: str, params: dict[str, object] | None = None) -> dict:
    func = ROUTES[route]
    params = params or {}
    clean_params: dict[str, object] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, list):
            clean_params[key] = [item for item in value if item is not None]
        elif value != "":
            clean_params[key] = value
    return func(clean_params) or {}


def page_param() -> str:
    value = st.query_params.get("page", "home")
    if isinstance(value, list):
        value = value[0] if value else "home"
    return str(value or "home").lower()


def navigate(page: str) -> None:
    st.query_params["page"] = page
    st.rerun()


def fmt_brl(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def fmt_brl_compact(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f"{number:,.0f}".replace(",", ".")
    return f"R$ {formatted}"


def fmt_num(value: object, decimals: int = 0) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f"{number:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if decimals == 0:
        return formatted.split(",")[0]
    return formatted


def h(text: object) -> str:
    return html.escape(clean_text(text))


def clean_text(text: object) -> str:
    value = str(text if text is not None else "")
    if any(marker in value for marker in ("Ã", "Â", "â€", "â€¢")):
        try:
            value = value.encode("latin1").decode("utf-8")
        except UnicodeError:
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
    broken = "\ufffd"
    replacements = {
        f"m{broken}s": "mês",
        f"M{broken}S": "MÊS",
        f"m{broken}dia": "média",
        f"M{broken}DIA": "MÉDIA",
        f"m{broken}dio": "médio",
        f"M{broken}DIO": "MÉDIO",
        f"{broken}ltimos": "últimos",
        f"{broken}LTIMOS": "ÚLTIMOS",
        f"combust{broken}vel": "combustível",
        f"COMBUST{broken}VEL": "COMBUSTÍVEL",
        f"gr{broken}fico": "gráfico",
        f"Gr{broken}fico": "Gráfico",
        f"GR{broken}FICO": "GRÁFICO",
        f"p{broken}gina": "página",
        f"P{broken}gina": "Página",
        f"P{broken}GINA": "PÁGINA",
        f"manuten{broken}{broken}o": "manutenção",
        f"MANUTEN{broken}{broken}O": "MANUTENÇÃO",
    }
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    return value


def selected_or_default(options: list, current: object | None = None, *, default_current_year: bool = False) -> object:
    all_options = ["Todos", *[item for item in options if item != "Todos"]]
    if current in all_options:
        return current
    if default_current_year and CURRENT_YEAR in all_options:
        return CURRENT_YEAR
    if default_current_year and str(CURRENT_YEAR) in all_options:
        return str(CURRENT_YEAR)
    return "Todos"


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


def render_kpis(items: list[tuple[str, str]]) -> None:
    cards = []
    for label, value in items:
        cards.append(
            f'<div class="kpi"><div class="kpi-title">{h(label)}</div><div class="kpi-value">{h(value)}</div></div>'
        )
    st.markdown(f'<section class="kpis">{"".join(cards)}</section>', unsafe_allow_html=True)


def render_home_totals(cards: list[tuple[str, str, str]]) -> None:
    body = []
    for label, value, status in cards:
        body.append(
            f'<div class="home-total-card home-total-card--secondary"><p class="home-total-label">{h(label)}</p><p class="home-total-value">{h(value)}</p><p class="home-total-status">{h(status)}</p></div>'
        )
    st.markdown(f'<div class="home-total-grid">{"".join(body)}</div>', unsafe_allow_html=True)


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


def line_chart(labels: list[str], values: list[float]) -> go.Figure:
    values = [float(value or 0) for value in values]
    if values:
        min_value = min(values)
        max_value = max(values)
        padding = (max_value - min_value) * 0.14 if max_value != min_value else max(1, abs(max_value) * 0.08)
        y_range = [max(0, min_value - padding), max_value + padding]
    else:
        y_range = None
    fig = go.Figure(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers+text",
            line={"color": JR_BLUE, "width": 3},
            marker={"color": JR_RED, "size": 7},
            text=[fmt_brl_compact(value) for value in values],
            textposition="top center",
            textfont={"size": 10, "color": JR_BLUE},
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
        text = [fmt_brl_compact(value) if currency else fmt_num(value) for value in values_clean]

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


def pie_chart(labels: list, values: list) -> go.Figure:
    fig = go.Figure(
        go.Pie(
            labels=labels or [],
            values=[float(value or 0) for value in values or []],
            hole=0.45,
            textinfo="percent",
            textposition="inside",
            hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=True, legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.2})
    return apply_theme(fig, height=360, margin={"l": 16, "r": 16, "t": 30, "b": 90})


def report_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
        "FreeSansBold.ttf" if bold else "FreeSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
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
    words = clean_text(text).split()
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
    words = clean_text(text).split()
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


def horizontal_bar_row_count(fig: go.Figure) -> int:
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
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
    return 420


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
        draw.text((margin + 84, y + 4), "Dashboards operacionais", font=report_font(36, bold=True), fill=JR_BLUE)
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
        draw.rounded_rectangle(
            (x + 6, y + 8, x + card_width + 6, y + card_height + 8),
            radius=18,
            fill=shadow,
        )
        draw.rounded_rectangle(
            (x, y, x + card_width, y + card_height),
            radius=18,
            fill=panel,
            outline=line,
            width=2,
        )
        center_x = x + card_width // 2
        draw_centered_wrapped_text(
            draw,
            clean_text(label).upper(),
            center_x,
            y + 26,
            font=report_font(20, bold=True),
            fill=MUTED,
            max_width=card_width - 60,
            line_gap=5,
        )
        value_text = clean_text(value)
        value_font = report_font(30, bold=True)
        value_bbox = draw.textbbox((0, 0), value_text, font=value_font)
        draw.text((center_x - (value_bbox[2] - value_bbox[0]) // 2, y + 95), value_text, font=value_font, fill=JR_BLUE)
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
                    f"Não foi possível renderizar: {clean_text(chart_title)}",
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
        for index, (label, value) in enumerate(kpis):
            row = index // card_cols
            col = index % card_cols
            x = margin + col * (card_width + gap)
            card_y = y + row * (card_height + gap)
            draw.rounded_rectangle(
                (x + 6, card_y + 8, x + card_width + 6, card_y + card_height + 8),
                radius=20,
                fill=shadow,
            )
            draw.rounded_rectangle(
                (x, card_y, x + card_width, card_y + card_height),
                radius=20,
                fill=panel,
                outline=line,
                width=2,
            )
            draw_wrapped_text(
                draw,
                clean_text(label).upper(),
                (x + 30, card_y + 28),
                font=report_font(22, bold=True),
                fill=MUTED,
                max_width=card_width - 60,
                line_gap=4,
            )
            value_size = 42
            value_text = clean_text(value)
            if len(value_text) > 18:
                value_size = 36
            if len(value_text) > 28:
                value_size = 31
            value_font = report_font(value_size, bold=True)
            value_bbox = draw.textbbox((0, 0), value_text, font=value_font)
            value_x = x + (card_width - (value_bbox[2] - value_bbox[0])) // 2
            draw.text((value_x, card_y + 104), value_text, font=value_font, fill=JR_RED)
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
                draw.rounded_rectangle(
                    (x + 6, chart_y + 8, x + chart_card_width + 6, chart_y + row_height + 8),
                    radius=22,
                    fill=shadow,
                )
                draw.rounded_rectangle(
                    (x, chart_y, x + chart_card_width, chart_y + row_height),
                    radius=22,
                    fill=panel,
                    outline=line,
                    width=2,
                )
                draw.text((x + 28, chart_y + 24), clean_text(chart_title), font=report_font(30, bold=True), fill=text)
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


def chart_card(title: str, fig: go.Figure) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="chart-title">{h(title)}</div>', unsafe_allow_html=True)
        scroll_height = chart_scroll_height(fig)
        if scroll_height:
            with st.container(height=scroll_height, border=False):
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
        else:
            st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)


def chart_grid(charts: list[tuple[str, go.Figure]]) -> None:
    for index in range(0, len(charts), 2):
        cols = st.columns(2)
        for col, item in zip(cols, charts[index : index + 2]):
            with col:
                chart_card(item[0], item[1])


def dashboard_controls(
    key_prefix: str,
    *,
    title: str,
    kpis: list[tuple[str, str, str]],
    charts: list[tuple[str, str, go.Figure]],
) -> tuple[bool, bool, list[tuple[str, str, str]], list[tuple[str, str, go.Figure]]]:
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
                (label, value)
                for item_id, label, value in kpis
                if st.session_state.get(f"{key_prefix}_visible_{item_id}", True)
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
            checkbox_items = [("cards", item_id, label) for item_id, label, _ in kpis]
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
    kpis: list[tuple[str, str, str]],
    charts: list[tuple[str, str, go.Figure]],
) -> None:
    show_cards, show_charts, visible_kpis, visible_charts = dashboard_controls(
        key_prefix,
        title=title,
        kpis=kpis,
        charts=charts,
    )
    if show_cards and visible_kpis:
        render_kpis([(label, value) for _, label, value in visible_kpis])
    if show_charts and visible_charts:
        chart_grid([(chart_title, fig) for _, chart_title, fig in visible_charts])


def filter_controls(
    route: str,
    *,
    extra_filters: list[tuple[str, str, list]],
    key_prefix: str,
) -> tuple[dict[str, object], dict]:
    all_data = route_json(route, {"ano": "Todos", "mes": ["Todos"]})
    years = all_data.get("anos", []) or []
    year_options = ["Todos", *years]
    year_default = selected_or_default(years, st.session_state.get(f"{key_prefix}_ano"), default_current_year=True)
    year_index = year_options.index(year_default) if year_default in year_options else 0

    with st.container(key=f"{key_prefix}_filterbar"):
        filter_widths = [1.1 if len(label) > 10 else 1.0 for _, label, _ in extra_filters]
        widths = [0.85, 1.25, *filter_widths, 1.05, 0.8]
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

        month_data = route_json(route, {"ano": None if ano == "Todos" else ano, "mes": ["Todos"]})
        meses = unique_filter_options(month_data.get("meses", []) or [])
        mes_options = ["Todos", *meses]
        mes_key = f"{key_prefix}_mes"
        mes_previous_key = f"{mes_key}__previous"
        mes_state_exists = mes_key in st.session_state
        current_meses = st.session_state.get(mes_key, ["Todos"])
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
            options = ["Todos", *unique_filter_options(options)]
            current = st.session_state.get(f"{key_prefix}_{param_name}", "Todos")
            if current not in options:
                current = "Todos"
            with filter_cols[idx]:
                params[param_name] = st.selectbox(
                    label,
                    options,
                    index=options.index(current),
                    key=f"{key_prefix}_{param_name}",
                    format_func=select_all_label(label),
                    label_visibility="collapsed",
                )

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
    return params, all_data


def render_home() -> None:
    logo = logo_data_uri()
    st.markdown('<main class="home-wrapper">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <header class="home-header">
          <a class="home-admin-link" href="?page=cadastro" target="_self">Adicionar dados</a>
          <div class="home-brand">
            <img src="{logo}" alt="JR" class="home-logo">
            <div>
              <p class="home-eyebrow">JR Ferragens &amp; Madeiras</p>
              <h1>Dashboards operacionais</h1>
              <p class="home-subtitle">Monitore combustível, manutenção, hospedagens e despesas de pedágio/seguro/IPVA em tempo real, com dados centralizados no Neon.</p>
            </div>
          </div>
          <a class="home-cta" href="#dashboards">Explorar dashboards</a>
        </header>
        """,
        unsafe_allow_html=True,
    )

    overview_all = route_json("overview")
    year_options = ["Todos", *(overview_all.get("anos_disponiveis", []) or [])]
    default_year = CURRENT_YEAR if CURRENT_YEAR in year_options else "Todos"
    ano_state = st.session_state.get("home_ano", default_year)
    ano = ano_state if ano_state in year_options else default_year
    months_seed = route_json("overview", {"ano": None if ano == "Todos" else ano})
    month_options = ["Todos", *(months_seed.get("meses_disponiveis", []) or [])]
    home_mes_exists = "home_mes" in st.session_state
    home_mes_previous_key = "home_mes__previous"
    current_months = st.session_state.get("home_mes", ["Todos"])
    current_months = [item for item in current_months if item in month_options] or ["Todos"]
    if home_mes_exists and st.session_state.get("home_mes") != current_months:
        st.session_state["home_mes"] = current_months
        st.session_state[home_mes_previous_key] = current_months
    if home_mes_previous_key not in st.session_state:
        st.session_state[home_mes_previous_key] = current_months
    meses = normalize_multiselect(current_months, st.session_state.get(home_mes_previous_key, ["Todos"]))

    overview = route_json(
        "overview",
        {
            "ano": None if ano == "Todos" else ano,
            "mes": ["Todos"] if meses == ["Todos"] else [int(item) for item in meses],
        },
    )
    filter_text = ""
    if ano != "Todos":
        filter_text = f"Filtro aplicado: {ano}."
    if meses != ["Todos"]:
        month_text = ", ".join(MONTH_NAMES[int(item) - 1] for item in meses)
        filter_text = f"Filtro aplicado: {month_text}/{ano}." if ano != "Todos" else f"Filtro aplicado: {month_text}."
    suffix = filter_text or "Cálculo baseado nos dados mais recentes do banco."
    home_total_cards = [
        ("Gasto consolidado", fmt_brl(overview.get("total_geral")), suffix),
        ("Gasto transporte", fmt_brl(overview.get("total_transporte")), 'Somatório das despesas marcadas como "Transporte".'),
        ("Gasto Vex", fmt_brl(overview.get("total_vex")), 'Somatório das despesas marcadas como "Vex".'),
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
        cols = st.columns([0.55, 0.55, 2.2])
        with cols[0]:
            st.selectbox("Ano", year_options, index=year_options.index(ano), key="home_ano")
        with cols[1]:
            home_mes_kwargs = {
                "format_func": month_label,
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
          <article class="home-card">
            <div><span class="home-chip">Combustível</span><h2>Consumo, custo e eficiência da frota</h2></div>
            <p class="home-card-text">Filtros por mês, placa, posto e tipo de combustível com KPIs e gráficos de desempenho.</p>
            <ul class="home-list"><li>KPIs automáticos de custo, km e litros</li><li>Comparativo por posto e tipo de combustível</li><li>Histórico mensal de consumo e gastos</li></ul>
            <a class="home-link" href="?page=combustivel" target="_self">Abrir dashboard &rarr;</a>
          </article>
          <article class="home-card">
            <div><span class="home-chip">Manutenção</span><h2>Gestão de oficinas e serviços</h2></div>
            <p class="home-card-text">Acompanhe gastos por placa, oficina e mês, com ticket médio atualizado.</p>
            <ul class="home-list"><li>Resumo financeiro com ticket médio</li><li>Distribuição por placa e oficina</li><li>Curva mensal de investimentos</li></ul>
            <a class="home-link" href="?page=manutencao" target="_self">Abrir dashboard &rarr;</a>
          </article>
          <article class="home-card">
            <div><span class="home-chip">Hotéis</span><h2>Reservas e hospedagens da equipe</h2></div>
            <p class="home-card-text">Filtros por mês, cidade e hotel para entender os investimentos em hospedagem.</p>
            <ul class="home-list"><li>KPIs automáticos de valor total, reservas e médias</li><li>Ranking por cidade e hotel/pousada</li><li>Histórico mensal dos gastos com hospedagem</li></ul>
            <a class="home-link" href="?page=hoteis" target="_self">Abrir dashboard &rarr;</a>
          </article>
          <article class="home-card">
            <div><span class="home-chip">Pedágio &amp; Seguros</span><h2>Pedágio, IPVA e seguros da frota</h2></div>
            <p class="home-card-text">Acompanhe quanto cada placa consome com pedágio, seguros e tributos, com KPIs dinâmicos.</p>
            <ul class="home-list"><li>Resumo mensal consolidado por tipo de despesa</li><li>Comparativo por placa e categoria</li><li>Filtros rápidos por mês, placa e tipo</li></ul>
            <a class="home-link" href="?page=pedagio" target="_self">Abrir dashboard &rarr;</a>
          </article>
          <article class="home-card">
            <div><span class="home-chip">Vex</span><h2>Gastos exclusivos da categoria Vex</h2></div>
            <p class="home-card-text">Visão consolidada dos custos Vex, com filtros por ano e mês.</p>
            <ul class="home-list"><li>Totais Vex por área</li><li>Evolução mensal dos gastos</li><li>Resumo centralizado da categoria</li></ul>
            <a class="home-link" href="?page=vex" target="_self">Abrir dashboard &rarr;</a>
          </article>
        </section>
        </main>
        """,
        unsafe_allow_html=True,
    )


def _entry_month(value: date) -> str:
    return f"{value.year}-{value.month:02d}"


def _entry_required_missing(row: dict, fields: list[str]) -> list[str]:
    missing = []
    for field in fields:
        value = row.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing


def _save_entry(
    dataset: str,
    row: dict,
    *,
    required: list[str],
    success: str,
    replace_keys: list[str] | None = None,
) -> bool:
    missing = _entry_required_missing(row, required)
    if missing:
        st.warning("Preencha os campos obrigatórios: " + ", ".join(missing))
        return False
    try:
        backend.save_dashboard_record(dataset, row, replace_keys=replace_keys)
    except Exception as exc:
        st.error("Não foi possível salvar no Neon.")
        st.exception(exc)
        return False
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
            mapping[placa] = "Vex" if categoria.lower() == "vex" else "Transporte"
    return dict(sorted(mapping.items()))


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
) -> str:
    clean_options = [option for option in options if option]
    if not clean_options:
        return st.text_input(label, placeholder=placeholder, key=f"{prefix}_manual_only")
    selected = st.selectbox(label, [*clean_options, create_label], key=f"{prefix}_select")
    if selected == create_label:
        return st.text_input(manual_label, placeholder=placeholder, key=f"{prefix}_manual")
    return selected


def _plate_fields(prefix: str, plate_map: dict[str, str] | None = None) -> tuple[str, str]:
    plate_map = plate_map if plate_map is not None else _registered_plate_map()
    options = ["Selecione uma placa", *plate_map.keys(), "Cadastrar nova placa"]
    selected = st.selectbox("Placa", options, key=f"{prefix}_placa_select")
    if selected == "Cadastrar nova placa":
        placa = st.text_input("Nova placa", placeholder="ABC1D23", key=f"{prefix}_placa_manual").upper()
        categoria = st.selectbox("Categoria da placa", ["Transporte", "Vex"], key=f"{prefix}_categoria_manual")
        return placa, categoria
    if selected == "Selecione uma placa":
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
        backend.save_dashboard_record("placas", {"PLACA": placa, "Categoria": categoria}, replace_keys=["PLACA"])
    except Exception as exc:
        st.error("Não foi possível salvar a placa no Neon.")
        st.exception(exc)
        return False
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
    st.success("Placa atualizada nos cadastros e lançamentos.")
    return True


def _save_plate_sheet(original_map: dict[str, str], edited: pd.DataFrame) -> bool:
    if edited is None or edited.empty:
        st.warning("Informe pelo menos uma placa.")
        return False

    rows = []
    final_categories: dict[str, str] = {}
    for _, row in edited.iterrows():
        old_plate = clean_text(row.get("Placa atual")).strip().upper()
        new_plate = clean_text(row.get("Placa")).strip().upper()
        categoria = clean_text(row.get("Categoria") or "Transporte").strip()
        if not old_plate and not new_plate:
            continue
        if not new_plate:
            st.warning("Existe uma linha sem placa preenchida.")
            return False
        categoria_final = "Vex" if categoria.lower() == "vex" else "Transporte"
        final_categories[new_plate] = categoria_final
        rows.append((old_plate, new_plate))

    if not rows:
        st.warning("Informe pelo menos uma placa.")
        return False

    try:
        for old_plate, new_plate in rows:
            categoria = final_categories.get(new_plate, "Transporte")
            if old_plate:
                if old_plate == new_plate and original_map.get(old_plate, "Transporte") == categoria:
                    continue
                backend.rename_plate(old_plate, new_plate, categoria)
            else:
                backend.save_dashboard_record("placas", {"PLACA": new_plate, "Categoria": categoria}, replace_keys=["PLACA"])
    except Exception as exc:
        st.error("NÃ£o foi possÃ­vel salvar a tabela de placas no Neon.")
        st.exception(exc)
        return False

    st.success("Tabela de placas salva.")
    st.rerun()
    return True


def render_cadastro() -> None:
    topbar("JR DASHBOARD • Adicionar dados", back=True)
    with st.container(key="cadastro_shell"):
        tabs = st.tabs(["Placas", "Combustível", "KM mensal", "Manutenção", "Hotéis", "Pedágio/IPVA"])

        with tabs[0]:
            with st.form("form_placas", clear_on_submit=True):
                c1, c2, c3 = st.columns([1.2, 1.0, 1.0])
                with c1:
                    placa = st.text_input("Placa", placeholder="ABC1D23", key="cad_placa_nome").upper()
                with c2:
                    categoria = st.selectbox("Categoria", ["Transporte", "Vex"], key="cad_placa_categoria")
                with c3:
                    st.write("")
                    submitted = st.form_submit_button("Cadastrar placa", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "placas",
                        {"PLACA": placa, "Categoria": categoria},
                        required=["PLACA", "Categoria"],
                        replace_keys=["PLACA"],
                        success="Placa cadastrada/atualizada.",
                    )

            plate_map = _registered_plate_map()
            if plate_map:
                table = pd.DataFrame(
                    [
                        {"Placa atual": placa, "Placa": placa, "Categoria": categoria}
                        for placa, categoria in plate_map.items()
                    ]
                )
                edited_plates = st.data_editor(
                    table,
                    width="stretch",
                    hide_index=True,
                    num_rows="dynamic",
                    disabled=["Placa atual"],
                    column_config={
                        "Placa atual": st.column_config.TextColumn("Placa atual"),
                        "Placa": st.column_config.TextColumn("Placa"),
                        "Categoria": st.column_config.SelectboxColumn(
                            "Categoria",
                            options=["Transporte", "Vex"],
                            required=True,
                        ),
                    },
                    key="cad_placas_editor",
                )
                if st.button("Salvar tabela de placas", type="primary", width="stretch", key="cad_placas_sheet_save"):
                    _save_plate_sheet(plate_map, edited_plates)
            else:
                st.info("Cadastre a primeira placa para liberar a edição.")

        with tabs[1]:
            combustivel_options = _registered_text_options(backend.load_combustiveis, "Combustivel")
            posto_options = _registered_text_options(backend.load_postos, "POSTOS")

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
                    )
                    posto = _select_or_create_text(
                        "Posto",
                        posto_options,
                        "cad_comb_posto",
                        "Cadastrar novo posto",
                        "Novo posto",
                        placeholder="Posto JR",
                    )
                    km = st.number_input("KM rodados", min_value=0.0, step=1.0, key="cad_comb_km")
                with c3:
                    litros = st.number_input("Litros", min_value=0.0, step=1.0, key="cad_comb_litros")
                    custo = st.number_input("Custo total", min_value=0.0, step=10.0, format="%.2f", key="cad_comb_custo")
                    submitted = st.form_submit_button("Salvar combustível", type="primary", width="stretch")
                if submitted:
                    _save_entry(
                        "combustivel",
                        {
                            "Data": data,
                            "Mes": _entry_month(data),
                            "Km Rodados": km,
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

        with tabs[2]:
            with st.form("form_km_mensal", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ano = st.number_input("Ano", min_value=2020, max_value=2100, value=CURRENT_YEAR, step=1, key="cad_km_ano")
                with c2:
                    mes = st.selectbox("Mês", list(range(1, 13)), format_func=month_label, key="cad_km_mes")
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

        with tabs[3]:
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
                    )

        with tabs[4]:
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

        with tabs[5]:
            with st.form("form_pedagio", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    data = st.date_input("Data", value=date.today(), key="cad_ped_data")
                    placa, categoria = _plate_fields("cad_ped", plate_map)
                with c2:
                    tipo = st.selectbox("Tipo", ["Pedagio", "IPVA", "Seguro", "Licenciamento", "DPVAT", "Outros"], key="cad_ped_tipo")
                with c3:
                    custo = st.number_input("Custo", min_value=0.0, step=10.0, format="%.2f", key="cad_ped_custo")
                    submitted = st.form_submit_button("Salvar pedágio/IPVA", type="primary", width="stretch")
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
                        required=["Data", "PLACA", "Tipo"],
                        success="Lançamento de pedágio/IPVA salvo.",
                    )


def render_combustivel() -> None:
    topbar("JR DASHBOARD • Combustível", back=False)
    seed = route_json("combustivel", {"ano": "Todos", "mes": ["Todos"]})
    params, _ = filter_controls(
        "combustivel",
        extra_filters=[
            ("placa", "Placa", seed.get("placas", []) or []),
            ("posto", "Posto", seed.get("postos", []) or []),
            ("combustivel", "Combustível", seed.get("combustiveis", []) or []),
            ("segmento", "Categoria", seed.get("segmentos", []) or []),
        ],
        key_prefix="comb",
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
    charts = [
        ("gasto_mes", "Gasto total por mês", line_chart(mensal_labels, mensal_values)),
        ("gasto_semana", "Gasto semanal (últimos 7 dias)", bar_chart(data.get("gasto_semana", {}).get("Dia", []), data.get("gasto_semana", {}).get("Custo", []))),
        ("gasto_posto", "Gasto por posto", pie_chart(data.get("gasto_por_posto", {}).get("POSTOS", []), data.get("gasto_por_posto", {}).get("Custo", []))),
        ("gasto_combustivel", "Gasto por combustível", pie_chart(data.get("gasto_por_combustivel", {}).get("Combustivel", []), data.get("gasto_por_combustivel", {}).get("Custo", []))),
        ("gasto_placa", "Gasto por placa", bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)),
        ("km_mes", "KM por mês", bar_chart(km_labels, km_values, currency=False, show_text=True)),
        ("litros_mes", "Litros por mês", bar_chart(litros_labels, litros_values, currency=False, show_text=True)),
    ]
    render_controlled_dashboard("comb", title="JR Dashboard - Combustível", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_manutencao() -> None:
    topbar("JR DASHBOARD • Manutenção", back=False)
    seed = route_json("manutencao", {"ano": "Todos", "mes": ["Todos"]})
    params, _ = filter_controls(
        "manutencao",
        extra_filters=[
            ("placa", "Placa", seed.get("placas", []) or []),
            ("oficina", "Oficina", seed.get("oficinas", []) or []),
            ("segmento", "Categoria", seed.get("segmentos", []) or []),
        ],
        key_prefix="manu",
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
    charts = [
        ("gasto_placa", "Gasto por placa", bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)),
        ("gasto_oficina", "Gasto por oficina", bar_chart(data.get("gasto_por_oficina", {}).get("OFICINA", []), data.get("gasto_por_oficina", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)),
        ("gasto_mensal", "Gasto mensal", line_chart(mensal_labels, mensal_values)),
        ("gasto_semana", "Gasto semanal (últimos 7 dias)", bar_chart(data.get("custo_semana", {}).get("Dia", []), data.get("custo_semana", {}).get("Custo", []))),
    ]
    render_controlled_dashboard("manu", title="JR Dashboard - Manutenção", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_hoteis() -> None:
    topbar("JR DASHBOARD • Reservas de Hotéis", back=False)
    seed = route_json("hoteis", {"ano": "Todos", "mes": ["Todos"]})
    params, _ = filter_controls(
        "hoteis",
        extra_filters=[
            ("cidade", "Cidade", seed.get("cidades", []) or []),
            ("hotel", "Hotel/Pousada", seed.get("hoteis", []) or []),
        ],
        key_prefix="hotel",
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
    charts = [
        ("valor_mensal", "Valor mensal", line_chart(mensal_labels, mensal_values)),
        ("valor_semanal", "Valor semanal (últimos 7 dias)", bar_chart(week.get("Dia", []), week.get("Valor", []), marker_colors=week_colors or None)),
        ("valor_cidade", "Valor por cidade", bar_chart(data.get("valor_por_cidade", {}).get("Cidade", []), data.get("valor_por_cidade", {}).get("Valor", []), horizontal=True, sort_desc=True, show_text=True)),
        ("valor_hotel", "Valor por hotel/pousada", bar_chart(data.get("valor_por_hotel", {}).get("Hotel", []), data.get("valor_por_hotel", {}).get("Valor", []), horizontal=True, sort_desc=True, show_text=True)),
    ]
    render_controlled_dashboard("hotel", title="JR Dashboard - Reservas de Hotéis", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_pedagio() -> None:
    topbar("JR DASHBOARD • Pedágio, Seguro e IPVA", back=False)
    seed = route_json("pedagio", {"ano": "Todos", "mes": ["Todos"]})
    params, _ = filter_controls(
        "pedagio",
        extra_filters=[
            ("placa", "Placa", seed.get("placas", []) or []),
            ("tipo", "Tipo", seed.get("tipos", []) or []),
            ("segmento", "Segmento", seed.get("segmentos", []) or []),
        ],
        key_prefix="ped",
    )
    data = route_json("pedagio", params)
    kpis = [
        ("gasto_total", "Gasto total (R$)", fmt_brl(data.get("custo_total"))),
        ("media_mensal", "Média mensal (R$)", fmt_brl(data.get("media_mensal"))),
        ("gasto_pedagio", "Gasto pedágio", fmt_brl(data.get("gasto_pedagio"))),
        ("gasto_ipva", "Gasto IPVA", fmt_brl(data.get("gasto_ipva"))),
        ("gasto_seguro", "Gasto seguro", fmt_brl(data.get("gasto_seguro"))),
        ("media_valores", "Média de valores", fmt_brl(data.get("media_valores", data.get("ticket_medio")))),
        ("lancamentos", "Lançamentos", fmt_num(data.get("total_lancamentos"))),
    ]
    include_year = params.get("ano") is None
    mensal_labels, mensal_values = sorted_series(data.get("custo_mensal", {}), "Mes", "Custo", include_year=include_year, fallback_year=params.get("ano"))
    charts = [
        ("gasto_mensal", "Gasto mensal", line_chart(mensal_labels, mensal_values)),
        ("gasto_semana", "Gasto semanal (últimos 7 dias)", bar_chart(data.get("custo_semana", {}).get("Dia", []), data.get("custo_semana", {}).get("Custo", []))),
        ("gasto_tipo", "Gasto por tipo", pie_chart(data.get("gasto_por_tipo", {}).get("Tipo", []), data.get("gasto_por_tipo", {}).get("Custo", []))),
        ("gasto_placa", "Gasto por placa", bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Custo", []), horizontal=True, sort_desc=True, show_text=True)),
        ("gasto_segmento", "Gasto por segmento", bar_chart(data.get("gasto_por_categoria", {}).get("Categoria", []), data.get("gasto_por_categoria", {}).get("Custo", []))),
    ]
    render_controlled_dashboard("ped", title="JR Dashboard - Pedágio, Seguro e IPVA", kpis=kpis, charts=charts)
    footer("Dados atualizados pelo Neon. © JR")


def render_vex() -> None:
    topbar("JR DASHBOARD • Vex", back=False)
    seed = route_json("vex", {"ano": "Todos", "mes": ["Todos"]})
    params, _ = filter_controls(
        "vex",
        extra_filters=[("placa", "Placa", seed.get("placas", []) or [])],
        key_prefix="vex",
    )
    data = route_json("vex", params)
    kpis = [
        ("gasto_vex", "Gasto Vex total (R$)", fmt_brl(data.get("total_vex"))),
        ("combustivel_vex", "Combustível Vex (R$)", fmt_brl(data.get("combustivel_total"))),
        ("km_total", "KM total", fmt_num(data.get("km_total"))),
        ("litros_total", "Total litros", fmt_num(data.get("litros_total"))),
        ("custo_km", "Custo médio por KM", fmt_brl(data.get("custo_por_km"))),
        ("media_kml", "Média KM/L", fmt_num(data.get("km_por_litro"), 2)),
        ("custo_litro", "Custo médio por litro", fmt_brl(data.get("custo_por_litro"))),
        ("manutencao_vex", "Manutenção Vex (R$)", fmt_brl(data.get("manutencao_total"))),
        ("pedagio_vex", "Pedágio/Seguro Vex (R$)", fmt_brl(data.get("pedagio_total"))),
    ]
    include_year = params.get("ano") is None
    mensal_labels, mensal_values = sorted_series(data.get("mensal_total", {}), "Mes", "Valor", include_year=include_year, fallback_year=params.get("ano"))
    charts = [
        ("gasto_mensal", "Gasto Vex mensal", line_chart(mensal_labels, mensal_values)),
        ("gasto_area", "Gasto Vex por área", bar_chart(data.get("por_area", {}).get("Area", []), data.get("por_area", {}).get("Valor", []))),
        ("gasto_placa", "Gasto Vex por placa", bar_chart(data.get("gasto_por_placa", {}).get("PLACA", []), data.get("gasto_por_placa", {}).get("Valor", []), horizontal=True, sort_desc=True, show_text=True)),
    ]
    render_controlled_dashboard("vex", title="JR Dashboard - Vex", kpis=kpis, charts=charts)
    footer("Dados Vex consolidados pelo Neon. © JR")


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
        elif page in {"cadastro", "dados"}:
            render_cadastro()
        else:
            render_home()
    except Exception as exc:
        st.error("Não foi possível carregar este dashboard. Configure o DATABASE_URL do Neon nos Secrets do Streamlit e tente novamente.")
        st.exception(exc)


if __name__ == "__main__":
    main()
