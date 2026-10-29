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
    def test_ai_broken_inline_table_is_normalized_for_chat(self):
        raw = "## Projeção | Métrica |---| Valor observado | **Conclusão** custo estável"
        normalized = dashboard._normalize_ai_markdown(raw)
        self.assertIn("### Projeção", normalized)
        self.assertNotIn("|", normalized)
        self.assertNotIn("---", normalized)
        self.assertIn("**Conclusão**", normalized)

    def test_ai_general_question_uses_every_dashboard_with_shared_period(self):
        self.assertTrue(dashboard._ai_is_general_question("Como está o desempenho geral de custo sobre ganho?"))
        self.assertTrue(dashboard._ai_is_general_question("Mostre o site inteiro"))
        self.assertFalse(dashboard._ai_is_general_question("Qual placa gastou mais combustível?"))
        self.assertFalse(dashboard._ai_is_general_question("Faça uma análise geral desta página"))

        context = {"filtros_ativos": {"data_inicio": "2026-10-01", "data_fim": "2026-10-27"}}
        with patch.object(
            dashboard,
            "_ai_dashboard_payload",
            side_effect=lambda name, filters: {"total": 10, "filtro_recebido": filters},
        ) as payload:
            overview = dashboard._ai_site_wide_overview(context)

        self.assertEqual(overview["escopo"], "site_inteiro")
        self.assertEqual(set(overview["dashboards_consultados"]), set(dashboard.AI_SITE_DASHBOARDS))
        self.assertEqual(payload.call_count, len(dashboard.AI_SITE_DASHBOARDS))
        self.assertEqual(overview["areas"]["combustivel"]["filtros"], {"ano": 2026, "mes": [10]})
        self.assertEqual(
            overview["areas"]["rotas"]["filtros"],
            {"data_inicio": "2026-10-01", "data_fim": "2026-10-27"},
        )

        compact_routes = dashboard._ai_global_dashboard_summary("rotas", sample_payload())
        self.assertEqual(compact_routes["custos"]["total_custo"], 8_500)
        self.assertEqual(compact_routes["custos"]["total_ganho"], 11_000)
        self.assertNotIn("rotas", compact_routes["custos"])

    def test_ai_chart_context_is_structured_and_filters_are_whitelisted(self):
        figure = dashboard.go.Figure(dashboard.go.Bar(x=["jan", "fev"], y=[10, 15], name="Custo"))
        snapshot = dashboard._ai_chart_snapshot("Custo mensal", figure)
        self.assertEqual(snapshot["grafico"], "Custo mensal")
        self.assertEqual(snapshot["series"][0]["x"], ["jan", "fev"])
        self.assertEqual(snapshot["series"][0]["y"], [10, 15])

        filters = dashboard._ai_sanitize_filters(
            "combustivel",
            {"ano": 2026, "placa": "ABC1D23", "sql": "DROP TABLE", "senha": "x"},
        )
        self.assertEqual(filters, {"ano": 2026, "placa": "ABC1D23"})

    def test_decimal_days_are_shown_as_days_plus_extra_hours(self):
        self.assertEqual(dashboard._format_days_hours(1.3), "1 dia + 7 horas")
        self.assertEqual(dashboard._format_days_hours(2.0), "2 dias")
        self.assertEqual(dashboard._format_days_hours(0.5), "12 horas")

        gauge = dashboard._route_gauge(
            1.3,
            "Dias para entregar",
            maximum=3,
            target=1,
            inverse=True,
            display_text=dashboard._format_days_hours(1.3),
            reference_text=f"Referência: {dashboard._format_days_hours(1)}",
        )
        annotations = [annotation["text"] for annotation in gauge.layout.annotations]
        self.assertIn("<b>1 dia + 7 horas</b>", annotations)
        self.assertIn("Referência: 1 dia", annotations)

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

        city_context = dashboard._route_gauge_context_html(
            [("Maior volume", "CARMO DO CAJURU")],
            value=526,
            target=5,
            inverse=False,
            positive_text="Acima da mediana",
            attention_text="Abaixo da mediana",
        )
        city_gauge = dashboard._route_gauge(
            526, "Maior cidade", maximum=632, target=5, suffix=" ent."
        )
        self.assertIn("Acima da mediana", city_context)
        self.assertEqual(city_gauge.data[0]["number"]["valueformat"], ".0f")
        self.assertEqual(city_gauge.data[0]["number"]["suffix"], " ent.")

        density_gauge = dashboard._route_gauge(
            0.0684, "Entregas por KM", maximum=1, target=0.09, suffix=" ent/km"
        )
        self.assertEqual(density_gauge.data[0]["number"]["valueformat"], ".2f")
        self.assertIn("0,09 ent/km", density_gauge.layout.annotations[0]["text"])

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

        plates = dashboard._route_ranking_indicator_frame(
            [{"PLACA": "AAA1A11", "Pontuacao": 90.0}], entity_column="PLACA"
        )
        routes = dashboard._route_ranking_indicator_frame(
            [{"Rota": "ROTA TESTE", "Pontuacao": 70.0}], entity_column="Rota"
        )
        cities = dashboard._route_ranking_indicator_frame(
            [
                {"Cidade": "MAIOR", "Entregas": 100},
                {"Cidade": "MENOR", "Entregas": 25},
            ],
            entity_column="Cidade",
            volume=True,
        )
        self.assertIn("🟩", plates.iloc[0]["Indicador"])
        self.assertIn("🟨", routes.iloc[0]["Indicador"])
        self.assertIn("Muito alto", cities.iloc[0]["Indicador"])
        self.assertIn("Baixo", cities.iloc[1]["Indicador"])

    def test_route_staff_image_uses_second_date_and_matches_existing_route(self):
        def box(center_x, center_y, width=80, height=16):
            return [
                [center_x - width / 2, center_y - height / 2],
                [center_x + width / 2, center_y - height / 2],
                [center_x + width / 2, center_y + height / 2],
                [center_x - width / 2, center_y + height / 2],
            ]

        texts = [
            "CARREGAMENTOS: sexta-feira, 9 de outubro de 2026",
            "ROTAS: terça-feira, 13 de outubro de 2026",
            "Nº ROTA", "PLACAS", "MOTORISTA", "OBSS.",
            "10", "HAM-3C53", "DIVINÓPOLIS", "RONALDO PEREIRA", "CAIQUE LACERDA DOS SANTOS",
        ]
        positions = [
            (520, 25), (520, 55), (40, 95), (150, 95), (520, 95), (930, 95),
            (40, 135), (150, 135), (300, 135), (520, 135), (760, 135),
        ]
        ocr = {
            "text": "\n".join(texts),
            "width": 1000,
            "height": 400,
            "detections": [
                {"text": text, "box": box(x, y), "score": 0.99}
                for text, (x, y) in zip(texts, positions)
            ],
        }
        route_date, parsed = dashboard._parse_route_collaborator_ocr(ocr)
        self.assertEqual(route_date, date(2026, 10, 13))
        self.assertEqual(parsed[0]["Nº rota"], "10")
        self.assertEqual(parsed[0]["PLACA lida"], "HAM3C53")
        self.assertEqual(parsed[0]["Ajudante"], "CAIQUE LACERDA DOS SANTOS")

        routes = pd.DataFrame(
            [
                {
                    "Rota ID": "route-10", "Codigo Rota": "10", "Rota": "10 - DIVINOPOLIS",
                    "PLACA": "HAM3C53", "Data": "2026-10-14", "Previsao": "2026-10-14",
                    "Emissao": "2026-10-13", "Saida": None, "Status": "Concluída",
                    "Motorista": "ANTIGO", "Ajudante": "",
                }
            ]
        )
        matched = dashboard._match_route_collaborators(parsed, routes)
        self.assertEqual(matched[0]["Correspondência"], "Encontrada")
        self.assertEqual(matched[0]["Rota ID"], "route-10")
        self.assertEqual(matched[0]["Status atual"], "Concluída")

    def test_route_staff_image_removes_observation_joined_to_helper_name(self):
        def box(center_x, center_y, width=80, height=16):
            return [
                [center_x - width / 2, center_y - height / 2],
                [center_x + width / 2, center_y - height / 2],
                [center_x + width / 2, center_y + height / 2],
                [center_x - width / 2, center_y + height / 2],
            ]

        texts = [
            "CARREGAMENTOS: sexta-feira, 9 de outubro de 2026",
            "ROTAS: terça-feira, 13 de outubro de 2026",
            "Nº ROTA", "PLACAS", "MOTORISTA", "OBSS.",
            "30", "NYC6H24", "ITAGUARA 2", "RICARDO DE OLIVEIRA",
            "GABRIEL ENRIQUE DE SOUZA CARVALHO ROTA 2 DIAS",
        ]
        positions = [
            (520, 25), (520, 55), (40, 95), (150, 95), (520, 95), (930, 95),
            (40, 135), (150, 135), (300, 135), (520, 135), (760, 135),
        ]
        ocr = {
            "text": "\n".join(texts),
            "width": 1000,
            "height": 400,
            "detections": [
                {"text": text, "box": box(x, y), "score": 0.99}
                for text, (x, y) in zip(texts, positions)
            ],
        }

        _, parsed = dashboard._parse_route_collaborator_ocr(ocr)

        self.assertEqual(parsed[0]["Motorista"], "RICARDO DE OLIVEIRA")
        self.assertEqual(parsed[0]["Ajudante"], "GABRIEL ENRIQUE DE SOUZA CARVALHO")

    def test_collaborator_ranking_includes_driver_and_helper(self):
        source = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Rota": "ROTA 1", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Entregas": 10, "Peso Carga": 5000, "KM Rodados": 100, "Tempo Viagem Horas": 10,
                    "Horas Trabalhadas": 8, "Dias Rota": 1, "_Qualidade": 100,
                }
            ]
        )
        ranking = backend._route_collaborator_ranking(source)
        self.assertEqual(set(ranking["Colaborador"]), {"MOTORISTA A", "AJUDANTE B"})
        roles = ranking.set_index("Colaborador")["Função"].to_dict()
        self.assertEqual(roles["MOTORISTA A"], "Motorista")
        self.assertEqual(roles["AJUDANTE B"], "Ajudante")

    def test_collaborator_daily_alerts_sum_day_and_do_not_duplicate_overlapping_routes(self):
        source = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-13", "Rota": "ROTA 10", "Carga": "1001",
                    "PLACA": "AAA1A11", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Saida": "2026-10-13 07:00", "Retorno": "2026-10-13 15:00",
                    "Horas Trabalhadas": 8,
                },
                {
                    "Rota ID": "r2", "Data": "2026-10-13", "Rota": "ROTA 11", "Carga": "1002",
                    "PLACA": "AAA1A11", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Saida": "2026-10-13 07:00", "Retorno": "2026-10-13 15:00",
                    "Horas Trabalhadas": 8,
                },
            ]
        )

        alerts = backend._route_collaborator_daily_alerts(source)

        self.assertEqual(set(alerts["Colaborador"]), {"MOTORISTA A", "AJUDANTE B"})
        self.assertTrue(alerts["Horas cumpridas"].eq(8.0).all())
        self.assertTrue(alerts["Horas faltantes"].eq(1.0).all())
        self.assertTrue(alerts["Quantidade de rotas"].eq(2).all())
        self.assertTrue(alerts["Rotas"].str.contains("ROTA 10").all())
        self.assertTrue(alerts["Rotas"].str.contains("ROTA 11").all())

    def test_collaborator_daily_alerts_use_each_multiday_journey(self):
        journeys = json.dumps(
            [
                {"saida": "2026-10-13T07:00:00", "parada": "2026-10-13T17:00:00"},
                {"saida": "2026-10-14T08:00:00", "parada": "2026-10-14T16:00:00"},
            ]
        )
        source = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-13", "Rota": "ROTA 10", "Carga": "1001",
                    "PLACA": "AAA1A11", "Motorista": "MOTORISTA A", "Ajudante": "",
                    "Jornadas": journeys, "Horas Trabalhadas": 18,
                }
            ]
        )

        alerts = backend._route_collaborator_daily_alerts(source)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(pd.to_datetime(alerts.iloc[0]["Data"]).date(), date(2026, 10, 14))
        self.assertEqual(alerts.iloc[0]["Horas cumpridas"], 8.0)

    def test_collaborator_performance_supports_total_individual_weekly_and_monthly(self):
        rows = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-05", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Entregas": 10, "Peso Carga": 5000, "KM Rodados": 100, "Horas Trabalhadas": 10,
                },
                {
                    "Rota ID": "r2", "Data": "2026-10-07", "Motorista": "MOTORISTA C", "Ajudante": "AJUDANTE B",
                    "Entregas": 8, "Peso Carga": 3000, "KM Rodados": 80, "Horas Trabalhadas": 8,
                },
                {
                    "Rota ID": "r3", "Data": "2026-10-14", "Motorista": "MOTORISTA A", "Ajudante": "",
                    "Entregas": 12, "Peso Carga": 6000, "KM Rodados": 120, "Horas Trabalhadas": 10,
                },
            ]
        )

        total_weekly = dashboard._route_collaborator_performance_frame(rows, cadence="Semanal")
        helper_weekly = dashboard._route_collaborator_performance_frame(
            rows, collaborator="AJUDANTE B", cadence="Semanal"
        )
        driver_monthly = dashboard._route_collaborator_performance_frame(
            rows, collaborator="MOTORISTA A", cadence="Mensal"
        )

        self.assertEqual(len(total_weekly), 2)
        self.assertEqual(total_weekly["Rotas"].sum(), 3)
        self.assertEqual(len(helper_weekly), 1)
        self.assertEqual(helper_weekly.iloc[0]["Entregas"], 18)
        self.assertEqual(helper_weekly.iloc[0]["Entregas por hora"], 1.0)
        self.assertEqual(len(driver_monthly), 1)
        self.assertEqual(driver_monthly.iloc[0]["Rotas"], 2)
        self.assertEqual(driver_monthly.iloc[0]["Peso transportado (t)"], 11.0)

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

    def test_route_profitability_states_if_route_paid_for_itself(self):
        paid = dashboard._route_profitability_snapshot(
            pd.DataFrame(
                [
                    {"Rota ID": "r1", "Custo total": 700.0, "Ganho entregas": 1_000.0},
                    {"Rota ID": "r2", "Custo total": 100.0, "Ganho entregas": 200.0},
                ]
            )
        )
        loss = dashboard._route_profitability_snapshot(
            pd.DataFrame([{"Rota ID": "r3", "Custo total": 1_200.0, "Ganho entregas": 900.0}])
        )
        self.assertTrue(paid["se_pagou"])
        self.assertEqual(paid["situacao"], "Se pagou")
        self.assertAlmostEqual(float(paid["resultado"]), 400.0)
        self.assertFalse(loss["se_pagou"])
        self.assertEqual(loss["situacao"], "Não se pagou")
        self.assertAlmostEqual(float(loss["resultado"]), -300.0)

    def test_unprofitable_trips_are_listed_from_biggest_loss(self):
        losses = dashboard._route_unprofitable_trips(
            dashboard._route_financial_frame(sample_payload())
        )
        self.assertEqual(losses["Rota"].tolist(), ["ROTA CARA"])
        self.assertAlmostEqual(float(losses.iloc[0]["Faltou para se pagar"]), 1_000.0)
        self.assertAlmostEqual(float(losses.iloc[0]["Custo/receita %"]), 116.666666, places=4)

    def test_operational_map_uses_real_city_metrics_and_known_coordinates(self):
        cities = dashboard._route_city_map_frame(
            {
                "ranking_cidades": [
                    {"Cidade": "Divinópolis - MG", "Rotas": 3, "Entregas": 12, "Peso kg": 5000, "Valor Notas": 9000},
                    {"Cidade": "Uberlândia - MG", "Rotas": 2, "Entregas": 5, "Peso kg": 1000, "Valor Notas": 2500},
                    {"Cidade": "Cidade sem cadastro", "Rotas": 1, "Entregas": 2, "Peso kg": 200, "Valor Notas": 500},
                ]
            }
        )
        mapped = cities.set_index("Cidade")["Localizada"].to_dict()
        self.assertTrue(mapped["Divinópolis - MG"])
        self.assertTrue(mapped["Uberlândia - MG"])
        self.assertFalse(mapped["Cidade sem cadastro"])
        self.assertEqual(float(cities["Entregas"].sum()), 19.0)
        self.assertTrue(dashboard.MAP_PLOTLY_CONFIG["scrollZoom"])

    def test_weekly_forecast_and_cost_explanation_use_completed_weeks(self):
        weeks = pd.date_range("2026-09-14", periods=6, freq="7D")
        data = {
            "tempos_rotas": [
                {"Rota ID": f"r{index}", "Data": week, "Entregas": 10 + index, "KM Rodados": 100 + index * 10}
                for index, week in enumerate(weeks)
            ]
        }
        financial = pd.DataFrame(
            [
                {
                    "Rota ID": f"r{index}", "Data": week, "Custo total": 1000 + index * 100,
                    "Combustivel": 600 + index * 80, "Manutencao": 100 + index * 20,
                    "Pedagio": 100, "Hoteis": 100, "Salarios": 100, "Freteiro": 0,
                }
                for index, week in enumerate(weeks)
            ]
        )
        weekly = dashboard._route_weekly_history(data, financial, today=pd.Timestamp("2026-10-27"))
        forecast = dashboard._route_forecast(weekly)
        change = dashboard._route_cost_change_snapshot(financial, today=pd.Timestamp("2026-10-27"))
        self.assertEqual(len(weekly), 6)
        self.assertEqual(len(forecast), 12)
        self.assertEqual(set(forecast["Métrica"]), {"Entregas", "KM", "Custos"})
        self.assertTrue(change["disponivel"])
        self.assertAlmostEqual(float(change["variacao"]), 100.0)
        self.assertEqual(change["contribuicoes"][0]["Categoria"], "Combustível")

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
