import json
import os
import unittest
import zipfile
from datetime import date
from io import BytesIO
from unittest.mock import patch

import pandas as pd

os.environ.setdefault("JR_SKIP_WARM_CACHE", "1")

import app as backend
import streamlit_app as dashboard


def sample_payload() -> dict:
    return {
        "total_rotas": 2,
        "entregas_total": 30,
        "peso_total": 18_000,
        "km_total": 800,
        "custos": {
            "total_custo": 8_500,
            "total_ganho": 11_000,
            "resultado": 2_500,
            "rotas": [
                {
                    "Rota ID": "r1", "Rota": "ROTA CARA", "PLACA": "AAA1A11",
                    "Combustivel": 5_000, "Manutencao": 1_000, "Pedagio": 500,
                    "Hoteis": 300, "Salarios": 200, "Freteiro": 0,
                    "Custo total": 7_000, "Ganho entregas": 6_000,
                    "Resultado": -1_000, "Custo sobre ganho %": 116.67,
                },
                {
                    "Rota ID": "r2", "Rota": "ROTA BOA", "PLACA": "BBB2B22",
                    "Combustivel": 1_000, "Manutencao": 200, "Pedagio": 100,
                    "Hoteis": 0, "Salarios": 200, "Freteiro": 0,
                    "Custo total": 1_500, "Ganho entregas": 5_000,
                    "Resultado": 3_500, "Custo sobre ganho %": 30,
                },
            ],
        },
        "tempos_rotas": [
            {"Rota ID": "r1", "Entregas": 10, "KM Rodados": 500, "Peso Carga": 10_000, "Dias Rota": 2, "Tempo Viagem Horas": 34, "Horas Trabalhadas": 20},
            {"Rota ID": "r2", "Entregas": 20, "KM Rodados": 300, "Peso Carga": 8_000, "Dias Rota": 1, "Tempo Viagem Horas": 10, "Horas Trabalhadas": 10},
        ],
        "rotas_detalhes": [],
        "entregas_detalhes": [],
        "ranking_motoristas": [],
        "ranking_placas": [],
        "alertas": [],
    }


class RoutesDashboardTests(unittest.TestCase):
    def test_gauge_context_identifies_result_and_reference_status(self):
        context = dashboard._route_gauge_context_html(
            [("Melhor", "MOTORISTA TESTE"), ("Menor pontuação", "OUTRO MOTORISTA")],
            value=82.0,
            target=80.0,
            inverse=False,
        )
        self.assertIn("MOTORISTA TESTE", context)
        self.assertIn("OUTRO MOTORISTA", context)
        self.assertIn("Refer&#234;ncia atingida", context)

    def test_driver_ranking_adds_linear_score_indicators(self):
        frame = dashboard._route_driver_ranking_frame(
            [
                {"Motorista": "VERDE", "Pontuacao": 85.0, "Posicao": 1},
                {"Motorista": "AMARELO", "Pontuacao": 72.0, "Posicao": 2},
                {"Motorista": "LARANJA", "Pontuacao": 60.0, "Posicao": 3},
                {"Motorista": "VERMELHO", "Pontuacao": 40.0, "Posicao": 4},
            ]
        )
        self.assertEqual(frame.columns[:4].tolist(), ["Motorista", "Indicador", "Posicao", "Pontuacao"])
        indicators = frame.set_index("Motorista")["Indicador"].to_dict()
        self.assertIn("🟩", indicators["VERDE"])
        self.assertIn("🟨", indicators["AMARELO"])
        self.assertIn("🟧", indicators["LARANJA"])
        self.assertIn("🟥", indicators["VERMELHO"])

    def test_pending_routes_never_enter_completed_scope(self):
        routes = pd.DataFrame(
            [
                {"Rota ID": "ok", "Status": "Concluída"},
                {"Rota ID": "pending", "Status": "Pendente"},
                {"Rota ID": "blank", "Status": ""},
            ]
        )
        completed = backend._completed_route_rows(routes)
        self.assertEqual(completed["Rota ID"].tolist(), ["ok"])

    def test_financial_indicators_use_real_route_values(self):
        frame = dashboard._route_financial_frame(sample_payload())
        expensive = frame.loc[frame["Rota ID"].eq("r1")].iloc[0]
        self.assertEqual(expensive["Situação"], "Não vale a pena")
        self.assertAlmostEqual(float(expensive["Custo por entrega"]), 700.0)
        self.assertAlmostEqual(float(expensive["Custo por km"]), 14.0)
        self.assertAlmostEqual(float(expensive["Intervalos e noites"]), 14.0)

    def test_fuel_cost_uses_plate_history_per_km(self):
        fuel = pd.DataFrame(
            [
                {"Data": "2026-01-05", "PLACA": "AAA1A11", "Custo": 1_000.0},
                {"Data": "2099-01-05", "PLACA": "AAA1A11", "Custo": 9_999.0},
            ]
        )
        mileage = pd.DataFrame(
            [
                {"Mes": "2026-01", "PLACA": "AAA1A11", "Km Rodados": 400.0},
                {"Mes": "2099-01", "PLACA": "AAA1A11", "Km Rodados": 1.0},
            ]
        )
        rates = backend._historical_plate_fuel_rates(
            fuel, mileage, cutoff=pd.Timestamp("2026-10-27")
        )
        self.assertEqual(len(rates), 1)
        self.assertAlmostEqual(float(rates.iloc[0]["Combustivel R$/km"]), 2.5)
        allocated, warnings = backend._route_fuel_costs_from_history(
            pd.DataFrame(
                [{"Rota ID": "r1", "Rota": "ROTA TESTE", "PLACA": "AAA1A11", "Km Rodados": 100.0}]
            ),
            rates,
        )
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(float(allocated.iloc[0]["Custo"]), 250.0)

        routes = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": pd.Timestamp("2026-10-20"),
                    "Saida": pd.Timestamp("2026-10-20 07:00"),
                    "Retorno": pd.Timestamp("2026-10-20 17:00"), "Mes": "2026-10",
                    "Rota": "ROTA TESTE", "PLACA": "AAA1A11", "Motorista": "TESTE",
                    "Categoria": "Transporte", "KM Rodados": 100.0,
                }
            ]
        )
        deliveries = pd.DataFrame([{"Rota ID": "r1", "Valor Nota": 1_000.0}])
        empty_costs = pd.DataFrame(columns=["Data", "Mes", "PLACA", "Custo"])
        empty_salary = pd.DataFrame(columns=["Mes", "Valor"])
        empty_hotels = pd.DataFrame(columns=["Data", "Valor", "Motorista", "Ajudante"])
        with (
            patch.object(backend, "load_combustivel", return_value=fuel),
            patch.object(backend, "load_combustivel_km", return_value=mileage),
            patch.object(backend, "load_manutencao", return_value=empty_costs),
            patch.object(backend, "load_pedagio", return_value=empty_costs),
            patch.object(backend, "load_salarios_transporte", return_value=empty_salary),
            patch.object(backend, "load_hoteis", return_value=empty_hotels),
            patch.object(backend, "_ranking_freighter_daily_rates", return_value={}),
            patch.object(backend, "_apply_plate_categories", side_effect=lambda frame: frame),
        ):
            result = backend._route_cost_breakdown(routes, routes, deliveries)
        route_cost = result["rotas"][0]
        self.assertAlmostEqual(float(route_cost["Combustivel R$/km"]), 2.5)
        self.assertAlmostEqual(float(route_cost["Combustivel"]), 250.0)

    def test_route_summary_preserves_operational_result_name(self):
        summary = dashboard._route_summary_table(dashboard._route_financial_frame(sample_payload()))
        worst = summary.iloc[0]
        self.assertEqual(worst["Rota"], "ROTA CARA")
        self.assertEqual(worst["Situação"], "Não vale a pena")
        self.assertAlmostEqual(float(worst["Resultado operacional"]), -1_000.0)

    def test_period_presets_are_deterministic(self):
        minimum, maximum = date(2026, 1, 1), date(2026, 10, 27)
        start, end = dashboard._route_period_dates("Todo o período", minimum, maximum, None)
        self.assertEqual((start, end), (minimum, maximum))
        start, end = dashboard._route_period_dates(
            "Intervalo personalizado", minimum, maximum, (date(2026, 10, 1), date(2026, 10, 15))
        )
        self.assertEqual((start, end), (date(2026, 10, 1), date(2026, 10, 15)))

    def test_management_exports_are_valid_files(self):
        raw = json.dumps(sample_payload(), ensure_ascii=False, default=str, sort_keys=True)
        workbook = dashboard._route_management_workbook(raw)
        report = dashboard._route_management_pdf(raw, "01/10/2026 — 27/10/2026")
        self.assertTrue(zipfile.is_zipfile(BytesIO(workbook)))
        self.assertTrue(report.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
